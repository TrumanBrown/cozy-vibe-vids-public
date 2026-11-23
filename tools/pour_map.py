#!/usr/bin/env python
"""Water pouring from a spout or falling over a drop, measured for src/library/pour.js.

The Yuzu Spring's sample v2 (2026-11-12) poured frozen, a miss Truman shouldn't have had to point out: analyze_plate
traces falling water as "waterfall" polygons in the masks json, and plate.js only nudged
their brightness a few percent, with streaks scrolled at a far waterfall's pace and weighted to bluish pixels: on the
colored pencil stream, lit warm by the lantern, nothing moved. A near pour falls fast. From a spout 33 cm above the
water it reaches 2.6 m/s, about 3,300 px a second at 4K, and the whole fall takes a fifth of a second, so its surface
can't be followed by eye: what reads as pouring water is streaks rushing down the stream and changing every frame,
calmer where it leaves the lip and broken lower down, and the splash where it meets the water.

For each fall this measures, once: the stream's center and half width on every row from the lip to the foot (the
water falls down the frame monotonically, so rows parametrize it), the time the water takes to reach each row (from
the lip at the layer's v0, in meters by the camera's scale at the foot: s = integral of ds / sqrt(v0^2 + 2 g h)), its
soft mask, its own light and dark colors in the plate, where it meets the water, and how flat the splash rings lie
(the water plane seen from the camera's height). Nothing here costs anything or needs the GPU.

usage: .venv\\Scripts\\python tools\\pour_map.py <scene>
Each pour layer of the scene names its water. A dry spout (the key art draws no moving water, Truman 2026-11-12, L223):
{"type": "pour", "spout": <name>, "lip": [x, y] (where the water leaves it), "lands": [x, y] (where it meets the water),
"angle" (degrees below horizontal it leaves at, 15), "depth" (the water's depth in the tube as a share of the opening's
diameter, 0.12), "contract" (how fast the tongue pulls into a round stream, in pipe radii, 0.35), "axis" (the screen
direction toward the tube's far end; else the opening's minor axis, pointing up), "width" (m across where it leaves,
without an opening, 0.02), "mouth" (false: no opening, the water starts at the lip), "light"/"dark" (sRGB 0..1, else the
warmest light and the dark around it)}: the jet is solved from the two points, and pour.js draws all of it, with the
water running in the tube seen through its opening.
A fall painted into older key art: {"type": "pour", "fall": <index into the masks json "waterfall" polygons, hand.json's
appended>, "v0" (m/s, 0.45), "ppm" (px per meter at the foot)}: measured from its trace, and pour.js moves the paint.
The camera, for both: the layer's "horizon", "camHeight", "focal", else the scene's poolsteam layer's, else
plate_fx.horizon, 1.1 m and 2700 px.
-> out/plates/<plate>/pour/<key>.png (the soft mask over its box) and pour.json {version, falls: [{key, ...}]}
"""
import argparse
import json
import math

import numpy as np
from PIL import Image, ImageFilter

from cozy.masks import poly_mask
from cozy.paths import ROOT

W4, H4 = 3840, 2160
G = 9.81
VERSION = 4                       # 2: records keyed, dry spouts drawn whole; 3: the opening; 4: the water over the rim
DEFAULT_CAM = {"camHeight": 1.1, "focal": 2700.0}


def falls_of(plate):
    """The "waterfall" polygons of a plate: the masks json's, then hand.json's (lists are appended, as plate_prep)."""
    out = []
    for p in (ROOT / "assets" / "keyart" / f"{plate}.masks.json", ROOT / "assets" / "keyart" / f"{plate}.hand.json"):
        if p.exists():
            out += json.loads(p.read_text(encoding="utf-8")).get("waterfall") or []
    return out


def camera(spec, L):
    """horizon (0..1), camera height (m), focal (px at 4K): the pour layer's own, else the poolsteam layer's (fitted to
    the water), else plate_fx.horizon with a seated eye's height."""
    ps = next((x for x in spec.get("layers", []) if x.get("type") == "poolsteam"), {})
    hz = L.get("horizon", ps.get("horizon", (spec.get("plate_fx") or {}).get("horizon", 0.45)))
    return {"horizon": float(hz), "camHeight": float(L.get("camHeight", ps.get("camHeight", DEFAULT_CAM["camHeight"]))),
            "focal": float(L.get("focal", ps.get("focal", DEFAULT_CAM["focal"])))}


def measure(img, poly, cam, v0=0.45, ppm=None, pad=6, soft=1.0):
    """One fall. img: the plate (H x W x 3, floats 0..1, 4K); poly: its polygon (normalized x, y down). Returns (the
    fall's record, its soft mask over the record's box as uint8)."""
    H, W = img.shape[:2]
    m = poly_mask((W, H), [poly]) > 0.5
    rows = np.flatnonzero(m.any(1))
    if len(rows) < 8:
        raise SystemExit(f"pour_map: the fall polygon covers {len(rows)} rows; trace it from the lip to the water")
    y0, y1 = int(rows.min()), int(rows.max())
    ys = np.arange(y0, y1 + 1)
    cx = np.full(len(ys), np.nan)
    hw = np.full(len(ys), np.nan)
    for k, y in enumerate(ys):
        xs = np.flatnonzero(m[y])
        if len(xs):
            cx[k], hw[k] = (xs.min() + xs.max() + 1) / 2, (xs.max() + 1 - xs.min()) / 2
    ok = ~np.isnan(cx)
    cx, hw = np.interp(ys, ys[ok], cx[ok]), np.interp(ys, ys[ok], hw[ok])
    # a light smoothing: the traced edge is ragged at the pixel level, the stream isn't
    ker = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
    ker /= ker.sum()
    sm = lambda a: np.convolve(np.pad(a, 6, mode="edge"), ker, mode="valid")
    cx, hw = sm(cx), np.maximum(sm(hw), 1.5)
    # the scale at the foot: the water plane's row seen from the camera's height
    yh = cam["horizon"] * H4
    foot_px = (y1 + 1) * H4 / H
    if ppm is None:
        if foot_px <= yh + 0.02 * H4:
            raise SystemExit(f"pour_map: the fall's foot (row {foot_px:.0f}) is at or above the horizon ({yh:.0f}): give the layer `ppm`")
        z = cam["focal"] * cam["camHeight"] / (foot_px - yh)
        ppm = cam["focal"] / z
    else:
        z = cam["focal"] / ppm
    ppm = float(ppm) * H / H4                                   # px of this image per meter
    # the time the water takes to reach each row: falling from the lip at v0
    drop = (ys - y0) / ppm                                      # m below the lip
    v = np.sqrt(v0 ** 2 + 2 * G * drop)
    ds = np.sqrt(1 + np.gradient(cx) ** 2) / ppm                # m of stream per row
    tau = np.concatenate([[0.0], np.cumsum(0.5 * (ds[1:] / v[1:] + ds[:-1] / v[:-1]))])
    # the stream's own light and dark in the plate (its lit strokes, the dark between them)
    inner = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 0
    px = img[inner if inner.sum() >= 50 else m]
    lum = px @ np.array([0.2126, 0.7152, 0.0722])
    light = px[lum >= np.percentile(lum, 92)].mean(0)
    dark = px[lum <= np.percentile(lum, 20)].mean(0)
    light = np.clip(light * 1.12, 0, 1)
    # its soft mask over a padded box
    xs = np.flatnonzero(m.any(0))
    bx0, bx1 = max(0, int(xs.min()) - pad), min(W, int(xs.max()) + 1 + pad)
    by0, by1 = max(0, y0 - pad), min(H, y1 + 1 + pad)
    crop = Image.fromarray(m[by0:by1, bx0:bx1].astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(soft))
    s = W4 / W
    rec = {
        "box": [round(bx0 * s, 1), round(by0 * s, 1), round(bx1 * s, 1), round(by1 * s, 1)],
        "rows": [[round(float(y * s), 1), round(float(c * s), 2), round(float(h * s), 2), round(float(t), 5)]
                 for y, c, h, t in zip(ys, cx, hw, tau)],
        "lip": [round(float(cx[0] * s), 1), round(float(y0 * s), 1)],
        "foot": [round(float(cx[-1] * s), 1), round(float((y1 + 1) * s), 1)],
        "tau": round(float(tau[-1]), 4), "fall_m": round(float(drop[-1]), 3), "v0": v0, "v_foot": round(float(v[-1]), 3),
        "ppm": round(float(ppm * s), 1), "z": round(float(z), 3),
        # a ring on the water plane is an ellipse this much flatter than wide
        "aspect": round(float(cam["camHeight"] / math.hypot(cam["camHeight"], z)), 4),
        "light": [round(float(c), 4) for c in light], "dark": [round(float(c), 4) for c in dark],
    }
    return rec, np.asarray(crop)


def mouth(img, lip, reach=170.0):
    """The opening a dry spout pours from, seen in the plate (Truman 2026-11-12: the pour looked like it spawned at the
    tube's tip; the water has to be seen running in the tube first): the dark blob ringed by the brighter rim just above
    the lip, enclosed (it never reaches the edge of the window around the lip, where the night behind the spout would
    leak in). The largest enclosed, compact one over a range of darkness thresholds, fitted with an ellipse. Returns
    {"c": center, "A": half axis, "B": the other half axis (px at 4K: a point of its edge is c + A cos t + B sin t),
    "low": its lowest point, "dark": its median luminance} or None."""
    import cv2
    H, W = img.shape[:2]
    s = W4 / W
    lx, ly = lip[0] / s, lip[1] / s
    r = reach / s
    x0, x1, y0, y1 = int(max(0, lx - r)), int(min(W, lx + r)), int(max(0, ly - 1.4 * r)), int(min(H, ly + 0.3 * r))
    lum = cv2.GaussianBlur(img[y0:y1, x0:x1] @ np.array([0.2126, 0.7152, 0.0722], np.float32), (0, 0), 2.0 / s)
    best = None
    for thr in np.arange(0.06, 0.2, 0.01):
        n, lab, st, cen = cv2.connectedComponentsWithStats((lum < thr).astype(np.uint8))
        for i in range(1, n):
            bx, by, bw, bh, area = st[i]
            if bx == 0 or by == 0 or bx + bw >= lum.shape[1] or by + bh >= lum.shape[0] or area < 300 / s ** 2:
                continue                                         # the night behind the spout, or a speck
            comp = (lab == i).astype(np.uint8)
            cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            hull = cv2.convexHull(max(cs, key=cv2.contourArea))
            if area < 0.8 * cv2.contourArea(hull) or len(hull) < 5:
                continue                                         # not a round opening
            cxy = cen[i]
            if math.hypot(cxy[0] - (lx - x0), cxy[1] - (ly - y0)) > r or cxy[1] > ly - y0:
                continue                                         # not above the lip
            if best is None or area > best[0]:
                best = (area, hull, float(np.median(lum[comp > 0])))
    if best is None:
        return None
    (cx, cy), (w, h), ang = cv2.fitEllipse(best[1])
    th = math.radians(ang)
    A = np.array([math.cos(th), math.sin(th)]) * w / 2 * s
    B = np.array([-math.sin(th), math.cos(th)]) * h / 2 * s
    c = np.array([cx + x0, cy + y0]) * s
    t = np.linspace(0, 2 * math.pi, 720, endpoint=False)
    pts = c[None] + np.cos(t)[:, None] * A[None] + np.sin(t)[:, None] * B[None]
    low = pts[int(np.argmax(pts[:, 1]))]
    rnd = lambda v: [round(float(q), 1) for q in v]  # noqa: E731
    return {"c": rnd(c), "A": rnd(A), "B": rnd(B), "low": rnd(low), "dark": round(best[2], 4)}


def jet(img, lip, lands, cam, angle=15.0, width=None, pad=6, soft=1.0, colors=None, find_mouth=True, fill=0.45,
        depth=0.12, contract=0.35, axis=None):
    """A pour from a dry spout (key art draws no moving water, Truman 2026-11-12; L223): the water leaves at `angle` degrees
    below horizontal, toward `lands`, and falls under gravity to where it meets the water there. lip and lands are px at
    4K; the scale is the water plane's at the landing row (the water there is as far away as the spout). The launch speed
    comes from the two points: dx = v cos(a) t, dy = v sin(a) t + g t^2 / 2.
    With the spout's opening found (mouth(), near the given lip): the water runs along the bottom of the tube, its level
    surface `depth` of the opening's diameter up (0.12), so at the end it pours over the whole stretch of rim under that
    surface, as a free overfall from a part-full pipe does: at the brink the water spans the chord across the opening at
    its level (about two thirds of the opening for that depth: the chord grows fast with depth). That tongue falls in
    front of the rim and pulls together into a round stream within about a pipe radius (the drop it takes to close by
    1/e is `contract` of the radius, 0.35), then thins as it speeds up: its cross-section is the flow over its speed, the
    flow being the water's section in the tube times its speed at the brink. The stream's center leaves from the water
    section's centroid. Started at the opening's lowest point and as wide as a stream, it looked like it came out of one
    spot on the rim (Truman 2026-11-15). Without an opening the ribbon is `width` m across where it leaves (0.02) and
    thins as v^-1/2. A row of the frame cuts the stream across, never lengthwise: it falls mostly toward the camera.
    Returns the record measure() does, "painted": False (pour.js draws all of it), "mouth" (the opening and the water's
    surface in it, or None), and the soft mask."""
    H, W = img.shape[:2]
    s = W4 / W
    (x0, y0), (x1, y1) = lip, lands
    m = mouth(img, lip) if find_mouth else None
    if m and math.hypot(m["low"][0] - x0, m["low"][1] - y0) > 40:
        m = None
    yh = cam["horizon"] * H4
    if y1 <= yh + 0.02 * H4:
        raise SystemExit(f"pour_map: the spout's water lands at row {y1:.0f}, at or above the horizon ({yh:.0f}): check `lands`")
    z = cam["focal"] * cam["camHeight"] / (y1 - yh)
    ppm = cam["focal"] / z
    ytop, area = y0, None
    if m:
        A, B, c = (np.array(m[k], float) for k in ("A", "B", "c"))
        Mx = np.stack([A, B], 1)
        p = np.linalg.solve(Mx, np.array(m["low"]) - c)
        tl = math.atan2(p[1], p[0])
        D = math.cos(tl) * A + math.sin(tl) * B             # the center to the lowest point (px)
        E = -math.sin(tl) * A + math.cos(tl) * B            # along the rim at its lowest point: level on screen
        sc = 1 - 2 * depth                                  # the water's surface across the opening (unit disk)
        hc = math.sqrt(max(0.0, 1 - sc * sc))
        th = 2 * math.acos(sc)                              # the angle the water's section spans
        sg = 4 * math.sin(th / 2) ** 3 / (3 * (th - math.sin(th)))   # its centroid, from the center
        top, g0 = c + sc * D, c + sg * D
        R = max(float(np.hypot(*A)), float(np.hypot(*B))) / ppm      # a circle seen at an angle keeps its major axis
        area = R * R * (th - math.sin(th)) / 2              # the water's section in the tube (m^2)
        Wc = hc * float(np.hypot(*E))                       # half the chord at the water's surface (px)
        if axis is None:
            # toward the tube's far end: a circle's normal projects along the ellipse's minor axis; up, into the tube
            mn = A if np.hypot(*A) < np.hypot(*B) else B
            ax = mn / np.hypot(*mn)
            ax = -ax if ax[1] > 0 else ax
        else:
            ax = np.array(axis, float) / max(1e-9, float(np.hypot(*axis)))
        x0, y0, ytop = float(g0[0]), float(g0[1]), float(top[1])
        m.update(d=[round(math.cos(tl), 5), round(math.sin(tl), 5)], across=round(float(np.hypot(*E)), 2),
                 inv=[round(float(v), 6) for v in np.linalg.inv(Mx).ravel()], depth=depth, sc=round(sc, 4),
                 top=[round(float(top[0]), 1), round(float(top[1]), 1)], half=round(Wc, 2), radius=round(R, 4),
                 axis=[round(float(ax[0]), 4), round(float(ax[1]), 4)])
    if y1 <= y0 + 8:
        raise SystemExit("pour_map: `lands` must be below `lip`")
    dx, dy = abs(x1 - x0) / ppm, (y1 - y0) / ppm
    sgn = 1.0 if x1 >= x0 else -1.0
    a = math.radians(angle)
    if dx < 1e-3:
        a, v0 = math.pi / 2, 0.15                           # straight down
    else:
        if dy <= dx * math.tan(a) + 1e-3:
            a = math.atan(0.8 * dy / dx)                    # too steep a spout for where it lands: aim lower
        v0 = math.sqrt(G * dx ** 2 / (2 * math.cos(a) ** 2 * (dy - dx * math.tan(a))))
    vx, vy0 = v0 * math.cos(a), v0 * math.sin(a)
    ys = np.arange(int(round(ytop)), int(round(y1)) + 1)
    h = np.maximum(ys - y0, 0) / ppm
    t = (-vy0 + np.sqrt(vy0 ** 2 + 2 * G * h)) / G
    t = np.where(ys < y0, (ys - y0) / ppm / max(v0, 0.1), t)          # the brink, above the centroid: just before
    cx = x0 + sgn * vx * np.maximum(t, 0) * ppm
    if m:
        f = np.clip((ys - ytop) / max(y0 - ytop, 1e-6), 0, 1)
        cx = np.where(ys < y0, m["top"][0] + (x0 - m["top"][0]) * f, cx)
    v = np.sqrt(vx ** 2 + (vy0 + G * np.maximum(t, 0)) ** 2)
    if m:
        Q = area * v0                                       # the flow (m^3/s)
        rope = np.sqrt(Q / (math.pi * np.maximum(v, v0))) * ppm         # the stream's radius once round (px)
        width = 2 * float(rope[0]) / ppm
        drop = (ys - ytop) / ppm
        hw = rope + np.maximum(m["half"] - rope[0], 0) * np.exp(-drop / (contract * m["radius"]))
        m.update(flow_lpm=round(Q * 60000, 2), contract=contract)
    else:
        width = width or 0.02
        hw = 0.5 * width * np.sqrt(v0 / np.maximum(v, 1e-6)) * ppm  # px: half the ribbon's width, level across the frame
    # its soft mask, row by row (pour.js draws the outline itself; the mask bounds the quad and feeds the checks)
    bx0, bx1 = int((cx - hw).min()) - pad, int((cx + hw).max()) + 1 + pad
    by0, by1 = ys[0] - pad, ys[-1] + 1 + pad
    mask = np.zeros((by1 - by0, bx1 - bx0), np.float32)
    xx = np.arange(bx0, bx1) + 0.5
    for k, y in enumerate(ys):
        mask[y - by0] = np.clip((hw[k] - np.abs(xx - cx[k])) / soft + 0.5, 0, 1)
    # its colors: the warmest light near it in the plate (the lantern's on the spout and the rocks), as cream pencil, and
    # the dark it falls in front of
    if colors is None:
        r = 60
        win = img[max(0, int((by0 - r) / s)):int((by1 + r) / s), max(0, int((bx0 - r) / s)):int((bx1 + r) / s)].reshape(-1, 3)
        lum = win @ np.array([0.2126, 0.7152, 0.0722])
        light = win[lum >= np.percentile(lum, 97)].mean(0)
        # half the warmest light there, brightened, half cream: the Yuzu Spring's painted stream measured [0.92, 0.81, 0.69]
        # where the plate's warmest light near the spout was [0.76, 0.65, 0.54]
        light = np.clip(0.5 * light * 1.3 + 0.5 * np.array([0.94, 0.85, 0.72]), 0, 1)
        dark = win[lum <= np.percentile(lum, 25)].mean(0)
    else:
        light, dark = (np.array(c, float) for c in colors)
    rec = {
        "box": [float(bx0), float(by0), float(bx1), float(by1)],
        "rows": [[float(y), round(float(c), 2), round(float(w), 2), round(float(tt), 5)] for y, c, w, tt in zip(ys, cx, hw, t)],
        "lip": [round(float(x0), 1), round(float(y0), 1)], "foot": [round(float(cx[-1]), 1), round(float(y1), 1)],
        "tau": round(float(t[-1]), 4), "fall_m": round(float(dy), 3), "v0": round(v0, 3), "angle": round(math.degrees(a), 1),
        "v_foot": round(float(v[-1]), 3), "ppm": round(float(ppm), 1), "z": round(float(z), 3),
        "aspect": round(float(cam["camHeight"] / math.hypot(cam["camHeight"], z)), 4),
        "light": [round(float(c), 4) for c in light], "dark": [round(float(c), 4) for c in dark], "painted": False,
        "width": round(float(width), 4), "mouth": m,
    }
    return rec, (mask * 255 + 0.5).astype(np.uint8)


def run(scene):
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    plate = sc.get("plate", scene)
    pours = [L for L in sc.get("layers", []) if L.get("type") == "pour" and L.get("enabled", True) is not False]
    if not pours:
        raise SystemExit(f"pour_map: scenes/{scene}/scene.json has no pour layer")
    polys = falls_of(plate)
    pdir = ROOT / "out" / "plates" / plate
    img = np.asarray(Image.open(pdir / "plate.png").convert("RGB"), np.float32) / 255
    out = pdir / "pour"
    out.mkdir(parents=True, exist_ok=True)
    falls = []
    for L in pours:
        if L.get("lip"):
            # a dry spout: the code pours all of it
            key = f"spout:{L.get('spout', 'spout')}"
            lip = [L["lip"][0] * W4, L["lip"][1] * H4]
            lands = [L["lands"][0] * W4, L["lands"][1] * H4]
            rec, mask = jet(img, lip, lands, camera(sc, L), angle=float(L.get("angle", 15)),
                            width=float(L["width"]) if L.get("width") else None,
                            colors=(L["light"], L["dark"]) if L.get("light") and L.get("dark") else None,
                            find_mouth=L.get("mouth", True) is not False, depth=float(L.get("depth", 0.12)),
                            contract=float(L.get("contract", 0.35)), axis=L.get("axis"))
            name = f"{key.replace(':', '_')}.png"
        else:
            i = int(L.get("fall", 0))
            if i >= len(polys):
                raise SystemExit(f"pour_map: fall {i}, but {plate} has {len(polys)} waterfall polygon(s) (masks json \"waterfall\")")
            key, name = f"fall:{i}", f"fall_{i}.png"
            rec, mask = measure(img, polys[i], camera(sc, L), v0=float(L.get("v0", 0.45)), ppm=L.get("ppm"))
            rec["fall"] = i
        Image.fromarray(mask, "L").save(out / name)
        falls.append({"key": key, "mask": name, **rec})
        print(f"pour {key}: lip {rec['lip']}, foot {rec['foot']}: {rec['fall_m'] * 100:.0f} cm at {rec['z']:.2f} m "
              f"({rec['ppm']:.0f} px/m), {rec['tau'] * 1000:.0f} ms from the lip, {rec['v_foot']:.2f} m/s at the foot"
              + (f", launched at {rec['v0']:.2f} m/s, {rec['angle']:.0f} deg down, {rec['width'] * 100:.1f} cm wide once round" if rec.get("painted") is False else "")
              + (f"; from the tube's opening (center {rec['mouth']['c']}, {rec['mouth']['across'] * 2:.0f} px across): the water "
                 f"{rec['mouth']['depth']:.0%} of it deep pours over {rec['mouth']['half'] * 2:.0f} px of rim, {rec['mouth']['flow_lpm']:.1f} L/min"
                 if rec.get("mouth") else ("; no opening found: it starts at the lip" if rec.get("painted") is False else "")))
    (out / "pour.json").write_text(json.dumps({"version": VERSION, "falls": falls}, indent=1), encoding="utf-8")
    print(f"  -> {out / 'pour.json'}")
    return falls


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scene")
    run(ap.parse_args().scene)


if __name__ == "__main__":
    main()
