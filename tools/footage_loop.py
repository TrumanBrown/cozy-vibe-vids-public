"""Loop a real camera recording into a long video (the aquarium, user 2026-10-22).

The plate pipeline animates one image. This takes footage instead: a locked-off recording is cut to a window
whose end blends into its start, encoded once, and repeated by stream copy, with a water bed made in code and
music planned over the whole length (tools/music.py), the way tools/loop_master.py does for rendered windows.

  .venv\\Scripts\\python tools\\footage_loop.py analyze <scene>   # decode once at 320x180 RGB, then `seam` (about 10 min)
  .venv\\Scripts\\python tools\\footage_loop.py seam <scene>      # pick the loop and the opening again from the analysis
  .venv\\Scripts\\python tools\\footage_loop.py heroes <scene>    # 4K stills of the fish for thumbnails (out/<scene>/stills)
  .venv\\Scripts\\python tools\\footage_loop.py grades <scene> [--frame N]   # six looks to pick from (tools/color_edit.py sets one)
  .venv\\Scripts\\python tools\\footage_loop.py cut <scene> [--tag cut_v1]   # a review cut: `in` to the end, the final sound, no loop
  .venv\\Scripts\\python tools\\footage_loop.py window <scene> [--tag loop20_v1]     # the window's pieces (about 30 min)
  .venv\\Scripts\\python tools\\footage_loop.py master <scene> [--tag loop20_v1] [--name 10h_v1]   # music, 10 h, QA

Settings: scenes/<scene>/footage.json (source file, `in` where the usable part starts, loop length and target_s,
crossfade, the chosen loop_start and opening once looked at (frames of the whole recording), encoder, water, intro,
music). Output: cache/<scene>/footage/ (analysis frames, the water bed),
out/<scene>/footage/ (analysis.json, seam_dissolve.jpg, opening_strips.jpg, hero_crops.jpg),
out/<scene>/render/<tag>/ (the window: a.mp4, i.mp4, b.mp4) and out/<scene>/render/<name>/ (master_music.mp4,
music_mix.m4a, music_plan.json, credits.txt, loop.json, qa.md).

The loop: of all windows [s, s + N) the source can hold (N = loop frames, plus D crossfade frames after it), the
one whose continuation src[s+N .. s+N+D) shows the fewest fish ghosts against its start src[s .. s+D) (seam()). Frame
k < D of the loop is the continuation dissolving into the start; every other frame is the source as shot. The video
starts at the loop's busiest stretch (strong opening, user 2026-10-16), so the dissolve falls inside the window and
every stream-copy join is two consecutive source frames. Look at seam_dissolve.jpg and opening_strips.jpg, then pin
loop_start and opening in footage.json.
"""
import argparse
import json
import subprocess
import sys
import time

import numpy as np

from cozy.paths import ROOT
from cozy.media import grab_frame, probe, run_ffmpeg
AW, AH = 320, 180                   # analysis frames (RGB, 1/12 of 4K): seam, opening
W, H = 640, 360                     # QA frames (grey): joins and the dissolve in the master


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_cfg(scene):
    p = ROOT / "scenes" / scene / "footage.json"
    if not p.exists():
        sys.exit(f"{p} is missing: it names the recording and the loop settings")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["_src"] = (p.parent / cfg["source"]).resolve()
    return cfg


def probe_video(src):
    s = probe(src, "stream=width,height,r_frame_rate,nb_frames,pix_fmt,duration", streams="v:0")["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return {"width": s["width"], "height": s["height"], "fps_num": num, "fps_den": den, "fps": num / den,
            "frames": int(s["nb_frames"]), "pix_fmt": s["pix_fmt"], "duration": float(s["duration"])}


def loop_frames(cfg, v):
    return int(round(cfg.get("loop_seconds", 1200) * v["fps"]))


def analyze(scene, cfg):
    """One decode of the usable part of the recording (footage.json `in` to its end, or `out`) at 320x180 RGB: per
    frame the mean level and how much moved since the frame before (grey pixels changed by more than 12 levels, overall
    and per cell of a 4x4 grid); the first and last (usable - N) frames kept for the seam search; one frame per second
    for the opening. About 10 minutes for 20 minutes of 4K 4:2:2 HEVC (the GPU can't decode 4:2:2 on this card).
    Frames here count from `in`; seam() reports the loop start in the recording's own frames."""
    src = cfg["_src"]
    v = probe_video(src)
    fps = v["fps"]
    N = loop_frames(cfg, v)
    k_in = int(np.ceil(float(cfg.get("in", 0.0)) * fps - 1e-6))
    k_end = v["frames"] if cfg.get("out") is None else int(np.floor(float(cfg["out"]) * fps))
    total = k_end - k_in
    head_n = total - N
    if head_n <= cfg.get("xfade_frames", 150):
        sys.exit(f"the usable part ({total} frames from frame {k_in}) is too short for a {N}-frame loop plus the crossfade")
    cache = ROOT / "cache" / scene / "footage"
    cache.mkdir(parents=True, exist_ok=True)
    head = np.lib.format.open_memmap(cache / "head_rgb.npy", "w+", np.uint8, (head_n, AH, AW, 3))
    tail = np.lib.format.open_memmap(cache / "tail_rgb.npy", "w+", np.uint8, (head_n, AH, AW, 3))
    nsec = int(total / v["fps"]) + 1
    thumbs = np.zeros((nsec, AH, AW, 3), np.uint8)
    mean = np.zeros(total, np.float32)
    moved = np.zeros(total, np.float32)
    grid = np.zeros((total, 4, 4), np.float32)
    log(f"analyze: {src.name} {v['width']}x{v['height']} {fps:.3f} fps, frames {k_in} to {k_end - 1} ({total}); loop {N} frames, "
        f"seam search over the first and last {head_n}")
    cmd = ["ffmpeg", "-v", "error", *(["-ss", ss(k_in, fps)] if k_in else []), "-i", str(src), "-map", "0:v:0", "-frames:v", str(total),
           "-vf", f"scale={AW}:{AH}:flags=area:in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24", "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=0)
    fsz = AW * AH * 3
    buf = bytearray(fsz)
    prev = None
    k, next_sec = 0, 0
    t0 = time.time()
    while True:
        view = memoryview(buf)
        got = 0
        while got < fsz:
            n = p.stdout.readinto(view[got:])
            if not n:
                break
            got += n
        if got < fsz:
            break
        if k >= total:
            log(f"analyze: the decoder gave more frames than the container lists ({total}); stopping there")
            break
        f = np.frombuffer(buf, np.uint8).reshape(AH, AW, 3)
        g = grey(f)
        mean[k] = g.mean()
        if prev is not None:
            d = np.abs(g - prev) > 12
            moved[k] = d.mean()
            grid[k] = d.reshape(4, AH // 4, 4, AW // 4).mean(axis=(1, 3))
        prev = g
        if k < head_n:
            head[k] = f
        if k >= N and k - N < head_n:
            tail[k - N] = f
        if k >= next_sec * v["fps"] - 1e-6 and next_sec < nsec:     # the first frame of each second
            thumbs[next_sec] = f
            next_sec += 1
        k += 1
        if k % 3000 == 0:
            el = time.time() - t0
            log(f"analyze: {k}/{total} frames, {k / el:.1f} fps, about {(total - k) / max(k / el, 1e-6) / 60:.0f} min left")
    p.wait()
    if p.returncode:
        sys.exit(f"ffmpeg failed decoding {src}")
    if k != total:
        log(f"analyze: decoded {k} frames, the container lists {total}")
    head.flush()
    tail.flush()
    np.savez_compressed(cache / "stats.npz", mean=mean[:k], moved=moved[:k], grid=grid[:k], thumbs=thumbs[:next_sec],
                        frames=k, N=N, head_n=head_n, fps=v["fps"], k_in=k_in)
    log(f"analyze: decoded in {(time.time() - t0) / 60:.1f} min -> {cache}")
    return seam(scene, cfg)


def grey(f):
    """Luma (Rec. 709 weights) of RGB frames, float32."""
    f = f.astype(np.float32)
    return f[..., 0] * 0.2126 + f[..., 1] * 0.7152 + f[..., 2] * 0.0722


def warm(f):
    """Pixels of the warm-colored fish (orange, gold, red: the gourami and the small fish) in RGB frames. Plants are
    green, the rock grey, the gravel dark brown; snails are warm too, but they sit still, so callers drop what is
    warm in the median frame."""
    a = f.astype(np.int16)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (R - G > 30) & (R > 90) & (R - B > 50)


def grade_vf(g):
    """The color grade (footage.json `grade`: iPhone's sliders, -100..100, 0 = as shot; tools/color_grade.py, set with
    tools/color_edit.py) as ffmpeg filters on the 10-bit frames: one 3D LUT on the camera's own Y'CbCr codes, so the range
    above video white (Y' 940..1023, which players show as flat white) stays for Highlights to bring back. eq would
    convert the frames to 8-bit first (checked 2026-10-23). Out as yuv444p10le; None when every slider is 0."""
    import color_grade as CG
    return CG.vf(g, ROOT / "cache" / "color")


def grab(src, k, fps, w=None, vf=None):
    """Source frame k as RGB (uint8), optionally scaled to width w and through a filter on the 10-bit frame first (vf:
    grade_vf)."""
    sc = f"scale={w}:-2:flags=lanczos:" if w else "scale="
    raw = grab_frame(src, f"{max(0.0, (k - 0.5) / fps):.6f}", frames=1,
                     vf=f"{vf + ',' if vf else ''}{sc}in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24")
    ww = w or 3840
    return np.frombuffer(raw, np.uint8).reshape(-1, ww, 3)


GRADES = [("A", "as shot", {}),
          ("B", "highlights -25", {"highlights": -25}),
          ("C", "highlights -50", {"highlights": -50}),
          ("D", "highlights -30, contrast +15", {"highlights": -30, "contrast": 15}),
          ("E", "highlights -30, shadows +15, vibrance +15", {"highlights": -30, "shadows": 15, "vibrance": 15}),
          ("F", "brilliance +40", {"brilliance": 40})]


def grades(scene, cfg, frame=None, options=GRADES):
    """Looks to pick from without the editor (tools/color_edit.py is the way to set one): one source frame through
    grade_vf, the same filters the window is encoded with, per option, tiled 3 x 2 with their letters ->
    out/<scene>/footage/grades.jpg, and grades.json with the sliders behind each letter. frame: a source frame (default:
    the video's first frame)."""
    from PIL import Image, ImageDraw, ImageFont
    import intro_title as IT
    an = json.loads((ROOT / "out" / scene / "footage" / "analysis.json").read_text())
    fps = an["fps"]
    k = int(frame) if frame is not None else int(cfg.get("loop_start", an["loop_start"])) + int(cfg.get("opening", an["opening"]))
    font = ImageFont.truetype(str(IT.font_file("quicksand")[0]), 34)
    tiles = []
    for letter, name, g in options:
        img = Image.fromarray(grab(cfg["_src"], k, fps, 1280, vf=grade_vf(g)))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 36 + int(d.textlength(f"{letter}   {name}", font=font)), 54], fill=(0, 0, 0))
        d.text((16, 7), f"{letter}   {name}", font=font, fill=(255, 255, 255))
        tiles.append(np.asarray(img))
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    out = ROOT / "out" / scene / "footage"
    Image.fromarray(np.concatenate([np.concatenate(tiles[i:i + 3], 1) for i in range(0, len(tiles), 3)], 0)).save(out / "grades.jpg", quality=92)
    (out / "grades.json").write_text(json.dumps({"source_frame": k, "options": {l: {"name": n, **g} for l, n, g in options}}, indent=1))
    log(f"grades: {len(options)} options of source frame {k} -> {out / 'grades.jpg'}")
    return out / "grades.jpg"


def seam(scene, cfg):
    """Pick the loop and the opening from the analysis (re-runnable without decoding: `seam <scene>`).

    The seam: a dissolve starting at s shows the pairs (src[s + k], src[s + N + k]), k < D, at weight w(1 - w). What a
    viewer sees as a ghost is a fish in one frame of a pair and not the other: per pair, the share of pixels where the
    warm-colored moving things (warm(), minus what is warm in the region's median frame: the snails) differ, plus 0.35
    times the share where any grey foreground (more than 20 levels off the region's median frame) differs. Each term is
    divided by its median over the choices. The aquarium (2026-10-22) showed why the fish term leads: by grey
    differences alone, moss strands swaying and snails that had crawled made up most of every pair, and the pick faded
    the big gourami in beside the sword leaves; the fish term found a seam where it is hidden in both frames.
    The opening: per second of the loop, the share of the frame where warm fish are (against a running median of
    +-60 s) and how big the biggest one is (the gourami near the glass), each divided by its median over the loop; the
    score is the first over the first 45 s, plus half of it over the first 15 s, plus 0.3 times the second over the
    first 15 s. Picks at least 90 s apart; the first wins unless
    footage.json pins `opening`. Look at opening_strips.jpg (6 frames over each pick's first 30 s) before trusting it."""
    from PIL import Image
    import cv2
    cache = ROOT / "cache" / scene / "footage"
    st = np.load(cache / "stats.npz")
    fps, N, hn, total = float(st["fps"]), int(st["N"]), int(st["head_n"]), int(st["frames"])
    k_in = int(st["k_in"]) if "k_in" in st.files else 0              # analysis frames count from footage.json `in`
    D = int(cfg.get("xfade_frames", 150))
    K = int(cfg.get("intro_frames", 720))
    head = np.load(cache / "head_rgb.npy", mmap_mode="r")
    tail = np.load(cache / "tail_rgb.npy", mmap_mode="r")
    n = min(hn, total - N)
    med_h = np.median(head[::25].astype(np.float32), axis=0)
    med_t = np.median(tail[::25].astype(np.float32), axis=0)
    still_h, still_t = warm(med_h.astype(np.uint8)), warm(med_t.astype(np.uint8))
    bg_h, bg_t = grey(med_h), grey(med_t)
    fish = np.zeros(n, np.float32)
    fg = np.zeros(n, np.float32)
    for j0 in range(0, n, 256):
        j1 = min(j0 + 256, n)                    # n can be short of the memmaps when the decoder gave fewer frames
        a, b = head[j0: j1], tail[j0: j1]
        fish[j0: j1] = ((warm(a) & ~still_h) ^ (warm(b) & ~still_t)).mean(axis=(1, 2))
        fg[j0: j1] = ((np.abs(grey(a) - bg_h) > 20) ^ (np.abs(grey(b) - bg_t) > 20)).mean(axis=(1, 2))
    w = (np.arange(D) + 0.5) / D
    c = w * (1 - w)
    cost_f = np.convolve(fish, c[::-1], "valid") / c.sum()           # cost[s] for s in [0, n - D]
    cost_g = np.convolve(fg, c[::-1], "valid") / c.sum()
    s_min = int(round(cfg.get("skip_start_s", 2.0) * fps))
    score = cost_f / np.median(cost_f[s_min:]) + 0.35 * cost_g / np.median(cost_g[s_min:])
    s = s_min + int(np.argmin(score[s_min:]))
    S = k_in + s                                                       # the loop start in the recording's frames
    mean = st["mean"]
    log(f"seam: loop starts at frame {S} ({S / fps:.2f} s in the recording): fish ghosts {cost_f[s] * 1e4:.1f} per 10k px (median over the "
        f"choices {np.median(cost_f[s_min:]) * 1e4:.1f}), any foreground {cost_g[s] * 100:.2f}% (median "
        f"{np.median(cost_g[s_min:]) * 100:.2f}%); brightness end vs start {mean[s + N: s + N + D].mean() - mean[s: s + D].mean():+.2f}")
    # opening: warm fish per second of the loop
    th = st["thumbs"]
    ns = len(th)
    pres = np.zeros(ns, np.float32)
    big = np.zeros(ns, np.float32)
    for i in range(ns):
        lo_, hi_ = max(0, i - 60), min(ns, i + 61)
        m = warm(th[i]) & (np.abs(th[i].astype(np.int16) - np.median(th[lo_:hi_:4], axis=0)).sum(-1) > 60)
        pres[i] = m.mean()
        I = np.pad(m.astype(np.float32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        bb = 12
        big[i] = (I[bb:, bb:] - I[:-bb, bb:] - I[bb:, :-bb] + I[:-bb, :-bb]).max() / bb ** 2
    sec = int(round(fps))
    loop_s = int(N / fps)
    lp = np.array([pres[min(ns - 1, int((s + t * fps) / fps))] for t in range(loop_s)])
    lb = np.array([big[min(ns - 1, int((s + t * fps) / fps))] for t in range(loop_s)])
    wm = lambda a, i, L: float(a[np.arange(i, i + L) % len(a)].mean())
    lo, hi = int(np.ceil((D + 2 * sec) / fps)), int((N - K - 2 * sec) / fps) - 1
    mp, mb = max(float(np.median(lp)), 1e-9), max(float(np.median(lb)), 1e-9)     # each term against its own median
    cand = sorted(((wm(lp, t, 45) / mp + 0.5 * wm(lp, t, 15) / mp + 0.3 * wm(lb, t, 15) / mb, t) for t in range(lo, hi)), reverse=True)
    picks = []
    for sc_, t in cand:
        if all(abs(t - q) > 90 for q in picks):
            picks.append(t)
        if len(picks) == 4:
            break
    o = int(round(picks[0] * fps))
    log(f"opening: the window starts {picks[0]} s into the loop (source frame {S + o}, {(S + o) / fps:.1f} s in the "
        f"recording); fish {wm(lp, picks[0], 45) * 100:.2f}% of the frame over its first 45 s (the loop's mean "
        f"{lp.mean() * 100:.2f}%); other picks at {', '.join(f'{t} s' for t in picks[1:])}")
    res = {"source": cfg["source"], "fps": fps, "frames": k_in + total, "k_in": k_in, "loop_frames": N, "xfade_frames": D, "intro_frames": K,
           "loop_start": S, "opening": o, "opening_candidates_s": picks,
           "seam_fish_per_10k": round(float(cost_f[s]) * 1e4, 2), "seam_fish_median_per_10k": round(float(np.median(cost_f[s_min:])) * 1e4, 2),
           "seam_foreground_pct": round(float(cost_g[s]) * 100, 3),
           "seam_brightness_step": round(float(mean[s + N: s + N + D].mean() - mean[s: s + D].mean()), 3),
           "fish_per_min_pct": [round(float(lp[m * 60:(m + 1) * 60].mean()) * 100, 3) for m in range(loop_s // 60)],
           "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out = ROOT / "out" / scene / "footage"
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(res, indent=1))
    # To look at: the dissolve at 20, 50 and 80% (the blend, and what differs), and each opening's first 30 s.
    src = cfg["_src"]
    rows = []
    for k in (int(D * 0.2), D // 2, int(D * 0.8)):
        wk = (k + 0.5) / D
        A = grab(src, S + N + k, fps, 960).astype(np.float32)
        B = grab(src, S + k, fps, 960).astype(np.float32)
        rows.append(np.concatenate([((1 - wk) * A + wk * B).astype(np.uint8), np.abs(A - B).clip(0, 255).astype(np.uint8)], 1))
    Image.fromarray(np.concatenate(rows, 0)).save(out / "seam_dissolve.jpg", quality=86)
    strips = []
    for t in picks[:2]:
        ims = [grab(src, S + int(round((t + dt) * fps)) % N, fps, 640) for dt in (0, 6, 12, 18, 24, 30)]
        strips += [np.concatenate(ims[:3], 1), np.concatenate(ims[3:], 1)]
    Image.fromarray(np.concatenate(strips, 0)).save(out / "opening_strips.jpg", quality=84)
    del cv2
    log(f"seam: wrote {out / 'analysis.json'}, seam_dissolve.jpg (the blend | what differs, at 20/50/80%), "
        "opening_strips.jpg (the first two openings, 6 frames over 30 s each)")
    return res


def heroes(scene, cfg, count=6):
    """Thumbnail stills: the recording's keyframes (one a second, decoded alone, so fast) inside the loop, scored by the
    biggest warm fish (the gourami near the glass) and how many small fish show; the best few, at least 10 s apart,
    saved at 4K to out/<scene>/stills/hero_f<frame>.png with a sheet of 1:1 crops around the fish (hero_crops.jpg)."""
    import re
    import cv2
    from PIL import Image
    src = cfg["_src"]
    an = json.loads((ROOT / "out" / scene / "footage" / "analysis.json").read_text())
    fps, N = an["fps"], an["loop_frames"]
    s = int(cfg.get("loop_start", an["loop_start"]))
    w, h = 480, 270
    p = run_ffmpeg(["-v", "info", "-skip_frame", "nokey", "-i", str(src), "-map", "0:v:0", "-vf",
                    f"scale={w}:{h}:flags=area:in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24,showinfo",
                    "-fps_mode", "passthrough", "-f", "rawvideo", "-"], check=False)
    frames = np.frombuffer(p.stdout, np.uint8).reshape(-1, h, w, 3)
    pts = [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", p.stderr.decode(errors="replace"))]
    med = np.median(frames[::10].astype(np.float32), axis=0)
    rows = []
    for f, t in zip(frames, pts):
        k = int(round(t * fps))
        if not (s <= k < s + N):
            continue
        m = (warm(f) & (np.abs(f.astype(np.int16) - med).sum(-1) > 60)).astype(np.uint8)
        nb, _, stats, cent = cv2.connectedComponentsWithStats(m, 8)
        blobs = [(stats[i, cv2.CC_STAT_AREA], cent[i]) for i in range(1, nb) if stats[i, cv2.CC_STAT_AREA] >= 6]
        bigb = max(blobs, key=lambda b: b[0]) if blobs else (0, (0, 0))
        rows.append({"frame": k, "fish_px": int(bigb[0]), "x": float(bigb[1][0]) / w, "y": float(bigb[1][1]) / h,
                     "small": sum(1 for b in blobs if b[0] < 60)})
    pick = []
    for r in sorted(rows, key=lambda r: -(r["fish_px"] + 8 * r["small"])):
        if all(abs(r["frame"] - q["frame"]) > 10 * fps for q in pick):
            pick.append(r)
        if len(pick) == count:
            break
    d = ROOT / "out" / scene / "stills"
    d.mkdir(parents=True, exist_ok=True)
    crops = []
    for r in pick:
        img = grab(src, r["frame"], fps, vf=grade_vf(cfg.get("grade")))
        Image.fromarray(img).save(d / f"hero_f{r['frame']:06d}.png")
        cx, cy = int(r["x"] * 3840), int(r["y"] * 2160)
        x0, y0 = min(max(cx - 480, 0), 3840 - 960), min(max(cy - 270, 0), 2160 - 540)
        crops.append(img[y0:y0 + 540, x0:x0 + 960])
    while len(crops) % 3:
        crops.append(np.zeros_like(crops[0]))
    sheet = np.concatenate([np.concatenate(crops[i:i + 3], 1) for i in range(0, len(crops), 3)], 0)
    Image.fromarray(sheet).resize((sheet.shape[1] // 2, sheet.shape[0] // 2), Image.LANCZOS).save(
        ROOT / "out" / scene / "footage" / "hero_crops.jpg", quality=88)
    (ROOT / "out" / scene / "footage" / "heroes.json").write_text(json.dumps(pick, indent=1))
    log(f"heroes: {len(pick)} stills in {d} (frames {', '.join(str(r['frame']) for r in pick)}); crops in hero_crops.jpg")
    return pick


ENC = {"preset": "p7", "multipass": "fullres", "bitrate": "46M", "maxrate": "70M", "bufsize": "92M", "gop": 120}
INTRO = {"lines": [], "font": "quicksand", "size": 72, "pos": [0.5, 0.5], "color": "#fff1df", "at": 1.0, "fade_in": 1.8,
         "hold": 6.5, "fade_out": 2.2}


def enc_args(cfg):
    """HEVC 10-bit with NVENC, the same for every piece so they join by stream copy (identical parameter sets).
    VBR at a fixed average: the long video's size is the window's size times the repeats, under YouTube's 256 GB.
    46 Mbit/s at p7: 1:1 crops match the source but for some sensor noise (2026-10-22, the aquarium's 20 s test:
    PSNR 34.4 dB, where consecutive source frames differ by 29 dB, i.e. the camera noise sets it)."""
    e = {**ENC, **(cfg.get("encoder") or {})}
    return ["-c:v", "hevc_nvenc", "-preset", e["preset"], "-tune", "hq", "-rc", "vbr", "-b:v", e["bitrate"], "-maxrate", e["maxrate"],
            "-bufsize", e["bufsize"], "-multipass", e["multipass"], "-rc-lookahead", "32", "-spatial-aq", "1", "-temporal-aq", "1",
            "-aq-strength", "8", "-bf", "4", "-b_ref_mode", "middle", "-g", str(e["gop"]), "-profile:v", "main10",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv", "-tag:v", "hvc1", "-an"]


def plan_of(scene, cfg):
    """The loop and window in source frames: loop start s, opening o, loop N, dissolve D, intro K (footage.json pins s and
    o once chosen and looked at; else analysis.json's)."""
    an = json.loads((ROOT / "out" / scene / "footage" / "analysis.json").read_text())
    s = int(cfg.get("loop_start", an["loop_start"]))
    o = int(cfg.get("opening", an["opening"]))
    N, D, K = an["loop_frames"], int(cfg.get("xfade_frames", 150)), int(cfg.get("intro_frames", 720))
    fps = an["fps"]
    if not (D <= o <= N - K):
        sys.exit(f"opening {o} must lie in [{D}, {N - K}] so the dissolve stays out of the intro")
    if s + N + D > an["frames"]:
        sys.exit("the loop and its dissolve run past the end of the recording")
    return {"s": s, "o": o, "N": N, "D": D, "K": K, "fps": fps, "fps_num": 60000 if abs(fps - 59.94) < 0.01 else None}


def ss(k, fps):
    """-ss for source frame k: the first frame at or after (k - 0.5) / fps is frame k."""
    return f"{max(0.0, (k - 0.5) / fps):.6f}"


def draw_intro(scene, cfg, out):
    """The intro block (intro_title.py's drawing and text rules) as intro.png, 1:1 at 4K; returns (png, x, y, timing)."""
    import intro_title as IT
    I = {**INTRO, **(cfg.get("intro") or {})}
    lines = [x if isinstance(x, str) else x["text"] for x in I["lines"]]
    scales = [1.0 if isinstance(x, str) else float(x.get("scale", 1.0)) for x in I["lines"]]
    IT.check_text(lines)
    path, entry = IT.font_file(I["font"])
    block, core = IT.block_ttf(lines, scales, path, entry, I["size"], I["color"])
    x0, y0 = int(round(I["pos"][0] * 3840 - block.width / 2)), int(round(I["pos"][1] * 2160 - block.height / 2))
    png = out / "intro.png"
    block.save(png)
    meta = {"lines": lines, "font": I["font"], "font_title": entry["title"], "size": I["size"], "color": I["color"],
            "box": [x0, y0, x0 + block.width, y0 + block.height], "timing": {k: I[k] for k in ("at", "fade_in", "hold", "fade_out")}}
    (out / "intro.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return png, x0, y0, meta["timing"]


def run(cmd, what):
    t0 = time.time()
    log(f"{what}: encoding")
    r = run_ffmpeg(["-hide_banner", "-loglevel", "error", "-stats_period", "30", "-y", *cmd], check=False, capture=False)
    if r.returncode:
        sys.exit(f"{what}: ffmpeg failed")
    log(f"{what}: done in {(time.time() - t0) / 60:.1f} min")


def window(scene, cfg, tag):
    """The window's pieces in out/<scene>/render/<tag>/: a.mp4 = its first K frames, i.mp4 = the same with the intro
    title, b.mp4 = the rest, with the dissolve (the loop's continuation fading into its start) inside it. The long
    video is i, b, then (a, b) repeated, all stream copy."""
    P = plan_of(scene, cfg)
    s, o, N, D, K, fps = P["s"], P["o"], P["N"], P["D"], P["K"], P["fps"]
    src = str(cfg["_src"])
    out = ROOT / "out" / scene / "render" / tag
    out.mkdir(parents=True, exist_ok=True)
    enc = enc_args(cfg)
    rate = "60000/1001" if P["fps_num"] else f"{fps}"
    import color_grade as CG
    gv = grade_vf(cfg.get("grade"))
    g_ = f"{gv}," if gv else ""
    look = CG.clean(cfg.get("grade"))
    if (out / "window.json").exists():
        old = json.loads((out / "window.json").read_text())
        if CG.clean(old.get("grade")) != look or old.get("source") != cfg["source"]:
            sys.exit(f"{out} holds a window of {old.get('source')} with grade {CG.describe(old.get('grade'))}; footage.json "
                     f"now says {cfg['source']} with grade {CG.describe(look)}: give the new one its own --tag")
    stamp = {**P, "tag": tag, "encoder": {**ENC, **(cfg.get("encoder") or {})}, "intro": cfg.get("intro"), "source": cfg["source"],
             "grade": look}
    # stamped before encoding too, so pieces left by a stopped run are never reused under another look
    (out / "window.json").write_text(json.dumps({**stamp, "complete": False}, indent=1))
    log(f"window {tag}: loop src[{s}, {s + N}) with src[{s + N}, {s + N + D}) dissolving into its start; the window opens "
        f"{o} frames in (source frame {s + o}, {(s + o) / fps:.1f} s); the dissolve plays {(N - o) / fps:.1f} s into it"
        + (f"; grade {CG.describe(look)}" if gv else ""))
    if not (out / "a.mp4").exists():
        run(["-ss", ss(s + o, fps), "-i", src, "-map", "0:v:0", "-vf", f"trim=end_frame={K},setpts=PTS-STARTPTS,{g_}format=p010le",
             "-frames:v", str(K), *enc, str(out / "a.new.mp4")], "a (the first 12 s)")
        (out / "a.new.mp4").replace(out / "a.mp4")
    if cfg.get("intro") and not (out / "i.mp4").exists():
        png, x0, y0, T = draw_intro(scene, cfg, out)
        t_out = T["at"] + T["fade_in"] + T["hold"]
        fc = (f"[0:v]trim=end_frame={K},setpts=PTS-STARTPTS,{g_}format=yuv422p10le[v];"
              f"[1:v]format=rgba,fade=t=in:st={T['at']}:d={T['fade_in']}:alpha=1,fade=t=out:st={t_out}:d={T['fade_out']}:alpha=1,"
              f"scale=out_color_matrix=bt709:out_range=tv,format=yuva422p10le[t];"
              f"[v][t]overlay=x={x0}:y={y0}:format=yuv422p10:shortest=1,format=p010le[o]")
        run(["-ss", ss(s + o, fps), "-i", src, "-loop", "1", "-framerate", rate, "-i", str(png), "-filter_complex", fc,
             "-map", "[o]", "-frames:v", str(K), *enc, str(out / "i.new.mp4")], "i (the first 12 s with the title)")
        (out / "i.new.mp4").replace(out / "i.mp4")
    if not (out / "b.mp4").exists():
        fc = (f"[0:v]trim=end_frame={N - o - K},setpts=PTS-STARTPTS[b1];"
              f"[1:v]trim=end_frame={D},setpts=PTS-STARTPTS[c];"
              f"[2:v]trim=end_frame={o},setpts=PTS-STARTPTS[h];"
              f"[c][h]xfade=transition=fade:duration={D / fps:.6f}:offset=0[x];"
              f"[b1][x]concat=n=2:v=1:a=0,{g_}format=p010le[o]")
        run(["-ss", ss(s + o + K, fps), "-i", src, "-ss", ss(s + N, fps), "-i", src, "-ss", ss(s, fps), "-i", src,
             "-filter_complex", fc, "-map", "[o]", "-frames:v", str(N - K), *enc, str(out / "b.new.mp4")], "b (the rest, with the dissolve)")
        (out / "b.new.mp4").replace(out / "b.mp4")
    (out / "window.json").write_text(json.dumps({**stamp, "complete": True, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    return out


class Bed:
    """The water bed on its circle: any absolute sample range, read modulo the period."""

    def __init__(self, x):
        self.x = x
        self.P = len(x)

    def __call__(self, n0, n1):
        idx = np.arange(n0, n1) % self.P
        return self.x[idx].astype(np.float64)


def water(scene, cfg):
    """The periodic water bed at its own loudness (footage.json water.lufs), built once and cached by its code and
    settings."""
    import hashlib
    import water_bed as WB
    from audio_analyze import integrated_lufs, k_weight
    w = {"lufs": -23.0, "period_s": 1200, **(cfg.get("water") or {})}
    from cozy.code import code_hash
    key = hashlib.sha1(code_hash("water_bed").encode() + json.dumps(
        [w["lufs"], w["period_s"], w.get("cfg"), cfg.get("seed")], sort_keys=True).encode()).hexdigest()[:16]
    c = ROOT / "cache" / scene / "footage" / f"water_bed_{key}.npy"
    c.parent.mkdir(parents=True, exist_ok=True)
    if not c.exists():
        log(f"water: building {w['period_s']} s of bed (tools/water_bed.py)")
        x = WB.normalize(WB.build(w["period_s"], int(cfg.get("seed", 1022)), w.get("cfg")), w["lufs"])
        np.save(c, x.astype(np.float32))
        log(f"water: {integrated_lufs(k_weight(x)):.1f} LUFS, peak {20 * np.log10(np.abs(x).max()):.1f} dBFS -> {c.name}")
    return Bed(np.load(c)), w, key


def gray_frame(video, k, fps, vf=None):
    """Frame k of a video at 640x360 grey (seek a half frame early: the first frame at or after is frame k), through vf
    first (the grade, to compare a graded render with its source)."""
    raw = grab_frame(video, f"{max(0.0, (k - 0.5) / fps):.6f}", frames=1,
                     vf=f"{vf + ',' if vf else ''}scale={W}:{H}:flags=area,format=gray")
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.float64)


def psnr(a, b):
    return float(10 * np.log10(255 ** 2 / max(np.mean((a - b) ** 2), 1e-9)))


def short_term(x, SR=48000, win=3.0):
    """Short-term loudness (K-weighted, 3 s windows every 0.5 s) of stereo samples, LUFS."""
    from audio_analyze import k_weight
    p = (k_weight(x) ** 2).sum(axis=1)
    n, hop = int(win * SR), SR // 2
    return np.array([-0.691 + 10 * np.log10(p[i:i + n].mean() + 1e-12) for i in range(0, max(len(p) - n, 0) + 1, hop)])


def opener_for(mcfg, water_lufs, seed, scene, dur):
    """The track whose first 30 s stays loudest over the water (its 10th percentile of short-term loudness at the bus
    gain), among those at their level within opener_lead s. Why (the aquarium, 2026-10-22): music.py's `lead` said
    Lilypad was at its level at once, but its first minute sat 7 dB under its body and the water was louder at times;
    the audio model heard only water in the opening."""
    import music as M
    probe_plan = M.plan({"seed": seed, "duration": 600.0, "scene": scene}, None, {**mcfg, "opener": None})
    best = None
    for t in probe_plan["tracks"]:
        if t["lead"] > mcfg.get("opener_lead", 5.0):
            continue
        x = np.asarray(M.decoded(t["path"])[1][t["in"]: t["in"] + 30 * M.SR], np.float64) * 10 ** (t["gain_db"] / 20)
        p10 = float(np.percentile(short_term(x), 10))
        if best is None or p10 > best[0]:
            best = (p10, t["title"])
    log(f"music: opener {best[1]} (its first 30 s at least {best[0]:.1f} LUFS 90% of the time; the water {water_lufs:g})")
    return best[1]


def soundtrack(scene, cfg, dur, out):
    """The video's sound for [0, dur): the water bed (footage.json `water`) under the music planned over the whole length
    (tools/music.py; the opener footage.json names, else the one that leads the water), fades at the very start and
    end, the local limiter, AAC 384k, encoded again with lower ceilings where the encode overshoots -2 dBTP (as
    tools/loop_master.py). A finished mix with the same plan, water and length is reused (music_mix.json).
    -> dict: m4a, plan, ptxt, psha, spots, bed, wcfg, wkey, mcfg, g (the water's gain under the music)"""
    import hashlib
    import loop_master as LM
    import music as M
    SR = M.SR
    nsamp = int(round(dur * SR))
    bed, wcfg, wkey = water(scene, cfg)
    mcfg = {**M.DEFAULTS, **(cfg.get("music") or {})}
    if not mcfg.get("opener"):
        mcfg["opener"] = opener_for(mcfg, wcfg["lufs"] + mcfg["ambience_db"], int(cfg.get("seed", 1022)), scene, dur)
    plan = M.plan({"seed": int(cfg.get("seed", 1022)), "duration": dur, "scene": scene}, None, mcfg)
    if not plan["entries"]:
        sys.exit("no music tracks with complete sidecars")
    ptxt = json.dumps(plan, indent=1)
    psha = hashlib.sha1(ptxt.encode()).hexdigest()[:16]
    op = plan["tracks"][plan["entries"][0]["track"]]
    log(f"music: {len(plan['tracks'])} tracks, {len(plan['entries'])} plays; opens with {op['title']} (normal level after {op['lead']:g} s); "
        f"water {wcfg['lufs'] + mcfg['ambience_db']:g} LUFS under the music bus at {mcfg['lufs']:g}")
    fade_in, fade_out = 1.5, 2.0
    g = 10 ** (mcfg["ambience_db"] / 20)

    def mix(n0, n1, spots=()):
        mg = SR // 4
        s0, s1 = max(0, n0 - mg), min(nsamp, n1 + mg)
        t = np.arange(s0, s1) / SR
        env = np.clip(t / fade_in, 0, 1) * np.clip((dur - t) / fade_out, 0, 1)
        amb = bed(s0, s1) * (g * (0.5 - 0.5 * np.cos(np.pi * env)))[:, None]
        bus = M.render(plan, s0 / SR, (s1 - s0) / SR)
        return M.limit(amb + bus, s0, spots=spots)[n0 - s0: n1 - s0]

    m4a, new_a = out / "music_mix.m4a", out / "music_mix.new.m4a"
    stamp = out / "music_mix.json"
    key = {"plan_sha1": psha, "water": wkey, "ambience_db": mcfg["ambience_db"], "samples": nsamp}
    done = json.loads(stamp.read_text()) if stamp.exists() and m4a.exists() else {}
    if done.get("key") == key:
        spots = [tuple(x) for x in done["spots"]]
        log(f"music mix: reusing {m4a.name} (same plan and water)")
    else:
        spots = []
        for attempt in range(1, 4):
            enc = LM.encoder(new_a)
            C = 60 * SR
            t0 = time.time()
            for c0 in range(0, nsamp, C):
                c1 = min(nsamp, c0 + C)
                LM.put(enc, mix(c0, c1, spots))
                if (c1 // C) % 60 == 0 or c1 == nsamp:
                    el = time.time() - t0
                    log(f"music mix: {c1 / SR / 60:.0f} of {dur / 60:.0f} min (pass {attempt}), "
                        f"about {(nsamp - c1) / max(c1 / el, 1) / 60:.0f} min left")
            LM.finish(enc, "music mix")
            hot = LM.overshoots(new_a)
            if not hot or attempt == 3:
                if hot:
                    log(f"music mix: after {attempt} passes {len(hot)} transient(s) still over -2 dBTP, worst {max(t for _, t in hot):+.1f}")
                break
            log(f"music mix: the AAC encode goes over -2 dBTP at {len(hot)} transient(s); lowering the ceiling there and encoding again")
            for smp, tp in hot:
                cur = min([db for a0_, a1_, db in spots if a0_ <= smp < a1_], default=-2.5)
                spots.append((smp - SR // 20, smp + SR // 20, round(cur - (tp + 2.0) - 0.5, 2)))
        LM.swap_in(new_a, m4a)
        stamp.write_text(json.dumps({"key": key, "spots": spots}))
        log("music mix encoded (AAC 384k)" + (f"; {len(spots)} transient(s) held lower" if spots else ""))
    return {"m4a": m4a, "plan": plan, "ptxt": ptxt, "psha": psha, "spots": spots, "bed": bed, "wcfg": wcfg, "wkey": wkey,
            "mcfg": mcfg, "g": g}


def audio_checks(snd, dur, over_s=None):
    """QA of a soundtrack: loudness and true peak of the encoded mix, the first 24 song changes, the water bed's own
    wrap (when the video is longer than its period), the music leading the opening, and the music over the water
    (user 2026-10-23: the music louder than both) over the first over_s seconds (default: all)."""
    import loop_master as LM
    import music as M
    SR = M.SR
    plan, bed, wcfg, mcfg, g, m4a = snd["plan"], snd["bed"], snd["wcfg"], snd["mcfg"], snd["g"], snd["m4a"]
    checks = {}
    lu = LM.ebu(m4a)
    want = M.mix_target(wcfg["lufs"], mcfg)
    checks["music_loudness"] = {"pass": lu["lufs"] is not None and abs(lu["lufs"] - want) <= 1.5 and lu["true_peak"] <= -1.5, **lu,
                                "target": f"{want - 1.5:.1f}..{want + 1.5:.1f} LUFS (music bus {mcfg['lufs']:g}, water "
                                          f"{wcfg['lufs'] + mcfg['ambience_db']:g}), true peak <= -1.5 dBTP"}
    tr = M.transitions(plan, 24)
    dips = [x["dip_db"] for x in tr]
    worst = max(tr, key=lambda x: x["dip_db"]) if tr else None
    checks["music_transitions"] = {"pass": not (dips and max(dips) > 6.0), "changes": len(tr),
                                   "dip_median_db": round(float(np.median(dips)), 2) if dips else None,
                                   "dip_max_db": max(dips) if dips else None,
                                   "worst": f"{worst['from']} -> {worst['to']} at {worst['at_s']:.0f} s" if worst else None}
    if dur > wcfg["period_s"] + 10:
        checks["water_join"] = {**LM.join_audio(m4a, wcfg["period_s"], level=False), "at_s": wcfg["period_s"],
                                "detail": "where the water bed comes round again: no step"}
    # the music leads from the start (strong opening): 4-34 s, the music bus 3 dB over the water 90% of the time
    sm = short_term(M.render(plan, 4.0, 30.0))
    sw = short_term(bed(4 * SR, 34 * SR) * g)
    lead_db = float(np.percentile(sm - sw, 10))
    checks["music_opening"] = {"pass": lead_db >= 3.0, "music_over_water_p10_db": round(lead_db, 1),
                               "music_median_lufs": round(float(np.median(sm)), 1), "water_median_lufs": round(float(np.median(sw)), 1),
                               "opener": plan["tracks"][plan["entries"][0]["track"]]["title"],
                               "detail": "4-34 s: the music 3 dB or more over the water 90% of the time"}
    # the music over the water: short-term loudness (3 s) of the music bus and of the water as mixed, in 5 minute chunks.
    # Judged while the music plays (within 12 dB of its bus level): Minecraft's pieces rest now and then (the cut's
    # longest rest, 34 s in One More Day, sat at -33 LUFS, 17 dB under its level), and keeping the music over the water
    # there would mean the water all but vanishing at every rest, so the rests are reported, not judged.
    span = float(over_s or dur) - 6.0
    sm, sw = [], []
    for a in np.arange(4.0, 4.0 + span, 300.0):
        L = min(300.0, 4.0 + span - a)
        if L < 10:
            break
        sm.append(short_term(M.render(plan, a, L)))
        sw.append(short_term(bed(int(a * SR), int((a + L) * SR)) * g))
    sm, sw = np.concatenate(sm), np.concatenate(sw)
    playing = sm >= mcfg["lufs"] - 12.0
    d = (sm - sw)[playing]
    share = float((d > 0).mean())
    checks["music_over_water"] = {"pass": share >= 0.95 and float(np.median(d)) >= 6.0, "share_music_louder_while_playing": round(share, 3),
                                  "median_db": round(float(np.median(d)), 1), "p5_db": round(float(np.percentile(d, 5)), 1),
                                  "rests_share": round(float(1 - playing.mean()), 3),
                                  "detail": f"3 s loudness of the music over the water, {span / 60:.0f} min from 0:04, while the music plays "
                                            "(within 12 dB of its level); pass: louder 95% of the time and by 6 dB or more in the median. "
                                            "In the rests the water carries."}
    return checks


def cut(scene, cfg, tag):
    """The review cut (user 2026-10-23: start at 09:06, and no 10 h loop yet: he wants to see the new cut with the audio
    reworked first): the source from footage.json `in` (seconds) to its
    end (or `out`), encoded once with the window's encoder settings (and `grade`, if set), with the soundtrack the 10 h
    will have (soundtrack()); no loop and no opening line. Also water_only_60s.wav: the first minute of the water alone,
    at its own level. -> out/<scene>/render/<tag>/cut_music.mp4, qa.md"""
    import music as M
    src = cfg["_src"]
    v = probe_video(src)
    fps = v["fps"]
    k0 = int(np.ceil(float(cfg.get("in", 0.0)) * fps - 1e-6))          # the first frame at or after `in`
    k1 = v["frames"] if cfg.get("out") is None else int(np.floor(float(cfg["out"]) * fps))
    frames = k1 - k0
    dur = frames / fps
    out = ROOT / "out" / scene / "render" / tag
    out.mkdir(parents=True, exist_ok=True)
    import color_grade as CG
    gv = grade_vf(cfg.get("grade"))
    log(f"cut {tag}: {cfg['source']} frames {k0} to {k1 - 1} ({k0 / fps // 60:.0f}:{k0 / fps % 60:04.1f} to the end), "
        f"{int(dur // 60)}:{dur % 60:04.1f} long" + (f", grade {CG.describe(cfg.get('grade'))}" if gv else ""))
    vid = out / "video.mp4"
    stamp = {"source": cfg["source"], "k0": k0, "k1": k1, "grade": CG.clean(cfg.get("grade")) or None,
             "encoder": {**ENC, **(cfg.get("encoder") or {})}}
    old = json.loads((out / "cut.json").read_text()) if (out / "cut.json").exists() else {}
    if vid.exists() and old.get("video") != stamp:
        sys.exit(f"{vid} was cut with other settings ({old.get('video')}): give the new cut its own --tag")
    if not vid.exists():
        run(["-ss", ss(k0, fps), "-i", str(src), "-map", "0:v:0", "-vf", f"{gv + ',' if gv else ''}format=p010le",
             "-frames:v", str(frames), *enc_args(cfg), str(out / "video.new.mp4")], "the cut's picture")
        (out / "video.new.mp4").replace(vid)
        (out / "cut.json").write_text(json.dumps({"video": stamp}, indent=1))
    snd = soundtrack(scene, cfg, dur, out)
    final = out / "cut_music.mp4"
    run_ffmpeg(["-v", "error", "-y", "-i", str(vid), "-i", str(snd["m4a"]), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                "-movflags", "+faststart", str(out / "cut_music.new.mp4")], capture=False)
    (out / "cut_music.new.mp4").replace(final)
    import water_bed as WB
    WB.write_wav(out / "water_only_60s.wav", snd["bed"](0, 60 * M.SR))
    # QA
    checks = {}
    fv = probe(final, "stream=duration,nb_frames", streams="v:0")["streams"][0]
    vd, nf = float(fv["duration"]), int(fv["nb_frames"])
    ad = float(probe(final, "stream=duration", streams="a:0")["streams"][0]["duration"])
    checks["length_sync"] = {"pass": nf == frames and abs(vd - dur) < 0.05 and abs(ad - dur) < 0.05, "frames": nf, "expected": frames,
                             "video_s": vd, "audio_s": ad}
    ends = []
    for m, e in ((0, k0), (frames // 2, k0 + frames // 2), (frames - 1, k1 - 1)):
        f = gray_frame(final, m, fps)
        own = psnr(f, gray_frame(src, e, fps, gv))
        nbr = max(psnr(f, gray_frame(src, e + dd, fps, gv)) for dd in (-1, 1) if 0 <= e + dd < v["frames"])
        ends.append({"frame": m, "source": e, "psnr": round(own, 2), "neighbours": round(nbr, 2), "pass": own >= 30 and own > nbr + 0.5})
    checks["frames"] = {"pass": all(x["pass"] for x in ends), "frames": ends,
                        "detail": "the cut's first, middle and last frames decode as their own source frames"}
    checks.update(audio_checks(snd, dur))
    ok = all(c["pass"] for c in checks.values())
    (out / "music_plan.json").write_text(snd["ptxt"])
    (out / "cut.json").write_text(json.dumps({"video": stamp, "duration_s": dur, "fps": fps, "music": {"plan_sha1": snd["psha"],
                                              "tracks": len(snd["plan"]["tracks"]), "plays": len(snd["plan"]["entries"])},
                                              "water": {**snd["wcfg"], "key": snd["wkey"]}, "qa": {"pass": ok, "checks": checks},
                                              "created": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1))
    rows = "\n".join(f"| {k} | {'PASS' if c['pass'] else 'FAIL'} | {json.dumps({x: y for x, y in c.items() if x != 'pass'})} |"
                     for k, c in checks.items())
    (out / "qa.md").write_text(f"# QA: {scene} {tag}\n\n{cfg['source']} from frame {k0} ({k0 / fps:.2f} s) to the end, {dur:.3f} s, "
                               f"with the water and the music as the 10 h will have them (no loop).\n\nOverall: **{'PASS' if ok else 'FAIL'}**"
                               f"\n\n| Check | Result | Detail |\n|---|---|---|\n{rows}\n", encoding="utf-8")
    log(f"QA {'PASS' if ok else 'FAIL'}: " + ", ".join(f"{k} {'PASS' if c['pass'] else 'FAIL'}" for k, c in checks.items()))
    log(f"done -> {final}")
    return ok


def master(scene, cfg, wtag, tag):
    """The long video: i, b, then (a, b) repeated (stream copy), with the water and the music planned over its whole
    length (tools/music.py), mixed through the local limiter and encoded once to AAC 384k, re-encoded with lower
    ceilings where the AAC encode overshoots (as tools/loop_master.py does); then QA."""
    import shutil
    import loop_master as LM
    import music as M
    import color_grade as CG
    SR = M.SR
    wd = ROOT / "out" / scene / "render" / wtag
    P = json.loads((wd / "window.json").read_text())
    if P.get("complete") is False:
        sys.exit(f"{wd} isn't finished: run `footage_loop.py window {scene} --tag {wtag}` again")
    s, o, N, D, K, fps = P["s"], P["o"], P["N"], P["D"], P["K"], P["fps"]
    target = float(cfg.get("target_s", 36000))                         # 10 h unless footage.json says otherwise
    T = int(cfg.get("times") or max(1, int(target // (N / fps))))
    out = ROOT / "out" / scene / "render" / tag
    out.mkdir(parents=True, exist_ok=True)
    pieces = {p: wd / f"{p}.mp4" for p in ("a", "i", "b")}
    first = pieces["i"] if pieces["i"].exists() else pieces["a"]
    seq = [first, pieces["b"]] + [pieces["a"], pieces["b"]] * (T - 1)
    frames = T * N
    want = target if not cfg.get("times") else T * float(cfg.get("loop_seconds", 1200))
    if want - frames / fps > K / fps:
        sys.exit(f"{T} loops of {N / fps:.1f} s leave {want - frames / fps:.0f} s to fill: pick loop_seconds that divides "
                 f"{want:g} s (the tail can only add the window's first {K / fps:.0f} s once or twice)")
    extra = 0
    while frames / fps < want - 1e-6:
        # At 59.94 fps 30 windows of 1200 s fall 36 ms short of 10 h, and YouTube shows whole seconds (9:59:59 under
        # a "10 hours" title): the first 12 s once more, which follow the last b seamlessly
        seq.append(pieces["a"])
        frames += K
        extra += 1
    vtxt = out / "video.txt"
    vtxt.write_text("".join(f"file '{p.as_posix()}'\n" for p in seq))
    dur = frames / fps
    checks = {}

    # pieces: their frame counts and identical parameter sets (stream copy needs them)
    def nb(p):
        return int(probe(p, "stream=nb_read_packets", streams="v:0", args=["-count_packets"], check=False)["streams"][0]["nb_read_packets"])

    def xh(p):
        s = probe(p, "stream=extradata_hash", streams="v:0", args=["-show_data_hash", "sha256"], check=False).get("streams") or [{}]
        return s[0].get("extradata_hash", "")
    counts = {k: nb(p) for k, p in pieces.items() if p.exists()}
    hashes = {k: xh(p) for k, p in pieces.items() if p.exists()}
    checks["pieces"] = {"pass": counts.get("a") == K and counts.get("b") == N - K and counts.get("i", K) == K
                        and len(set(hashes.values())) == 1, "frames": counts, "same_parameter_sets": len(set(hashes.values())) == 1}
    vbytes = sum(p.stat().st_size for p in seq)
    proj = vbytes + 384000 / 8 * dur
    checks["size"] = {"pass": proj < 250e9, "projected_gb": round(proj / 1e9, 1), "video_mbps": round(vbytes * 8 / dur / 1e6, 1),
                      "detail": "under YouTube's 256 GB with room to spare"}
    log(f"master {tag}: {T} x {N} frames" + (f" + {extra} x {K}" if extra else "") + f" = {dur:.3f} s ({dur / 3600:.3f} h), "
        f"about {proj / 1e9:.1f} GB ({checks['size']['video_mbps']} Mbit/s video); pieces {counts}")
    if not checks["pieces"]["pass"] or not checks["size"]["pass"]:
        sys.exit(f"stopping: {checks}")

    # audio: the water bed under the music, planned over the whole video
    snd = soundtrack(scene, cfg, dur, out)
    plan, ptxt, psha, spots, wcfg, wkey, mcfg, m4a = (snd[k] for k in ("plan", "ptxt", "psha", "spots", "wcfg", "wkey", "mcfg", "m4a"))

    # the video: stream copy of the pieces, muxed with the mix
    mm, new_v = out / "master_music.mp4", out / "master_music.new.mp4"
    free = shutil.disk_usage(out).free
    if free < proj + 5e9:
        sys.exit(f"master_music.mp4 needs about {proj / 1e9:.0f} GB free, {free / 1e9:.0f} GB is free")
    log("mux: stream copy of the pieces with the mix")
    LM.mux(vtxt, m4a, new_v, False)
    LM.swap_in(new_v, mm)
    log(f"master_music.mp4 muxed ({mm.stat().st_size / 1e9:.1f} GB)")

    # QA
    mv = probe(mm, "stream=duration,nb_frames", streams="v:0")["streams"][0]
    vd, nf = float(mv["duration"]), int(mv["nb_frames"])
    ad = float(probe(mm, "stream=duration", streams="a:0")["streams"][0]["duration"])
    checks["length_sync"] = {"pass": nf == frames and abs(vd - dur) < 0.05 and abs(ad - dur) < 0.05, "frames": nf, "expected": frames,
                             "video_s": vd, "audio_s": ad}
    src = cfg["_src"]
    gq = grade_vf(P.get("grade"))                      # the window's own look: its frames are compared with graded source frames

    def expect(m):
        """Source frame shown at master frame m (None inside the dissolve)."""
        i = (o + m % N) % N
        return None if i < D else s + i

    joins = []
    for m in [K - 1, K, N - 1, N, N + K - 1, N + K, 2 * N - 1, 2 * N, (T - 1) * N + K, T * N - 1, T * N, frames - 1]:
        if m >= frames:
            continue
        e = expect(m)
        if e is None:
            continue
        f = gray_frame(mm, m, fps)
        own = psnr(f, gray_frame(src, e, fps, gq))
        nbr = max(psnr(f, gray_frame(src, e + d, fps, gq)) for d in (-1, 1))
        joins.append({"frame": m, "source": e, "psnr": round(own, 2), "neighbours": round(nbr, 2), "pass": own >= 30 and own > nbr + 0.5})
    checks["joins"] = {"pass": all(j["pass"] for j in joins), "frames": joins,
                       "detail": "frames each side of every kind of join decode as their own source frame (better than its neighbours)"}
    jd = N - o                                         # the dissolve's first window frame
    mid = jd + D // 2
    f = gray_frame(mm, N + mid, fps)
    i_mid = (o + mid) % N
    A, B = gray_frame(src, s + N + i_mid, fps, gq), gray_frame(src, s + i_mid, fps, gq)
    w_ = i_mid / D
    blend = psnr(f, (1 - w_) * A + w_ * B)
    checks["dissolve"] = {"pass": blend >= 30 and blend > max(psnr(f, A), psnr(f, B)), "at_s": round((N + mid) / fps, 2),
                          "psnr_blend": round(blend, 2), "psnr_continuation": round(psnr(f, A), 2), "psnr_start": round(psnr(f, B), 2),
                          "detail": f"mid-dissolve frame is the blend of the loop's continuation and its start ({D} frames, "
                                    f"{(N - o) / fps:.1f} s into every window)"}
    checks.update(audio_checks(snd, dur, over_s=min(dur, 1800.0)))
    ok = all(c["pass"] for c in checks.values())
    (out / "music_plan.json").write_text(ptxt)
    (out / "credits.txt").write_text(M.credits(plan), encoding="utf-8")
    info = {"source": str(src), "window": str(wd), "times": T, "tail_pieces": extra, "loop_frames": N, "fps": fps, "duration_s": dur, "loop_start": s,
            "opening": o, "xfade_frames": D, "intro_frames": K, "grade": P.get("grade") or {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "music": {"tracks": len(plan["tracks"]), "plays": len(plan["entries"]), "music_dir": plan["dirs"], "plan_sha1": psha,
                      "limited_spots": [[round((a0_ + SR // 20) / SR, 3), db] for a0_, _, db in spots]},
            "water": {**wcfg, "key": wkey}, "qa": {"pass": ok, "checks": checks}}
    (out / "loop.json").write_text(json.dumps(info, indent=1))
    rows = "\n".join(f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | {json.dumps({x: y for x, y in v.items() if x != 'pass'})} |"
                     for k, v in checks.items())
    (out / "qa.md").write_text(
        f"# QA: {scene} {tag}\n\n{cfg['source']} looped {T} times (tools/footage_loop.py)"
        + (f", then its first {K} frames once more so it runs a full {want / 3600:g} h ({dur:.3f} s)" if extra else "")
        + f": the loop is source frames {s}-{s + N} "
        f"({N / fps:.2f} s), its continuation dissolving into its start over {D} frames; the video opens {o} frames into the loop "
        f"(source frame {s + o}), the first {K} frames carry the intro line. Water (tools/water_bed.py, {wcfg['period_s']} s "
        f"periodic) under {len(plan['tracks'])} tracks planned over the whole video ({len(plan['entries'])} plays; music_plan.json). "
        f"Color: {CG.describe(P.get('grade'))}.\n\n"
        f"Overall: **{'PASS' if ok else 'FAIL'}**\n\n| Check | Result | Detail |\n|---|---|---|\n{rows}\n", encoding="utf-8")
    log(f"QA {'PASS' if ok else 'FAIL'}: " + ", ".join(f"{k} {'PASS' if v['pass'] else 'FAIL'}" for k, v in checks.items()))
    log(f"done -> {mm}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["analyze", "seam", "heroes", "grades", "cut", "window", "master"])
    ap.add_argument("scene")
    ap.add_argument("--tag", default="loop20_v1", help="window (or cut) folder under out/<scene>/render/")
    ap.add_argument("--name", default="10h_v1", help="master: output folder under out/<scene>/render/")
    ap.add_argument("--frame", type=int, help="grades: the source frame to show (default: the video's first frame)")
    a = ap.parse_args()
    cfg = load_cfg(a.scene)
    if a.cmd == "analyze":
        analyze(a.scene, cfg)
    elif a.cmd == "seam":
        seam(a.scene, cfg)
    elif a.cmd == "heroes":
        heroes(a.scene, cfg)
    elif a.cmd == "grades":
        grades(a.scene, cfg, a.frame)
    elif a.cmd == "cut":
        sys.exit(0 if cut(a.scene, cfg, a.tag if a.tag != "loop20_v1" else "cut_v1") else 1)
    elif a.cmd == "window":
        window(a.scene, cfg, a.tag)
    elif a.cmd == "master":
        sys.exit(0 if master(a.scene, cfg, a.tag, a.name) else 1)


if __name__ == "__main__":
    main()
