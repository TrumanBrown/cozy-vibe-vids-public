"""Art changes Truman asks for on a key art that is already in use (a prettier sky, more kinds of crops): masked image
edits of the cleaned key art (assets/keyart/<scene>/clean.png). Only the masked pixels change, and unlike
tools/plate_clean.py there is no color fit, because the point is a new look there (user 2026-10-21 on the pixel
greenhouse: a prettier sky, less bland, and more variety in what is planted). Each edit is logged in clean.json (kind
"art": prompt, mask, usage, date),
which the asset ledger row of clean.png points to; then the plate is rebuilt with plate_prep --keep-depth (the
room's shape is unchanged, so the masks built on the depth stay put).

  .venv\\Scripts\\python tools\\art_edit.py <scene> --name sky --sky --prompt "..."
  .venv\\Scripts\\python tools\\art_edit.py <scene> --name crops --green "x,y,x,y,..." [--green ...] [--poly "..."] --prompt "..."
      [--dry]          the mask and its preview only (free)
      [--no-rebuild]   skip plate_prep

Masks (their union, at the key art's size; polygon points are fractions of the image, x,y pairs):
  --sky       the open sky in the view: outdoors (the plate's lights.png G), lighter than the land below it and
              joined to the top of the view, so hills, trees and buildings stay
  --green P   inside polygon P, the foliage only (green and yellow-green pixels, grown --grow px, 2 by default): plants
              change, the posts, stakes, boards, soil and a tray's dividers around them stay
  --poly P    the whole polygon
  --sam "x,y;x,y"  one SAM 2 mask per point (local GPU): each plant or object under a point, repainted inside its own
              outline (grown --grow px); the way to give a bed's plants variety without a seam through the leaves behind
Writes out/plates/<scene>/art_edit/<name>_mask.png, <name>_before.png, <name>_after.png and <name>_preview.jpg.
The prompt should say what stays (the style, the pixel size, the light) and forbid animals, people and text: the
critic fails painted animals (the code animates its own).
"""
import argparse
import base64
import datetime
import io
import json
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT, PY


def poly(s, W, H):
    v = [float(x) for x in s.replace(";", ",").split(",") if x.strip()]
    pts = [(v[i] * W, v[i + 1] * H) for i in range(0, len(v) - 1, 2)]
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return np.asarray(m) > 127


def sky_mask(img, plate_dir, cell=None):
    """The open sky in the view and the land's top above a smooth horizon line, so the far hills' soft tops are
    repainted with the new sky behind them (cut at a brightness threshold, the greenhouse's hills came back torn,
    with floating specks, 2026-10-21). The horizon is the first wide land in each column (darker than the view's top
    rows by 6 L, at least ~40 px wide) smoothed over 41 columns, plus two cells; a windpump's tower or a lone tree
    does not hold it up (that left strips of the old sky by the greenhouse's tower). Thin dark things above it (a
    tower, blades, a pole, tree tops: 4 L darker than the sky's edge and not part of the wide land) stay as they are.
    Returns (mask, info) with what spin_fix needs."""
    W, H = img.size
    G = np.asarray(Image.open(plate_dir / "lights.png").convert("RGB").resize((W, H), Image.BILINEAR))[..., 1] > 127
    if not G.any():
        return np.zeros((H, W), bool), None
    cell = cell or max(3, W // 450)
    L = cv2.cvtColor(np.asarray(img, np.float32) / 255, cv2.COLOR_RGB2LAB)[..., 0]
    ys = np.nonzero(G.any(1))[0]
    top, bot = int(ys.min()), int(ys.max())
    band = G.copy()
    band[top + max(4, (bot - top) // 10):] = False
    thr = (float(np.median(L[band])) if band.any() else 50.0) - 6
    low = (G & (L < thr)).astype(np.uint8)
    land = cv2.morphologyEx(cv2.morphologyEx(low, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8)), cv2.MORPH_OPEN,
                            np.ones((1, max(9, int(0.016 * W))), np.uint8)) > 0
    first = np.where(land.any(0), land.argmax(0), H).astype(np.float32)
    horizon = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(first, 20, mode="edge"), 41), axis=1)
    struct = G & (L < thr - 4) & ~cv2.dilate(land.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    struct = cv2.morphologyEx(struct.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    sky = G & ~struct & (np.arange(H)[:, None] < (horizon + 2 * cell)[None, :])
    n, lab_, st, _ = cv2.connectedComponentsWithStats(sky.astype(np.uint8), 8)
    small = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] < 40]
    if small:
        sky &= ~np.isin(lab_, small)
    return sky, {"L": L, "G": G, "horizon": horizon, "struct": struct, "cell": cell}


def spin_fix(before, new, spin, info):
    """A turning wheel in the repainted sky (the greenhouse's windpump, 2026-10-21): its blades and the tower under
    them come back from the original, the sky across the wheel's columns is filled row by row between the new sky on
    either side (an edit repaints what it sees next to a hole, and painted ghost blades and strips of the old sky
    there), and the sky between the blades is one flat color, since a turning patch of cloud texture would show."""
    L, G, horizon, struct, cell = info["L"], info["G"], info["horizon"], info["struct"].copy(), info["cell"]
    H, W = L.shape
    L2 = cv2.cvtColor(new.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)[..., 0]
    t, _ = cv2.threshold(np.clip(L[spin] * 2.55, 0, 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    blades = spin & (L < t / 2.55)
    out = new.copy()
    n, lab, st, _ = cv2.connectedComponentsWithStats(spin.astype(np.uint8), 8)
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        c0, c1 = max(1, int(x - 2 * cell)), min(W - 2, int(x + w + 2 * cell))
        r0, r1 = max(0, int(y - cell)), int(horizon[c0:c1 + 1].max())
        # the tower: the thin structure joined to the blades, above the horizon in the wheel's columns
        sb = np.zeros((H, W), bool)
        sb[r0:r1, c0:c1 + 1] = struct[r0:r1, c0:c1 + 1]
        for c in range(c0, c1 + 1):
            sb[int(horizon[c]):, c] = False
        k, lb, _s, _ = cv2.connectedComponentsWithStats((sb | (blades & (lab == i))).astype(np.uint8), 8)
        main = lb[blades & (lab == i)]
        tower = sb & np.isin(lb, np.unique(main[main > 0]))

        def edge(r, c, step):
            for j in range(12):
                cc = min(W - 1, max(0, c + step * j))
                if L2[r, cc] >= 45 and not struct[r, cc] and not spin[r, cc]:
                    return new[r, cc].astype(np.float32)
            return new[r, c].astype(np.float32)
        for r in range(r0, min(r1, H)):
            a, b = edge(r, c0 - 1, -1), edge(r, c1 + 1, 1)
            f = (np.arange(c0, c1 + 1) - c0) / max(1, c1 - c0)
            row = np.round(a[None] * (1 - f[:, None]) + b[None] * f[:, None]).astype(np.uint8)
            sel = (r < horizon[c0:c1 + 1]) & G[r, c0:c1 + 1] & ~tower[r, c0:c1 + 1]
            out[r, c0:c1 + 1][sel] = row[sel]
        disc = lab == i
        ring = (cv2.dilate(disc.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0) & ~spin & G
        out[disc & ~blades] = np.median(out[ring], axis=0).astype(np.uint8)
        out[tower] = before[tower]
    out[blades] = before[blades]
    return out


def spinning(scene, W, H):
    """Regions the code turns in place (kind wheel): an edit must leave them out, or the new texture between the
    blades turns with them."""
    from cozy.masks import region_raster
    ov = {}
    for p in (ROOT / "assets" / "keyart" / f"{scene}.masks.json", ROOT / "assets" / "keyart" / f"{scene}.hand.json"):
        if p.exists():
            for k, v in json.loads(p.read_text(encoding="utf-8")).items():
                ov[k] = ov[k] + v if isinstance(v, list) and isinstance(ov.get(k), list) else v
    m = np.zeros((H, W), bool)
    for rg in ov.get("regions") or []:
        if rg.get("kind") == "wheel" and rg.get("polys"):
            m |= region_raster(rg, W, H) > 0.5
    return m


def sam_mask(img, points, grow=2, max_frac=0.012):
    """One SAM 2 mask per point (x, y fractions): the plant or object under it, so each can be repainted inside its
    own outline (a bed's heads of lettuce one by one; a polygon across a bed cut the leaves behind it with a straight
    seam). Of SAM's three candidates the best scored one under max_frac of the image is kept."""
    from cozy.segment import Segmenter
    W, H = img.size
    seg = Segmenter()
    m = np.zeros((H, W), bool)
    for (x, y), cands in zip(points, seg.point_candidates(img, [(x * W, y * H) for x, y in points])):
        ok = [(mk, s) for mk, s in cands if 0 < mk.sum() < max_frac * W * H]
        if ok:
            m |= max(ok, key=lambda c: c[1])[0]
    k = 2 * max(1, grow) + 1
    return cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0


def green_mask(img, inside, grow=2):
    """The foliage inside a polygon (green and yellow-green pixels), grown by `grow` px so new plants can take a
    slightly different shape; the soil, boards, posts and dividers around them stay."""
    hsv = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(np.int32) * 2, hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
    leaf = (h >= 45) & (h <= 165) & (s > 0.18) & (v > 0.1)
    leaf = cv2.morphologyEx(leaf.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    k = 2 * max(1, grow) + 1
    leaf = cv2.dilate(leaf, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    return leaf & inside


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--name", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--sky", action="store_true")
    ap.add_argument("--green", action="append", default=[])
    ap.add_argument("--grow", type=int, default=2, help="px the --green foliage is grown by (at the key art's size)")
    ap.add_argument("--sam", action="append", default=[], help="x,y;x,y;... (fractions): one SAM mask per point, grown by --grow")
    ap.add_argument("--poly", action="append", default=[])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args()
    kd = ROOT / "assets" / "keyart" / a.scene
    cp = kd / "clean.png"
    img = Image.open(cp).convert("RGB")
    W, H = img.size
    sc = json.loads((ROOT / "scenes" / a.scene / "scene.json").read_text(encoding="utf-8"))
    plate_dir = ROOT / "out" / "plates" / sc.get("plate", a.scene)
    m = np.zeros((H, W), bool)
    pj = plate_dir / "plate.json"
    px = (json.loads(pj.read_text(encoding="utf-8")).get("pixel") or {}) if pj.exists() else {}
    cell = float(px["cell"]) * W / 3840 if px.get("cell") else None   # the pixel-art grid at the key art's size
    info = None
    if a.sky:
        s, info = sky_mask(img, plate_dir, cell)
        m |= s
    for p in a.green:
        m |= green_mask(img, poly(p, W, H), a.grow)
    for p in a.sam:
        pts = [tuple(float(v) for v in q.split(",")) for q in p.split(";") if q.strip()]
        m |= sam_mask(img, pts, a.grow)
    for p in a.poly:
        m |= poly(p, W, H)
    spin = spinning(a.scene, W, H)
    m &= ~spin
    od = plate_dir / "art_edit"
    od.mkdir(parents=True, exist_ok=True)
    Image.fromarray((m * 255).astype(np.uint8)).save(od / f"{a.name}_mask.png")
    vis = np.asarray(img).copy()
    vis[m] = (vis[m] * 0.4 + np.array([255, 120, 0]) * 0.6).astype(np.uint8)
    vis[spin] = [255, 0, 255]
    Image.fromarray(vis).save(od / f"{a.name}_maskview.jpg", quality=88)
    print(f"{a.name}: mask {int(m.sum())} px ({m.mean() * 100:.1f}% of the key art) -> {od / (a.name + '_maskview.jpg')}")
    if a.dry or not m.any():
        return 0
    from azure_ai import edit_image
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = np.where(cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0, 0, 255)   # transparent = repaint
    res = edit_image(img, a.prompt, mask=Image.fromarray(rgba, "RGBA"), size=f"{W}x{H}", quality="high", purpose=f"art_edit:{a.scene}:{a.name}")
    out = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGB")
    if out.size != (W, H):
        out = out.resize((W, H), Image.LANCZOS)
    out.save(od / f"{a.name}_raw.png")
    new = np.asarray(img).copy()
    new[m] = np.asarray(out)[m]
    if info is not None and (spin & cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)).any():
        new = spin_fix(np.asarray(img), new, spin, info)
    img.save(od / f"{a.name}_before.png")
    Image.fromarray(new).save(od / f"{a.name}_after.png")
    Image.fromarray(new).save(cp)
    pv = np.concatenate([np.asarray(img), new], 1)
    Image.fromarray(pv).resize((pv.shape[1] // 2, pv.shape[0] // 2), Image.LANCZOS).save(od / f"{a.name}_preview.jpg", quality=88)
    cj = kd / "clean.json"
    log = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {"items": []}
    log.setdefault("items", []).append({
        "name": a.name, "kind": "art", "prompt": a.prompt,
        "mask": {"sky": a.sky, "green": a.green, "sam": a.sam, "grow": a.grow, "poly": a.poly, "px": int(m.sum())},
        "size": f"{W}x{H}", "usage": [res.get("usage") or {}], "date": datetime.date.today().isoformat()})
    cj.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"  edited -> {cp} (logged in {cj.name}); preview {od / (a.name + '_preview.jpg')}")
    if not a.no_rebuild:
        r = subprocess.run([PY, str(ROOT / "tools" / "plate_prep.py"), str(cp), "--name", sc.get("plate", a.scene), "--keep-depth"])
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
