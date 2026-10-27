"""Blinks for the channel's awake cast (Truman 2026-10-25: the characters may be awake doing something quiet, "with
breathing and blinks drawn in code"; nothing generated). Finds each character's dot eyes on the plate and paints the
closed-eye patches the blink layer (src/library/blink.js) fades in for a moment: the eye filled with the skin around
it and a thin lid line in the eye's own dark color, slightly curved like a sleepy closed eye.

  .venv\\Scripts\\python tools\\cast_eyes.py <scene> [--max-eyes 2]

Eyes: in each character (a pet region: its outline and its "still" boxes, where analyze_plate puts the head), the
small, round, dark dots that stand out from the fur or skin around them (a black top-hat on lightness), at most two
per character, a pair only when they sit side by side. Writes out/plates/<plate>/eyes_closed.png (RGBA at 4K: the
closed patches), eyes_id.png (R = (character index + 1) / 8 under each patch), eyes.json and eyes_preview.jpg (each
character's head at 1:1 with its eyes ringed, open beside closed): look at it before any render.
"""
import argparse
import json
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cozy.paths import ROOT


def regions(scene):
    out = []
    for p in (ROOT / "assets" / "keyart" / f"{scene}.masks.json", ROOT / "assets" / "keyart" / f"{scene}.hand.json"):
        if p.exists():
            out += [r for r in (json.loads(p.read_text(encoding="utf-8")).get("regions") or []) if r.get("kind") == "pet" and r.get("polys")]
    return out


def find_eyes(L, M, boxes, W, H, max_eyes=2):
    """Dark round dots inside the character: returns [(cx, cy, r, score)] in plate px."""
    area = np.zeros((H, W), bool)
    for x0, y0, x1, y1 in boxes or [[0, 0, 1, 1]]:
        area[int(y0 * H):int(np.ceil(y1 * H)), int(x0 * W):int(np.ceil(x1 * W))] = True
    inside = area & (cv2.dilate((M > 0.5).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)
    if not inside.any():
        return []
    ys, xs = np.nonzero(inside)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    Lc = L[y0:y1, x0:x1]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))
    bh = cv2.morphologyEx(Lc, cv2.MORPH_BLACKHAT, k)
    cand = (bh > 14) & (Lc < max(32.0, float(np.percentile(Lc[inside[y0:y1, x0:x1]], 10)))) & inside[y0:y1, x0:x1]
    cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(cand, 8)
    found = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        w, h = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if not 25 <= a <= 3000 or not 0.5 <= w / max(h, 1) <= 2.0:
            continue
        cnts, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        per = max(cv2.arcLength(cnts[0], True), 1.0)
        circ = 4 * np.pi * a / per ** 2
        if circ < 0.55:
            continue
        score = float(bh[lab == i].mean()) * np.sqrt(a) * circ
        found.append((float(cen[i][0] + x0), float(cen[i][1] + y0), float(np.sqrt(a / np.pi)), score))
    found.sort(key=lambda e: -e[3])
    if not found:
        return []
    best = [found[0]]
    for e in found[1:]:
        if len(best) >= max_eyes:
            break
        b = best[0]
        # a second eye: about the same size, beside the first (same height), not far away
        if abs(e[1] - b[1]) < 2.0 * b[2] and abs(e[0] - b[0]) < 9 * b[2] and 0.6 < e[2] / b[2] < 1.6 and e[3] > 0.45 * b[3]:
            best.append(e)
    return best


def refine(L, px, py, W, H, r0):
    """The darkest round dot near (px, py): the disk radius and center that make the dot darkest against its ring.
    The search stays close to the pointed spot (half a radius, at least 6 px): with a wide window it slid onto a dark
    edge nearby and left the real eye open (the salamander's, 2026-10-25)."""
    best = None
    win = int(max(24, 3 * r0))
    reach = max(6.0, 0.5 * r0)
    x0, y0, x1, y1 = max(0, int(px) - win), max(0, int(py) - win), min(W, int(px) + win + 1), min(H, int(py) + win + 1)
    sub = L[y0:y1, x0:x1]
    gy, gx = np.mgrid[y0:y1, x0:x1]
    near = np.hypot(gx - px, gy - py) <= reach
    for r in np.linspace(max(3.0, 0.7 * r0), max(5.0, 1.3 * r0), 7):
        k = int(np.ceil(2.0 * r)) + 1
        g = np.hypot(*np.mgrid[-k:k + 1, -k:k + 1]).astype(np.float32)
        disk = (g <= r).astype(np.float32)
        ring = ((g >= 1.3 * r) & (g <= 1.9 * r)).astype(np.float32)
        md = cv2.filter2D(sub, -1, disk / disk.sum(), borderType=cv2.BORDER_REPLICATE)
        mr = cv2.filter2D(sub, -1, ring / max(ring.sum(), 1), borderType=cv2.BORDER_REPLICATE)
        # contrast of the disk with its ring, barely weighted by size: a strong weight grew the salamander's eye into
        # the dark socket around it (r 21 for an 11 px eye, 2026-10-25)
        score = np.where(near, (mr - md) * r ** 0.15, -1e9)
        yy, xx = np.unravel_index(int(np.argmax(score)), score.shape)
        s = float(score[yy, xx])
        if best is None or s > best[3]:
            best = (float(xx + x0), float(yy + y0), float(r), s)
    return best


def ask_eyes(plate, M, name):
    """The vision model points at each visible eye on a crop of the character; returns [(x, y, r)] in plate px. The
    model's eye radius runs large (it took the salamander's dark socket for its 11 px eye), so it only bounds the
    search; the size comes from the measured disk."""
    from azure_ai import vision_json
    H, W = M.shape
    ys, xs = np.nonzero(M > 0.5)
    pad = 40
    x0, y0, x1, y1 = max(0, xs.min() - pad), max(0, ys.min() - pad), min(W, xs.max() + pad), min(H, ys.max() + pad)
    crop = Image.fromarray(plate[y0:y1, x0:x1])
    q = ("This is a crop of one storybook creature (" + name.replace("_", " ") + ") from an illustration. Point at the "
         "center of each of its eyes that is visible (one for a side view, two when it faces us), as fractions of this "
         "crop's width and height (0, 0 top left), and give each eye's radius as a fraction of the crop's width. Not the "
         "nostril, the mouth, a spot or a speckle. Answer as JSON: {\"eyes\": [{\"x\": 0.0, \"y\": 0.0, \"r\": 0.0}]}")
    res, _ = vision_json(q, images=[crop], purpose="cast_eyes", max_side=1400)
    out = []
    for e in res.get("eyes") or []:
        try:
            out.append((x0 + float(e["x"]) * crop.width, y0 + float(e["y"]) * crop.height, max(4.0, float(e.get("r") or 0.02) * crop.width)))
        except (TypeError, ValueError, KeyError):
            continue
    return out[:2]


def closed_patch(plate, L, cx, cy, r):
    """The eye filled with real skin from right beside it (the side whose texture is calmest and whose color is
    closest to the eye's own ring, its mean shifted to that ring) and a thin lid line in the eye's own dark color."""
    H, W = plate.shape[:2]
    R = int(np.ceil(3.2 * r)) + 4
    x0, y0, x1, y1 = max(0, int(cx) - R), max(0, int(cy) - R), min(W, int(cx) + R + 1), min(H, int(cy) + R + 1)
    crop = plate[y0:y1, x0:x1].astype(np.float32)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - cx, yy - cy)
    ring = (d > 1.4 * r) & (d < 2.2 * r)
    ring_col = np.median(crop[ring].reshape(-1, 3), axis=0) if ring.any() else crop.reshape(-1, 3).mean(0)
    dark = crop[d <= r * 0.8].reshape(-1, 3)
    col = np.median(dark, axis=0) if len(dark) else np.array([20, 18, 16])
    best = None
    s = 2.4 * r
    for dx, dy in ((0, -s), (-s, 0), (s, 0), (0, s), (-s * 0.7, -s * 0.7), (s * 0.7, -s * 0.7)):
        sx, sy = cx + dx, cy + dy
        if not (r + 2 <= sx < W - r - 2 and r + 2 <= sy < H - r - 2):
            continue
        src = plate[np.clip((yy + dy).round().astype(int), 0, H - 1), np.clip((xx + dx).round().astype(int), 0, W - 1)].astype(np.float32)
        Ls = L[np.clip((yy + dy).round().astype(int), 0, H - 1), np.clip((xx + dx).round().astype(int), 0, W - 1)]
        disk = d <= r + 1.5
        cost = float(np.abs(src[disk].mean(0) - ring_col).sum()) + 3.0 * float(Ls[disk].std()) + 40.0 * float((Ls[disk] < 18).mean())
        if best is None or cost < best[0]:
            best = (cost, src)
    fill = best[1] - best[1][d <= r + 1.5].mean(0) + ring_col if best else np.broadcast_to(ring_col, crop.shape).copy()
    # the color comes from the skin right around the eye, gradient and all (inpainted), the texture from the cloned
    # skin: one mean color left a tinted disk where the salamander's eye sits between its red stripe and gray side
    hole = (d <= 1.15 * r + 4).astype(np.uint8)
    low = cv2.inpaint(np.clip(crop, 0, 255).astype(np.uint8), hole, max(3, int(r)), cv2.INPAINT_TELEA).astype(np.float32)
    sig = max(1.5, 0.45 * r)
    fill = cv2.GaussianBlur(low, (0, 0), sig) + (fill - cv2.GaussianBlur(fill, (0, 0), sig))
    big = 4
    im = Image.fromarray(np.clip(cv2.resize(fill, None, fx=big, fy=big, interpolation=cv2.INTER_CUBIC), 0, 255).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    lx, ly = (cx - x0) * big, (cy - y0) * big
    wline = max(2 * big, int(0.32 * r * big))
    dr.arc([lx - 1.0 * r * big, ly - 0.55 * r * big, lx + 1.0 * r * big, ly + 0.45 * r * big], start=20, end=160,
           fill=tuple(int(v) for v in col), width=wline)
    patch = np.asarray(im.resize((x1 - x0, y1 - y0), Image.LANCZOS))
    alpha = np.clip((1.15 * r + 3.0 - d) / 1.5, 0, 1)
    return (x0, y0, x1, y1), patch, alpha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--max-eyes", type=int, default=2)
    ap.add_argument("--no-ask", action="store_true", help="the shape search only (free, but it can take a nostril for an eye)")
    a = ap.parse_args()
    from cozy.masks import region_raster
    spec = json.loads((ROOT / "scenes" / a.scene / "scene.json").read_text(encoding="utf-8")) if (ROOT / "scenes" / a.scene / "scene.json").exists() else {}
    plate_name = spec.get("plate", a.scene)
    pd = ROOT / "out" / "plates" / plate_name
    plate = np.asarray(Image.open(pd / "plate.png").convert("RGB"))
    H, W = plate.shape[:2]
    L = cv2.cvtColor(plate.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)[..., 0]
    pets = regions(a.scene)
    rgba = np.zeros((H, W, 4), np.float32)
    ids = np.zeros((H, W), np.float32)
    meta, shots = [], []
    for i, rg in enumerate(pets[:7]):
        M = region_raster(rg, W, H)
        # the vision model points (a black eye on dark skin next to the head's outline fooled the shape search: it
        # took a nostril and a speck, 2026-10-25), the code finds the exact dark disk there
        eyes = [refine(L, x, y, W, H, r) for x, y, r in ask_eyes(plate, M, rg["name"])] if not a.no_ask else []
        if len(eyes) == 2:
            # a pair has one size: the smaller measurement takes the larger's (the mothling's far eye measured half
            # its near one and stayed half open, 2026-10-25)
            r = max(e[2] for e in eyes)
            eyes = [(e[0], e[1], r, e[3]) for e in eyes]
        if not eyes:
            eyes = find_eyes(L, M, rg.get("still"), W, H, a.max_eyes) or find_eyes(L, M, None, W, H, a.max_eyes)
        meta.append({"index": i, "region": rg["name"], "eyes": [[round(e[0], 1), round(e[1], 1), round(e[2], 2)] for e in eyes]})
        for cx, cy, r, _ in eyes:
            (x0, y0, x1, y1), patch, alpha = closed_patch(plate, L, cx, cy, r)
            sl = (slice(y0, y1), slice(x0, x1))
            keep = alpha > rgba[sl][..., 3]
            rgba[sl][keep, :3] = patch[keep]
            rgba[sl][..., 3] = np.maximum(rgba[sl][..., 3], alpha)
            ids[sl] = np.where(alpha > 0, (i + 1) / 8, ids[sl])
        if eyes:
            xs = [e[0] for e in eyes]
            ys = [e[1] for e in eyes]
            R = int(max(60, 8 * max(e[2] for e in eyes)))
            box = (int(max(0, min(xs) - R)), int(max(0, min(ys) - R)), int(min(W, max(xs) + R)), int(min(H, max(ys) + R)))
            shots.append((rg["name"], box, eyes))
        print(f"  {rg['name']}: {len(eyes)} eye(s) " + ", ".join(f"({e[0]:.0f}, {e[1]:.0f}) r {e[2]:.1f}" for e in eyes))
    Image.fromarray(np.dstack([np.clip(rgba[..., :3], 0, 255), rgba[..., 3:] * 255]).round().astype(np.uint8), "RGBA").save(pd / "eyes_closed.png")
    Image.fromarray((ids * 255).round().astype(np.uint8), "L").convert("RGB").save(pd / "eyes_id.png")
    (pd / "eyes.json").write_text(json.dumps({"pets": meta}, indent=1), encoding="utf-8")
    # preview: each head at 1:1, open (eyes ringed) beside closed
    closed = plate.astype(np.float32) * (1 - rgba[..., 3:]) + rgba[..., :3] * rgba[..., 3:]
    tiles = []
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 18)
    for name, (x0, y0, x1, y1), eyes in shots:
        o = Image.fromarray(plate[y0:y1, x0:x1].copy())
        dr = ImageDraw.Draw(o)
        for cx, cy, r, _ in eyes:
            dr.ellipse([cx - x0 - r - 4, cy - y0 - r - 4, cx - x0 + r + 4, cy - y0 + r + 4], outline=(0, 255, 255), width=2)
        c = Image.fromarray(closed[y0:y1, x0:x1].clip(0, 255).astype(np.uint8))
        t = Image.new("RGB", (o.width * 2 + 6, o.height + 26), (18, 18, 18))
        t.paste(o, (0, 26)); t.paste(c, (o.width + 6, 26))
        ImageDraw.Draw(t).text((4, 2), f"{name}: open, closed", font=font, fill=(235, 235, 235))
        tiles.append(t)
    if tiles:
        Wt = max(t.width for t in tiles)
        S = Image.new("RGB", (Wt, sum(t.height + 6 for t in tiles)), (18, 18, 18))
        y = 0
        for t in tiles:
            S.paste(t, (0, y))
            y += t.height + 6
        S.save(pd / "eyes_preview.jpg", quality=92)
    print(f"cast_eyes: {sum(len(m['eyes']) for m in meta)} eyes on {len(meta)} characters -> {pd / 'eyes.json'}, eyes_preview.jpg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
