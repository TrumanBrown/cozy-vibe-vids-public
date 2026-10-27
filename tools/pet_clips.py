"""Pet behavior clips: the scene's sleeping pet wakes, looks around, sits up, grooms, lies back down.

RETIRED for pets (user 2026-10-18, DECISIONS): generated video of a pet painted into the key art looked eerie,
jerky, unclear and obviously AI, however well it was matted and color-fit. A painted pet only breathes; a pet
that moves must be a fully rendered 3D model or a library asset animated in code. tools/new_video.py no longer
runs this, and no scene may add a 'pet' layer or events.petAct. Its model loader (load_pipe, VaeShuttle, MODEL),
which tools/fire_clips.py uses, is in tools/cozy/wan.py.

A still key art can only make a pet breathe. Real behavior (a head lifting, sitting up, lying back down) is
generated as short video clips of a crop around the pet with a local image-to-video model (Wan 2.2 TI2V-5B,
Apache-2.0, diffusers, runs on a 12 GB GPU with fp8 weight storage). The renderer (src/library/pet.js) plays
them over the plate as a motion graph: a clip forward from the plate's pose, held at a rest frame (with
breathing), and played backward to return exactly to the plate's pose; or forward to a rest frame and back
(a look around). Every join is exact, so nothing pops.

Usage (repo root):
  .venv/Scripts/python tools/pet_clips.py <scene> gen [--behavior wake|sit|...] [--n 2] [--steps 40] [--frames 121] [--seed 1]
  .venv/Scripts/python tools/pet_clips.py <scene> matte [--clip name]      # SAM 2.1 mattes + color fit + rest frames
  .venv/Scripts/python tools/pet_clips.py <scene> pick <clip> [<clip> ...]  # clips the renderer uses -> pet.json
  .venv/Scripts/python tools/pet_clips.py <scene> sheet                     # contact sheet of every clip

Outputs (gitignored): out/plates/<scene>/pet/<clip>/f_0000.png ... (RGBA, crop size), <clip>.mp4 previews,
clips.json (every generated clip: prompt, seed, motion profile) and pet.json (what the renderer plays).
Provenance of the clips used goes in docs/asset-ledger.csv (model, license, date).
"""
import argparse
import json
import os
import sys
import time

from cozy.paths import ROOT, config, load_scene, plate_dir, save_scene
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from cozy.media import run_ffmpeg  # noqa: E402
from cozy.models import revision  # noqa: E402  (pinned model revisions, TASKS.md T8)
from cozy.wan import MODEL, VaeShuttle, load_pipe  # noqa: E402  (TASKS.md T12)

FPS = 24
NEG = ("blurry, low quality, distorted, deformed, extra legs, extra tail, extra ears, morphing, flickering, camera movement, zoom, "
       "pan, shaky, text, watermark, people, hands, sudden change, jump cut, overexposed, color shift, changing colors, green tint, "
       "changing lighting, static, frozen, motionless")

# What each behavior asks for. {pet} = species + look, {pose} = the pose in the key art, {place} = what it rests on.
# Clear, concrete actions in order work best (the model otherwise keeps the pet nearly still).
BEHAVIORS = {
    "wake": ("A {pet} is asleep, {pose} on {place}. It slowly lifts its head up off its paws, opens its eyes, and turns its head to "
             "look around at the rainy street, blinking sleepily. Then it lowers its head back down onto its paws and closes its eyes. "
             "Natural, smooth cat movement."),
    "sit": ("A {pet} {pose} asleep on {place} wakes up, lifts its head, then gets up and sits upright on {place}: front legs straight, "
            "tail wrapped around its feet, ears up, calmly looking out at the rain. Natural, smooth, unhurried cat movement."),
    "groom": ("A {pet} {pose} on {place} lifts its head, licks its front paw a few times and wipes its face with it, then rests "
              "its head again. Natural, smooth cat movement."),
    "stretch": ("A {pet} {pose} on {place} stretches its front legs out long, spreads its toes, yawns widely, then settles back "
                "into the same position. Natural, smooth cat movement."),
}
STYLE = ("Static locked-off camera; the background, the light and the colors stay exactly the same as in the first frame. "
         "{style}, rainy night, warm lantern light.")


def pet_region(scene):
    regs = json.loads((plate_dir(scene) / "regions.json").read_text(encoding="utf-8"))
    pet = next((g for g in regs if g["kind"] == "pet"), None)
    if not pet:
        sys.exit(f"{scene}: no pet region in regions.json")
    return pet


def crop_box(bbox, size=(1280, 704), W=3840, H=2160, headroom=1.6):
    """Model-size crop (4K px) around the pet, centered across: its bottom just inside the crop and as much room
    above it as the crop allows, up to `headroom` x its height (a sitting cat is ~1.6x as tall as a curled one);
    any spare room is split above and below."""
    x0, y0, x1, y1 = bbox[0] * W, bbox[1] * H, bbox[2] * W, bbox[3] * H
    cw, ch = size
    cx = (x0 + x1) / 2
    anchored = y1 + 0.06 * ch - ch          # highest top that keeps the pet's bottom inside
    needed = y0 - headroom * (y1 - y0)
    top = anchored if anchored >= needed else needed - 0.5 * (needed - anchored)
    left = max(0, min(W - cw, cx - cw / 2))
    top = max(0, min(H - ch, top))
    return [int(round(left)), int(round(top)), cw, ch]


def encode_prompt(pipe, prompt):
    """umT5-XXL on the CPU (11 GB in bf16 does not fit next to the transformer on a 12 GB GPU)."""
    import torch
    with torch.no_grad():
        pe, ne = pipe.encode_prompt(prompt=prompt, negative_prompt=NEG, do_classifier_free_guidance=True, device=torch.device("cpu"))
    return pe.to("cuda", torch.bfloat16), ne.to("cuda", torch.bfloat16)


def describe(scene):
    brief = json.loads((ROOT / "scenes" / scene / "brief.json").read_text(encoding="utf-8"))
    ana_p = plate_dir(scene) / "analysis.json"
    ana = json.loads(ana_p.read_text(encoding="utf-8")) if ana_p.exists() else {}
    el = next((e for e in ana.get("elements", []) if e.get("kind") == "pet"), {})
    aes = config("aesthetics")["aesthetics"][brief["aesthetic"]]
    pet = el.get("look") or brief.get("pet") or "cat"
    return {"pet": el.get("look") or pet.split(" asleep")[0].split(" sleeping")[0].replace("a ", "", 1),
            "pose": el.get("pose") or "curled up", "place": el.get("place") or "a round wooden stool",
            "style": aes.get("style", "painted").replace("-", " ") + " painting"}


def save_frames(frames, out):
    out.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(out / f"f_{i:04d}.png")
    run_ffmpeg(["-v", "error", "-y", "-framerate", str(FPS), "-i", str(out / "f_%04d.png"), "-c:v", "libx264", "-crf", "16",
                "-pix_fmt", "yuv420p", str(out.parent / f"{out.name}.mp4")], capture=False)


def cmd_gen(a):
    import torch
    scene = a.scene
    pet = pet_region(scene)
    box = crop_box(pet["bbox"], (a.width, a.height))
    plate = Image.open(plate_dir(scene) / "plate.png").convert("RGB")
    x, y, w, h = box
    first = plate.crop((x, y, x + w, y + h))
    d = describe(scene)
    pdir = plate_dir(scene) / "pet"
    pdir.mkdir(parents=True, exist_ok=True)
    first.save(pdir / "first.png")
    log_p = pdir / "clips.json"
    log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else {"crop": box, "fps": FPS, "model": MODEL, "clips": {}}
    if log.get("crop") != box:
        print(f"  crop changed {log.get('crop')} -> {box}: older clips are kept but no longer match")
        log["crop"] = box
    t0 = time.time()
    pipe = load_pipe()
    VaeShuttle(pipe)
    print(f"model loaded in {time.time() - t0:.0f} s; crop {box}")
    for beh in a.behavior:
        prompt = BEHAVIORS[beh].format(**d) + " " + STYLE.format(**d)
        pe, ne = encode_prompt(pipe, prompt)
        for k in range(a.n):
            seed = a.seed + k
            name = f"{beh}_{seed}"
            t1 = time.time()
            g = torch.Generator("cuda").manual_seed(seed)
            res = pipe(image=first, prompt_embeds=pe, negative_prompt_embeds=ne, height=h, width=w, num_frames=a.frames,
                       guidance_scale=a.cfg, num_inference_steps=a.steps, generator=g, output_type="pil")
            frames = res.frames[0]
            save_frames(frames, pdir / name)
            log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else log
            log["clips"][name] = {"behavior": beh, "seed": seed, "prompt": prompt, "frames": len(frames), "steps": a.steps,
                                  "cfg": a.cfg, "s": round(time.time() - t1), "date": time.strftime("%Y-%m-%d"), "crop": box}
            log_p.write_text(json.dumps(log, indent=1), encoding="utf-8")
            print(f"  {name}: {len(frames)} frames in {time.time() - t1:.0f} s -> {pdir / (name + '.mp4')}", flush=True)
    del pipe
    torch.cuda.empty_cache()


# ---------------------------------------------------------------- matte, color fit, rest frames

def frame_paths(clip_dir):
    return sorted(clip_dir.glob("f_*.png"))


def sam_candidates(seg, img, box):
    """SAM 2.1's three mask candidates for a box prompt (bool, n x H x W) and their predicted IoUs."""
    torch = seg.torch
    inp = seg.proc(images=img, input_boxes=[[list(map(float, box))]], return_tensors="pt").to("cuda")
    with torch.no_grad():
        res = seg.model(**inp, multimask_output=True)
    ms = seg.proc.post_process_masks(res.pred_masks.cpu(), inp["original_sizes"])[0][0].numpy().astype(bool)
    return ms, res.iou_scores.cpu().numpy()[0][0]


def mask_iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum()) / u if u else 0.0


def track_masks(seg, frames, m0, W, H):
    """The pet's mask in every frame: SAM 2.1's video predictor (memory of earlier frames, so it follows the pet
    through big pose changes), prompted with the plate's own pet mask on frame 0. `seg` is unused (kept for the
    call signature); the video model is loaded here and freed after."""
    import torch
    from transformers import Sam2VideoModel, Sam2VideoProcessor
    from cozy.segment import SAM_MODEL
    proc = Sam2VideoProcessor.from_pretrained(SAM_MODEL, revision=revision(SAM_MODEL))
    model = Sam2VideoModel.from_pretrained(SAM_MODEL, revision=revision(SAM_MODEL)).to("cuda", dtype=torch.bfloat16).eval()
    with torch.no_grad():
        sess = proc.init_video_session(video=[np.asarray(f) for f in frames], inference_device="cuda", dtype=torch.bfloat16)
        ys, xs = np.nonzero(m0)
        box = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
        # a box around the plate's pet plus a positive point on its body (the mask's most interior pixel)
        import cv2
        dist = cv2.distanceTransform(m0.astype(np.uint8), cv2.DIST_L2, 5)
        py, px = np.unravel_index(np.argmax(dist), dist.shape)
        proc.add_inputs_to_inference_session(inference_session=sess, frame_idx=0, obj_ids=1, input_boxes=[[box]],
                                             input_points=[[[[float(px), float(py)]]]], input_labels=[[[1]]])
        model(inference_session=sess, frame_idx=0)
        out = {}
        for o in model.propagate_in_video_iterator(sess):
            m = proc.post_process_masks([o.pred_masks], original_sizes=[[H, W]], binarize=True)[0]
            out[o.frame_idx] = np.asarray(m.reshape(-1, H, W)[0].cpu().numpy()).astype(bool)
    del model, sess
    torch.cuda.empty_cache()
    masks = [out.get(i) for i in range(len(frames))]
    for i in range(len(masks)):          # any frame it could not track keeps the previous mask
        if masks[i] is None or masks[i].sum() < 0.3 * m0.sum():
            masks[i] = masks[i - 1] if i else m0
    return masks


def color_fits(frames, plate, bg, n_iter=2):
    """Per-frame affine color transform (3x4) mapping the frame to the plate on static background pixels: undoes
    the video model's slow color drift. Smoothed over +-4 frames so it cannot flicker."""
    import cv2
    P = np.asarray(plate, np.float32) / 255
    ys, xs = np.nonzero(bg)
    sel = np.arange(0, len(xs), max(1, len(xs) // 60000))
    ys, xs = ys[sel], xs[sel]
    tgt = P[ys, xs]
    fits = []
    for fr in frames:
        F = np.asarray(fr, np.float32)[ys, xs] / 255
        X = np.concatenate([F, np.ones((len(F), 1), np.float32)], 1)
        keep = np.ones(len(F), bool)
        for _ in range(n_iter):
            A, *_ = np.linalg.lstsq(X[keep], tgt[keep], rcond=None)
            r = np.abs(X @ A - tgt).max(1)
            keep = r < max(0.04, np.percentile(r, 85))
        fits.append(A)
    fits = np.stack(fits)
    sm = np.stack([fits[max(0, i - 4): i + 5].mean(0) for i in range(len(fits))])
    del cv2
    return sm


def apply_fit(fr, A):
    F = np.asarray(fr, np.float32) / 255
    out = F @ A[:3] + A[3]
    return np.clip(out, 0, 1)


def cmd_matte(a):
    import cv2
    from cozy.segment import Segmenter
    scene = a.scene
    pdir = plate_dir(scene) / "pet"
    log = json.loads((pdir / "clips.json").read_text(encoding="utf-8"))
    names = a.clip or [n for n in log["clips"] if not (pdir / n / "matte.json").exists() or a.force]
    if not names:
        print("nothing to matte")
        return
    pet = pet_region(scene)
    seg = Segmenter()
    plate = Image.open(plate_dir(scene) / "plate.png").convert("RGB")
    for name in names:
        info = log["clips"][name]
        x, y, w, h = info.get("crop", log["crop"])
        pc = plate.crop((x, y, x + w, y + h))
        P = np.asarray(pc, np.float32) / 255
        paths = frame_paths(pdir / name)
        frames = [Image.open(p).convert("RGB") for p in paths]
        reg = np.asarray(Image.open(plate_dir(scene) / "regions.png").convert("RGB"))[..., 0]
        m0 = reg[y:y + h, x:x + w] == pet["id"]
        t0 = time.time()
        masks = track_masks(seg, frames, m0, w, h)
        # the plate's own pet is covered for the whole act too, so nothing of it can peek out (plate.js also
        # stops its breathing during acts)
        env = np.any(np.stack(masks), 0) | m0
        k = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        envd = cv2.dilate(env.astype(np.uint8), k(28)) > 0
        fits = color_fits(frames, pc, ~cv2.dilate(env.astype(np.uint8), k(40)).astype(bool))
        # alpha: the pet now + what changed around it (shadows, the stool it uncovers) + the plate's pet, inside
        # the envelope; held over +-2 frames and feathered so it cannot flicker
        raw = []
        diff0, motion, prev = [], [], None
        cor = []
        for i, fr in enumerate(frames):
            c = apply_fit(fr, fits[i])
            cor.append(c)
            ch = (np.abs(c - P).max(-1) > 0.07) & envd
            ch = cv2.morphologyEx(ch.astype(np.uint8), cv2.MORPH_OPEN, k(2)) > 0
            raw.append(cv2.dilate(masks[i].astype(np.uint8), k(5)).astype(bool) | ch | m0)
            em = envd
            diff0.append(float(np.abs(c - cor[0])[em].mean()))
            motion.append(float(np.abs(c - prev)[em].mean()) if prev is not None else 0.0)
            prev = c
        al = []
        for i in range(len(frames)):
            m = np.any(np.stack(raw[max(0, i - 2): i + 3]), 0).astype(np.float32)
            m = cv2.GaussianBlur(cv2.dilate(m, k(3)), (0, 0), 3.0)
            al.append(np.clip(m * 1.3, 0, 1) * envd)
        A = np.stack(al)
        ys, xs = np.nonzero(A.max(0) > 0.01)
        bx0, by0, bx1, by1 = max(0, xs.min() - 6), max(0, ys.min() - 6), min(w, xs.max() + 7), min(h, ys.max() + 7)
        out = pdir / name / "rgba"
        out.mkdir(exist_ok=True)
        for f in out.glob("a_*.png"):
            f.unlink()
        prev_frames = []
        for i in range(len(frames)):
            rgba = np.concatenate([cor[i][by0:by1, bx0:bx1], A[i][by0:by1, bx0:bx1, None]], -1)
            Image.fromarray((rgba * 255).round().astype(np.uint8), "RGBA").save(out / f"a_{i:04d}.png")
            comp = cor[i] * A[i][..., None] + P * (1 - A[i][..., None])
            prev_frames.append(Image.fromarray((comp * 255).round().astype(np.uint8)))
        cdir = pdir / name / "comp"
        cdir.mkdir(exist_ok=True)
        for i, im in enumerate(prev_frames):
            im.save(cdir / f"c_{i:04d}.jpg", quality=90)
        run_ffmpeg(["-v", "error", "-y", "-framerate", str(FPS), "-i", str(cdir / "c_%04d.jpg"), "-c:v", "libx264", "-crf", "17",
                    "-pix_fmt", "yuv420p", str(pdir / f"{name}_comp.mp4")], capture=False)
        # rest frame (the turnaround of the act): where the pet's silhouette differs most from the plate's pose, i.e.
        # the head fully up or the cat sitting; on a plateau (sitting) the first frame that reaches it. Measured on
        # the masks, not on colors (the video model's background drifts slowly and would win otherwise).
        n = len(frames)
        sil = np.array([1.0 - mask_iou(masks[i], masks[0]) for i in range(n)])
        sil_s = np.convolve(np.pad(sil, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        lo, hi = int(0.15 * n), int(0.9 * n)
        peak = float(sil_s[lo:hi].max())
        rest = int(lo + np.flatnonzero(sil_s[lo:hi] >= 0.92 * peak)[0])
        d0, mo = np.array(diff0), np.array(motion)
        # the pet at its rest frame (4K px) for breathing while it holds there
        ys2, xs2 = np.nonzero(masks[rest])
        hold_bbox = [int(xs2.min() + x), int(ys2.min() + y), int(xs2.max() + x), int(ys2.max() + y)] if len(xs2) else None
        mj = {"box": [int(x + bx0), int(y + by0), int(bx1 - bx0), int(by1 - by0)], "frames": n, "rest": rest, "hold_bbox": hold_bbox,
              "pose_change": round(float(sil_s.max()), 4), "pose_change_at_rest": round(float(sil_s[rest]), 4),
              "silhouette": [round(float(v), 4) for v in sil.tolist()],
              "motion": [round(v, 4) for v in mo.tolist()], "diff0": [round(v, 4) for v in d0.tolist()],
              "drift_fit": [[round(float(v), 4) for v in fits[-1].ravel()]]}
        (pdir / name / "matte.json").write_text(json.dumps(mj, indent=1), encoding="utf-8")
        print(f"  {name}: matte in {time.time() - t0:.0f} s, box {mj['box']}, rest frame {rest}/{n}, pose change {mj['pose_change']:.3f}"
              f" (at rest {mj['pose_change_at_rest']:.3f}) -> {pdir / (name + '_comp.mp4')}", flush=True)


def act_for(name, mj, behavior):
    """Default act for a clip (named after it): look around = forward to the rest frame and back (short hold);
    sit = up to the rest frame (sitting), a hold with small idle movements, and back down."""
    if behavior == "sit":
        return {"name": name, "clip": name, "to": mj["rest"], "hold": [10, 30], "idle": 5, "idlePeriod": 8, "weight": 1}
    if behavior == "groom":
        return {"name": name, "clip": name, "to": mj["rest"], "hold": [0.5, 2], "weight": 1}
    return {"name": name, "clip": name, "to": mj["rest"], "hold": [1.2, 3.5], "idle": 3, "idlePeriod": 5, "weight": 2}


def cmd_pick(a):
    """Write out/plates/<scene>/pet/pet.json from the chosen clips and add the pet layer + petAct events to
    scenes/<scene>/scene.json."""
    scene = a.scene
    pdir = plate_dir(scene) / "pet"
    log = json.loads((pdir / "clips.json").read_text(encoding="utf-8"))
    clips, acts = {}, []
    for name in a.clips:
        mj = json.loads((pdir / name / "matte.json").read_text(encoding="utf-8"))
        clips[name] = {"frames": mj["frames"], "box": mj["box"], "dir": f"{name}/rgba", "hold_bbox": mj["hold_bbox"]}
        act = act_for(name, mj, log["clips"][name]["behavior"])
        if a.rest and name in a.rest:
            act["to"] = int(a.rest[name])
        acts.append(act)
    pet = {"fps": log.get("fps", FPS), "model": log.get("model"), "clips": clips, "acts": acts,
           "_note": "tools/pet_clips.py pick; played by src/library/pet.js"}
    (pdir / "pet.json").write_text(json.dumps(pet, indent=1), encoding="utf-8")
    spec = load_scene(scene)
    spec["layers"] = [L for L in spec.get("layers", []) if L.get("type") != "pet"] + [{"type": "pet"}]
    fps = pet["fps"]
    longest = max(2 * x["to"] / fps + x["hold"][1] for x in acts)
    spec.setdefault("events", {})["petAct"] = {
        "perHour": a.per_hour, "minGap": round(longest + 45), "startAfter": a.start_after, "first": 20,
        "acts": [{"name": x["name"], "weight": x["weight"], "dur": round(2 * x["to"] / fps, 3), "hold": x["hold"]} for x in acts]}
    save_scene(scene, spec)
    print(f"pet.json: {len(acts)} acts ({', '.join(x['name'] for x in acts)}); scene.json: pet layer + petAct {a.per_hour}/h")


def cmd_sheet(a):
    pdir = plate_dir(a.scene) / "pet"
    for d in sorted(p for p in pdir.iterdir() if p.is_dir() and (p / "comp").exists()):
        cs = sorted((d / "comp").glob("c_*.jpg"))
        idx = np.linspace(0, len(cs) - 1, 8).round().astype(int)
        ims = [Image.open(cs[i]) for i in idx]
        w, h = ims[0].size
        s = 480 / w
        tw, th = int(w * s), int(h * s)
        sheet = Image.new("RGB", (tw * 4, th * 2))
        for k, im in enumerate(ims):
            sheet.paste(im.resize((tw, th), Image.LANCZOS), ((k % 4) * tw, (k // 4) * th))
        sheet.save(pdir / f"{d.name}_sheet.jpg", quality=88)
        print(pdir / f"{d.name}_sheet.jpg")


def score_clip(scene, name):
    """Vision check of a matted clip's composite contact sheet: does the pet do the behavior and look natural?"""
    from azure_ai import vision_json
    pdir = plate_dir(scene) / "pet"
    sheet = pdir / f"{name}_sheet.jpg"
    if not sheet.exists():
        cmd_sheet(argparse.Namespace(scene=scene))
    beh = json.loads((pdir / "clips.json").read_text(encoding="utf-8"))["clips"][name]["behavior"]
    what = {"wake": "lift its head, open its eyes and look around", "sit": "wake up and sit upright", "groom": "lick its paw and wash its face",
            "stretch": "stretch its front legs and yawn"}.get(beh, beh)
    res, usage = vision_json(
        "These 8 frames (left to right, top to bottom) are from a short clip of an animal in a painted scene; the clip is "
        f"meant to show it: {what}. "
        "Rate it for use in a calm ambience video. Return JSON {\"does_action\": 0-10 (clearly does the behavior), \"natural\": 0-10 "
        "(anatomy stays correct, no morphing, extra limbs, melting or flicker), \"consistent\": 0-10 (same animal, colors and style "
        "throughout), \"problem\": \"...\"}", images=[sheet], purpose=f"petclip:{scene}:{name}", effort="low")
    return res


def cmd_auto(a):
    """Generate (if needed), matte and rank clips per behavior; pick the best of each into pet.json + scene.json."""
    scene = a.scene
    pdir = plate_dir(scene) / "pet"
    log_p = pdir / "clips.json"
    log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else {"clips": {}}
    want = {"wake": (97, 11), "sit": (121, 21)}
    for beh, (frames, seed) in want.items():
        have = [n for n, c in log["clips"].items() if c["behavior"] == beh]
        if len(have) < a.n:
            cmd_gen(argparse.Namespace(scene=scene, behavior=[beh], n=a.n - len(have), seed=seed + len(have), steps=30, frames=frames,
                                       cfg=5.5, width=1280, height=704))
    log = json.loads(log_p.read_text(encoding="utf-8"))
    cmd_matte(argparse.Namespace(scene=scene, clip=None, force=False))
    cmd_sheet(argparse.Namespace(scene=scene))
    best = {}
    for name, c in log["clips"].items():
        mj = json.loads((pdir / name / "matte.json").read_text(encoding="utf-8"))
        sc = score_clip(scene, name)
        total = sc.get("does_action", 0) + 1.5 * sc.get("natural", 0) + sc.get("consistent", 0) + 20 * min(mj["pose_change_at_rest"], 0.25)
        print(f"  {name}: {sc} pose {mj['pose_change_at_rest']:.3f} -> {total:.1f}")
        c["score"] = {**sc, "total": round(total, 2)}
        if sc.get("natural", 0) >= 6 and sc.get("does_action", 0) >= 4 and total > best.get(c["behavior"], ("", -1))[1]:
            best[c["behavior"]] = (name, total)
    log_p.write_text(json.dumps(log, indent=1), encoding="utf-8")
    if not best:
        sys.exit("no usable clip: generate more candidates (gen --seed ...) and check the *_sheet.jpg sheets")
    # the best of each behavior, plus any other clip close behind it (more variety over 10 hours)
    picks = [n for n, _ in best.values()]
    for name, c in log["clips"].items():
        sc = c.get("score") or {}
        if name not in picks and sc.get("natural", 0) >= 7 and sc.get("does_action", 0) >= 6 and sc.get("total", 0) >= best[c["behavior"]][1] - 3:
            picks.append(name)
    cmd_pick(argparse.Namespace(scene=scene, clips=picks, rest=None, per_hour=a.per_hour, start_after=a.start_after))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--behavior", action="append", choices=list(BEHAVIORS))
    g.add_argument("--n", type=int, default=1)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--steps", type=int, default=30)
    g.add_argument("--frames", type=int, default=97)
    g.add_argument("--cfg", type=float, default=5.5)
    g.add_argument("--width", type=int, default=1280)
    g.add_argument("--height", type=int, default=704)
    m = sub.add_parser("matte")
    m.add_argument("--clip", action="append")
    m.add_argument("--force", action="store_true")
    p = sub.add_parser("pick")
    p.add_argument("clips", nargs="+")
    p.add_argument("--rest", type=json.loads, help='override rest frames: {"wake_11": 50}')
    p.add_argument("--per-hour", type=float, default=6)
    p.add_argument("--start-after", type=float, default=20)
    sub.add_parser("sheet")
    u = sub.add_parser("auto")
    u.add_argument("--n", type=int, default=2)
    u.add_argument("--per-hour", type=float, default=6)
    u.add_argument("--start-after", type=float, default=20)
    a = ap.parse_args()
    if a.cmd == "gen":
        a.behavior = a.behavior or ["wake", "sit"]
    {"gen": cmd_gen, "matte": cmd_matte, "pick": cmd_pick, "sheet": cmd_sheet, "auto": cmd_auto}[a.cmd](a)


if __name__ == "__main__":
    main()
