"""The visual critic: the "eye" checks of the lessons, judged by the vision model on evidence cut from a render.

Truman reviewed every early render frame by frame, and each thing he flagged is a row in
.agents/skills/new-video/references/lessons.md. Most rows have an automatic check (tools/review.py); the rest
needed someone to look ("eye:"). This tool does that looking: it cuts the evidence each eye check needs from a
render (steam crops a fraction of a second apart, the pet, the gaps between near objects' legs, the rain, the
opening line, the event contact sheets, the key art, the thumbnails), shows it to the vision model next to an
approved reference from a published video, with his own words about what went wrong before, and gets back
pass or fail with the problems it sees. A failure goes back to the agent to fix before anything is shown to him
(the evaluator-optimizer loop; DECISIONS 2026-10-21).

  .venv\\Scripts\\python tools\\critic.py <scene> --render out\\<scene>\\render\\<tag> [--only steam,pet,...]
      [--refs assets\\reference\\approved\\<scene>] [--no-ask] [--min-conf 0.6]
  .venv\\Scripts\\python tools\\critic.py <scene> --render <approved render> --approve [--note "his words"]
      after Truman approves: its passing evidence becomes the scene's approved references (--refs for later scenes of
      the look; anything a set lacks falls back to the ramen alley's)

Checks (each one or more judgments; skipped when the scene has nothing to judge):
  keyart   painted steam, smoke, flames or hanging drops left in the picture; animals besides the pet; people; text; the pet asleep
  steam    every vessel: a soft haze from the whole surface (no box edge, no separate wisps, not heavy)
  pet      nothing rains or drips on the pet, it keeps its size
  gaps     rain falls and lands between a near object's legs (gaps.png), the legs themselves stay dry
  rain     upright, only in the open, finer and dimmer far away
  frames   doors, then every part of the frame where weather draws (outdoor_check's tiles, most edge first; six crops
           at 1:1): no rain over frames, mullions, a handle, a sill, a lamp or a plant in front of the glass
  opening  the opening line readable, centered, in the first seconds
  events   every event contact sheet (critter, ant, birds, perch, boat, moth...): sits on surfaces, comes and goes
           behind things, stays visible near poles
  thumbs   every thumbnail at phone size: each line readable, 4K and 10 HR on it
Writes <render>/critic/: the evidence JPEGs, critic.json and critic.md. Exit 1 when a check fails with at least
--min-conf confidence. --no-ask builds the evidence only (free; look at it yourself).

Cost: one vision call per judgment, about $0.01 to $0.03 each (out/azure_usage.jsonl). A 5 minute sample is
usually 8 to 15 judgments.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT, config
from cozy.media import grab_frame, probe as media_probe
W, H = 3840, 2160
REFS = ROOT / "assets" / "reference" / "approved" / "ramen-alley"
KEYART_NOTE = ""     # set per scene in main(): what the code animates in place (animated_in_place)
OPENING_NOTE = ""    # set per scene in main(): where intro_title.py slid the line to clear a character (L147)
DEFAULT_REFS = REFS


def ref(name):
    """An approved reference crop: from --refs when it has one by that name, else the ramen alley's (published)."""
    p = REFS / name
    return p if p.exists() else DEFAULT_REFS / name


def approve(scene, render, note):
    """After Truman approves a sample or a video: the evidence of every check that passed becomes an approved
    reference of this scene (assets/reference/approved/<scene>/, under the name of the reference it was judged
    against), so later scenes of the look can be judged against his OKs too (--refs)."""
    import datetime as dt
    cj = pathlib.Path(render) / "critic" / "critic.json"
    if not cj.exists():
        sys.exit(f"no {cj}: run the critic on the approved render first")
    rows = json.loads(cj.read_text(encoding="utf-8"))["results"]
    out = ROOT / "assets" / "reference" / "approved" / scene
    out.mkdir(parents=True, exist_ok=True)
    ip = out / "index.json"
    idx = json.loads(ip.read_text(encoding="utf-8")) if ip.exists() else {"source": "", "refs": {}}
    idx["source"] = f"{pathlib.Path(render).relative_to(ROOT).as_posix()} (approved {dt.date.today().isoformat()})"
    n = 0
    for r in rows:
        v = r.get("verdict") or ("PASS" if r.get("pass") and (r.get("confidence") or 0) >= 0.5 else "")
        if v != "PASS" or not r.get("evidence"):
            continue
        name = pathlib.Path(r["reference"]).name if r.get("reference") else \
            f"{r['check']}__{''.join(ch if ch.isalnum() else '_' for ch in r['label'].lower())[:40]}.jpg"
        if (out / name).exists() and name in {v.get("file") for v in idx["refs"].values() if v.get("render") == str(render)}:
            continue                                   # one per reference name from this render
        im = Image.open(r["evidence"][0]).convert("RGB")
        s = min(1.0, 1600 / max(im.size))
        im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS).save(out / name, quality=88)
        idx["refs"][pathlib.Path(name).stem] = {"file": name, "label": r["label"], "lessons": r.get("lessons"),
                                                "render": str(render), "note": note or ""}
        n += 1
    ip.write_text(json.dumps(idx, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"approved: {n} references -> {out}")
    return 0
CHANNEL = ("a YouTube channel of 10-hour cozy ambience videos to study, work or sleep to: one painted key-art image per "
           "scene, animated in code (rain, rain on the ground, steam from a fluid simulation, drips, small creatures, birds, "
           "lights, a sleeping pet that only breathes), with a locked camera. The owner wants it to look real and hand-made, "
           "calm but alive, never like obvious AI or cheap overlays")


# ---------------------------------------------------------------- evidence

def duration(video):
    return float(media_probe(video, "format=duration", check=False).get("format", {}).get("duration") or 0)


def grab(video, t, box=(0, 0, 1, 1)):
    """One frame at t s, cropped to box (frame fractions), as a PIL image at 1:1."""
    x0, y0 = int(box[0] * W) // 2 * 2, int(box[1] * H) // 2 * 2
    x1, y1 = int(min(1, box[2]) * W) // 2 * 2, int(min(1, box[3]) * H) // 2 * 2
    w, h = max(2, x1 - x0), max(2, y1 - y0)
    raw = grab_frame(video, f"{max(0.0, t):.3f}", frames=1, vf=f"crop={w}:{h}:{x0}:{y0},format=rgb24", check=False)
    if len(raw) != w * h * 3:
        return Image.new("RGB", (w, h))
    return Image.fromarray(np.frombuffer(raw, np.uint8).reshape(h, w, 3))


def strip(ims, labels=None, max_w=560, gap=8):
    """Images side by side (each at most max_w wide), with small labels."""
    ims = [im.resize((max(1, round(im.width * min(1, max_w / im.width))), max(1, round(im.height * min(1, max_w / im.width)))),
                     Image.LANCZOS) for im in ims]
    hh = max(im.height for im in ims)
    out = Image.new("RGB", (sum(im.width for im in ims) + gap * (len(ims) - 1), hh + 20), (18, 18, 18))
    d = ImageDraw.Draw(out)
    x = 0
    for i, im in enumerate(ims):
        out.paste(im, (x, 20))
        if labels:
            d.text((x + 4, 4), labels[i], fill=(255, 220, 0))
        x += im.width + gap
    return out


def grow(b, f, min_w=0.0, aspect=None):
    x0, y0, x1, y1 = b
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * (1 + f), (y1 - y0) * (1 + f)
    w = max(w, min_w)
    if aspect:
        h = max(h, w * W / H / aspect)
    return [max(0, cx - w / 2), max(0, cy - h / 2), min(1, cx + w / 2), min(1, cy + h / 2)]


class Ctx:
    def __init__(self, scene, render):
        self.scene, self.render = scene, pathlib.Path(render)
        self.video = self.render / "master.mp4"
        self.dur = duration(self.video)
        self.spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
        self.plate = self.spec.get("plate", scene)
        pd = ROOT / "out" / "plates" / self.plate
        self.pdir = pd
        self.regions = json.loads((pd / "regions.json").read_text(encoding="utf-8")) if (pd / "regions.json").exists() else []
        bp = ROOT / "scenes" / scene / "brief.json"
        self.brief = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
        self.layers = {L.get("type") for L in self.spec.get("layers", [])}
        self.out = self.render / "critic"
        self.out.mkdir(parents=True, exist_ok=True)

    def t(self, frac, lo=2.0):
        """A time at this fraction of the render, kept inside it."""
        return max(lo, min(self.dur - 2.0, self.dur * frac))

    def save(self, im, name):
        p = self.out / f"{name}.jpg"
        im.save(p, quality=88)
        return p


def ev_keyart(c):
    hero = ROOT / "assets" / "keyart" / c.scene / "clean.png"
    if not hero.exists() and c.brief.get("hero"):
        hero = ROOT / c.brief["hero"]
    if not hero.exists():
        return []
    im = Image.open(hero).convert("RGB")
    im.thumbnail((1600, 1600))
    return [("key art", [c.save(im, "keyart")], None)]


def animated_in_place(c):
    """What the code animates where it is painted (a lantern's small flame traced as a `flame` region, a fire played from
    its own clips): the key-art check must not fail those, it sees only the still (the pixel greenhouse's lantern
    flame failed it twice though it wavered and flickered, 2026-10-21)."""
    names = [g["name"].replace("_", " ") for g in c.regions if g["kind"] in ("flame", "fire")]
    return ("Animated in code where they are painted, so NOT frozen (do not fail these): " + ", ".join(names) + ". ") if names else ""


def ev_steam(c):
    out = []
    for g in [g for g in c.regions if g["kind"] == "steam"]:
        x0, y0, x1, y1 = g["bbox"]
        w = x1 - x0
        box = [max(0, x0 - 0.3 * w), max(0, y0 - 1.3 * w * W / H), min(1, x1 + 0.3 * w), y1]
        t0 = c.t(0.3)
        ims = [grab(c.video, t0 + k * 0.4, box) for k in range(4)]
        p = c.save(strip(ims, [f"+{k * 0.4:.1f} s" for k in range(4)]), f"steam_{g['name']}")
        rp = ref("steam_cup.jpg" if w < 0.1 else "steam_bowl.jpg")
        out.append((f"steam over {g['name'].replace('_', ' ')}", [p], rp))
    return out


def ev_pet(c):
    out = []
    for g in [g for g in c.regions if g["kind"] == "pet"]:
        box = grow(g["bbox"], 0.3)
        ims = [grab(c.video, c.t(f), box) for f in (0.15, 0.4, 0.7)]
        out.append((f"the pet ({g['name'].replace('_', ' ')})", [c.save(strip(ims, ["early", "middle", "late"]), f"pet_{g['name']}")],
                    ref("pet_dry.jpg")))
    return out


def ev_gaps(c):
    gp = c.pdir / "gaps.png"
    if not gp.exists() or "rain" not in c.layers:
        return []
    import cv2
    m = np.asarray(Image.open(gp).convert("L").resize((W // 4, H // 4)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats((m > 127).astype(np.uint8))
    comps = sorted([stats[i] for i in range(1, n) if stats[i][4] > 0.0004 * (W // 4) * (H // 4)], key=lambda s: -s[4])[:3]
    out = []
    for k, (x, y, w, h, _a) in enumerate(comps):
        b = [x / (W // 4), y / (H // 4), (x + w) / (W // 4), (y + h) / (H // 4)]
        box = grow(b, 0.8, min_w=0.14, aspect=16 / 10)
        t0 = c.t(0.35)
        ims = [grab(c.video, t0 + j * 0.3, box) for j in range(3)]
        out.append((f"the gaps of a near object ({k + 1})", [c.save(strip(ims, [f"+{j * 0.3:.1f} s" for j in range(3)]), f"gaps_{k + 1}")],
                    ref("stool_gaps_rain.jpg")))
    return out


def ev_rain(c):
    if "rain" not in c.layers:
        return []
    t0 = c.t(0.5)
    full = grab(c.video, t0)
    full.thumbnail((1600, 1600))
    op = next((g["bbox"] for g in c.regions if g["kind"] == "opening"), [0.2, 0.15, 0.8, 0.85])
    left = [op[0], (op[1] + op[3]) / 2 - 0.15, op[0] + 0.25, (op[1] + op[3]) / 2 + 0.1]
    right = [op[2] - 0.25, (op[1] + op[3]) / 2 - 0.15, op[2], (op[1] + op[3]) / 2 + 0.1]
    crops = strip([grab(c.video, t0, left), grab(c.video, t0, right)], ["left, 1:1", "right, 1:1"], max_w=800)
    return [("the rain", [c.save(full, "rain_full"), c.save(crops, "rain_crops")], ref("full_frame_strike.jpg"))]


def ev_frames(c):
    """Rain stops at a window's frame, a door's stiles and its handle (user 2026-10-21, the pixel greenhouse: rain over the
    door and its handle, a request he had made before). The rain check's crops sit at
    an opening's sides and a glass room has none, so they never showed the door. Doors first, then the parts of the
    frame where weather draws (tools/outdoor_check.py's tiles), those with the most edge of that area first: with only
    the door and the two largest panes, the rain over the plants by the lantern went to Truman again (v6, 2026-10-21).
    At most six crops."""
    if "rain" not in c.layers:
        return []
    import cv2
    import outdoor_check as OC
    out, seen = [], []

    def add(box, label, name):
        t0 = c.t(0.45)
        ims = [grab(c.video, t0 + j * 0.5, box) for j in range(2)]
        out.append((label, [c.save(strip(ims, [f"+{j * 0.5:.1f} s, 1:1" for j in range(2)], max_w=900), f"frames_{name}")], None))
        seen.append(box)

    def overlap(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy / max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))

    for g in [g for g in c.regions if g["kind"] in ("glass", "opening") and "door" in g["name"]]:
        box = grow(g["bbox"], 0.25, min_w=0.12, aspect=4 / 3)
        if not any(overlap(box, b) > 0.5 for b in seen):
            add(box, f"rain at the frames of {g['name'].replace('_', ' ')}", g["name"])
    if (c.pdir / "lights.png").exists():
        area, _ = OC.weather_area(c.spec, c.pdir)
        edge = area & ~cv2.erode(area.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        rows, cols = ["top", "upper middle", "lower middle", "bottom"], ["left", "left of center", "right of center", "right"]
        for key, (x0, y0, x1, y1) in sorted(OC.tiles(area), key=lambda t: -int(edge[t[1][1]:t[1][3], t[1][0]:t[1][2]].sum())):
            if len(out) >= 6:
                break
            box = [x0 / W, y0 / H, x1 / W, y1 / H]
            if any(overlap(box, b) > 0.5 for b in seen):
                continue
            add(box, f"rain at the glass and what stands in front of it ({rows[int(key[0])]}, {cols[int(key[1])]})", f"tile_{key}")
    return out


def ev_opening(c):
    if not c.spec.get("intro"):
        return []
    ij = c.pdir / "intro.json"
    if ij.exists():                                  # the line's own box and timing (tools/intro_title.py): judge it at 1:1
        j = json.loads(ij.read_text(encoding="utf-8"))
        x0, y0, x1, y1 = j["box"]
        tm = j["timing"]
        shown = tm["at"] + tm["fade_in"]
        ts = [shown + 0.4, shown + tm["hold"] / 2, shown + tm["hold"] - 0.4, shown + tm["hold"] + tm["fade_out"] + 0.8]
        box = grow([x0 / W, y0 / H, x1 / W, y1 / H], 0.25)
        crops = strip([grab(c.video, t, box) for t in ts if t < c.dur], [f"{t:.1f} s, 1:1" for t in ts], max_w=760)
        full = grab(c.video, shown + tm["hold"] / 2)
        full.thumbnail((1280, 1280))
        return [("the opening line", [c.save(crops, "opening_crops"), c.save(full, "opening_full")], ref("intro_title.jpg"))]
    ts = [1.5, 4.0, 7.0, 10.5, 13.0]
    ims = [grab(c.video, t) for t in ts if t < c.dur]
    return [("the opening seconds", [c.save(strip(ims, [f"{t:g} s" for t in ts], max_w=760), "opening")], ref("intro_title.jpg"))]


EVENT_Q = {
    "critter": "a small creature (snail, beetle...) crawling, shown at five moments along its path including the last tenth: it sits ON a surface (never floating above it, never crawling up a wall), its shadow and trail flat on that surface, and at the end of its path it goes out of sight behind something (it never pops out of existence in plain view). Walking near a step's edge is fine",
    "critter (under way)": "a small creature (snail, beetle...) crawling, shown at moments while it is under way: its walk began before this sample and ends after it, so neither end is shown and the crop's edge is not where it leaves. Judge only that it sits ON a surface (never floating above it, never crawling up a wall) with its shadow and trail flat on that surface",
    "ant (under way)": "an ant walking on a counter, shown at moments while it is under way: its walk began before this sample or ends after it, so its ends are not shown. Judge only that it stays on the surface and looks like a small ant, not a sticker",
    "ant": "an ant walking on the counter, shown at five moments including the last tenth of its walk: it stays on the surface, and at the end it walks over the counter's far edge so the counter hides it (front first), rather than sinking into the wood or vanishing in the middle of the surface",
    "birds": "birds flying across: flapping or gliding on curves (never a stiff straight vector), drawn in front of thin poles and wires that are farther away (never vanishing next to a pole), big enough to read",
    "perch": "birds landing and sitting on a wire: they sit ON the wire, at a plausible size, and arrive and leave by flying",
    "boat": "a boat on the water: it passes behind near things correctly, the water's reflections are not drawn over the boat, it moves along the water",
    "moth": "a moth near a lamp: small, flutters near the light, not a sticker on top of the picture",
    "heron": "a large bird crossing: flaps, curves, readable",
    "petals": "petals falling from a tree: drift and tumble, sized for their distance",
    "lightning": "a lightning strike: a soft glow lighting the sky and the scene, not a harsh strobe",
}


def along(pts, f):
    """The point at fraction f of a polyline's length."""
    seg = [((pts[i][0] - pts[i - 1][0]) ** 2 + ((pts[i][1] - pts[i - 1][1]) * H / W) ** 2) ** 0.5 for i in range(1, len(pts))]
    goal = max(0.0, min(1.0, f)) * (sum(seg) or 1.0)
    for i, s in enumerate(seg):
        if goal <= s or i == len(seg) - 1:
            u = 0 if s == 0 else min(1.0, goal / s)
            return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u]
        goal -= s
    return list(pts[-1])


def tight_box(c, kind, e, tv, t0):
    """For the small signature creatures, a tight crop around where they are at video time tv: the ant along its path,
    the critter along its route. None for other kinds (their event boxes are used)."""
    layer = next((L for L in c.spec.get("layers", []) if L.get("type") == kind), None)
    if not layer:
        return None
    f = (tv + t0 - e["t"]) / max(float(e.get("dur", 1.0)), 1e-3)
    if kind == "ant" and layer.get("paths"):
        pts = layer["paths"][int(e.get("path", 0)) % len(layer["paths"])]
        p = along(pts if e.get("fwd", 1) else pts[::-1], f)
    elif kind == "critter" and layer.get("path"):
        a, b = float(e.get("from", 0)), float(e.get("to", 1))
        p = along(layer["path"], a + (b - a) * f)
    elif kind == "moth" and layer.get("center"):
        # the moth is ~10-16 px: around its lamp, a few lamp units each way (moth.js `unit`)
        u = float(layer.get("unit", 32)) / W
        cx, cy = layer["center"]
        return [max(0.0, cx - 5 * u), max(0.0, cy - 4 * u * W / H), min(1.0, cx + 5 * u), min(1.0, cy + 4 * u * W / H)]
    elif kind == "perch" and layer.get("perches"):
        pts = [q for pr in layer["perches"] for q in pr["pts"]]
        x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
        y0, y1 = min(q[1] for q in pts), max(q[1] for q in pts)
        return [max(0.0, x0 - 0.01), max(0.0, y0 - 0.03), min(1.0, x1 + 0.01), min(1.0, y1 + 0.015)]
    else:
        return None
    w = 0.07
    return [p[0] - w / 2, p[1] - w * W / H * 0.32, p[0] + w / 2, p[1] + w * W / H * 0.32]


def ev_events(c):
    """Each kind's first two occurrences, cropped where they play (the same boxes and moments as tools/event_sheets.py),
    at a size the model can judge: one row per occurrence, four moments across it. The ant and the critter are cropped
    tightly around where they are at each moment and shown at twice their size."""
    import event_sheets as ES
    plans, (_v, t0, *_rest) = ES.plan(c.render, list(EVENT_Q), max_n=2)
    out = []
    for kind, (count, rows) in sorted(plans.items()):
        if kind not in EVENT_Q:
            continue
        strips = []
        partial = False
        for label, cells, e in rows:
            if kind in ("ant", "critter"):            # the path ends matter most (L28, L49): early, middle and the last tenth
                d = max(float(e.get("dur", 1.0)), 1e-3)
                pick = [(f"{f:.0%}", e["t"] - t0 + f * d, cells[0][2] if cells else [0, 0, W, H]) for f in (0.04, 0.5, 0.86, 0.93, 0.985)]
                pick = [p for p in pick if 0 <= p[1] < c.dur - 0.1]     # an event can outlast a short sample
                if len(pick) < 3:                     # under way when the sample starts, or past its end: what shows
                    a, b = max(0.0, e["t"] - t0), min(c.dur - 0.1, e["t"] - t0 + d)
                    pick = [(f"{(a + (b - a) * k / 3 + t0 - e['t']) / d:.0%}", a + (b - a) * k / 3, cells[0][2] if cells else [0, 0, W, H])
                            for k in range(4)] if b > a else pick
                    partial = True
            else:
                pick = cells if len(cells) <= 4 else [cells[i] for i in (0, len(cells) // 3, 2 * len(cells) // 3, len(cells) - 1)]
            ims = []
            for _cap, tv, box in pick:
                tb = tight_box(c, kind, e, tv, t0)
                im = grab(c.video, tv, tb or [b / s for b, s in zip(box, (W, H, W, H))])
                ims.append(im.resize((im.width * 2, im.height * 2), Image.LANCZOS) if tb else im)
            strips.append(strip(ims, [cap + (", 2x" if kind in ("ant", "critter", "moth", "perch") else "") for cap, _t, _b in pick], max_w=520))
        if not strips:
            continue
        sheet = Image.new("RGB", (max(s.width for s in strips), sum(s.height + 8 for s in strips)), (18, 18, 18))
        y = 0
        for s in strips:
            sheet.paste(s, (0, y))
            y += s.height + 8
        out.append((f"event: {kind}" + (" (under way)" if partial and f"{kind} (under way)" in EVENT_Q else ""),
                    [c.save(sheet, f"event_{kind}")], None))
    return out


def ev_thumbs(c):
    td = ROOT / "out" / c.scene / "thumbnails"
    th = sorted(td.glob("*_1280.jpg")) if td.exists() else []
    if not th:
        return []
    th = th[:12]
    cols, tw, thh = 4, 360, 202
    sheet = Image.new("RGB", (cols * (tw + 10), ((len(th) + cols - 1) // cols) * (thh + 24)), (15, 15, 15))
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(th):
        x, y = (i % cols) * (tw + 10), (i // cols) * (thh + 24)
        sheet.paste(Image.open(p).convert("RGB").resize((tw, thh), Image.LANCZOS), (x, y + 20))
        d.text((x + 2, y + 4), p.name.replace("_1280.jpg", ""), fill=(200, 200, 200))
    return [("the thumbnails at phone size", [c.save(sheet, "thumbs_phone")], None)]


# ---------------------------------------------------------------- rubric

# A scene with the channel's own cast (brief "cast", config/cast.json; Truman 2026-10-25: original creatures, awake
# doing something quiet, breathing and blinks drawn in code): several characters, awake and upright, are the design.
CAST = ""
CAST_NAMES = ""
CAST_Q = {
    "keyart": ("the key art, before animation. The scene's characters are the channel's own creatures, painted on purpose "
               "and AWAKE by the owner's decision (2026-10-25): {cast}. FAIL if any steam, smoke, flame or hanging water "
               "drop is PAINTED into the picture (they must be removed and animated: a painted one sits frozen), if any OTHER "
               "animal is painted in (a snail, an insect, a bird, a frog: the code animates its own), if any person or human "
               "silhouette appears, if there are letters, words, numbers or a brand logo, or if a character is cut off, "
               "malformed, or missing a part of its description (a part its own pose hides, a far wing behind its body or a "
               "far leg, is not missing). Small differences from the wording in how a part is drawn (a shine in the eyes, "
               "the length of horns, the texture of skin) are not failures: the owner approved this painting. Open eyes and "
               "upright poses are intended. Also note if the image looks flat or plain rather than detailed, warm and hand-made."),
    "pet": ("one of the scene's characters at a few moments (two or more panels). The characters are the channel's own "
            "creatures, AWAKE by the owner's decision (2026-10-25), doing something quiet; open eyes, an upright pose and "
            "holding things are intended: {names}. They only breathe and blink. Their design (eyes, horns, skin, colors) is "
            "the painting the owner approved: do not judge it here. FAIL if rain streaks, drips or splashes touch the "
            "character or what it holds (rain falling behind and around it is right), if it changes size or shape between "
            "the moments, or if it looks pasted on."),
}


def cast_desc(brief, names=False):
    """The scene's characters for the cast rubrics ("" when the scene has no cast): their whole descriptions, or with
    `names` only what they are (the words before the description's colon). The pet check judged the approved painting
    against the descriptions' wording ("a glossy eye, not a tiny matte dot", the Burdock Shelter, L145)."""
    ids = (brief or {}).get("cast") or []
    if not ids:
        return ""
    cast = config("cast")["cast"]
    if names:
        return "; ".join(cast[i]["prompt"].split(":")[0].strip() for i in ids if i in cast)
    return "; ".join(cast[i]["prompt"].rstrip(".") for i in ids if i in cast)


CHECKS = {
    "keyart": (ev_keyart, ["L03", "L06", "L07", "L60", "L71"],
               "the key art, before animation. FAIL if any steam, smoke, flame or hanging water drop is PAINTED into the picture "
               "(they must be removed and animated: a painted one sits frozen), if any animal besides the one sleeping pet is "
               "painted in (a snail, an insect, a bird, a frog: the code animates its own, a painted one sits frozen), if any "
               "person or human silhouette appears, if "
               "there are letters, words, numbers or a brand logo, or if the pet is awake, cut off or missing its ears or tail. "
               "A sign or neon with a simple picture (a bowl, a cat face, a moon) is fine and intended. Also note if the image "
               "looks flat or plain rather than detailed, warm and cinematically lit."),
    "steam": (ev_steam, ["L06", "L12", "L18", "L25", "L32", "L35"],
              "the steam over a hot bowl or cup, a few frames 0.4 s apart. It must rise from the WHOLE surface of the vessel as "
              "a soft, translucent, subtle haze that curls a little and fades out within about a vessel width, like the approved "
              "reference. FAIL if: a straight edge or box outline is visible; it comes from a few separate points, streams or thin "
              "wisps (two or more distinct sources); it is a heavy, opaque cloud; it bends back down; part of the surface has none; "
              "or there is no visible steam at all."),
    "pet": (ev_pet, ["L10", "L19", "L31"],
            "the sleeping pet at a few moments (two or more panels). FAIL if rain streaks, drips or splashes touch the pet or its "
            "cushion or stool top, "
            "if it changes size or shape between the moments (it only breathes), or if it looks pasted on."),
    "gaps": (ev_gaps, ["L02", "L24", "L33", "L57"],
             "a near object with gaps (stool or chair legs, railing balusters), a few frames apart. Through the gaps, rain must "
             "keep falling and landing on the wet ground behind, like the approved reference. FAIL if a gap area looks dry or "
             "rain stops at a box-shaped boundary, or if rain streaks run down the object's own legs or rails."),
    "rain": (ev_rain, ["L01", "L11", "L14", "L36", "L37"],
             "the rain: a full frame and two 1:1 crops. Rain falls nearly upright (a few degrees of lean at most), clumpy and "
             "irregular, finer and dimmer in the distance, lit by the scene. Rain falling in the open street or air between the "
             "camera and a building across the way is correct: buildings, roofs, walls, lanterns, steps and trees out in the "
             "open (across a garden, a pond or a street) stand in the rain, and only the room or veranda the camera stands in "
             "and what is under its roof stay dry. FAIL only if streaks are slanted more than a few degrees or "
             "nearly horizontal, if rain falls where a roof directly above would stop it (under the awning or roof the camera "
             "sits under, inside a room, on the counter or table), if the rain stops at the outline of a building, lantern or "
             "tree out in the open (a dry hole in its shape), or if the far rain looks big and heavy next to the reference. "
             "The characters (pets and creatures) and whatever they hold stay dry by design, even standing out in the rain: "
             "never fail rain stopping at a character's or its lantern's outline."),
    "frames": (ev_frames, ["L57", "L92", "L100"],
               "a window, a door or a stretch of glass seen at 1:1, two moments half a second apart. Rain (falling streaks, "
               "splashes, drops) may show only where the outside is seen through the glass or the opening. FAIL if rain "
               "streaks or splashes are drawn over the solid parts: the window or door frame, mullions and muntins, the "
               "door's handle, a sill, a post, a lamp, or a plant, its leaves or a vine standing in front of the glass "
               "inside the room. Name the part. Rain on the glass itself (beads, trickles) is intended."),
    "opening": (ev_opening, ["L04", "L55"],
                "the opening line of text, at 1:1 over its first seconds, and a full frame for where it sits. The crops are "
                "exactly where the line is placed, so if none of the first three crops shows any text, the line is missing. "
                "It is a quiet welcome centered in the middle of the screen, each line centered (the owner asked for that "
                "on 2026-10-21; earlier videos put it low); it may sit somewhat above or below the exact middle to stay "
                "clear of a character (2026-10-25). FAIL if it is missing, illegible at 1:1, clearly off center sideways, "
                "low in the frame like a subtitle, on top of the pet or a character, or still visible in the last crop "
                "(about 12 s)."),
    "events": (ev_events, ["L16", "L20", "L23", "L28", "L40", "L41", "L42", "L49"],
               "one kind of event: each row is one occurrence, cropped to where it plays, with four moments across it (the "
               "creature can be small: look closely). Judge: {what}. FAIL only for a problem visible in the rows."),
    "thumbs": (ev_thumbs, ["L47", "L64", "L65"],
               "the video's thumbnails at phone size. FAIL if a thumbnail's text line is hard to read against what is right "
               "behind it (color too close to the background), or a thumbnail lacks 4K or the length (10 HR). Name the thumbnail."),
}


def lesson_lines(ids):
    import review
    rows = {r["id"]: r for r in review.lessons()}
    return "\n".join(f"- {i}: he saw: {rows[i]['saw']} | what the pipeline does now: {rows[i]['fix']}" for i in ids if i in rows)


def judge(label, images, ref, check, ids, scene, effort="medium"):
    from azure_ai import vision_json
    q = CHECKS[check][2]
    if CAST and check in CAST_Q:
        q = CAST_Q[check].format(cast=CAST, names=CAST_NAMES)
    if check == "keyart" and KEYART_NOTE:
        q = KEYART_NOTE + q
    if check == "opening" and OPENING_NOTE:
        q = OPENING_NOTE + q
    if check == "events":
        q = q.format(what=EVENT_Q.get(label.split(": ", 1)[-1], "a natural, physical motion that sits in the picture"))
    n = len(images)
    refs = [ref] if ref and pathlib.Path(ref).exists() else []
    channel = CHANNEL.replace("a sleeping pet that only breathes", "the channel's own small made-up creatures, awake doing "
                              "something quiet, that only breathe and blink") if CAST else CHANNEL
    prompt = (f"You review renders for {channel}.\n\nJudge {label}. The first {n} image{'s are' if n > 1 else ' is'} the candidate"
              + (". The last image is an APPROVED reference cut from a published video of the channel: it shows what passing "
                 "looks like. Do not judge the reference." if refs else ".")
              + f"\n\nWhat to check: {q}\n\nWhat the owner flagged in earlier videos (his words, and what is expected now):\n"
              f"{lesson_lines(ids)}\n\nFail only for a problem you can actually see in the candidate. If the candidate does not "
              "show the thing well enough to judge (cropped out, too dark, too small), pass with confidence below 0.5 and say "
              "so. Answer as JSON: {\"pass\": true|false, \"confidence\": 0.0-1.0, \"problems\": [\"concrete, with where in the "
              "image\"], \"fix\": \"one sentence: what to change\", \"seen\": \"what you see, briefly\"}")
    res, usage = vision_json(prompt, images=[*images, *refs], purpose=f"critic:{scene}:{check}", effort=effort, max_side=1600)
    return res, usage.get("usd_est", 0.0)


def verdict(label, images, ref, check, ids, scene, min_conf=0.6):
    """One judgment, and when it fails, two more: the failure stands only when two of the three fail. The judge is not
    consistent on borderline evidence (the farm porch's steam and rain passed at 0.83 and 0.87, then failed at 0.9 on
    the same frames, 2026-10-21); self-consistency over three samples is the research's fix. Returns (result, usd,
    votes note or "")."""
    res, usd = judge(label, images, ref, check, ids, scene)
    if not (res.get("pass") is False and (res.get("confidence") or 0) >= min_conf):
        return res, usd, ""
    votes = [res]
    for _ in range(2):
        r2, c2 = judge(label, images, ref, check, ids, scene)
        usd += c2
        votes.append(r2)
    bad = [v for v in votes if v.get("pass") is False and (v.get("confidence") or 0) >= min_conf]
    if len(bad) >= 2:
        return max(bad, key=lambda v: v.get("confidence") or 0), usd, f"{len(bad)} of 3 failed"
    good = [v for v in votes if v.get("pass")]
    best = max(good, key=lambda v: v.get("confidence") or 0) if good else min(votes, key=lambda v: v.get("confidence") or 0)
    return {**best, "seen": (best.get("seen") or "") + f" (1 of 3 judgments failed: {'; '.join(bad[0].get('problems') or [])})"}, usd, "1 of 3 failed"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--render", required=True, help="a render folder with master.mp4 (out/<scene>/render/<tag>)")
    ap.add_argument("--only", default="", help="comma list of checks: " + ", ".join(CHECKS))
    ap.add_argument("--refs", help="approved reference crops (default assets/reference/approved/ramen-alley)")
    ap.add_argument("--no-ask", action="store_true", help="build the evidence only")
    ap.add_argument("--min-conf", type=float, default=0.6, help="a failure counts from this confidence")
    ap.add_argument("--approve", action="store_true", help="Truman approved this render: save its passing evidence as this "
                    "scene's approved references (no model calls)")
    ap.add_argument("--note", help="with --approve: his words")
    a = ap.parse_args()
    global REFS
    if a.refs:
        REFS = pathlib.Path(a.refs)
    if a.approve:
        return approve(a.scene, pathlib.Path(a.render).resolve(), a.note)
    c = Ctx(a.scene, a.render)
    if not c.video.exists():
        sys.exit(f"no {c.video}")
    global KEYART_NOTE, CAST, CAST_NAMES, OPENING_NOTE
    KEYART_NOTE = animated_in_place(c)
    CAST = cast_desc(c.brief)
    CAST_NAMES = cast_desc(c.brief, names=True)
    ij = c.pdir / "intro.json"
    moved = (json.loads(ij.read_text(encoding="utf-8")).get("placement") or {}).get("moved_to") if ij.exists() else None
    if moved is not None:
        OPENING_NOTE = (f"On purpose, the line sits at {moved:.0%} of the frame's height instead of the exact middle: in the middle it "
                        "covered one of the scene's characters, so it slid up or down only as far as needed to clear them (the line "
                        "must never cover a character). Do not fail it for that. ")
    only = [x for x in a.only.split(",") if x] or list(CHECKS)
    results, usd = [], 0.0
    for check in only:
        build, ids, _q = CHECKS[check]
        for label, images, ref in build(c):
            row = {"check": check, "label": label, "lessons": ids, "evidence": [str(p) for p in images],
                   "reference": str(ref) if ref else None}
            if not a.no_ask:
                try:
                    res, cost, votes = verdict(label, images, ref, check, ids, a.scene, a.min_conf)
                    usd += cost
                    if votes:
                        row["votes"] = votes
                    row.update({k: res.get(k) for k in ("pass", "confidence", "problems", "fix", "seen")})
                except Exception as e:                               # a failed call is reported, never a silent pass
                    row.update({"pass": None, "error": str(e)[:300]})
            results.append(row)
            v = ("evidence" if a.no_ask else "ERROR" if row.get("pass") is None else "FAIL" if not row.get("pass")
                 else "UNSURE" if (row.get("confidence") or 0) < 0.5 else "PASS")
            row["verdict"] = v
            print(f"  {v:8s} {check:8s} {label}" + (f"  ({row.get('confidence')})" if row.get("confidence") is not None else "")
                  + "".join(f"\n           - {p}" for p in (row.get("problems") or []) if v != "PASS")
                  + (f"\n           seen: {row.get('seen')}" if v == "UNSURE" else ""))
    fails = [r for r in results if r.get("pass") is False and (r.get("confidence") or 0) >= a.min_conf]
    errors = [r for r in results if "error" in r]
    unsure = [r for r in results if r.get("verdict") == "UNSURE"]
    (c.out / "critic.json").write_text(json.dumps({"scene": a.scene, "render": str(c.render), "usd_est": round(usd, 4),
                                                   "results": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"# Critic: {a.scene}, {c.render.name}", "",
          f"{len(results)} judgments: {len(fails)} failed, {len(unsure)} unsure (the model couldn't see enough: look at that "
          f"evidence yourself), {len(errors)} errors, ~${usd:.2f}.", "",
          "| Result | Check | What | Problems, fix, or what it saw | Evidence |", "|---|---|---|---|---|"]
    for r in results:
        res = r.get("verdict", "evidence")
        probs = ("; ".join(r.get("problems") or []) + (f" Fix: {r['fix']}" if r.get("fix") and res == "FAIL" else "")
                 + (r.get("seen") or "" if res == "UNSURE" else "") + (r.get("error") or ""))
        md.append(f"| {res} {r.get('confidence') if r.get('confidence') is not None else ''} | {r['check']} | {r['label']} | "
                  f"{probs.replace('|', '/')} | {', '.join(pathlib.Path(p).name for p in r['evidence'])} |")
    (c.out / "critic.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\ncritic: {len(results)} judgments, {len(fails)} failed (confidence >= {a.min_conf}), {len(unsure)} unsure, "
          f"{len(errors)} errors, ~${usd:.2f} -> {c.out / 'critic.md'}")
    return 1 if (fails or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
