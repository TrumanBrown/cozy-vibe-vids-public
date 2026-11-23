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

  python tools/critter_ends.py <scene>      each critter layer's ends (hidden or in plain sight) and where it is cut off on
                                            its way (exit 1 if any)
"""
import json
import math
import sys
import types

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
    old map, or a cover added by hand): [(end, piece px, depth difference)]. Water the layer names in `occ` is no flat
    ground for a creature that lives in it: it goes into the water there (the tide pool's hermit crab)."""
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
    wet = water_covers(layer, pd, m.shape) if lives_in_water(layer.get("creature", "")) else None
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
            if wet is not None and float(wet[sub].mean()) > 0.5:
                continue
            dd = cover_depth(sub, dep, (x, y))
            if dd < -COVER_TOL:
                out.append((e, int(area), round(dd, 3)))
    return out


# creatures that go into water: a water region may hide them at a path end (they walk in or climb out)
WATER_LIFE = ("crab", "frog", "toad", "newt", "salamander", "turtle", "periwinkle", "limpet", "shrimp", "duck")


def lives_in_water(creature):
    return any(w in str(creature).lower() for w in WATER_LIFE)


def water_covers(layer, pd, shape):
    """The water regions a critter layer names in `occ` (regions.json kind water), as a bool mask of the given shape;
    None without any."""
    import cv2
    names = [n for n in layer.get("occ") or [] if isinstance(n, str)]
    rj = pd / "regions.json"
    if not names or not rj.exists() or not (pd / "regions.png").exists():
        return None
    regs = json.loads(rj.read_text(encoding="utf-8"))
    regs = regs if isinstance(regs, list) else regs.get("regions", [])
    ids = [g["id"] for g in regs if g.get("name") in names and g.get("kind") == "water"]
    if not ids:
        return None
    rid = np.asarray(Image.open(pd / "regions.png"))[..., 0]
    wm = np.isin(rid, ids).astype(np.uint8)
    return cv2.resize(wm, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) > 0


def dry_water_covers(scene, layer, plate=None):
    """The water regions a critter layer names in `occ` though its creature doesn't live in water (a beetle walking
    into a pond): their names."""
    if lives_in_water(layer.get("creature", "")):
        return []
    pd = ROOT / "out" / "plates" / (plate or scene)
    rj = pd / "regions.json"
    if not rj.exists():
        return []
    regs = json.loads(rj.read_text(encoding="utf-8"))
    regs = regs if isinstance(regs, list) else regs.get("regions", [])
    water = {g.get("name") for g in regs if g.get("kind") == "water"}
    return [n for n in layer.get("occ") or [] if n in water]


def dry_mask(pd, shape):
    """Characters and what they hold, cut out of the outdoors so no weather falls on them (plate_prep's character rule:
    regions.json `dry_why`), grown 5 px at 4K (the cutout's own 4 and a little), as a 0..1 float of the given shape.
    They are no indoors: an outdoor creature walking in front of one was clipped by its cutout (the tide pool's hermit
    crab at the decorator crab's feet, 2026-11-05). Regions marked dry by hand (a noren across the opening, a sign) stand
    in front of the view and are left out. Zeros without any."""
    import cv2
    rj, rp = pd / "regions.json", pd / "regions.png"
    if not rj.exists() or not rp.exists():
        return np.zeros(shape, np.float32)
    regs = json.loads(rj.read_text(encoding="utf-8"))
    regs = regs if isinstance(regs, list) else regs.get("regions", [])
    ids = [g["id"] for g in regs if g.get("dry") and g.get("dry_why")]
    if not ids:
        return np.zeros(shape, np.float32)
    rid = np.asarray(Image.open(rp))
    rid = rid[..., 0] if rid.ndim == 3 else rid
    k = 2 * max(1, round(5 * rid.shape[1] / W)) + 1
    m = cv2.dilate(np.isin(rid, ids).astype(np.uint8), np.ones((k, k), np.uint8))
    return cv2.resize(m.astype(np.float32), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)


def _critter(scene, layer, plate=None, name=None):
    """What critters.js knows about a critter when it loads: its sprite's opaque samples about its foot point, its
    path, and hid(x, y, d0): how hidden each sprite point is (0..1) for a surface at depth d0, under its occ map,
    behind anything clearly nearer, or, walking outdoors, behind anything indoors (a character's dry cutout is no
    indoors)."""
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
    dry = dry_mask(pd, lit.shape[:2]) if lit is not None else None
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

    if "outdoor" in layer:
        outdoor = bool(layer["outdoor"])
    elif lit is None:
        outdoor = True
    else:
        xs, ys = np.array([p[0] for p in P0]), np.array([p[1] + 2 for p in P0])
        outdoor = float(sample(lit, 1, xs, ys, True).mean()) > 0.5

    def hid(x, y, d0):
        inside = (x >= 0) & (y >= 0) & (x < W) & (y < H)
        h = np.ones_like(x)
        if not inside.any():
            return h
        xi, yi = x[inside], y[inside]
        o = sample(occ, 0, xi, yi, False) if occ is not None else np.zeros_like(xi)
        if dep is not None:
            d = sample(dep, None, xi, yi, True)
            near = np.clip((d - (d0 * 1.06 + 0.01)) / (d0 * 0.06 + 0.01), 0, 1)
        else:
            near = np.zeros_like(xi)
        if outdoor:
            out = np.maximum(sample(lit, 1, xi, yi, True), sample(dry, None, xi, yi, True)) if lit is not None else 1
            near = np.maximum(near, 1 - out)
        h[inside] = np.maximum(o, near)
        return h

    # a walker leans at most its gait's tilt along its way (critters.js GAITS: a crab 12 degrees, others 15)
    tilt = math.radians(12 if "crab" in str(kind) else 15) if layer.get("gait") else None
    return types.SimpleNamespace(body=body, anchor=anchor, ln=ln, sizes=sizes, P0=P0, dep=dep, hid=hid, tilt=tilt)


def _cover(c, x, y, th, sz, d0):
    """The share of the creature hidden posed at (x, y) heading th (rad), sz px long, on a surface at depth d0."""
    flip, ang = facing(th)
    if c.tilt is not None:
        ang = min(c.tilt, max(-c.tilt, ang))
    k = sz / c.ln
    co, si = math.cos(ang), math.sin(ang)
    dx = (c.body[:, 0] - c.anchor[0]) * k * flip
    dy = (c.body[:, 1] - c.anchor[1]) * k
    return float(c.hid(x + co * dx - si * dy, y + si * dx + co * dy, d0).mean()) if len(c.body) else 0.0


def open_ends(scene, layer, plate=None, name=None):
    """The ends ('start', 'end') of a critter layer's path that critters.js can't hide. scene: the scene folder;
    plate: its plate (scene.json "plate"); name: scene.json "name" (where the sprite lives)."""
    c = _critter(scene, layer, plate, name)
    P0 = c.P0
    foot = [surface_depth(c.dep, *P0[0]) if c.dep is not None else 0.0, surface_depth(c.dep, *P0[-1]) if c.dep is not None else 0.0]
    bad = []
    for end in (0, 1):
        b, a = (P0[-1], P0[-2]) if end else (P0[0], P0[1])
        l = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        ux, uy = (b[0] - a[0]) / l, (b[1] - a[1]) / l
        th, sz = math.atan2(uy, ux), c.sizes[end]
        if not any(min(_cover(c, b[0] + ux * d, b[1] + uy * d, th, sz, foot[end]), _cover(c, b[0] + ux * d, b[1] + uy * d, th + math.pi, sz, foot[end])) >= 0.99
                   for d in (k * 0.05 * sz for k in range(61))):
            bad.append("end" if end else "start")
    return bad


def clipped_along(scene, layer, plate=None, name=None, lo=0.04):
    """Where critters.js would cut part of the creature away on its way: [(share of the way, x, y, hidden share)]. Its
    hidden share may fall as it comes out (from behind a cover, past the frame's edge) and rise as it goes, but never
    rise and fall again in between: a bump of more than lo, either way it faces, is a clip. A creature passing wholly
    behind a pot is fine; the tide pool's hermit crab lost a fifth of itself at the decorator crab's feet (2026-11-05)."""
    c = _critter(scene, layer, plate, name)
    P0 = c.P0
    vd = [surface_depth(c.dep, x, y) if c.dep is not None else 0.0 for x, y in P0]
    cum = [0.0]
    for a, b in zip(P0, P0[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    pts = []
    d = 0.0
    while d <= total:
        k = max(1, next((i for i, v in enumerate(cum) if v >= d), len(cum) - 1))
        f = (d - cum[k - 1]) / max(1e-6, cum[k] - cum[k - 1])
        (ax, ay), (bx, by) = P0[k - 1], P0[k]
        x, y = ax + (bx - ax) * f, ay + (by - ay) * f
        d0 = vd[k - 1] + (vd[k] - vd[k - 1]) * f
        th = math.atan2(by - ay, bx - ax)
        sz = c.sizes[0] + (c.sizes[1] - c.sizes[0]) * d / max(total, 1e-6)
        pts.append((d / max(total, 1e-6), x, y, max(_cover(c, x, y, th, sz, d0), _cover(c, x, y, th + math.pi, sz, d0))))
        d += 0.25 * c.sizes[0]
    h = [q[3] for q in pts]
    out = []
    for i in bumps(h, lo):
        u, x, y, hi = pts[i]
        out.append((round(u, 3), round(x), round(y), round(hi, 2)))
    return out


def bumps(h, lo=0.04):
    """Indexes where a hidden-share profile rises and falls again by more than lo: what it hides there it shows again,
    on both sides (coming out and going away only fall, then rise)."""
    return [i for i in range(1, len(h) - 1) if h[i] - max(min(h[:i]), min(h[i + 1:])) > lo]


def comes_back(scene, layer, plate=None, name=None, lo=0.1):
    """Where the stretch critters.js adds past a path end shows the creature again: [(end, x, y, hidden share)].
    hideEnds pushes each end out along the path until the whole creature is covered, facing either way. A cover that
    hides most of it but not all lets the push run on past it: the Yuzu Spring's mouse went behind the round rock with its
    ears over the rock's top, walked on through the gap in plain sight and went out of sight behind the stoat
    (2026-11-12). Its hidden share must only rise from a body length before the end to where it is wholly covered."""
    c = _critter(scene, layer, plate, name)
    P0 = c.P0
    out = []
    for end in (0, 1):
        b, a = (P0[-1], P0[-2]) if end else (P0[0], P0[1])
        l = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        ux, uy = (b[0] - a[0]) / l, (b[1] - a[1]) / l
        th, sz = math.atan2(uy, ux), c.sizes[end]
        d0 = surface_depth(c.dep, *b) if c.dep is not None else 0.0
        got = next((d for d in (k * 0.05 * sz for k in range(61))
                    if min(_cover(c, b[0] + ux * d, b[1] + uy * d, th, sz, d0), _cover(c, b[0] + ux * d, b[1] + uy * d, th + math.pi, sz, d0)) >= 0.99), None)
        if got is None:
            continue                       # an open end: open_ends says so
        for face in (th, th + math.pi):
            prof, d = [], -sz
            while d <= got + 0.25 * sz:
                x, y = b[0] + ux * d, b[1] + uy * d
                prof.append((x, y, _cover(c, x, y, face, sz, d0)))
                d += 0.05 * sz
            hs = [q[2] for q in prof]
            hit = bumps(hs, lo)
            if hit:
                p = max(hit, key=lambda i: hs[i])                              # the cover it went behind
                j = p + min(range(len(hs) - p), key=lambda k: hs[p + k])       # where it shows most again past it
                x, y, h = prof[j]
                out.append(("end" if end else "start", round(x), round(y), round(h, 2)))
                break
    return out


def check_scene(scene):
    """[(layer, open ends, flat covers, clipped spots on its way, spots past an end where it shows again)] for every
    critter layer of a scene."""
    spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    plate = spec.get("plate", scene)
    out = []
    for L in spec.get("layers", []):
        if L.get("type") == "critter" and L.get("enabled", True) is not False and len(L.get("path") or []) >= 2:
            out.append((L, open_ends(scene, L, plate, spec.get("name", scene)), flat_covers(scene, L, plate),
                        clipped_along(scene, L, plate, spec.get("name", scene)), comes_back(scene, L, plate, spec.get("name", scene))))
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    bad = 0
    for L, ends, flat, clip, back in check_scene(sys.argv[1]):
        what = f"{L.get('creature', 'snail')} (track {L.get('track', 0)})"
        print(f"{what}: " + (f"in plain sight at the path {' and '.join(ends)}" if ends else "both ends hidden")
              + (f"; covers that are flat ground: {flat}" if flat else "")
              + (f"; partly cut off on its way at {clip[:6]}" if clip else "")
              + (f"; shows again past its {', '.join(f'{e} at ({x}, {y}) {h:.0%} hidden' for e, x, y, h in back)}" if back else ""))
        bad += bool(ends or flat or clip or back)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
