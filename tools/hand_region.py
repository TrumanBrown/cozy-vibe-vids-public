"""Add a region the analysis missed to a scene's hand fixes, traced by SAM 2 from a box, and rebuild the plate's masks.

This is the fix the static check asks for (lessons L50: cloth and leaves in moving air sway, and whatever hangs from
them moves along): the ramen alley's noren and cherry tree were added this way by hand; the farm porch's big tree and
the blanket on its rocking chair were the first fixed by this tool (2026-10-21). The region goes into
assets/keyart/<scene>.hand.json (merged by plate_prep, never overwritten by the analysis), and its sway into
scenes/<scene>/scene.json `regions` when the kind's default doesn't fit.

  .venv/Scripts/python tools/hand_region.py <scene> --box x0,y0,x1,y1 --kind plant|curtain --name <name>
      [--outdoor | --indoor] [--sway amp,hz,gust] [--twigs] [--no-rebuild]
  .venv/Scripts/python tools/hand_region.py <scene> --from-static <render>/review/first40s_static.json [--no-rebuild]

--from-static takes every flag of severity "high" that names foliage or cloth (a tree, leaves, a vine, a bush; a
blanket, a curtain, a towel, a flag, a banner) and adds it; anything else it lists for the agent. Then re-render and
run the static check again. Look at out/plates/<scene>/regions_preview.png after it: SAM's trace of a see-through
plant (bare, frosted or dry twigs) can take the rock or wall behind it, and the sway would wobble that too. Trace such
a plant again with --twigs, one box per clump (its strokes in the box, no SAM).
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

from cozy.paths import ROOT, PY, load_scene, save_scene
from cozy.plate.regions import hangs
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from PIL import Image  # noqa: E402

# plurals too: the static check's flag of still shrubs on the riverbank was left for the agent by `shrub\b` (the Sleeping
# Hound Inn's sample v9, 2026-11-15)
FOLIAGE = re.compile(r"(?i)\b(trees?|foliage|leaves|leaf|branch|branches|canopy|canopies|vines?|ivy|bush|bushes|shrubs?|shrubbery|hedges?|"
                     r"grass|grasses|reeds?|ferns?|palms?|willows?|bamboo|pines?|saplings?|weeds?|twigs?)\b")
CLOTH = re.compile(r"(?i)\b(blanket|blankets|throw|quilt|curtain|curtains|drape|drapes|cloth|towel|towels|flag|flags|banner|banners|noren|laundry|scarf|tablecloth|tarp|awning cloth|sheet)\b")


def covered(box, other):
    """The share of box (x0, y0, x1, y1 fractions) inside other."""
    ix = max(0.0, min(box[2], other[2]) - max(box[0], other[0]))
    iy = max(0.0, min(box[3], other[3]) - max(box[1], other[1]))
    return ix * iy / max((box[2] - box[0]) * (box[3] - box[1]), 1e-9)
DRAPED = re.compile(r"(?i)\b(draped|over the|on the (chair|bench|rail|railing|sofa|couch)|folded)\b")


def sway_for(kind, where, outdoor):
    """The sway that fits what it is (px at 4K at the free end): a tree in the open moves its canopy a few px and
    more in gusts; cloth hanging free in the open moves like the ramen alley's noren (5 px); a blanket draped over
    furniture on a sheltered porch only stirs at its hem. Vines hanging in the open take autoscene's hanging sway
    (their region is pinned at its top, L163), so none is written for them."""
    if kind == "plant":
        if outdoor and hangs({"note": where}):
            return None
        big = bool(re.search(r"(?i)\b(trees?|canopy|canopies|willows?|palms?)\b", where))
        return {"amp": 6.0, "hz": 0.1, "gust": 1.5} if (big and outdoor) else ({"amp": 3.0, "hz": 0.12, "gust": 1.2} if outdoor else None)
    if kind == "curtain":
        if DRAPED.search(where):
            return {"amp": 2.0, "hz": 0.08, "gust": 1.2}
        return {"amp": 5.0, "hz": 0.09, "gust": 1.6} if outdoor else None
    return None


def twigs(rgb, inside, t=0.15):
    """The thin strokes of a see-through plant (bare, frosted or dry twigs, grass blades) inside a bool mask: whatever is
    much brighter or darker than its 9 px surroundings (top-hats of the luminance), specks dropped, grown 2 px and
    closed so a clump's strokes hold together. Smooth things behind them (a rock, a wall, snow) stay out: the Sleeping
    Hound Inn's frosted riverbank shrubs, traced by SAM from the static check's box, took the boulder behind them, the
    snow lump at their foot and part of a post, and the sway would have wobbled the rock (sample v9, 2026-11-15)."""
    import cv2
    import numpy as np
    a = np.asarray(rgb, np.float32) / 255
    L = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    thin = np.maximum(L - cv2.morphologyEx(L, cv2.MORPH_OPEN, k), cv2.morphologyEx(L, cv2.MORPH_CLOSE, k) - L)
    m = ((thin > t) & inside).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 12
    m = cv2.dilate(keep[lab].astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return (m > 0) & inside


def trace(scene, box, kind=None, twig=False):
    """SAM 2 mask of the thing in box (plate fractions) -> normalized polygons. A plant keeps only what looks like
    foliage or blossom (saturated color, not gray): the Minecraft tea house's "shrubs along the right bank" took the
    bank's stone blocks with them, and the sway would have wobbled the rocks (2026-10-22). With `twig`, the plant's
    strokes inside the box itself (twigs()), no SAM: for a see-through plant in front of something solid.
    trace.leafy says afterwards whether a plant's trace was cut to its foliage by color."""
    import cozy.segment as A
    import numpy as np
    raw = Image.open(ROOT / "out" / "plates" / scene / "plate_raw.png").convert("RGB")
    W, H = raw.size
    trace.leafy = False
    if twig:
        x0, y0, x1, y1 = (int(round(v)) for v in (box[0] * W, box[1] * H, box[2] * W, box[3] * H))
        inside = np.zeros((H, W), bool)
        inside[max(0, y0):y1, max(0, x0):x1] = True
        m = twigs(raw, inside)
        return A.contours(m, W, H, eps=1.0, min_area=20) if m.any() else []
    m = A.Segmenter().masks(raw, [A.box_px(box, W, H, grow=0.02)], keep_area=(0.05, 1.2))[0]
    if m is None or not m.any():
        return []
    if kind == "plant":
        import cv2
        a = np.asarray(raw, np.float32) / 255
        sat = (a.max(-1) - a.min(-1)) / (a.max(-1) + 1e-6)
        leafy = cv2.dilate(((sat > 0.18) & (a.max(-1) > 0.08)).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        leafy = cv2.morphologyEx((m & leafy).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
        if leafy.sum() >= 0.2 * m.sum():
            m = leafy
            trace.leafy = True
    return A.contours(m, W, H, eps=1.0, min_area=20)


def under_weather(scene, polys):
    """The share of a traced region under the weather (lights.png G), or None without a plate. The words of the static
    check's description decided indoors or out, and "overhanging the veranda", "along the far bank" matched none of
    them: the Minecraft tea house's cherry tree and bamboo went in as indoor plants (no gusts, a 0.8 px sway) and
    leak_check failed on rain over "indoor" plants (2026-10-22)."""
    lp = ROOT / "out" / "plates" / scene / "lights.png"
    if not lp.exists():
        return None
    import numpy as np
    from cozy.masks import poly_mask
    g = np.asarray(Image.open(lp).convert("RGB"))[..., 1] > 127
    H, W = g.shape
    m = poly_mask((W, H), polys) > 0.5
    return float(g[m].mean()) if m.any() else None


def add(scene, name, kind, box, where, outdoor, sway, twig=False):
    hp = ROOT / "assets" / "keyart" / f"{scene}.hand.json"
    hand = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {"_note": "Hand fixes merged over the analyzed masks (tools/plate_prep.py)."}
    regs = hand.setdefault("regions", [])
    if any(r.get("name") == name for r in regs):
        print(f"  {name}: already a hand region")
        return False
    polys = trace(scene, box, kind, twig)
    if not polys:
        print(f"  ! {name}: {'no twigs' if twig else 'SAM found nothing'} in {box}")
        return False
    if sway == "auto":
        # from the static check: what the masks say beats the words (under_weather)
        share = under_weather(scene, polys)
        if share is not None:
            outdoor = share >= 0.5
        sway = sway_for(kind, where, outdoor)
    regs.append({"name": name, "kind": kind, "polys": polys, "outdoor": outdoor, "feather": 3})
    if kind == "plant" and hangs({"name": name, "note": where}):
        regs[-1].update(anchor="top", feather=6)
    how = "its twigs in a box (--twigs)" if twig else "a SAM mask from a box"
    hand["_note"] = (hand.get("_note", "") + f" {name} ({kind}, {how}; the static check found it still: "
                     f"\"{where}\") added by tools/hand_region.py.").strip()
    hp.write_text(json.dumps(hand, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    sp = ROOT / "scenes" / scene / "scene.json"
    if sway and sp.exists():
        spec = load_scene(scene)
        spec.setdefault("regions", {})[name] = {"sway": sway}
        save_scene(scene, spec)
    print(f"  + {name}: {kind}, {'outdoors' if outdoor else 'indoors'}, {len(polys)} polygon(s)" + (f", sway {sway}" if sway else ""))
    return True


def box_iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


CAP = {"plant": 10.0, "curtain": 7.0}       # px at the free end: more reads as a puppet, not wind


def retrace(scene, g, box, where):
    """A flagged thing a hand region covers only in part: trace it again over both boxes, with the same name and sway.
    The Burdock Shelter's reeds region held their lower half; the static check found the upper half still, and growing
    the region's sway could never move it (2026-10-25). Returns True when it was traced again."""
    hp = ROOT / "assets" / "keyart" / f"{scene}.hand.json"
    hand = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {}
    old = next((r for r in hand.get("regions") or [] if r.get("name") == g["name"]), None)
    if old is None:
        return False                     # an analysis region: not ours to retrace
    b = g["bbox"]
    union = [min(b[0], box[0]), min(b[1], box[1]), max(b[2], box[2]), max(b[3], box[3])]
    hand["regions"] = [r for r in hand["regions"] if r.get("name") != g["name"]]
    hp.write_text(json.dumps(hand, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    spec = load_scene(scene)
    sway = ((spec.get("regions") or {}).get(g["name"]) or {}).get("sway") or "auto"
    if add(scene, g["name"], old["kind"], union, where, old.get("outdoor", True), sway):
        return True
    hand["regions"].append(old)          # SAM found nothing: the old trace stays
    hp.write_text(json.dumps(hand, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    return False


def strengthen(scene, regs, box, where):
    """A flagged thing that already has a sway region (it was added, and still measures still): its sway grows by
    about 1.6 times, up to CAP, when the region covers most of the flagged box; when it covers under 70% of it, the
    still part is outside the region, so the region is traced again over both boxes instead (retrace). Returns the
    changes and whether a region was traced again (the masks need a rebuild)."""
    hits = [g for g in regs if g["kind"] in ("plant", "curtain") and box_iou(g["bbox"], box) > 0.25]
    if not hits:
        return [], False
    out, traced = [], False
    area = max(1e-9, (box[2] - box[0]) * (box[3] - box[1]))
    for g in list(hits):
        b = g["bbox"]
        inside = max(0.0, min(b[2], box[2]) - max(b[0], box[0])) * max(0.0, min(b[3], box[3]) - max(b[1], box[1])) / area
        if inside < 0.7 and retrace(scene, g, box, where):
            out.append(f"{g['name']} traced again over the flagged box (it covered {inside:.0%} of it)")
            traced = True
            hits.remove(g)
    spec = load_scene(scene)
    grown = []
    for g in hits:
        cur = ((spec.get("regions") or {}).get(g["name"]) or {}).get("sway") or {}
        hanging = g["kind"] == "plant" and g.get("anchor") == "top" and g.get("outdoor", True)
        # what autoscene gives the region without an override (REGION_FX, a hanging plant's swing): grow from that
        base = 6.0 if hanging else {"plant": 2.0, "curtain": 5.0}[g["kind"]] if g.get("outdoor", True) else 0.8
        amp = float(cur.get("amp", base))
        new = round(min(CAP[g["kind"]], max(amp * 1.6, amp + 1.0)), 1)
        if new <= amp:
            continue
        sw = {"amp": new, "hz": cur.get("hz", 0.1), "gust": max(float(cur.get("gust", 1.5 if hanging else 1.2)), 1.2)}
        spec.setdefault("regions", {})[g["name"]] = {**((spec.get("regions") or {}).get(g["name"]) or {}), "sway": sw}
        grown.append(f"{g['name']} sway {amp:g} -> {new:g} px")
    if grown:
        save_scene(scene, spec)
    return out + grown, traced


def name_for(where, kind, taken):
    words = [w for w in re.findall(r"[a-z]+", where.lower()) if w not in {"still", "the", "a", "an", "of", "on", "in", "at", "over", "and", "with", "open", "edge"}]
    base = "_".join(words[:3]) or kind
    n, k = base, 2
    while n in taken:
        n, k = f"{base}_{k}", k + 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--box")
    ap.add_argument("--kind", choices=["plant", "curtain"])
    ap.add_argument("--name")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--outdoor", action="store_true")
    g.add_argument("--indoor", action="store_true")
    ap.add_argument("--sway", help="amp,hz,gust")
    ap.add_argument("--twigs", action="store_true", help="a see-through plant (bare, frosted or dry twigs, grass): its strokes in the box, no SAM")
    ap.add_argument("--from-static")
    ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args()
    added, left = 0, []
    regs = json.loads((ROOT / "out" / "plates" / a.scene / "regions.json").read_text(encoding="utf-8"))
    regs = regs["regions"] if isinstance(regs, dict) else regs
    taken = {g["name"] for g in regs}
    rebuild = False
    if a.from_static:
        st = json.loads(pathlib.Path(a.from_static).read_text(encoding="utf-8"))
        ana = json.loads((ROOT / "out" / "plates" / a.scene / "analysis.json").read_text(encoding="utf-8"))
        for f in st.get("flagged") or []:
            if f.get("severity") != "high" or not f.get("box"):
                continue
            where = f.get("where", "")
            # a flag over a character is about the character, whatever else it names ("the otter's head remains still
            # while its scarf ... moves" was traced as cloth and swayed: the tide pool, 2026-11-05). The cast and a
            # painted pet only breathe and blink (their heads hold still by design); their touches are their own regions
            box = [float(v) for v in f["box"]]
            pet = max((covered(box, g["bbox"]) for g in regs if g.get("kind") == "pet"), default=0.0)
            if pet >= 0.5:
                left.append(f"{where} (a character: it only breathes and blinks; its head holds still by design)")
                continue
            kind = "curtain" if CLOTH.search(where) else "plant" if FOLIAGE.search(where) else None
            if not kind:
                left.append(where)
                continue
            grown, traced = strengthen(a.scene, regs, box, where)
            if grown:
                print("  ~ " + "; ".join(grown) + " (it already sways and still measured still)")
                added += 1
                rebuild |= traced
                continue
            outdoor = not re.search(r"(?i)\b(indoors?|inside|room|bedroom|kitchen|living room)\b", where) and \
                (not ana.get("indoor", True) or bool(re.search(r"(?i)\b(open|outside|outdoors?|porch|veranda|garden|street|yard|bank|pond|lake|river|sky)\b", where)))
            name = name_for(where, kind, taken)
            taken.add(name)
            ok = add(a.scene, name, kind, box, where, outdoor, "auto")
            added += ok
            rebuild |= bool(ok)
            if ok and kind == "plant" and not getattr(trace, "leafy", True):
                # no saturated foliage to cut SAM's mask to: it can hold whatever stands behind see-through twigs
                print(f"  ! {name}: SAM's trace isn't cut to leaves: look at regions_preview.png before the render; if it took "
                      f"a rock, a wall or snow behind the twigs, trace it again with --box ... --kind plant --twigs")
    else:
        if not (a.box and a.kind and a.name):
            sys.exit("give --box, --kind and --name, or --from-static")
        box = [float(v) for v in a.box.split(",")]
        outdoor = not a.indoor
        sway = dict(zip(("amp", "hz", "gust"), map(float, a.sway.split(",")))) if a.sway else sway_for(a.kind, a.name.replace("_", " "), outdoor)
        if a.twigs and a.kind != "plant":
            sys.exit("--twigs traces a plant")
        ok = add(a.scene, a.name, a.kind, box, a.name.replace("_", " "), outdoor, sway, a.twigs)
        added += ok
        rebuild |= bool(ok)
    for w in left:
        print(f"  ? not foliage or cloth, left for the agent: {w}")
    if rebuild and not a.no_rebuild:
        r = subprocess.run([PY, str(ROOT / "tools" / "new_video.py"), "prep", a.scene, "--masks-only"])
        if r.returncode != 0:
            sys.exit("plate_prep --masks-only failed")
    print(f"hand_region: {added} added" + (f", {len(left)} left for the agent" if left else ""))
    return 0 if not left else 3


if __name__ == "__main__":
    sys.exit(main())
