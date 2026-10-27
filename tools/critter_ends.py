"""What critters.js does at a critter's path ends, in Python, so the checks gate sees it before a render (L144).

critters.js (hideEnds) pushes each end of a critter's path out along its last stretch until the whole creature
(every opaque sample of its sprite, posed as it walks either way) is hidden: under its occ map (occ_<track>.png,
else occ.png), behind something clearly nearer than the ground at that end (depth8.png), behind anything indoors
when it walks outdoors (lights.png G), or off the frame. It looks up to 3 body lengths out. An end it can't hide
fades in or out in plain view, and the render only prints a page warning that its log drops: the Burdock Shelter's
beetle faded in on open moss and every gate passed (2026-10-25).

cover_ok() is the other half: a cover must stand up between the creature and the camera. SAM's object just past a
path end can be a patch of the same ground (a wet stone lying flat, a dark stretch of leaf litter): the creature
then melts into the ground along the patch's outline. Such a patch lies at or beyond the end's ground in depth;
a rock, a pot or a plant the creature passes behind is at least as near. On every approved scene each cover's
median depth was within 0.004 of its end's ground or nearer; the Burdock Shelter's flat patches were 0.016 and
0.141 farther.

  python tools/critter_ends.py <scene>      each critter layer's ends: hidden or in plain sight (exit 1 if any open)
"""
import json
import math
import sys

import numpy as np
from PIL import Image

from cozy.paths import ROOT
W, H = 3840, 2160
COVER_TOL = 0.01


def _round(v):
    return math.floor(v + 0.5)          # JavaScript's Math.round


def _img(path, mode):
    return np.asarray(Image.open(path).convert(mode)) if path.exists() else None


def facing(th):
    """critters.js critterFacing: the sprite faces right; moving left-ish it is mirrored and turned by th - PI."""
    return (1, th) if math.cos(th) >= 0 else (-1, th - math.pi)


def surface_depth(dep, x, y):
    """The ground under a path vertex (4K px): the farthest depth within ~8 px, as critters.js surfD (the depth map
    is soft at an occluder's edge). dep: float HxW, nearer is larger."""
    h, w = dep.shape
    vals = []
    for dx in (-8, 0, 8):
        for dy in (-6, 2, 8):
            ix = min(w - 1, max(0, _round((x + dx) * w / W)))
            iy = min(h - 1, max(0, _round((y + dy) * h / H)))
            vals.append(float(dep[iy, ix]))
    return min(vals)


def cover_depth(mask, dep, end_xy):
    """A cover's median depth minus the ground's at a path end (end_xy in 4K px); mask: bool at any size."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return -1.0
    h, w = dep.shape
    dm = dep[np.minimum(h - 1, (ys * h / mask.shape[0]).astype(int)), np.minimum(w - 1, (xs * w / mask.shape[1]).astype(int))]
    return float(np.median(dm)) - surface_depth(dep, *end_xy)


def cover_ok(mask, dep, end_xy, tol=COVER_TOL):
    """A cover candidate stands up between the creature and the camera at a path end: its median depth is not
    farther than the ground at that end by more than tol."""
    return cover_depth(mask, dep, end_xy) >= -tol


def flat_covers(scene, layer, plate=None):
    """Pieces of a critter's occ map within 3 body lengths of a path end that lie farther than the ground there (an
    old map, or a cover added by hand): [(end, piece px, depth difference)]."""
    import cv2
    pd = ROOT / "out" / "plates" / (plate or scene)
    occ = _img(pd / f"occ_{layer.get('track', 0)}.png", "L")
    if occ is None:
        occ = _img(pd / "occ.png", "L")
    dep = _img(pd / "depth8.png", "L")
    if occ is None or dep is None:
        return []
    dep = dep.astype(np.float32) / 255
    m = occ > 127
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8))
    size = float(layer.get("size", 70))
    out = []
    for e, (ex, ey) in (("start", layer["path"][0]), ("end", layer["path"][-1])):
        x, y = ex * W, ey * H
        r = 3 * size * m.shape[1] / W
        cx, cy = x * m.shape[1] / W, y * m.shape[0] / H
        y0, y1, x0, x1 = int(max(0, cy - r)), int(cy + r) + 1, int(max(0, cx - r)), int(cx + r) + 1
        for i in sorted(set(np.unique(lab[y0:y1, x0:x1][m[y0:y1, x0:x1]])) - {0}):
            bx, by, bw, bh, area = stats[i]
            sub = np.zeros_like(m)
            sub[by:by + bh, bx:bx + bw] = lab[by:by + bh, bx:bx + bw] == i
            dd = cover_depth(sub, dep, (x, y))
            if dd < -COVER_TOL:
                out.append((e, int(area), round(dd, 3)))
    return out


def open_ends(scene, layer, plate=None, name=None):
    """The ends ('start', 'end') of a critter layer's path that critters.js can't hide. scene: the scene folder;
    plate: its plate (scene.json "plate"); name: scene.json "name" (where the sprite lives)."""
    plate = plate or scene
    pd = ROOT / "out" / "plates" / plate
    kind = layer.get("creature", "snail")
    base = ROOT / "assets" / "keyart" / (name or scene) / f"critter_{kind}"
    if base.with_suffix(".json").exists() and base.with_suffix(".png").exists():
        meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
        spr = _img(base.with_suffix(".png"), "RGBA")
    else:
        # no sprite yet (plate_features runs before new_video.py life makes it): a low oval about as tall as a
        # snail's or a beetle's is to its length (0.48, 0.55)
        meta = {"bbox": [100, 380, 924, 740], "shell_x": [262, 762], "foot_y": 740}
        yy, xx = np.mgrid[0:1024, 0:1024]
        spr = np.zeros((1024, 1024, 4), np.uint8)
        spr[..., 3] = np.where(((xx - 512) / 412.0) ** 2 + ((yy - 560) / 180.0) ** 2 <= 1, 255, 0)
    bx0, by0, bx1, by1 = meta["bbox"]
    ln = bx1 - bx0
    anchor = ((meta["shell_x"][0] + meta["shell_x"][1]) / 2, meta["foot_y"])
    body = []
    for j in range(17):
        for i in range(33):
            x, y = _round(bx0 + (bx1 - bx0) * i / 32), _round(by0 + (by1 - by0) * j / 16)
            if x < spr.shape[1] and y < spr.shape[0] and spr[y, x, 3] > 128:
                body.append((x, y))
    body = np.array(body, float).reshape(-1, 2)
    track = layer.get("track", 0)
    occ = _img(pd / f"occ_{track}.png", "RGB")
    if occ is None:
        occ = _img(pd / "occ.png", "RGB")
    dep = _img(pd / "depth8.png", "RGB")
    dep = dep[..., 0].astype(np.float32) / 255 if dep is not None else None
    lit = _img(pd / "lights.png", "RGB")
    size = float(layer.get("size", 70))
    sizes = (size, float(layer.get("sizeEnd", size)))
    P0 = [(float(x) * W, float(y) * H) for x, y in layer["path"]]

    def sample(img, ch, x, y, clamp_low):
        h, w = img.shape[:2]
        ix = np.minimum(w - 1, np.floor(x * w / W + 0.5).astype(int))
        iy = np.minimum(h - 1, np.floor(y * h / H + 0.5).astype(int))
        if clamp_low:
            ix, iy = np.maximum(ix, 0), np.maximum(iy, 0)
        return img[iy, ix, ch].astype(np.float32) / 255 if img.ndim == 3 else img[iy, ix]

    foot = [surface_depth(dep, *P0[0]) if dep is not None else 0.0, surface_depth(dep, *P0[-1]) if dep is not None else 0.0]
    if "outdoor" in layer:
        outdoor = bool(layer["outdoor"])
    elif lit is None:
        outdoor = True
    else:
        xs, ys = np.array([p[0] for p in P0]), np.array([p[1] + 2 for p in P0])
        outdoor = float(sample(lit, 1, xs, ys, True).mean()) > 0.5

    def hid(x, y, e):
        inside = (x >= 0) & (y >= 0) & (x < W) & (y < H)
        h = np.ones_like(x)
        if not inside.any():
            return h
        xi, yi = x[inside], y[inside]
        o = sample(occ, 0, xi, yi, False) if occ is not None else np.zeros_like(xi)
        if dep is not None:
            d0 = foot[e]
            d = sample(dep, None, xi, yi, True)
            near = np.clip((d - (d0 * 1.06 + 0.01)) / (d0 * 0.06 + 0.01), 0, 1)
        else:
            near = np.zeros_like(xi)
        if outdoor:
            near = np.maximum(near, 1 - (sample(lit, 1, xi, yi, True) if lit is not None else 1))
        h[inside] = np.maximum(o, near)
        return h

    def cover(x, y, th, sz, e):
        flip, ang = facing(th)
        k = sz / ln
        c, s = math.cos(ang), math.sin(ang)
        dx = (body[:, 0] - anchor[0]) * k * flip
        dy = (body[:, 1] - anchor[1]) * k
        return float(hid(x + c * dx - s * dy, y + s * dx + c * dy, e).mean()) if len(body) else 0.0

    bad = []
    for end in (0, 1):
        b, a = (P0[-1], P0[-2]) if end else (P0[0], P0[1])
        l = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        ux, uy = (b[0] - a[0]) / l, (b[1] - a[1]) / l
        th, sz = math.atan2(uy, ux), sizes[end]
        if not any(min(cover(b[0] + ux * d, b[1] + uy * d, th, sz, end), cover(b[0] + ux * d, b[1] + uy * d, th + math.pi, sz, end)) >= 0.99
                   for d in (k * 0.05 * sz for k in range(61))):
            bad.append("end" if end else "start")
    return bad


def check_scene(scene):
    """[(layer, open ends, flat covers)] for every critter layer of a scene."""
    spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    plate = spec.get("plate", scene)
    out = []
    for L in spec.get("layers", []):
        if L.get("type") == "critter" and L.get("enabled", True) is not False and len(L.get("path") or []) >= 2:
            out.append((L, open_ends(scene, L, plate, spec.get("name", scene)), flat_covers(scene, L, plate)))
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    bad = 0
    for L, ends, flat in check_scene(sys.argv[1]):
        what = f"{L.get('creature', 'snail')} (track {L.get('track', 0)})"
        print(f"{what}: " + (f"in plain sight at the path {' and '.join(ends)}" if ends else "both ends hidden")
              + (f"; covers that are flat ground: {flat}" if flat else ""))
        bad += bool(ends or flat)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
