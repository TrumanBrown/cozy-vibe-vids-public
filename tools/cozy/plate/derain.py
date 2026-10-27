"""Painted transients out of the plate (TASKS.md T16), moved verbatim from plate_prep.py: what is painted still
looks frozen under the animation.

  derain, derain_pass    painted rain streaks (thin bright lines that hold down a column)
  cleanup                the masks json's "inpaint", "inpaint_bright" and "desnow"
  pixel_grid             a pixel-art plate's cell size and origin
  derain_cells           painted rain dashes on that grid
"""
import cv2
import numpy as np
from PIL import Image

from cozy.masks import poly_mask
from cozy.plate.primitives import soften


def derain(img, outdoor, lights, ov):
    """Remove rain streaks painted into the key art (static streaks look frozen under animated rain).
    A painted streak is a thin bright line that stays consistent down a column: horizontal high-pass,
    then long vertical averaging (two scales) gated by vertical coherence. Only outdoors, away from
    light sources, outside `not_derain` polygons (waterfalls etc.). "passes": 2 repeats it for dense
    painted rain (one pass leaves faint streaks)."""
    cfg = ov.get("derain", {})
    if cfg is False or cfg.get("strength", 1.0) <= 0:
        return img, np.zeros(outdoor.shape, np.float32)
    total = np.zeros(outdoor.shape, np.float32)
    for k in range(max(1, int(cfg.get("passes", 1)))):
        # later passes relax the coherence gate: once the first pass has taken the strong streaks, what is left of them is
        # weak next to the texture around it and the gate stopped seeing it; two passes left a third of the Minecraft tea
        # house's painted rain over its far hills, frozen under the moving rain (the static check found it, 2026-10-22)
        img, corr = derain_pass(img, outdoor, lights, ov, cfg, thr=0.45 if k == 0 or not cfg.get("relaxed") else float(cfg["relaxed"]))
        total += corr
    return img, total


def derain_pass(img, outdoor, lights, ov, cfg, thr=0.45):
    a = np.asarray(img, np.float32) / 255
    H, W = outdoor.shape
    r = W / 3840
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    R = lum - cv2.GaussianBlur(lum, (0, 0), sigmaX=3.0 * r, sigmaY=0.01)
    corr = np.zeros_like(lum)
    for sy in (14.0, 6.0):
        Rv = cv2.GaussianBlur(R, (0, 0), sigmaX=0.01, sigmaY=sy * r)
        A = cv2.GaussianBlur(np.abs(R), (0, 0), sigmaX=0.01, sigmaY=sy * r) + 1e-4
        coh = np.clip((Rv / A - thr) / 0.35, 0, 1)
        corr = np.maximum(corr, np.maximum(Rv, 0) * coh)
    w = outdoor * np.clip(1 - cv2.GaussianBlur(lights, (0, 0), 25 * r) * 3, 0, 1)
    # Painted rain is cool/desaturated: protect warm saturated pixels (distant windows, lamps, leaves).
    sat = (a.max(-1) - a.min(-1)) / (a.max(-1) + 1e-6)
    warm = ((a[..., 0] > a[..., 2] + 0.08) & (sat > 0.3) & (lum > 0.12)).astype(np.float32)
    warm = np.clip(cv2.GaussianBlur(cv2.dilate(warm, np.ones((5, 5), np.uint8)), (0, 0), 2 * r) * 2, 0, 1)
    w = w * (1 - warm)
    if ov.get("not_derain"):
        w = w * (1 - soften(poly_mask((W, H), ov["not_derain"]), 4 * r))
    corr = cv2.GaussianBlur(corr * w * float(cfg.get("strength", 1.5)), (0, 0), sigmaX=1.0 * r, sigmaY=0.01)
    out = np.clip(a - corr[..., None], 0, 1)
    return Image.fromarray((out * 255).round().astype(np.uint8)), corr


def cleanup(img, ov, outdoor):
    """Remove painted transients that would look frozen under the animation (masks json keys):
      inpaint         polygons (painted lightning bolts, sparks): Telea inpainting
      inpaint_bright  boxes: only the thin bright strokes inside (painted drips), so the texture around survives
      desnow          true: small bright painted snowflakes outdoors replaced by their surroundings
    Painted steam stays: it is too close to the scenery to separate, and the animated steam streams over it."""
    if not (ov.get("inpaint") or ov.get("inpaint_bright") or ov.get("desnow")):
        return img
    a = np.asarray(img, np.uint8).copy()
    H, W = a.shape[:2]
    r = W / 3840
    m = poly_mask((W, H), ov["inpaint"]) > 0.5 if ov.get("inpaint") else np.zeros((H, W), bool)
    for box in ov.get("inpaint_bright") or []:
        # only the thin bright strokes inside the box (painted drips, sparks), so the texture around survives
        x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
        lum = a[y0:y1, x0:x1].astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32) / 255
        bg = cv2.medianBlur((lum * 255).astype(np.uint8), int(21 * r) | 1).astype(np.float32) / 255
        m[y0:y1, x0:x1] |= (lum - bg) > 0.06
    if m.any():
        m = cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(7 * r) | 1, int(7 * r) | 1)))
        a = cv2.inpaint(a, m * 255, max(3, int(4 * r)), cv2.INPAINT_TELEA)
        print(f"  inpainted {int(m.sum())} px (painted transients)")
    if ov.get("desnow"):
        f = a.astype(np.float32) / 255
        lum = f @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(9 * r) | 1, int(9 * r) | 1))
        th = lum - cv2.morphologyEx(lum, cv2.MORPH_OPEN, ker)
        sat = (f.max(-1) - f.min(-1)) / (f.max(-1) + 1e-4)
        m = ((th > 0.05) & (sat < 0.35) & (outdoor > 0.5)).astype(np.uint8)
        m = cv2.dilate(m, np.ones((3, 3), np.uint8))
        med = cv2.medianBlur(a, int(9 * r) | 1)
        a = np.where(m[..., None] > 0, med, a)
        print(f"  desnow: {int(m.sum())} px of painted snowflakes removed")
    return Image.fromarray(a)


def pixel_grid(img, lo=4.0, hi=30.0):
    """Pixel-art grid of an image: (cell px, origin x, origin y) or None. The period is the spacing of the
    autocorrelation peaks of the column / row profiles of the luminance gradient (fitted over several
    multiples, sub-pixel); the origin is the comb phase that puts the most pseudo-pixel edges on cell edges."""
    a = np.asarray(img.convert("L"), np.float32) / 255

    def period(prof):
        p = prof - cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 12).ravel()
        p = p - p.mean()
        ac = np.correlate(p, p, "full")[len(p) - 1:]
        ac = ac / max(ac[0], 1e-12)
        pk = [l for l in range(int(lo), int(hi) + 1) if ac[l] > ac[l - 1] and ac[l] >= ac[l + 1] and ac[l] > 0.12]
        if not pk:
            return None, p
        L1 = pk[0]
        est = []
        for k in range(1, 7):
            c = int(round(k * L1 * (np.mean(est) / L1 if est else 1)))
            w = max(2, k)
            seg = range(max(1, c - w), min(len(ac) - 1, c + w + 1))
            l = max(seg, key=lambda i: ac[i])
            d = ac[l - 1] - 2 * ac[l] + ac[l + 1]
            sub = l + (0.5 * (ac[l - 1] - ac[l + 1]) / d if d < 0 else 0)
            est.append(sub / k)
        return float(np.median(est)), p

    def phase(p, P):
        n = len(p)
        k = np.arange(0, n / P - 1)
        best, bph = -1e9, 0.0
        for ph in np.arange(0, P, 0.25):
            x = ph + k * P
            i = np.floor(x).astype(int)
            f = x - i
            s = ((1 - f) * p[i] + f * p[np.minimum(i + 1, n - 1)]).mean()
            if s > best:
                best, bph = s, ph
        return bph

    px, prx = period(np.abs(np.diff(a, axis=1)).mean(0))
    py, pry = period(np.abs(np.diff(a, axis=0)).mean(1))
    if px is None and py is None:
        return None
    P = float(np.mean([v for v in (px, py) if v]))
    if px and py and abs(px - py) > 0.3:
        print(f"  pixel grid: x {px:.2f} / y {py:.2f} disagree; using their mean")
    # gradient between pixels i and i+1 sits at i + 1: cell edges are at phase + 1
    return P, phase(prx, P) + 1.0, phase(pry, P) + 1.0


def derain_cells(img, pg, outdoor, lights, ov, passes=2, maxrun=14):
    """Painted rain on a pixel-art plate (after pixelize): each dash is one cell wide and 2-8 cells tall, wider than
    derain()'s 3 px high-pass sees, so they stayed frozen in the pixel greenhouse's sky (2026-10-21). On the cell grid a
    dash is a run of 2..maxrun cells down a column, each brighter than both its row neighbors while those two match,
    outdoors, away from lights, not warm (lit windows); each such cell takes the mean of its row neighbors. Longer runs
    are structure (a mullion's lit edge, a pole). Inside `derain_extra` polygons (masks or hand json) the light and warm
    guards are off: glass in a lamp's glow. Returns (image, cells changed)."""
    cfg = ov.get("derain", {})
    if cfg is False or cfg.get("strength", 1.0) <= 0:
        return img, 0
    a = np.asarray(img, np.float32) / 255
    H, W = outdoor.shape
    cell, (ox, oy) = pg["cell"], pg["origin"]
    xs = np.unique(np.clip(np.round(ox + np.arange(-1, W / cell + 2) * cell).astype(int), 0, W))
    ys = np.unique(np.clip(np.round(oy + np.arange(-1, H / cell + 2) * cell).astype(int), 0, H))
    cx, cy = (xs[:-1] + xs[1:]) // 2, (ys[:-1] + ys[1:]) // 2
    small = a[cy][:, cx].copy()
    lg = cv2.GaussianBlur(lights.astype(np.float32), (0, 0), 25 * W / 3840)[cy][:, cx]
    # "derain_extra" polygons (hand.json): glass in a lamp's glow, where the guards against lit windows and lamps kept
    # the painted streaks (the pixel greenhouse's panes beside its lantern, 2026-10-21)
    extra = (poly_mask((W, H), ov["derain_extra"]) > 0.5)[cy][:, cx] if ov.get("derain_extra") else np.zeros((len(cy), len(cx)), bool)
    ok = ((outdoor[cy][:, cx] > 0.5) & (lg < 0.15)) | extra
    ok = ok & np.roll(ok, 1, 1) & np.roll(ok, -1, 1)
    ok[:, 0] = ok[:, -1] = False
    lw = np.array([0.2126, 0.7152, 0.0722], np.float32)
    changed = np.zeros(ok.shape, bool)
    for _ in range(passes):
        lum = small @ lw
        Lc, Rc = np.roll(small, 1, 1), np.roll(small, -1, 1)
        L, R = Lc @ lw, Rc @ lw
        sat = (small.max(-1) - small.min(-1)) / (small.max(-1) + 1e-6)
        warm = (small[..., 0] > small[..., 2] + 0.08) & (sat > 0.3) & ~extra
        weak = ok & (np.minimum(lum - L, lum - R) > 0.008) & (lum - 0.5 * (L + R) > 0.015) & (np.abs(L - R) < 0.08) & ~warm
        dash = np.zeros_like(weak)
        for x in np.nonzero(weak.any(0))[0]:
            d = np.diff(np.concatenate([[0], weak[:, x].astype(np.int8), [0]]))
            for s, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
                if 2 <= e - s <= maxrun:
                    dash[s:e, x] = True
        if not dash.any():
            break
        small[dash] = 0.5 * (Lc[dash] + Rc[dash])
        changed |= dash
    for j, i in zip(*np.nonzero(changed)):
        a[ys[j]:ys[j + 1], xs[i]:xs[i + 1]] = small[j, i]
    return Image.fromarray((np.clip(a, 0, 1) * 255).round().astype(np.uint8)), int(changed.sum())
