"""What the plate offers beyond the analysis draft, found and placed automatically (autopilot, user 2026-10-21).

The ramen alley's best details were placed by hand over several rounds (lessons L15, L21, L22, L26, L28, L34):
birds sitting on the power lines, a moth at the lamp, smoke from a stove pipe, petals off the cherry tree, tea in
the empty cup, snails on the street as well as on the ledge, ants on the counter. This finds and places the same
kinds of details on any plate, the way they were traced by hand, so a new scene has them on its first render:

  1. look    the vision model lists candidates on the gridded plate, with the analysis's regions and the brief
  2. zoom    each candidate again on a crop with a fine grid in plate coordinates (a vision model misplaces small
             things by a few percent of the frame; on a crop the error shrinks with the zoom)
  3. snap    the plate refines what it can measure: a wire's dark line or a crossarm's top edge, a lamp's lit
             glass, what a critter's path ends hide behind (SAM: analyze_plate.critter_cover)
  4. check   everything drawn on the plate and judged again by the model; whatever sits wrong is dropped

Writes out/plates/<scene>/features.json (candidates, placements, verdicts) and features_preview.jpg, and (unless
--dry) the layers and events into scenes/<scene>/scene.json for kinds the scene does not have yet (--force
replaces them), and what the critters hide behind into the masks json and occ.png. Rates: config/defaults.json.

  .venv/Scripts/python tools/plate_features.py <scene> [--only perch,moth,smoke,petals,liquid,fish,critter,ant]
                                                      [--dry] [--force] [--reuse]

About $0.3 of vision calls. Look at features_preview.jpg after a run.
"""
import argparse
import json
import math
import os
import sys

from cozy.paths import ROOT, config, creature_id, load_scene, save_scene
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from azure_ai import vision_json  # noqa: E402
from cozy.masks import render_occluders  # noqa: E402
from cozy.segment import Segmenter, contours, critter_cover, critter_size, grid_image  # noqa: E402

W4, H4 = 3840, 2160
KINDS = ["perch", "moth", "smoke", "petals", "liquid", "fish", "critter", "ant"]
DEFAULTS = config("defaults")
FOCAL = 2700.0              # px at 4K: the plate camera shared by rain, petals, boats and the ant
BIRD_M = 0.18               # a sparrow or bulbul, beak to tail (the ramen alley's perched birds: 18 px at ~27 m)
ANT_M, ANT_READ = 0.007, 5.5  # an ant's length, and how much bigger than life it is drawn (the ramen ant: 30 px)
CAM_H = 1.1                 # m: a seated eye above a surface below eye level
# a critter's walking pace in body lengths a second (critters.js eases in and out of two pauses on top); keyed by
# creature_id(), like cozy.segment's CRITTER_M and critter.py's LOOKS (tests/test_creatures.py holds them together)
PACE = {"snail": 0.04, "slug": 0.04, "ladybug": 0.3, "beetle": 0.33, "shieldbug": 0.3, "gecko": 0.3,
        "frog": 0.15, "mouse": 0.5}
# the creatures the feature look offers the vision model, as it reads them
OFFERED = ("snail", "ladybug", "beetle", "shield bug", "gecko", "frog", "mouse")
COORDS = ("The image is a zoomed crop of the key art with a labeled grid. The labels are coordinates in the FULL image "
          "(fractions of its width x and height y, y from the top). Answer in those coordinates, read from the grid as "
          "exactly as you can (to 0.001).")


def font(px):
    try:
        return ImageFont.truetype("arial.ttf", px)
    except OSError:
        return ImageFont.load_default()


def nice_step(span, n=10):
    for s in (0.002, 0.0025, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1):
        if span / s <= n * 1.6:
            return s
    return 0.1


def square_box(box, pad=0.35, min_side=0.05):
    """A crop around box (plate fractions): equal sides in fractions (so 16:9 in pixels), padded, inside the frame."""
    x0, y0, x1, y1 = box
    side = min(1.0, max(min_side, max(x1 - x0, y1 - y0) * (1 + 2 * pad)))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cx = min(max(cx, side / 2), 1 - side / 2)
    cy = min(max(cy, side / 2), 1 - side / 2)
    return [cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2]


def crop_grid(img, box, out_w=1600, grid=True):
    """The plate inside box (fractions), scaled to out_w px wide, with a labeled grid in full-image fractions."""
    W, H = img.size
    x0, y0, x1, y1 = box
    px = (round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))
    oh = max(1, round(out_w * (px[3] - px[1]) / max(1, px[2] - px[0])))
    im = img.crop(px).resize((out_w, oh), Image.LANCZOS)
    if not grid:
        return im
    d = ImageDraw.Draw(im, "RGBA")
    f = font(17)
    step = nice_step(x1 - x0)
    dec = 4 if step < 0.005 else 3
    for axis, (a, b) in ((0, (x0, x1)), (1, (y0, y1))):
        for k in range(math.ceil(a / step), math.floor(b / step) + 1):
            v = k * step
            p = (v - a) / (b - a) * (im.width if axis == 0 else im.height)
            line = [(p, 0), (p, im.height)] if axis == 0 else [(0, p), (im.width, p)]
            d.line(line, fill=(255, 255, 0, 110), width=1)
            d.text((p + 3, 3) if axis == 0 else (3, p + 2), f"{v:.{dec}f}", fill=(255, 255, 0, 255), font=f,
                   stroke_width=2, stroke_fill=(0, 0, 0, 255))
    return im


def bbox_of(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def clean_pts(pts):
    out = []
    for p in pts or []:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            out.append([x, y])
    return out


# ---------------------------------------------------------------- 1. look

def ask_candidates(scene, img, regs, brief, ana, aes):
    small = img.resize((1920, 1080), Image.LANCZOS)
    rl = [{"name": g["name"], "kind": g["kind"], "box": [round(v, 3) for v in g["bbox"]]} for g in regs]
    creatures = ", ".join(f"a {c}" for c in OFFERED[:-1]) + f" or a {OFFERED[-1]}"
    sig = brief.get("signature_detail") or brief.get("signature") or ""
    prompt = f"""You place small animated details on the key art of a calm 10-hour ambience video (one still image, animated in code).
Brief: {json.dumps({k: brief.get(k) for k in ('setting', 'time', 'weather', 'pet', 'props')}, ensure_ascii=False)}
Art style: {aes.get('style', '')}. Seen in the image: {ana.get('time_of_day', '')}, weather {ana.get('weather_outside', '')}.
The analysis already found these regions (name, kind, box [x0, y0, x1, y1]): {json.dumps(rl)}

The first image is the key art; the second is the same with a labeled grid every 0.1. Coordinates are fractions of
the image width (x) and height (y, from the top). Find what the image offers for each detail below. Leave a list
empty (or null) when nothing fits: a detail where it would not be in reality looks fake, and that is worse than none.

1. perches (at most 3): thin things out in the open air, seen against the sky or a far, lighter background, where
   small birds really sit: a power or phone line (look for every line crossing the sky: the commonest perch), a
   pole's crossarm, a bare branch, a fence rail, a roof ridge or gutter. Not indoors, not over the pet or the food.
   "pts": 2-8 points along it from left to right, only along the
   open stretch a bird could sit on; "what"; "thin": true for a wire, rope or twig (birds grip its centerline), false
   for a bar, rail or ridge (they stand on its top edge); "distance_m" from the camera.
2. chimneys (at most 2): a chimney, flue or stove pipe on a building in view that would smoke this evening (cold,
   wet or dusk). "top": the center of its opening at the very top; "what"; "width_m" (real outer width); "distance_m".
3. blossom: a tree in blossom (cherry, plum, apple, magnolia) whose petals could drift down, or null. "region": its
   region name from the list if it has one, else null; "canopy": the box of its blossoms; "distance_m".
4. moth_lamp: the one lamp, lantern or lit window pane outdoors (or out in an open view) a moth would circle at
   dusk or night, or null by day or when there is none. Not a neon sign. "region": its region name from the list;
   "lit": a tight box around its lit glass or bulb; "lit_width_m": the real width of that lit glass or bulb in meters.
5. empty_vessels: names of regions of kind steam whose cup, mug or bowl looks empty (no drink or soup visible).
6. critter_paths (at most 4; give 3 or 4 where the picture has the surfaces, each a different creature: Truman likes
   the little insects and asked for more of them, 2026-10-21): level surfaces in the near or middle ground where a
   small creature ({creatures})
   crawls slowly over minutes: a step's tread a little behind its front edge, a ledge, a sill, a planter rim, a wet
   street, a porch floor, a garden path. "path": 3-8 points where its foot touches the surface (never along an edge
   line, never on a riser, a wall or any upright face; across the frame rather than toward the camera: the creature
   is drawn from the side, and a path running toward the camera tilts it as if it climbed); it starts and ends where it
   can come out from behind something and go out of sight behind something (a pot, a post, a step, a bag) or at the
   frame edge; "creature" (fits the setting and weather: snails in rain); "surface": what it crawls on. Not over the
   pet, food or a fire.
7. ant_table: a near table, counter, desk or tray top with things standing on it (cups, bowls, books, a plate), or
   null. "box": its top surface; "paths" (2-3): 4-9 points each, on the top surface, where an ant walks; each starts
   hidden behind a thing standing on it (it comes out from behind it) or just over the surface's far edge, and ends
   the same way; never through a thing, never along the near edge's face.
8. signature: the brief's signature detail ("{sig}") as one of "critter:<creature>", "ant", "moth", "perch",
   "petals", "smoke", or "new: <what it would take>" when none of these shows it.

Return JSON: {{"perches": [...], "chimneys": [...], "blossom": ..., "moth_lamp": ..., "empty_vessels": [...],
"critter_paths": [...], "ant_table": ..., "signature": "..."}}"""
    res, _ = vision_json(prompt, images=[small, grid_image(small)], purpose=f"features:{scene}", effort="high")
    return res


# ---------------------------------------------------------------- 2-3. zoom and snap

def snap_line(gray, pts_px, thin, search=12):
    """Follow a thin line (thin: a wire's centerline, darker or lighter than around it) or a bar's top edge (lighter
    above, darker below) near a rough polyline (px). Returns (xs, ys fitted, strength, on-line mask) every 2 px of x,
    or None when the line is not there."""
    g = gray.astype(np.float32)
    P = np.array(sorted(pts_px), np.float32)
    x0, x1 = int(max(0, P[0, 0])), int(min(g.shape[1] - 1, P[-1, 0]))
    if x1 - x0 < 12:
        return None
    xs = np.arange(x0, x1 + 1, 2)
    yr = np.interp(xs, P[:, 0], P[:, 1])
    if thin:
        bg = cv2.blur(g, (1, 2 * search + 1))
        dark, light = bg - g, g - bg
        sample = [dark[int(np.clip(y, 0, g.shape[0] - 1)), int(x)] for x, y in zip(xs, yr)]
        resp = dark if np.median(sample) >= -0.5 else light
    else:
        resp = np.zeros_like(g)
        resp[2:-2] = g[:-4] - g[4:]
    ys, st = [], []
    for x, y0 in zip(xs, yr):
        a, b = int(max(0, y0 - search)), int(min(g.shape[0] - 1, y0 + search))
        col = resp[a:b + 1, int(x)]
        k = int(np.argmax(col))
        ys.append(a + k)
        st.append(float(col[k]))
    ys, st = np.array(ys, float), np.array(st, float)
    good = st > max(4.0, 0.35 * float(np.median(st)))
    c = None
    for _ in range(5):
        if good.sum() < 8:
            return None
        c = np.polyfit(xs[good], ys[good], 2)
        r = np.abs(np.polyval(c, xs) - ys)
        good = (st > max(4.0, 0.35 * float(np.median(st[good])))) & (r < max(1.6, 2.5 * float(np.median(r[good]))))
    fit = np.polyval(c, xs)
    if good.mean() < 0.45:
        return None
    return xs, fit, st, good


def place_perch(scene, img, gray, d8, cand):
    pts = clean_pts(cand.get("pts"))
    if len(pts) < 2:
        return None, "no points"
    thin = bool(cand.get("thin", True))
    box = square_box(bbox_of(pts), pad=0.2, min_side=0.06)
    crop = crop_grid(img, box)
    q = (f"Trace the {cand.get('what', 'line')} that runs through this crop precisely. \"pts\": 4-12 points along "
         + ("its centerline" if thin else "its top edge, where a bird's feet would grip")
         + ", from left to right, only along the open stretch a small bird could sit on. \"avoid\": [[x0, x1], ...] x spans "
         "along it where a bird can't sit: a pole, an insulator, a junction, a crossing line, a lamp, a sign. \"visible\": "
         "true if the line is clearly visible here. JSON: {\"pts\": [[x, y], ...], \"avoid\": [[x0, x1], ...], \"visible\": true}. " + COORDS)
    res, _ = vision_json(q, images=[crop], purpose=f"features:{scene}:perch", effort="medium")
    fp = clean_pts(res.get("pts")) or pts
    if res.get("visible") is False:
        return None, "the line is not clearly visible"
    W, H = img.size
    sn = snap_line(gray, [(x * W, y * H) for x, y in fp], thin)
    if sn is None:
        return None, "no line in the plate along the traced points"
    xs, fit, st, good = sn
    dist = float(cand.get("distance_m") or 25)
    size = float(np.clip(BIRD_M * FOCAL / max(dist, 3.0), 14, 30))
    ok = good.copy()
    for span in res.get("avoid") or []:
        try:
            a, b = sorted((float(span[0]) * W, float(span[1]) * W))
        except (TypeError, ValueError, IndexError):
            continue
        ok &= ~((xs >= a - 0.5 * size) & (xs <= b + 0.5 * size))
    ok &= (xs >= xs[0] + 0.6 * size) & (xs <= xs[-1] - 0.6 * size)
    # where the line thickens (an insulator, a junction, a crossing) its response spreads: not a seat
    slots, last = [], -1e9
    for x, k in zip(xs, ok):
        if k and x - last >= 1.6 * size:
            slots.append(float(x))
            last = x
    if not slots:
        return None, "no open stretch on the line"
    n = max(2, min(12, int((xs[-1] - xs[0]) / 26)))
    sel = np.linspace(0, len(xs) - 1, n).round().astype(int)
    line = [[round(float(xs[i]) / W, 5), round(float(fit[i]) / H, 5)] for i in sel]
    # the perch's disparity: the line's own (with the depth model's halo around it: the pole beside it must not hide
    # the birds), the 90th percentile along it
    dv = [d8[int(np.clip(round(f), 0, d8.shape[0] - 1)), int(x)] for x, f in zip(xs[good], fit[good])]
    disp = float(np.percentile(dv, 90)) ** 2 if dv else 0.05
    return {"name": cand.get("name") or cand.get("what", "perch").replace(" ", "_"), "pts": line,
            "slots": [round(s / W, 5) for s in slots[:6]], "size": round(size), "lift": 0 if thin else round(0.08 * size, 1),
            "_disp": round(disp, 4), "_what": cand.get("what"), "_snap": f"{int(good.sum())} of {len(xs)} samples on the line"}, "ok"


def place_moth(img, regs, cand, lights_g=None):
    by = {g["name"]: g for g in regs}
    reg = by.get((cand or {}).get("region") or "")
    if not reg:
        return None, f"no region named {cand.get('region')!r}"
    W, H = img.size
    box = clean_pts([(cand.get("lit") or [])[:2], (cand.get("lit") or [])[2:]]) if cand.get("lit") else []
    bx = bbox_of(box) if len(box) == 2 else reg["bbox"]
    bx = square_box(bx, pad=0.3, min_side=0.0)
    x0, y0, x1, y1 = int(bx[0] * W), int(bx[1] * H), int(bx[2] * W), int(bx[3] * H)
    rx0, ry0, rx1, ry1 = [int(v) for v in (reg["bbox"][0] * W, reg["bbox"][1] * H, reg["bbox"][2] * W, reg["bbox"][3] * H)]
    x0, y0, x1, y1 = max(x0, rx0), max(y0, ry0), min(x1, rx1), min(y1, ry1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        x0, y0, x1, y1 = rx0, ry0, rx1, ry1
    a = np.asarray(img.crop((x0, y0, x1, y1)).convert("L"), np.float32)
    thr = max(0.8 * float(a.max()), float(np.percentile(a, 92)))
    m = (a >= thr).astype(np.uint8)
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None, "no lit glass in the lamp"
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(lab == k)
    wts = a[ys, xs]
    cx, cy = float((xs * wts).sum() / wts.sum()) + x0, float((ys * wts).sum() / wts.sum()) + y0
    # one lamp unit is the lit glass's half width (the ramen alley's lamp: its panes, 32 px); the brightest core
    # alone is a third of that, so the model's box of the lit glass sets it when given
    half = (np.percentile(xs, 95) - np.percentile(xs, 5)) / 2 + 2
    if len(box) == 2:
        half = max(half, 0.5 * (box[1][0] - box[0][0]) * W)
    unit = float(np.clip(half, 10, 80))
    # its real size sets the moth's: a porch lantern's glass (~0.15 m) a meter away makes a 4.5 cm moth ~30 px, the
    # ramen alley's big street lamp far off made it a few px (drawn at 11 to read); a 16 px dot read as an overlay.
    # A small lamp near the camera (the Burdock Shelter's 6 cm paper lantern, a miniature world) wants a moth bigger
    # than the lantern; capped at 48 px: at 36 its blurred wingbeats read as a tan speck (2026-10-25, L148)
    lit_m = float(cand.get("lit_width_m") or 0.15)
    unit_m = max(0.03, lit_m / 2)
    size = int(np.clip(round(max(0.045 * unit / unit_m, 11)), 11, 48))
    # the glow's color from the lit pixels that aren't clipped white (a white-hot center lit the moth grey)
    rgb = np.asarray(img.crop((x0, y0, x1, y1)), np.float32) / 255
    sel = (a >= 0.45 * 255) & (a <= 0.95 * 255)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    col = lin[sel].mean(0) if sel.sum() >= 12 else None
    place = {"lamp": reg["name"], "center": [round(cx / W, 4), round(cy / H, 4)], "unit": round(unit), "size": size,
             "unitM": round(unit_m, 3)}
    # a moth 40 px or more across reads as one only with wing shapes and a fast shutter (1/200 s: the wingtips still blur a little): the soft blob of the small
    # moths, blurred over 1/60 s, read as a glowing orb at 48 px (L148)
    if size >= 40:
        place["detail"] = True
        place["shutter"] = 0.005
    if col is not None:
        place["color"] = [round(float(v) / float(col.max()), 3) for v in col]
    # a lamp under a roof on our side (a porch lantern): the indoors mask covers the whole porch, and moth.js would
    # hide the moth everywhere there (the farm porch, 2026-10-21); a lantern a character holds is cut from the outdoors
    # as dry (plate_prep's character rule), and the moth vanished over it and the one holding it (2026-10-25)
    if reg.get("dry_why"):
        place["covered"] = True
    if lights_g is not None and not place.get("covered"):
        gy, gx = lights_g.shape
        r = int(4 * unit * gx / W)
        win = lights_g[max(0, int(cy * gy / H) - r):int(cy * gy / H) + r, max(0, int(cx * gx / W) - r):int(cx * gx / W) + r]
        if win.size and float((win > 127).mean()) < 0.5:
            place["covered"] = True
    return place, "ok"


def place_smoke(scene, img, cand):
    top = clean_pts([cand.get("top")])
    if not top:
        return None, "no top"
    box = square_box([top[0][0] - 0.01, top[0][1] - 0.01, top[0][0] + 0.01, top[0][1] + 0.01], pad=0.0, min_side=0.06)
    crop = crop_grid(img, box)
    q = (f"There is a {cand.get('what', 'chimney')} in this crop. Give \"top\": [x, y] the center of its opening at the very top "
         "(where smoke would leave it), \"x0\" and \"x1\": its outer left and right edges at the top, and \"is_chimney\": true if "
         "it really is a chimney, flue or stove pipe. JSON: {\"top\": [x, y], \"x0\": x, \"x1\": x, \"is_chimney\": true}. " + COORDS)
    res, _ = vision_json(q, images=[crop], purpose=f"features:{scene}:smoke", effort="medium")
    if res.get("is_chimney") is False:
        return None, "not a chimney on a closer look"
    t = clean_pts([res.get("top")]) or top
    W = img.size[0]
    try:
        wpx = abs(float(res["x1"]) - float(res["x0"])) * W
    except (KeyError, TypeError, ValueError):
        wpx = 10.0
    dist = float(cand.get("distance_m") or 60)
    ppm = FOCAL / max(dist, 5.0)
    w = float(np.clip(wpx / ppm, 0.15, 1.2))
    return {"x": round(t[0][0], 4), "y": round(t[0][1], 4), "w": round(w, 2), "ppm": round(ppm, 1), "drift": 0.5,
            "density": 2.0, "life": 12}, "ok"


def surface_mask(seg, img, path_px):
    """The surface a path lies on (bool HxW at img size): SAM's candidate at the path's middle that holds the most of its
    inner points, under 40% of the frame."""
    inner = path_px[1:-1] or path_px
    probe = inner[len(inner) // 2]
    best = None
    for m, s in seg.point_candidates(img, [probe])[0]:
        if m.mean() > 0.4:
            continue
        inside = sum(bool(m[int(min(max(y, 0), m.shape[0] - 1)), int(min(max(x, 0), m.shape[1] - 1))]) for x, y in inner) / len(inner)
        if best is None or (inside, s) > best[0]:
            best = ((inside, s), m)
    return best[1] if best and best[0][0] >= 0.6 else None


def extend_ends(path_px, S, beyond, cap=300.0, depth=None, img=None, jump=0.04, far_cap=0.3):
    """Ends out in the open on the surface S walk on along the path's direction until they leave it (into a thing
    standing there, over the far edge, off the frame) and `beyond` px further, so the creature is hidden at its ends
    (L28, L49). An end that is still on the surface after `cap` px stays where it was.

    With the depth (depth8, nearer is larger) and the image: SAM often splits one surface into pieces (paving stones,
    planks), and leaving S there left the end out in the open on more of the same paving (the Minecraft tea house's
    signature gecko was dropped for it, 2026-10-22). So where S ends but the depth goes on as the path's own (no step
    nearer or farther) and the colors look like the surface's, the walk goes on, up to far_cap of the frame width; it
    stops where the depth jumps (a nearer thing it goes behind, or the far edge it goes over) or the colors change (a
    pot standing on the tread at the same depth)."""
    P = [np.array(p, float) for p in path_px]
    H, W = S.shape
    lab = None
    if depth is not None and img is not None:
        lab = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2LAB).astype(np.float32)

    def on(q):
        x, y = int(round(q[0])), int(round(q[1]))
        return 0 <= x < W and 0 <= y < H and bool(S[y, x])

    def z_at(q, r=3):
        x, y = int(round(q[0])), int(round(q[1]))
        return float(np.median(depth[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]))

    def col_at(q, r=6):
        x, y = int(round(q[0])), int(round(q[1]))
        return np.median(lab[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3), 0)

    def walk(b, a):
        if not on(b):
            return b
        L = max(1e-6, float(np.hypot(*(b - a))))
        d = (b - a) / L
        q, t = b.copy(), 0.0
        if lab is None:
            while t < cap:
                q, t = q + 2 * d, t + 2
                if not (0 <= q[0] < W and 0 <= q[1] < H):
                    return np.clip(q, [0, 0], [W - 1, H - 1])
                if not on(q):
                    return q + beyond * d
            return b
        # the surface's depth along the path (extrapolated from its last stretch) and its colors near the end
        zb, za = z_at(b), z_at(a)
        slope = (zb - za) / L
        r = int(max(12, beyond))
        y0, y1, x0, x1 = max(0, int(b[1]) - r), int(b[1]) + r + 1, max(0, int(b[0]) - r), int(b[0]) + r + 1
        sm = S[y0:y1, x0:x1]
        px = lab[y0:y1, x0:x1][sm] if sm.any() else lab[y0:y1, x0:x1].reshape(-1, 3)
        c0 = np.median(px, 0)
        spread = float(np.median(np.linalg.norm(px - c0, axis=1))) if len(px) else 0.0
        tol = max(18.0, 3.0 * spread)
        off_s = False
        cap2 = max(cap, far_cap * W)
        while t < cap2:
            q, t = q + 2 * d, t + 2
            if not (0 <= q[0] < W and 0 <= q[1] < H):
                return np.clip(q, [0, 0], [W - 1, H - 1])
            if abs(z_at(q) - (zb + slope * t)) > jump:
                return q + beyond * d                  # a nearer thing it goes behind, or the far edge it goes over
            if on(q):
                if t >= cap and not off_s:
                    return b                           # still on the surface after cap px: the end stays
                continue
            if float(np.linalg.norm(col_at(q) - c0)) > tol:
                return q + beyond * d                  # a thing standing on the surface at its depth
            off_s = True                               # SAM split the surface: more of the same goes on
        return b

    P[0] = walk(P[0], P[1])
    P[-1] = walk(P[-1], P[-2])
    return [list(map(float, q)) for q in P]


def place_fish(regs, horizon, rid=None):
    """Fish rising on open water (fish.js): zones on the water below the eye line, near and far, and the lake camera
    (boat.js lakeCamera). Zones come from the water's own pixels (regions.png), so a fence or a bank in front of it
    is left out; the camera's height puts the water's near edge about 40 m away (a pond across a field; rings come
    out ~0.5-1 m wide there)."""
    wat = [g for g in regs if g["kind"] == "water" and g.get("area", 0) >= 0.004]
    if not wat:
        return None, "no open water"
    if rid is not None:
        m = np.isin(rid, [g["id"] for g in wat])
    else:
        m = np.zeros((1080, 1920), bool)
        for g in wat:
            x0, y0, x1, y1 = g["bbox"]
            m[int(y0 * 1080):int(y1 * 1080), int(x0 * 1920):int(x1 * 1920)] = True
    Hm, Wm = m.shape
    rows = np.nonzero(m.mean(1) > 0.01)[0]
    if len(rows) < 4:
        return None, "too little water"
    y0, y1 = rows[0] / Hm, (rows[-1] + 1) / Hm
    hz = min(horizon, y0 - 0.006)                     # the water's far edge is below the eye line
    top = max(y0, hz + 0.008)
    if y1 - top < 0.02:
        return None, "the water is too thin a band to see rings on"
    ang = (y1 - hz) * H4 / FOCAL
    height = float(np.clip(40.0 * ang, 1.5, 20.0))
    zones = []
    for a, b, w in ((top, top + 0.5 * (y1 - top), 1.0), (top + 0.5 * (y1 - top), y1, 1.4)):
        band = m[int(a * Hm):max(int(a * Hm) + 1, int(b * Hm))]
        cols = band.mean(0) > 0.6                     # columns that are mostly water across the band
        if cols.sum() < 0.01 * Wm:
            continue
        # the widest run of such columns
        idx = np.nonzero(cols)[0]
        runs = np.split(idx, np.nonzero(np.diff(idx) > 3)[0] + 1)
        run = max(runs, key=len)
        rows_b = np.nonzero(band[:, run].mean(1) > 0.6)[0]
        if len(run) < 0.01 * Wm or len(rows_b) < 2:
            continue
        ya, yb = (int(a * Hm) + rows_b[0]) / Hm, (int(a * Hm) + rows_b[-1] + 1) / Hm
        pad = 0.06 * (run[-1] - run[0]) / Wm
        zones.append([round(run[0] / Wm + pad, 3), round(ya, 3), round((run[-1] + 1) / Wm - pad, 3), round(yb, 3), w])
    if not zones:
        return None, "no stretch of open water wide enough for rings"
    box = [min(z[0] for z in zones), min(z[1] for z in zones), max(z[2] for z in zones), max(z[3] for z in zones)]
    return {"camera": {"focalPx": FOCAL, "horizon": round(hz, 3), "height": round(height, 1)}, "zones": zones,
            "box": box}, "ok"


def place_path(scene, img, kind, cand, horizon, seg=None, depth=None, problem=None):
    """A critter's or an ant's path, traced again on a crop around it; open ends walk on until hidden. `problem`: the
    check's reason a first placement was dropped, for one more try (the Minecraft tea house's signature gecko, 2026-10-22)."""
    paths = [clean_pts(p) for p in (cand.get("paths") or [cand.get("path")])]
    paths = [p for p in paths if len(p) >= 2]
    if not paths:
        return None, "no path"
    allp = [q for p in paths for q in p]
    if problem and cand.get("_prev"):
        allp += clean_pts(cand["_prev"])
    crop = crop_grid(img, square_box(bbox_of(allp), pad=0.45 if problem else 0.3, min_side=0.14 if problem else 0.1))
    again = ""
    if problem:
        again = (" A first try was judged wrong: \"" + str(problem) + "\" (its path was " + json.dumps(cand.get("_prev")) + "). "
                 "Trace it again so this is fixed: move each end along the surface until it lies INSIDE the outline of something "
                 "nearer to the camera that the creature passes behind (a table, a post, a pot, a pillar's base), or at the frame "
                 "edge; keep the path on the level surface, a little in from any edge line, never along an edge.")
    if kind == "ant":
        q = ("An ant will walk on the top surface of the " + str(cand.get("what") or "table or counter") + " in this crop. Trace 2-3 "
             "paths for it, 5-9 points each, on the top surface. Each starts hidden behind a thing standing on the surface (a cup, a "
             "bowl, a book: its first point lies INSIDE that thing's outline, where the ant is still hidden) or exactly on the "
             "surface's far edge (it climbs up over it), and ends the same way (its last point inside the outline of what it goes "
             "behind, or on the far edge, where it walks over and down the far side). Never through a thing standing there, never "
             "along the near edge's face, never out in the open at an end. JSON: {\"paths\": [[[x, y], ...], ...], \"ends\": "
             "[[\"what it starts behind\", \"what it ends behind\"], ...]}. " + COORDS)
    else:
        q = (f"A small {cand.get('creature', 'snail')} will crawl slowly over minutes on the {cand.get('surface', 'surface')} in this "
             "crop. Trace its path: 4-8 points where its foot touches the level surface (on a step's tread a little behind the front "
             "edge, never along an edge line itself, never on a riser, a wall or any upright face). It starts where it comes out from "
             "behind something (a pot, a post, a step, a bag) or at the frame edge, and ends going out of sight behind something or at "
             "the frame edge; name what it hides behind at each end. JSON: {\"path\": [[x, y], ...], \"start_behind\": \"...\", "
             "\"end_behind\": \"...\"}. " + again + COORDS)
    res, _ = vision_json(q, images=[crop], purpose=f"features:{scene}:{kind}", effort="medium")
    W, H = img.size

    def hide(p, beyond):
        if seg is None:
            return p
        px = [(x * W, y * H) for x, y in p]
        S = surface_mask(seg, img, px)
        return p if S is None else [[x / W, y / H] for x, y in extend_ends(px, S, beyond, depth=depth, img=img)]

    if kind == "ant":
        got = [clean_pts(p) for p in res.get("paths") or []]
        got = [p for p in got if len(p) >= 3] or paths
        ys = [q[1] for p in got for q in p]
        y = sum(ys) / len(ys)
        size = float(np.clip(ANT_M * ANT_READ * max(y - horizon, 0.05) * H4 / CAM_H, 16, 34))
        got = [hide(p, 0.8 * size * W / W4) for p in got[:3]]
        return {"paths": [[[round(x, 4), round(y, 4)] for x, y in p] for p in got], "size": round(size), "horizon": horizon}, "ok"
    got = clean_pts(res.get("path"))
    got = got if len(got) >= 3 else paths[0]
    creature = creature_id(cand.get("creature"))                     # the sprite's file name: critter_<creature>.png
    sz = critter_size({"creature": creature, "path": got, "size": 0.01}, horizon)
    got = hide(got, 0.6 * sz * W / W4)
    return {"creature": creature, "path": [[round(x, 4), round(y, 4)] for x, y in got],
            "_behind": [res.get("start_behind"), res.get("end_behind")], "_surface": cand.get("surface")}, "ok"


# ---------------------------------------------------------------- 4. check

COLORS = {"perch": (0, 255, 255), "moth": (255, 80, 255), "smoke": (255, 255, 255), "petals": (255, 150, 190),
          "liquid": (255, 200, 0), "critter": (80, 255, 80), "ant": (255, 120, 0), "fish": (80, 160, 255)}
CRITERIA = {
    "perch": "the cyan line lies exactly on a real wire, crossarm, branch or rail (on a wire's centerline; on a bar, rail or "
             "ridge it marks the top edge, where the birds' feet grip, so it runs along that edge), not beside it or across "
             "empty sky, and the red circles, where birds will sit, are on open stretches of it, clear of poles, insulators, "
             "junctions and crossing lines",
    "moth": "the magenta circle is centered on the lit glass or bulb of a lamp outdoors (or out in the open view)",
    "smoke": "the white arrow starts at the very top of a real chimney, flue or stove pipe",
    "petals": "the pink box covers the blossoms of a tree in blossom",
    "liquid": "the orange-boxed cup or bowl looks empty (no drink or soup visible in it)",
    "fish": "the blue boxes lie on open water (a pond, lake, river or canal) where a fish could rise and send out rings, not on "
            "land, a road or the sky",
    "critter": "the green path lies on a level surface a small creature could crawl on (not in the air, not on a wall, a riser "
               "or any upright face, not along an edge line). Its ends (white: start, red: end) are where it is out of sight: "
               "inside the outline of something it passes behind (a pot, a post, a step), or at the frame edge; a dot just "
               "inside such an outline is right, a dot out in the open is wrong",
    "ant": "the orange path runs over the top surface of the table or counter. Its ends (white: start, red: end) are where the "
           "ant is out of sight: inside the outline of a thing standing on the surface, or a little past the surface's far "
           "edge (the ant walks over that edge and down the far side, where the counter hides it, so a dot just past the far "
           "edge is right). Wrong: an end out in the open on the top, a path through a thing standing there, a path that "
           "leaves the surface in its middle",
}


def draw_item(d, it, W, H, s=1.0, off=(0, 0), lw=3):
    k, p = it["kind"], it["place"]
    c = COLORS[k]
    P = lambda x, y: ((x * W - off[0]) * s, (y * H - off[1]) * s)  # noqa: E731
    if k == "perch":
        d.line([P(*q) for q in p["pts"]], fill=c, width=lw)
        ys = np.interp(p["slots"], [q[0] for q in p["pts"]], [q[1] for q in p["pts"]])
        for x, y in zip(p["slots"], ys):
            X, Y = P(x, y)
            d.ellipse([X - 2 * lw, Y - 2 * lw, X + 2 * lw, Y + 2 * lw], outline=(255, 0, 0), width=max(1, lw - 1))
    elif k == "moth":
        X, Y = P(*p["center"])
        r = p["unit"] * s
        d.ellipse([X - r, Y - r, X + r, Y + r], outline=c, width=lw)
    elif k == "smoke":
        X, Y = P(p["x"], p["y"])
        d.line([(X, Y), (X, Y - 60 * s)], fill=c, width=lw)
        d.polygon([(X - 8 * s, Y - 50 * s), (X + 8 * s, Y - 50 * s), (X, Y - 66 * s)], fill=c)
        d.ellipse([X - 4, Y - 4, X + 4, Y + 4], fill=(255, 0, 0))
    elif k in ("petals", "liquid"):
        x0, y0, x1, y1 = p["box"]
        d.rectangle([P(x0, y0), P(x1, y1)], outline=c, width=lw)
    elif k == "fish":
        for z in p["zones"]:
            d.rectangle([P(z[0], z[1]), P(z[2], z[3])], outline=c, width=lw)
    elif k in ("critter", "ant"):
        for path in ([p["path"]] if k == "critter" else p["paths"]):
            d.line([P(*q) for q in path], fill=c, width=lw)
            for q, col in ((path[0], (255, 255, 255)), (path[-1], (255, 0, 0))):
                X, Y = P(*q)
                d.ellipse([X - 2 * lw, Y - 2 * lw, X + 2 * lw, Y + 2 * lw], fill=col)


def item_box(it):
    k, p = it["kind"], it["place"]
    if k == "perch":
        return bbox_of(p["pts"])
    if k == "moth":
        u = p["unit"] / W4 * 2.5
        return [p["center"][0] - u, p["center"][1] - u * 16 / 9, p["center"][0] + u, p["center"][1] + u * 16 / 9]
    if k == "smoke":
        return [p["x"] - 0.01, p["y"] - 0.03, p["x"] + 0.01, p["y"] + 0.01]
    if k in ("petals", "liquid", "fish"):
        return p["box"]
    return bbox_of([q for path in ([p["path"]] if k == "critter" else p["paths"]) for q in path])


def check(scene, img, items, pd, name="features_preview.jpg"):
    W, H = img.size
    small = img.resize((1920, 1080), Image.LANCZOS)
    d = ImageDraw.Draw(small)
    f = font(22)
    for i, it in enumerate(items, 1):
        draw_item(d, it, W, H, s=1920 / W, lw=3)
        bx = item_box(it)
        d.text((bx[0] * 1920, max(0, bx[1] * 1080 - 26)), str(i), fill=COLORS[it["kind"]], font=f, stroke_width=3, stroke_fill=(0, 0, 0))
    small.save(pd / name, quality=88)
    crops = []
    for i, it in enumerate(items, 1):
        bx = square_box(item_box(it), pad=0.25, min_side=0.06)
        x0, y0 = bx[0] * W, bx[1] * H
        s = 1200 / ((bx[2] - bx[0]) * W)
        cim = img.crop((round(x0), round(y0), round(bx[2] * W), round(bx[3] * H))).resize((1200, round((bx[3] - bx[1]) * H * s)), Image.LANCZOS)
        cd = ImageDraw.Draw(cim)
        draw_item(cd, it, W, H, s=s, off=(x0, y0), lw=2)
        cd.text((8, 6), f"#{i} {it['kind']}", fill=(255, 255, 0), font=font(26), stroke_width=3, stroke_fill=(0, 0, 0))
        crops.append(cim)
    if not items:
        return []
    out = []
    for k in range(0, len(items), 5):
        sub = list(enumerate(items, 1))[k:k + 5]
        lines = "\n".join(f"#{i} {it['kind']}: right when {CRITERIA[it['kind']]}." for i, it in sub)
        q = ("Small animated details were placed on the key art of an ambience video. The first image shows all of them on the "
             "whole frame (numbered); then one zoomed crop for each of the items " + ", ".join(f"#{i}" for i, _ in sub) + ", in that "
             "order, each labeled with its number. Judge only these items, each strictly on its own crop. A detail that sits wrong "
             "(a bird in the air beside the wire, smoke out of a roof instead of a chimney, a snail walking up a wall) looks fake, "
             "so say no when unsure.\n" + lines + "\nJSON: {\"items\": [{\"id\": <number>, \"ok\": true, \"problem\": \"\"}, ...]}")
        res, _ = vision_json(q, images=[small] + [crops[i - 1] for i, _ in sub], purpose=f"features:{scene}:check", effort="high")
        out += res.get("items") or []
    return out


# ---------------------------------------------------------------- apply

def path_gap(p, q):
    """How far apart two paths are (frame fractions): the mean distance from each point of one to the other's line,
    both ways."""
    def one(a, b):
        B = np.array(b, float)
        dense = np.concatenate([B[i] + (B[i + 1] - B[i]) * np.linspace(0, 1, 24)[:, None] for i in range(len(B) - 1)]) if len(B) > 1 else B
        return float(np.mean([np.min(np.hypot(*(dense - np.array(x, float)).T)) for x in a]))
    return 0.5 * (one(p, q) + one(q, p))


def apply(spec, kept, ana, scene, force, regs):
    layers = spec.setdefault("layers", [])
    ev = spec.setdefault("events", {})
    E = DEFAULTS["events"]
    notes = []
    has = lambda t: any(L.get("type") == t for L in layers)  # noqa: E731
    stamp = "drafted by tools/plate_features.py"

    def put(t, layer, evk=None, evv=None):
        if has(t) and not force:
            return False
        if force:
            layers[:] = [L for L in layers if L.get("type") != t]
        layers.append(layer)
        if evk:
            ev[evk] = evv
        notes.append(t)
        return True

    per = [it["place"] for it in kept if it["kind"] == "perch"]
    if per:
        disp = max(p.pop("_disp", 0.05) for p in per)
        for p in per:
            p.pop("_what", None)
            p.pop("_snap", None)
        put("perch", {"type": "perch", "perches": per, "disp": round(max(disp, 0.02), 4), "haze": 0.25, "_auto": stamp},
            "perch", {"perHour": E["perch"]["perHour"], "slots": [len(p["slots"]) for p in per], "group": [1, 4], "stay": [90, 420],
                      "together": 0.35, "atStart": min(3, sum(len(p["slots"]) for p in per)), "startAfter": 4,
                      "first": E["perch"]["first"], "intro": [300, 2]})
    m = next((it["place"] for it in kept if it["kind"] == "moth"), None)
    if m:
        put("moth", {"type": "moth", **m, "_auto": stamp}, "moth",
            {"perHour": E["moth"]["perHour"], "dur": [45, 140], "lands": 2, "startAfter": 15, "first": E["moth"]["first"]})
    sm = [it["place"] for it in kept if it["kind"] == "smoke"]
    if sm:
        put("smoke", {"type": "smoke", "sources": sm, "_auto": stamp})
    pt = next((it["place"] for it in kept if it["kind"] == "petals"), None)
    if pt:
        layer = {"type": "petals", "_auto": stamp}
        if pt.get("region"):
            layer["tree"] = pt["region"]
        else:
            layer["treePpm"] = pt["ppm"]
        bx = [round(v, 3) for v in pt["box"]]
        put("petals", layer, "petals", {"tree": {"perMinute": 40, "box": bx, "fall": 6},
                                        "near": {"perMinute": 5, "depth": [2.5, 7], "x": [0.3, 0.7], "stay": [20, 40]},
                                        "flurry": {"tree": [14, 28], "near": [4, 9]}, "gustBoost": 1.4, "startAfter": 2})
    lq = [it["place"]["region"] for it in kept if it["kind"] == "liquid"]
    if lq:
        put("liquid", {"type": "liquid", "regions": lq, "_auto": stamp})
    fi = next((it["place"] for it in kept if it["kind"] == "fish"), None)
    if fi:
        F = E.get("fish", {})
        put("fish", {"type": "fish", "camera": fi["camera"], "_auto": stamp}, "fish",
            {"perHour": F.get("perHour", 20), "minGap": F.get("minGap", 60), "jump": 0.5, "zones": fi["zones"],
             "startAfter": 5, "first": F.get("first", 15)})
    ant = next((it["place"] for it in kept if it["kind"] == "ant"), None)
    if ant:
        put("ant", {"type": "ant", **ant, "_auto": stamp}, "ant",
            {"perHour": E["ant"]["perHour"], "dur": [16, 28], "paths": len(ant["paths"]), "startAfter": 5,
             "first": E["ant"]["first"], "intro": [300, 3], "file": 0.45})
    crs = [it["place"] for it in kept if it["kind"] == "critter"]
    if crs:
        old = [L for L in layers if L.get("type") == "critter"]
        if force:
            layers[:] = [L for L in layers if L.get("type") != "critter"]
            old = []
        olde = ev.get("critter")
        olde = olde if isinstance(olde, list) else [olde] if olde else []
        horizon = float(ana.get("horizon") or 0.45)
        specs = list(olde[:len(old)])
        while len(specs) < len(old):
            specs.append({"perHour": 3, "dur": [450, 600], "startAfter": 20})
        fresh = []
        for c in crs:
            # a checked path close to the analysis's unchecked one replaces it (same track); close to another new one: dropped
            twin = next((L for L in old if path_gap(L["path"], c["path"]) < 0.05), None)
            if twin is not None:
                if not twin.get("_auto"):
                    sz = critter_size({"creature": c["creature"], "path": c["path"], "size": 0.01}, horizon)
                    twin.update({"creature": c["creature"], "path": c["path"], "size": round(sz, 1), "_auto": stamp + " (replaced the draft's path)"})
                    twin.pop("sizeEnd", None)
                    notes.append(f"critter {c['creature']} (the draft's path, checked)")
                continue
            if any(path_gap(f["path"], c["path"]) < 0.05 for f in fresh):
                continue
            fresh.append(c)
        for c in fresh[:max(0, 3 - len(old))]:
            sz = critter_size({"creature": c["creature"], "path": c["path"], "size": 0.01}, horizon)
            ys = [q[1] for q in c["path"]]
            sz_end = critter_size({"creature": c["creature"], "path": [c["path"][-1]], "size": 0.01}, horizon) if max(ys) - min(ys) > 0.02 else sz
            k = len(specs)
            layer = {"type": "critter", "creature": c["creature"], "path": c["path"], "size": round(sz, 1), "_auto": stamp}
            if k:
                layer["track"] = k
            if abs(sz_end - sz) > 2:
                layer["sizeEnd"] = round(sz_end, 1)
            layers.append(layer)
            plen = sum(math.hypot((b[0] - a[0]) * W4, (b[1] - a[1]) * H4) for a, b in zip(c["path"], c["path"][1:])) + 2 * sz
            # each at its own pace in body lengths a second: only a snail glides at a few px a second; every creature
            # was drafted at the snail's (a gecko would have taken ten minutes to cross the tea house's paving,
            # 2026-10-22); the greenhouse's insects, timed by hand, walk 0.27-0.35
            pace = PACE.get(creature_id(c["creature"]), 0.04)
            dd = float(np.clip(plen / (pace * sz), 40, 900))
            specs.append({"perHour": 3, "dur": [round(0.85 * dd), round(1.15 * dd)], "startAfter": 4 + 8 * k, "first": 6 + 14 * k})
            notes.append(f"critter {c['creature']}")
        ev["critter"] = specs if len(specs) > 1 else specs[0] if specs else ev.get("critter")
    return notes


def critter_occ(scene, spec, pd):
    """What every critter hides behind at its path ends -> the masks json "critter_occ" (all of them) and
    "critter_occ_tracks" (each track's own), occ.png and occ_<track>.png. Each critter hides only behind its own
    covers: the shader draws a critter under whatever its map covers, without a depth test, and with one map for all
    the pixel greenhouse's seedling tray (a floor beetle goes behind it) hid the ladybug walking on the tray's rim
    (2026-10-21)."""
    from critter_ends import open_ends
    crs = [L for L in spec.get("layers", []) if L.get("type") == "critter" and len(L.get("path") or []) >= 2]
    if not crs:
        return []
    raw = Image.open(pd / "plate_raw.png").convert("RGB")
    W, H = raw.size
    dep = np.asarray(Image.open(pd / "depth8.png").convert("L"), np.float32) / 255 if (pd / "depth8.png").exists() else None
    seg = Segmenter()
    cov = np.zeros((H, W), bool)
    per = {}
    for L in crs:
        size = float(L.get("size", 40)) * W / W4
        c = critter_cover(seg, raw, L["path"], size, depth=dep)
        if c is not None:
            cov |= c
            per[str(L.get("track", 0))] = contours(c, W, H, eps=1.0, min_area=4)
    mp = ROOT / "assets" / "keyart" / f"{scene}.masks.json"
    ov = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    named = [x for x in ov.get("critter_occ") or [] if isinstance(x, str)]
    ov["critter_occ"] = named + (contours(cov, W, H, eps=1.0, min_area=4) if cov.any() else [])
    if len(crs) > 1:
        ov["critter_occ_tracks"] = per
    else:
        ov.pop("critter_occ_tracks", None)
    mp.write_text(json.dumps(ov, indent=1), encoding="utf-8", newline="\n")
    render_occluders(ov, W, H, pd, path=[L["path"] for L in crs])
    # an end is hidden only where critters.js can hide the whole creature (critter_ends: the same rule, L144); "any
    # cover within 3 body lengths" passed the Burdock Shelter's beetle, which then faded in on open moss
    missing = []
    for L in crs:
        for e in open_ends(scene, L, spec.get("plate", scene), spec.get("name", scene)):
            q = L["path"][0] if e == "start" else L["path"][-1]
            missing.append(f"{L.get('creature', 'critter')} track {L.get('track', 0)} {e} at ({q[0]:.3f}, {q[1]:.3f})")
    return missing


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--only", help="comma list of " + ",".join(KINDS))
    ap.add_argument("--dry", action="store_true", help="find and check, but leave scene.json and the masks alone")
    ap.add_argument("--force", action="store_true", help="replace layers of these kinds the scene already has")
    ap.add_argument("--reuse", action="store_true", help="reuse the cached candidates (features.json)")
    a = ap.parse_args()
    scene = a.scene
    only = set((a.only or ",".join(KINDS)).split(","))
    spec, pd, img, gray, d8, regs = _plate_inputs(scene)
    brief, ana, aes, horizon = _scene_inputs(scene, spec, pd)
    fj, cand = _candidates(a, scene, pd, img, regs, brief, ana, aes)
    items, dropped, add = _collector()

    _place_perch_moth_smoke(only, scene, pd, img, gray, d8, regs, cand, add)
    _place_petals_liquid_fish(only, pd, regs, cand, horizon, add)
    seg, want_ant = _segmenter(a, only, cand)
    _place_critters(only, scene, spec, img, cand, horizon, seg, d8, dropped, add)
    _place_ant(want_ant, scene, img, cand, horizon, seg, d8, add)
    kept, redo = _judge(scene, img, items, pd, seg, dropped)
    _retry(scene, img, pd, redo, horizon, seg, d8, kept, dropped)
    _signature_kept(cand, kept)
    kept = _merge_ants(kept)
    rec, notes, missing = _record(a, scene, spec, pd, cand, kept, dropped, ana, regs)
    return _report(a, pd, fj, rec, kept, dropped, notes, missing)


def _plate_inputs(scene):
    """(scene.json, the plate folder, the plate, its grey levels, the depth at its size, its regions)."""
    pd = ROOT / "out" / "plates" / scene
    spec = load_scene(scene)
    plate = spec.get("plate", scene)
    pd = ROOT / "out" / "plates" / plate
    img = Image.open(pd / "plate.png").convert("RGB")
    W, H = img.size
    gray = np.asarray(img.convert("L"), np.float32)
    d8 = np.asarray(Image.open(pd / "depth8.png").convert("L"), np.float32) / 255.0
    if d8.shape != gray.shape:
        d8 = cv2.resize(d8, (W, H), interpolation=cv2.INTER_LINEAR)
    regs = json.loads((pd / "regions.json").read_text(encoding="utf-8"))
    regs = regs["regions"] if isinstance(regs, dict) else regs
    return spec, pd, img, gray, d8, regs


def _scene_inputs(scene, spec, pd):
    """(the brief, the analysis, the look, the horizon)."""
    bp = ROOT / "scenes" / scene / "brief.json"
    brief = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
    ana = json.loads((pd / "analysis.json").read_text(encoding="utf-8")) if (pd / "analysis.json").exists() else {}
    ana = ana.get("model", ana)
    aes = config("aesthetics")["aesthetics"].get(spec.get("aesthetic"), {})
    horizon = float(ana.get("horizon") or (spec.get("plate_fx") or {}).get("horizon") or 0.45)
    return brief, ana, aes, horizon


def _candidates(a, scene, pd, img, regs, brief, ana, aes):
    """(features.json, the candidates: cached with --reuse, else the vision model's)."""
    fj = pd / "features.json"
    prev = json.loads(fj.read_text(encoding="utf-8")) if fj.exists() else {}
    if a.reuse and prev.get("candidates"):
        cand = prev["candidates"]
    else:
        print(f"features: asking the vision model what {scene} offers")
        cand = ask_candidates(scene, img, regs, brief, ana, aes)
    print(f"  signature detail: {brief.get('signature_detail', '-')} -> {cand.get('signature')}")
    return fj, cand


def _collector():
    """(the placed items, the dropped ones, add(kind, place, why, src), which files a placement under one of them)."""
    items, dropped = [], []

    def add(kind, place, why, src):
        if place is None:
            dropped.append({"kind": kind, "why": why, "candidate": src})
            print(f"  - {kind}: dropped ({why})")
        else:
            items.append({"kind": kind, "place": place, "candidate": src})
            print(f"  + {kind}: placed")
    return items, dropped, add


def _place_perch_moth_smoke(only, scene, pd, img, gray, d8, regs, cand, add):
    if "perch" in only:
        for c in (cand.get("perches") or [])[:3]:
            p, why = place_perch(scene, img, gray, d8, c)
            add("perch", p, why, c)
    if "moth" in only and cand.get("moth_lamp"):
        lp = pd / "lights.png"
        lg = np.asarray(Image.open(lp).convert("RGBA"))[..., 1] if lp.exists() else None
        p, why = place_moth(img, regs, cand["moth_lamp"], lg)
        add("moth", p, why, cand["moth_lamp"])
    if "smoke" in only:
        for c in (cand.get("chimneys") or [])[:2]:
            p, why = place_smoke(scene, img, c)
            add("smoke", p, why, c)


def _place_petals_liquid_fish(only, pd, regs, cand, horizon, add):
    if "petals" in only and cand.get("blossom"):
        b = cand["blossom"]
        box = b.get("canopy")
        names = {g["name"] for g in regs}
        if box and len(box) == 4:
            dist = float(b.get("distance_m") or 25)
            add("petals", {"box": [float(v) for v in box], "region": b.get("region") if b.get("region") in names else None,
                           "ppm": round(FOCAL / max(dist, 3.0), 1)}, "", b)
    if "liquid" in only:
        vessels = {g["name"]: g for g in regs if g["kind"] == "steam" and g.get("opening")}
        for n in cand.get("empty_vessels") or []:
            if n in vessels:
                add("liquid", {"region": n, "box": vessels[n]["bbox"]}, "", n)
    if "fish" in only:
        rp = pd / "regions.png"
        rid = np.asarray(Image.open(rp).convert("RGB").resize((1920, 1080), Image.NEAREST))[..., 0] if rp.exists() else None
        p, why = place_fish(regs, horizon, rid)
        if p is not None or why != "no open water":
            add("fish", p, why, "water regions")


def _segmenter(a, only, cand):
    """(SAM when a critter or the ant is to be placed, else None; whether the ant is wanted)."""
    seg = None
    want_ant = ("ant" in only) if a.only else str(cand.get("signature") or "").startswith("ant")
    if ("critter" in only and cand.get("critter_paths")) or (want_ant and cand.get("ant_table")):
        seg = Segmenter()
    return seg, want_ant


def _place_critters(only, scene, spec, img, cand, horizon, seg, d8, dropped, add):
    if "critter" in only:
        old = [L["path"] for L in spec.get("layers", []) if L.get("type") == "critter"]
        for c in (cand.get("critter_paths") or [])[:3]:
            pts = clean_pts(c.get("path"))
            if len(pts) < 2:
                continue
            mid = np.mean(pts, 0)
            if any(np.hypot(*(np.mean(o, 0) - mid)) < 0.05 for o in old):
                dropped.append({"kind": "critter", "why": "the analysis's critter already crawls there", "candidate": c})
                continue
            p, why = place_path(scene, img, "critter", c, horizon, seg, depth=d8)
            add("critter", p, why, c)


def _place_ant(want_ant, scene, img, cand, horizon, seg, d8, add):
    # the ant is the ramen alley's signature detail (L29): it comes back only when a video's signature is an ant
    # (or with --only ant)
    if want_ant and cand.get("ant_table"):
        p, why = place_path(scene, img, "ant", cand["ant_table"], horizon, seg, depth=d8)
        if p is None:
            add("ant", None, why, cand["ant_table"])
        for path in (p or {}).get("paths", []):
            add("ant", {**p, "paths": [path]}, "", cand["ant_table"])


def _judge(scene, img, items, pd, seg, dropped):
    """The check of every placement; -> (the kept ones, the critters to try again)."""
    verdicts = check(scene, img, items, pd)
    kept = []
    redo = []
    for i, it in enumerate(items, 1):
        v = next((x for x in verdicts if int(x.get("id", -1)) == i), {"ok": False, "problem": "no verdict"})
        it["check"] = v
        if v.get("ok"):
            kept.append(it)
            print(f"  ok   #{i} {it['kind']}")
        elif it["kind"] == "critter" and seg is not None:
            redo.append(it)
            print(f"  redo #{i} {it['kind']}: {v.get('problem')}")
        else:
            dropped.append({"kind": it["kind"], "why": "check: " + str(v.get("problem")), "candidate": it["candidate"], "place": it["place"]})
            print(f"  drop #{i} {it['kind']}: {v.get('problem')}")
    return kept, redo


def _retry(scene, img, pd, redo, horizon, seg, d8, kept, dropped):
    # a critter the check drops gets one more try with the check's reason (the Minecraft tea house lost all three,
    # its signature gecko among them, for ends left in the open and paths along an edge line, 2026-10-22; the pixel
    # greenhouse's signature ladybug was placed by hand for the same reason, L83)
    if redo:
        again = []
        for it in redo:
            c = {**it["candidate"], "_prev": it["place"]["path"]}
            p, why = place_path(scene, img, "critter", c, horizon, seg, depth=d8, problem=it["check"].get("problem"))
            if p is None:
                dropped.append({"kind": "critter", "why": "retry: " + why, "candidate": it["candidate"], "place": it["place"]})
                continue
            again.append({"kind": "critter", "place": p, "candidate": it["candidate"], "first_try": it["place"],
                          "first_check": it["check"]})
        v2 = check(scene, img, again, pd, name="features_retry.jpg") if again else []
        for i, it in enumerate(again, 1):
            v = next((x for x in v2 if int(x.get("id", -1)) == i), {"ok": False, "problem": "no verdict"})
            it["check"] = v
            if v.get("ok"):
                kept.append(it)
                print(f"  ok   retry {it['place'].get('creature')}")
            else:
                dropped.append({"kind": "critter", "why": "check (retry): " + str(v.get("problem")), "candidate": it["candidate"],
                                "place": it["place"]})
                print(f"  drop retry {it['place'].get('creature')}: {v.get('problem')}")


def _signature_kept(cand, kept):
    sig = str(cand.get("signature") or "")
    if sig.startswith("critter:"):
        want = creature_id(sig.split(":", 1)[1])
        if not any(it["kind"] == "critter" and creature_id(it["place"].get("creature")) == want for it in kept):
            print(f"  ! the signature detail ({sig}) was dropped: place it by hand on its surface's top face, both ends hidden "
                  "(L83); review.py's L29 lint fails until the scene has it")


def _merge_ants(kept):
    ants = [it for it in kept if it["kind"] == "ant"]
    if len(ants) > 1:
        merged = {**ants[0], "place": {**ants[0]["place"], "paths": [q for it in ants for q in it["place"]["paths"]]}}
        kept = [it for it in kept if it["kind"] != "ant"] + [merged]
    return kept


def _record(a, scene, spec, pd, cand, kept, dropped, ana, regs):
    """The record for features.json, and (unless --dry) the layers applied to scene.json and what the critters hide
    behind; -> (the record, what was applied, critter ends left in view)."""
    rec = {"scene": scene, "candidates": cand, "kept": kept, "dropped": dropped, "signature": cand.get("signature")}
    notes, missing = [], []
    if not a.dry:
        notes = apply(spec, [json.loads(json.dumps(k)) for k in kept], ana, scene, a.force, regs)
        save_scene(scene, spec)
        if any(n.startswith("critter") for n in notes):
            missing = critter_occ(scene, spec, pd)
        rec["applied"] = notes
        rec["critter_in_view"] = missing
    return rec, notes, missing


def _report(a, pd, fj, rec, kept, dropped, notes, missing):
    fj.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"features: kept {len(kept)}, dropped {len(dropped)}" + (f"; scene.json: {', '.join(notes) or 'nothing new'}" if not a.dry else " (dry)"))
    for m in missing:
        print(f"  ! {m}: nothing to hide behind at a path end; it fades in view there (L49): move that end")
    print(f"look at {pd / 'features_preview.jpg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
