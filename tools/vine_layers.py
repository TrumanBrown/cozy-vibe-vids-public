"""Lift hanging strands off the plate so they can swing freely (src/library/vines.js).

Truman asked for the jungle temple's vines, especially those hanging off the front, to move more (2026-10-27, L167). A
strand that hangs free in front of the view can only sway a few px as a warp of the plate (plate.js regions): the warp
slides its leaves inside an outline that stays where it is, and a bigger warp drags the jungle behind it along. Lifted,
it is its own sprite (cut from the plate before anything is repainted) drawn over a background with the strand painted
away (tools/plate_clean.py, the image model), and vines.js bends it from where it hangs.

  .venv/Scripts/python tools/vine_layers.py <scene>            sprites, lift.json, the clean.json items, the sky behind
  .venv/Scripts/python tools/vine_layers.py <scene> --preview  ... and out/plates/<plate>/lift_preview.jpg

Reads assets/keyart/<scene>.hand.json:
  "lift": [{"name": <an analysis region>, or a new name with "box": [x0, y0, x1, y1] (a strand the analysis missed:
           SAM traces it), "matte": "leaves" (a curtain with more than sky in its gaps: the leaves by their color) or
           "bright" (a bright thing on a dark ground, a clock's pendulum in its case: by its brightness)}, ...]
  "lift_clean": [{"name": "lift_upper", "y": [y0, y1], "what": "...", "behind": "...", "strands": [names] (optional: only
           these strands; default every strand in the rows)}, ...]: the repaint, in bands no taller than one edit window
           (1024 px of a 1440 px key art). A strand lifted later gets bands of its own, so the earlier items stay as
           they were and plate_clean.py --only repaints just the new ones.
A strand cut off by the frame's side gets its leaves continued past the edge (mirrored, "edge_pad" px, 72).
Writes out/plates/<plate>/lift/src.png (the 4K plate with the strands, the sprites' source: made once, from plate_raw.png
while the plate is still built from the hero, else by upscaling the hero again), lift/<name>.png (RGBA) and lift.json,
the clean.json items (kind "other", "polys"), and hand.json "lift_sky": the sky behind the strands (plate_prep adds it to
the sky, so the moon and the birds show there once a strand swings away). Then run tools/plate_clean.py <scene> and
tools/new_video.py prep <scene>, and give the scene a vines layer (and its regions null: the plate no longer sways them).
"""
import argparse
import json
import shutil
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT, load_json, load_scene
from cozy.masks import poly_mask
from cozy.plate.primitives import guided_filter
from cozy.segment import contours

PAD = 6          # px at 4K: the sprite's alpha reaches this far past the traced outline (soft edges)
EDGE_PAD = 72    # px of leaves continued past the frame's side (more than the widest swing)


def source(scene, plate, pd):
    sp = pd / "lift" / "src.png"
    sp.parent.mkdir(parents=True, exist_ok=True)
    if not sp.exists():
        meta = load_json(pd / "plate.json", {})
        if "clean.png" not in str(meta.get("source", "")).replace("\\", "/"):
            shutil.copyfile(pd / "plate_raw.png", sp)
        else:
            # the plate is built from the repainted key art by now: upscale the original as plate_prep did
            from cozy.plate.image import crop_16x9, upscale
            hero = ROOT / load_json(ROOT / "scenes" / scene / "brief.json")["hero"]
            upscale(crop_16x9(Image.open(hero).convert("RGB"), 0.5), 3840).save(sp)
        print(f"  sprite source: {sp.relative_to(ROOT)}")
    return Image.open(sp).convert("RGB")


def leaf_cut(img, hard):
    """The leaves of a curtain with the view showing through its gaps (the jungle temple's right edge: ruins, a cliff,
    lit windows, sky): GrabCut on the traced area, seeded by how leaf-colored each pixel is (olive to yellow-green: red
    and green about equal and both well over blue; the view behind is teal, blue, grey stone or orange lamplight), so
    the background between the leaves is left out instead of swinging with them. Small specks go; leaf clusters the
    gaps cut off stay (they would be left painted on the plate)."""
    H, W = hard.shape
    ys, xs = np.nonzero(hard)
    m = 40
    y0, y1, x0, x1 = max(ys.min() - m, 0), min(ys.max() + m + 1, H), max(xs.min() - m, 0), min(xs.max() + m + 1, W)
    crop = np.asarray(img)[y0:y1, x0:x1]
    hm = hard[y0:y1, x0:x1].astype(np.uint8)
    rgb = crop.astype(np.float32) / 255
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    yel = np.clip((np.minimum(R, G) - B) / (np.maximum(np.maximum(R, G), B) + 0.02), 0, 1)
    yel *= np.clip((G / (R + 1e-3) - 0.62) / 0.2, 0, 1)
    near = cv2.dilate(hm, np.ones((25, 25), np.uint8)) > 0
    gc = np.full(hm.shape, cv2.GC_BGD, np.uint8)
    gc[near] = cv2.GC_PR_BGD
    gc[(hm > 0) & (yel > 0.25)] = cv2.GC_PR_FGD
    # leaves in deep shade are near black and grey, no color to go by; in front of the sky nothing else is that dark
    blue = B - np.maximum(R, G)
    skyfrac = cv2.blur((blue > 0.05).astype(np.float32), (41, 41))
    dark = (0.2126 * R + 0.7152 * G + 0.0722 * B < 0.15) & (blue < 0.02)
    gc[(hm > 0) & dark & (skyfrac > 0.25)] = cv2.GC_PR_FGD
    gc[(cv2.erode(hm, np.ones((5, 5), np.uint8)) > 0) & (yel > 0.5)] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(np.ascontiguousarray(crop[..., ::-1]), gc, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    fg = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)) & near
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8))
    fg = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 150])
    out = np.zeros_like(hard)
    out[y0:y1, x0:x1] = fg
    return out


def bright_cut(img, hard):
    """A bright thing on a dark ground, cut by its brightness (a clock's gold pendulum on its case's dark back panel,
    the spruce cabin, 2026-11-06: SAM traced the whole glass door): what is clearly brighter than the traced area's
    dark part (Otsu on luminance, a little lower so its shaded edges stay), holes filled, and only the largest piece
    (the hinges and a small block below it are pieces of their own)."""
    g = np.asarray(img.convert("L"))
    ys, xs = np.nonzero(hard)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    crop, hm = g[y0:y1, x0:x1], hard[y0:y1, x0:x1]
    thr, _ = cv2.threshold(crop[hm].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = ((crop > 0.8 * thr) & hm).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg)
    if n < 2:
        return hard
    keep = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    # holes: whatever the background flood fill from the crop's border can't reach
    flood = keep.copy()
    pad = np.zeros((flood.shape[0] + 2, flood.shape[1] + 2), np.uint8)
    cv2.floodFill(flood, pad, (0, 0), 2)
    keep = (flood != 2).astype(bool)
    out = np.zeros_like(hard)
    out[y0:y1, x0:x1] = keep
    return out


def alpha_of(img, hard, matte="sky"):
    """A soft alpha that follows the leaves' own edges: the traced mask without what is sky- or cloud-colored (leaves
    are green to yellow, the night sky and the clouds blue: SAM's strands held patches of sky between their leaves and
    a scrap of cloud) and without small detached pieces, snapped to the image (guided filter) and kept within a few px.
    matte "leaves": the leaves alone by their color (leaf_cut), for a curtain with more than sky behind its gaps.
    matte "bright": a bright thing on a dark ground by its brightness (bright_cut), a pendulum in its case."""
    rgb = np.asarray(img, np.float32) / 255
    blue = rgb[..., 2] - np.maximum(rgb[..., 0], rgb[..., 1])
    leafy = 1 - np.clip((blue - 0.05) / 0.05, 0, 1)
    if matte == "leaves":
        hard = leaf_cut(img, hard)
    elif matte == "bright":
        hard = bright_cut(img, hard)
    else:
        hard = hard & (leafy > 0.5)
        n, lab, st, _ = cv2.connectedComponentsWithStats(hard.astype(np.uint8))
        if n > 2:
            big = st[1:, cv2.CC_STAT_AREA].max()
            hard = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.15 * big])
    g = np.asarray(img.convert("L"), np.float32) / 255
    gf = guided_filter(g, hard.astype(np.float32), 4, 2e-3)
    a = np.clip((gf - 0.25) / 0.5, 0, 1) * leafy
    near = cv2.dilate(hard.astype(np.uint8), np.ones((2 * PAD + 1, 2 * PAD + 1), np.uint8)) > 0
    return (a * near).astype(np.float32), hard


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    spec = load_scene(a.scene)
    plate = spec.get("plate", a.scene)
    pd = ROOT / "out" / "plates" / plate
    hp = ROOT / "assets" / "keyart" / f"{a.scene}.hand.json"
    hand = load_json(hp, {})
    lift = hand.get("lift") or []
    if not lift:
        sys.exit(f"no \"lift\" list in {hp.relative_to(ROOT)}")
    masks = load_json(ROOT / "assets" / "keyart" / f"{a.scene}.masks.json", {})
    img = source(a.scene, plate, pd)
    W, H = img.size
    arr = np.asarray(img)
    seg = None
    out, union, own = [], np.zeros((H, W), bool), {}
    for e in lift:
        name = e["name"]
        if e.get("box"):
            if seg is None:
                from cozy.segment import Segmenter, box_px
                seg = Segmenter()
            hard = seg.masks(img, [box_px(e["box"], W, H, grow=0.02)])[0]
        else:
            # a hand region replaces the analysis's of the same name (plate_prep), so it is looked up first
            reg = next((g for g in (hand.get("regions") or []) + (masks.get("regions") or []) if g.get("name") == e.get("region", name)), None)
            if not reg or not reg.get("polys"):
                sys.exit(f"{name}: no region of that name in the analysis (give a box)")
            hard = poly_mask((W, H), reg["polys"]) > 0.5
        if hard is None or not hard.any():
            sys.exit(f"{name}: nothing traced")
        al, hard = alpha_of(img, hard, e.get("matte", "sky"))
        ys, xs = np.nonzero(al > 0.02)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        rgba = np.dstack([arr[y0:y1, x0:x1], (al[y0:y1, x0:x1] * 255).round().astype(np.uint8)])
        # a curtain cut off by the frame's side: its leaves go on past the edge (mirrored), so a swing never brings a
        # straight cut line into view
        pad = int(e.get("edge_pad", EDGE_PAD))
        if x1 >= W - 1:
            rgba = np.concatenate([rgba, rgba[:, -pad:][:, ::-1]], 1)
            x1 += pad
        if x0 <= 0:
            rgba = np.concatenate([rgba[:, :pad][:, ::-1], rgba], 1)
            x0 -= pad
        f = pd / "lift" / f"{name}.png"
        Image.fromarray(rgba, "RGBA").save(f)
        hs = np.nonzero(hard.any(1))[0]
        # where it hangs: the middle of its top rows (a rigid strand, a pendulum, turns about it)
        top_cols = np.nonzero(hard[int(hs.min()):int(hs.min()) + 8].any(0))[0]
        pivot = [round(float(top_cols.mean()), 1), int(hs.min())]
        out.append({"name": name, "file": f"lift/{name}.png", "box": [x0, y0, x1, y1], "top": int(hs.min()), "bottom": int(hs.max()) + 1,
                    "pivot": pivot})
        own[name] = al > 0.1
        union |= own[name]
        print(f"  {name}: {x1 - x0}x{y1 - y0} px at ({x0}, {y0}), hangs from row {int(hs.min())} to {int(hs.max()) + 1}")
    (pd / "lift.json").write_text(json.dumps({"_note": "written by tools/vine_layers.py; the sprites are cut from lift/src.png",
                                              "strands": out}, indent=1), encoding="utf-8", newline="\n")
    # the repaint: the strands grown a little (their soft edges and halos go too), in bands, at the key art's size
    cp = ROOT / "assets" / "keyart" / f"{a.scene}.clean.json"
    clean = load_json(cp, None) or {"_note": "Painted things to remove from the key art (tools/plate_clean.py).",
                                     "source": load_json(ROOT / "scenes" / a.scene / "brief.json")["hero"], "items": []}
    names = set()
    for b in hand.get("lift_clean") or []:
        # a band repaints the strands it names (a strand lifted later gets bands of its own: the earlier repaint's
        # items stay as they were), else every strand in its rows
        sel = union if not b.get("strands") else np.any([own[n] for n in b["strands"]], 0)
        grown = cv2.dilate(sel.astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
        band = np.zeros_like(grown)
        band[int(b["y"][0] * H):int(b["y"][1] * H)] = True
        polys = contours(grown & band, W, H, eps=1.0, min_area=20)
        if not polys:
            continue
        item = {"name": b["name"], "kind": "other", "polys": polys, "what": b.get("what", "hanging vine strands"),
                "behind": b.get("behind", "the scene behind them as it continues"), "_auto": "tools/vine_layers.py"}
        clean["items"] = [it for it in clean["items"] if it.get("name") != b["name"]] + [item]
        names.add(b["name"])
        print(f"  clean item {b['name']}: {len(polys)} polygon(s) in rows {b['y']}")
    cp.write_text(json.dumps(clean, indent=1), encoding="utf-8", newline="\n")
    # the sky behind the strands: where the sky around them closes over them. Only the sky outside the strands counts
    # (masks.png already holds the lift_sky of an earlier run), so a re-run finds the same.
    sky = np.asarray(Image.open(pd / "masks.png").convert("RGB"))[..., 0] > 127
    fill = cv2.dilate(union.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (91, 91))
    closed = cv2.morphologyEx((sky & ~fill).astype(np.uint8), cv2.MORPH_CLOSE, k) > 0
    hand["lift_sky"] = contours(fill & closed, W, H, eps=1.0, min_area=10)
    hp.write_text(json.dumps(hand, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"  sky behind the strands: {len(hand['lift_sky'])} polygon(s) -> hand.json lift_sky")
    if a.preview:
        vis = img.copy().convert("RGB")
        d = ImageDraw.Draw(vis, "RGBA")
        for s in out:
            d.rectangle(s["box"], outline=(0, 255, 255, 255), width=4)
        for p in hand["lift_sky"]:
            d.polygon([(x * W, y * H) for x, y in p], fill=(255, 0, 255, 120))
        vis.resize((1920, 1080), Image.LANCZOS).save(pd / "lift_preview.jpg", quality=88)
        print(f"  preview: {(pd / 'lift_preview.jpg').relative_to(ROOT)}")
    print(f"lift: {len(out)} strand(s); next: tools/plate_clean.py {a.scene} --only " + " --only ".join(sorted(names)))


if __name__ == "__main__":
    main()
