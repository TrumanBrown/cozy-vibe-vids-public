"""Look at motion in a clip without watching it: a heatmap of where pixels change, plus crop strips over time.

  .venv/Scripts/python tools/motion_review.py <clip.mp4> [--crops "x0,y0,x1,y1;..."] [--times 0,1.5,3,...] [--ask]
  .venv/Scripts/python tools/motion_review.py <clip.mp4> --static <scene>      # what should move but doesn't

Writes next to the clip: <name>_motion.png (temporal standard deviation of luminance over the clip, as a heat
overlay on the first frame: what moves and how much) and <name>_strips.png (each crop at several times, side
by side, at full 4K detail). Crops are fractions of the frame (x0,y0,x1,y1, y from the top); without --crops
the most active areas are picked. --ask sends both images to the vision model for a quick QA opinion
(~$0.03): "does anything look broken or unnatural?".

--static <scene> (the user's standing rule, 2026-10-16: nothing that moves in reality may sit frozen): measures the
motion inside every animated region of the plate (regions.json) and flags regions of moving kinds that barely
change; then asks the vision model which visible things would move in reality (water, drips, steam, smoke,
flames, rain, cloth, leaves, animals) but are still in the heatmap. A flag stands unless the thing itself (SAM
mask from the model's box) keeps changing (persistent_motion: rain and drips falling in front of a frozen cloth
don't count); a thing measured still and at least 1% of the frame fails whatever severity the model gave.
Writes <name>_static.json; exit code 2 if anything is flagged. Run it on every preview before showing it.
"""
import argparse
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT
from cozy.media import grab_frame, probe as media_probe


def probe(path):
    s = media_probe(path, "stream=width,height,r_frame_rate,nb_frames", streams="v:0", check=False)["streams"][0]
    num, den = map(int, s["r_frame_rate"].split("/"))
    return int(s["width"]), int(s["height"]), num / den


def frames_at(path, times, W, H, scale=1.0):
    out = []
    w, h = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
    for t in times:
        raw = grab_frame(path, f"{t:.3f}", frames=1, vf=f"scale={w}:{h}", pix_fmt="rgb24", check=False)
        out.append(np.frombuffer(raw, np.uint8).reshape(h, w, 3))
    return out


def all_frames(path, W, H, fps_out=10, scale=0.25):
    w, h = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
    a = np.frombuffer(grab_frame(path, vf=f"fps={fps_out},scale={w}:{h}", pix_fmt="rgb24", check=False), np.uint8)
    return a.reshape(-1, h, w, 3)


# Least motion (temporal std of luminance, 0..1) a region of each kind must show in a preview. Kinds that only
# move on events (neon buzz, lamps) or not at all are not checked.
MIN_MOTION = {"lantern": 0.0012, "chime": 0.0015, "plant": 0.0012, "curtain": 0.0012, "water": 0.0025, "fire": 0.008, "candle": 0.002,
              "bob": 0.0015, "pet": 0.0006, "glass": 0.003, "clouds": 0.001, "fog": 0.001, "string": 0.001}


def persistent_motion(lum, fps_out=10, lag_s=0.5, rows=48):
    """Motion that persists at each pixel: the 75th percentile over time of |frame(t) - frame(t - 0.5 s)|. Rain
    and drips cross a pixel only now and then (~0 here, though they dominate the temporal std); a swaying cloth,
    rippling water, drifting steam or a breathing pet keep changing it. Calibrated on the ramen alley: still
    things under rain 0.000-0.002, a curtain swaying 3 px 0.004, the canal 0.008, steam 0.05."""
    lag = max(1, int(round(lag_s * fps_out)))
    out = np.zeros(lum.shape[1:], np.float32)
    for y in range(0, lum.shape[1], rows):
        blk = lum[:, y:y + rows]
        out[y:y + rows] = np.percentile(np.abs(blk[lag:] - blk[:-lag]), 75, axis=0)
    return out


_NOTED = set()


def note_once(msg):
    """A check that runs weaker than it should says so in the review output, once."""
    if msg not in _NOTED:
        _NOTED.add(msg)
        print(f"  note: {msg}")


def thing_mask(first, box):
    """The object the vision model meant by a box: SAM 2.1 on the clip's first frame (bool, frame size); None
    without SAM."""
    try:
        from cozy.segment import Segmenter, box_px
    except ImportError as e:
        note_once(f"SAM 2 isn't available ({e}): a flagged thing is measured over its whole box, not its outline")
        return None
    img = Image.fromarray((first * 255).astype(np.uint8))
    global _SEG
    if "_SEG" not in globals():
        _SEG = Segmenter()
    return _SEG.masks(img, [box_px(box, img.width, img.height, grow=0.0)])[0]


# What the vision model calls a thing -> the region kinds that animate it. Steam and drops are drawn by overlay
# layers above or below their regions, so they (and anything no region covers) are measured where SAM finds them.
THING_KINDS = [
    (("cloth", "fabric", "curtain", "banner", "noren", "awning", "canopy", "flag", "drape"), ("curtain", "sway")),
    (("leaf", "leaves", "plant", "tree", "branch", "blossom", "bush", "vine", "foliage", "shrub", "flower"), ("plant", "sway")),
    (("water", "river", "canal", "stream", "lake", "sea", "pond", "harbor"), ("water",)),
    (("lantern", "chime", "mobile"), ("lantern", "chime", "pendulum")),
    (("cat", "dog", "pet", "animal"), ("pet",)),
    (("flame", "fire", "candle"), ("fire", "candle", "bob")),
]


def painted_streaks(pdir, box):
    """How strongly painted rain still shows in the still picture inside box: derain's own streak response on plate.png
    (thin, vertically coherent bright lines, outdoors, away from lights, not warm), the brightest 1% as a luminance
    step (0..1), or None without a plate. The raw art of the Minecraft tea house reads 0.035 (painted rain plainly
    visible), its plate after derain 0.012 (faint, at the edge of what reads at 1:1)."""
    try:
        from cozy.plate.derain import derain_pass
    except ImportError as e:
        note_once(f"cozy.plate.derain can't be imported ({e}): a flagged rain streak is judged without the painted-rain measure")
        return None
    try:
        pl = Image.open(pdir / "plate.png").convert("RGB")
        L = np.asarray(Image.open(pdir / "lights.png").convert("RGB"), np.float32) / 255
    except FileNotFoundError as e:
        note_once(f"no plate to measure painted rain on ({e.filename}): a flagged rain streak is judged by its motion only")
        return None
    _, corr = derain_pass(pl, L[..., 1], L[..., 0], {}, {"strength": 1.0})
    H, W = corr.shape
    x0, y0, x1, y1 = box
    sl = (slice(int(y0 * H), max(int(y1 * H), int(y0 * H) + 1)), slice(int(x0 * W), max(int(x1 * W), int(x0 * W) + 1)))
    c = corr[sl][L[..., 1][sl] > 0.5]
    return float(np.percentile(c, 99)) if c.size else 0.0


RAIN_CLAIM = ("rain", "streak", "drizzle")
NOT_RAIN = ("drop", "drip", "hang", "bead", "puddle", "ring", "gutter", "runoff", "stream", "pour")


def is_rain_claim(what):
    """A claim about falling rain or rain streaks (not hanging drops, drips, puddles or runoff, judged as before)."""
    return any(w in what for w in RAIN_CLAIM) and not any(w in what for w in NOT_RAIN)


def static_check(clip, scene, sd, first, mot, pm):
    """Things that should move but don't: per-region motion vs MIN_MOTION, plus a vision check of the heatmap.
    A vision flag is overruled only when the flagged thing itself keeps moving (persistent_motion >= 0.003),
    measured on the scene's regions of its kind inside its box (cloth -> curtain regions, leaves -> plants...)
    or else on what SAM finds in the box: rain or drips passing in front, or a lantern swinging inside the same
    box, don't count."""
    pdir = ROOT / "out" / "plates" / scene
    regs = json.loads((pdir / "regions.json").read_text(encoding="utf-8")) if (pdir / "regions.json").exists() else []
    # panes the hand file says don't look out (their mask is what stands in front of them): no rain to move there
    hp = ROOT / "assets" / "keyart" / f"{scene}.hand.json"
    no_view = (json.loads(hp.read_text(encoding="utf-8")).get("no_view") or {}) if hp.exists() else {}
    h, w = sd.shape
    ids = np.asarray(Image.open(pdir / "regions.png").convert("RGB").resize((w, h), Image.NEAREST))[..., 0] if regs else None
    rows, flagged = [], []
    for g in regs:
        need = MIN_MOTION.get(g["kind"])
        if need is None or g["name"] in no_view:
            continue
        m = ids == g["id"]
        if g["kind"] == "steam":
            continue
        if m.sum() < 4:
            continue
        v = float(np.percentile(sd[m], 75))
        ok = v >= need
        rows.append({"region": g["name"], "kind": g["kind"], "motion": round(v, 5), "min": need, "ok": ok})
        if not ok:
            flagged.append({"where": g["name"], "problem": f"{g['kind']} region barely moves ({v:.4f} < {need})", "source": "regions"})
    from azure_ai import vision_json
    res, usage = vision_json(
        "Image 1 is the first frame of a short clip from a calm ambience video (one painted image animated in code). Image 2 shows "
        "where pixels change over the clip (bright = moving) on top of it. The video's standing rule: nothing that moves in real life "
        "may sit frozen. List every visible thing that would move in reality but is completely still (dark) in image 2: painted water "
        "drops hanging from edges, painted streams of water, steam or smoke plumes, flames, frozen rain streaks, water surfaces outdoors "
        "(rivers, ponds, the sea, puddles in rain), cloth and leaves outdoors or in an open doorway where air moves, animals. Inside a "
        "closed room, plants, curtains, blankets, quilts and throws hang still in real life: don't list them. Ignore solid things (walls, "
        "furniture, signs) and small things far away. Return JSON "
        "{\"issues\": [{\"what\": \"...\", \"box\": [x0, y0, x1, y1] (fractions, y from top), \"severity\": \"high\"|\"low\"}], "
        "\"moving_well\": [\"...\"]}", images=[Image.fromarray((first * 255).astype(np.uint8)), mot], purpose=f"static:{scene}",
        effort="medium")
    for it in res.get("issues", []):
        sev = it.get("severity", "high")
        b = it.get("box")
        note = "still in the clip"
        if b and len(b) == 4:
            # the model reads a downscaled heatmap: overrule it where the thing itself measurably keeps moving
            # (the scene's regions of that kind inside its box, else what SAM finds in the box)
            x0, y0, x1, y1 = [min(max(float(v), 0.0), 1.0) for v in b]
            inbox = np.zeros((h, w), bool)
            inbox[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)] = True
            what = (it.get("what") or "").lower()
            if is_rain_claim(what):
                # "frozen rain streaks": rain moves by construction, and the persistent measure below leaves rain out on
                # purpose, so it confirmed any such claim (the tea house's gentle rain, faint in the heatmap, 2026-10-22).
                # Painted rain is what can be frozen: it shows in the still picture. Overruled only when the rain in the
                # box moves and the picture under it holds no painted streaks that read (under a 2% step)
                pr = painted_streaks(pdir, [x0, y0, x1, y1])
                rain_mv = float(np.percentile(sd[inbox], 90))
                if pr is not None and pr < 0.02 and rain_mv >= 0.008:
                    sev, note = "overruled", (f"the rain in it moves (temporal std p90 {rain_mv:.4f}) and the still picture holds no "
                                              f"painted streaks that read (brightest {pr * 100:.1f}% step, under 2%)")
                elif pr is not None and pr >= 0.02:
                    sev, note = "high", (f"painted rain left in the picture (brightest streaks a {pr * 100:.1f}% step; derain more: hand.json "
                                         "\"derain\": {\"strength\": 1.5, \"passes\": 4, \"relaxed\": 0.25}, or clean it)")
                else:
                    sev, note = "high", f"the rain in it barely moves (temporal std p90 {rain_mv:.4f})"
                flagged.append({"where": it.get("what"), "box": b, "problem": note, "severity": sev, "source": "vision"})
                continue
            kinds = next((ks for words, ks in THING_KINDS if any(wd in what for wd in words)), ())
            m = None
            if kinds and ids is not None:
                m = np.isin(ids, [g["id"] for g in regs if g["kind"] in kinds]) & inbox
                if m.sum() < 16:
                    m = None
            # a pet breathes only where pet.png says it rises (its torso): the head, eyes and tail hold still on purpose
            # (user 2026-10-21), and measured over the whole pet they read as a frozen animal
            if m is not None and kinds == ("pet",) and (pdir / "pet.png").exists():
                rise = np.asarray(Image.open(pdir / "pet.png").convert("RGB").resize((w, h), Image.BILINEAR))[..., 0] > 76
                if (rise & m).sum() >= 16:
                    m = rise & m
            if m is None:
                m = thing_mask(first, [x0, y0, x1, y1])
            if m is None or m.sum() < 16:
                m = inbox
            mv = float(np.percentile(pm[m], 75))
            if mv >= 0.003:
                sev, note = "overruled", f"measured motion {mv:.4f} in it"
            else:
                note = f"still in the clip (persistent motion {mv:.4f} in it; rain or drips in front don't count)"
                if (x1 - x0) * (y1 - y0) >= 0.01:
                    sev = "high"       # measured still and big enough to notice: fails whatever the model's severity
        flagged.append({"where": it.get("what"), "box": b, "problem": note, "severity": sev, "source": "vision"})
    out = clip.with_name(clip.stem + "_static.json")
    out.write_text(json.dumps({"regions": rows, "flagged": flagged, "moving_well": res.get("moving_well", [])}, indent=1), encoding="utf-8")
    for r in rows:
        print(f"  {'ok ' if r['ok'] else 'LOW'} {r['region']:28s} {r['kind']:8s} {r['motion']:.4f} (min {r['min']})")
    for f in flagged:
        if f["source"] == "vision":
            print(f"  STILL ({f.get('severity')}): {f['where']} {f.get('box')}  [{f['problem']}]")
    print(f"static check: {sum(1 for f in flagged if f.get('severity') != 'overruled')} flagged -> {out} (~${usage['usd_est']:.3f})")
    return 2 if any(f.get("severity", "high") == "high" for f in flagged) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--crops", default="")
    ap.add_argument("--times", default="")
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--n", type=int, default=4, help="auto crops")
    ap.add_argument("--static", metavar="SCENE", help="flag things that should move but don't (scene's regions + vision check)")
    a = ap.parse_args()
    clip = pathlib.Path(a.clip)
    W, H, fps = probe(clip)
    fr = all_frames(clip, W, H).astype(np.float32) / 255
    lum = fr @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    sd = lum.std(0)
    dur = len(fr) / 10
    heat = np.clip(sd / max(float(np.percentile(sd, 99.7)), 1e-4), 0, 1) ** 0.6
    base = fr[0] * 0.45
    col = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1].astype(np.float32) / 255
    over = np.clip(base + col * heat[..., None] * 0.9, 0, 1)
    mot = clip.with_name(clip.stem + "_motion.png")
    Image.fromarray((over * 255).astype(np.uint8)).resize((1920, 1080), Image.LANCZOS).save(mot)
    if a.static:
        sys.exit(static_check(clip, a.static, sd, fr[0], mot, persistent_motion(lum)))
    crops = []
    if a.crops:
        crops = [tuple(map(float, c.split(","))) for c in a.crops.split(";") if c.strip()]
    else:
        hh, ww = heat.shape
        k = cv2.GaussianBlur(heat, (0, 0), 6)
        for _ in range(a.n):
            y, x = np.unravel_index(np.argmax(k), k.shape)
            if k[y, x] < 0.05:
                break
            cw, ch = 0.16, 0.2
            cx, cy = x / ww, y / hh
            c = (max(0, cx - cw / 2), max(0, cy - ch / 2), min(1, cx + cw / 2), min(1, cy + ch / 2))
            crops.append(c)
            k[max(0, int((cy - ch) * hh)):int((cy + ch) * hh), max(0, int((cx - cw) * ww)):int((cx + cw) * ww)] = 0
    times = [float(t) for t in a.times.split(",")] if a.times else [round(0.37 + (dur - 0.8) * i / 5, 2) for i in range(6)]
    full = frames_at(clip, times, W, H)
    rows = []
    for c in crops:
        x0, y0, x1, y1 = int(c[0] * W), int(c[1] * H), int(c[2] * W), int(c[3] * H)
        tiles = [Image.fromarray(f[y0:y1, x0:x1]) for f in full]
        th = 360
        tw = max(1, round(th * (x1 - x0) / max(1, y1 - y0)))
        row = Image.new("RGB", (tw * len(tiles), th + 22), (20, 20, 20))
        d = ImageDraw.Draw(row)
        for i, t in enumerate(tiles):
            row.paste(t.resize((tw, th), Image.LANCZOS), (i * tw, 22))
            d.text((i * tw + 4, 4), f"t={times[i]:.1f}s  crop {c[0]:.2f},{c[1]:.2f}-{c[2]:.2f},{c[3]:.2f}", fill=(220, 220, 220))
        rows.append(row)
    if rows:
        Wm = max(r.width for r in rows)
        sheet = Image.new("RGB", (Wm, sum(r.height for r in rows)), (10, 10, 10))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height
        strips = clip.with_name(clip.stem + "_strips.png")
        if sheet.width > 3000:
            sheet = sheet.resize((3000, round(sheet.height * 3000 / sheet.width)), Image.LANCZOS)
        sheet.save(strips)
        print(f"strips: {strips}")
    print(f"motion: {mot} (crops: {', '.join('%.2f,%.2f,%.2f,%.2f' % c for c in crops)})")
    if a.ask:
        from azure_ai import vision_json
        imgs = [mot] + ([clip.with_name(clip.stem + "_strips.png")] if rows else [])
        res, usage = vision_json(
            "These come from a short clip of a calm ambience video (one still image animated in code). Image 1: where pixels change over the "
            "clip (bright = more motion) over the first frame. Image 2: crops of the busiest areas at several times. Judge as a picky viewer: does "
            "any motion look broken, unnatural, too strong, too regular, flickering, in the wrong place, or missing where you'd expect it? "
            "Return JSON {\"ok\": true/false, \"issues\": [{\"where\": \"...\", \"problem\": \"...\", \"fix\": \"...\"}], \"good\": [\"...\"]}",
            images=imgs, purpose=f"review:{clip.stem}", effort="medium")
        print(json.dumps(res, indent=1))
        print(f"(~${usage['usd_est']:.3f})")


if __name__ == "__main__":
    main()
