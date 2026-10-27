"""The named animation regions (TASKS.md T16), moved verbatim from plate_prep.py.

  render_regions     regions.png, views.png and regions.json from the masks json's "regions"
  regions_preview    regions_preview.png: each region tinted and labeled
  water_only         a water region without what stands in front of the water
  see_through        the water seen through a railing in front of a water region
  REGION_ANCHOR      each kind's default anchor; CONTAINERS, the kinds drawn first (glass, opening)
"""
import json

import cv2
import numpy as np
from PIL import Image

from cozy.masks import region_raster


# Named animation regions (masks json "regions", written by tools/analyze_plate.py or by hand): each has a
# kind (glass, fire, steam, sway, pendulum, bob, flow, twinkle, flicker, neon, candle, pet, puddle, ...),
# polygons or a box, and optional geometry (point, pivot, anchor, width, dir). Kinds that animate the plate
# itself (src/library/plate.js) read the region map; overlay layers (glass, steam, fire, particles) read it
# for their masks. Effect strengths live in the scene (scenes/<scene>/scene.json), not here.
REGION_ANCHOR = {"sway": "top", "curtain": "top", "plant": "bottom", "pendulum": "pivot", "chime": "pivot", "flame": "bottom"}


CONTAINERS = ("glass", "opening")


def see_through(m, disp, lab, W, H, reach=1.2):
    """Water (or sky) seen through a railing, fence or balustrade in front of it: the gaps below the region, within
    its column span, that are farther than the bars around them (a black top-hat on the disparity) and have the
    water's colors. Returns the extra pixels (bool), so a canal behind a railing flows in its gaps too."""
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    h = y1 - y0
    X0, X1 = max(0, int(x0 - 0.03 * (x1 - x0))), min(W, int(x1 + 0.03 * (x1 - x0)))
    Y0, Y1 = int(y0 + 0.3 * h), min(H, int(y1 + reach * h))
    if Y1 - Y0 < 8 or X1 - X0 < 8:
        return np.zeros_like(m)
    sub = (slice(Y0, Y1), slice(X0, X1))
    k = int(0.026 * W) | 1
    gap = cv2.morphologyEx(disp[sub], cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) - disp[sub]
    ab = lab[..., 1:][m]
    C = np.cov(ab.T) + np.eye(2) * 4.0
    d = lab[sub][..., 1:] - ab.mean(0)
    maha = np.sqrt(np.einsum("...i,ij,...j->...", d, np.linalg.inv(C), d))
    cand = ((gap > 0.004) & (maha < 3.0)).astype(np.uint8)
    # what is seen through a railing in front is the same flat water carried on toward us, so its disparity follows the
    # water's own by row (extrapolated from the water's nearest rows), never a nearer floor's: the Minecraft tea house's
    # glossy deck mirrors the pond, and the deck between the table's legs read as railing gaps (+127k px of deck taken
    # for water, which the ripple would have wobbled, 2026-10-22; the class of L82)
    rows = np.arange(y0, y1)
    med = np.array([np.median(disp[y][m[y]]) if m[y].sum() >= 8 else np.nan for y in rows], np.float32)
    ok = ~np.isnan(med)
    if ok.sum() >= 6:
        ry, rv = rows[ok], med[ok]
        near = ry >= ry[0] + 0.6 * (ry[-1] - ry[0])
        if near.sum() >= 3:
            slope, icpt = np.polyfit(ry[near].astype(np.float64), rv[near].astype(np.float64), 1)
            slope = max(0.0, float(slope))
            pred = (icpt + slope * np.arange(Y0, Y1)).astype(np.float32)
            pred = np.maximum(pred, float(rv[-1]))
            cand &= (disp[sub] <= (pred + np.maximum(0.03, 0.25 * pred))[:, None]).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lb, st, _ = cv2.connectedComponentsWithStats(cand, 8)
    keep = np.zeros(cand.shape, bool)
    # a gap of a railing shows water well behind its bars: on the ramen canal and the farm's fence the water is 8% to
    # 30 times farther (in disparity) than the bars around it; the tea house's wet stone beside the lantern's pedestal
    # and at the table's corner was 1-4% (2026-10-22)
    rel = gap / np.maximum(disp[sub], 1e-3)
    for i in range(1, n):
        if st[i][4] >= 0.00004 * W * H:
            sel = lb == i
            if float(np.median(rel[sel])) >= 0.06:
                keep |= sel
    out = np.zeros_like(m)
    out[sub] = keep & ~m[sub]
    return out


def water_only(m, disp):
    """Drop pixels of a water region that stand in front of the water (a post or a bank the polygon overlaps):
    flat water at a given row is at one distance, so anything clearly nearer than that row's water is not
    water. The row reference is a low percentile of the region's disparity in the row, smoothed over rows."""
    ys, xs = np.nonzero(m)
    if len(ys) < 50:
        return m
    y0, y1 = ys.min(), ys.max() + 1
    ref = np.full(y1 - y0, np.nan, np.float32)
    for y in range(y0, y1):
        v = disp[y][m[y]]
        if v.size >= 4:
            ref[y - y0] = np.percentile(v, 25)
    ok = ~np.isnan(ref)
    if ok.sum() < 3:
        return m
    ref = np.interp(np.arange(len(ref)), np.flatnonzero(ok), ref[ok]).astype(np.float32)
    ref = cv2.GaussianBlur(ref.reshape(-1, 1), (0, 0), 6).ravel()
    out = m.copy()
    band = out[y0:y1]
    band &= disp[y0:y1] <= (ref + np.maximum(0.006, 0.3 * ref))[:, None]
    out[y0:y1] = band
    return out


def render_regions(regions, disp, W, H, out, plate=None, outdoor=None, views_outdoor=True, no_view=()):
    """regions.png (R = region id 1..63, G = feathered weight, B = coordinate along the region's anchor axis: 0 at
    the anchor, 1 at the far end), views.png (R = id of the glass/opening region seen at each pixel, G = weight;
    zero where something nearer stands in front of it), regions.json and regions_preview.png.
    Draw order: containers (glass, opening) first, then the other regions far to near (nearer wins), then "under"
    regions (they fill only pixels nothing but a container claims). "on_top": true draws a region after the others of
    its group (a lantern's flame inside the lantern's own region). So what is seen through a window or an
    opening keeps its own region (a canal flows, a far plant sways), and glass.js reads views.png.
    A pane shows its rain only where it is seen through to the outdoors (`outdoor`, grown ~2 pixel-art cells to
    reach the frame): a pane's SAM mask can hold the plants standing in front of it, and glass.js ran drops and
    trickles down the pixel greenhouse's tomato plants (2026-10-21). "views_outdoor": false in the masks json
    turns that off; panes left with little view are listed.
    Water regions also take the water seen through a railing in front of them (see_through; "through": false
    turns it off)."""
    for f in ("regions.png", "regions.json", "regions_preview.png", "views.png"):
        (out / f).unlink(missing_ok=True)
    if not regions:
        return []
    r = W / 3840
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    yy /= H
    xx /= W
    lab = cv2.cvtColor(np.asarray(plate, np.float32) / 255, cv2.COLOR_RGB2Lab) if plate is not None else None
    items = []
    for rg in regions:
        m = region_raster(rg, W, H) > 0.5
        if not m.any():
            print(f"  region {rg.get('name')}: empty, skipped")
            continue
        dm = float(np.median(disp[m]))
        if rg.get("kind") == "water" and rg.get("through", True):
            n0 = int(m.sum())
            m = water_only(m, disp)
            if n0 - int(m.sum()) > 0:
                print(f"  region {rg.get('name')}: -{n0 - int(m.sum())} px standing in front of the water")
        if rg.get("kind") == "water" and lab is not None and rg.get("through", True):
            extra = see_through(m, disp, lab, W, H)
            if extra.any():
                print(f"  region {rg.get('name')}: +{int(extra.sum())} px of water seen through the railing in front")
                m = m | extra
        items.append((dm, rg, m))
    items.sort(key=lambda t: (t[1].get("kind") not in CONTAINERS, bool(t[1].get("under")), bool(t[1].get("on_top")), t[0]))
    if len(items) > 63:
        print(f"  note: {len(items)} regions, only the 63 nearest-first-kept are used")
        items = items[-63:]
    ids = np.zeros((H, W), np.uint8)
    wts = np.zeros((H, W), np.float32)
    axis = np.zeros((H, W), np.float32)
    vids = np.zeros((H, W), np.uint8)
    vwts = np.zeros((H, W), np.float32)
    is_cont = np.zeros(256, bool)
    dm_of = np.zeros(256, np.float32)
    meta = []
    for k, (dm, rg, m) in enumerate(items):
        rid = k + 1
        cont = rg.get("kind") in CONTAINERS
        is_cont[rid], dm_of[rid] = cont, dm
        fe = max(1.0, float(rg.get("feather", 3)) * r)
        rad = int(np.ceil(2 * fe))
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))
        # Water feathers inward: things in front of it (railing bars, posts, a bank) must not ripple with it,
        # so its weight is 0 at its edge and reaches 1 a little inside; other regions feather outward.
        inward = rg.get("feather_in", rg.get("kind") == "water")
        dil = m.copy() if inward else cv2.dilate(m.astype(np.uint8), ker) > 0
        if rg.get("under"):          # fills only pixels no other region claims (e.g. heat haze above a cup)
            dil &= (ids == 0) | is_cont[ids]
        soft = cv2.GaussianBlur(m.astype(np.float32), (0, 0), fe)
        soft = np.clip((soft - 0.5) / 0.4, 0, 1) if inward else np.clip((soft - 0.02) / 0.5, 0, 1)
        ys, xs = np.nonzero(m)
        x0, x1, y0, y1 = xs.min() / W, (xs.max() + 1) / W, ys.min() / H, (ys.max() + 1) / H
        anchor = rg.get("anchor") or REGION_ANCHOR.get(rg.get("kind"), "")
        if anchor == "top":
            a = (yy - y0) / max(y1 - y0, 1e-6)
        elif anchor == "bottom":
            a = (y1 - yy) / max(y1 - y0, 1e-6)
        elif anchor == "left":
            a = (xx - x0) / max(x1 - x0, 1e-6)
        elif anchor == "right":
            a = (x1 - xx) / max(x1 - x0, 1e-6)
        elif anchor == "pivot":
            px, py = rg.get("pivot") or [(x0 + x1) / 2, y0]
            d = np.hypot((xx - px) * W / H, yy - py)
            a = d / max(float(d[m].max()), 1e-6)
        else:
            a = np.zeros_like(xx)
        ids[dil] = rid
        wts[dil] = soft[dil]
        axis[dil] = np.clip(a[dil], 0, 1)
        if cont:
            vids[dil] = rid
            vwts[dil] = soft[dil]
        extra = {k2: v for k2, v in rg.items() if k2 not in ("polys", "box", "name", "kind")}
        meta.append({"id": rid, "name": rg.get("name", f"r{rid}"), "kind": rg.get("kind", ""),
                     "bbox": [round(float(v), 4) for v in (x0, y0, x1, y1)],
                     "center": [round(float(xs.mean() / W), 4), round(float(ys.mean() / H), 4)],
                     "area": round(float(m.mean()), 5), "disp": round(dm, 4), "anchor": anchor, **extra})
    # things clearly nearer than the window or opening they overlap stand in front of it: no glass there
    front = (ids > 0) & ~is_cont[ids] & (vids > 0) & (dm_of[ids] > dm_of[vids] + 0.02)
    vids[front] = 0
    vwts[front] = 0
    if outdoor is not None and views_outdoor:
        k = max(3, int(17 * r) | 1)
        seen = cv2.dilate((outdoor > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
        glass_ids = np.array([g["id"] for g in meta if g["kind"] == "glass"], np.int32)
        pane = np.isin(vids, glass_ids)
        for g in meta:
            if g["kind"] == "glass" and g["name"] not in no_view:
                pm = vids == g["id"]
                share = float((pm & seen).sum()) / max(int(pm.sum()), 1)
                if share < 0.2:
                    print(f"  ! glass {g['name']}: only {share:.0%} of it looks out (its mask may be what stands in front of "
                          "it, or the depth reads the pane as near): no rain on it there; fix the outdoors (hand.json "
                          "\"outdoor\") or list it in hand.json \"no_view\" with why")
        vids[pane & ~seen] = 0
        vwts[pane & ~seen] = 0
    Image.fromarray(np.stack([ids, np.round(wts * 255).astype(np.uint8), np.round(axis * 255).astype(np.uint8)], -1), "RGB").save(out / "regions.png")
    Image.fromarray(np.stack([vids, np.round(vwts * 255).astype(np.uint8), np.zeros_like(vids)], -1), "RGB").save(out / "views.png")
    (out / "regions.json").write_text(json.dumps(meta, indent=1))
    return meta


def regions_preview(plate, regions, out):
    """Plate dimmed, each region tinted in its own color with its name (check after every analysis)."""
    if not regions:
        return
    p = np.asarray(plate, np.float32) / 255
    rm = np.asarray(Image.open(out / "regions.png"), np.uint8)
    H, W = rm.shape[:2]
    pv = p * 0.5
    pal = np.array([[1, .3, .3], [.3, 1, .3], [.3, .5, 1], [1, 1, .3], [1, .3, 1], [.3, 1, 1], [1, .6, .2], [.6, .3, 1]], np.float32)
    for g in regions:
        sel = rm[..., 0] == g["id"]
        w = (rm[..., 1].astype(np.float32) / 255)[..., None]
        c = pal[(g["id"] - 1) % len(pal)]
        pv = np.where(sel[..., None], pv * (1 - 0.55 * w) + c * 0.55 * w, pv)
    pv = (np.clip(pv, 0, 1) * 255).astype(np.uint8).copy()
    for g in regions:
        c = tuple(int(v * 255) for v in pal[(g["id"] - 1) % len(pal)])
        x0, y0, x1, y1 = g["bbox"]
        cv2.rectangle(pv, (int(x0 * W), int(y0 * H)), (int(x1 * W), int(y1 * H)), c, 3)
        cv2.putText(pv, f"{g['id']} {g['name']} ({g['kind']})", (int(x0 * W) + 6, int(y0 * H) + 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 6)
        cv2.putText(pv, f"{g['id']} {g['name']} ({g['kind']})", (int(x0 * W) + 6, int(y0 * H) + 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, c, 2)
    Image.fromarray(pv).resize((1920, 1080), Image.LANCZOS).save(out / "regions_preview.png")
