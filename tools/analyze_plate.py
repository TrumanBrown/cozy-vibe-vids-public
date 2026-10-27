"""Automatic plate analysis: key art -> animation regions, masks and a draft animated scene.

  .venv/Scripts/python tools/analyze_plate.py <scene> [--reuse] [--verify] [--no-scene]
  .venv/Scripts/python tools/analyze_plate.py <scene> --critter-occ    # only redo what the critter hides behind

Needs scenes/<scene>/brief.json (tools/new_video.py) and the 4K plate (out/plates/<scene>/, plate_prep.py).
1. The vision model (Azure, config/azure.json "vision_deployment") lists the animatable elements of the image
   from a fixed vocabulary (KINDS) with approximate boxes, plus painted effects that must be removed (frozen
   lightning bolts) and the street a car could drive along. Answer cached in out/plates/<scene>/analysis.json.
2. SAM 2.1 (facebook/sam2.1-hiera-large, Apache-2.0, local GPU) turns each box into a mask; kind-specific
   rules refine it (flames = bright warm pixels, floating candles = one region per flame, a cup's rim = the top
   of its mask, a hanging lantern's pivot = the top of its mask). The things just past the critter's path ends
   (point prompts) become "critter_occ": it comes out from behind them and goes out of sight behind them.
3. Writes assets/keyart/<scene>.masks.json (regions + outdoor/sky/water polygons + cleanup) and, unless it
   exists (or --force-scene), scenes/<scene>/scene.json + scene.js; then re-runs plate_prep.py --masks-only.
4. --verify: the model checks the labeled region overlay (regions_preview.png) and reports wrong regions.
Check out/plates/<scene>/regions_preview.png (and occ_preview.jpg with a critter) yourself after every run.
"""
import argparse
import json
import os
import subprocess
import sys

from cozy.paths import ROOT, PY, config, creature_id, safe_name, save_scene
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from azure_ai import vision_json  # noqa: E402
import plate_features  # noqa: E402
# the SAM wrapper and the critter helpers are in cozy/segment.py (TASKS.md T12)
from cozy.segment import Segmenter, box_px, contours, critter_cover, critter_size, grid_image  # noqa: E402

AES = config("aesthetics")

KINDS = {
    "glass": "a window pane with clear glass through which the outside is seen (one element per window; rain on glass and outdoor weather go here)",
    "opening": "an open view to the outside without glass (porch, awning, balcony, open door): outdoor weather falls there",
    "cover": "a solid near structure that weather must not fall on and that blocks the view (awning, roof edge, stall, posts, railing, counter, and furniture under the roof next to the camera such as stools, chairs and tables)",
    "sky": "visible sky (clouds drift there; lightning glows there)",
    "water": "open water that should flow or ripple: a river, canal, harbor, lake, sea or pond, including small or distant water seen through an opening or window (give 'flow')",
    "puddle": "wet ground outdoors where rain lands: pavement, a street, a path, a deck, steps, the paving or stone ledge at a pond's edge, or puddles (one element per surface; box it)",
    "fire": "the visible flames and glowing logs of a fireplace, stove, campfire or brazier (box just the flames; give 'fuel')",
    "candle": "a single lit candle or oil lamp standing on something (box the flame and the candle)",
    "bob": "floating lit candles or floating objects (one element for the whole group; set count)",
    "lantern": "a hanging lantern or hanging lamp that can sway slightly (one element each)",
    "chime": "a hanging wind chime, mobile or hanging sign that can sway",
    "lamp": "a fixed lamp, pendant bulb or sconce (steady light)",
    "neon": "a neon sign (one element each)",
    "string": "string lights or fairy lights (one element per strand or area)",
    "screen": "a glowing screen or monitor",
    "steam": "a hot drink, bowl or pot that should steam (box the cup or bowl itself; if steam is painted above it give 'plume')",
    "pet": "the animal (one element; box the whole body; give 'look', 'pose', 'place')",
    "plant": "a potted or hanging plant near an opening or window that could sway in a draft",
    "curtain": "a curtain, cloth or banner that could sway",
    "clouds": "large soft clouds or fog banks in the sky that could drift",
    "dust": "a bright beam or pool of lamplight indoors where dust motes would show",
    "fireflies": "a dusky garden, field or bushes outdoors where fireflies would show",
    "remove": "a painted transient effect that would look frozen and must be removed: a lightning bolt, a shooting star, sparks, a big splash (not rain streaks, snowflakes, steam or drips: those are handled elsewhere)",
    "creature": "a small animal painted into the picture other than the sleeping pet: a snail, an insect, a bird, a frog, a mouse. It would sit frozen while the code animates its own, so it is removed",
}
# Old analyses may still list painted drips one by one; plate_clean.py now removes them along every edge.
LEGACY_KINDS = {"drip"}
# kinds that become regions (others only feed masks or the scene)
REGION_KINDS = {"glass", "opening", "sky", "fire", "candle", "bob", "lantern", "chime", "lamp", "neon", "string", "screen", "steam",
                "pet", "plant", "curtain", "clouds", "dust", "fireflies", "water"}


def ask_model(plate_img, brief, aes):
    kinds = "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    prompt = f"""You prepare a still image for animation in code. It is the key art of a calm 10-hour ambience video.
Brief: {json.dumps({k: brief.get(k) for k in ('setting', 'time', 'weather', 'pet', 'props', 'signature')})}
Art style: {aes.get('style')}.

The first image is the key art; the second is the same image with a labeled grid every 0.1 of width and height.
List every element the code can animate, using ONLY these kinds:
{kinds}

Coordinates are fractions of the image width (x) and height (y), y measured from the TOP. Boxes are [x0, y0, x1, y1]
and must be tight around the element (read the grid). Use one element per window, lantern, neon sign, cup, candle.
Return a JSON object:
{{
 "indoor": true/false,
 "time_of_day": "...",
 "weather_outside": "rain" | "heavy rain" | "snow" | "thunderstorm" | "clear" | "fog" | "none",
 "light_color": "#rrggbb of the main warm light",
 "horizon": y of the eye-level line (where the ground's perspective lines meet; may be hidden behind things),
 "elements": [
   {{"name": "short_snake_case_name", "kind": "<kind>", "box": [x0, y0, x1, y1], "note": "what it is",
     "side": "inside" (on our side of the window/opening: dry, in front of the weather) | "outside" (out in the weather),
     "count": <for bob: how many floating objects>,
     "rim": [x, y] (steam: center of the cup/bowl rim), "rim_width": <steam: rim width as a fraction of image width>,
     "plume": [x0, y0, x1, y1] (steam: box of steam or smoke painted into the image near it, if any; null if none),
     "plume_behind": "what the painted steam covers, e.g. 'the dark wooden wall and a potted plant'",
     "fuel": "fire: what burns, e.g. 'split logs on an iron grate in a stone fireplace'",
     "flow": [dx, dy] (water: the direction the water moves on screen, unit-ish; [0, 0] for still water),
     "pivot": [x, y] (lantern/chime: where it hangs from), "species": "cat"|"dog"|... (pet),
     "behind": "creature: what is behind or under it, e.g. 'the wet porch boards'",
     "look": "pet: its color and kind, e.g. 'black-and-white cat'", "pose": "pet: e.g. 'curled up asleep'", "place": "pet: what it lies on",
     "head": [x0, y0, x1, y1] (pet: box of its head with ears, eyes and nose), "tail": [x0, y0, x1, y1] (pet: box of its tail, null if hidden)}}
 ],
 "road": null or {{"path": [[x, y], [x, y], ...] along the drivable street lane seen outside (left to right or far to near),
          "car_length": <length of a car at the middle of the path as a fraction of image width>,
          "view": "side" (street runs across the frame) | "depth" (street runs toward the camera)}},
 "rail": null or {{"path": [[x, y], [x, y]] where a distant train could pass, "car_length": <fraction>}},
 "birds": null or {{"band": [x0, y0, x1, y1] open sky (or far open air) that small birds could fly across, clear of nearer things,
          "wingspan": <a small bird's wingspan there as a fraction of image width>}},
 "critter": null or {{"creature": "snail" | "ladybug" | "beetle" | "gecko" | "frog" | "mouse" (fits the setting and weather: snails in rain),
          "path": [[x, y], ...] the line where its foot touches a level surface in the near or middle ground, where it would crawl
          slowly over minutes: ON the top of a step a little behind its front edge, a ledge, a planter rim, a sill (never along an
          edge line itself, and never on a riser, a wall or any upright face: it would hang in the air there), clearly visible (not
          hidden by the counter), starting and ending where it can come and go out of sight (behind something or at the frame edge),
          "size": <its body length on screen as a fraction of image width at its real size (a garden snail is ~6 cm long: compare a
          step's height ~15 cm, a door ~0.9 m wide)>}},
 "notes": "anything that would make animation hard (painted lightning, people, text)"
}}
Only include a road if a street with room for passing cars is clearly visible outside."""
    return vision_json(prompt, images=[plate_img, grid_image(plate_img)], purpose=f"analyze:{brief['scene']}", effort="high", max_side=1600)


# ---------------------------------------------------------------- segmentation

def critter_occ_only(scene):
    """--critter-occ: recompute what every critter hides behind from the scene's current critter paths (scene.json,
    e.g. after moving one by hand or adding a track) into the masks json ("critter_occ") and
    out/plates/<scene>/occ.png. Every critter layer counts: this once used only the first and dropped the others'
    covers (the pixel greenhouse's ladybug lost its cloth when two insects were added, 2026-10-21)."""
    spec = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    if not any(L.get("type") == "critter" and len(L.get("path") or []) >= 2 for L in spec.get("layers", [])):
        sys.exit(f"{scene}: no critter layer with a path in scene.json")
    missing = plate_features.critter_occ(scene, spec, ROOT / "out" / "plates" / spec.get("plate", scene))
    for m in missing or []:
        print(f"  ! nothing to hide the critter behind at {m}: it fades in view there (move that path end)")
    return 1 if missing else 0


def water_body(m, disp, margin=0.06):
    """A water region is one level surface. SAM's mask of the Minecraft tea house's pond also took the glossy wet deck
    around the table, which mirrors the view like water (2026-10-22): 15% of the region was deck, and the water's
    ripple would have wobbled its boards (the class of L82, the trough's planks). Keep the main body (the largest
    connected piece) and the pieces at its depth (a river seen between a railing's balusters, a pond split by a
    bridge); drop the pieces clearly nearer than the main body's near shore, and anything within it far nearer still.
    m: bool HxW; disp: the disparity at the same size (nearer is larger, 0..1)."""
    H, W = m.shape
    s = 4
    ms = cv2.resize(m.astype(np.uint8), (max(1, W // s), max(1, H // s)), interpolation=cv2.INTER_NEAREST)
    ds = cv2.resize(disp, (ms.shape[1], ms.shape[0]), interpolation=cv2.INTER_AREA)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ms, connectivity=8)
    if n <= 2:
        return m
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    shore = float(np.percentile(ds[lab == main], 97))
    keep = np.zeros(n, bool)
    keep[main] = True
    for i in range(1, n):
        if i != main and float(np.median(ds[lab == i])) <= shore + margin:
            keep[i] = True
    ok = keep[lab] & (ds <= shore + 2 * margin)
    ok = cv2.resize(ok.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
    return m & ok


def holes(mask, W, H, min_area=12):
    """Polygons (normalized) of the holes inside a bool mask: the openings enclosed by its parts (a chair's rungs, a
    railing's bars). Computed at 1920 px wide, like contours()."""
    s = 1920 / W
    small = cv2.resize(mask.astype(np.uint8) * 255, (1920, round(H * s)), interpolation=cv2.INTER_AREA)
    cs, hier = cv2.findContours((small > 127).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = []
    if hier is None:
        return out
    for c, h in zip(cs, hier[0]):
        if h[3] < 0 or cv2.contourArea(c) < min_area:          # outer contours have no parent
            continue
        a = cv2.approxPolyDP(c, 1.0, True).reshape(-1, 2)
        if len(a) >= 3:
            out.append([[round(float(x) / 1920, 5), round(float(y) / small.shape[0], 5)] for x, y in a])
    return out


def box_mask_small(box, W=1920, H=1080):
    m = np.zeros((H, W), bool)
    x0, y0, x1, y1 = box
    m[int(max(0, y0) * H):int(min(1, y1) * H) + 1, int(max(0, x0) * W):int(min(1, x1) * W) + 1] = True
    return m


def flames_in(arr, box, W, H):
    """Bright warm pixels (flames, glowing embers) inside a box: bool mask (full size)."""
    x0, y0, x1, y1 = [int(v) for v in box_px(box, W, H, 0.04)]
    sub = arr[y0:y1, x0:x1].astype(np.float32) / 255
    lum = sub @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    warm = (sub[..., 0] > sub[..., 2] + 0.2) & (lum > 0.42)
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = cv2.dilate(warm.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return m


def candle_flames(arr, box, W, H, max_n=32, avoid=()):
    """Individual flames of floating candles in a box -> list of (cx, cy, flame w, flame h) px. A flame is a
    small, very bright warm core with a pale candle body under it (lit castle windows and lamps have none)."""
    x0, y0, x1, y1 = [int(v) for v in box_px(box, W, H, 0.02)]
    sub = arr[y0:y1, x0:x1].astype(np.float32) / 255
    lum = sub @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    r = W / 3840
    flame = ((lum > 0.78) & (sub[..., 0] > 0.88) & (sub[..., 0] > sub[..., 2] + 0.08)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(flame, connectivity=8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = st[k]
        if not (12 * r * r <= area <= 900 * r * r) or h < 0.7 * w:
            continue
        cx, cy = cen[k][0] + x0, cen[k][1] + y0
        if any(b[0] * W <= cx <= b[2] * W and b[1] * H <= cy <= b[3] * H for b in avoid):
            continue
        # candle body: pale, fairly bright pixels in a narrow column below the flame
        bx0, bx1 = int(max(0, x - 0.5 * w)), int(min(x1 - x0, x + 1.5 * w))
        by0, by1 = int(y + h + 1), int(min(y1 - y0, y + h + 5 * h))
        col = lum[by0:by1, bx0:bx1]
        if col.size == 0 or (col > 0.4).mean() < 0.3:
            continue
        out.append((cx, cy, float(w), float(h), area))
    out.sort(key=lambda t: -t[4])
    return [t[:4] for t in out[:max_n]]


def painted_drip(arr, box, W, H):
    """A painted hanging drop / short stream in a box: bright pixels standing above their surroundings
    (vertical structures), dilated; plus the drip's top point (x, y px) where water should start falling."""
    x0, y0, x1, y1 = [int(v) for v in box_px(box, W, H, 0.15)]
    sub = arr[y0:y1, x0:x1].astype(np.float32) / 255
    lum = sub @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bg = cv2.medianBlur((lum * 255).astype(np.uint8), 21).astype(np.float32) / 255
    m = ((lum - bg) > 0.08).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 1), np.uint8))
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    full = np.zeros((H, W), bool)
    full[y0:y1, x0:x1] = m > 0
    ys, xs = np.nonzero(m)
    top = (float(xs[ys == ys.min()].mean() + x0), float(ys.min() + y0)) if len(xs) else None
    return full, top


def painted_bolt(arr, box, W, H):
    """A painted lightning bolt in a box: the very brightest pixels standing well above their surroundings,
    kept only in long connected structures (rain streaks and window lead are much dimmer), slightly dilated."""
    x0, y0, x1, y1 = [int(v) for v in box_px(box, W, H, 0.05)]
    sub = arr[y0:y1, x0:x1].astype(np.float32) / 255
    lum = sub @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bg = cv2.medianBlur((lum * 255).astype(np.uint8), 31).astype(np.float32) / 255
    thr = max(0.55, float(np.percentile(lum, 99.3)))
    core = ((lum > thr) & (lum - bg > 0.18)).astype(np.uint8)
    core = cv2.dilate(core, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    r = W / 3840
    keep = np.zeros_like(core)
    for k in range(1, n):
        if max(st[k][2], st[k][3]) >= 40 * r:
            keep[lab == k] = 1
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    full = np.zeros((H, W), bool)
    full[y0:y1, x0:x1] = keep > 0
    return full


# ---------------------------------------------------------------- scene draft

def eave_runoff(eave_masks, view_box, seed=3, disp=None):
    """Runoff sources (rain.js) along the lower edge of roofs/awnings over an open view: a few pouring streams
    and sparse drips, spaced across the view (same parameters as Treetop's, scene.js). With the disparity (nearer is
    larger, the masks' size), a cover counts only when it is clearly nearer than the view around it: the Burdock
    Shelter's "canopy" was SAM's trace of the forest above the leaf, and its streams poured from open air (L149)."""
    if not eave_masks or not view_box:
        return []
    if disp is not None:
        Hd, Wd = disp.shape
        vb = np.zeros((Hd, Wd), bool)
        vb[int(view_box[1] * Hd):int(view_box[3] * Hd), int(view_box[0] * Wd):int(view_box[2] * Wd)] = True
        eave_masks = [em for em in eave_masks if em.any() and (vb & ~em).any()
                      and float(np.median(disp[em])) > 1.1 * float(np.median(disp[vb & ~em]))]
        if not eave_masks:
            return []
    m = np.zeros_like(eave_masks[0])
    for em in eave_masks:
        m |= em
    H, W = m.shape
    rng = np.random.default_rng(seed)
    x0, x1 = int(view_box[0] * W) + 20, int(view_box[2] * W) - 20
    cols = [x for x in range(x0, x1, 4) if m[:, x].any()]
    if len(cols) < 10:
        return []
    out = []
    picks = np.linspace(0, len(cols) - 1, 9)[1:-1]
    for i, j in enumerate(picks):
        x = cols[int(j) + int(rng.integers(-3, 4))]
        y = int(np.nonzero(m[:, x])[0].max())
        stream = i in (1, 4)
        out.append({"x": round(x / W, 4), "y": round((y + 2) / H, 4), "z": 3.2, "d": 4.6 if stream else 4.0,
                    "rate": 34 if stream else round(float(rng.uniform(0.6, 2.2)), 2), "flow": 0.6 if stream else 0.85,
                    "burst": 0.3 if stream else 0.15, "burstCycles": int(rng.integers(3, 6)), "neck": 0.04 if stream else 0,
                    "spread": 0.015, "warm": 1.2, "bright": 1.2})
    return out


def draft_scene(scene, brief, aes, ana, regions, road, rail, has_outdoor, W, H, runoff=None):
    weather = (ana.get("weather_outside") or brief.get("weather") or "none").lower()
    kinds = {r["kind"] for r in regions}
    rain = any(w in weather for w in ("rain", "storm", "drizzle"))
    snow = "snow" in weather or "blizzard" in weather
    storm = "storm" in weather or "thunder" in weather or "thunder" in (brief.get("weather") or "")
    pixel = aes.get("render", {}).get("pixel")
    layers, events = [], {}
    # how hard it rains: the brief's words count too ("gentle rain" on the farm porch drew a city storm's drops:
    # big bright streaks over the dark trees, and the eave poured in streams, 2026-10-21). Drop sizes follow
    # Marshall-Palmer (larger lambda, smaller drops): a light rain ~3.4, a steady one 2.4, a downpour 2.1
    words = f"{weather} {(brief.get('weather') or '').lower()}"
    heavy = any(w in words for w in ("heavy", "downpour", "pouring")) or storm
    gentle = not heavy and any(w in words for w in ("gentle", "light", "drizzle", "soft", "misty", "fine"))
    if rain and has_outdoor:
        layers.append({"type": "rain", "count": 9000 if heavy else 4500 if gentle else 6500, "depth": [3, 40], "depthPower": 1.3,
                       "dropRange": [0.5, 2.4 if gentle else 3.2], "dropLambda": 2.1 if heavy else 3.4 if gentle else 2.4,
                       "focalPx": 2700, "shutter": 1 / 110, "alphaRef": 0.25 if gentle else 0.35,
                       "farBoost": 0.15 if gentle else 0.3, "maxAlpha": 0.85, "minWidth": 2.0 if gentle else 3.0, "focus": 12, "coc": 10,
                       "skyGain": 2.0, "envMix": 0.85,
                       # the least a drop stands above the dark behind it (linear): physically a drop in front of a
                       # dark forest at night is about as dark as the forest, and the Burdock Shelter's rain vanished
                       # there (2026-10-25, L152); where the scene is brighter the drops are already above it
                       "minContrast": 0.05 if gentle else 0.08,
                       "warm": brief.get("light_color") or ana.get("light_color") or "#ffb26a", "warmGain": 0.35,
                       "clumps": {"amount": 1.0, "strength": 0.5, "cycles": 13, "across": 3, "drift": 1}})
        if pixel:
            # pixel art shows each cell's center: drops thinner than a cell or faint vanish, and the greenhouse's rainy dawn
            # showed almost no rain (2026-10-21): fewer, bigger and bolder drops (autoscene widens every streak to a cell)
            R = layers[-1]
            R.update({"count": int(R["count"] * 0.6), "dropRange": [1.2, R["dropRange"][1]], "alphaRef": round(R["alphaRef"] * 2, 2),
                      "maxAlpha": 0.9, "farBoost": round(R["farBoost"] + 0.2, 2)})
    # rain on the glass: beads and trickles. Not in pixel looks: on the grid every bead is one dark cell, which read as
    # dark marks on glass that should look clear (the pixel greenhouse, 2026-10-21)
    if "glass" in kinds and (rain or storm) and not pixel:
        gl = [r for r in regions if r["kind"] == "glass"]
        hpx = max((r["bbox"][3] - r["bbox"][1]) * H for r in gl)
        layers.append({"type": "glass", "regions": "kind:glass", "size": round(float(np.clip(hpx / 1300, 0.6, 1.5)), 2),
                       "density": 1.0, "trickles": 0.55, "spec": ana.get("light_color") or "#ffe2b8"})
    if snow and has_outdoor:
        layers.append({"type": "particles", "mode": "snow", "count": 7000, "depth": [1.5, 30], "depthBias": 1.0, "size": [3, 13], "fall": 0.9,
                       "flutter": 0.14, "density": 0.85, "warm": ana.get("light_color") or "#ffb26a"})
    if "steam" in kinds:
        # gust flurries lean a plume only where the wind reaches it: not a mug inside a closed room (2026-10-21)
        layers.append({"type": "steam", "regions": "kind:steam", "opacity": 0.7, "drafts": not ana.get("indoor", True)})
    if "fire" in kinds:
        layers.append({"type": "fire", "regions": "kind:fire"})
        layers.append({"type": "particles", "mode": "embers", "regions": "kind:fire", "rate": 0.45})
        events["ember"] = {"perHour": 14, "minGap": 90, "startAfter": 8}
    if rain and has_outdoor and ("opening" in kinds or not ana.get("indoor", True)):
        # drops swelling on every wet edge over an open view and letting go (plate.json beads); behind glass
        # the rain on the pane is glass.js instead
        layers.append({"type": "drips", "size": 5.5, "period": [4, 11]})
        # and where painted drips were removed anywhere else (far eaves, signs, leaves): live ones in their place
        layers.append({"type": "drips", "sources": "strands", "size": 3.5, "period": [3, 9]})
    birds = ana.get("birds") or {}
    sky_r = next((r for r in regions if r["kind"] == "sky"), None)
    if not birds.get("band") and sky_r and has_outdoor:
        # any open sky gets birds: they cross its lower part (under hanging things at the top of the frame)
        x0, y0, x1, y1 = sky_r["bbox"]
        birds = {**birds, "band": [x0, y0 + 0.1 * (y1 - y0), x1, y1 - 0.1 * (y1 - y0)], "wingspan": 0.009}
    if birds.get("band") and not snow:
        b = birds["band"]
        span = max(float(birds.get("wingspan") or 0.009), 0.007) * 3840
        layers.append({"type": "birds", "disp": round(float(birds.get("disp", 0.03)), 4), "haze": 0.35})
        events["birds"] = {"perHour": 14 if (rain or storm) else 10, "minGap": 40, "startAfter": 4, "band": [round(float(v), 3) for v in b],
                           "size": [round(span * 0.8, 1), round(span * 1.3, 1)], "count": [1, 5]}
    crit = ana.get("critter")
    if crit and len(crit.get("path") or []) >= 2:
        sz = critter_size(crit, float(ana.get("horizon") or 0.45))
        layers.append({"type": "critter", "creature": crit.get("creature", "snail"), "path": [[round(float(x), 4), round(float(y), 4)] for x, y in crit["path"]],
                       "size": round(sz, 1)})
        # a snail's pace: ~0.04 body lengths a second (plus the bits behind its cover at the ends)
        plen = sum(float(np.hypot((b[0] - a[0]) * 3840, (b[1] - a[1]) * 2160)) for a, b in zip(crit["path"][:-1], crit["path"][1:])) + 2 * sz
        d = float(np.clip(plen / (0.04 * sz), 180, 900))
        events["critter"] = {"perHour": 3, "dur": [round(0.85 * d), round(1.15 * d)], "startAfter": 20}
    if "dust" in kinds:
        layers.append({"type": "particles", "mode": "dust", "regions": "kind:dust", "count": 120})
    if "fireflies" in kinds and not (rain or snow):
        layers.append({"type": "particles", "mode": "fireflies", "regions": "kind:fireflies", "count": 16})
    if road and not any(w in (ana.get("time_of_day") or brief.get("time") or "").lower() for w in ("night", "late evening", "midnight")):
        # traffic.js draws lights only (headlights, tail lights, their reflections): at night they read as cars, but at
        # dusk or by day the road shows plainly and bodiless lights slide along it (the comic bus stop at dusk, 2026-10-25)
        print(f"  road: no traffic drafted ({ana.get('time_of_day') or brief.get('time') or 'time unknown'}: traffic.js draws lights only)")
        road = None
    if road:
        P = road["path"]
        base = road.get("car_length", 0.08) * 3840
        if road.get("view", "side") == "depth":
            # cars shrink toward the far end: scale ~ distance below the horizon (a little above the far end)
            hz = min(p[1] for p in P) - 0.05
            ym = sum(p[1] for p in P) / len(P)
            sc = [round(base * max(0.12, (p[1] - hz) / max(ym - hz, 1e-3))) for p in P]
        else:
            sc = round(base)
        layers.append({"type": "traffic", "path": P, "scale": sc, "view": road.get("view", "side"), "lanes": [0, -0.08], "reflect": 0.6})
        events["car"] = {"perHour": 70, "minGap": 14, "dur": [4, 7] if road.get("view", "side") == "side" else [6, 10], "startAfter": 3}
    if rail:
        tr = next((L for L in layers if L["type"] == "traffic"), None)
        T = {"path": rail["path"], "scale": round(rail.get("car_length", 0.05) * 3840 / 6), "windows": 6}
        if tr:
            tr["train"] = T
        else:
            layers.append({"type": "traffic", "train": T})
        events["train"] = {"perHour": 3, "startAfter": 20, "dur": [14, 22], "cooldown": 600}
    if storm:
        sky = next((r for r in regions if r["kind"] == "sky"), None)
        views = [r for r in regions if r["kind"] in ("glass", "opening")]
        if sky:
            bx = sky["bbox"]
        elif views:
            bx = [min(r["bbox"][0] for r in views), min(r["bbox"][1] for r in views), max(r["bbox"][2] for r in views), max(r["bbox"][3] for r in views)]
        else:
            bx = [0.2, 0.05, 0.8, 0.3]
        events["lightning"] = {"perHour": 5, "cluster": [1, 3], "withinCluster": [50, 180], "minGap": 90, "maxGap": 1500,
                               "startAfter": 25, "endBefore": 45, "delay": [2.5, 6]}
        events["farflash"] = {"perHour": 18, "minGap": 35, "startAfter": 6, "delay": [3, 5], "power": [0.4, 0.8],
                              "x": [round(bx[0] + 0.1 * (bx[2] - bx[0]), 3), round(bx[2] - 0.1 * (bx[2] - bx[0]), 3)],
                              "y": [round(bx[1] + 0.1 * (bx[3] - bx[1]), 3), round(bx[1] + 0.5 * (bx[3] - bx[1]), 3)], "clear": 20}
    if rain or snow or storm:
        events["weather"] = {"dt": 5, "rainAmp": 1.25 if rain else 1.4, "windAmp": 1, "stormRain": 0.2 if storm else 0, "stormWind": 0.3 if storm else 0,
                             "stormHalfWidth": 420, "streamLag": 90}
        # gusts lean falling rain: a few degrees reads as rain, 15+ degrees reads as sideways (user 2026-10-17)
        events["flurry"] = {"perHour": 4, "minGap": 300, "dur": [5, 9], "amp": [1.0, 2.2] if snow else ([0.6, 1.1] if storm else [0.35, 0.7]),
                            "leaves": [0, 0], "prevailing": 1, "startAfter": 40}
    if "neon" in kinds:
        events["neon"] = {"perHour": 10, "minGap": 120, "startAfter": 10}
    if kinds & {"candle", "bob", "lantern"}:
        events["gutter"] = {"perHour": 5, "minGap": 300, "startAfter": 30, "depth": 0.55}
    if "pet" in kinds:
        # a painted pet only breathes: sighs, never ear flicks or tail twitches (timeline.js defaults those to 0)
        events["pet"] = {"sigh": 8, "minGap": 30}
    # Window life: someone passing a lit window inside dims it for a moment (plate light groups of kind
    # window, from the previous plate_prep run); any open view at dusk or night.
    pm = json.loads((ROOT / "out" / "plates" / scene / "plate.json").read_text(encoding="utf-8")) if (ROOT / "out" / "plates" / scene / "plate.json").exists() else {}
    wins = [g for g in pm.get("light_groups", []) if g.get("kind") == "window" and not g.get("reflective") and g.get("size_px", 0) >= 20]
    tod = (ana.get("time_of_day") or brief.get("time") or "").lower()
    if wins and any(w in tod for w in ("night", "dusk", "evening")):
        events["windows"] = {"pass": 6, "dim": 3, "away": 2, "minGap": 30, "minSize": 20}
    if "sky" in kinds and not (rain or snow or storm) and "night" in (ana.get("time_of_day") or brief.get("time") or ""):
        sky = next(r for r in regions if r["kind"] == "sky")
        layers.append({"type": "particles", "mode": "stars"})
        events["star"] = {"perHour": 3, "minGap": 400, "startAfter": 15, "box": sky["bbox"]}
    events["rareGap"] = 45
    events["strikeBusy"] = [30, 30]
    # rain ~2-3 degrees off vertical in calm air and ~10 in a gust; snow drifts more (it is light), a storm leans harder
    wind = ({"mean": 0.1, "gust": 0.8, "turb": 0.35} if snow else {"mean": 0.08, "gust": 0.4, "turb": 0.4} if storm
            else {"mean": 0.05, "gust": 0.25, "turb": 0.3})
    wind.update({"gustCycles": 5, "fronts": 0.6})
    if gentle and runoff:
        # in a gentle rain an eave drips; it doesn't pour: streams become slow drips, drips slow and dim
        runoff = [{**r, "rate": 0.5, "d": 3.2, "flow": 0.85, "burst": 0.15, "neck": 0, "bright": 1.0} if float(r.get("rate", 1)) > 5 else
                  {**r, "rate": round(0.4 * float(r.get("rate", 1)), 2), "d": min(float(r.get("d", 4.0)), 3.2), "bright": 1.0} for r in runoff]
    spec = {
        "_note": "Draft written by tools/analyze_plate.py; tune freely (it is not overwritten unless --force-scene). Keys: src/library/autoscene.js.",
        "name": scene, "title": brief.get("title_idea") or brief.get("setting"), "aesthetic": brief["aesthetic"], "plate": scene,
        "seed": 7, "fps": 30, "loopSeconds": 120, "duration": 36000,
        "plate_fx": {"flicker": 0.02, "mist": 0.0, "ripple": 0.0006 if kinds & {"water"} else 0.0, "horizon": round(float(ana.get("horizon") or 0.45), 3),
                     "lightning": {"color": "#b9c8ff", "sky": 2.0, "land": 0.8, "roomNear": 0.35, "roomAmbient": 0.06, "farColor": "#c9c4f2"}},
        "regions": {}, "layers": layers, "wind": wind, "runoff": (runoff or []) if rain else [], "events": events,
        "audio": {"bed": aes.get("audio_bed", "porch_rain"), "lufs": -20},
    }
    from cozy.audio.ambience import choose_bed
    bed, extra = choose_bed(aes.get("audio_bed", "porch_rain"), weather, "fire" in kinds, ana.get("indoor", True))
    spec["audio"]["bed"] = bed
    if extra:
        spec["audio"]["extra_db"] = extra
    fire = next((r for r in regions if r["kind"] == "fire"), None)
    if fire:
        spec["audio"]["fire_pan"] = round(float(np.clip(((fire["bbox"][0] + fire["bbox"][2]) / 2 - 0.5) * 1.6, -0.9, 0.9)), 2)
    if pixel:
        spec["render"] = {"animFps": aes.get("render", {}).get("animFps", 12), "pixel": "plate"}
        spec["post"] = {"bloom": {"strength": 0.12, "radius": 0.3, "threshold": 0.95}}
    if has_outdoor and (rain or snow or "fog" in weather or "mist" in weather):
        # mist drifting through the far view (plate.js: far, outdoor pixels), in the color of the far air
        sky = (pm.get("env_linear") or {}).get("outdoor") or [0.05, 0.06, 0.1]
        srgb = [min(255, round(255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055))) for c in sky]
        spec["plate_fx"].update({"mist": 0.14, "mistColor": "#%02x%02x%02x" % tuple(srgb)})
    wet = {e.get("kind") for e in ana.get("elements", [])}
    if wet & {"puddle", "water"} and (rain or storm):
        # rain on the wet ground and water: rings laid out on the ground plane (plate.js groundRings)
        hz = float(ana.get("horizon") or 0.45)
        spec["plate_fx"].update({"ripple": 0.0003, "rippleXY": [0.9, 0.5], "rings": [0, 0],
                                 "ground": {"horizon": round(min(max(hz, 0.2), 0.8), 3), "refract": 8, "highlight": 0.7, "cells": 24, "density": 0.85}})
    elif "water" in wet:
        spec["plate_fx"].update({"ripple": 0.0006, "rings": [0, 0]})
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--reuse", action="store_true", help="reuse out/plates/<scene>/analysis.json (no model call)")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--force-scene", action="store_true", help="overwrite scenes/<scene>/scene.json")
    ap.add_argument("--no-prep", action="store_true")
    ap.add_argument("--critter-occ", action="store_true", help="only recompute what the critter hides behind (masks json + occ.png) from scene.json's path")
    a = ap.parse_args()
    scene = a.scene
    if a.critter_occ:
        return critter_occ_only(scene)
    brief, aes, pdir, raw, W, H, arr = _plate(scene)
    ana, els = _elements(a, pdir, raw, brief, aes)

    seg, disp_full, mask_of = _sam_masks(pdir, raw, els, W, H)
    regions, ov = [], {"auto_masks": False, "auto_lanterns": False, "outdoor_disp": "auto"}
    uname = _unique_names()
    sky_p, water_p, cover_p, inpaint_p, cover_h, small_masks, eave_masks, drips, clean = _regions_of_elements(
        els, mask_of, arr, W, H, disp_full, regions, ov, uname)
    kinds = _outdoors(ana, regions, ov, cover_p, cover_h)
    disp, view_med = _cut_near(pdir, els, regions, small_masks, ov, W, H)
    weather = _weather(ana, brief, els, regions, kinds, ov, sky_p, water_p, cover_p, clean)
    _clean_list(scene, brief, pdir, clean)
    _mask_flags(aes, ana, kinds, ov, regions, inpaint_p, weather)
    _critter_covers(ana, seg, raw, W, H, disp, ov)
    _write_masks(scene, ov, regions)

    sd = ROOT / "scenes" / scene
    _draft(a, scene, sd, brief, aes, ana, regions, ov, eave_masks, drips, disp, view_med, W, H)
    _scene_js(sd)
    _run_plate_prep(a, scene, brief)
    _verify(a, scene, pdir)


def _plate(scene):
    """(the brief, the look, the plate folder, the raw plate, its size, its pixels)."""
    brief = json.loads((ROOT / "scenes" / scene / "brief.json").read_text(encoding="utf-8"))
    aes = AES["aesthetics"][brief["aesthetic"]]
    pdir = ROOT / "out" / "plates" / scene
    raw = Image.open(pdir / "plate_raw.png").convert("RGB")
    W, H = raw.size
    arr = np.asarray(raw)
    return brief, aes, pdir, raw, W, H, arr


def _elements(a, pdir, raw, brief, aes):
    """The analysis (cached, or the model's) and its elements with plain names."""
    ana_p = pdir / "analysis.json"
    if a.reuse and ana_p.exists():
        ana = json.loads(ana_p.read_text(encoding="utf-8"))
    else:
        ana, usage = ask_model(raw, brief, aes)
        ana_p.write_text(json.dumps(ana, indent=1), encoding="utf-8")
        print(f"model: {len(ana.get('elements', []))} elements (~${usage['usd_est']:.3f})")
    els = [e for e in ana.get("elements", []) if (e.get("kind") in KINDS or e.get("kind") in LEGACY_KINDS) and len(e.get("box", [])) == 4]
    # the model's names become folder and file names (steam/<name>/, fire/<name>/, critter_<creature>.png): plain only
    for e in els:
        e["name"] = safe_name(e.get("name"), e["kind"])
    if isinstance(ana.get("critter"), dict):
        ana["critter"]["creature"] = creature_id(ana["critter"].get("creature"))
    for e in els:
        print(f"  {e['kind']:9s} {e['name']:24s} {[round(v, 3) for v in e['box']]}  {e.get('note', '')[:60]}")
    return ana, els


def _sam_masks(pdir, raw, els, W, H):
    """(the segmenter, the disparity at full size, SAM's mask of each element that gets one, by the element's id)."""
    seg = Segmenter()
    # the disparity (nearer is larger) at full size, for masks that must lie on one surface (water_body)
    disp_full = cv2.resize(np.asarray(Image.open(pdir / "depth.png"), np.float32) / 65535, (W, H), interpolation=cv2.INTER_LINEAR)
    # Open views are areas, not objects: SAM finds patches in them, so they keep the model's box (depth and
    # "cover" elements then cut out the near structures).
    need = [e for e in els if e["kind"] not in ("bob", "remove", "creature", "dust", "fireflies", "opening", "drip")]
    ms = seg.masks(raw, [box_px(e["box"], W, H) for e in need])
    mask_of = {id(e): m for e, m in zip(need, ms)}
    return seg, disp_full, mask_of


def _unique_names():
    """uname(n): n, else n_2, n_3 ... when n is taken."""
    used = set()

    def uname(n):
        k, i = n, 2
        while k in used:
            k, i = f"{n}_{i}", i + 1
        used.add(k)
        return k

    return uname


def _regions_of_elements(els, mask_of, arr, W, H, disp_full, regions, ov, uname):
    """Each element to its region, polygons or cleanup item; -> (the sky, water, cover and inpaint polygons, the
    covers' holes, the regions' masks at 1920, the eaves' masks, the painted drips, the cleanup items)."""
    sky_p, water_p, cover_p, inpaint_p = [], [], [], []
    cover_h = []
    small_masks, eave_masks, drips = {}, [], []
    clean = []          # painted transients for tools/plate_clean.py (steam plumes, flames, edge drips)
    for e in els:
        k, m = e["kind"], mask_of.get(id(e))
        if k == "fire":
            m = _fire_mask(e, m, arr, W, H, clean)
        if k == "bob":
            _bob_regions(e, els, arr, W, H, regions, uname)
            continue
        if k == "remove":
            _bolt_inpaint(e, arr, W, H, inpaint_p)
            continue
        if k == "creature":
            _creature_clean(e, clean, uname)
            continue
        if k == "drip":
            _drip_source(e, arr, W, H, ov, drips)
            continue
        if k in ("dust", "fireflies", "opening"):
            _box_region(e, k, regions, uname)
            continue
        if m is None or not m.any():
            print(f"  ! no mask for {e['name']}")
            continue
        if k == "glass" and (e["box"][2] - e["box"][0]) < 0.04:
            print(f"  skip {e['name']}: too narrow for rain on the glass")
            continue
        polys = contours(m, W, H)
        if not polys:
            continue
        ys, xs = np.nonzero(m)
        if k == "sky":
            sky_p += polys
        if k in ("water", "puddle"):
            if k == "water":
                m2 = water_body(m, disp_full)
                if m2.sum() < m.sum():
                    print(f"  water {e['name']}: {100 * (1 - m2.sum() / m.sum()):.0f}% of SAM's mask is nearer than the water "
                          "(a glossy floor mirroring the view): left out")
                    m = m2
                    polys = contours(m, W, H)
                    if not polys:
                        continue
            _water_region(e, k, polys, water_p, regions, uname)
            continue
        if k == "cover":
            _cover_masks(e, m, polys, W, H, cover_p, cover_h, eave_masks)
            continue
        _mask_region(e, k, m, polys, xs, ys, W, H, regions, small_masks, clean, uname)
    return sky_p, water_p, cover_p, inpaint_p, cover_h, small_masks, eave_masks, drips, clean


def _fire_mask(e, m, arr, W, H, clean):
    fm = flames_in(arr, e["box"], W, H)
    m = (m | fm) if m is not None and fm.sum() < 0.3 * m.sum() else (fm if fm.any() else m)
    if m is not None and m.any():
        # room above the flames so the streaming flame texture can lick upward and change the outline
        ys_, _ = np.nonzero(m)
        grow = max(3, int(0.3 * (ys_.max() - ys_.min())))
        ker = np.zeros((2 * grow + 1, 9), np.uint8)
        ker[grow:, :] = 1          # dilation reaches up only (the anchor row is the kernel center)
        m = cv2.dilate(m.astype(np.uint8), ker) > 0
    # the painted flames go (fire.js draws live ones on the logs); the region keeps the light flicker
    x0, y0, x1, y1 = e["box"]
    ex, ey = 0.12 * (x1 - x0), 0.15 * (y1 - y0)
    clean.append({"name": f"{e['name']}_flames", "kind": "fire", "box": [round(x0 - ex, 4), round(y0 - 2 * ey, 4), round(x1 + ex, 4), round(y1 + 0.5 * ey, 4)],
                  "shape": "ellipse", "what": e.get("note") or "fire", "behind": e.get("fuel") or "the logs, glowing with embers"})
    return m


def _bob_regions(e, els, arr, W, H, regions, uname):
    avoid = [x["box"] for x in els if x["kind"] in ("glass", "opening", "lamp", "lantern")]
    fl = candle_flames(arr, e["box"], W, H, max_n=min(32, int(e.get("count") or 28) + 4), avoid=avoid)
    for i, (cx, cy, fw, fh) in enumerate(fl):
        fw, fh = max(fw, 5.0), max(fh, 8.0)
        regions.append({"name": uname(f"{e['name']}_{i + 1}"), "kind": "bob", "feather": 3,
                        "box": [round((cx - 2.4 * fw) / W, 5), round((cy - 1.6 * fh) / H, 5), round((cx + 2.4 * fw) / W, 5), round((cy + 6.0 * fh) / H, 5)]})
    print(f"  bob {e['name']}: {len(fl)} flames")


def _bolt_inpaint(e, arr, W, H, inpaint_p):
    bm = painted_bolt(arr, e["box"], W, H)
    inpaint_p += contours(bm, W, H, eps=1.0, min_area=4)


def _creature_clean(e, clean, uname):
    # a painted snail or bird would sit frozen next to the animated ones (the farm porch's snail, 2026-10-21);
    # the box reaches well below it: its reflection or shadow on a wet surface goes too (a tight box left a smudge)
    x0, y0, x1, y1 = e["box"]
    gx, h = 0.45 * (x1 - x0) + 0.005, y1 - y0
    clean.append({"name": uname(e["name"]), "kind": "other",
                  "box": [round(x0 - gx, 4), round(y0 - 0.3 * h - 0.005, 4), round(x1 + gx, 4), round(y1 + 0.9 * h + 0.01, 4)],
                  "shape": "ellipse", "what": (e.get("note") or e["name"].replace("_", " ")) + ", with its reflection or shadow",
                  "behind": e.get("behind") or "the surface and the scenery behind it"})


def _drip_source(e, arr, W, H, ov, drips):
    _, top = painted_drip(arr, e["box"], W, H)
    x0, y0, x1, y1 = e["box"]
    pad = 0.3 * (x1 - x0)
    ov.setdefault("inpaint_bright", []).append([round(x0 - pad, 4), round(y0 - 0.002, 4), round(x1 + pad, 4), round(y1 + 0.01, 4)])
    if top:
        drips.append({"x": round(top[0] / W, 4), "y": round(top[1] / H, 4)})


def _box_region(e, k, regions, uname):
    bx = [round(v, 4) for v in e["box"]]
    if k == "opening":
        # an opening's box that stops within 4% of the frame edge goes to it: the model's boxes are approximate,
        # and the tea house's main opening stopped 2% under the frame top, which left a strip of sky between
        # the rafter ends dry and hung drops along the box edge in open sky (2026-10-22)
        bx = [0.0 if bx[0] < 0.04 else bx[0], 0.0 if bx[1] < 0.04 else bx[1], 1.0 if bx[2] > 0.96 else bx[2], 1.0 if bx[3] > 0.96 else bx[3]]
    regions.append({"name": uname(e["name"]), "kind": k, "box": bx, "feather": 12 if k != "opening" else 2})


def _water_region(e, k, polys, water_p, regions, uname):
    water_p += polys
    if k == "water":     # a region too: the current flows there (plate.js river)
        fl = e.get("flow") or [0, 0]
        # feather 6: the current shifts the reflections a few px, and near a railing bar that must fade out
        r = {"name": uname(e["name"]), "kind": "water", "polys": polys, "feather": 6, "flow": [round(float(v), 3) for v in fl[:2]]}
        # water on our side (a trough, a basin) has solid sides, no railing to see more of it through: plate_prep's
        # see_through took the pixel greenhouse trough's planks and a watering can for water (2026-10-21)
        if e.get("side") == "inside":
            r["through"] = False
        regions.append(r)


def _cover_masks(e, m, polys, W, H, cover_p, cover_h, eave_masks):
    cover_p += polys
    # the openings enclosed by a chair's rungs or a railing's bars: the outline alone fills them, and then no
    # rain falls where the field shows through (the farm porch's rocking chair, 2026-10-21); plate_prep takes
    # them out of the cut and its gap fill decides what is outdoors
    cover_h += holes(m, W, H)
    nm = e["name"].lower()
    if any(w in nm for w in ("awning", "roof", "eave", "gutter", "canopy", "porch")):
        eave_masks.append(cv2.resize(m.astype(np.uint8), (1920, 1080), interpolation=cv2.INTER_NEAREST) > 0)


def _mask_region(e, k, m, polys, xs, ys, W, H, regions, small_masks, clean, uname):
    r = {"name": uname(e["name"]), "kind": k, "polys": polys}
    small_masks[r["name"]] = cv2.resize(m.astype(np.uint8), (1920, 1080), interpolation=cv2.INTER_NEAREST) > 0
    if k == "steam":
        top = ys.min()
        band = xs[ys < top + max(4, int(0.12 * (ys.max() - top)))]
        r["point"] = [round(float(band.mean()) / W, 5), round(float(top) / H, 5)]
        r["width"] = round(float(np.ptp(band) + 1) / W * 0.85, 5)
    if k in ("lantern", "chime"):
        r["pivot"] = [round(float(xs[ys < ys.min() + 6].mean()) / W, 5), round(float(ys.min()) / H, 5)]
    if k == "pet":
        r["species"] = e.get("species", "")
        for f in ("look", "pose", "place"):
            if e.get(f):
                r[f] = e[f]
        # only the torso breathes: the head (eyes, ears) and the tail hold still (user 2026-10-21 on the pixel
        # greenhouse's dog: the eyes and tail must hold still); plate_prep writes pet.png from these
        still = [[round(float(v), 4) for v in e[f]] for f in ("head", "tail") if isinstance(e.get(f), list) and len(e[f]) == 4]
        if still:
            r["still"] = still
    if k in ("glass", "opening"):
        r["feather"] = 2
    if k == "glass":
        # the model's box for the pane: SAM can leave out what is seen through it, and plate_prep's outdoors takes
        # the whole pane (the pixel greenhouse's barn, 2026-10-21)
        r["box"] = [round(float(v), 4) for v in e["box"]]
    regions.append(r)
    if k == "steam" and e.get("plume") and len(e["plume"]) == 4:
        # painted steam goes (tools/plate_clean.py): steam.js draws the moving steam from the rim
        px0, py0, px1, py1 = e["plume"]
        ex, ey = 0.1 * (px1 - px0), 0.1 * (py1 - py0)
        clean.append({"name": f"{r['name']}_plume", "kind": "steam", "box": [round(px0 - ex, 4), round(py0 - ey, 4), round(px1 + ex, 4), round(py1 + ey, 4)],
                      "shape": "ellipse", "what": f"steam rising from the {e.get('note') or r['name'].replace('_', ' ')}",
                      "behind": e.get("plume_behind") or "the scenery behind it", "protect": [r["name"]]})


def _outdoors(ana, regions, ov, cover_p, cover_h):
    kinds = {r["kind"] for r in regions}
    # Plants and curtains move in gusts only outdoors (inside an open view or an outdoor scene); indoors a
    # faint air movement at most.
    views = [r.get("box") for r in regions if r["kind"] == "opening"]
    for r in regions:
        if r["kind"] in ("plant", "curtain"):
            pts = [p for poly in r.get("polys", []) for p in poly] or [r["box"][:2], r["box"][2:]]
            cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            r["outdoor"] = (not ana.get("indoor", True)) or any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in views if b)
    if "glass" in kinds or "opening" in kinds:
        ov["outdoor_regions"] = [k for k in ("glass", "opening") if k in kinds]
    elif not ana.get("indoor", True):
        ov["outdoor_regions"] = ["all"]
    if cover_p:
        ov["not_outdoor"] = cover_p
    if cover_h:
        ov["not_outdoor_holes"] = cover_h
    return kinds


def _cut_near(pdir, els, regions, small_masks, ov, W, H):
    """Cuts what stands on our side of the weather out of the outdoors; -> (the disparity at 1920, the view's median)."""
    # Things on our side of the weather never get rain or snow drawn over them: pets, cups, candles, lanterns,
    # fires, curtains always; lamps, plants, neon and string lights when clearly nearer than the view behind
    # the glass or opening (a street lamp or a neon sign across the street stays outdoors).
    NEAR = {"pet", "steam", "candle", "bob", "fire", "lantern", "chime", "curtain", "screen"}
    disp = cv2.resize(np.asarray(Image.open(pdir / "depth.png"), np.float32) / 65535, (1920, 1080), interpolation=cv2.INTER_AREA)
    view = np.zeros((1080, 1920), bool)
    vbox = np.zeros((1080, 1920), bool)
    for r in regions:
        if r["kind"] in ("glass", "opening"):
            vm = small_masks[r["name"]] if r["name"] in small_masks else box_mask_small(r["box"])
            view |= vm
            ys, xs = np.nonzero(vm)
            if len(xs):
                vbox[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
    objs = np.zeros_like(view)
    for r in regions:
        if r["kind"] not in ("glass", "opening") and r["name"] in small_masks:
            objs |= small_masks[r["name"]]
    view_med = float(np.median(disp[view & ~objs])) if (view & ~objs).any() else 0.0
    cut = []
    for r in regions:
        # the panes and openings are the view itself: in a glass room the model calls every pane "inside", and
        # cutting them left a greenhouse with no outdoors, so no rain and no derain (pixel greenhouse, 2026-10-21)
        if r["kind"] in ("glass", "opening"):
            continue
        sm = small_masks.get(r["name"])
        if sm is None and r["kind"] == "bob":
            sm = box_mask_small(r["box"])
        if sm is None or not (sm & vbox).any():
            continue
        nearer = float(np.median(disp[sm])) > view_med + 0.08
        side = next((e.get("side") for e in els if e.get("name") == r["name"].rsplit("_", 1)[0] or e.get("name") == r["name"]), None)
        indoor_plant = r["kind"] == "plant" and r.get("outdoor") is False
        if side == "outside":
            continue
        if r["kind"] in NEAR or indoor_plant or side == "inside" or (r["kind"] in ("lamp", "plant", "neon", "string") and nearer and not r.get("outdoor")):
            grown = cv2.dilate(sm.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            cut += contours(cv2.resize(grown.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0, W, H, eps=1.0, min_area=4)
            r["near"] = True
    if cut:
        ov["not_outdoor"] = ov.get("not_outdoor", []) + cut
        print(f"  {sum(1 for r in regions if r.get('near'))} near objects cut out of the outdoors (view disparity {view_med:.3f})")
    return disp, view_med


def _weather(ana, brief, els, regions, kinds, ov, sky_p, water_p, cover_p, clean):
    # (sky/water polygons ADD to the masks: analyzed scenes have auto_masks off, so "only_*" would leave them empty)
    if sky_p:
        ov["sky"] = sky_p
    if water_p:
        ov["water"] = water_p
    else:
        ov["not_water"] = [[[0, 0], [1, 0], [1, 1], [0, 1]]]
    weather = (ana.get("weather_outside") or brief.get("weather") or "").lower()
    ov["derain"] = {"strength": 1.5, "passes": 2} if any(w in weather for w in ("rain", "storm")) else False
    # Drops painted hanging from the awning, eaves and lanterns go too (drips.js grows and drops real ones).
    open_view = "opening" in kinds or not ana.get("indoor", True)
    if any(w in weather for w in ("rain", "storm", "drizzle")) and open_view and ov.get("outdoor_regions") and cover_p:
        eaves = [e["name"].replace("_", " ") for e in els if e["kind"] == "cover"
                 and any(w in e["name"].lower() for w in ("awning", "roof", "eave", "gutter", "canopy", "porch", "overhang"))]
        what = " and ".join(eaves[:2]) or "roof edge"
        if any(r["kind"] == "lantern" and r.get("near") for r in regions):
            what += " and the hanging lanterns"
        clean.append({"name": "edge_drips", "kind": "drips", "what": what, "behind": "the scene behind them as it continues"})
        for r in regions:
            if r["kind"] == "curtain" and r.get("outdoor"):
                clean.append({"name": f"{r['name']}_drips", "kind": "drips", "under": [r["name"]], "band": 0.05,
                              "what": r["name"].replace("_", " "), "behind": "what is behind it"})
    if any(w in weather for w in ("rain", "storm", "drizzle")):
        # painted drips anywhere else (far eaves, signs, leaves): plate_clean.py finds them with the vision model
        clean.append({"name": "painted_strands", "kind": "strands", "what": "roof eaves, signs, lanterns and leaves",
                      "behind": "the walls, windows and leaves behind them"})
    return weather


def _clean_list(scene, brief, pdir, clean):
    plate_meta = json.loads((pdir / "plate.json").read_text(encoding="utf-8")) if (pdir / "plate.json").exists() else {}
    cp = ROOT / "assets" / "keyart" / f"{scene}.clean.json"
    if "clean.png" in str(plate_meta.get("source", "")).replace("\\", "/"):
        print(f"  plate is already cleaned: keeping {cp.name}")
    elif clean:
        cp.write_text(json.dumps({"_note": "Painted transients to remove from the key art (tools/plate_clean.py); written by "
                                  "tools/analyze_plate.py, edit freely.", "source": brief["hero"], "items": clean}, indent=1), encoding="utf-8")
        print(f"clean: {cp.relative_to(ROOT)} ({', '.join(i['name'] for i in clean)}): run tools/plate_clean.py {scene}")


def _mask_flags(aes, ana, kinds, ov, regions, inpaint_p, weather):
    if "snow" in weather:
        ov["desnow"] = True
    if inpaint_p:
        ov["inpaint"] = inpaint_p
    ov["auto_windows"] = any(k in kinds for k in ("glass", "opening")) or not ana.get("indoor", True)
    if aes.get("render", {}).get("pixel"):
        ov["pixel"] = "auto"
    ov["regions"] = regions


def _critter_covers(ana, seg, raw, W, H, disp, ov):
    # what the critter comes out from behind and goes out of sight behind at its path ends (plate_prep: occ.png)
    crit = ana.get("critter")
    if crit and len(crit.get("path") or []) >= 2:
        cov = critter_cover(seg, raw, crit["path"], critter_size(crit, float(ana.get("horizon") or 0.45)) * W / 3840,
                            depth=np.sqrt(disp))       # depth8's scale (sqrt of the disparity), as critter_ends calibrates
        if cov is not None:
            ov["critter_occ"] = contours(cov, W, H, eps=1.0, min_area=4)
        else:
            print("  ! nothing to hide the critter behind at its path ends: it fades in view there (move the path ends)")


def _write_masks(scene, ov, regions):
    ov["_generated"] = "tools/analyze_plate.py (edit freely; re-running overwrites this file)"
    mp = ROOT / "assets" / "keyart" / f"{scene}.masks.json"
    mp.write_text(json.dumps(ov, indent=1), encoding="utf-8")
    print(f"masks: {mp.relative_to(ROOT)} ({len(regions)} regions: {', '.join(sorted({r['kind'] for r in regions}))})")


def _draft(a, scene, sd, brief, aes, ana, regions, ov, eave_masks, drips, disp, view_med, W, H):
    """The draft scene.json, unless the scene has one (--force-scene: anyway)."""
    if not (sd / "scene.json").exists() or a.force_scene:
        def rbbox(r):
            if r.get("polys"):
                pts = [p for poly in r["polys"] for p in poly]
                return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
            return list(r["box"])
        rr = [{"kind": r["kind"], "bbox": rbbox(r), "name": r["name"]} for r in regions]
        vb = next((rbbox(r) for r in regions if r["kind"] == "opening"), None)
        if ana.get("birds") and len(ana["birds"].get("band") or []) == 4:
            # the birds fly at the depth of the far scenery in their band: nearer things hide them
            bx0, by0, bx1, by1 = ana["birds"]["band"]
            sub = disp[int(by0 * 1080):max(int(by1 * 1080), int(by0 * 1080) + 1), int(bx0 * 1920):max(int(bx1 * 1920), int(bx0 * 1920) + 1)]
            if sub.size:
                ana["birds"]["disp"] = float(np.percentile(sub, 30)) * 1.15 + 0.01
        elif any(r["kind"] == "sky" for r in regions):
            # birds cross in front of the far scenery (the sky itself has ~0 disparity): about 60% of the view's median
            ana["birds"] = {"band": None, "disp": max(0.02, 0.3 * view_med)}
        ro = eave_runoff(eave_masks, vb, disp=disp)
        rng = np.random.default_rng(11)
        hand = ROOT / "assets" / "keyart" / f"{scene}.hand.json"
        if hand.exists():   # hand-placed drips (e.g. where a painted drip was inpainted by hand)
            drips += [{"x": x, "y": y} for x, y in json.loads(hand.read_text(encoding="utf-8")).get("drips", [])]
        for d in drips:   # painted drips become real ones: a bead every 1-3 s from the same spot
            ro.append({"x": d["x"], "y": d["y"], "z": 3.0, "d": 4.2, "rate": round(float(rng.uniform(0.4, 1.0)), 2), "flow": 0.9, "burst": 0.15,
                       "burstCycles": int(rng.integers(3, 6)), "neck": 0, "spread": 0.01, "warm": 1.5, "bright": 1.2})
        spec = draft_scene(scene, brief, aes, ana, rr, ana.get("road"), ana.get("rail"), "outdoor_regions" in ov, W, H, runoff=ro)
        save_scene(scene, spec)
        print(f"scene: {(sd / 'scene.json').relative_to(ROOT)} ({len(spec['layers'])} layers, events: {', '.join(k for k in spec['events'] if k not in ('rareGap', 'strikeBusy'))})")


def _scene_js(sd):
    if not (sd / "scene.js").exists():
        (sd / "scene.js").write_text("// The scene is data: scene.json (written by tools/analyze_plate.py, tuned by hand). Keys: src/library/autoscene.js.\n"
                                     "import spec from './scene.json' with { type: 'json' };\n"
                                     "import { autoScene } from '../../src/library/autoscene.js';\n\nexport default autoScene(spec);\n", encoding="utf-8")


def _run_plate_prep(a, scene, brief):
    if not a.no_prep:
        hero = ROOT / "assets" / "keyart" / scene / "clean.png"
        if not hero.exists():
            hero = ROOT / brief["hero"]
        r = subprocess.run([PY, str(ROOT / "tools" / "plate_prep.py"), str(hero), "--name", scene, "--masks-only"])
        if r.returncode != 0:
            sys.exit("plate_prep --masks-only failed")


def _verify(a, scene, pdir):
    if a.verify:
        res, usage = vision_json(
            "This overlay shows the animation regions found in a key-art image, each tinted with a label 'id name (kind)'. "
            "Check each region: does it cover exactly the thing its name and kind say? Notes: a 'steam' region is meant to cover the cup "
            "or bowl itself (the code adds the steam above it); 'glass' should cover the window panes, not the wall; 'opening' is a "
            "rectangle around an open outdoor view; 'bob' regions are small boxes around single floating candles. Return JSON "
            "{\"regions\": [{\"id\": n, \"ok\": true/false, \"problem\": \"...\", \"box\": [x0, y0, x1, y1] (corrected tight box, fractions, "
            "y from top, only if wrong)}], \"missing\": [\"...\"]}",
            images=[pdir / "regions_preview.png"], purpose=f"verify:{scene}", effort="medium")
        (pdir / "verify.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        bad = [r for r in res.get("regions", []) if not r.get("ok", True)]
        print(f"verify (~${usage['usd_est']:.3f}): {len(bad)} region(s) flagged" + "".join(f"\n  {r['id']}: {r.get('problem')}" for r in bad))
        if res.get("missing"):
            print("  missing: " + "; ".join(res["missing"]))


if __name__ == "__main__":
    main()
