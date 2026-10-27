"""Where the weather goes, on one image: check it before any render (user 2026-10-18: the masks must be exact; to him
this is the easiest tell between AI and hand-made work).

  .venv/Scripts/python tools/weather_audit.py <scene>     -> out/plates/<scene>/weather_audit.jpg (+ _full.png)

Draws on the plate:
  blue    falling rain (lights.png G, outdoors)
  green   rain rings on wet ground and water (masks.png G x outdoors); red where that wet mask still covers an
          upright surface by depth (a wall, a riser, a post): rings there read as streaks
  yellow  drops hanging along wet edges (plate.json beads)
  cyan    live drips where painted ones were removed (plate.json strand_drips), with their fall line
  magenta roof runoff sources (scene.json runoff)
  orange  dry pockets: open air or wet ground the masks keep dry (gaps between legs, balusters)
  red     wet frames: rain over thin structure in or around the glass (a frame, a mullion, a door's handle)
and prints counts; exits 1 on a dry pocket or a wet frame, with 1:1 crops in audit_pockets/ and audit_frames/.
Fix by hand in assets/keyart/<scene>.hand.json: not_outdoor / not_water polygons, regions,
inpaint_bright boxes; then `new_video.py prep <scene> --masks-only` and audit again.
"""
import argparse
import json
import sys

from cozy.paths import ROOT

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402


def _local_mean(v, m, sigma):
    num = cv2.GaussianBlur(v * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    return num / np.maximum(den, 1e-4), den


def dry_pockets(outdoor, ground, disp, keep_dry, horizon, reach=300, min_area=1500, min_side=24, enclose=200):
    """Where the weather is missing (user 2026-10-19, raised for the Treetop railing and again for the ramen
    stool): pixels the masks keep dry although the depth says they are out in the open. Real gaps (between a
    stool's legs, a railing's balusters) show the street behind, and rain must fall there and ring the ground.
      rain:  not outdoors, but as far away as the open air within `reach` px of it (nothing nearer stands there)
      rings: not wet ground, but below the horizon, within `reach` px of wet ground and at the ground's own depth
             for its row (the median disparity of the wet ground in that row band): the street seen in a gap
    and in both cases enclosed: something much nearer on both sides within `enclose` px (a gap, not a street's
    edge against a wall).
    Works at a quarter of the plate size; reach, min_area and min_side are px at 4K. keep_dry: what is dry on
    purpose (pets, food, candles). Strips thinner than min_side (a step's riser edge, a depth halo along an
    outline) are not gaps. Returns [(kind, x0, y0, x1, y1, area px at 4K)] and the pocket mask (full size)."""
    H, W = outdoor.shape
    s = 4 * W // 3840 or 1
    sm = lambda a: cv2.resize(a.astype(np.float32), (W // s, H // s), interpolation=cv2.INTER_AREA)
    o, g, d, k = sm(outdoor) > 0.5, sm(ground) > 0.5, sm(disp), sm(keep_dry) > 0.05
    h, w = o.shape
    rr = reach * (W / 3840) / s
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2 * rr) | 1, int(2 * rr) | 1))
    near = lambda m: cv2.dilate(m.astype(np.uint8), disk).astype(bool)
    cands = {}
    ref, cov = _local_mean(d, o.astype(np.float32), rr / 2)
    cands["rain"] = ~o & ~k & near(o) & (cov > 0.05) & (d <= 1.12 * ref + 0.01)
    # the ground's disparity by row: median of the wet pixels in a band of rows (no guess where none are wet)
    gd = np.full(h, np.nan, np.float32)
    band = max(2, int(8 * (W / 3840)))
    for y in range(int(horizon * h), h):
        v = d[max(0, y - band): y + band + 1][g[max(0, y - band): y + band + 1]]
        if v.size >= 20:
            gd[y] = np.median(v)
    gdy = gd[:, None]
    with np.errstate(invalid="ignore"):
        at_ground = np.abs(d - gdy) <= 0.12 * gdy + 0.01
    # (near the horizon depth cannot tell the ground from a far shore or a wall, and rings there are a few px)
    rows = np.arange(h)[:, None] > int((horizon + 0.06) * h)
    cands["rings"] = ~g & ~k & near(g) & rows & np.nan_to_num(at_ground, nan=0).astype(bool)
    # a gap shows the far side through something near: there is something much nearer on both sides of it (left
    # and right, or above and below) within `enclose` px; a street's edge against a wall or a step has not
    R = max(3, int(enclose * (W / 3840) / s))
    win = lambda shape, anchor: cv2.dilate(d, np.ones(shape, np.uint8), anchor=anchor)
    lm, rm = win((1, R), (R - 1, 0)), win((1, R), (0, 0))
    um, dm = win((R, 1), (0, R - 1)), win((R, 1), (0, 0))
    nr = 1.3 * d + 0.02
    enclosed = ((lm >= nr) & (rm >= nr)) | ((um >= nr) & (dm >= nr))
    for kk in cands:
        cands[kk] &= enclosed
    found, mask = [], np.zeros(o.shape, bool)
    for kind, cand in cands.items():
        n, lab, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
        dist = cv2.distanceTransform(cand.astype(np.uint8), cv2.DIST_L2, 3)
        for i in range(1, n):
            area = st[i, cv2.CC_STAT_AREA] * (s * s) * (3840 / W) ** 2
            x, y, bw, bh = st[i, :4]
            if area < min_area:
                continue
            # thickness (twice the largest distance to its edge), px at 4K
            thick = 2 * float(dist[y:y + bh, x:x + bw][lab[y:y + bh, x:x + bw] == i].max()) * s * 3840 / W
            if thick < min_side:
                continue
            found.append((kind, x * s, y * s, (x + bw) * s, (y + bh) * s, int(area)))
            mask |= lab == i
    return found, cv2.resize(mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)


def wet_structure(plate, outdoor, disp, glass, min_area=400, min_side=8):
    """The other half of the dry-pocket check (L57 asks both ways; user 2026-10-21 on the pixel greenhouse: rain over the
    door and its handle, a request he had made before): inside and around the glass
    panes, anything thin that stands clearly nearer than what is around it and is colored unlike the view beside it (a
    frame, a mullion, a door's stiles and handle, a stake's tip) is structure, and rain drawn over it gives the picture
    away. Uses plate_prep's frame test at a higher bar (0.02), so a mask made any other way (a hand polygon, a pane's
    rectangle, gap fill) is held to it too. Slivers thinner than min_side px along an edge are the mask's soft rim, not
    a wet bar. plate: RGB floats 0..1. Returns [(x0, y0, x1, y1, area px at 4K)] and the mask."""
    from cozy.masks import pane_structure
    H, W = outdoor.shape
    zone = cv2.dilate(glass.astype(np.uint8), np.ones((int(0.016 * W) | 1,) * 2, np.uint8)).astype(bool)
    cand = (outdoor > 0.5) & pane_structure(plate, disp, zone, outdoor > 0.5, 0.02)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
    dist = cv2.distanceTransform(cand.astype(np.uint8), cv2.DIST_L2, 3)
    found, mask = [], np.zeros((H, W), bool)
    k = (3840 / W) ** 2
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area * k < min_area:
            continue
        if 2 * float(dist[y:y + bh, x:x + bw][lab[y:y + bh, x:x + bw] == i].max()) * 3840 / W < min_side:
            continue
        found.append((int(x), int(y), int(x + bw), int(y + bh), int(area * k)))
        mask |= lab == i
    return found, mask


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    a = ap.parse_args()
    pd = ROOT / "out" / "plates" / a.scene
    spec_p = ROOT / "scenes" / a.scene / "scene.json"
    spec = json.loads(spec_p.read_text(encoding="utf-8")) if spec_p.exists() else {}
    plate = np.asarray(Image.open(pd / "plate.png").convert("RGB"), np.float32) / 255
    H, W = plate.shape[:2]
    masks = np.asarray(Image.open(pd / "masks.png").convert("RGB"), np.float32) / 255
    lights = np.asarray(Image.open(pd / "lights.png").convert("RGB"), np.float32) / 255
    outdoor = lights[..., 1]
    ground = masks[..., 1] * np.clip((outdoor - 0.2) / 0.6, 0, 1)
    upright = np.zeros_like(ground)
    if (pd / "depth.png").exists() and (ground > 0.5).sum() > 2000:
        from cozy.masks import flat_surface
        disp = np.asarray(Image.open(pd / "depth.png"), np.float32) / 65535
        upright = ground * (1 - flat_surface(disp, ground, W / 1920))
        if (pd / "gaps.png").exists():   # ground seen between a stool's legs: the depth there is the stool's smear
            upright *= 1 - np.asarray(Image.open(pd / "gaps.png").convert("L"), np.float32) / 255
    pj = json.loads((pd / "plate.json").read_text(encoding="utf-8"))
    # dry on purpose: pets, food and drink, candles, fire (DRY_KINDS in cozy/masks.py) and hand regions marked "dry"
    keep = np.zeros((H, W), np.float32)
    glass = np.zeros((H, W), bool)
    if (pd / "regions.png").exists() and (pd / "regions.json").exists():
        from cozy.masks import DRY_KINDS
        ids = np.asarray(Image.open(pd / "regions.png").convert("RGB"))[..., 0]
        regs = json.loads((pd / "regions.json").read_text(encoding="utf-8"))
        regs = regs["regions"] if isinstance(regs, dict) else regs
        keep = cv2.dilate(np.isin(ids, [g["id"] for g in regs if g["kind"] in DRY_KINDS or g.get("dry")]).astype(np.uint8),
                          np.ones((9, 9), np.uint8)).astype(np.float32)
        glass = np.isin(ids, [g["id"] for g in regs if g["kind"] == "glass"])
    if (pd / "gap_parts.png").exists():   # a stool's back legs seen between its front legs: dry on purpose
        keep = np.maximum(keep, np.asarray(Image.open(pd / "gap_parts.png").convert("L"), np.float32) / 255)
    if (pd / "shelter.png").exists():     # under a cover a character holds up (an umbrella leaf): dry on purpose (L156)
        sh = np.asarray(Image.open(pd / "shelter.png").convert("RGB"), np.float32) / 255
        keep = np.maximum(keep, np.maximum(sh[..., 0], sh[..., 1]))
    # what tools/outdoor_check.py found inside under the weather and cut (a vine's leaves in front of a pane, with a cell
    # around them): dry on purpose, or the two checks send each other's fixes back (2026-10-21)
    hp = ROOT / "assets" / "keyart" / f"{spec.get('plate', a.scene)}.hand.json"
    cuts = json.loads(hp.read_text(encoding="utf-8")).get("outdoor_cuts") if hp.exists() else None
    if cuts:
        from cozy.masks import poly_mask
        keep = np.maximum(keep, cv2.dilate((poly_mask((W, H), cuts) > 0.5).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(np.float32))
    pockets, pmask = [], None
    wets, wmask = [], None
    if (pd / "depth.png").exists():
        disp = np.asarray(Image.open(pd / "depth.png"), np.float32) / 65535
        horizon = next((float(x["horizon"]) for x in [spec.get("plate_fx", {})] if "horizon" in x), 0.45)
        pockets, pmask = dry_pockets(outdoor, ground, disp, keep, horizon)
        if glass.any():
            wets, wmask = wet_structure(plate, outdoor, disp, glass)
    img = plate * 0.45
    img[..., 2] += 0.35 * outdoor * (1 - ground)
    img[..., 1] += 0.45 * (ground - upright)
    img[..., 0] += 0.8 * upright
    img = (np.clip(img, 0, 1) * 255).astype(np.uint8).copy()
    if pmask is not None and pmask.any():
        cs, _ = cv2.findContours(pmask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cs, -1, (255, 140, 0), max(3, int(4 * W / 3840)))
    if wmask is not None and wmask.any():
        cs, _ = cv2.findContours(wmask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cs, -1, (255, 30, 30), max(3, int(4 * W / 3840)))
    r = max(2, int(5 * W / 3840))
    for b in pj.get("beads", []):
        cv2.circle(img, (int(b[0]), int(b[1])), r, (255, 255, 0), -1)
    for s in pj.get("strand_drips", []):
        x, y, _, stop = s[:4]
        cv2.line(img, (int(x), int(y)), (int(x), int(min(stop, H - 1))), (0, 255, 255), 2)
        cv2.circle(img, (int(x), int(y)), r + 1, (0, 255, 255), -1)
    for ro in spec.get("runoff", []):
        cv2.circle(img, (int(ro["x"] * W), int(ro["y"] * H)), 2 * r, (255, 0, 255), -1)
    Image.fromarray(img).save(pd / "weather_audit_full.png")
    Image.fromarray(img).resize((1920, 1080), Image.LANCZOS).save(pd / "weather_audit.jpg", quality=88)
    up = float((upright > 0.5).sum()) / max(float((ground > 0.5).sum()), 1)
    print(f"{a.scene}: rain {float((outdoor > 0.5).mean()) * 100:.1f}% of the frame, wet ground {float((ground > 0.5).mean()) * 100:.1f}%"
          f" ({up * 100:.1f}% of it upright by depth), {len(pj.get('beads', []))} hanging drops, {len(pj.get('strand_drips', []))} live drips,"
          f" {len(spec.get('runoff', []))} runoff sources -> {pd / 'weather_audit.jpg'}")
    # each pocket as a 1:1 crop next to the plate, to look at before any render
    pdir = pd / "audit_pockets"
    if pdir.exists():
        for p in pdir.glob("*.jpg"):
            p.unlink()
    if pockets:
        pdir.mkdir(exist_ok=True)
        pl8 = (plate * 255).astype(np.uint8)
        for i, (kind, x0, y0, x1, y1, area) in enumerate(pockets):
            m = 60
            X0, Y0, X1, Y1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
            Image.fromarray(np.concatenate([pl8[Y0:Y1, X0:X1], img[Y0:Y1, X0:X1]], 1)).save(pdir / f"{i:02d}_{kind}.jpg", quality=90)
        print(f"  CHECK: {len(pockets)} dry pocket(s) where the depth says open air or wet ground but no {', no '.join(sorted({p[0] for p in pockets}))} "
              f"falls (orange in the audit; crops in {pdir}):")
        for kind, x0, y0, x1, y1, area in pockets:
            print(f"    no {kind:5s} at x {x0}-{x1}, y {y0}-{y1} px ({area} px)")
        print("  Gaps between legs, balusters or posts must take the weather; a real dry spot (under an eave, a covered "
              "step) is fine: say why in the hand.json note.")
    else:
        print("  no dry pockets: the rain and the wet ground reach every gap the depth shows")
    fdir = pd / "audit_frames"
    if fdir.exists():
        for p in fdir.glob("*.jpg"):
            p.unlink()
    if wets:
        fdir.mkdir(exist_ok=True)
        pl8 = (plate * 255).astype(np.uint8)
        for i, (x0, y0, x1, y1, area) in enumerate(wets):
            m = 60
            X0, Y0, X1, Y1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
            Image.fromarray(np.concatenate([pl8[Y0:Y1, X0:X1], img[Y0:Y1, X0:X1]], 1)).save(fdir / f"{i:02d}_frame.jpg", quality=90)
        print(f"  CHECK: {len(wets)} wet frame part(s): rain over thin structure in or around the glass (a frame, a mullion, "
              f"a handle; red in the audit; crops in {fdir}):")
        for x0, y0, x1, y1, area in wets:
            print(f"    rain over structure at x {x0}-{x1}, y {y0}-{y1} px ({area} px)")
        print("  Frames stay dry (plate_prep frame cut): find what put rain there (a hand outdoor polygon, a pane's rectangle) "
              "and fix the mask; if it really is the view (a far post), say why in the hand.json note.")
    elif glass.any():
        print("  no wet frames: the rain stops at every frame, mullion and handle in the glass")
    return 1 if pockets or wets else 0


if __name__ == "__main__":
    sys.exit(main())
