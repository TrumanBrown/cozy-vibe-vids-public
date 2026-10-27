"""Weather only over the outdoors: the vision model looks at every part of the weather's area at 1:1.

Truman, 2026-10-21, on the pixel greenhouse's v6: rain still fell on the plants left of the lamp and beside it, after
earlier fixes, and he wants it fixed for good. Where the
weather draws (lights.png G: falling rain and the drops along its top edges; views.png: the glass layer's beads;
masks.png G: rings on wet ground) is built from depth, the analysis's polygons and hand polygons, and any of them
can take in what stands in front of the glass: SAM masks of the panes beside the lantern took the plants on the sill,
a tomato vine's edge and a potted plant's leaves. The free checks (leak_check, weather_audit) trust that area; this
one does not. It cuts every part of the frame where weather draws into tiles at 1:1, shows the model each tile plain
and with the area tinted magenta (hanging drops as yellow circles), and asks for anything inside the room or in
front of the glass under the tint: plants, leaves, pots, a lamp, frames, a sill, a wall, the pet.

  .venv\\Scripts\\python tools\\outdoor_check.py <scene> [--repair] [--rounds 2] [--no-ask] [--min-conf 0.6] [--first-pass auto|on|off]
  .venv\\Scripts\\python tools\\outdoor_check.py --selftest

--repair traces each flagged thing with SAM 2 (its box, a point on it and a point on the view beside it), grows the
cut by a cell, writes it to hand.json ("not_outdoor", and "not_water" where it covers wet ground: plate_prep's gap
fill still lets the view show between its parts), rebuilds the masks and asks again about the tiles that changed,
at most --rounds times. Answers are cached per tile (a hash of the plate and the area there), so unchanged tiles
cost nothing on the next run; review.py runs it on every review.

First passes on the local model (Truman 2026-10-22: the local model for first passes to save cost, Azure for the
final check; config/local_vision.json first_pass): with --repair, the local vision model (llama.cpp on
this PC's GPU, tools/local_vision.py) looks at every tile first, free. A tile it flags goes to Azure, and only what
Azure finds is cut: a local false alarm would otherwise cut real rain, and no later check looks where rain is missing
(the tea house's pavilion, L121). When the local model finds nothing more, Azure looks at every tile (the final
pass; tiles it already answered as they are now cost nothing), and from there the run is Azure's alone with its own
--rounds (what it finds then, the local model missed). A PASS is always Azure's. The local model caught 8
of 16 indoor things Azure caught on the labeled cases, so its rounds save Azure asks without deciding anything.
The server stops while SAM runs (both need the GPU). Without the setup (docs/SETUP.md) it stays on Azure.

Writes out/plates/<plate>/outdoor_check/: tile_<row><col>_plain.jpg, _tint.jpg (each patch of the weather's area
numbered), _ctx.jpg and _area.png (the evidence), check.json, and outdoor_check.jpg (the plate with the weather's
area, every flag in red, every cut in cyan). Exit 0 when nothing is flagged with at least --min-conf, 1 when
something is, 2 when it cannot run. About $0.02 per tile asked (medium effort); a glass room is 8 to 12 tiles.
--selftest asks about the fixtures in assets/reference/selftest/outdoor_* (plain crop, area mask, context; the tint
is drawn as check() draws it): the greenhouse's v6 tile by the lantern and its indoor trough must be flagged, the
lantern tile after the fix and the tea house's pavilion across the pond (L121) must pass.
"""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT, PY
import cozy.llama as llama
GRID = 4            # tiles per side; each tile is grown by MARGIN of its size on every side, so a thing on a tile's
MARGIN = 0.12       # edge is seen whole in one of them
MIN_PX = 300        # weather pixels in a tile's core for it to be asked about
VERSION = 4         # bump when the prompt or the evidence changes: cached answers are asked again
SELFTEST = ROOT / "assets" / "reference" / "selftest"
# (fixture, must be flagged): rain over indoor plants and an indoor trough must be flagged; the fixed lantern tile and
# the tea house's pavilion across the pond (rain in front of far buildings, lanterns and trees, L121) must pass
SELFTEST_CASES = [("outdoor_v6_lamp", True), ("outdoor_trough", True), ("outdoor_v7_lamp", False),
                  ("outdoor_pavilion", False)]

PROMPT = """You check where a cozy ambience video draws its weather, before it is rendered. Image 1 is a crop of the still
picture at full size. Image 2 is the same crop with the area where the video draws falling rain, splashes and rain
rings tinted MAGENTA (hanging water drops: yellow circles). Image 3 is the whole picture, smaller, with the same tint
and the crop outlined in yellow, so you know where the crop sits in the room.

Rain may only be drawn where we see the OUTSIDE: through window glass, a glass roof, a glass door or an opening: the
sky, the landscape, fields, trees and buildings outside, and ground or water that lies outdoors. Everything inside the
room or under its roof (plants in pots, beds or on trellises, hanging plants and vines, pots, lamps and lanterns,
cups, shelves, benches, troughs or tubs of water, floors, animals) and every solid part of the building the camera
stands in (its frames, mullions, beams, posts, sills, gutters, handles) must stay free of rain. The owner sees rain
over a leaf, a frame or indoor water as a glaring mistake, and a thin dry strip beside a frame as fine.

Other buildings are part of the view. Houses, pavilions, towers, roofs, walls, fences, bridges, steps, stone lanterns,
lanterns hanging on another building, lit windows and trees out in the open (across a garden, a pond, a field or a
street) stand in the rain: rain falls in front of them, so they are outside. Only the room, porch or veranda the
camera stands in, and what stands under its own roof, stay dry. A missing patch of rain in the shape of a far building
or tree is as bad a mistake as rain over a lamp in the room.

Step 1: list EVERY separate thing or surface that the magenta in image 2 lies on, each once, the outside ones too
(for example "sky in the upper pane", "far field", "leaf of the tomato vine at the pane's right edge", "water in the
trough"). Go along every edge of the magenta and look at every small magenta patch. Where the magenta's edge only
meets a thing's outline without lying on it, that thing is not covered.
Step 2: for each, say whether it is outside (seen through the glass or the opening, or out in the open).
Step 3: every separate magenta patch in image 2 has a white number. Go through EVERY number, thin slivers and small
patches too (a narrow strip beside a bright lamp is easy to miss), and say whether everything under that patch is
outside.

For each thing that is NOT outside also give "patch" (its number), "box": [x0, y0, x1, y1] tightly around the part of
it under the magenta, "point": [x, y] on it where the magenta covers it, and "view_point": [x, y] on the outside view
next to it (in the magenta, not on the thing), as fractions of image 2's width and height (0, 0 top left; 1, 1 bottom
right).

Answer as JSON: {"covered": [{"what": "...", "outside": true, "confidence": 0.0}, {"what": "...", "outside": false,
"confidence": 0.0, "patch": 1, "box": [0, 0, 0, 0], "point": [0, 0], "view_point": [0, 0]}], "patches": [{"n": 1,
"outside_only": true}], "seen": "briefly"}
"confidence" is how sure you are of that thing's outside or not."""


def load(scene):
    spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    plate = spec.get("plate", scene)
    return spec, plate, ROOT / "out" / "plates" / plate


def has_weather(spec):
    """Rain, snow, rain on the glass, drips or rings on wet ground in the scene (autoscene's layer types)."""
    on = [L for L in spec.get("layers", []) if L.get("enabled", True) is not False]
    return (any(L.get("type") in ("rain", "glass", "drips") or (L.get("type") == "particles" and "snow" in json.dumps(L)) for L in on)
            or bool((spec.get("plate_fx") or {}).get("ground")))


def grid(spec, pd):
    """The scene's pixel grid (cell, origin x, origin y) when it renders on its art's grid, else None."""
    px = (spec.get("render") or {}).get("pixel")
    if isinstance(px, dict) and px.get("cell"):
        return float(px["cell"]), float(px["origin"][0]), float(px["origin"][1])
    if px and (pd / "plate.json").exists():
        pg = json.loads((pd / "plate.json").read_text(encoding="utf-8")).get("pixel") or {}
        if pg.get("cell"):
            return float(pg["cell"]), float(pg["origin"][0]), float(pg["origin"][1])
    return None


def on_grid(m, g):
    """What the output pass shows of a mask on a pixel-art grid: every pixel takes its cell's center (output.glsl.js),
    so a sliver thinner than a cell either fills the cell or is gone."""
    cell, ox, oy = g
    H, W = m.shape
    cx = np.clip(np.floor(ox + (np.floor((np.arange(W) + 0.5 - ox) / cell) + 0.5) * cell).astype(int), 0, W - 1)
    cy = np.clip(np.floor(oy + (np.floor((np.arange(H) + 0.5 - oy) / cell) + 0.5) * cell).astype(int), 0, H - 1)
    return m[cy][:, cx]


def weather_area(spec, pd):
    """Where any weather draws (bool HxW, as the output shows it) and the hanging drops' sources [(x, y)] in plate px."""
    lights = np.asarray(Image.open(pd / "lights.png").convert("RGB"))
    area = lights[..., 1] > 127
    if (pd / "masks.png").exists():
        # rain rings draw only where rain falls on the wet ground (plate.js: groundRings * water * smoothstep(0.2, 0.8,
        # lights.g)); counting all of masks.png's wet ground tinted a sheltered deck on the Minecraft tea house as
        # weather, the model rightly called it indoor floor, and the repair cut there for nothing (2026-10-22)
        area |= (np.asarray(Image.open(pd / "masks.png").convert("RGB"))[..., 1] > 127) & (lights[..., 1] > 51)
    glass = [L for L in spec.get("layers", []) if L.get("type") == "glass" and L.get("enabled", True) is not False]
    if glass and (pd / "views.png").exists() and (pd / "regions.json").exists():
        regs = json.loads((pd / "regions.json").read_text(encoding="utf-8"))
        regs = regs["regions"] if isinstance(regs, dict) else regs
        views = np.asarray(Image.open(pd / "views.png").convert("RGB"))
        for L in glass:
            sel = L.get("regions") or "kind:glass"
            want = sel if isinstance(sel, list) else [sel]
            ids = [g["id"] for g in regs if g["name"] in want or f"kind:{g['kind']}" in want]   # every selected pane (glass.js)
            area |= np.isin(views[..., 0], ids) & (views[..., 1] > 127)
    g = grid(spec, pd)
    if g:
        area = on_grid(area, g)
    beads = []
    if any(L.get("type") == "drips" for L in spec.get("layers", [])) and (pd / "plate.json").exists():
        pj = json.loads((pd / "plate.json").read_text(encoding="utf-8"))
        beads = [(float(b[0]), float(b[1])) for b in (pj.get("beads") or []) + (pj.get("strand_drips") or [])]
    return area, beads


def tiles(area):
    H, W = area.shape
    tw, th = W / GRID, H / GRID
    out = []
    for r in range(GRID):
        for c in range(GRID):
            x0, y0, x1, y1 = int(c * tw), int(r * th), int((c + 1) * tw), int((r + 1) * th)
            if int(area[y0:y1, x0:x1].sum()) < MIN_PX:
                continue
            out.append((f"{r}{c}", (max(0, int(x0 - MARGIN * tw)), max(0, int(y0 - MARGIN * th)),
                                    min(W, int(x1 + MARGIN * tw)), min(H, int(y1 + MARGIN * th)))))
    return out


def tint(a, m):
    """Magenta at half strength over the area, its outline drawn just inside it (never over what borders it)."""
    b = a.astype(np.float32)
    b[m] = b[m] * 0.5 + np.array([255, 0, 255], np.float32) * 0.5
    edge = m & ~cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    b[edge] = (255, 40, 255)
    return b.clip(0, 255).astype(np.uint8)


def patches(m, min_px=150):
    """The separate patches of the weather's area in a tile, each with a spot well inside it for its number: the model
    answers for every patch by number, so a thin one next to a bright lamp gets an explicit answer instead of none."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    out = []
    for i in sorted(range(1, n), key=lambda i: (st[i, cv2.CC_STAT_TOP], st[i, cv2.CC_STAT_LEFT])):
        if st[i, cv2.CC_STAT_AREA] < min_px:
            continue
        d = cv2.distanceTransform((lab == i).astype(np.uint8), cv2.DIST_L2, 3)
        y, x = np.unravel_index(int(np.argmax(d)), d.shape)
        x0, y0, w, h = (int(v) for v in st[i, :4])
        out.append({"n": len(out) + 1, "at": (int(x), int(y)), "box": (x0, y0, x0 + w, y0 + h), "px": int(st[i, cv2.CC_STAT_AREA])})
    return out


def numbered(t, pats):
    """The patches' numbers on the tinted tile: white with a dark outline."""
    t = np.ascontiguousarray(t)
    for p in pats:
        x, y = p["at"]
        s = str(p["n"])
        (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        org = (int(min(max(2, x - tw / 2), t.shape[1] - tw - 2)), int(min(max(th + 2, y + th / 2), t.shape[0] - 2)))
        cv2.putText(t, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(t, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return t


def evidence(plate, area, beads, box):
    """The tile plain and with the weather's area tinted in magenta, each patch numbered, drops as yellow circles.
    Returns (plain, tinted, patches)."""
    x0, y0, x1, y1 = box
    a = plate[y0:y1, x0:x1]
    m = area[y0:y1, x0:x1]
    pats = patches(m)
    t = Image.fromarray(numbered(tint(a, m), pats))
    d = ImageDraw.Draw(t)
    for x, y in beads:
        if x0 <= x < x1 and y0 <= y < y1:
            d.ellipse((x - x0 - 7, y - y0 - 7, x - x0 + 7, y - y0 + 7), outline=(255, 230, 0), width=2)
    return Image.fromarray(np.ascontiguousarray(a)), t, pats


def context(plate, area):
    """The whole picture, smaller, tinted like the tiles (the tile's box is drawn on it per tile)."""
    H, W = area.shape
    s = 1280 / W
    small = cv2.resize(plate, (1280, round(H * s)), interpolation=cv2.INTER_AREA)
    m = cv2.resize(area.astype(np.uint8), (1280, round(H * s)), interpolation=cv2.INTER_NEAREST).astype(bool)
    b = small.astype(np.float32)
    b[m] = b[m] * 0.5 + np.array([255, 0, 255], np.float32) * 0.5
    return Image.fromarray(b.clip(0, 255).astype(np.uint8)), s


def context_for(ctx, s, box):
    im = ctx.copy()
    x0, y0, x1, y1 = box
    ImageDraw.Draw(im).rectangle((x0 * s, y0 * s, x1 * s, y1 * s), outline=(255, 230, 0), width=3)
    return im


def tile_hash(plate, area, beads, box):
    x0, y0, x1, y1 = box
    h = hashlib.sha1(f"v{VERSION}".encode())
    h.update(np.ascontiguousarray(plate[y0:y1, x0:x1]).tobytes())
    h.update(np.packbits(area[y0:y1, x0:x1]).tobytes())
    h.update(json.dumps([[round(x), round(y)] for x, y in beads if x0 <= x < x1 and y0 <= y < y1]).encode())
    return h.hexdigest()[:16]


def ask(plain, tint_im, ctx_im, purpose, effort="high", pats=None, backend=None):
    from azure_ai import vision_json
    res, usage = vision_json(PROMPT, images=[plain, tint_im, ctx_im], purpose=purpose, effort=effort, max_side=1600, backend=backend)

    def nums(v, n):
        try:
            return [float(x) for x in v] if v is not None and len(v) == n else None
        except (TypeError, ValueError):
            return None
    cov = []
    for o in res.get("covered") or res.get("objects") or []:
        if not isinstance(o, dict):
            continue
        try:
            conf = float(o.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        item = {"what": str(o.get("what", "?")), "outside": o.get("outside") is True, "confidence": conf}
        if not item["outside"]:
            b, p = nums(o.get("box"), 4), nums(o.get("point"), 2)
            if b is None and p is not None:
                b = [p[0] - 0.03, p[1] - 0.03, p[0] + 0.03, p[1] + 0.03]
            if p is None and b is not None:
                p = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]
            item.update({"box": b, "point": p, "view_point": nums(o.get("view_point"), 2), "patch": o.get("patch")})
        cov.append(item)
    # a patch the model says is not only outside, with nothing listed for it, is flagged at the patch itself
    W, H = tint_im.size
    by_n = {p["n"]: p for p in pats or []}
    named = {o.get("patch") for o in cov if not o["outside"]}
    for q in res.get("patches") or []:
        if not isinstance(q, dict) or q.get("outside_only") is not False or q.get("n") in named or q.get("n") not in by_n:
            continue
        p = by_n[q["n"]]
        x0, y0, x1, y1 = p["box"]
        cov.append({"what": f"something under patch {p['n']}", "outside": False, "confidence": 0.7, "patch": p["n"],
                    "box": [x0 / W, y0 / H, x1 / W, y1 / H], "point": [p["at"][0] / W, p["at"][1] / H], "view_point": None})
    return {"covered": cov, "patches": res.get("patches") or [], "seen": res.get("seen", "")}, float(usage.get("usd_est", 0.0))


def hits(ans, min_conf):
    """The things an answer found under the weather that are not outside."""
    return [o for o in ans.get("covered") or [] if not o.get("outside") and o.get("confidence", 0) >= min_conf]


def local_name():
    from azure_ai import local_model
    return local_model()[0]


def first_pass(mode):
    """Whether --repair screens with the local model first: --first-pass on or off, else (auto) whether
    config/local_vision.json "first_pass" lists outdoor_check (Truman 2026-10-22: the local model for first passes,
    Azure for the final check)."""
    if mode in ("on", "off"):
        return mode == "on"
    try:
        from azure_ai import local_cfg
        return "outdoor_check" in (local_cfg().get("first_pass") or [])
    except Exception:   # noqa: BLE001
        return False


def screen_tile(plain, tint_im, ctx_im, pats, scene, effort, min_conf, lasks):
    """The local first pass on one tile, with check()'s vote. Returns (asks, flagged). An answer that isn't valid JSON
    counts as a flag: an unsure tile goes to Azure."""
    errors = 0
    while True:
        k = sum(1 for x in lasks if hits(x, min_conf))
        if lasks and (k == 0 or k >= 2 or len(lasks) - k >= 2):
            break
        try:
            ans, _ = ask(plain, tint_im, ctx_im, f"outdoor_check:{scene}", effort, pats, backend="local")
        except Exception as e:   # noqa: BLE001  (a bad answer, or the server gone)
            errors += 1
            if errors >= 2:
                print(f"    local first pass: no answer ({str(e)[:120]}); the tile goes to Azure")
                return lasks, True
            continue
        lasks.append(ans)
    found = [x for x in lasks if hits(x, min_conf)]
    return lasks, len(found) >= 2 or (len(found) == 1 and len(lasks) < 3)


def check(scene, ask_model=True, min_conf=0.6, quiet=False, effort="high", screen=None):
    """Every tile: its evidence, and the model's answers (cached by the tile's hash). A tile with a flag is asked up
    to three times and fails when two of them find something: the model is not consistent from one ask to the next
    (a tile it called clean got a beam flagged on the next ask, 2026-10-21). Returns (state, flags, usd, data);
    flags = [(tile key, box, thing)] from the asks that found something.
    screen="local": the local model looks first (its answers cached per model and tile); a tile it calls clean is left
    for the final pass, a tile it flags goes to Azure, and only what Azure finds counts. Azure's answers already
    cached for a tile as it is are used as they are. The result is not final (state "final": false)."""
    spec, plate_name, pd = load(scene)
    od = pd / "outdoor_check"
    od.mkdir(exist_ok=True)
    cj = od / "check.json"
    state = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}
    cache = state.get("cache") or {}
    lcache = state.get("cache_local") or {}
    lname = local_name() if screen else None
    plate = np.asarray(Image.open(pd / "plate.png").convert("RGB"))
    area, beads = weather_area(spec, pd)
    ctx, s = context(plate, area)
    ts = tiles(area)
    flags, usd, now, missing = [], 0.0, {}, []
    for key, box in ts:
        hsh = tile_hash(plate, area, beads, box)
        plain, tint_im, pats = evidence(plate, area, beads, box)
        ctx_im = context_for(ctx, s, box)
        plain.save(od / f"tile_{key}_plain.jpg", quality=90)
        tint_im.save(od / f"tile_{key}_tint.jpg", quality=90)
        ctx_im.save(od / f"tile_{key}_ctx.jpg", quality=85)
        x0, y0, x1, y1 = box
        Image.fromarray((area[y0:y1, x0:x1] * 255).astype(np.uint8)).save(od / f"tile_{key}_area.png")
        asks = list((cache.get(hsh) or {}).get("asks") or [])
        n0 = len(asks)
        if screen and ask_model and not asks:
            lk = f"{lname}:{hsh}"
            lasks, flagged = screen_tile(plain, tint_im, ctx_im, pats, scene, effort, min_conf,
                                         list((lcache.get(lk) or {}).get("asks") or []))
            lcache[lk] = {"asks": lasks}
            if not flagged:
                now[key] = {"box": list(box), "hash": hsh, "asks": 0, "screened": "clean", "local_asks": len(lasks)}
                if not quiet:
                    print(f"  tile {key} {box}: clean on the local first pass")
                continue
            if not quiet:
                names = sorted({o["what"] for x in lasks for o in hits(x, min_conf)})
                print(f"  tile {key} {box}: the local first pass flags " + ("; ".join(names) or "it") + ": asking Azure")
        while ask_model:
            k = sum(1 for x in asks if hits(x, min_conf))
            if asks and (k == 0 or k >= 2 or len(asks) - k >= 2):
                break
            ans, c = ask(plain, tint_im, ctx_im, f"outdoor_check:{scene}", effort, pats, backend="azure")
            usd += c
            asks.append(ans)
        if not asks:
            missing.append(key)
            now[key] = {"box": list(box), "hash": hsh, "asks": 0}
            continue
        cache[hsh] = {"asks": asks}
        found = [x for x in asks if hits(x, min_conf)]
        fails = len(found) >= 2 or (len(found) == 1 and len(asks) < 3)
        tile_flags = [(key, box, o) for x in found for o in hits(x, min_conf)] if fails else []
        flags += tile_flags
        now[key] = {"box": list(box), "hash": hsh, "asks": len(asks), "found": len(found), "fails": fails}
        if not quiet:
            names = sorted({o["what"] for _, _, o in tile_flags})
            print(f"  tile {key} {box}: " + (f"{len(found)} of {len(asks)} asks found: " + "; ".join(names) if fails
                                              else "clean" + (f" ({len(found)} of {len(asks)} asks found something)" if found else ""))
                  + (" (cached)" if n0 == len(asks) else ""))
    state.update({"scene": scene, "plate": plate_name, "version": VERSION, "tiles": now, "cache": cache, "cache_local": lcache,
                  "tiles_hash": {k: v["hash"] for k, v in now.items()}, "missing": missing,
                  "pass": not flags and not missing, "final": screen is None,
                  "screened_clean": sum(1 for v in now.values() if v.get("screened") == "clean"),
                  "checked": dt.datetime.now().isoformat(timespec="seconds")})
    cj.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    return state, flags, usd, (plate, area, beads)


def to_px(box, f):
    x0, y0, x1, y1 = box
    return (x0 + f[0] * (x1 - x0), y0 + f[1] * (y1 - y0))


def refine(cand, T, lab, lim):
    """Keep in a cut only the weather pixels that look like the object, not like the view beside it. SAM's outline of a
    tomato vine took the column of sky between the vine and the next mullion, and that pane went dry (weather_audit's
    dry pocket, 2026-10-21). Palettes: the object's pixels outside the weather area and the view's inside it near the
    object (8 Lab clusters each); a pixel under the weather that SAM gave the object stays cut when it is nearer the
    object's palette. Only for a thing mostly outside the weather (a vine reaching into a pane), and skipped when either
    side has too few pixels to learn from: then the whole outline is cut."""
    obj = cand & ~T & lim
    view = T & ~cand & lim
    inside = cand & T
    # a thing that lies mostly under the weather (the water in a trough, a leaf wholly inside a pane) is itself what the
    # tint covers, and the tinted pixels around it are more of it: the trough's water was half kept as "view"
    if obj.sum() < 60 or view.sum() < 60 or not inside.any() or inside.sum() > 0.5 * cand.sum():
        return cand

    def centers(sel):
        X = lab[sel].astype(np.float32)
        if len(X) > 20000:
            X = X[np.random.default_rng(0).choice(len(X), 20000, replace=False)]
        k = min(8, len(X))
        _, _, c = cv2.kmeans(X, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 2, cv2.KMEANS_PP_CENTERS)
        return c
    co, cw = centers(obj), centers(view)
    P = lab[inside].astype(np.float32)
    do = ((P[:, None, :] - co[None]) ** 2).sum(-1).min(1)
    dw = ((P[:, None, :] - cw[None]) ** 2).sum(-1).min(1)
    keep = np.zeros_like(cand)
    keep[inside] = do <= dw
    return (cand & ~T) | keep


def repair(scene, flags, area, pixel_cell):
    """SAM traces of the flagged things, kept to what looks like the thing (refine), grown by a cell, into hand.json
    not_outdoor / not_water. Returns the cut mask and the names cut."""
    import cozy.segment as A
    spec, plate_name, pd = load(scene)
    raw = Image.open(pd / "plate_raw.png").convert("RGB")
    W, H = raw.size
    lab = cv2.cvtColor(np.asarray(Image.open(pd / "plate.png").convert("RGB"), np.float32) / 255, cv2.COLOR_RGB2LAB)
    water = np.asarray(Image.open(pd / "masks.png").convert("RGB"))[..., 1] > 127 if (pd / "masks.png").exists() else np.zeros((H, W), bool)
    seg = A.Segmenter()
    cuts = np.zeros((H, W), bool)
    names = []
    grow = max(3, int(round(pixel_cell or 4 * W / 3840)))
    done = set()
    for key, box, o in flags:
        if not o.get("box"):
            print(f"  ! {o['what']} (tile {key}): no box or point in the answer; left for the agent")
            continue
        sig = (key, round(o["point"][0], 2), round(o["point"][1], 2))
        if sig in done:          # the same thing from another ask of the tile
            continue
        done.add(sig)
        bx0, by0 = to_px(box, o["box"][:2])
        bx1, by1 = to_px(box, o["box"][2:])
        bx0, bx1 = sorted((bx0, bx1))
        by0, by1 = sorted((by0, by1))
        pw, ph = max(12.0, 0.15 * (bx1 - bx0)), max(12.0, 0.15 * (by1 - by0))
        gb = [max(0, bx0 - pw), max(0, by0 - ph), min(W - 1, bx1 + pw), min(H - 1, by1 + ph)]
        pt = to_px(box, o["point"])
        pts, labels = [pt], [1]
        if o.get("view_point"):
            vp = to_px(box, o["view_point"])
            if 0 <= vp[0] < W and 0 <= vp[1] < H:
                pts.append(vp)
                labels.append(0)
        cands = seg.prompt_candidates(raw, gb, pts, labels)
        lim = np.zeros((H, W), bool)
        lx0, ly0 = int(max(0, gb[0] - 2 * pw)), int(max(0, gb[1] - 2 * ph))
        lx1, ly1 = int(min(W, gb[2] + 2 * pw)), int(min(H, gb[3] + 2 * ph))
        lim[ly0:ly1, lx0:lx1] = True
        tint_here = area & lim
        best = None
        for m, s in cands:
            m = m & lim
            if not m.any() or not (m & area).any():
                continue
            px, py = int(min(W - 1, max(0, pt[0]))), int(min(H - 1, max(0, pt[1])))
            near_pt = m[max(0, py - 6):py + 7, max(0, px - 6):px + 7].any()
            # SAM sometimes takes the pane's view itself: a candidate that is nearly all of the tinted area around it
            inter = float((m & tint_here).sum())
            union = float((m | tint_here).sum())
            viewlike = inter / max(union, 1.0) > 0.7
            if near_pt and not viewlike and (best is None or s > best[1]):
                best = (m, s)
        if best is None:
            print(f"  ! {o['what']} (tile {key}): SAM gave no outline that holds the point and is not the view itself; left for the agent")
            continue
        kept = refine(best[0], area, lab, lim)
        back = int((best[0] & area & ~kept).sum())
        c = cv2.dilate(kept.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))).astype(bool)
        cuts |= c
        names.append(f"{o['what']} (tile {key}, {int((c & area).sum())} px of weather)")
        print(f"  cut: {o['what']} (tile {key}): {int((c & area).sum())} px of weather taken off"
              + (f" ({back} px of view in SAM's outline kept)" if back else ""))
    if not cuts.any():
        return cuts, names
    polys = A.contours(cuts, W, H, eps=1.0, min_area=6)
    wpolys = A.contours(cuts & cv2.dilate(water.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool), W, H, eps=1.0, min_area=6) if water.any() else []
    hp = ROOT / "assets" / "keyart" / f"{plate_name}.hand.json"
    hand = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {"_note": "Hand fixes merged over the analyzed masks (tools/plate_prep.py)."}
    # their own keys: plate_prep cuts them like not_outdoor / not_water, and weather_audit counts them as dry on purpose
    # (what the model saw inside, and a cell around it), so its dry-pocket check doesn't send them back
    hand.setdefault("outdoor_cuts", []).extend(polys)
    if wpolys:
        hand.setdefault("water_cuts", []).extend(wpolys)
    day = dt.date.today().isoformat()
    hand["_outdoor_check"] = (hand.get("_outdoor_check", "") + f" {day}: tools/outdoor_check.py --repair cut what the vision "
                              f"model found under the weather's area (SAM from its box and points, grown a cell): "
                              + "; ".join(names) + ".").strip()
    hp.write_text(json.dumps(hand, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    return cuts, names


def preview(pd, plate, area, flags, cuts):
    H, W = area.shape
    pv = plate.astype(np.float32) * 0.6
    pv[area] = pv[area] * 0.55 + np.array([255, 0, 255], np.float32) * 0.45 * 0.6
    if cuts is not None and cuts.any():
        e = cuts & ~cv2.erode(cuts.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        pv[cv2.dilate(e.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = (0, 255, 255)
    im = Image.fromarray(pv.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for key, box, o in flags:
        if not o.get("point"):
            continue
        x, y = to_px(box, o["point"])
        d.ellipse((x - 28, y - 28, x + 28, y + 28), outline=(255, 40, 40), width=6)
        d.text((x + 32, y - 10), o["what"][:40], fill=(255, 80, 80))
    im.resize((W // 2, H // 2), Image.LANCZOS).save(pd / "outdoor_check" / "outdoor_check.jpg", quality=88)


def report(flags, missing):
    seen = set()
    for key, box, o in flags:
        x, y = to_px(box, o["point"]) if o.get("point") else (float("nan"), float("nan"))
        if (key, o["what"]) in seen:
            continue
        seen.add((key, o["what"]))
        print(f"   - weather over {o['what']} at ({x:.0f}, {y:.0f}) px, tile {key} ({o['confidence']:.2f})")
    for key in missing:
        print(f"   - tile {key} not asked (--no-ask, or the model failed)")


def selftest(effort="high", min_conf=0.6):
    """Fixtures (assets/reference/selftest/outdoor_<name>_plain.jpg, _area.png (the weather's area in the tile) and
    _ctx.jpg), the tinted and numbered evidence built from them as check() builds it, judged as check() judges a tile
    (up to three asks, two must find something): the greenhouse's v6 tile by the lantern (rain over the potted plant, the
    plants on the sill and a tomato vine's edge) and the indoor trough's front must be flagged; the lantern tile after the
    fix must pass, and so must the Minecraft tea house's pavilion across the pond with its lanterns, the pagoda and the
    trees under the rain (the check had cut the rain in front of them as "solid parts of the building", L121). (The
    sliver of glass beside the lantern is real glass, and the model says so: plate_prep's sliver rule keeps such strips
    dry on pixel art, not this check.)"""
    cases = SELFTEST_CASES
    right, usd, n = 0, 0.0, 0
    for name, want_flag in cases:
        ps = [SELFTEST / f"{name}_{k}" for k in ("plain.jpg", "area.png", "ctx.jpg")]
        if not all(p.exists() for p in ps):
            print(f"  missing fixture {name}")
            continue
        n += 1
        plain = Image.open(ps[0]).convert("RGB")
        m = np.asarray(Image.open(ps[1]).convert("L")) > 127
        pats = patches(m)
        tint_im = Image.fromarray(numbered(tint(np.asarray(plain), m), pats))
        ctx_im = Image.open(ps[2]).convert("RGB")
        (ROOT / "out" / "outdoor_selftest").mkdir(parents=True, exist_ok=True)
        tint_im.save(ROOT / "out" / "outdoor_selftest" / f"{name}_tint.jpg", quality=90)
        asks = []
        while True:
            k = sum(1 for x in asks if hits(x, min_conf))
            if asks and (k == 0 or k >= 2 or len(asks) - k >= 2):
                break
            ans, c = ask(plain, tint_im, ctx_im, "outdoor_check:selftest", effort, pats)
            usd += c
            asks.append(ans)
        found = [x for x in asks if hits(x, min_conf)]
        flagged = len(found) >= 2 or (len(found) == 1 and len(asks) < 3)
        ok = flagged == want_flag
        right += ok
        names = sorted({o["what"] for x in found for o in hits(x, min_conf)})
        print(f"  {'ok   ' if ok else 'WRONG'} {name}: expected {'flags' if want_flag else 'clean'}, got "
              + (f"flags ({len(found)} of {len(asks)} asks): " + "; ".join(names) if flagged else
                 f"clean ({len(found)} of {len(asks)} asks found something)"))
    print(f"selftest: {right}/{n} right, ~${usd:.2f}")
    return 0 if n and right == n else 1


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", nargs="?")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--no-ask", action="store_true", help="build the evidence and use cached answers only (free)")
    ap.add_argument("--min-conf", type=float, default=0.6)
    ap.add_argument("--effort", default="medium", choices=["low", "medium", "high"],
                    help="the model's reasoning effort (medium found every fixture's flags at half the cost of high, 2026-10-21)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--first-pass", default="auto", choices=["auto", "on", "off"],
                    help="with --repair: screen with the local model first (auto: config/local_vision.json first_pass)")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.effort, a.min_conf)
    if not a.scene:
        ap.error("give a scene")
    spec, plate_name, pd = load(a.scene)
    if not has_weather(spec):
        print(f"outdoor_check: {a.scene} draws no weather; nothing to check")
        return 0
    if not (pd / "lights.png").exists() or not (pd / "plate.png").exists():
        print(f"outdoor_check: no plate masks in {pd}")
        return 2
    print(f"outdoor_check: {a.scene} (tiles at 1:1, the weather's area in magenta)")
    lv, ours, screen = None, False, None
    if a.repair and not a.no_ask and first_pass(a.first_pass):
        try:
            lv = llama
            ours = lv.serve()
            screen = "local"
            print(f"outdoor_check: first passes on the local model ({local_name()}); Azure confirms what it flags and has "
                  "the last look at every tile")
        except Exception as e:   # noqa: BLE001  (no setup on this machine, or the server didn't start)
            print(f"outdoor_check: no local first pass ({e}); Azure checks every tile")
            lv = None
    all_cuts = None
    rounds = 0
    try:
        state, flags, usd, (plate, area, beads) = check(a.scene, not a.no_ask, a.min_conf, effort=a.effort, screen=screen)
        final = screen is None
        while True:
            if not flags and not final:
                # the local rounds are done: from here on Azure alone, with its own rounds (what it finds now, the
                # local model missed, so screening those tiles again would only cost a round)
                print(f"\n== final pass: Azure on every tile ({state['screened_clean']} the local model called clean; "
                      "answers Azure gave for a tile as it is now are reused)")
                if lv and ours and lv.up(lv.cfg()):
                    lv.stop()
                screen, rounds = None, 0
                state, flags, c, (plate, area, beads) = check(a.scene, True, a.min_conf, effort=a.effort)
                usd += c
                final = True
            if not flags or not a.repair or rounds >= a.rounds:
                break
            rounds += 1
            pj = json.loads((pd / "plate.json").read_text(encoding="utf-8")) if (pd / "plate.json").exists() else {}
            cell = (pj.get("pixel") or {}).get("cell")
            print(f"\n== repair round {rounds}: {len(flags)} thing(s) under the weather")
            if lv and lv.up(lv.cfg()):
                lv.stop()          # SAM needs the GPU memory the local model holds (8.5 of the card's 12 GB)
            cuts, names = repair(a.scene, flags, area, cell)
            if not names:
                break
            all_cuts = cuts if all_cuts is None else (all_cuts | cuts)
            r = subprocess.run([PY, str(ROOT / "tools" / "new_video.py"), "prep", a.scene, "--masks-only"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print((r.stdout or "")[-2000:] + (r.stderr or "")[-2000:])
                print("outdoor_check: plate_prep --masks-only failed")
                return 2
            if screen:
                try:
                    ours = lv.serve() or ours
                except Exception as e:   # noqa: BLE001
                    print(f"outdoor_check: the local model didn't come back ({e}); Azure checks every tile from here")
                    screen = None
            state, flags, c, (plate, area, beads) = check(a.scene, True, a.min_conf, effort=a.effort, screen=screen)
            usd += c
            final = screen is None
    except Exception as e:   # noqa: BLE001  (the model or the network)
        print(f"outdoor_check: could not ask the model: {e}")
        return 2
    finally:
        if lv and ours and lv.up(lv.cfg()):
            lv.stop()
    preview(pd, plate, area, flags, all_cuts)
    n = len(state["tiles"])
    print(f"\noutdoor_check: {'PASS' if state['pass'] else 'FAIL'}: {n} tile(s), {len(flags)} thing(s) under the weather"
          + (f", {len(state['missing'])} not asked" if state["missing"] else "") + f", ~${usd:.2f} of Azure this run"
          + f" -> {pd / 'outdoor_check' / 'outdoor_check.jpg'}")
    report(flags, state["missing"])
    return 0 if state["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
