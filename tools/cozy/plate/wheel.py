"""A painted waterwheel, taken apart so it can turn (Truman 2026-11-08: the mill's waterwheel turning the whole video;
src/library/wheel.js draws it, tools/wheel_layer.py runs this).

A spinning region of the plate (plate.js `spin`) turns the picture in a flat circle: right for a windmill's sails seen
face on, wrong for a waterwheel seen at an angle. The wall seen between its spokes would turn with them, and the band
of paddles on its far side would swing round the hub. So the wheel is modeled as the 3D thing it is, from the painting:

  the front face   the rim's ellipse fitted to its painted ink edge (fit_rim), the hub where the painted spokes meet
                   (it is off the ellipse's center: perspective), and the projective map that takes a unit disk to that
                   ellipse with its center at the hub (a Lorentz boost of the disk, homography()); the face turns in
                   the disk's own angle, so it turns the way a wheel in perspective does
  the back face    the same face, moved by the wheel's depth `d` (fit_depth: the back rim's edge), darker
  the band         the paddles between the two rims, on the side the wheel shows (the outward normal along d): a
                   point there is a rim point plus s * d, s from 0 (front) to 1 (back)

and its look comes from the painting itself, in three small textures that repeat as the wheel turns:
  rim.png      the front rim's ring over half a turn of its visible upper arc (rho across, angle along), seamless
  spoke.png    one painted spoke, straightened (across, along): every spoke of the turning wheel is this one
  band.png     one paddle period of the band, folded (median) over the paddles in view, so it tiles
The hub cap, the trestle that holds the axle and the water stay painted on the plate in front of it (occ.png, SAM),
and the wall behind it is repainted without the wheel (plate_clean, the clean.json item this writes).
"""
import json

import cv2
import numpy as np

LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def ellipse_M(a, b, angle):
    """2x2: a unit-circle point (cos t, sin t), local y up, to its offset from the ellipse's center in image px (y down)."""
    ca, sa = np.cos(angle), np.sin(angle)
    return np.array([[a * ca, -b * sa], [a * sa, b * ca]]) @ np.array([[1.0, 0.0], [0.0, -1.0]])


def homography(geo):
    """3x3 K: the unit disk (local, the wheel's own frame) to the ellipse's normalized coordinates, its center at the hub.
    A projective map that keeps the unit circle (a boost in the disk's Klein model), so the rim stays on the ellipse."""
    hn = np.asarray(geo["hn"], float)
    r, psi = float(np.hypot(*hn)), float(np.arctan2(hn[1], hn[0]))
    eta = np.arctanh(min(r, 0.95))

    def R(t):
        return np.array([[np.cos(t), -np.sin(t), 0.0], [np.sin(t), np.cos(t), 0.0], [0.0, 0.0, 1.0]])

    B = np.array([[np.cosh(eta), 0.0, np.sinh(eta)], [0.0, 1.0, 0.0], [np.sinh(eta), 0.0, np.cosh(eta)]])
    return R(psi) @ B @ R(-psi)


def to_img(geo, rho, th, shift=(0.0, 0.0)):
    """Image px (x, y) of local polar points (arrays of the same shape) on the front face (+ shift: the back face)."""
    M, K = ellipse_M(*geo["rim"][2:]), homography(geo)
    loc = np.stack([rho * np.cos(th), rho * np.sin(th), np.ones_like(th)], 0).reshape(3, -1)
    xn = K @ loc
    xn = xn[:2] / xn[2]
    p = M @ xn
    sh = np.asarray(shift, float)
    return (p[0] + geo["rim"][0] + sh[0]).reshape(np.shape(rho)), (p[1] + geo["rim"][1] + sh[1]).reshape(np.shape(rho))


def _grad(lum):
    gx = cv2.GaussianBlur(cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3), (0, 0), 1.2)
    gy = cv2.GaussianBlur(cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3), (0, 0), 1.2)
    return gx, gy


def _edge(gx, gy, rim, th, shift=(0.0, 0.0)):
    """Mean fall of brightness outward across the ellipse at angles th (a light rim against a darker background)."""
    cx, cy, a, b, al = rim
    M = ellipse_M(a, b, al)
    u = np.stack([np.cos(th), np.sin(th)], 0)
    pts = M @ u
    x, y = (cx + shift[0] + pts[0]).astype(np.float32)[None], (cy + shift[1] + pts[1]).astype(np.float32)[None]
    n = np.linalg.inv(M).T @ u
    n = n / np.linalg.norm(n, axis=0)
    g = cv2.remap(gx, x, y, cv2.INTER_LINEAR)[0] * n[0] + cv2.remap(gy, x, y, cv2.INTER_LINEAR)[0] * n[1]
    return float(np.mean(-g))


def fit_rim(lum, init, arc=(95.0, 265.0)):
    """The front rim's ellipse [cx, cy, a, b, angle] fitted to its painted outer edge along `arc` (degrees, the side
    away from the paddle band), by coordinate search from init."""
    gx, gy = _grad(lum)
    th = np.deg2rad(np.arange(arc[0], arc[1], 1.0))
    p = np.asarray(init, float)
    steps = np.array([2.0, 2.0, 2.0, 2.0, 0.01])
    best = _edge(gx, gy, p, th)
    while steps[0] >= 0.1:
        better = False
        for k in range(5):
            for sgn in (1, -1):
                q = p.copy()
                q[k] += sgn * steps[k]
                s = _edge(gx, gy, q, th)
                if s > best:
                    best, p, better = s, q, True
        if not better:
            steps *= 0.5
    return p.tolist(), best


def fit_depth(lum, rim, init, span=(-75.0, 76.0), reach=36.0):
    """The wheel's depth d (px: the back rim is the front's ellipse moved by d) fitted to the back rim's outer edge on
    the band's side, searched within `reach` px of init."""
    gx, gy = _grad(lum)
    th = np.deg2rad(np.arange(span[0], span[1], 1.0))
    best = None
    for dx in np.arange(init[0] - reach, init[0] + reach + 0.1, 2.0):
        for dy in np.arange(init[1] - reach, init[1] + reach + 0.1, 2.0):
            s = _edge(gx, gy, rim, th, (dx, dy))
            if best is None or s > best[0]:
                best = (s, dx, dy)
    s0, dx, dy = best
    for ddx in np.arange(dx - 2, dx + 2.01, 0.5):
        for ddy in np.arange(dy - 2, dy + 2.01, 0.5):
            s = _edge(gx, gy, rim, th, (ddx, ddy))
            if s > best[0]:
                best = (s, ddx, ddy)
    return [float(best[1]), float(best[2])], best[0]


def hub_from_lines(lines):
    """The point nearest to every spoke line ([[x0, y0], [x1, y1]] each, px): where the painted spokes meet."""
    A, b = [], []
    for p0, p1 in lines:
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = (p1 - p0) / np.linalg.norm(p1 - p0)
        n = np.array([-d[1], d[0]])
        A.append(n)
        b.append(n @ p0)
    return np.linalg.lstsq(np.array(A), np.array(b), rcond=None)[0]


def local_angle(geo, p):
    """The wheel-frame angle (rad) and radius of image point p on the front face."""
    M, K = ellipse_M(*geo["rim"][2:]), homography(geo)
    xn = np.linalg.inv(M) @ (np.asarray(p, float) - geo["rim"][:2])
    loc = np.linalg.inv(K) @ np.array([xn[0], xn[1], 1.0])
    loc = loc[:2] / loc[2]
    return float(np.arctan2(loc[1], loc[0])), float(np.hypot(*loc))


def _sample(img, x, y):
    return cv2.remap(img, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def rim_texture(img, geo, start, period, rho=(0.78, 1.05), size=(512, 64), seam=0.08):
    """The front rim's ring over [start, start + period) of wheel angle (rad; a visible, unoccluded arc), as an RGBA
    strip (rows: rho from rho[0] to rho[1]; columns: angle). The last `seam` of the period crossfades into the arc just
    before `start`, so the strip tiles. Alpha: the rim between its edges (geo rim_band), soft over a pixel."""
    T, R = size
    th = start + np.linspace(0, period, T, endpoint=False)
    rr = np.linspace(rho[0], rho[1], R)
    RR, TT = np.meshgrid(rr, th, indexing="ij")
    a = _sample(img, *to_img(geo, RR, TT))
    b = _sample(img, *to_img(geo, RR, TT - period))           # the same rim one period earlier, for the seam
    w = np.clip((np.linspace(0, 1, T, endpoint=False) - (1 - seam)) / seam, 0, 1)[None, :, None]
    rgb = a * (1 - w) + b * w
    lo, hi = geo["rim_band"]
    px = (rho[1] - rho[0]) / R * 1.5
    al = np.clip((rr - lo) / px + 0.5, 0, 1) * np.clip((hi - rr) / px + 0.5, 0, 1)
    return np.dstack([rgb, np.repeat(al[:, None], T, 1)]).astype(np.float32)


def spoke_texture(img, geo, angle, center, half, t_range=(0.0, 0.86), size=(64, 256), soft=0.006):
    """One painted spoke straightened: rows along it (t, wheel radius from the hub), columns across (w, local units,
    from center - 1.6 half to center + 1.6 half). Alpha 1 across its painted width (center +- half), soft at the
    sides; its outer end runs under the rim."""
    Wn, Tn = size
    t = np.linspace(t_range[0], t_range[1], Tn)
    w = center + np.linspace(-1.6 * half, 1.6 * half, Wn)
    T, Wd = np.meshgrid(t, w, indexing="ij")
    lx = T * np.cos(angle) - Wd * np.sin(angle)
    ly = T * np.sin(angle) + Wd * np.cos(angle)
    rgb = _sample(img, *to_img(geo, np.hypot(lx, ly), np.arctan2(ly, lx)))
    al = np.clip((half - np.abs(w - center)) / soft + 0.5, 0, 1)
    return np.dstack([rgb, np.repeat(al[None, :], Tn, 0)]).astype(np.float32)


def band_unwrap(img, geo, psi_range, n_psi=900, n_s=96):
    """The band (rows: s from 0, the front rim, to 1, the back rim; columns: wheel angle psi over psi_range, rad)."""
    psi = np.linspace(psi_range[0], psi_range[1], n_psi)
    x0, y0 = to_img(geo, np.ones_like(psi), psi)
    s = np.linspace(0.0, 1.0, n_s)
    X = x0[None, :] + s[:, None] * geo["d"][0]
    Y = y0[None, :] + s[:, None] * geo["d"][1]
    return _sample(img, X, Y), psi, s


def paddle_period(band, psi, lo=np.deg2rad(8), hi=np.deg2rad(30)):
    """The paddles' spacing (rad) and the phase of one paddle's middle: the autocorrelation peak of the band's
    brightness across its middle, then the phase that puts a paddle where the folded profile is brightest."""
    prof = np.median(band[int(0.3 * len(band)):int(0.7 * len(band))] @ LUM, 0)
    prof = prof - cv2.GaussianBlur(prof[None].astype(np.float32), (0, 0), 25)[0]
    dpsi = psi[1] - psi[0]
    ac = np.correlate(prof, prof, "full")[len(prof) - 1:]
    k0, k1 = int(lo / dpsi), int(hi / dpsi)
    k = k0 + int(np.argmax(ac[k0:k1]))
    period = k * dpsi
    ph = ((psi - psi[0]) % period) / period
    bins = np.zeros(48)
    for i in range(48):
        sel = (ph * 48).astype(int) == i
        bins[i] = prof[sel].mean() if sel.any() else 0
    phase = psi[0] + (np.argmax(bins) + 0.5) / 48 * period
    return float(period), float(phase)


def band_texture(band, psi, period, phase, visible, size=(128, 96)):
    """One paddle period folded from the visible band (median over the periods in view, `visible` the columns that
    show the band, unoccluded): rows s, columns the period from one paddle's middle (phase - period / 2). Alpha from
    brightness: the paddles and the rims' edges are lit wood, the gaps between them the dark inside of the wheel."""
    Tn, Sn = size
    u = ((psi - phase + period / 2) % period) / period
    cols = np.clip((u * Tn).astype(int), 0, Tn - 1)
    rgb = np.zeros((band.shape[0], Tn, 3), np.float32)
    for c in range(Tn):
        sel = (cols == c) & visible
        if sel.any():
            rgb[:, c] = np.median(band[:, sel], axis=1)
    # columns no paddle period filled (too few in view): from their neighbors
    empty = ~np.array([((cols == c) & visible).any() for c in range(Tn)])
    if empty.any() and (~empty).any():
        idx = np.arange(Tn)
        for ch in range(3):
            for r in range(rgb.shape[0]):
                rgb[r, empty, ch] = np.interp(idx[empty], idx[~empty], rgb[r, ~empty, ch], period=Tn)
    rgb = cv2.resize(rgb, (Tn, Sn), interpolation=cv2.INTER_AREA)
    lum = rgb @ LUM
    lo, hi = np.percentile(lum, 35), np.percentile(lum, 80)
    al = np.clip((lum - lo) / max(hi - lo, 1e-4), 0, 1)
    al = cv2.GaussianBlur(al, (0, 0), 0.8)
    return np.dstack([rgb, al]).astype(np.float32)


def band_visible(geo, psi, occ):
    """Which band columns (wheel angle psi) show on the plate: the rim's outward normal points along d (the side the
    wheel turns to the camera) and the column's middle isn't under something in front (occ)."""
    M = ellipse_M(*geo["rim"][2:])
    Mi = np.linalg.inv(M)
    e = Mi @ np.asarray(geo["d"], float)
    x, y = to_img(geo, np.ones_like(psi), psi)
    xn = np.stack([x - geo["rim"][0], y - geo["rim"][1]], 0)
    q = Mi @ xn
    vis = (q * e[:, None]).sum(0) > 0.15 * np.linalg.norm(e)
    mx, my = x + 0.5 * geo["d"][0], y + 0.5 * geo["d"][1]
    H, W = occ.shape
    inside = (mx >= 0) & (mx < W) & (my >= 0) & (my < H)
    o = np.ones_like(psi, bool)
    o[inside] = occ[my[inside].astype(int), mx[inside].astype(int)] < 0.5
    return vis & o & inside


def silhouette(geo, shape, grow=1.04, band=True):
    """bool mask of everything the turning wheel may cover: the front and back faces (rho <= grow) and the band
    between them."""
    H, W = shape
    th = np.linspace(0, 2 * np.pi, 720)
    m = np.zeros((H, W), np.uint8)
    for sh in ((0.0, 0.0), tuple(geo["d"])):
        x, y = to_img(geo, np.full_like(th, grow), th, sh)
        cv2.fillPoly(m, [np.stack([x, y], 1).round().astype(np.int32)], 1)
    if band:
        x0, y0 = to_img(geo, np.full_like(th, grow), th)
        for k in range(0, 720, 3):
            p = np.array([[x0[k], y0[k]], [x0[(k + 3) % 720], y0[(k + 3) % 720]],
                          [x0[(k + 3) % 720] + geo["d"][0], y0[(k + 3) % 720] + geo["d"][1]], [x0[k] + geo["d"][0], y0[k] + geo["d"][1]]])
            cv2.fillConvexPoly(m, p.round().astype(np.int32), 1)
    return m > 0


def save_rgba(path, a):
    from PIL import Image
    Image.fromarray((np.clip(a, 0, 1) * 255).round().astype(np.uint8), "RGBA").save(path)


def write_meta(path, geo, extra):
    path.write_text(json.dumps({**geo, **extra}, indent=1), encoding="utf-8", newline="\n")
