"""One review of a scene before anything is shown to Truman: every automatic check, then the list of things to
look at with the files to open. Built from the lessons file (.agents/skills/new-video/references/lessons.md):
every revision he ever asked for has a check there, so the same mistake is caught here instead of by him
(user 2026-10-19: remember every iteration, apply it automatically, and catch what slips through in a review).

  .venv/Scripts/python tools/review.py <scene> [--render out/<scene>/render/<tag>] [--clip <mp4>] [--skip-static]

Automatic:
  lint      scene.json against the lessons: no generated pet clips, fire clips for a fire, a simulated plume for
            every cup, bowl or pot with a measured opening (none forced to wisps), a liquid layer for a vessel, a
            signature detail in the brief, near hand regions dry,
            water that flows, what the plate offers (a tree, water, lamps) used by a layer, a loop period that holds
            every event type (L54), an intro line drawn in the look's font (L55), a music folder with 15+ tracks (L53)
  leak      tools/leak_check.py (no weather over the pet, food, candles)
  outdoor   tools/outdoor_check.py (the vision model on every tile of where the weather draws: nothing inside the room,
            no frame, no indoor water under it; cached per tile, so only changed tiles are asked, ~$0.02 each)
  weather   tools/weather_audit.py (dry pockets: gaps between legs or balusters without rain or rings; wet frames:
            rain over a window's frame, mullions or a door's handle)
  timeline  events per hour and the first minute (strong opening)
  render    qa.md PASS, event contact sheets, every event layer draws something alone on black, and where the rain
            moves (tools/rain_motion.py -> <render>/review/rain_motion.jpg, an eye check: L121) (with --render)
  static    tools/motion_review.py <clip> --static (with --clip, or the render's first 40 s with --render)
Exit 1 when an automatic check fails. The eye checks always print: do them before showing anything.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

from cozy.paths import ROOT, PY, config, creature_id, rel
from cozy.media import run_ffmpeg
LESSONS = ROOT / ".agents" / "skills" / "new-video" / "references" / "lessons.md"
DRY_KINDS = {"pet", "steam", "candle", "bob", "fire", "screen"}


def lessons():
    rows = []
    for line in LESSONS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (L\d+) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| ([^|]*) \|$", line)
        if m:
            rows.append({"id": m[1], "date": m[2].strip(), "saw": m[3].strip(), "fix": m[4].strip(), "check": m[5].strip()})
    return rows


def lint(scene):
    """Scene data against the lessons. Returns [(lesson id, ok, message)]."""
    sd, spec, plate, pd, regs, layers, types, ev = _lint_scene(scene)
    out = []
    _lint_pet_glass_fire(out, spec, regs, types, ev, pd)
    _lint_steam(out, regs, layers, pd)
    _lint_signature(out, sd, spec, pd, layers, types)
    _lint_critter_ends(out, scene)
    _lint_runoff(out, spec, pd, layers)
    _lint_straight_lines(out, scene, plate, pd, layers)
    _lint_fire_core(out, plate, pd, layers)
    hp, has_rain = _lint_plate_offers(out, spec, plate, regs, types)
    _lint_panes(out, spec, pd, regs, hp, has_rain)
    _lint_loop(out, spec, ev)
    _lint_intro(out, scene, spec, pd)
    _lint_music(out, scene)
    return out


def _lint_scene(scene):
    """(scene folder, scene.json, plate, plate folder, regions, enabled layers, their types, events)."""
    sd = ROOT / "scenes" / scene
    spec = json.loads((sd / "scene.json").read_text(encoding="utf-8"))
    plate = spec.get("plate", scene)
    pd = ROOT / "out" / "plates" / plate
    regs = json.loads((pd / "regions.json").read_text(encoding="utf-8")) if (pd / "regions.json").exists() else []
    regs = regs["regions"] if isinstance(regs, dict) else regs
    layers = [L for L in spec.get("layers", []) if L.get("enabled", True) is not False]
    types = {L["type"] for L in layers}
    ev = spec.get("events") or {}
    return sd, spec, plate, pd, regs, layers, types, ev


def _lint_pet_glass_fire(out, spec, regs, types, ev, pd):
    # L10: a painted pet only breathes
    bad = "pet" in types or bool(ev.get("petAct"))
    out.append(("L10", not bad, "generated pet clips in the scene (a `pet` layer or events.petAct)" if bad else "the pet only breathes"))
    # L102: no rain beads on the glass in a pixel look (each bead is one dark cell on the grid)
    if (spec.get("render") or {}).get("pixel") and "glass" in types:
        out.append(("L102", False, "a glass layer in a pixel look: its beads draw as dark specks on the grid; remove it (the glass stays clear)"))
    # L09: a fire plays clips of its own key art
    fires = [g for g in regs if g["kind"] == "fire"]
    if fires and "fire" in types:
        ok = (pd / "fire" / "fire.json").exists()
        out.append(("L09", ok, "fire clips ready" if ok else "a fire without clips: run new_video.py life"))


def _lint_steam(out, regs, layers, pd):
    # L25, L35: every vessel with a measured opening, cup or bowl, steams from a simulation of its whole surface
    vessels = [g for g in regs if g["kind"] == "steam" and g.get("opening") and g.get("opening_fit") in ("rim", "hand")]
    wide = [g for g in vessels if 2 * g["opening"][2] * 3840 > 300]
    per = next((L.get("per") or {} for L in layers if L["type"] == "steam"), {})
    for g in regs:
        if g["kind"] == "steam" and g not in vessels:
            out.append(("L35", None, f"{g['name']}: no measured opening, so it steams as a few wisps; if it is a cup or a bowl, "
                        "fit its rim (hand.json \"openings\") and run new_video.py life"))
    for g in vessels:
        if (per.get(g["name"]) or {}).get("mode") == "wisps":
            out.append(("L35", False, f"{g['name']}: forced to wisps (steam layer per.{g['name']}.mode), which read as separate "
                        "streams: remove the mode so it gets the simulated plume"))
        sj = pd / "steam" / g["name"] / "steam.json"
        ok = sj.exists()
        out.append(("L25", ok, f"{g['name']}: simulated plume" if ok else f"{g['name']}: no simulated plume, run new_video.py life"))
        if ok:
            # L32: no box edge (steam left at the saved box's edges) and no steam rolling back down
            sm = json.loads(sj.read_text(encoding="utf-8"))
            em, dn = sm.get("edge_max"), sm.get("down_max", sm.get("down_share"))
            good = em is not None and dn is not None and em <= 0.01 and dn <= 0.06
            out.append(("L32", good, f"{g['name']}: steam at the box edge {em}, moving down at most {dn}" if good else
                        f"{g['name']}: plume from an old steam_sim or it shows the box/rolls back (edge {em}, down {dn}): re-run new_video.py life --force"))
    # L26: a vessel the key art painted empty gets a drink
    liq = set()
    for L in layers:
        if L["type"] == "liquid":
            liq |= set(L.get("regions") or [])
    for g in regs:
        if g["kind"] == "steam" and g["name"] not in liq and g not in wide:
            out.append(("L26", None, f"{g['name']}: no liquid layer; if the cup looks empty at 1:1, add one (liquid.js)"))


def _lint_signature(out, sd, spec, pd, layers, types):
    # L29: a signature detail, and (L83) the scene really has it: the feature check dropped the pixel greenhouse's
    # ladybug and the Minecraft tea house's gecko (2026-10-21, 2026-10-22), and only the brief's words were checked
    brief = json.loads((sd / "brief.json").read_text(encoding="utf-8")) if (sd / "brief.json").exists() else {}
    sig = brief.get("signature_detail") or spec.get("signature_detail")
    out.append(("L29", bool(sig), f"signature detail: {sig}" if sig else "no signature detail (brief.json `signature_detail`): name the one odd little living thing only this video has"))
    fj = pd / "features.json"
    fsig = str((json.loads(fj.read_text(encoding="utf-8")) if fj.exists() else {}).get("signature") or "").strip().lower()
    if sig and fsig and not fsig.startswith("new"):
        kind, _, what = fsig.partition(":")
        if kind == "critter":
            have = [str(L.get("creature", "")).lower() for L in layers if L["type"] == "critter"]
            ok = creature_id(what) in {creature_id(h) for h in have}
            msg = (f"the signature {what.strip()} crawls (critter layer)" if ok else
                   f"the signature detail ({fsig}) is not in the scene (critters: {', '.join(have) or 'none'}): the feature check "
                   "dropped it; place it on its surface's top face with both ends hidden (L83), then --critter-occ and new_video.py life")
        else:
            ok = kind in types
            msg = f"the signature detail ({fsig}) has its layer" if ok else f"the signature detail ({fsig}) has no `{kind}` layer in scene.json"
        out.append(("L112", ok, msg))


def _lint_critter_ends(out, scene):
    # L144: every critter comes out from behind something standing and goes out of sight behind something standing.
    # critters.js only warns in the page log, which the render log drops: the Burdock Shelter's beetle faded in on open
    # moss and its snail melted into a patch of leaf litter SAM took for a cover, and every gate passed (2026-10-25)
    from critter_ends import check_scene
    for L, ends, flat in check_scene(scene):
        what = f"{L.get('creature', 'snail')} (track {L.get('track', 0)})"
        if ends:
            out.append(("L144", False, f"{what}: the path {' and '.join(ends)} is in plain sight, so it fades in or out on open ground: "
                        "move that end beside something standing (a rock, a pot, a plant) or past the frame's edge, then "
                        "analyze_plate.py --critter-occ"))
        if flat:
            out.append(("L144", False, f"{what}: covers at its path ends lie farther than the ground it walks on (flat ground it would "
                        f"melt into): {', '.join(f'{e} {a} px {d:+.3f}' for e, a, d in flat[:4])}; re-run analyze_plate.py --critter-occ "
                        "or move the end"))
        if not ends and not flat:
            out.append(("L144", True, f"{what}: both path ends hidden behind something standing or off the frame"))


def _lint_runoff(out, spec, pd, layers):
    # L149: runoff pours from an edge (dry above, open below), and a drips layer has drops to draw. The Burdock Shelter's
    # seven streams hung from a cover SAM had traced in open forest, and its drips layers drew nothing (2026-10-25)
    if (pd / "lights.png").exists() and (spec.get("runoff") or any(L["type"] == "drips" for L in layers)):
        import numpy as np
        from PIL import Image
        od = np.asarray(Image.open(pd / "lights.png").convert("RGB"))[..., 1] > 127
        Ho, Wo = od.shape
        air = []
        for s in spec.get("runoff") or []:
            x, y = int(s["x"] * Wo), int(s["y"] * Ho)
            # open view all the way up 40 px: nothing to pour from (the tea house's drops hang 10-20 px under its rafter
            # tails, which reads as hanging from them)
            win = od[max(0, y - int(40 * Ho / 2160)):max(1, y - int(2 * Ho / 2160)), max(0, x - 2):x + 3]
            if win.size and bool(win.all()):
                air.append(f"({s['x']:.3f}, {s['y']:.3f})")
        if spec.get("runoff"):
            out.append(("L149", not air, f"every runoff stream pours from an edge ({len(spec['runoff'])})" if not air else
                        f"runoff streams with open view right above them, pouring from the air: {', '.join(air[:5])}: remove them "
                        "(scene.json runoff) or move them under the real edge"))
        pj = pd / "plate.json"
        meta = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
        for L in layers:
            if L["type"] == "drips" and L.get("sources") is None and not meta.get("beads"):
                out.append(("L149", False, "a drips layer with no drops to draw (plate.json beads is empty): give the wet edges their drops "
                            "(a held leaf or cloth: \"drips\": true on its hand region) or remove the layer"))


def _lint_straight_lines(out, scene, plate, pd, layers):
    # L151: no straight line in the weather where the picture has none. The Burdock Shelter's rain stopped along the
    # side of the analysis's opening box, a straight vertical line through the moss and the wet ground (2026-10-25)
    if (pd / "lights.png").exists() and any(L["type"] == "rain" for L in layers):
        from mask_edges import check_plate, preview
        res = check_plate(pd)
        if res.get("rain") or res.get("rings"):
            preview(pd, res, pd / "mask_edges.jpg")

        def where(k):
            return ", ".join(f"{'vertical at x' if ax == 'x' else 'horizontal at y'} {at:.3f} ({'y' if ax == 'x' else 'x'} {s:.2f}..{e:.2f})"
                             for ax, at, s, e, _ in res.get(k, []))
        out.append(("L151", not res.get("rain"), "no straight line in the rain where the picture has none" if not res.get("rain") else
                    f"the rain stops at straight lines the picture doesn't have: {where('rain')} (tools/mask_edges.py {scene}): "
                    "trace the thing's own outline (SAM) instead of the box's edge"))
        if res.get("rings"):
            out.append(("L151", True, f"the rings end at straight lines, look at them (a far shore or a step may be right): "
                        f"{where('rings')} (out/plates/{plate}/mask_edges.jpg)"))


def _lint_fire_core(out, plate, pd, layers):
    # L153: the fire's center moves, not only its licks. The Burdock Shelter's clips kept the painted fan and amber body
    # still under moving licks (Truman, 2026-10-25: the center of the fire did not move at all)
    fj = pd / "fire" / "fire.json"
    if any(L["type"] == "fire" for L in layers) and fj.exists():
        from fire_clips import CORE_MIN
        fm = json.loads(fj.read_text(encoding="utf-8"))
        cf = {n: fm["clips"][n].get("core_flow") for n in fm.get("names", [])}
        lo = {n: v for n, v in cf.items() if v is None or v < CORE_MIN}
        out.append(("L153", not lo, f"the fire's center moves in every clip (core flow {', '.join(f'{v:.1f}' for v in cf.values())})"
                    if not lo else f"fire clips whose center holds still or was never measured: "
                    f"{', '.join(f'{n} {v}' for n, v in lo.items())} (needs {CORE_MIN}): tools/fire_clips.py {plate} auto"))


def _lint_plate_offers(out, spec, plate, regs, types):
    # L30: near hand regions of a dry kind must be cut from the weather
    hp = ROOT / "assets" / "keyart" / f"{plate}.hand.json"
    if hp.exists():
        for g in json.loads(hp.read_text(encoding="utf-8")).get("regions", []):
            if g.get("kind") in DRY_KINDS and g.get("near") and not g.get("dry"):
                out.append(("L30", False, f"hand region {g['name']} ({g['kind']}, near) without \"dry\": true"))
    # L13: water flows
    for g in regs:
        if g["kind"] == "water" and (spec.get("regions") or {}).get(g["name"], {}) is None:
            out.append(("L13", False, f"water region {g['name']} switched off in scene.json"))
    # L22: whatever the plate offers gets used
    offers = {"plant": ("petals", "a tree or plant: petals or leaves if it blossoms or sheds"), "water": ("boat", "open water: boats, fish, a heron"),
              "lamp": ("moth", "a lamp in the dark: a moth"), "lantern": ("drips", "lanterns: drops along their bottoms")}
    kinds = {g["kind"] for g in regs}
    for k, (layer, what) in offers.items():
        if k in kinds and layer not in types:
            out.append(("L22", None, f"the plate has {what}; no `{layer}` layer (fine if it does not fit)"))
    has_rain = "rain" in types
    if has_rain:
        for need, what in (("birds", "birds crossing the sky"), ("critter", "a small creature"), ("drips", "drops along the wet edges")):
            if need not in types:
                out.append(("L15", None, f"no {what} (`{need}` layer)"))
    return hp, has_rain


def _lint_panes(out, spec, pd, regs, hp, has_rain):
    # L79: the weather shows through every pane. The pixel greenhouse's panes were all cut out as near objects (no
    # outdoors at all: no rain, painted streaks never removed) and its side panes read as near in the depth (2026-10-21)
    if (has_rain or "snow" in json.dumps(spec.get("layers", []))) and (pd / "regions.png").exists() and (pd / "lights.png").exists():
        import numpy as np
        from PIL import Image
        rid = np.asarray(Image.open(pd / "regions.png").convert("RGB"))[..., 0]
        od = np.asarray(Image.open(pd / "lights.png").convert("RGB"))[..., 1] > 127
        hj = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {}
        nv = hj.get("no_view") or {}
        blind = []
        for g in regs:
            if g["kind"] == "glass" and g["name"] not in nv:
                pm = rid == g["id"]
                if pm.sum() > 400 and float(od[pm].mean()) < 0.2:
                    blind.append(f"{g['name']} {float(od[pm].mean()):.0%}")
        out.append(("L79", not blind, "every pane looks out to the weather" if not blind else
                    "panes with little or no outdoors behind them, so no rain shows through: " + ", ".join(blind[:6])
                    + " (a near-reading pane: hand.json \"outdoor\"; a mask that is what stands in front: hand.json \"no_view\" with why)"))


def _lint_loop(out, spec, ev):
    # L54: the 10 h video loops a short window, so the timeline must repeat with it and hold every event type
    lp = (ev.get("loop") or {}).get("period")
    ls = spec.get("loopSeconds", 120)
    if not lp:
        out.append(("L54", False, "no events.loop.period: the 10 h video loops a short window and needs a timeline that repeats "
                    "with it (1200 s; master-render skill)"))
    elif lp % ls or not 600 <= lp <= 3600:
        out.append(("L54", False, f"events.loop.period {lp} s: make it a whole number of loopSeconds ({ls} s), 10 to 60 minutes"))
    else:
        rare = [f"{k} {v['perHour']:g}/h" for k, v in ev.items() if isinstance(v, dict) and v.get("perHour") and v["perHour"] * lp / 3600 < 1]
        out.append(("L54", not rare, f"loop period {lp / 60:g} min; every event type comes at least once per period" if not rare else
                    f"under once per {lp / 60:g} min period, so some loops would lack it: {', '.join(rare)}"))


def _lint_intro(out, scene, spec, pd):
    # L55: an intro line in the look's font
    aes = config("aesthetics")["aesthetics"].get(spec.get("aesthetic"), {})
    if not spec.get("intro"):
        out.append(("L55", False, "no intro line (scene.json `intro`): a short welcome in his voice, in the look's font (tools/intro_title.py)"))
    else:
        import intro_title as IT
        why = IT.stale(scene)
        ij = json.loads((pd / "intro.json").read_text(encoding="utf-8")) if (pd / "intro.json").exists() else {}
        want = spec["intro"].get("font") or aes.get("title_font")
        if why:
            out.append(("L55", False, f"intro: {why}; run tools/intro_title.py {scene} and look at intro_preview.jpg"))
        else:
            out.append(("L55", ij.get("font") == want, f"intro: {' / '.join(ij.get('lines', []))} in {ij.get('font_title')}"
                        + ("" if ij.get("font") == want else f" (the look's font is {want})")))


def _lint_music(out, scene):
    # L53: music folders that hold a real playlist (each track with a complete sidecar)
    import music as M
    dirs, mc = M.scene_music(scene)
    tracks = []
    for d in dirs:
        for f in sorted(d.glob("*")) if d.is_dir() else []:
            if f.suffix.lower() in M.AUDIO_EXT:
                sc_ = next((p for p in (f.with_name(f.name + ".json"), f.with_suffix(".json")) if p.exists()), None)
                meta = json.loads(sc_.read_text(encoding="utf-8")) if sc_ else {}
                if all(meta.get(k) for k in M.REQUIRED):
                    tracks.append(meta)
    moj = [t["title"] for t in tracks if M.is_mojang(t)] if not mc else []
    if not dirs:
        out.append(("L53", None, "no music folders for this look yet (aesthetics.json music_dirs): music comes at STOP 3"))
    elif moj:
        out.append(("L53", False, f"Mojang tracks in a non-Minecraft look's music: {', '.join(moj[:3])}"))
    else:
        out.append(("L53", len(tracks) >= 15, f"music: {len(tracks)} tracks with sidecars in {', '.join(rel(d) for d in dirs)}"
                    + ("" if len(tracks) >= 15 else " (under 15: the playlist repeats too soon; curate more with tools/music_like.py)")))


def timeline(scene):
    r = subprocess.run(["node", str(ROOT / "src" / "cli.mjs"), "timeline", f"scenes/{scene}", "--duration", "1h",
                        "--out", str(ROOT / "out" / scene / "review_timeline.json")], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads((ROOT / "out" / scene / "review_timeline.json").read_text(encoding="utf-8"))


LAYER_EVENTS = ("moth", "perch", "ant", "critter", "fish", "birds", "boat", "heron")


def layers_draw(scene, rd):
    """Every event layer draws something: the layer alone on black (`--params only=<layer>,plate=black`) at a moment
    inside its first event in the render's window. The farm porch's moth was placed, scheduled and hidden everywhere
    by the indoors mask, and no other check saw it (2026-10-21). Returns [(layer, ok, message)]."""
    import numpy as np
    from PIL import Image
    spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    types = {L["type"] for L in spec.get("layers", []) if L.get("enabled", True) is not False}
    man = json.loads((rd / "render.json").read_text(encoding="utf-8"))
    r0, r1, fps = float(man.get("from", 0)), float(man.get("from", 0)) + float(man.get("length", 0)), float(man.get("fps", 30))
    tl = json.loads((rd / "timeline.json").read_text(encoding="utf-8"))
    out_dir = ROOT / "out" / scene / "review_layers"
    out = []
    for kind in LAYER_EVENTS:
        if kind not in types:
            continue
        evs = [e for e in tl.get("events", []) if e["type"] == kind and e["t"] < r1 and e["t"] + float(e.get("dur", 0) or 0) > r0]
        if not evs:
            continue
        e = evs[0]
        d = float(e.get("dur", 0) or 0)
        ts = [min(max(e["t"] + f * d, r0 + 0.5), r1 - 0.5) for f in (0.3, 0.5, 0.7)] if d else [e["t"] + 0.5]
        frames = sorted({int(round(t * fps)) for t in ts})
        r = subprocess.run(["node", str(ROOT / "src" / "cli.mjs"), "still", f"scenes/{scene}", "--frames", ",".join(map(str, frames)),
                            "--width", "1920", "--height", "1080", "--params", f"only={kind},plate=black", "--out", str(out_dir)],
                           capture_output=True, text=True, cwd=ROOT)
        peak = 0.0
        for f in frames:
            p = out_dir / f"{scene}_1920x1080_f{f:06d}.png"
            if p.exists():
                peak = max(peak, float(np.asarray(Image.open(p).convert("L"), np.float32).max()) / 255)
        ok = r.returncode == 0 and peak > 0.06
        out.append((kind, ok, f"{kind} at {e['t']:.0f} s: brightest pixel {peak:.2f} alone on black" if ok else
                    f"{kind} draws nothing at {', '.join(f'{t:.0f}' for t in ts)} s alone on black (peak {peak:.2f}): hidden everywhere? "
                    "check its masks (lights.png, depth, occ.png) and its placement"))
    return out


def run(args, label):
    print(f"\n== {label}: {' '.join(str(a) for a in args[1:])}")
    # UTF-8 both ways: a vision model's curly quote in motion_review's output crashed this reader as cp1252 (2026-10-21)
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for line in lines[-14:]:
        print("   " + line)
    return r.returncode


def main():
    # his quotes carry emoji (a published title); a piped Windows console is cp1252 and crashed on them, which read as
    # a failed review
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--render", help="a render folder (out/<scene>/render/<tag>)")
    ap.add_argument("--clip", help="a preview or sample clip for the static check")
    ap.add_argument("--skip-static", action="store_true")
    a = ap.parse_args()
    fails = []
    print(f"review: {a.scene}")
    print("\n== lint (scene data against the lessons)")
    for lid, ok, msg in lint(a.scene):
        tag = "ok  " if ok else ("FAIL" if ok is False else "look")
        print(f"   {tag} {lid} {msg}")
        if ok is False:
            fails.append(f"{lid} {msg}")
    if run([PY, str(ROOT / "tools" / "leak_check.py"), a.scene], "leak") != 0:
        fails.append("leak_check")
    # the vision model on every tile of where the weather draws (asks only about tiles that changed since the last run)
    if run([PY, str(ROOT / "tools" / "outdoor_check.py"), a.scene], "outdoor (nothing inside under the weather)") != 0:
        fails.append("L100 outdoor_check: weather over something inside or a frame (look at out/plates/<plate>/outdoor_check/"
                     "outdoor_check.jpg; tools/outdoor_check.py <scene> --repair cuts it, autopilot's checks stage runs that)")
    if run([PY, str(ROOT / "tools" / "weather_audit.py"), a.scene], "weather") != 0:
        fails.append("weather_audit: dry pockets or wet frames (look at each crop in out/plates/<scene>/audit_pockets and "
                     "audit_frames; fix the mask, or note why in the hand.json note)")
    tl = timeline(a.scene)
    if tl:
        print("\n== timeline (first hour)")
        cnt = {}
        for e in tl["events"]:
            cnt[e["type"]] = cnt.get(e["type"], 0) + 1
        print("   per hour: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])))
        P = (tl.get("loop") or {}).get("period")
        if P:
            per = {}
            for e in tl["events"]:
                if 0 <= e["t"] < P:
                    per[e["type"]] = per.get(e["type"], 0) + 1
            print(f"   per {P / 60:g} min loop (L54): " + ", ".join(f"{k} {v}" for k, v in sorted(per.items(), key=lambda kv: -kv[1])))
            lost = sorted(set(cnt) - set(per))
            if lost:
                fails.append(f"L54 event types missing from the loop period: {', '.join(lost)}")
        first = [f"{e['type']}@{e['t']:.0f}s" for e in tl["events"] if 0 <= e["t"] < 60 and e["type"] not in ("perch",)]
        print(f"   first minute (L04 strong opening): {', '.join(first) or 'nothing'}")
        if not first:
            fails.append("L04 nothing happens in the first minute")
    clip = a.clip
    if a.render:
        rd = pathlib.Path(a.render)
        qa = (rd / "qa.md").read_text(encoding="utf-8") if (rd / "qa.md").exists() else ""
        ok = "Overall: **PASS**" in qa
        print(f"\n== render QA: {'PASS' if ok else 'FAIL or missing'} ({rd / 'qa.md'})")
        if not ok:
            fails.append("render QA")
        run([PY, str(ROOT / "tools" / "event_sheets.py"), str(rd)], "event sheets")
        if (rd / "master.mp4").exists():
            run([PY, str(ROOT / "tools" / "rain_motion.py"), str(rd)], "rain motion (holes in the rain: L121's eye check)")
            import rain_motion
            pd = rain_motion.plate_of(rd)
            spec = json.loads((ROOT / "scenes" / a.scene / "scene.json").read_text(encoding="utf-8"))
            if pd and any(L.get("type") == "rain" and L.get("enabled") is not False for L in spec.get("layers") or []):
                share, boxes, checked = rain_motion.faint_rain(rd / "master.mp4", pd)
                print(f"   faint rain in the dark (L152): {share:.0%} of the open rain area ({len(boxes)} of {checked} blocks)")
                if share > rain_motion.FAINT_SHARE:
                    fails.append(f"L152 the rain doesn't show over {share:.0%} of the open rain area in the dark "
                                 f"(red boxes in {rd / 'review' / 'rain_motion.jpg'}): lift the drops (rain layer minContrast)")
        if (rd / "render.json").exists() and (rd / "timeline.json").exists():
            print("\n== layers draw (each event layer alone on black, inside its first event)")
            for kind, ok, msg in layers_draw(a.scene, rd):
                print(f"   {'ok  ' if ok else 'FAIL'} {msg}")
                if not ok:
                    fails.append(f"layer {msg}")
        if not clip and (rd / "master.mp4").exists():
            clip = str(rd / "review" / "first40s.mp4")
            (rd / "review").mkdir(exist_ok=True)
            run_ffmpeg(["-v", "error", "-y", "-i", str(rd / "master.mp4"), "-t", "40", "-c", "copy", clip], capture=False)
    if clip and not a.skip_static:
        if run([PY, str(ROOT / "tools" / "motion_review.py"), clip, "--static", a.scene], "static (nothing that should move is still)") != 0:
            fails.append("motion_review --static")
    print("\n== look yourself before showing (lessons with an eye check)")
    for L in lessons():
        if "eye:" in L["check"]:
            eye = L["check"].split("eye:", 1)[1].strip()
            print(f"   [ ] {L['id']} {eye}   ({L['saw']})")
    print(f"\n{'FAIL' if fails else 'PASS'}: {len(fails)} automatic check(s) failed" + "".join(f"\n   - {f}" for f in fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
