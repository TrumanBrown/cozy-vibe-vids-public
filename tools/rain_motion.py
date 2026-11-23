"""Where the rain moves: the most each pixel changes over a short stretch of a render, so holes in the rain show.

Found on the Minecraft tea house (2026-10-22, lessons L121): the outdoor check had cut the rain in front of the
pavilion across the pond, the far buildings and the cherry's trunk, reading them as the room's own structure, and no
check showed it. weather_audit counts the outdoor check's cuts as dry on purpose, the static check looks for things
that should move, and in a still the faint rain is easy to miss. Over a dozen frames the rain leaves bright streaks
everywhere it falls, and a false cut is a dark hole in the shape of the thing (out/local_vision/rain_holes.jpg).

  .venv\\Scripts\\python tools\\rain_motion.py <render dir or mp4> [--at 90] [--frames 12] [--box x,y,w,h]

Writes <render>/review/rain_motion.jpg (next to an mp4: <name>_rain_motion.jpg): a frame on the left, the motion on
the right (x10; at quarter size each pixel shows the most its 4x4 block moved, so thin streaks stay). With --box, that
part at 1:1 (_box_<x>_<y> added to the name). Look at every far building, wall, roof, lantern and tree out in the view:
rain must move in front of them. Dark is right only where something near stands in front (a post, the eaves, a
railing's bars), under the roof, and in the sky far above the rain's top. review.py makes it on every render review.
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np
from PIL import Image

from cozy.paths import ROOT
from cozy.media import grab_frame, probe as media_probe


def probe(video):
    j = media_probe(video, "stream=width,height,r_frame_rate:format=duration", streams="v:0")
    s = j["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return int(s["width"]), int(s["height"]), num / max(den, 1), float(j["format"].get("duration") or 0)


def grab(video, at, n, box, fmt, ch):
    x, y, w, h = box
    a = np.frombuffer(grab_frame(video, f"{at:.3f}", frames=n, vf=f"crop={w}:{h}:{x}:{y}", pix_fmt=fmt), np.uint8)
    k = a.size // (w * h * ch)
    return a[: k * w * h * ch].reshape(k, h, w, ch) if ch > 1 else a[: k * w * h].reshape(k, h, w)


def motion_map(video, at=90.0, n=12, box=None):
    """(first frame RGB, motion 0-255) over n frames from `at` s (clamped into the video), inside box (x, y, w, h)."""
    W, H, fps, dur = probe(video)
    box = box or (0, 0, W, H)
    at = max(0.0, min(at, dur - (n + 2) / max(fps, 1.0) - 0.5)) if dur else at
    gray = grab(video, at, n, box, "gray", 1).astype(np.float32)
    if len(gray) < 2:
        raise SystemExit(f"rain_motion: got {len(gray)} frame(s) from {video} at {at:.1f} s")
    m = np.abs(np.diff(gray, axis=0)).max(axis=0)
    rgb = grab(video, at, 1, box, "rgb24", 3)[0]
    return rgb, np.clip(m * 10, 0, 255).astype(np.uint8), at


def panel(rgb, mot, scale, boxes=()):
    h, w = mot.shape
    if scale > 1:
        hh, ww = h // scale * scale, w // scale * scale
        mot = mot[:hh, :ww].reshape(hh // scale, scale, ww // scale, scale).max(axis=(1, 3))
    left = Image.fromarray(rgb).resize((mot.shape[1], mot.shape[0]), Image.LANCZOS)
    out = Image.new("RGB", (2 * mot.shape[1], mot.shape[0]))
    out.paste(left, (0, 0))
    out.paste(Image.fromarray(np.stack([mot] * 3, axis=2)), (mot.shape[1], 0))
    if boxes:
        from PIL import ImageDraw
        d = ImageDraw.Draw(out)
        k = mot.shape[1]
        for x0, y0, x1, y1 in boxes:     # frame fractions
            for off in (0, k):
                d.rectangle((off + x0 * k, y0 * mot.shape[0], off + x1 * k - 1, y1 * mot.shape[0] - 1), outline=(255, 40, 40))
    return out


FAINT_LEVEL = 0.3   # mean frame-to-frame change (8-bit levels, 1920 px wide) under which a block of open rain shows none
FAINT_DARK = 64     # only blocks this dark count (the plate's mean, 8-bit): against a bright sky real rain hardly shows
FAINT_SHARE = 0.10  # review.py fails a render when more of the open rain area than this is dark and faint


def faint_rain(video, plate_dir, at=90.0, n=24, block=60, cover=0.9, level=FAINT_LEVEL, dark=FAINT_DARK):
    """Where the rain falls in front of the dark but doesn't show (lessons L152): blocks of the open rain area (the
    plate's outdoor mask over `cover` of a block of `block` px at 1920 px wide) on dark plate (mean under `dark`) whose
    mean frame-to-frame change over n frames stays under `level` levels. Found on the Burdock Shelter (2026-10-25): its
    night forest was in the rain mask, but a drop there was about as dark as the forest (0.12 levels behind the
    salamander, 0.6 once the drops were lifted; the lantern's light 1.9). The approved tea house and farmscape have
    faint blocks too, all against bright sky (plate 86 to 191), none dark. Returns (share of the open rain area that is
    dark and faint, those blocks as frame fractions, blocks checked)."""
    W, H, fps, dur = probe(video)
    at = max(0.0, min(at, dur - (n + 2) / max(fps, 1.0) - 0.5)) if dur else at
    w, h = 1920, int(round(1920 * H / W / 2)) * 2
    a = np.frombuffer(grab_frame(video, f"{at:.3f}", frames=n, vf=f"scale={w}:{h}:flags=area", pix_fmt="gray"), np.uint8)
    fr = a[: a.size // (w * h) * w * h].reshape(-1, h, w).astype(np.float32)
    if len(fr) < 3:
        return 0.0, [], 0
    act = np.abs(np.diff(fr, axis=0)).mean(0)
    lights, plate = pathlib.Path(plate_dir) / "lights.png", pathlib.Path(plate_dir) / "plate.png"
    if not lights.exists() or not plate.exists():
        return 0.0, [], 0
    od = np.asarray(Image.open(lights).convert("RGB").resize((w, h), Image.BOX), np.float32)[..., 1] / 255
    lum = np.asarray(Image.open(plate).convert("L").resize((w, h), Image.BOX), np.float32)
    faint, checked = [], 0
    for y in range(0, h - block + 1, block):
        for x in range(0, w - block + 1, block):
            if od[y:y + block, x:x + block].mean() < cover:
                continue
            checked += 1
            if lum[y:y + block, x:x + block].mean() < dark and act[y:y + block, x:x + block].mean() < level:
                faint.append((x / w, y / h, (x + block) / w, (y + block) / h))
    return (len(faint) / checked if checked else 0.0), faint, checked


def plate_of(src):
    """The plate folder of a render under out/<scene>/render/<tag> (the scene's "plate", else its name)."""
    p = pathlib.Path(src).resolve()
    parts = p.parts
    if "render" not in parts:
        return None
    scene = parts[parts.index("render") - 1]
    sj = ROOT / "scenes" / scene / "scene.json"
    plate = json.loads(sj.read_text(encoding="utf-8")).get("plate", scene) if sj.exists() else scene
    d = ROOT / "out" / "plates" / plate
    return d if d.exists() else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="a render folder (with master.mp4) or an mp4")
    ap.add_argument("--at", type=float, default=90.0, help="start, seconds into the video (clamped into it)")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--box", help="x,y,w,h in video px: that part at 1:1")
    ap.add_argument("--plate", help="plate folder for the faint-rain measure (default: found from the render's scene)")
    a = ap.parse_args()
    src = pathlib.Path(a.src)
    video = src / "master.mp4" if src.is_dir() else src
    if not video.exists():
        print(f"rain_motion: no {video}")
        return 2
    box = tuple(int(v) for v in a.box.split(",")) if a.box else None
    rgb, mot, at = motion_map(video, a.at, a.frames, box)
    scale = 1 if box else max(1, math.ceil(mot.shape[1] / 960))
    boxes = []
    pd = pathlib.Path(a.plate) if a.plate else plate_of(src)
    if pd and not box:
        share, boxes, checked = faint_rain(video, pd, a.at)
        if checked:
            print(f"rain_motion: faint rain in the dark {share:.0%} of the open rain area ({len(boxes)} of {checked} "
                  f"blocks under {FAINT_LEVEL} levels on plate darker than {FAINT_DARK}; red boxes; review fails over "
                  f"{FAINT_SHARE:.0%}, L152)")
    out = (src / "review" / "rain_motion.jpg") if src.is_dir() else video.with_name(video.stem + "_rain_motion.jpg")
    if box:
        out = out.with_name(out.stem + f"_box_{box[0]}_{box[1]}.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    panel(rgb, mot, scale, boxes).save(out, quality=88)
    print(f"rain_motion: {a.frames} frames from {at:.1f} s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
