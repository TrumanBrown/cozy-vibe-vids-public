"""Plate mask helpers several tools share (TASKS.md T12), moved verbatim from plate_prep.py. No model and no torch.

  poly_mask, region_raster     polygons or a masks-json region as a float mask at W x H
  render_occluders             occ.png (and occ_<track>.png): what a crawling critter passes behind
  pane_structure               the thin structure in a window that must stay dry (frame_tophat, view_color_share)
  flat_surface                 where depth says a wet surface is level, not upright
  pixelize                     a pixel-art plate rebuilt on an exact grid
  DRY_KINDS                    region kinds never rained or dripped on
"""
import json

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT

DRY_KINDS = {"pet", "steam", "candle", "bob", "fire", "screen"}


def poly_mask(size, polys):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for p in polys:
        d.polygon([(x * size[0], y * size[1]) for x, y in p], fill=255)
    return np.asarray(m, np.float32) / 255


def region_raster(rg, W, H):
    if rg.get("polys"):
        return poly_mask((W, H), rg["polys"])
    if rg.get("box"):
        x0, y0, x1, y1 = rg["box"]
        return poly_mask((W, H), [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]])
    if rg.get("point"):
        x, y = rg["point"]
        rr = rg.get("width", 0.02) / 2
        return poly_mask((W, H), [[[x - rr, y - rr], [x + rr, y - rr], [x + rr, y + rr], [x - rr, y + rr]]])
    return np.zeros((H, W), np.float32)


def render_occluders(ov, W, H, out, path=None):
    """occ.png: what a crawling critter (src/library/critters.js) passes behind, from "critter_occ" in the masks
    json: region names and/or polygons (tools/analyze_plate.py puts there what the critter hides behind at its
    path ends). Grown ~2 px so no sliver of the creature shows along an outline; 255 = in front of the critter.
    With several critters, "critter_occ_tracks" ({track: polygons}) gives each its own occ_<track>.png (plus the
    named regions in "critter_occ"): one track's cover must not hide another critter walking on it.
    occ_preview.jpg: the plate with them in red and the critters' paths (scenes/<plate>/scene.json) in cyan."""
    for f in ["occ.png", "occ_preview.jpg", *[p.name for p in out.glob("occ_*.png")]]:
        (out / f).unlink(missing_ok=True)
    items = ov.get("critter_occ") or []
    if not items:
        return
    by_name = {rg.get("name"): rg for rg in ov.get("regions") or []}
    k = max(3, 2 * round(2 * W / 3840) + 1)

    def raster(its):
        m = np.zeros((H, W), np.float32)
        for it in its:
            if isinstance(it, str):
                if it not in by_name:
                    print(f"  critter_occ: no region named {it}")
                    continue
                m = np.maximum(m, region_raster(by_name[it], W, H))
            else:
                m = np.maximum(m, poly_mask((W, H), [it]))
        if m.any():
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            m = cv2.GaussianBlur(m, (0, 0), 0.7 * W / 3840)
        return m
    m = raster(items)
    if not m.any():
        return
    Image.fromarray((np.clip(m, 0, 1) * 255).round().astype(np.uint8)).save(out / "occ.png")
    named = [x for x in items if isinstance(x, str)]
    for tr, polys in (ov.get("critter_occ_tracks") or {}).items():
        mt = raster(named + list(polys))
        Image.fromarray((np.clip(mt, 0, 1) * 255).round().astype(np.uint8)).save(out / f"occ_{tr}.png")
    print(f"  critter occluders: {len(items)} -> occ.png ({float((m > 0.5).mean()) * 100:.2f}% of the frame)"
          + (f", one map per track: {', '.join('occ_%s.png' % t for t in ov['critter_occ_tracks'])}" if ov.get("critter_occ_tracks") else ""))
    if path is None:
        sp = ROOT / "scenes" / out.name / "scene.json"
        spec = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        path = [L.get("path") for L in spec.get("layers", []) if L.get("type") == "critter" and L.get("path")]
    paths = [path] if path and isinstance(path[0][0], (int, float)) else (path or [])
    src = out / "plate.png" if (out / "plate.png").exists() else out / "plate_raw.png"
    pv = np.asarray(Image.open(src).convert("RGB").resize((W // 2, H // 2)), np.float32) / 255
    o = cv2.resize(m, (W // 2, H // 2))[..., None]
    pv = pv * (1 - 0.5 * o) + np.array([1, 0.1, 0.1], np.float32) * 0.5 * o
    im = Image.fromarray((np.clip(pv, 0, 1) * 255).astype(np.uint8))
    for pth in paths:
        if pth:
            ImageDraw.Draw(im).line([(x * W / 2, y * H / 2) for x, y in pth], fill=(0, 230, 255), width=2)
    im.save(out / "occ_preview.jpg", quality=88)


def frame_tophat(disp, W):
    """How much nearer each pixel stands than the surface around it, for things thinner than about 3% of the frame's
    width (window frames, mullions, a door's stiles and handle, stake tips): a white top-hat of the disparity. A smooth
    slope (ground running toward the camera) gives ~0; only ridges count."""
    k = max(15, int(0.03 * W)) | 1
    return cv2.morphologyEx(disp.astype(np.float32), cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))


def view_color_share(img, cand, view):
    """For each candidate pixel, the share of the view pixels around it (a Gaussian of 1.5% of the frame's width) with
    nearly its color (Lab within one bin: 8 in L, 10 in a and b). The depth model smears a near leaf's depth over the
    view beside it, so depth alone takes that view for a frame (the rainy cafe lost a band of wet street above its
    plant, 2026-10-21); that view finds its own colors all around, a brown frame against a blue view finds none.
    img: RGB floats 0..1. Works at about 960 px wide."""
    H, W = cand.shape
    s = max(1, W // 960)
    size = (W // s, H // s)
    sm = lambda m: cv2.resize(m.astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0.5
    lab = cv2.cvtColor(cv2.resize(np.ascontiguousarray(img, np.float32), size, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2LAB)
    qL = np.clip(lab[..., 0] / 8, 0, 12).astype(np.int32)
    qa = np.clip((lab[..., 1] + 65) / 10, 0, 12).astype(np.int32)
    qb = np.clip((lab[..., 2] + 65) / 10, 0, 12).astype(np.int32)
    q = qL * 169 + qa * 13 + qb
    v, c = sm(view), sm(cand)
    sig = 0.015 * W / s
    den = np.maximum(cv2.GaussianBlur(v.astype(np.float32), (0, 0), sig), 1e-4)
    share = np.zeros(c.shape, np.float32)
    for b in np.unique(q[c]):
        L, A, B = b // 169, (b // 13) % 13, b % 13
        near = (np.abs(qL - L) <= 1) & (np.abs(qa - A) <= 1) & (np.abs(qb - B) <= 1)
        sel = c & (q == b)
        share[sel] = (cv2.GaussianBlur((v & near).astype(np.float32), (0, 0), sig) / den)[sel]
    return cv2.resize(share, (W, H), interpolation=cv2.INTER_NEAREST)


def pane_structure(img, disp, glass, view, t, thr=None, od=None):
    """Thin structure in the glass that must stay dry: nearer than what is around it (frame_tophat over t, or above
    the pane's own depth split thr) and colored unlike the view beside it (view_color_share under 4%)."""
    cand = (frame_tophat(disp, disp.shape[1]) > t) & glass
    if thr is not None:
        cand |= glass & (disp > thr) & (disp < od)
    if not cand.any():
        return cand
    return cand & (view_color_share(img, cand, view & glass & (frame_tophat(disp, disp.shape[1]) < t / 2)) < 0.04)


def flat_surface(disp, wmask, r):
    """Where depth says the surface is level (ground, puddles, water): a level surface's disparity grows steadily
    down the screen (disparity ~ rows below the horizon), while walls, step risers, posts and plants hold their
    disparity up and down. Rain rings drawn on an upright surface read as streaks (the ramen alley's wall by the
    post, 2026-10-18). Returns 1 = level, 0 = upright, judged against the median slope of the whole wet mask."""
    sel = wmask > 0.5
    if sel.sum() < 2000:
        return np.ones_like(disp, np.float32)
    # the surface's own disparity only (normalized blur over the wet pixels): a much nearer thing next to it (the cat
    # in front of the wall behind it, 2026-10-19) must not lend its depth step to the surface as a slope
    sw = cv2.GaussianBlur(sel.astype(np.float32), (0, 0), 6 * r)
    ds = cv2.GaussianBlur((disp * sel).astype(np.float32), (0, 0), 6 * r) / np.maximum(sw, 1e-3)
    gy = cv2.Sobel(ds, cv2.CV_32F, 0, 1, ksize=5) / 32.0
    a = float(np.median(gy[sel]))
    if a <= 1e-6:
        return np.ones_like(disp, np.float32)
    ratio = cv2.GaussianBlur(gy / a, (0, 0), 5 * r)
    flat = np.clip((ratio - 0.2) / 0.25, 0, 1).astype(np.float32)
    # drop little islands that survive inside an upright patch
    keep = (flat > 0.5) & sel
    n, lab, st, _ = cv2.connectedComponentsWithStats(keep.astype(np.uint8), connectivity=8)
    small = np.isin(lab, [k for k in range(1, n) if st[k, cv2.CC_STAT_AREA] < 0.0004 * disp.size])
    flat[small] = 0
    return flat


def pixelize(img, cell, ox, oy):
    """Rebuild a pixel-art plate on an exact grid: every cell becomes one flat color (median of its interior),
    so the plate and the animation (snapped to the same grid by the output pass) share one pixel size."""
    a = np.asarray(img, np.uint8)
    H, W = a.shape[:2]
    out = np.empty_like(a)
    xs = np.unique(np.clip(np.round(ox + np.arange(-1, W / cell + 2) * cell).astype(int), 0, W))
    ys = np.unique(np.clip(np.round(oy + np.arange(-1, H / cell + 2) * cell).astype(int), 0, H))
    for y0, y1 in zip(ys[:-1], ys[1:]):
        for x0, x1 in zip(xs[:-1], xs[1:]):
            blk = a[y0:y1, x0:x1]
            inner = blk[1:-1, 1:-1] if blk.shape[0] > 3 and blk.shape[1] > 3 else blk
            out[y0:y1, x0:x1] = np.median(inner.reshape(-1, 3), axis=0)
    return Image.fromarray(out)
