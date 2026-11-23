"""The plate's painted northern lights, lifted off the sky so the aurora layer can make them ripple
(src/library/aurora.js; Truman 2026-11-08: the northern lights rippling, the Skyrim mill).

An aurora is light: it adds to the night sky behind it and to nothing in front (mountains, trees, roofs). plate_prep
lifts it when the masks json has "aurora" (hand.json: {"box": [x0, y0, x1, y1] around it in the sky, "reflect":
[x0, y0, x1, y1] around its green on the water, optional; "pull" (3), "keep" (0.02) and "solid" (false), sky_matte's
below: a sky traced to the silhouette at 4K can take pull 1 and solid, and keep 0.0005 holds a small window of sky
such as an arch's, when the outline has no islands on the slopes; the Sleeping Hound Inn, 2026-11-15, where the light
is brightest right at the ridge and what of it stayed on the plate there read as a glowing rim; "silhouette" (off, 0.3
there): pixels inside the traced sky darker than the fitted sky by more than that share of it are land and stay on
the plate; "extend" (40 px): how far the lifted light continues past the sky's edge in the maps, for the folds}):

  sky_matte(sky)        where the light shows: the analysis's sky outline (SAM, which follows the ridge to a few px)
                        without its stray islands, pulled in 3 px and feathered. Not the moon's air_matte: its color
                        test took the snowy peaks for sky, since they are as light as an aurora sky
  base_fit(lin, mask)   the sky without the aurora: a smooth surface per channel fitted to the sky's lower envelope
                        (asymmetric least squares on a 1/8 image: what lies above the fit is light added to it)
  stars(lin, sky)       the small bright points, which stay on the plate (the aurora moves, the stars don't)
  lift(...)             the aurora's light off the plate, signed: aurora.png (what lies above the smooth base, sRGB-coded
                        linear light times `gain`) and aurora_neg.png (the paint darker than the base, times
                        `dark_gain`), so the light, its brush strokes and the paper grain under it move as one; and
                        aurorafx.png (R: where the light shows; G: how much of the water's color there is the light's
                        mirror image, which the layer brightens and dims with the light above it; the water's paint
                        stays on the plate, where the river's own ripples move it). aurora.json has the gains, the
                        boxes and the light's lower edge per column (where its curtain hangs lowest)

Works in linear light; the plate's sky under the light is the smooth base and the stars.
"""
import json

import cv2
import numpy as np
from PIL import Image

from cozy.plate.moon import _to_srgb
from cozy.plate.primitives import guided_filter, srgb_to_linear

LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def sky_matte(sky, lum, pull=3, keep=0.02, solid=False):
    """Soft (H, W) float matte of the open sky: the outline's main parts (connected parts under `keep` of the
    largest are islands on the slopes), eroded by `pull` px so no ridge pixel is ever in it, edge-aware feathered.
    `solid`: 1 everywhere inside the eroded outline, soft only past it (the guided filter alone dipped to 0.85 within
    8 px of a bright aurora's ridge, and the 15% of its light left on the plate read as a rim)."""
    s = (np.asarray(sky, np.float32) > 0.5).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(s, connectivity=8)
    if n > 1:
        big = st[1:, cv2.CC_STAT_AREA].max()
        s = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= keep * big]).astype(np.uint8)
    s0 = s
    s = cv2.erode(s, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pull + 1, 2 * pull + 1)))
    # never past the outline itself: with pull under 3 the feather's 2 px would step over it
    m = np.clip(guided_filter(lum, s.astype(np.float32), 3, 1e-4), 0, 1) * (cv2.dilate(s, np.ones((5, 5), np.uint8)) & s0)
    return np.maximum(m, s.astype(np.float32)) if solid else m


def base_fit(lin, mask, deg=3, iters=12, scale=8):
    """(H, W, 3) linear sky without the light added to it: per channel a 2D polynomial fitted to the lower envelope of
    lin inside mask (bool), on a 1/scale image. Points above the fit are light added to the base (the aurora, stars),
    so they get almost no weight (asymmetric least squares)."""
    H, W = mask.shape
    h, w = H // scale, W // scale
    small = cv2.resize(lin, (w, h), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) > 0.95
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        raise ValueError("aurora: too little sky to fit")
    u, v = xs / w * 2 - 1, ys / h * 2 - 1

    def terms(u, v):
        return np.stack([u ** i * v ** j for i in range(deg + 1) for j in range(deg + 1 - i)], 1)

    A = terms(u, v)
    out = np.zeros((H, W, 3), np.float32)
    gy, gx = np.mgrid[0:H, 0:W]
    U, V = (gx + 0.5) / W * 2 - 1, (gy + 0.5) / H * 2 - 1
    for c in range(3):
        y = small[ys, xs, c].astype(np.float64)
        wt = np.ones_like(y)
        for _ in range(iters):
            coef = np.linalg.lstsq(A * wt[:, None], y * wt, rcond=None)[0]
            r = y - A @ coef
            wt = np.where(r > 0, 0.02, 1.0)
        out[..., c] = (terms(U.ravel(), V.ravel()) @ coef).reshape(H, W).astype(np.float32)
    return np.maximum(out, 0)


def stars(lin, sky, k=7, thr=0.012):
    """The stars' light (H, W, 3): what stands above a small morphological opening, in small bright points only."""
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    op = np.stack([cv2.morphologyEx(lin[..., c], cv2.MORPH_OPEN, ker) for c in range(3)], -1)
    top = np.maximum(lin - op, 0)
    pts = (top @ LUM > thr) & (sky > 0.5)
    pts = cv2.dilate(pts.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return top * pts[..., None]


def mirror_share(lin, water, box, light):
    """(H, W) how much of the water's color in box is the aurora's mirror image (0..1): its excess of the light's own
    hue over the water's plain color (a smooth fit of the water's lower envelope), soft at the box's edges."""
    H, W = water.shape
    x0, y0, x1, y1 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
    win = np.zeros((H, W), np.float32)
    win[y0:y1, x0:x1] = 1
    win = cv2.GaussianBlur(win, (0, 0), 0.01 * W) * np.clip(water, 0, 1)
    wb = base_fit(lin, win > 0.5, deg=2)
    lc = light.reshape(-1, 3).sum(0)
    lc = lc / max(float(np.linalg.norm(lc)), 1e-6)
    ex = np.maximum(lin - wb, 0)
    along = np.clip(ex @ lc, 0, None)                    # the excess in the light's own color
    share = along / np.maximum(lin @ np.ones(3, np.float32) / np.sqrt(3), 1e-5)
    return np.clip(cv2.GaussianBlur(share, (0, 0), 2), 0, 1) * win


def _extend(v, src, px, keep=None):
    """(H, W, 3) v continued past the source area by about px: each pixel outside `keep` (bool; default the source
    area itself) takes the normalized blur of v over the source area `src` (0..1; a push-pull fill: wide enough blurs
    carry the edge's light outward, never across the sky itself)."""
    if px <= 0:
        return v
    w = (src > 0.5).astype(np.float32)
    out = v.copy()
    filled = (w if keep is None else keep.astype(np.float32)).copy()
    for s in (px / 8, px / 4, px / 2, px):
        num = cv2.GaussianBlur(v * w[..., None], (0, 0), s)
        den = cv2.GaussianBlur(w, (0, 0), s)
        est = num / np.maximum(den, 1e-6)[..., None]
        take = (filled < 0.5) & (den > 0.02)
        out[take] = est[take]
        filled = np.maximum(filled, take.astype(np.float32))
    return out


def lift(img, sky, water, spec, out):
    """plate_prep's step: the aurora's light off the plate, its maps and data into the plate folder. Returns the plate
    without it."""
    a = np.asarray(img, np.float32) / 255
    H, W = a.shape[:2]
    lin = srgb_to_linear(a)
    bx = spec["box"]
    x0, y0, x1, y1 = int(bx[0] * W), int(bx[1] * H), int(bx[2] * W), int(bx[3] * H)
    win = np.zeros((H, W), np.float32)
    win[y0:y1, x0:x1] = 1
    win = cv2.GaussianBlur(win, (0, 0), 0.01 * W)
    sm = sky_matte(sky, lin @ LUM, pull=int(spec.get("pull", 3)), keep=float(spec.get("keep", 0.02)),
                   solid=bool(spec.get("solid", False)))
    air = sm * win
    st = stars(lin, air)
    base = base_fit(lin - st, air > 0.5)
    ext = int(spec.get("extend", 40))
    if spec.get("silhouette"):
        # At the land's edge the maps must hold the light behind it, not the edge: the layer folds the maps sideways, and
        # whatever the edge left in them (the land's dark paint, or the gap where no light was lifted) drifted into the
        # open sky as specks and a thin dark ghost of the outline (the Sleeping Hound Inn's arch, 2026-11-15). So the
        # maps are the sky's interior continued over the edge and past it, and the layer's matte is how much of each
        # pixel is sky: the darkness against the fitted sky past `silhouette` (a share of it) is land, a soft ramp from
        # 0.05; the plate gives up exactly what the layer adds back at rest.
        thr = float(spec["silhouette"])
        lb = base @ LUM
        ratio = (lb - (lin - st) @ LUM) / np.maximum(lb, 1e-4)
        cov = np.clip(1 - (ratio - 0.05) / max(thr - 0.05, 1e-3), 0, 1)
        air = air * cov
        # the maps' source: the sky inside its outline, not cut by the box's soft border (cut there, the fill drew an
        # arc where the border met the ridge); far outside the box only a little, where the fitted sky still holds
        core = cv2.erode(((sm * cov > 0.97) & (win > 0.01)).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        ec = (lin - st - base) * core[..., None]
        light = _extend(np.maximum(ec, 0), core.astype(np.float32), ext)
        dark = _extend(np.maximum(-ec, 0), core.astype(np.float32), ext)
        e = (light - dark) * air[..., None]
        print(f"  aurora: {int(((cov < 0.5) & (sky > 0.5)).sum())} px of land inside the traced sky kept on the plate "
              f"(silhouette {thr}); the maps carry the sky's light over its edge")
        peak_mask = core
    else:
        # signed: the painting's texture under the light (brush and paper grain darker than the smooth base) goes with the
        # light too, so all of it moves together; the plate's sky is the smooth base and the stars
        e = (lin - st - base) * air[..., None]
        light, dark = np.maximum(e, 0), np.maximum(-e, 0)
        peak_mask = np.ones((H, W), bool)
        # The layer folds the curtain sideways (aurora.js, fold up to 1.6 x 16 px), so at the sky's edge it samples the
        # light from beside the outline, where nothing was lifted: a dark seam followed the ridge, the beams and the
        # gables as the light moved (the Sleeping Hound Inn, 2026-11-15). In the maps the light continues past the
        # outline into the land; the plate is unchanged, and the layer still draws only inside the sky's matte.
        light, dark = _extend(light, air, ext, keep=air > 0), _extend(dark, air, ext, keep=air > 0)
    lin2 = lin - e
    pm = peak_mask[y0:y1, x0:x1]
    peak = float(np.percentile((light @ LUM)[y0:y1, x0:x1][pm], 99.9)) or 1e-3
    gain = 0.85 / max(peak, 1e-4)
    dpeak = float(np.percentile((dark @ LUM)[y0:y1, x0:x1][pm], 99.9)) or 1e-3
    dgain = 0.85 / max(dpeak, 1e-4)
    Image.fromarray((_to_srgb(np.clip(light * gain, 0, 1)) * 255).round().astype(np.uint8), "RGB").save(out / "aurora.png")
    Image.fromarray((_to_srgb(np.clip(dark * dgain, 0, 1)) * 255).round().astype(np.uint8), "RGB").save(out / "aurora_neg.png")
    light = light * (air > 0)[..., None]          # the sky's own light, for the reflection's color and the curtain's edge
    share = mirror_share(lin2, np.asarray(water, np.float32), spec["reflect"], light) if spec.get("reflect") else np.zeros((H, W), np.float32)
    fx = np.stack([air, share, np.zeros((H, W), np.float32)], -1)
    Image.fromarray((np.clip(fx, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "aurorafx.png")
    # the curtain's lower edge per column: the lowest row where the light still holds a tenth of its column's most
    col = light @ LUM
    edge = []
    for x in range(0, W, 16):
        c = col[:, x:x + 16].mean(1)
        hit = np.nonzero(c > 0.1 * max(float(c.max()), 1e-6))[0]
        edge.append(int(hit[-1]) if len(hit) else -1)
    meta = {"box": [x0, y0, x1, y1], "gain": round(gain, 4), "peak": round(peak, 5), "dark_gain": round(dgain, 4),
            "edge_step": 16, "edge": edge, "light_sum": round(float(col.sum()), 2), "stars": int((st @ LUM > 0).sum())}
    if spec.get("reflect"):
        rb = spec["reflect"]
        meta["reflect"] = [int(rb[0] * W), int(rb[1] * H), int(rb[2] * W), int(rb[3] * H)]
        meta["mirror_mean"] = round(float(share[share > 0.02].mean()) if (share > 0.02).any() else 0.0, 4)
    (out / "aurora.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print(f"  aurora: light lifted off the sky (peak {peak:.4f} linear, gain {gain:.2f})"
          + (f"; its mirror image on the water stays painted, {meta['mirror_mean']:.2f} of the water's color" if spec.get("reflect") else ""))
    return Image.fromarray((_to_srgb(np.clip(lin2, 0, 1)) * 255).round().astype(np.uint8))
