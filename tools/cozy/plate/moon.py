"""The plate's moon and its glitter on the water, lifted off so the moon can cross the sky (src/library/plate.js `moon`).

Truman asked for the jungle temple's moon to move rather than stay in one spot (2026-10-27, L168). plate_prep lifts the
painted moon off the plate when the masks json has "moon" (hand.json: {"box": [x0, y0, x1, y1] around it, or a list of
boxes, one per moon, for moons that move together as one sprite, "glitter": [x0, y0, x1, y1] around its glitter on the
water, optional}):

  lift_moon(img, sky, box)      the moon's disk as a sprite, its halo measured ring by ring in the sky (median: stars and
                                clouds left out) and taken off, the disk painted over with the sky around it
  lift_glitter(img, water, box) the moonlight glitter on the water: what stands above a morphological opening of the
                                water's brightness, taken off; plate.js adds it back under the moon wherever the moon is

Both work in linear light. Writes moon.png (RGBA), moonfx.png (red: where the moon and its glow show, air_matte; green:
the glitter's linear luminance, its color in moon.json) and moon.json (the disk's center and size in px, the halo's
excess linear RGB by radius, the glitter's box and color) to the plate folder. When the sky around the moon was
repainted (tools/plate_clean.py kind "moon"), the moon and its glow are measured on the key art as painted and the
plate's sky is left as it is.
"""
import json
import warnings

import cv2
import numpy as np
from PIL import Image

from cozy.plate.primitives import guided_filter, srgb_to_linear


def _to_srgb(lin):
    lin = np.clip(lin, 0, 1)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def _boxes(box):
    """hand.json moon "box": one box (x0, y0, x1, y1, fractions) or a list of them, one per moon: the Sleeping Hound
    Inn's Masser and Secunda move together as one sprite (2026-11-15). Each is found by its own brightness: one
    threshold over both took the bright white Secunda and only part of the dim red Masser."""
    return [list(box)] if isinstance(box[0], (int, float)) else [list(b) for b in box]


def _union(box):
    bs = _boxes(box)
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def lift_moon(img, sky, box, glow=(2.4, 3.2), polys=None, grow=3):
    """(img without the moon and its halo, the sprite RGBA, meta). box: fractions around the painted moon, or a list of
    boxes, one per moon (_boxes: their disks are one sprite). polys (hand.json moon "polys", fractions): the moons'
    outlines measured by hand, used instead of finding each by its brightness, grown by `grow` px for the soft limb. A
    painted moon whose unlit side shows (the Sleeping Hound Inn's Masser: a dim red-gray disk beside its lit side) has
    no threshold that takes it whole: its lit side alone would have crossed the sky. The halo is
    measured in rings by distance from the disk's own outline (a blocky moon is a square, and rings around its center
    mixed the glow at its edges with the sky off its corners: a dark ring was left where the moon had been). glow: where
    the plain sky starts and how far out to measure, in moon sizes from its outline (hand.json moon "glow"; the jungle
    temple's painted glow reached about 4 sizes)."""
    a = np.asarray(img, np.float32) / 255
    H, W = a.shape[:2]
    lin = srgb_to_linear(a)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    disk = np.zeros((H, W), np.uint8)
    if polys:
        for p in polys:
            cv2.fillPoly(disk, [np.round(np.array(p, np.float64) * [W, H]).astype(np.int32)], 1)
        if grow > 0:
            disk = cv2.dilate(disk, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    for b in ([] if polys else _boxes(box)):
        x0, y0, x1, y1 = int(b[0] * W), int(b[1] * H), int(b[2] * W), int(b[3] * H)
        sub = lum[y0:y1, x0:x1]
        hot = (sub > 0.55 * float(sub.max())).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(hot)
        i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        pts = cv2.findNonZero((lab == i).astype(np.uint8))
        cv2.fillConvexPoly(disk, cv2.convexHull(pts) + np.array([x0, y0]), 1)
    disk = cv2.dilate(disk, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(disk)
    cx, cy = (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
    hx, hy = (xs.max() + 1 - xs.min()) / 2, (ys.max() + 1 - ys.min()) / 2
    side = 2 * max(hx, hy)
    soft = cv2.GaussianBlur(disk.astype(np.float32), (0, 0), 1.0)
    # the sprite, before anything is changed
    m = int(max(hx, hy) + 6)
    sx0, sy0, sx1, sy1 = int(cx - m), int(cy - m), int(cx + m) + 1, int(cy + m) + 1
    rgba = np.dstack([(a[sy0:sy1, sx0:sx1] * 255).round(), (soft[sy0:sy1, sx0:sx1] * 255).round()]).astype(np.uint8)
    # the halo: per ring of distance from the disk and per twelfth of the way round, the median sky color (stars, and
    # clouds that fill less than half a cell, are outliers), less the sky's own further out the same way: the glow isn't
    # the same all round, and one median per ring left a dark square on one side and glow on the other
    d = cv2.distanceTransform((1 - disk).astype(np.uint8), cv2.DIST_L2, 5)
    med = cv2.medianBlur((np.clip(lin, 0, 1) * 65535).astype(np.uint16), 5).astype(np.float32) / 65535
    R = int(glow[1] * side)
    bx0, by0, bx1, by1 = max(0, int(cx - hx - R)), max(0, int(cy - hy - R)), min(W, int(cx + hx + R)), min(H, int(cy + hy + R))
    dd, mm, sk = d[by0:by1, bx0:bx1], med[by0:by1, bx0:bx1], (sky[by0:by1, bx0:bx1] > 0.5) & (disk[by0:by1, bx0:bx1] == 0)
    yy, xx = np.mgrid[by0:by1, bx0:bx1]
    NS, step = 12, max(3.0, side / 14)
    sec = ((np.arctan2(yy - cy, xx - cx) + np.pi) / (2 * np.pi) * NS).astype(int) % NS
    rad = np.arange(0, R, step)
    ri = np.minimum((dd / step).astype(int), len(rad) - 1)
    T = np.full((len(rad), NS, 3), np.nan, np.float32)
    for k in range(len(rad)):
        for s in range(NS):
            sel = sk & (ri == k) & (sec == s) & (dd < R)
            if sel.sum() > 12:
                T[k, s] = np.median(mm[sel], axis=0)
    far = rad >= glow[0] * side
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)     # a twelfth with no sky far out (into the trees) takes the rest's
        glob = np.nanmedian(T[far].reshape(-1, 3), axis=0)
        per = np.nanmedian(T[far], axis=0)
    base = np.where(np.isnan(per), glob, per)       # (NS, 3)
    exc = np.zeros_like(T)
    for s in range(NS):
        last = None
        for k in range(len(rad)):
            e = (last if last is not None else np.zeros(3, np.float32)) if np.isnan(T[k, s]).any() else np.maximum(0, T[k, s] - base[s])
            if last is not None:
                e = np.minimum(e, last)      # the halo only falls off outward
            exc[k, s], last = e, e
    exc[far] = 0
    # the glow fades to nothing before the plain sky starts: cut off where it still measured a few levels (the sky's own
    # gradient, or the glow's last faint reach), it drew a ring around the moon
    exc *= np.clip((glow[0] * side - rad) / (0.4 * glow[0] * side), 0, 1)[:, None, None] ** 2
    # bilinear in (distance, angle), the angle wrapping round
    fr = np.clip(dd / step - 0.5, 0, len(rad) - 1.001)
    fs = (np.arctan2(yy - cy, xx - cx) + np.pi) / (2 * np.pi) * NS - 0.5
    k0, s0 = fr.astype(int), np.floor(fs).astype(int)
    wr, ws = (fr - k0)[..., None], (fs - s0)[..., None]
    s0m, s1m = s0 % NS, (s0 + 1) % NS
    E = ((1 - wr) * ((1 - ws) * exc[k0, s0m] + ws * exc[k0, s1m]) + wr * ((1 - ws) * exc[k0 + 1, s0m] + ws * exc[k0 + 1, s1m]))
    E *= np.clip(sky[by0:by1, bx0:bx1], 0, 1)[..., None] * (dd < R)[..., None]
    lin2 = lin.copy()
    lin2[by0:by1, bx0:bx1] = np.maximum(lin[by0:by1, bx0:bx1] - E, 0)
    # the disk painted over with the sky right around it (a wide normalized blur of the halo-free sky): no edge. The
    # hole reaches past the face's own edge to take the moon's darker side face (a blocky moon is a cube seen a little
    # from the side), which an inpaint smeared into a bright wedge
    hole = cv2.dilate(disk, np.ones((51, 51), np.uint8))
    valid = ((hole == 0) & (sky > 0.5) & (d < 160)).astype(np.float32)
    star_free = cv2.medianBlur((np.clip(lin2, 0, 1) * 65535).astype(np.uint16), 5).astype(np.float32) / 65535
    num = np.stack([cv2.GaussianBlur(star_free[..., c] * valid, (0, 0), 30) for c in range(3)], -1)
    den = cv2.GaussianBlur(valid, (0, 0), 30)[..., None]
    fill = num / np.maximum(den, 1e-6)
    w = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 4)[..., None]
    lin2 = fill * w + lin2 * (1 - w)
    # what the halo's removal leaves is a faint blotch of low frequencies (the glow wasn't round): near the old disk the
    # sky's broad shape is set to the gradient fitted further out, its fine detail (stars, cloud edges) kept, clouds left
    sf = cv2.medianBlur((np.clip(lin2, 0, 1) * 65535).astype(np.uint16), 5).astype(np.float32) / 65535
    lsf = sf @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    blum = float(np.median(base, axis=0) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    cloud = cv2.dilate((lsf > 1.6 * blum).astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    clear = (sky > 0.5) & ~cloud
    ann = clear & (d >= 1.6 * side) & (d < 3.6 * side)
    yy2, xx2 = np.nonzero(ann)
    if len(xx2) > 500:
        core = (d < 2.4 * side) & clear
        u, v = (xx2 - cx) / 400.0, (yy2 - cy) / 400.0
        A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
        cy_, cx_ = np.nonzero(core)
        uc, vc = (cx_ - cx) / 400.0, (cy_ - cy) / 400.0
        Ac = np.stack([np.ones_like(uc), uc, vc, uc * uc, uc * vc, vc * vc], 1)
        valid = clear.astype(np.float32)
        den = cv2.GaussianBlur(valid, (0, 0), 30)
        wt = np.clip((2.4 * side - d) / (0.8 * side), 0, 1) * core
        for c in range(3):
            coef = np.linalg.lstsq(A, sf[yy2, xx2, c], rcond=None)[0]
            low = cv2.GaussianBlur(sf[..., c] * valid, (0, 0), 30) / np.maximum(den, 1e-6)
            fix = np.zeros((H, W), np.float32)
            fix[cy_, cx_] = Ac @ coef - low[cy_, cx_]
            lin2[..., c] = np.maximum(lin2[..., c] + fix * wt, 0)
    o8 = (_to_srgb(lin2) * 255).round().astype(np.uint8)
    halo = exc.mean(axis=1)
    meta = {"center": [round(float(cx), 1), round(float(cy), 1)], "half": [round(float(hx), 1), round(float(hy), 1)], "size": round(float(side), 1),
            "sprite": [sx0, sy0, sx1, sy1], "halo": {"d": [round(float(v + step / 2), 1) for v in rad], "rgb": [[round(float(c), 5) for c in e] for e in halo]}}
    return Image.fromarray(o8), Image.fromarray(rgba, "RGBA"), meta


def lift_glitter(img, water, box):
    """(img without the moonlight glitter on the water inside box, the glitter's linear luminance (0..1, float), meta with
    its color: the glitter is the moon's light, one color scaled by its luminance)."""
    a = np.asarray(img, np.float32) / 255
    H, W = a.shape[:2]
    lin = srgb_to_linear(a)
    x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
    win = np.zeros((H, W), np.float32)
    win[y0:y1, x0:x1] = 1
    win = cv2.GaussianBlur(win, (0, 0), 0.03 * W) * (water > 0.5)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    floor = np.stack([cv2.GaussianBlur(cv2.morphologyEx(lin[..., c], cv2.MORPH_OPEN, k), (0, 0), 6) for c in range(3)], -1)
    g = np.maximum(lin - floor, 0) * win[..., None]
    out = _to_srgb(np.maximum(lin - g, 0))
    lum = g @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    rgb = g.reshape(-1, 3).sum(0) / max(float(lum.sum()), 1e-6)
    return (Image.fromarray((out * 255).round().astype(np.uint8)), np.clip(lum, 0, 1),
            {"box": list(box), "peak": round(float(lum.max()), 4), "rgb": [round(float(c), 4) for c in rgb]})


def _bright(img, box):
    """How bright the box is over most of it (80th percentile, linear): the moon fills about half its box, a star in a
    repainted sky a few pixels (the peak alone took a bright star for the moon)."""
    a = srgb_to_linear(np.asarray(img, np.float32) / 255) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    H, W = a.shape
    return float(np.percentile(a[int(box[1] * H):int(box[3] * H), int(box[0] * W):int(box[2] * W)], 80))


def air_matte(img, sky, box=(0.5, 0.0, 1.0, 0.5), band=40, unsure=None):
    """Where the moon's glow lights the picture and its face can show: the open sky, against everything solid in front of
    it (treetops, ruins, vines; clouds are left out, they hide the face and take no glow), snapped to the plate's own
    edges. The analysis's sky outline is smooth and runs dozens of px off the real treetops: the moon rose behind a
    smooth dark blob with its glow stopping at the outline (2026-10-27). Within `band` px of that outline, and wherever
    `unsure` (behind strands lifted onto their own layer: the analysis saw the strands, the repainted plate shows what
    was behind them), every pixel goes by its color, nearer the open sky's around it or the solid things' (star-free);
    inside the outline, what is far darker than the sky around it is a treetop the outline took in. Only inside box
    (the moon's part of the frame)."""
    a = np.asarray(img, np.float32) / 255
    H, W = a.shape[:2]
    out = (np.asarray(sky, np.float32) > 0.5).astype(np.float32)
    x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
    s = out[y0:y1, x0:x1] > 0.5
    un = np.zeros_like(s) if unsure is None else np.asarray(unsure, bool)[y0:y1, x0:x1]
    med = cv2.medianBlur((a[y0:y1, x0:x1] * 255).round().astype(np.uint8), 5).astype(np.float32) / 255
    ker = np.ones((2 * band + 1, 2 * band + 1), np.uint8)
    sure_sky = (cv2.erode(s.astype(np.uint8), ker) > 0) & ~un
    sure_solid = (cv2.erode((~s).astype(np.uint8), ker) > 0) & ~un

    def nblur(v, w, sg):
        w = w.astype(np.float32)
        return cv2.GaussianBlur(v * w[..., None], (0, 0), sg) / np.maximum(cv2.GaussianBlur(w, (0, 0), sg), 1e-6)[..., None]

    def around(w):
        """The color of w's pixels around each point; from further off where none are near (behind a wide curtain)."""
        near, wn = nblur(med, w, 60), cv2.GaussianBlur(w.astype(np.float32), (0, 0), 60)
        return np.where((wn > 0.02)[..., None], near, nblur(med, w, 240))

    sky_c, sol_c = around(sure_sky), around(sure_solid)
    d_sky, d_sol = np.linalg.norm(med - sky_c, axis=2), np.linalg.norm(med - sol_c, axis=2)
    lum = np.array([0.2126, 0.7152, 0.0722], np.float32)
    edge = (~sure_sky & ~sure_solid) | un
    m = np.where(edge, d_sky < d_sol, s)
    m &= ~(m & (med @ lum < 0.55 * (sky_c @ lum)))      # a treetop the outline took in: far darker than the sky
    g = med @ lum
    out[y0:y1, x0:x1] = np.clip(guided_filter(g, m.astype(np.float32), 4, 1e-4), 0, 1)
    return out


def lifted(out, W, H):
    """Where strands were lifted onto their own layer (tools/vine_layers.py, lift.json), grown 20 px; None if none."""
    lj = out / "lift.json"
    if not lj.exists():
        return None
    m = np.zeros((H, W), np.uint8)
    for s in json.loads(lj.read_text(encoding="utf-8")).get("strands", []):
        x0, y0, x1, y1 = s["box"]
        al = np.asarray(Image.open(out / s["file"]).convert("RGBA"))[..., 3] > 25
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        m[cy0:cy1, cx0:cx1] |= al[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0].astype(np.uint8)
    return cv2.dilate(m, np.ones((41, 41), np.uint8)) > 0


def lift(img, sky, water, spec, out, orig=None, repainted=False):
    """plate_prep's step: the moon (and its glitter) off the plate, its sprite and data into the plate folder. When the
    sky around it was repainted (tools/plate_clean.py kind "moon": no moon left on the plate; `repainted`, from
    plate_clean's record), the moon and its glow are measured on orig, the key art as painted at the plate's size, and
    the plate's sky stays as repainted. Without that record a repaint is guessed by the box getting much darker: the
    Sleeping Hound Inn's dim red Masser didn't darken its box enough, and a moon was looked for on the clean sky."""
    glow = tuple(spec.get("glow") or (2.4, 3.2))
    if orig is not None and (repainted or _bright(img, _union(spec["box"])) < 0.3 * _bright(orig, _union(spec["box"]))):
        _, sprite, meta = lift_moon(orig, sky, spec["box"], glow, spec.get("polys"), spec.get("grow", 3))
        meta["repainted"] = True
    else:
        img, sprite, meta = lift_moon(img, sky, spec["box"], glow, spec.get("polys"), spec.get("grow", 3))
    sprite.save(out / "moon.png")
    W, H = img.size
    glit = np.zeros((H, W), np.float32)
    if spec.get("glitter"):
        img, glit, gm = lift_glitter(img, water, spec["glitter"])
        meta["glitter"] = gm
    # one map for both (the plate's shader is at its limit of 16 textures): red where the moon and its glow show,
    # green the glitter's luminance
    air = air_matte(img, sky, unsure=lifted(out, W, H))
    fx = np.stack([air, glit, np.zeros_like(air)], -1)
    Image.fromarray((np.clip(fx, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "moonfx.png")
    (out / "moon.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print(f"  moon: {meta['size']} px at {meta['center']} "
          + ("measured on the key art as painted (the sky around it repainted)" if meta.get("repainted") else "lifted off")
          + f" with its halo ({len(meta['halo']['d'])} rings)"
          + (f"; glitter on the water up to {meta['glitter']['peak']}" if spec.get("glitter") else ""))
    return img
