"""Live fire from the key art itself: the painted fire animated by a local image-to-video model.

Flames drawn in code read as icons or a flat glowing band next to a painting. A video model knows how fire
moves and keeps the painting's style, so the fireplace of the ORIGINAL key art (with its painted fire) is
animated into short clips (Wan 2.2 TI2V-5B, Apache-2.0, local, ~10 min of GPU per 4 s clip; the same model as
tools/pet_clips.py). The clips are color-matched to the plate and cut to the fire: a feathered mask over the
fire region and the area tools/plate_clean.py repainted when it took the painted flames out. The renderer
(src/library/fire.js) plays them as an endless walk: runs of 1.2 to 3 s, each ending in a jump to a frame that
looks like the next one would have (the "video textures" idea), with a short crossfade. The fire never loops
visibly and never cuts.

Usage (repo root):
  .venv/Scripts/python tools/fire_clips.py <scene> gen [--n 2] [--seed 1] [--steps 30] [--frames 97]
  .venv/Scripts/python tools/fire_clips.py <scene> loop       # color fit, mask, transitions -> fire.json
  .venv/Scripts/python tools/fire_clips.py <scene> auto       # gen until --n clips move the fire's center (core flow), loop
  .venv/Scripts/python tools/fire_clips.py <scene> sheet      # contact sheet of every clip

Outputs (gitignored), out/plates/<scene>/fire/: src_plate.png (the original key art at plate geometry),
first.png (the model's input), <clip>.mp4 + <clip>/f_0000.png (raw clips), clips.json (prompts, seeds),
<clip>/c_0000.jpg (color-fitted frames, crop size), alpha.png (the mask), fire.json (what fire.js plays),
sheet.jpg. The clips go in docs/asset-ledger.csv (model, license, date) like the pet's.
"""
import argparse
import json
import os
import sys
import time

from cozy.paths import ROOT, load_json, plate_dir
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from cozy.media import run_ffmpeg  # noqa: E402

FPS = 24
LO = 6            # the first frames stay close to the still input: the walk never uses them
XFADE = 12        # crossfade frames at a jump (0.5 s: fire tolerates a slow blend better than a quick pop)
RUN = (1.2, 3.0)  # seconds between jumps (fire.js)
MIN_SCALE = 0.55  # a small fire is cropped tighter and upscaled for the model (up to 1.8x), so it fills the frame
CORE_MIN = 1.6    # least core flow a clip needs (core_flow): the fire's bright center must move, not only its licks
FIRE_PROMPT = ("A wood fire burns steadily in this painting ({what}). The whole fire is alive, its bright center most of all: "
               "the glowing heart of the flames churns and rises without pause, tongues of flame form in the middle, stretch "
               "upward, split and vanish, so no part of the flames ever holds still. Lively flames flicker and lick upward from "
               "the logs, their tips curl, split and fade, glowing embers pulse under them and a few small sparks rise. The fire "
               "keeps the same size the whole time, never dying down or flaring up. Static locked-off camera: the stones, the "
               "logs, the mantel and the room stay exactly the same and do not move; only the flames and their light move. {style}.")
FIRE_NEG = ("camera movement, zoom, pan, shaky, morphing, logs moving, objects moving, room changing, people, hands, animals, text, "
            "watermark, blurry, low quality, color shift, changing colors, overexposed, fire going out, fire spreading, explosion, "
            "thick smoke, jump cut, static, frozen, motionless")


def fire_dir(scene):
    return plate_dir(scene) / "fire"


def fire_region(scene):
    regs = load_json(plate_dir(scene) / "regions.json", [])
    fires = [g for g in regs if g["kind"] == "fire"]
    if not fires:
        sys.exit(f"{scene}: no fire region in regions.json")
    return max(fires, key=lambda g: (g["bbox"][2] - g["bbox"][0]) * (g["bbox"][3] - g["bbox"][1]))


def clean_items(scene):
    cj = load_json(ROOT / "assets" / "keyart" / f"{scene}.clean.json", {})
    return cj, [it for it in cj.get("items", []) if it.get("kind") == "fire"]


def crop_box(scene, W=3840, H=2160):
    """Crop (4K px) around the fire region and the repainted area, plus margins, in the model's aspect (1280x704
    or 704x1280, whichever needs less scaling); a crop larger than the model size is resized for the model, and a
    small fire's crop is upscaled for it (to MIN_SCALE): the Burdock Shelter's campfire filled 19% x 34% of the model's
    frame at 1:1, and its clips moved only the licks, never the fire's center (2026-10-25, L153)."""
    reg = fire_region(scene)
    x0, y0, x1, y1 = reg["bbox"]
    for it in clean_items(scene)[1]:
        if it.get("box"):
            bx0, by0, bx1, by1 = it["box"]
            x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    x0, y0, x1, y1 = max(0.0, x0) * W, max(0.0, y0) * H, min(1.0, x1) * W, min(1.0, y1) * H
    nw, nh = (x1 - x0) * 1.25 + 60, (y1 - y0) * 1.2 + 60
    best = min(((max(nw / cw, nh / ch, MIN_SCALE), cw, ch) for cw, ch in ((1280, 704), (704, 1280))), key=lambda v: v[0])
    s, cw, ch = best
    w, h = int(round(cw * s)), int(round(ch * s))
    w, h = min(w, W), min(h, H)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = int(round(max(0, min(W - w, cx - w / 2)))), int(round(max(0, min(H - h, cy - h / 2))))
    return [left, top, w, h], (cw, ch)


def src_plate(scene):
    """The key art WITH its painted fire at the plate's geometry (16:9 crop + the same upscale), cached."""
    p = fire_dir(scene) / "src_plate.png"
    if p.exists():
        return Image.open(p).convert("RGB")
    cj, _ = clean_items(scene)
    src = ROOT / (cj.get("source") or load_json(ROOT / "scenes" / scene / "brief.json", {}).get("hero", ""))
    if not src.is_file():
        sys.exit(f"{scene}: the original key art {src} is missing")
    from cozy.plate.image import crop_16x9, upscale
    img = upscale(crop_16x9(Image.open(src).convert("RGB"), 0.5), 3840)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    return img


def describe(scene):
    brief = load_json(ROOT / "scenes" / scene / "brief.json", {})
    ana = load_json(plate_dir(scene) / "analysis.json", {})
    reg = fire_region(scene)
    el = next((e for e in ana.get("elements", []) if e.get("kind") == "fire" and e.get("name") == reg["name"]), None) \
        or next((e for e in ana.get("elements", []) if e.get("kind") == "fire"), {})
    aes = load_json(ROOT / "config" / "aesthetics.json", {}).get("aesthetics", {}).get(brief.get("aesthetic", ""), {})
    what = (el.get("note") or "a cozy fire on glowing logs").strip().rstrip(".")
    what = what[0].lower() + what[1:]
    style = {"pixel": "Pixel art", "anime-painted": "Hand-painted anime"}.get(aes.get("style"), aes.get("style", "painted").replace("-", " ").capitalize())
    return {"what": what, "style": f"{style} style, exactly like the first frame"}


class SpillAbort(RuntimeError):
    pass


def spill_guard(limit_s):
    """callback_on_step_end for the Wan pipeline: abort when a denoising step takes far longer than normal. On
    Windows a GPU that runs out of memory (another app playing a 4K video, a render) silently spills into
    shared RAM and every step gets ~5x slower; better to stop, wait and retry than crawl for an hour."""
    state = {"t": time.time()}

    def cb(pipe, step, timestep, kw):
        now = time.time()
        dt, state["t"] = now - state["t"], now
        if step >= 1 and dt > limit_s:
            raise SpillAbort(f"step {step} took {dt:.0f} s (limit {limit_s:.0f} s): the GPU is short of memory")
        return kw
    return cb


def free_vram_gb():
    import torch
    free, total = torch.cuda.mem_get_info()
    return free / 2**30, total / 2**30


def cmd_gen(a):
    import torch
    from cozy.wan import load_pipe, VaeShuttle, MODEL
    scene = a.scene
    box, (cw, ch) = crop_box(scene)
    x, y, w, h = box
    first = src_plate(scene).crop((x, y, x + w, y + h))
    if (w, h) != (cw, ch):
        first = first.resize((cw, ch), Image.LANCZOS)
    fd = fire_dir(scene)
    fd.mkdir(parents=True, exist_ok=True)
    first.save(fd / "first.png")
    log_p = fd / "clips.json"
    log = load_json(log_p) or {"crop": box, "model_size": [cw, ch], "fps": FPS, "model": MODEL, "clips": {}}
    if log.get("crop") != box:
        print(f"  crop changed {log.get('crop')} -> {box}: older clips no longer match and are dropped")
        log = {"crop": box, "model_size": [cw, ch], "fps": FPS, "model": MODEL, "clips": {}}
    # written now: each new clip reloads the log, and an unwritten reset left the old crop in it (2026-10-25)
    log_p.write_text(json.dumps(log, indent=1), encoding="utf-8")
    prompt = FIRE_PROMPT.format(**describe(scene))
    print(f"crop {box} -> model {cw}x{ch}\nprompt: {prompt}")
    fg, tg = free_vram_gb()
    print(f"GPU memory free {fg:.1f} of {tg:.1f} GB (the model needs ~11 GB at 97 frames: close other GPU apps)")
    t0 = time.time()
    pipe = load_pipe()
    VaeShuttle(pipe)
    with torch.no_grad():
        pe, ne = pipe.encode_prompt(prompt=prompt, negative_prompt=FIRE_NEG, do_classifier_free_guidance=True, device=torch.device("cpu"))
    pe, ne = pe.to("cuda", torch.bfloat16), ne.to("cuda", torch.bfloat16)
    print(f"model loaded in {time.time() - t0:.0f} s")
    seeds = [s for s in range(a.seed, a.seed + 50) if f"fire_{s}" not in log["clips"]][: a.n]
    for seed in seeds:
        name = f"fire_{seed}"
        for attempt in range(a.retries + 1):
            t1 = time.time()
            g = torch.Generator("cuda").manual_seed(seed)
            try:
                res = pipe(image=first, prompt_embeds=pe, negative_prompt_embeds=ne, height=ch, width=cw, num_frames=a.frames,
                           guidance_scale=a.cfg, num_inference_steps=a.steps, generator=g, output_type="pil",
                           callback_on_step_end=spill_guard(a.step_limit))
                break
            except SpillAbort as e:
                torch.cuda.empty_cache()
                if attempt == a.retries:
                    sys.exit(f"  {name}: {e}; gave up after {a.retries + 1} tries")
                print(f"  {name}: {e}; waiting {a.wait} s, then retrying ({attempt + 1}/{a.retries})", flush=True)
                time.sleep(a.wait)
        frames = res.frames[0]
        od = fd / name
        od.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(frames):
            f.save(od / f"f_{i:04d}.png")
        run_ffmpeg(["-v", "error", "-y", "-framerate", str(FPS), "-i", str(od / "f_%04d.png"), "-c:v", "libx264", "-crf", "16",
                    "-pix_fmt", "yuv420p", str(fd / f"{name}.mp4")], capture=False)
        log = load_json(log_p) or log
        log["clips"][name] = {"seed": seed, "prompt": prompt, "negative": FIRE_NEG, "frames": len(frames), "steps": a.steps, "cfg": a.cfg,
                              "s": round(time.time() - t1), "date": time.strftime("%Y-%m-%d")}
        log_p.write_text(json.dumps(log, indent=1), encoding="utf-8")
        print(f"  {name}: {len(frames)} frames in {time.time() - t1:.0f} s -> {fd / (name + '.mp4')}", flush=True)
    del pipe
    torch.cuda.empty_cache()


# ---------------------------------------------------------------- mask, color fit, transitions

def alpha_mask(scene, box, W=3840, H=2160):
    """Where the clip replaces the plate: the fire region plus the area plate_clean.py repainted (there the clean
    plate has no flames and may differ from the original), grown and feathered, faded out near the crop edge."""
    from plate_clean import item_mask
    x, y, w, h = box
    reg = fire_region(scene)
    ids = np.asarray(Image.open(plate_dir(scene) / "regions.png").convert("RGB"))[..., 0]
    m = (ids == reg["id"]).astype(np.float32)
    masks = load_json(ROOT / "assets" / "keyart" / f"{scene}.masks.json", {})
    for it in clean_items(scene)[1]:
        m = np.maximum(m, item_mask({k: v for k, v in it.items() if k != "protect"}, (W, H), masks))
    m = m[y:y + h, x:x + w]
    m = cv2.dilate((m > 0.02).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(np.float32)
    m = cv2.GaussianBlur(m, (0, 0), 9)
    ramp = lambda n, d: np.clip(np.minimum(np.arange(n), np.arange(n)[::-1]) / d, 0, 1)   # noqa: E731
    edge = np.minimum.outer(ramp(h, 28.0), ramp(w, 28.0))
    return np.clip(m * edge, 0, 1)


def color_fit(fr, ref, ring):
    """Per-channel gain/offset that maps the clip frame onto the plate on the ring around the mask."""
    A = np.empty((3, 2), np.float32)
    for c in range(3):
        X = np.stack([fr[..., c][ring], np.ones(int(ring.sum()), np.float32)], 1)
        g, b = np.linalg.lstsq(X, ref[..., c][ring], rcond=None)[0]
        A[c] = (np.clip(g, 0.75, 1.3), np.clip(b, -0.12, 0.12))
    return A


def descriptor(fr, alpha, size=(96, 54)):
    """Small linear-light image of the fire area (alpha-weighted), for frame-to-frame distances."""
    lin = np.power(np.clip(fr, 0, 1), 2.2) * alpha[..., None]
    return cv2.resize(lin, size, interpolation=cv2.INTER_AREA).ravel()


def core_flow(grays, alpha, lag=6):
    """How much the fire's bright center moves (L153): the median optical flow inside the brightest 40% of the fire
    between frames 0.25 s apart, per mille of the fire's height per frame pair. The licks are thin and the median
    leaves them out, so a painted center that holds still under moving licks scores low: the Burdock Shelter's first
    clips 1.29 and 1.52 (Truman: the center of the fire did not move at all), its clips from the tighter crop
    1.75 and up, the wizard library's 2.5 to 3.2. A coarse gate: flow undercounts a flame changing shape, so the
    center strip (center_strip.jpg) is the real check, by eye."""
    h, w = grays[0].shape
    s = 256 / max(h, w)
    g = [cv2.resize(x, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA) for x in grays]
    a = cv2.resize(alpha.astype(np.float32), (g[0].shape[1], g[0].shape[0]))
    inner = a > 0.6
    if inner.sum() < 50 or len(g) <= lag:
        return 0.0
    mean = np.mean(g, 0)
    core = inner & (mean >= np.percentile(mean[inner], 60))
    flows = []
    for i in range(0, len(g) - lag, 3):
        f = cv2.calcOpticalFlowFarneback(g[i], g[i + lag], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        flows.append(float(np.median(np.hypot(f[..., 0], f[..., 1])[core])) / g[0].shape[0])
    return round(float(np.median(flows)) * 1000, 2)


def center_strip(fd, alpha, strips, clips):
    """center_strip.jpg: each kept clip's bright center, 8 frames 0.25 s apart, side by side (L153's eye check: the
    center's flames change shape from frame to frame; the same painted shape in every frame is a still center)."""
    if not strips:
        return
    from PIL import ImageDraw
    a = alpha > 0.6
    ys, xs = np.nonzero(a)
    if not len(ys):
        return
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rows = []
    for name, frames in strips.items():
        tiles = [Image.fromarray(f[y0:y1, x0:x1]) for f in frames]
        s = 220 / tiles[0].height
        tiles = [t.resize((max(1, round(t.width * s)), 220), Image.LANCZOS) for t in tiles]
        row = Image.new("RGB", (sum(t.width + 4 for t in tiles), 244))
        xx = 0
        for k, t in enumerate(tiles):
            row.paste(t, (xx, 24))
            xx += t.width + 4
        ImageDraw.Draw(row).text((4, 4), f"{name}: core flow {clips[name]['core_flow']:.2f}, frames 0.25 s apart", fill=(255, 220, 0))
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)))
    yy = 0
    for r in rows:
        sheet.paste(r, (0, yy))
        yy += r.height
    sheet.save(fd / "center_strip.jpg", quality=88)
    print(f"  center strip: {fd / 'center_strip.jpg'} (look: the center's flames change shape frame to frame)")


def cmd_loop(a):
    scene = a.scene
    fd = fire_dir(scene)
    log = load_json(fd / "clips.json")
    if not log or not log.get("clips"):
        sys.exit("no clips: run gen first")
    x, y, w, h = log["crop"]
    plate = np.asarray(Image.open(plate_dir(scene) / "plate.png").convert("RGB"), np.float32)[y:y + h, x:x + w] / 255
    alpha = alpha_mask(scene, log["crop"])
    near = cv2.dilate((alpha > 0.01).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (161, 161))) > 0
    ring = near & (alpha < 0.005)
    if ring.sum() < 500:
        ring = alpha < 0.005
    # the renderer only needs the masked part: frames and alpha are cut to its bounding box
    ys, xs = np.nonzero(alpha > 0.003)
    bx0, by0, bx1, by1 = max(0, xs.min() - 4), max(0, ys.min() - 4), min(w, xs.max() + 5), min(h, ys.max() + 5)
    box = [x + int(bx0), y + int(by0), int(bx1 - bx0), int(by1 - by0)]
    acut = alpha[by0:by1, bx0:bx1]
    Image.fromarray((acut * 255).round().astype(np.uint8), "L").save(fd / "alpha.png")
    small = (max(24, acut.shape[1] // 12), max(24, acut.shape[0] // 12))
    half = XFADE // 2
    run_min = int(RUN[0] * FPS)
    clips, descs, strips = {}, {}, {}
    for name in sorted(log["clips"]):
        if log["clips"][name].get("dropped"):
            continue
        files = sorted((fd / name).glob("f_*.png"))
        if not files:
            continue
        frs = []
        for f in files:
            im = Image.open(f).convert("RGB")
            if im.size != (w, h):
                im = im.resize((w, h), Image.LANCZOS)
            frs.append(np.asarray(im, np.float32) / 255)
        fits = np.stack([color_fit(fr, plate, ring) for fr in frs])
        k = np.array([1, 2, 3, 2, 1], np.float32)
        k /= k.sum()
        pad = np.concatenate([fits[:1].repeat(2, 0), fits, fits[-1:].repeat(2, 0)])
        fits = np.stack([np.tensordot(k, pad[i:i + 5], 1) for i in range(len(frs))])
        for old in (fd / name).glob("c_*.jpg"):
            old.unlink()
        ds, act, lum, grays, keyf = [], [], [], [], []
        prev = None
        for i, fr in enumerate(frs):
            c = np.clip(fr * fits[i][:, 0] + fits[i][:, 1], 0, 1)[by0:by1, bx0:bx1]
            c8 = (c * 255).round().astype(np.uint8)
            Image.fromarray(c8).save(fd / name / f"c_{i:04d}.jpg", quality=93)
            grays.append(cv2.cvtColor(c8, cv2.COLOR_RGB2GRAY))
            if i >= LO and (i - LO) % 6 == 0 and len(keyf) < 8:
                keyf.append(c8)
            ds.append(descriptor(c, acut, small))
            lum.append(float((c.mean(-1) * acut).sum() / acut.sum()))
            if prev is not None:
                act.append(float((np.abs(c - prev).mean(-1) * acut).sum() / acut.sum()))
            prev = c
        n = len(frs)
        clips[name] = {"frames": n, "dir": name, "lo": LO, "hi": n - 1,
                       "motion": round(float(np.median(act)), 5), "core_flow": core_flow(grays[LO:], acut),
                       "lum": [round(v, 4) for v in lum]}
        descs[name] = np.stack(ds).astype(np.float64)
        strips[name] = keyf
        print(f"  {name}: {n} frames, motion {clips[name]['motion']:.4f} (mean abs change per frame in the fire), "
              f"core flow {clips[name]['core_flow']:.2f} (needs {a.core_min}), brightness {min(lum):.3f}..{max(lum):.3f}")
    # a clip whose bright center holds still while only the licks move is dropped (L153); gen picks new seeds after it
    for name in [k for k, v in clips.items() if v["core_flow"] < a.core_min]:
        log["clips"][name]["dropped"] = f"core flow {clips[name]['core_flow']} < {a.core_min}: the fire's center holds still"
        print(f"  {name}: dropped, {log['clips'][name]['dropped']}")
        del clips[name], descs[name]
    (fd / "clips.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    center_strip(fd, acut, {k: v for k, v in strips.items() if k in clips}, clips)
    if not clips:
        print("  no clip moves the fire's center: generate more (fire_clips.py <scene> auto)")
        return 0
    # Jumps: at the end frame e of a run the walk crossfades (over XFADE frames centered on the boundary) to frame
    # j - 1 of any clip, where frames j-1..j+1 look like e..e+2 would have (the motion carries on through the blend).
    # Rows exist for e in [lo + half, hi - half); targets j in [lo + half + 1, hi - half - run_min).
    names = list(clips)
    d2 = {}
    for n_ in names:
        for m in names:
            A, B = descs[n_], descs[m]
            G = (A * A).sum(1)[:, None] + (B * B).sum(1)[None, :] - 2 * A @ B.T
            d2[n_, m] = np.maximum(G, 0) / A.shape[1]
    step = np.median([d2[n_, n_][i, i + 1] for n_ in names for i in range(LO, clips[n_]["hi"])])
    nxt = {}
    for n_ in names:
        lo, hi = clips[n_]["lo"], clips[n_]["hi"]
        rows = []
        for e in range(lo + half, hi - half):
            cands = []
            for mi, m in enumerate(names):
                mlo, mhi = clips[m]["lo"], clips[m]["hi"]
                D = d2[n_, m]
                for j in range(mlo + half + 1, mhi - half - run_min):
                    if m == n_ and abs(j - (e + 1)) < FPS:
                        continue
                    cost = 0.25 * D[e, j - 1] + 0.5 * D[e + 1, j] + 0.25 * D[min(e + 2, hi), j + 1]
                    cands.append((cost / max(step, 1e-12), mi, j))
            cands.sort()
            rows.append([[mi, j, round(float(c), 3)] for c, mi, j in cands[:5]])
        nxt[n_] = rows
    best = [row[0][2] for n_ in names for row in nxt[n_] if row]
    meta = {"fps": FPS, "box": box, "alpha": "alpha.png", "xfade": XFADE, "run": list(RUN), "region": fire_region(scene)["name"],
            "names": names, "clips": clips, "next": nxt, "model": log.get("model"), "core_min": a.core_min,
            "_note": "tools/fire_clips.py: frames <dir>/c_####.jpg cut to box (4K px); next[clip][e - (lo + xfade/2)] = up to 5 "
                     "jumps [clip index, frame j, cost (1 = one frame step)]: the run ending at e continues as frame j - 1"}
    (fd / "fire.json").write_text(json.dumps(meta), encoding="utf-8")
    print(f"fire.json: {len(names)} clip(s), box {box}; best jump cost median {np.median(best):.2f}, 90% {np.percentile(best, 90):.2f} "
          f"(1 = one frame step)")
    return len(names)


def cmd_sheet(a):
    fd = fire_dir(a.scene)
    log = load_json(fd / "clips.json", {})
    rows = []
    for name in sorted(log.get("clips", {})):
        fs = sorted((fd / name).glob("c_*.jpg")) or sorted((fd / name).glob("f_*.png"))
        if not fs:
            continue
        pick = [fs[int(i)] for i in np.linspace(0, len(fs) - 1, 6)]
        ims = [Image.open(p).convert("RGB") for p in pick]
        s = 300 / ims[0].height
        ims = [im.resize((round(im.width * s), 300), Image.LANCZOS) for im in ims]
        row = Image.new("RGB", (sum(im.width for im in ims) + 6 * 5, 300))
        xx = 0
        for im in ims:
            row.paste(im, (xx, 0))
            xx += im.width + 6
        rows.append(row)
    if not rows:
        sys.exit("no clips")
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 6 for r in rows)))
    yy = 0
    for r in rows:
        sheet.paste(r, (0, yy))
        yy += r.height + 6
    sheet.save(fd / "sheet.jpg", quality=88)
    print(fd / "sheet.jpg")


def cmd_auto(a):
    """gen until --n clips move the fire's center (core flow), at most --rounds rounds of new seeds, then the sheet."""
    box, _ = crop_box(a.scene)
    want, kept = a.n, 0
    for rnd in range(a.rounds):
        log = load_json(fire_dir(a.scene) / "clips.json", {})
        live = [k for k, v in log.get("clips", {}).items() if not v.get("dropped")] if log.get("crop") == box else []
        if len(live) < want:
            a.n = want - len(live)
            cmd_gen(a)
        kept = cmd_loop(a)
        if kept >= want:
            break
        print(f"  round {rnd + 1}: {kept} of {want} clip(s) move the fire's center; generating more")
    if not kept:
        sys.exit(f"{a.scene}: no clip moved the fire's center in {a.rounds} round(s) (core flow under {a.core_min}): "
                 "look at the clips, then try --cfg 6 or a tighter crop")
    cmd_sheet(a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("cmd", choices=["gen", "loop", "auto", "sheet"])
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--frames", type=int, default=97, help="4k+1; 97 = 4 s at 24 fps (121 spills a 12 GB GPU)")
    ap.add_argument("--cfg", type=float, default=5.0)
    ap.add_argument("--core-min", type=float, default=CORE_MIN, help="least core flow a clip keeps (the fire's center moving)")
    ap.add_argument("--rounds", type=int, default=3, help="auto: rounds of new seeds while too few clips move the center")
    ap.add_argument("--step-limit", type=float, default=45.0, help="s per denoising step before it counts as a GPU memory spill")
    ap.add_argument("--retries", type=int, default=6)
    ap.add_argument("--wait", type=int, default=300, help="s to wait before retrying after a spill")
    a = ap.parse_args()
    if a.cmd == "loop":
        sys.exit(0 if cmd_loop(a) else 3)
    {"gen": cmd_gen, "auto": cmd_auto, "sheet": cmd_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
