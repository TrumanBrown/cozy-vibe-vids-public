"""The weather masks (TASKS.md T16), moved verbatim from plate_prep.py.

  masks          outdoors (where rain and snow can be), wet ground and water, sky, foliage and lights; writes
                 frames.png, shelter.png, gaps.png and gap_parts.png
  depth_split    the valley between the view's depth and the near frames and posts ("outdoor_disp": "auto")
  gap_fill       the view and the wet ground carried on behind near things (a stool's legs, a railing)
  shelters       what a cover a character holds up keeps dry (SHELTER_SPREAD, SHELTER_LEAN)
  flow_map       flow.png: the waterfalls' flow
"""
import cv2
import numpy as np
from PIL import Image

from cozy.masks import flat_surface, pane_structure, poly_mask, region_raster
from cozy.plate.primitives import guided_filter, local_var, poly_bbox, soften


def depth_split(v, min_gap=10):
    """Threshold between a far mode (the view outside) and a near mode (frames, posts, railings) of
    disparity values in 0..1, or None if the histogram has no clear valley (one mode: keep it all).
    min_gap: the least distance between the two modes, in bins of 1/128."""
    h, e = np.histogram(v, bins=128, range=(0, 1))
    h = np.convolve(h.astype(np.float64), np.hanning(7) / np.hanning(7).sum(), mode="same")
    pk = [i for i in range(1, 127) if h[i] >= h[i - 1] and h[i] >= h[i + 1] and h[i] > 0.02 * h.max()]
    best = None
    for i in pk:
        for j in pk:
            if j <= i or (j - i) < min_gap:
                continue
            k = i + int(np.argmin(h[i:j + 1]))
            depth = h[k] / min(h[i], h[j])
            if depth < 0.35 and (best is None or depth < best[0]):
                best = (depth, (e[k] + e[k + 1]) / 2)
    return None if best is None else float(best[1])


def _last_idx(mask, axis):
    """Index of the last True at or before each position along `axis` (-10**9 where there is none)."""
    n = mask.shape[axis]
    shp = [1, 1]
    shp[axis] = n
    a = np.where(mask, np.arange(n, dtype=np.int32).reshape(shp), np.int32(-10 ** 9))
    return np.maximum.accumulate(a, axis=axis)


def _next_idx(mask, axis):
    """Index of the next True at or after each position along `axis` (10**9 where there is none)."""
    n = mask.shape[axis]
    shp = [1, 1]
    shp[axis] = n
    a = np.where(mask, np.arange(n, dtype=np.int32).reshape(shp), np.int32(10 ** 9))
    return np.flip(np.minimum.accumulate(np.flip(a, axis), axis=axis), axis)


def gap_fill(outdoor, water, disp, cut, base, r, horizon=0.45):
    """The view and the wet ground go on behind near things standing in the opening (a stool's legs, a railing's
    balusters, a chair): what shows between their parts is the scene behind them, out in the weather. The depth
    model smears thin near structures over those gaps (Treetop's railing, 2026-10-16) and a box cut swallows them
    (the ramen stool, 2026-10-19). Gaps = pixels outside `cut` (cover polygons, near regions, hand cuts) with the
    same cut object on both sides within ~160 px at 4K and above them within ~320 px (it closes the gap over the
    top), in the opening (`base`).
    - outdoor: a gap pixel clearly farther than the object around it (disparity under 0.9 x the local mean of the
      cut's disparity) is outdoors;
    - wet: an outdoor, not yet wet gap pixel below the horizon is wet ground when wet ground is seen across the
      object's parts in the same row (only things indoors stop the look across), or lies right above or below it in
      the same column, and its disparity agrees with the wet ground of its row (level ground is at one distance per
      row; a wall or riser is not).
    Returns the new outdoor and water masks and the numbers of pixels filled."""
    H, W = disp.shape
    cb = cut > 0.5
    if not cb.any():
        return outdoor, water, 0, 0, np.zeros((H, W), bool), np.zeros((H, W), bool)
    reach = int(160 * r)
    xi = np.arange(W, dtype=np.int32)[None, :]
    yi = np.arange(H, dtype=np.int32)[:, None]
    # a gap lies between two parts of the same object (the stool's legs), not between two different things (the cat
    # and the awning post, with a wall between them)
    _, lab = cv2.connectedComponents(cb.astype(np.uint8), connectivity=8)
    li, ni = _last_idx(cb, 1), _next_idx(cb, 1)
    ll = np.take_along_axis(lab, np.clip(li, 0, W - 1), axis=1)
    rl = np.take_along_axis(lab, np.clip(ni, 0, W - 1), axis=1)
    # and the object closes it over the top (a stool's seat over its legs, a railing's top rail over its balusters):
    # a wall seen beside a cat sitting on the stool is not a gap
    ai = _last_idx(cb, 0)
    al = np.take_along_axis(lab, np.clip(ai, 0, H - 1), axis=0)
    gap = (xi - li <= reach) & (ni - xi <= reach) & (ll == rl) & (ll > 0) & ~cb & (base > 0.5) & (yi - ai <= 2 * reach) & (al == ll)
    sig = 40 * r
    den = cv2.GaussianBlur(cb.astype(np.float32), (0, 0), sig)
    ref = cv2.GaussianBlur((disp * cb).astype(np.float32), (0, 0), sig) / np.maximum(den, 1e-4)
    # and clearly farther than the object's own parts beside it in the same row: what lies ON a surface seen at a slant
    # (a petal or a saucer on the tea house's table top: holes in SAM's outline of the table) is as near as the surface
    # around it, while the local mean takes in the table's nearer half, so it passed as a gap and rain was drawn over
    # the petal (2026-10-22); between a stool's legs the street is far behind the legs on both sides
    k_in = max(2, int(3 * r))
    dl = np.take_along_axis(disp, np.clip(li - k_in, 0, W - 1), axis=1)
    dr = np.take_along_axis(disp, np.clip(ni + k_in, 0, W - 1), axis=1)
    side = np.minimum(dl, dr)
    out = outdoor.copy()
    far = gap & (den > 0.02) & (disp < 0.9 * ref) & (disp < 0.9 * side) & (out < 0.5)
    out[far] = 1.0
    wet = water.copy()
    # the wet ground's disparity per row (median, gaps between rows interpolated, smoothed)
    wm = wet > 0.5
    rows = np.full(H, np.nan, np.float32)
    for y in np.flatnonzero(wm.sum(1) >= 8):
        rows[y] = np.median(disp[y][wm[y]])
    ok = ~np.isnan(rows)
    added_w = 0
    if ok.sum() >= 3:
        rows = np.interp(np.arange(H), np.flatnonzero(ok), rows[ok]).astype(np.float32)
        rows = cv2.GaussianBlur(rows.reshape(-1, 1), (0, 0), 8 * r).ravel()
        agree = np.abs(disp - rows[:, None]) <= 0.3 * rows[:, None] + 0.01
        below = yi >= int(horizon * H)
        for _ in range(4):
            o, wt = out > 0.5, wet > 0.5
            cand = o & ~wt & gap & below & agree
            if not cand.any():
                break
            block = ~(cb | o)            # only things indoors stop it; outdoor seams along the object's outline don't
            fill = np.zeros_like(cand)
            for flip in (False, True):
                c_, w_, b_, d_ = (x[:, ::-1] if flip else x for x in (cb, wt, block, cand))
                lw, lc, lb = _last_idx(w_, 1), _last_idx(c_, 1), _last_idx(b_, 1)
                f = d_ & (lw > lb) & (lc > lw) & (xi - lw <= 2 * reach)
                fill |= f[:, ::-1] if flip else f
            ln, nx = _last_idx(~cand, 0), _next_idx(~cand, 0)
            above = np.take_along_axis(wt, np.clip(ln, 0, H - 1), axis=0) & (ln >= 0) & (yi - ln <= reach)
            under = np.take_along_axis(wt, np.clip(nx, 0, H - 1), axis=0) & (nx < H) & (nx - yi <= reach)
            fill |= cand & (above | under)
            if not fill.any():
                break
            wet[fill] = 1.0
            added_w += int(fill.sum())
    filled = (wet > 0.5) & ~(water > 0.5)
    # Parts of the object seen through its own gaps (a stool's back legs and rungs between its front legs) are no
    # open air: the depth model puts them almost as far as the street behind (ramen stool: 0.30-0.35 against 0.28),
    # so the depth test above let them through and rain fell over the back legs (user 2026-10-19, round 3). Below
    # the horizon a gap shows the ground; anything in it nearer than the wet ground of its row is in front of the
    # ground: a part of the object. (Above the horizon a gap shows far things at any depth, so nothing is cut there.)
    gm = (wet > 0.5)
    band = max(2, int(4 * r))
    gref = np.full(H, np.nan, np.float32)
    for y in range(int(horizon * H), H):
        sl = slice(max(0, y - band), y + band + 1)
        v = disp[sl][gm[sl]]
        if v.size >= 30:
            gref[y] = np.median(v)
    with np.errstate(invalid="ignore"):
        nearer = disp > 1.05 * gref[:, None] + 0.004
    parts = gap & np.nan_to_num(nearer, nan=0).astype(bool) & ((out > 0.5) | gm)
    k = max(3, int(3 * r) | 1)
    parts = cv2.morphologyEx(parts.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab2, st, _ = cv2.connectedComponentsWithStats(parts, 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= int(120 * r * r)
    parts = keep[lab2]
    out[parts] = 0.0
    wet[parts] = 0.0
    filled &= ~parts
    return out, wet, int(far.sum()), added_w, filled, parts


def _erf(x):
    """erf for numpy arrays, to 1.5e-7 (Abramowitz and Stegun 7.1.26)."""
    s = np.sign(x)
    x = np.abs(x)
    t = 1 / (1 + 0.3275911 * x)
    return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x))


SHELTER_SPREAD = float(np.tan(np.radians(6)))   # how far the rain's slant wanders (gusts, turbulence): the penumbra
SHELTER_LEAN = 0.046   # its mean slant: rain.js's default 0.3 m/s wind over a 2 mm drop's 6.5 m/s fall, to the right


def shelters(ov, W, H):
    """What a cover a character holds up keeps dry (hand.json region "shelter": true, a leaf held as an umbrella):
    (rain cut, ground cut), 0..1 at plate size, or None. Straight under the cover the rain is gone; with the distance
    below it the edge softens, because drops come in at angles that wander with the wind (a penumbra: the cover's
    width blurred by distance x tan 6 deg, leaning with the mean wind, "shelter_lean" on the region), down to the
    ground at the holder's feet, which is dry over an ellipse as wide as the cover and its penumbra there and a quarter
    as deep, the rain's cut ending on its near edge. The
    Burdock Shelter's salamander held its salal leaf over itself and its lantern, and the rain fell and splashed right
    under it (Truman 2026-10-26: rain fell under the covered lantern; L156)."""
    covers = [rg for rg in ov.get("regions") or [] if rg.get("shelter") and rg.get("polys")]
    if not covers:
        return None
    pets = [rg for rg in ov.get("regions") or [] if rg.get("kind") == "pet" and rg.get("polys")]
    s4 = W / 3840
    rain = np.zeros((H, W), np.float32)
    ground = np.zeros((H, W), np.float32)
    xx = np.arange(W, dtype=np.float32)[None, :]
    for cv in covers:
        m = region_raster(cv, W, H) > 0.5
        cols = np.nonzero(m.any(0))[0]
        if len(cols) < 4:
            continue
        x0, x1 = int(cols.min()), int(cols.max())
        # the holder: the character overlapping the cover's columns most; its lowest row there is its feet
        feet, best = None, 0
        for pt in pets:
            pm = region_raster(pt, W, H)[:, x0:x1 + 1] > 0.5
            n = int(pm.any(0).sum())
            if n > best:
                best, feet = n, int(np.nonzero(pm.any(1))[0].max())
        if feet is None:
            print(f"  shelter {cv.get('name')}: no character under it, skipped")
            continue
        lean = float(cv.get("shelter_lean", SHELTER_LEAN))
        low = np.where(m, np.arange(H, dtype=np.float32)[:, None], -1).max(0)      # the cover's underside, per column
        idx = np.arange(W)
        top = np.interp(idx, idx[low >= 0], low[low >= 0]).astype(np.float32)      # its end heights carried past its ends
        yu = float(np.median(low[cols]))
        hf = 0.25 * (x1 - x0) / 2                  # the dry ground's half-depth on screen
        y0, y1 = int(max(0, top.min())), int(min(H, feet + 1.2 * hf + 2))
        yy = np.arange(y0, y1, dtype=np.float32)[:, None]

        def width(d):
            sig = 2 * s4 + d * SHELTER_SPREAD
            return 0.5 * (_erf((xx - (x0 + d * lean)) / (np.sqrt(2) * sig)) - _erf((xx - (x1 + d * lean)) / (np.sqrt(2) * sig)))
        # the dry ground: an ellipse around the holder's feet (a level patch seen in perspective), as wide as the cover
        # plus the penumbra there, soft at its rim; the rain's cut ends on its near edge, so no straight line is left
        dg = float(max(feet - yu, 0))
        sg = 2 * s4 + dg * SHELTER_SPREAD
        cxg, ax = (x0 + x1) / 2 + dg * lean, (x1 - x0) / 2 + sg
        rho = np.sqrt(((xx - cxg) / ax) ** 2 + ((yy - feet) / hf) ** 2)
        ground[y0:y1] = np.maximum(ground[y0:y1], np.clip((1.2 - rho) / 0.6, 0, 1))
        near_edge = feet + hf * np.sqrt(np.clip(1 - ((xx - cxg) / ax) ** 2, 0, 1))
        p = width(np.maximum(yy - yu, 0))
        below = np.clip((yy - top[None, :]) / (6 * s4), 0, 1)
        end = np.clip((near_edge - yy) / (0.6 * hf) + 0.3, 0, 1)
        rain[y0:y1] = np.maximum(rain[y0:y1], p * below * end)
        print(f"  shelter {cv.get('name')}: rain kept off under it down to the holder's feet (y {feet / H:.3f}), "
              f"penumbra {sg:.0f} px there")
    return rain, ground


def masks(img, disp, ov, out_dir=None, cell=None):
    """The weather masks of a plate, each 0..1 at its size: outdoors (where rain and snow fall), sky, water and wet
    ground, foliage and lights, from its depth, its colors and the masks json (ov: polygons, regions and switches; the
    regions of characters and what they hold are marked dry in it). Writes frames.png, gaps.png, gap_parts.png and
    shelter.png into out_dir when given. Pixel art (cell: its grid's cell px) keeps strips under 3 cells dry."""
    a = np.asarray(img, np.float32) / 255
    H, W = disp.shape
    r = W / 1920
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mx, mn = a.max(-1), a.min(-1)
    sat = (mx - mn) / (mx + 1e-6)
    yy = np.repeat(np.linspace(0, 1, H, dtype=np.float32)[:, None], W, 1)
    base, sel_masks, panes = _outdoor_regions(ov, W, H)
    base_all = base if base is not None else np.ones((H, W), np.float32)
    od = _outdoor_split(ov, disp, base, sel_masks)
    soft = 0.012
    thr, frames = _frame_cut(a, disp, panes, od, ov, W, H)
    raw = np.clip((thr + soft - disp) / (2 * soft), 0, 1).astype(np.float32)
    if frames.any():
        raw = raw * (1 - frames)
    if out_dir is not None:
        Image.fromarray((frames * 255).astype(np.uint8)).save(out_dir / "frames.png")
    if base is not None:
        raw = raw * base
    outdoor = np.clip(guided_filter(lum.astype(np.float32), raw, int(4 * r), 1e-3), 0, 1)
    outdoor = np.clip((outdoor - 0.15) / 0.7, 0, 1)  # tighten: prefer excluding over leaking
    ch = _auto_masks(a, lum, sat, yy, disp, outdoor, ov, r)
    _hand_polygons(ch, ov, disp, W, H, r)
    cut = _dry_regions(ch, ov, W, H, r)
    if ov.get("not_outdoor"):
        cut = np.maximum(cut, _not_mask(ov, "outdoor", disp, W, H, r))
    _level_water(ch, ov, disp, W, H, r)
    gaps, parts = _gaps(ch, ov, disp, cut, base_all, W, H, r)
    # a hand polygon around a pane takes in what stands in front of it too (the greenhouse's left panes took tomato
    # leaves), and gap fill can carry the view over a frame: the frame cut wins over both
    if frames.any():
        ch["outdoor"] = ch["outdoor"] * (1 - frames)
    _slivers(ch, ov, cell)
    _shelter(ch, ov, W, H, out_dir)
    _frame_edges(ch, W, H, r)
    # the wet ground filled in behind near objects (weather_audit trusts it: the depth there is the object's smear),
    # and the object's own parts seen in its gaps (weather_audit counts them as dry on purpose)
    if out_dir is not None:
        Image.fromarray((gaps * 255).astype(np.uint8)).save(out_dir / "gaps.png")
        Image.fromarray((parts * 255).astype(np.uint8)).save(out_dir / "gap_parts.png")
    return {"sky": soften(ch["sky"], 3 * r), "water": soften(ch["water"], 3 * r), "foliage": soften(ch["foliage"], 2 * r),
            "lights": soften(ch["lights"], 6 * r), "outdoor": ch["outdoor"]}


def _outdoor_regions(ov, W, H):
    """Outdoors: far by depth, edge-snapped to the image. With "outdoor_regions" (region kinds or names, e.g. ["glass"]
    for a window view, ["all"] for a scene that is outdoors everywhere) it is limited to them; "outdoor_disp": "auto"
    cuts near things (frames, posts) out of them only if depth has a clear valley. -> (base: what may be outdoors, None
    without outdoor_regions; the regions' own masks; each glass pane's area, its frame cut at its own depth)."""
    base = None
    sel_masks = None
    panes = []   # each glass pane's area (its mask, with its rectangle under pane_hull): its frame is cut at its own depth
    oregs = ov.get("outdoor_regions")
    if oregs:
        if "all" in oregs:
            base = np.ones((H, W), np.float32)
        else:
            base = np.zeros((H, W), np.float32)
            sel_masks = np.zeros((H, W), bool)
            for rg in ov.get("regions", []):
                if rg.get("kind") in oregs or rg.get("name") in oregs:
                    rm = region_raster(rg, W, H)
                    base = np.maximum(base, rm)
                    sel_masks |= rm > 0.5
                    if rg.get("kind") == "glass":
                        panes.append(rm > 0.5)
                    # SAM can outline a pane's sky and leave out what is seen through it (the pixel greenhouse's far
                    # barn and silo stayed dry, 2026-10-21): with "pane_hull": true the pane takes part with its whole
                    # rectangle (the smallest one around its mask, turned with it; a convex hull still cut a notched
                    # corner off) and the model's own box for it, and the depth split below keeps only what is as far
                    # as the view. Opt-in: on the rainy cafe and the wizard library the soft depth let a window's sill,
                    # a table's edge, the stone around arch tops and a globe in (2026-10-21)
                    if ov.get("pane_hull", False) and rg.get("kind") in ("glass", "opening"):
                        hull = np.zeros((H, W), np.uint8)
                        cs, _ = cv2.findContours((rm > 0.5).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        if cs:
                            cv2.fillPoly(hull, [np.round(cv2.boxPoints(cv2.minAreaRect(np.concatenate(cs)))).astype(np.int32)], 1)
                        if rg.get("polys") and rg.get("box"):
                            bx0, by0, bx1, by1 = rg["box"]
                            hull[int(by0 * H):int(np.ceil(by1 * H)), int(bx0 * W):int(np.ceil(bx1 * W))] = 1
                        base = np.maximum(base, hull.astype(np.float32))
                        if rg.get("kind") == "glass":
                            panes[-1] = panes[-1] | (hull > 0)
    return base, sel_masks, panes


def _outdoor_split(ov, disp, base, sel_masks):
    """The disparity below which the plate is outdoors: "outdoor_disp" (0.15), or "auto": the depth's valley."""
    od = ov.get("outdoor_disp", 0.15)
    if od == "auto":
        # measured on the regions' own masks: the panes' whole rectangles hold more frame, which pulled the greenhouse's
        # split from 0.113 to 0.090 and cut real view off its left panes
        sel = sel_masks if sel_masks is not None and sel_masks.any() else base > 0.5 if base is not None else np.ones(disp.shape, bool)
        cut = depth_split(disp[sel]) if sel.any() else None
        od = cut if cut is not None else 1.05
        print(f"  outdoor_disp auto: {'%.3f' % od if cut is not None else 'none (one depth mode)'}")
    return float(od)


def _frame_cut(a, disp, panes, od, ov, W, H):
    """-> (the split per pixel, the panes' structure kept dry). A glass pane's frame, mullions and a door's stiles and
    handle stood at disparity 0.07-0.10 on the pixel greenhouse's back wall, the view behind them 0.01-0.04, and the one
    split for the whole room (0.113, between the back wall and the near side walls) let them all rain (Truman 2026-10-21,
    rain over the door and its handle, a request he had made before). Each pane splits again on
    its own far pixels, and inside the glass anything thin that stands clearly nearer than what is around it (a white
    top-hat of the depth, wider than any frame bar) is structure, never view. Prefer a dry strip by a frame over rain on
    it. "frame_cut": false turns both off."""
    thr = np.full((H, W), od, np.float32)
    frames = np.zeros((H, W), bool)
    if panes and ov.get("frame_cut", True):
        for pm in panes:
            v = disp[pm & (disp < od)]
            loc = depth_split(v, min_gap=6) if v.size > 2000 else None
            if loc is not None and loc < od:
                thr[pm] = np.minimum(thr[pm], loc)
        glass = np.logical_or.reduce(panes)
        # 0.015: the greenhouse's roof beam, a rail's corner and a mullion's edge stood 0.02-0.034 nearer than the view
        # beside them; weather_audit's wet-frame check holds the mask to 0.02
        frames = pane_structure(a, disp, glass, disp < thr, 0.015, thr, od)
        print(f"  frame cut: {int(frames.sum())} px of pane structure kept dry (per-pane splits: "
              f"{sorted({round(float(t), 3) for t in np.unique(thr) if t < od})})")
    return thr, frames


def _auto_masks(a, lum, sat, yy, disp, outdoor, ov, r):
    """The masks found in the picture itself: smooth far sky, outdoor ground low in the frame, warm leaves indoors and
    bright warm lights (an analyzed scene, "auto_masks": false, takes sky, water and foliage from polygons only)."""
    smooth = local_var(lum, max(2, int(3 * r))) < 0.0015
    far_lim = max(float(np.percentile(disp[outdoor > 0.5], 25)), 0.005) if (outdoor > 0.5).any() else 0.02
    sky = (outdoor > 0.5) & smooth & (disp <= far_lim) & (yy < 0.6)
    water = (outdoor > 0.5) & (yy > 0.35)
    warm_leaf = (sat > 0.45) & (a[..., 0] > a[..., 2] + 0.12) & (lum > 0.16) & (a[..., 1] < a[..., 0] * 0.8)
    foliage = warm_leaf & (outdoor < 0.5)
    if ov.get("auto_masks") is False:   # analyzed scenes: sky/water/foliage come only from polygons
        sky, water, foliage = np.zeros_like(sky), np.zeros_like(water), np.zeros_like(foliage)
    lights = (lum > 0.82) & (a[..., 0] > 0.85) & (sat > 0.25)
    return {"sky": sky.astype(np.float32), "water": water.astype(np.float32), "foliage": foliage.astype(np.float32),
            "lights": lights.astype(np.float32), "outdoor": outdoor}


def _not_mask(ov, k, disp, W, H, r):
    # a cover's outline with the openings its parts enclose taken out (a chair's rungs, a railing's bars:
    # tools/analyze_plate.py "not_<k>_holes"); gap_fill below decides what shows through them
    m = poly_mask((W, H), ov[f"not_{k}"])
    if ov.get(f"not_{k}_holes"):
        m = m * (1 - _see_through_holes(ov[f"not_{k}_holes"], m, disp, W, H, r))
    # hand.json "<k>_open": open view an analysis cover took in (the Burdock Shelter's leaf, traced with the dark
    # forest above it, left that forest dry: the rain stopped at a straight vertical line, 2026-10-25, L146)
    if ov.get(f"{k}_open"):
        m = m * (1 - poly_mask((W, H), ov[f"{k}_open"]))
    # what the agent or tools/outdoor_check.py cut stays cut, holes or open polygons or not: the holes undid
    # outdoor_check's repairs wherever they overlapped, and three rounds never converged on the tea house's table
    # and rafter (2026-10-22)
    keep = list(ov.get({"outdoor": "outdoor_cuts", "water": "water_cuts"}.get(k, "")) or []) if (ov.get(f"not_{k}_holes") or ov.get(f"{k}_open")) else []
    if ov.get(f"{k}_open"):
        keep += list(ov.get(f"_hand_not_{k}") or [])
    if keep:
        m = np.maximum(m, poly_mask((W, H), keep))
    return m


def _see_through_holes(polys, cover, disp, W, H, r):
    """The holes that are openings: clearly farther than the cover around them (the field between a rocking
    chair's rungs). SAM also leaves holes where something lies on the cover (a petal or a saucer on the tea
    house's table, 2026-10-22) or where its outline frays; those are as near as the cover and stay cut."""
    hm = np.zeros((H, W), np.float32)
    ring_k = np.ones((max(3, int(9 * r) | 1),) * 2, np.uint8)
    for poly in polys:
        one = poly_mask((W, H), [poly]) > 0.5
        if one.sum() < 4:
            continue
        ring = (cv2.dilate(one.astype(np.uint8), ring_k) > 0) & ~one & (cover > 0.5)
        if ring.sum() < 8 or float(np.median(disp[one])) < 0.85 * float(np.median(disp[ring])):
            hm[one] = 1.0
    return hm


def _hand_polygons(ch, ov, disp, W, H, r):
    """The masks json's polygons per mask: <k> adds, <k>_open adds open view, not_<k> cuts, only_<k> limits."""
    for k in ch:
        if ov.get(k):
            ch[k] = np.maximum(ch[k], poly_mask((W, H), ov[k]))
        if ov.get(f"{k}_open"):
            ch[k] = np.maximum(ch[k], poly_mask((W, H), ov[f"{k}_open"]))
        if ov.get(f"not_{k}"):
            ch[k] = ch[k] * (1 - _not_mask(ov, k, disp, W, H, r))
        if ov.get(f"only_{k}"):
            ch[k] = ch[k] * poly_mask((W, H), ov[f"only_{k}"])


def _dry_regions(ch, ov, W, H, r):
    """Regions marked "dry" (hand.json: cloth strips across the opening, a sign; the analysis cuts its own near
    objects through not_outdoor) are cut out of the outdoors, grown by ~4 px at 4K for their sway, so no rain or
    snow draws over them. A character is always dry, wherever it stands (nothing rains or drips on the pet, L19,
    L31), and so is what it holds or stands right beside (a lantern, a cup): out in the open it stands in front of
    the rain like any near object, the rain falling behind and around it (the Burdock Shelter's salamander under its
    leaf, 2026-10-25). A far lantern out in the view still takes the rain (L121). -> the cut (0 where nothing is)."""
    pets = [rg for rg in ov.get("regions") or [] if rg.get("kind") == "pet" and rg.get("polys")]
    held_kinds = ("lantern", "lamp", "candle", "steam", "screen", "bob", "chime")

    def grown_box(rg, f=0.25):
        x0, y0, x1, y1 = poly_bbox(rg["polys"])
        gx, gy = f * (x1 - x0), f * (y1 - y0)
        return x0 - gx, y0 - gy, x1 + gx, y1 + gy

    def overlaps(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    pet_boxes = [grown_box(rg) for rg in pets]
    for rg in ov.get("regions") or []:
        if rg.get("dry") or not rg.get("polys"):
            continue
        if rg.get("kind") == "pet" or (rg.get("kind") in held_kinds and any(overlaps(poly_bbox(rg["polys"]), b) for b in pet_boxes)):
            rg["dry"] = True
            rg.setdefault("dry_why", "a character" if rg.get("kind") == "pet" else "held by or beside a character")
    dry = [rg for rg in ov.get("regions") or [] if rg.get("dry")]
    if dry:
        k = max(3, int(4 * r) | 1)
        cut = np.zeros((H, W), np.float32)
        for rg in dry:
            cut = np.maximum(cut, region_raster(rg, W, H))
        cut = cv2.dilate((cut > 0.5).astype(np.uint8), np.ones((k, k), np.uint8)).astype(np.float32)
        ch["outdoor"] = ch["outdoor"] * (1 - cut)
        ruled = [rg["name"] for rg in dry if rg.get("dry_why")]
        print(f"  {len(dry)} dry region(s) cut out of the outdoors" + (f" ({', '.join(ruled)}: characters and what they hold)" if ruled else ""))
    else:
        cut = np.zeros((H, W), np.float32)
    return cut


def _level_water(ch, ov, disp, W, H, r):
    """Wet ground and water are level: rings never land on an upright surface the polygons overlap (analyzed
    scenes; "water_flat": false turns it off)."""
    if ov.get("water_flat", ov.get("auto_masks") is False) and ch["water"].any():
        fl = flat_surface(disp, ch["water"], r)
        # open water (a canal, a lake: regions of kind water) is level by nature; far away its depth is flat and
        # reads as upright, which left the canal's far band without rings (2026-10-19, round 2)
        for rg in ov.get("regions") or []:
            if rg.get("kind") == "water" and rg.get("polys"):
                fl = np.maximum(fl, region_raster(rg, W, H))
        n0 = float((ch["water"] > 0.5).sum())
        ch["water"] = ch["water"] * fl
        print(f"  water/ground kept on level surfaces only: -{(n0 - float((ch['water'] > 0.5).sum())) / max(n0, 1) * 100:.1f}% (walls, risers)")


def _gaps(ch, ov, disp, cut, base_all, W, H, r):
    """The view and the wet ground continue behind near things in the opening ("gaps": false turns it off). -> (what
    was filled in behind them, the parts of the objects seen through their own gaps, kept dry)."""
    if ov.get("gaps", True) and cut.any():
        ch["outdoor"], ch["water"], go, gw, gaps, parts = gap_fill(ch["outdoor"], ch["water"], disp, cut, base_all, r, ov.get("horizon", 0.45))
        ch["outdoor"] = ch["outdoor"] * (1 - cut)
        ch["water"] = ch["water"] * (1 - cut)
        if go or gw:
            print(f"  see-through gaps behind near objects: +{go} px outdoors, +{gw} px wet ground")
        if parts.any():
            print(f"  parts of near objects seen through their gaps (back legs, rungs) kept dry: {int(parts.sum())} px")
    else:
        gaps = parts = np.zeros((H, W), bool)
    return gaps, parts


def _slivers(ch, ov, cell):
    """Pixel art: weather in a strip under 3 cells wide shows as a column of stray rain cells hugging whatever borders
    it, not as rain behind the glass (the sliver of glass between the greenhouse's window post and its lantern, v7:
    Truman had flagged it, 2026-10-21). Such strips stay dry; weather_audit's dry pockets ignore
    strips under 24 px too. "slivers": false turns it off."""
    if cell and ov.get("slivers", True) is not False:
        k = max(3, int(round(3 * cell)))
        o = (ch["outdoor"] > 0.5).astype(np.uint8)
        op = cv2.morphologyEx(o, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        gone = int(o.sum()) - int(op.sum())
        if gone:
            ch["outdoor"] = ch["outdoor"] * cv2.dilate(op, np.ones((5, 5), np.uint8)).astype(np.float32)
            print(f"  slivers under 3 cells kept dry: {gone} px ({gone / max(int(o.sum()), 1) * 100:.1f}% of the outdoors)")


def _shelter(ch, ov, W, H, out_dir):
    """A cover a character holds up (an umbrella leaf) keeps the rain off the space under it and the ground below it;
    shelter.png (R rain, G ground) tells weather_audit it is dry on purpose (L156)."""
    sz = shelters(ov, W, H)
    if sz is not None:
        ch["outdoor"] = ch["outdoor"] * (1 - sz[0])
        ch["water"] = ch["water"] * (1 - sz[1])
        if out_dir is not None:
            Image.fromarray((np.stack([sz[0], sz[1], np.zeros_like(sz[0])], -1) * 255).round().astype(np.uint8)).save(out_dir / "shelter.png")
    elif out_dir is not None and (out_dir / "shelter.png").exists():
        (out_dir / "shelter.png").unlink()


def _frame_edges(ch, W, H, r):
    """The frame's outermost pixels follow the ones just inside: polygons traced at 1920 px wide stop a pixel or two
    short of the 4K frame's edge, so every cut along it (a cover, a hand or outdoor_check cut) left a 1-2 px line of
    rain down the frame's edge that no repair could reach (the tea house's right edge, 2026-10-22)."""
    for k_ in ("outdoor", "water"):
        c = ch[k_]
        b = max(2, int(round(r)))
        c[:, :b] = c[:, b:b + 1]
        c[:, W - b:] = c[:, W - b - 1:W - b]
        c[:b, :] = c[b:b + 1, :]
        c[H - b:, :] = c[H - b - 1:H - b, :]


def flow_map(img, ov):
    """Waterfall flow mask from "waterfall" polygons (each a thin band from the lip down to the foot):
    R = weight (soft edges; full on the bright, bluish falling water, a quarter elsewhere in the band so
    dark gaps between strands still move), G = progress from the polygon's top (0) to its bottom (1),
    B = the fall's height (uv) / 0.25."""
    polys = ov.get("waterfall")
    if not polys:
        return None
    a = np.asarray(img, np.float32) / 255
    H, W = a.shape[:2]
    r = W / 1920
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    gate = np.clip((a[..., 2] - a[..., 0] - 0.13) / 0.06, 0, 1) * np.clip((lum - 0.17) / 0.07, 0, 1)
    yy = np.repeat(np.linspace(0, 1, H, dtype=np.float32)[:, None], W, 1)
    band = np.zeros((H, W), np.float32)
    prog = np.zeros((H, W), np.float32)
    hgt = np.zeros((H, W), np.float32)
    for p in polys:
        m = poly_mask((W, H), [p])
        y0, y1 = min(v[1] for v in p), max(v[1] for v in p)
        band = np.maximum(band, m)
        prog = np.where(m > 0, np.clip((yy - y0) / max(y1 - y0, 1e-6), 0, 1), prog)
        hgt = np.where(m > 0, (y1 - y0) / 0.25, hgt)
    band = soften(band, 1.5 * r)
    k = np.ones((int(6 * r) | 1, int(6 * r) | 1), np.uint8)   # progress/height defined under the soft edge
    return np.stack([band * (0.25 + 0.75 * gate), cv2.dilate(prog, k), cv2.dilate(hgt, k)], -1)
