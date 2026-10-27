"""Where drops, flames and steam start (TASKS.md T16), moved verbatim from plate_prep.py.

  edge_sources       the outdoors' top edge and the drip and runoff candidates along it
  bead_sources       hanging drops along every wet edge over the opening
  strand_drips       live drips where plate_clean.py removed painted ones
  dry_mask           what must never be rained or dripped on; keep_off_dry drops the sources that would (drip_lands)
  fire_beds          where the flames stand on each fire region
  vessel_openings    the opening of each steaming vessel, fitted to its rim
"""
import json

import cv2
import numpy as np
from PIL import Image

from cozy.masks import DRY_KINDS, poly_mask


def vessel_openings(plate, regions, ov, W, H):
    """The opening of each steaming vessel (regions of kind 'steam'), an ellipse fitted to its rim: "opening":
    [cx, cy, a, b] (image coords; a = half width, b = half height) in regions.json, where steam.js's veil rises
    from the whole surface. Edge points (strong horizontal edges, both polarities, the 3 strongest per column
    in the top 60% of the vessel's box) and a RANSAC ellipse kept nearly level, as wide as 55-100% of the box,
    centred in it and flattened by the view (b/a 0.08-0.6). Falls back to an ellipse from the box. A hand fix:
    "openings": {"<region>": [cx, cy, a, b]} in the masks or hand json (the ramen bowl's back rim is partly
    hidden by the nori)."""
    hand = ov.get("openings") or {}
    a8 = np.asarray(plate, np.float32).mean(2)
    L = cv2.GaussianBlur(a8, (0, 0), 1.2 * W / 3840)
    gy = np.zeros_like(L)
    gy[1:-1] = L[2:] - L[:-2]
    changed = False
    for g in regions:
        if g.get("kind") != "steam":
            continue
        if g["name"] in hand:
            g["opening"] = [round(float(v), 5) for v in hand[g["name"]]]
            g["opening_fit"] = "hand"
            changed = True
            continue
        x0, y0, x1, y1 = g["bbox"]
        X0, X1, Y0, Y1 = int(x0 * W), int(x1 * W), int(y0 * H), int(y1 * H)
        bw, bh = X1 - X0, Y1 - Y0
        if bw < 20 or bh < 20:
            continue
        ya, yb = max(1, Y0 - int(0.1 * bh)), min(H - 2, Y0 + int(0.45 * bh))
        pts = []
        for x in range(X0, X1, max(2, bw // 200)):
            col = np.abs(gy[ya:yb, x])
            for _ in range(2):
                k = int(np.argmax(col))
                if col[k] < 10:
                    break
                pts.append((x, ya + k))
                col[max(0, k - 5): k + 6] = 0
        if len(pts) < 12:
            continue
        P = np.array(pts, np.float64)
        # a level ellipse: A x^2 + C y^2 + D x + E y + F = 0 (4 points fix it)
        Dm = np.stack([P[:, 0] ** 2, P[:, 1] ** 2, P[:, 0], P[:, 1], np.ones(len(P))], 1)
        sc = np.array([1 / W ** 2, 1 / H ** 2, 1 / W, 1 / H, 1.0])
        Dn = Dm * sc

        def conic(idx):
            c = np.linalg.svd(Dn[idx])[2][-1] * sc
            return c

        def ell(c):
            A, C, D, E, F = c
            if A * C <= 0:
                return None
            cx, cy = -D / (2 * A), -E / (2 * C)
            Fp = D * D / (4 * A) + E * E / (4 * C) - F
            if Fp / A <= 0 or Fp / C <= 0:
                return None
            return (cx, cy), float(np.sqrt(Fp / A)), float(np.sqrt(Fp / C))

        def dist(c):
            A, C, D, E, F = c
            x, y = P[:, 0], P[:, 1]
            v = A * x * x + C * y * y + D * x + E * y + F
            return np.abs(v) / np.maximum(np.hypot(2 * A * x + D, 2 * C * y + E), 1e-12)

        def ok(e):
            if e is None:
                return False
            (cx, cy), a, b = e
            return (0.275 * bw <= a <= 0.5 * bw and 0.08 <= b / a <= 0.6 and abs(cx - (X0 + X1) / 2) < 0.2 * bw
                    and Y0 - 0.06 * bh <= cy - b <= Y0 + 0.3 * bh)

        rng = np.random.default_rng(3)
        best, bc = 0, None
        tol = 3.0 * W / 3840
        for _ in range(6000):
            c = conic(rng.choice(len(P), 4, replace=False))
            if not ok(ell(c)):
                continue
            n = int((dist(c) < tol).sum())
            if n > best:
                best, bc = n, c
        e = None
        if bc is not None and best >= 0.15 * len(P):
            inl = np.flatnonzero(dist(bc) < tol)
            c = np.linalg.svd(Dn[inl])[2][-1] * sc
            e = ell(c) if ok(ell(c)) else ell(bc)
        if e is not None:
            (cx, cy), a, b = e
            g["opening"] = [round(cx / W, 5), round(cy / H, 5), round(a / W, 5), round(b / H, 5)]
            g["opening_fit"] = "rim"
            print(f"  steam {g['name']}: opening fitted to the rim ({best} of {len(P)} edge points): center ({cx:.0f}, {cy:.0f}), {2 * a:.0f} x {2 * b:.0f} px")
        else:
            a = 0.42 * bw
            g["opening"] = [round((X0 + X1) / 2 / W, 5), round((Y0 + 0.15 * a) / H, 5), round(a / W, 5), round(0.15 * a / H, 5)]
            g["opening_fit"] = "box"
            print(f"  steam {g['name']}: no rim found, opening from its box (check it, or set \"openings\" in the hand json)")
        changed = True
    return changed


def edge_sources(outdoor, W, H):
    """Top edge of the outdoors region per column (where roof/vines end) and drip/stream candidates:
    - 'tip':  local lowest points of hanging leaves/vines (water collects and drips there)
    - 'eave': long, nearly flat edge segments (roof/beam edge; runoff pours along them)
    - 'top':  columns open to the frame top (roof edge is just above the frame)"""
    step = 4
    xs = np.arange(0, W, step)
    ytop = np.full(len(xs), -1, np.int32)
    lim = int(H * 0.6)
    for i, x in enumerate(xs):
        col = outdoor[:lim, x] > 0.5
        nz = np.flatnonzero(col)
        if len(nz):
            ytop[i] = nz[0]
    cands = []
    win = int(48 / step)
    for i in range(win, len(xs) - win):
        y = ytop[i]
        if y <= 0:
            continue
        seg = ytop[i - win: i + win + 1]
        if (seg < 0).any():
            continue
        if y == seg.max() and y - np.median(seg) > 12:
            cands.append([int(xs[i]), int(y), "tip"])
    # Flat edges: runs where |dy| small over >= 160 px and y > 0.
    run = 0
    for i in range(1, len(xs)):
        ok = ytop[i] > 0 and ytop[i - 1] > 0 and abs(int(ytop[i]) - int(ytop[i - 1])) <= 3
        run = run + 1 if ok else 0
        if run * step >= 160 and run % int(160 / step) == 0:
            cands.append([int(xs[i - run // 2]), int(np.median(ytop[i - run: i + 1])), "eave"])
    for i in range(0, len(xs), int(200 / step)):
        if ytop[i] == 0:
            cands.append([int(xs[i]), 0, "top"])
    return xs, ytop, cands


def dry_mask(W, H, out):
    """What must never be rained or dripped on: the pet, food and drink, candles, fire (regions.png kinds
    DRY_KINDS), what is inside a vessel (the fitted opening of a steam region: the broth, noodles and the nori
    standing up in a bowl, which its region, the ceramic, leaves out), and what a character holds or stands beside
    (regions.json "dry_why", the character rule: the Burdock Shelter's salamander holds its paper lantern under the
    dripping salal leaf, 2026-10-25, L149). A cat under a dripping lantern read as rain hitting the cat (user
    2026-10-19)."""
    rp, mp = out / "regions.png", out / "regions.json"
    if not (rp.exists() and mp.exists()):
        return None
    ids = np.asarray(Image.open(rp).convert("RGB"))[..., 0]
    regs = json.loads(mp.read_text())
    keep = [g["id"] for g in regs if g["kind"] in DRY_KINDS or g.get("dry_why")]
    if not keep:
        return None
    m = np.isin(ids, keep).astype(np.uint8)
    for g in regs:
        if g["kind"] == "steam" and g.get("opening"):
            cx, cy, a, b = g["opening"]
            cv2.ellipse(m, (int(round(cx * W)), int(round(cy * H))), (int(round(a * W)), int(round(b * H))), 0, 0, 360, 1, -1)
    return cv2.dilate(m, np.ones((9, 9), np.uint8)).astype(bool)


def drip_lands(x, y, outdoor, W, H):
    """The row where a drop falling from (x, y) leaves the opening: below the first stretch where it enters it
    (an edge's own pixels can read as not outdoors for a few dozen px), the first pixel that is not outdoors
    (the ground's edge, a counter, a pet...), or the frame bottom."""
    xi = int(min(max(x, 0), W - 1))
    col = outdoor[int(y) + 2:, max(0, xi - 1): xi + 2].min(1) >= 0.5
    inside = np.flatnonzero(col[: int(0.06 * H)])
    start = int(inside[0]) if len(inside) else 0
    hit = np.flatnonzero(~col[start:])
    return int(y) + 2 + start + int(hit[0]) if len(hit) else H


def keep_off_dry(sources, dry, outdoor, W, H, label):
    """Drop drip sources whose drops would land on something that must stay dry (dry_mask): at the row where
    the fall leaves the opening (beads) or at its landing row (strand drips), within a few px, or anywhere down
    the thing it lands on (followed down the column while it is not outdoors, up to ~150 px at 4K): the nori
    standing up out of the ramen bowl is not in the bowl's region, and drops ending on its top edge read as
    dripping into the food. Even when the drop really falls far behind: it vanishes at the outline, which reads
    as hitting it (checked 2026-10-19, round 2)."""
    if dry is None:
        return sources
    reach = int(150 * W / 3840)
    out = []
    for s in sources:
        x, y = int(s[0]), int(s[1])
        land = int(s[3]) if len(s) > 3 and s[3] < H else drip_lands(x, y, outdoor, W, H)
        cols = slice(max(0, x - 3), x + 4)
        a, b = max(0, land - 6), min(H, land + 10)
        if land < H:
            s0 = land + int(8 * W / 3840)       # past the outdoor mask's soft edge
            col = outdoor[s0: min(H, land + reach), cols].max(1) >= 0.5
            # down the thing it lands on; a sliver of open air under a slanted edge (the nori's side) is bridged
            gap, run, k = int(32 * W / 3840), len(col), 0
            while k < len(col):
                if col[k]:
                    e = k
                    while e < len(col) and col[e]:
                        e += 1
                    if e - k > gap or e == len(col):
                        run = k
                        break
                    k = e
                else:
                    k += 1
            b = max(b, min(H, s0 + run + 4))
        if a < b and dry[a:b, cols].any():
            print(f"  {label} at ({x}, {y}): it would drip onto the pet, the food or what a character holds, dropped")
            continue
        out.append(s)
    return out


def bead_sources(outdoor, ov, W, H, spacing=34, seed=5, disp=None):
    """Hanging-drop sources (src/library/drips.js) along every wet edge over the opening: the top edge of the
    outdoor region (awning hems, eaves, lantern bottoms; not columns open to the frame top), the lower edges of
    outdoor cloth (curtain regions with "outdoor": true) and of any region marked "drips": true (a leaf held up in
    the rain as an umbrella: the Burdock Shelter's salal leaf, a hole in an outdoors that reaches the frame top, had
    no edge to drip from, 2026-10-25, L149). [x, y, w] in plate px; w = 2 at the
    lowest point of a dip (water collects and drips there faster), else 1. Steep parts (sides of lanterns
    and posts, where water runs down instead) are skipped.
    A drop hangs only from something: with the disparity, only where what is just above the edge is nearer than the
    view just below it (an eave, a hem), never along a mask's straight edge in open sky; and never from a near thing on
    our side of the weather (a lantern hanging under the roof is dry). The tea house hung drops along its opening box's
    top edge across the sky and from the bottom of the lantern under its eave (2026-10-22)."""
    lim = int(0.6 * H)
    o = outdoor[:lim] > 0.5
    y = np.where(o.any(0), o.argmax(0), -1).astype(np.float32)
    y[y == 0] = -1
    for rg in ov.get("regions") or []:
        if ((rg.get("kind") == "curtain" and rg.get("outdoor")) or rg.get("drips")) and rg.get("polys"):
            cm = poly_mask((W, H), rg["polys"]) > 0.5
            cols = np.flatnonzero(cm.any(0))
            bot = H - 1 - np.argmax(cm[::-1, cols], 0)
            ok = bot < H - 2
            y[cols[ok]] = np.where(y[cols[ok]] > 0, np.minimum(y[cols[ok]], bot[ok] + 1), bot[ok] + 1)
    r = W / 3840
    dryk = ("lantern", "lamp", "chime", "bob", "candle", "pet", "steam", "screen")
    near = np.zeros((H, W), np.uint8)
    for rg in ov.get("regions") or []:
        if rg.get("near") and not rg.get("outdoor") and rg.get("kind") in dryk and rg.get("polys"):
            near = np.maximum(near, (poly_mask((W, H), rg["polys"]) > 0.5).astype(np.uint8))
    near = cv2.dilate(near, np.ones((max(3, int(9 * r) | 1),) * 2, np.uint8)) > 0
    rng = np.random.default_rng(seed)
    out = []
    x = float(rng.uniform(0, spacing))
    k = max(3, int(8 * r))
    while x < W - 2:
        xi = int(x)
        a, b = max(0, xi - int(6 * r)), min(W - 1, xi + int(6 * r))
        if y[xi] > 0 and y[a] > 0 and y[b] > 0 and abs(y[b] - y[a]) / max(b - a, 1) < 1.0:
            yi = int(y[xi])
            hang = not near[max(0, yi - 2), xi]
            if hang and disp is not None:
                hang = float(disp[max(0, yi - k), xi]) > float(disp[min(H - 1, yi + k), xi]) + 0.02
            if hang:
                win = y[max(0, xi - int(40 * r)): xi + int(40 * r) + 1]
                w = 2.0 if y[xi] >= win[win > 0].max() - 1 else 1.0
                out.append([xi, yi, w])
        x += spacing * r * float(rng.uniform(0.55, 1.45))
    return out


def fire_beds(plate, regions, W, H):
    """Where the flames stand on each fire region: the glowing ember bed of the (cleaned) plate inside the
    region's box (bright, saturated warm pixels in its lower part). Adds "bed": [x0, x1, y] (image coords:
    the bed's extent and the top of the glow) to the region entries for src/library/fire.js."""
    a = np.asarray(plate, np.float32) / 255
    changed = False
    for g in regions:
        if g.get("kind") != "fire" or g.get("bed"):
            continue
        x0, y0, x1, y1 = g["bbox"]
        X0, X1, Y0, Y1 = int(x0 * W), int(x1 * W), int((y0 + 0.3 * (y1 - y0)) * H), int(min(1.0, y1 + 0.08 * (y1 - y0)) * H)
        c = a[Y0:Y1, X0:X1]
        if c.size == 0:
            continue
        lum = c @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        warm = (c[..., 0] > 0.5) & (c[..., 0] > 1.35 * c[..., 2] + 0.08) & (lum > np.percentile(lum, 80))
        ys, xs = np.nonzero(warm)
        if len(xs) < 50:
            continue
        g["bed"] = [round((X0 + float(np.percentile(xs, 6))) / W, 4), round((X0 + float(np.percentile(xs, 94))) / W, 4),
                    round((Y0 + float(np.percentile(ys, 25))) / H, 4)]
        changed = True
        print(f"  fire bed {g['name']}: {g['bed']}")
    return changed


def strand_drips(cmeta, disp, W, H, height_m=2.6, lights=None, wet=None):
    """Live drip sources where tools/plate_clean.py removed painted drips ("strands" items of the key art's
    clean.json: "drips": [[x, y, length], ...] 0..1): [x, y, w, stop, ppm, splash] in plate px. A drop falls in
    front of what it hung from until it reaches the ground straight below it: the first row under it whose
    disparity reaches the drip's own (the ground at the same distance) or a nearer object hides it; else the frame
    bottom. Its px per m comes from that fall (an eave is ~`height_m` above the ground). splash = 1 when it lands
    on wet ground (`wet`, the water mask): only then does drips.js draw a splash there; landing on a nearer object
    it just goes out of sight behind it.
    One whose first stretch of fall crosses a lit sign or lamp (`lights`) is dropped: it was a sign's hook or
    chain read as a drip, and a drop would streak across the neon (the ramen alley's bowl sign, 2026-10-18)."""
    out = []
    for it in cmeta.get("items", []):
        for x, y, _ in it.get("drips") or []:
            xi, yi = int(x * W), int(y * H)
            if not (0 <= xi < W and 0 <= yi < H - 8):
                continue
            d0 = float(np.median(disp[max(0, yi - 4): yi + 5, max(0, xi - 4): xi + 5]))
            y1 = yi + int(0.02 * H)
            col = disp[y1:, max(0, xi - 2): xi + 3].mean(1) if y1 < H else np.zeros(0)
            hit = np.flatnonzero(col >= d0 + 0.004)
            stop = y1 + int(hit[0]) if len(hit) else H + 40
            if lights is not None:
                seg = lights[yi + 3: min(int(stop), yi + int(0.12 * H), H), max(0, xi - 2): xi + 3]
                if seg.size and float(seg.max()) > 0.5:
                    print(f"  strand drip at ({xi}, {yi}): its fall crosses a lit sign or lamp, dropped")
                    continue
            ppm = float(np.clip((stop - yi) / height_m, 150, 900)) if len(hit) else 400.0
            sp = 0
            if wet is not None and len(hit) and stop < H - 3:
                sp = int(float(wet[int(stop) + 1: int(stop) + 4, max(0, xi - 3): xi + 4].mean()) > 0.5)
            out.append([xi, yi, 1.0, int(stop), round(ppm, 1), sp])
    return out
