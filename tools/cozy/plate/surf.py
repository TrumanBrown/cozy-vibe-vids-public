"""Surf on a painted sea (the tide pool, 2026-11-05: the waves breaking on the far rocks were painted, so their foam
would sit frozen). The foam stays the painting's own: plate.js brings it in with every wave of the timeline (scene.json
events.surf; one 'surf' event a wave): it rises to the painted foam as a wave breaks, peeling along the rocks and
riding shoreward, then settles back until the next one. The same waves drive the surf's sound (cozy/audio/ambience.py).

  surf_maps(plate, cfg, held, out)   from hand.json "surf": surf.png, one RGBA map (the plate shader had no texture unit
                                     left, so plate.js binds it where a waterfall's flow.png goes): R shoreward, 0 outside
                                     the zone, 0.02 at its far edge to 1 at its near edge; G along the shore, 0 left to 1
                                     right; B the water under the foam as a share of the painted pixel's light (1 where no
                                     foam is painted); A how much foam is painted. surf_preview.jpg: the zone, the foam,
                                     the water under it, shoreward; and surf_fx.png, for the surf layer (src/library/surf.js:
                                     the spray a wave throws off the rocks and the white water it runs in with, which the
                                     painting has no pixels for): R where the wash may run (open water in the zone), G rock
                                     (the spray rises behind it), B what stands in front of the sea (characters and what they
                                     hold); surf.json: the painted foam's color and the zone's box; surf_fx_preview.jpg;
                                     surf_room.png (L, px x 8): how far the plate's foam may come from at each pixel, so
                                     it never shows a character or what lies past the zone (room_map; plate.js binds it
                                     where the moon's moonfx.png goes)

hand.json "surf": {"zone": [[x, y], ...] (frame fractions: the open sea, the far edge where the waves come from on top),
"foam": [lo, hi] (percentiles of the zone's lightness that ramp the foam from none to all; default [70, 97]: foam is the
whitest thing out there, while rock never gets that light, so no rock is taken for foam), "rock": [lo, hi] (percentiles
of the zone's lightness between which rock gives way to water; default [10, 22]: the tide pool's rocks were the darkest
fifth of its sea). Characters and what they hold (held) are left out: they stand in front of the sea.
"""
import json
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.plate.primitives import srgb_to_linear

DEFAULT_FOAM = (70.0, 97.0)
DEFAULT_ROCK = (10.0, 22.0)
HELD = {"pet", "chime", "lantern", "steam", "candle", "bob"}
ROOM_SCALE = 8.0     # surf_room.png: px at 4K x 8 (to 31.9 px)


def tighten(m, rgb, band=5):
    """A trace's slack: pixels inside a character's outline, within `band` px (4K) of it, that look like what lies just
    outside it rather than the character just inside (Lab distance to each side's local mean) go back to the view. The
    tide pool's oystercatcher was traced with 2 to 5 px of sea around its thin legs, and the white water stopped in
    straight lines there (2026-11-05). Conservative: only pixels clearly nearer the outside's color leave."""
    H, W = m.shape
    r = W / 3840
    b = max(1, round(band * r))
    ker = np.ones((2 * b + 1, 2 * b + 1), np.uint8)
    mu = m.astype(np.uint8)
    inner = cv2.erode(mu, ker) > 0
    outer = (cv2.dilate(mu, ker) > 0) & ~m
    edge = m & ~inner
    if not edge.any() or not outer.any():
        return m
    lab = cv2.cvtColor(np.asarray(rgb, np.float32) / 255, cv2.COLOR_RGB2Lab)
    win = (max(3, round(31 * r)) | 1,) * 2

    def mean(sel):
        w = cv2.blur(sel.astype(np.float32), win)
        return cv2.blur(lab * sel[..., None].astype(np.float32), win) / np.maximum(w, 1e-6)[..., None], w

    bg, wb = mean(outer)
    fg, wf = mean(inner)
    db = np.linalg.norm(lab - bg, axis=-1)
    df = np.linalg.norm(lab - fg, axis=-1)
    return m & ~(edge & (wb > 0.05) & (wf > 0.05) & (db < 0.5 * df))


def held_mask(out, regions, grow=2, polys=None, plate=None):
    """The characters and what they hold or carry (region kinds HELD), grown `grow` px at 4K: they stand in front of
    the sea. Tight to the outline: grown 9 px, then 7 more for the layer, the foam and the white water stopped short of
    the oystercatcher all around it, and Truman saw the mask (2026-11-05). From the traced polygons (`polys`, the masks
    json's regions as plate_prep merged them) when given, less the trace's slack where `plate` shows the view through
    it (tighten): regions.png holds each region grown by its outward feather (about 6 px), and the white water stopped
    in straight lines 8 px off the oystercatcher's thin legs, a box between them (the same day). Else from regions.png.
    None without regions."""
    p = out / "regions.png"
    if not regions or not p.exists():
        return None
    ids = np.asarray(Image.open(p))[..., 0]
    H, W = ids.shape
    held = [g for g in (polys or []) if g.get("kind") in HELD]
    if held:
        from cozy.masks import region_raster
        m = np.zeros((H, W), bool)
        for g in held:
            m |= region_raster(g, W, H) > 0.5
        if plate is not None:
            m = tighten(m, np.asarray(plate.convert("RGB") if hasattr(plate, "convert") else plate))
    else:
        m = np.isin(ids, [g["id"] for g in regions if g.get("kind") in HELD])
    k = max(1, round(2 * grow * W / 3840) + 1)
    return cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0 if k > 1 else m


def zone_mask(poly, W, H):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([(x * W, y * H) for x, y in poly], fill=255)
    return np.asarray(m) > 127


def room_map(zone, held, margin=3.0):
    """How far (px at 4K) the plate's foam may come from at each pixel of the zone (plate.glsl.js pushes it shoreward,
    showing the plate from farther out, straight up the frame): half the distance to the nearest thing it must never
    show, less `margin`, so the pixel it shows stays clear of it. That is a character standing in the sea and what lies
    beyond the zone's far edge; the zone's near edge is never looked toward. Smooth, so the push never jumps: shown
    unpushed wherever the push would have reached into the oystercatcher, its legs left straight-edged boxes under its
    belly, and pushed right up to it the foam dragged its dark outline into the water (2026-11-05). 0 outside the zone."""
    H, W = zone.shape
    r = W / 3840
    below = np.maximum.accumulate(zone, axis=0) & ~zone       # under the zone in its column: the near shore
    stop = (~zone & ~below) | (held if held is not None else False)
    d = cv2.distanceTransform((~stop).astype(np.uint8), cv2.DIST_L2, 5) / r
    return np.where(zone & ~stop, np.clip(0.5 * (d - margin), 0, 255 / ROOM_SCALE), 0.0)


def shore_edges(zone):
    """The zone's top (far) and bottom (near) edge rows in each column, smoothed across the columns so the shoreward
    coordinate has no steps, and its first and last columns."""
    H, W = zone.shape
    cols = np.nonzero(zone.any(0))[0]
    top = np.full(W, np.nan)
    bot = np.full(W, np.nan)
    rows = np.arange(H)
    for x in cols:
        r = rows[zone[:, x]]
        top[x], bot[x] = r[0], r[-1]
    xs = np.arange(W)
    ok = ~np.isnan(top)
    top = np.interp(xs, xs[ok], top[ok])
    bot = np.interp(xs, xs[ok], bot[ok])
    k = max(3, int(W / 96) | 1)
    top = cv2.GaussianBlur(top.reshape(1, -1).astype(np.float32), (k, 1), 0).ravel()
    bot = cv2.GaussianBlur(bot.reshape(1, -1).astype(np.float32), (k, 1), 0).ravel()
    return top, bot, int(cols[0]), int(cols[-1])


def shoreward(zone):
    """0 at the zone's top edge in each column (the far side, where the waves come in) to 1 at its bottom edge, the
    edges smoothed across the columns so the coordinate has no steps; and 0 to 1 left to right across the zone."""
    H, W = zone.shape
    top, bot, c0, c1 = shore_edges(zone)
    rows, xs = np.arange(H), np.arange(W)
    s = (rows[:, None] - top[None, :]) / np.maximum(bot - top, 1.0)[None, :]
    a = (xs - c0) / max(c1 - c0, 1)
    return np.clip(s, 0, 1).astype(np.float32), np.broadcast_to(np.clip(a, 0, 1), (H, W)).astype(np.float32)


def surf_maps(plate, cfg, held, out):
    """Write surf.png and surf_preview.jpg for hand.json "surf" (see the module's note). Returns stats."""
    rgb = np.asarray(plate.convert("RGB"))
    H, W = rgb.shape[:2]
    r = W / 3840
    zone = zone_mask(cfg["zone"], W, H)
    sea = zone & ~held if held is not None else zone
    if sea.sum() < 1000:
        raise SystemExit("hand.json surf: the zone holds almost no open sea (check its polygon)")
    L = cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2Lab)[..., 0]
    lo, hi = np.percentile(L[sea], cfg.get("foam", DEFAULT_FOAM))
    foam = np.clip((L - lo) / max(hi - lo, 1e-3), 0, 1) * sea
    foam = cv2.GaussianBlur(foam.astype(np.float32), (0, 0), 1.0 * r)
    # the water under the foam: the foam painted out from what is around it (the characters and what they hold are
    # painted out too, so they never bleed into it; outside the open sea the plate stays as it is)
    hole = cv2.dilate((foam > 0.04).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
    near = cv2.dilate(zone.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
    fill_mask = (hole & sea) | ((held & near) if held is not None else np.zeros_like(sea))
    under = cv2.inpaint(rgb, fill_mask.astype(np.uint8) * 255, max(3, round(9 * r)), cv2.INPAINT_TELEA)
    under = np.where(sea[..., None], under, rgb)
    # the water under the foam as a share of the painted pixel's light (linear): the shader brings the painted pixel
    # down to it, so the water keeps the painting's own grain
    lum = lambda c: srgb_to_linear(c.astype(np.float32) / 255) @ np.array([0.2126, 0.7152, 0.0722], np.float32)  # noqa: E731
    share = np.where(foam > 0.002, np.clip(lum(under) / np.maximum(lum(rgb), 1e-4), 0, 1), 1.0)
    s, a = shoreward(zone)
    # a character standing in the sea is no sea: the plate's foam skips it and never pulls it into the water as the wash
    # rides in, and the white water stops at its outline
    s_enc = np.where(sea, 0.02 + 0.98 * s, 0.0)
    Image.fromarray(np.round(np.stack([s_enc, a * sea, share, foam], -1) * 255).astype(np.uint8), "RGBA").save(out / "surf.png")
    Image.fromarray(np.round(room_map(zone, held) * ROOM_SCALE).astype(np.uint8), "L").save(out / "surf_room.png")
    preview(rgb, zone, foam, under, s, out / "surf_preview.jpg")
    fx = fx_maps(rgb, L, zone, held, foam, cfg, out)
    st = {"zone_px": int(zone.sum()), "sea_px": int(sea.sum()), "foam_share": round(float((foam > 0.5).sum() / sea.sum()), 3),
          "lightness": [round(float(lo), 1), round(float(hi), 1)], **fx}
    print(f"  surf: {st['foam_share']:.0%} of the open sea is painted foam (lightness {st['lightness'][0]} to "
          f"{st['lightness'][1]}), {st['rock_share']:.0%} rock -> surf.png, surf_fx.png; look at surf_preview.jpg, surf_fx_preview.jpg")
    return st


def fx_maps(rgb, L, zone, held, foam, cfg, out):
    """surf_fx.png and surf.json for the surf layer (see the module's note). The tide pool's waves were only the painted
    foam brightening and dimming, and Truman saw no waves on the far rocks while the surf roared (2026-11-05): a break
    needs spray and white water where nothing white is painted. Rock is the zone's darkest lightness, kept where it is
    a solid shape (the painted wave shadows in the water are dark too, but thin)."""
    H, W = zone.shape
    r = W / 3840
    sea = zone & ~held if held is not None else zone
    Ls = cv2.GaussianBlur(L, (0, 0), 2.0 * r)
    lo, hi = np.percentile(Ls[sea], cfg.get("rock", DEFAULT_ROCK))
    # at least 4 lightness units of ramp: on an evenly painted sea the percentiles meet, and any slightly darker
    # brush mark would count as rock
    rock = np.clip((hi - Ls) / max(hi - lo, 4.0), 0, 1).astype(np.float32)
    # a rock is a solid shape: an opening drops the thin dark streaks of the water's own painting
    k = max(3, round(7 * r) | 1)
    rock = cv2.morphologyEx(rock, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    rock = cv2.GaussianBlur(rock, (0, 0), 1.0 * r)
    near = cv2.dilate(zone.astype(np.uint8), np.ones((max(3, round(161 * r) | 1),) * 2, np.uint8)) > 0
    rock = rock * near
    front = held.astype(np.float32) if held is not None else np.zeros((H, W), np.float32)
    front = cv2.GaussianBlur(front, (0, 0), 0.8 * r)
    # the wash runs over the open water, fading in from the zone's outline (no ruled edge where the polygon ends)
    soft = cv2.GaussianBlur(zone.astype(np.float32), (0, 0), 6.0 * r)
    wash = np.clip(soft * (1 - rock) * (1 - front), 0, 1)
    Image.fromarray(np.round(np.stack([wash, rock, front, np.ones_like(wash)], -1) * 255).astype(np.uint8), "RGBA").save(out / "surf_fx.png")
    lit = foam > 0.8
    col = rgb[lit].mean(0) / 255 if lit.sum() > 50 else np.array([0.82, 0.84, 0.86])
    water = rgb[sea & (foam < 0.05) & (rock < 0.1)].mean(0) / 255 if (sea & (foam < 0.05) & (rock < 0.1)).sum() > 50 else col * 0.6
    ys, xs = np.nonzero(zone)
    s, _a = shoreward(zone)
    spots = spray_spots(rock, wash, zone, s, front)
    # the zone's edges every 8 px at 4K, so the layer times a spot anywhere (a hand-placed one too) as the shader does
    top, bot, c0, c1 = shore_edges(zone)
    st = max(1, round(8 * r))
    edges = {"step": 8, "top": [round(float(v) / r, 1) for v in top[::st]], "bot": [round(float(v) / r, 1) for v in bot[::st]],
             "x0": round(c0 / r, 1), "x1": round(c1 / r, 1)}
    meta = {"foam": [round(float(v), 4) for v in col], "water": [round(float(v), 4) for v in water],
            "bbox": [round(xs.min() / W, 4), round(ys.min() / H, 4), round((xs.max() + 1) / W, 4), round((ys.max() + 1) / H, 4)],
            "spots": spots, "edges": edges}
    (out / "surf.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    fx_preview(rgb, zone, wash, rock, front, out / "surf_fx_preview.jpg", spots)
    return {"rock_share": round(float((rock[sea] > 0.5).mean()), 3), "foam_rgb": meta["foam"], "spots": len(spots)}


def spray_spots(rock, wash, zone, s, front, step=4, gap=14, longest=260):
    """Where the waves throw spray: the seaward top edge of each rock out in the water (the first rock down each column
    of the zone, with open water right above it, short of the near shore), cut into stretches no longer than `longest`
    px at 4K. Each: {x, y (frame fractions: the middle of its top edge), w, h (px at 4K: the stretch's width and the
    biggest wave's spray height), s (0..1 shoreward), min (the smallest wave's strength that throws spray there: rocks
    farther in only take the bigger waves)}."""
    H, W = zone.shape
    r = W / 3840
    above = max(2, round(8 * r))
    cols = []
    for x in range(0, W, max(1, round(step * r))):
        zc = np.nonzero(zone[:, x])[0]
        if not len(zc):
            continue
        for y in range(zc[0] + above, zc[-1]):
            if rock[y, x] > 0.5 and front[y, x] < 0.2:
                if s[y, x] < 0.75 and wash[y - above, x] > 0.5:
                    cols.append((x, y))
                break
    spots = []
    run = []

    def flush():
        if len(run) < 3:
            return
        x0, x1 = run[0][0], run[-1][0]
        n = max(1, math.ceil((x1 - x0) / (longest * r)))
        for k in range(n):
            part = [q for q in run if x0 + (x1 - x0) * k / n <= q[0] <= x0 + (x1 - x0) * (k + 1) / n]
            if len(part) < 3:
                continue
            px0, px1 = part[0][0], part[-1][0]
            w = (px1 - px0 + step * r) / r
            if w < 24:
                continue
            mid = part[len(part) // 2]
            yy = float(np.percentile([q[1] for q in part], 30))
            sh = float(s[int(yy), mid[0]])
            spots.append({"x": round((px0 + px1) / 2 / W, 4), "y": round(yy / H, 4), "w": round(w), "h": round(float(np.clip(0.55 * w, 45, 130))),
                          "s": round(sh, 3), "min": round(0.42 + 0.3 * sh, 3)})
    for q in cols:
        if run and (q[0] - run[-1][0] > gap * r or abs(q[1] - run[-1][1]) > 18 * r):
            flush()
            run = []
        run.append(q)
    flush()
    return spots


def fx_preview(rgb, zone, wash, rock, front, path, spots=()):
    """The zone and a band above it (where the spray rises), top to bottom: the plate with the spray spots (yellow: each
    spot's width at its base and its biggest spray's height), the wash (white), the rock (white), what stands in front
    (white)."""
    ys, xs = np.nonzero(zone)
    H, W = zone.shape
    r = W / 3840
    x0, x1 = max(xs.min() - 20, 0), min(xs.max() + 20, W)
    y0, y1 = max(ys.min() - round(0.09 * H), 0), min(ys.max() + 20, H)
    gray = lambda m: np.repeat((np.clip(m, 0, 1) * 255).astype(np.uint8)[..., None], 3, -1)  # noqa: E731
    top = Image.fromarray(np.ascontiguousarray(rgb))
    d = ImageDraw.Draw(top)
    for sp in spots:
        cx, cy, hw, hh = sp["x"] * W, sp["y"] * H, sp["w"] * r / 2, sp["h"] * r
        d.rectangle([cx - hw, cy - hh, cx + hw, cy], outline=(255, 220, 0), width=max(2, round(3 * r)))
    tiles = [top.crop((x0, y0, x1, y1))] + [Image.fromarray(np.ascontiguousarray(t[y0:y1, x0:x1])) for t in (gray(wash), gray(rock), gray(front))]
    w = min(1600, x1 - x0)
    tiles = [t.resize((w, round(t.height * w / t.width)), Image.LANCZOS) for t in tiles]
    sheet = Image.new("RGB", (w, sum(t.height for t in tiles) + 6 * (len(tiles) - 1)), (0, 0, 0))
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + 6
    sheet.save(path, quality=88)


def preview(rgb, zone, foam, under, s, path):
    """The zone, top to bottom: the plate, the foam (white), the water under it, shoreward (dark far, light near)."""
    ys, xs = np.nonzero(zone)
    pad = 20
    x0, x1, y0, y1 = max(xs.min() - pad, 0), min(xs.max() + pad, rgb.shape[1]), max(ys.min() - pad, 0), min(ys.max() + pad, rgb.shape[0])
    rows = [rgb, np.repeat((foam * 255).astype(np.uint8)[..., None], 3, -1), under,
            np.repeat((s * zone * 255).astype(np.uint8)[..., None], 3, -1)]
    tiles = [Image.fromarray(np.ascontiguousarray(t[y0:y1, x0:x1])) for t in rows]
    w = min(1600, x1 - x0)
    tiles = [t.resize((w, round(t.height * w / t.width)), Image.LANCZOS) for t in tiles]
    sheet = Image.new("RGB", (w, sum(t.height for t in tiles) + 6 * (len(tiles) - 1)), (0, 0, 0))
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height + 6
    sheet.save(path, quality=88)
