"""The lights a scene switches, and their reflections (TASKS.md T16), moved verbatim from plate_prep.py.

  light_groups         windows and lanterns: lightid.png, lightw.png and the plate with them off (plate_off.png)
  light_reflections    refl.png: where the wet ground reflects a flickering light (the kinds in REFL_KINDS)
"""
import json

import cv2
import numpy as np
from PIL import Image

from cozy.plate.primitives import srgb_to_linear


REFL_KINDS = {"neon", "lamp", "lantern", "candle", "string"}


def light_reflections(plate, wet, disp, out, kinds=REFL_KINDS):
    """refl.png: where the wet ground reflects a flickering light (R = the light's region id, G = how much of the
    pixel's light is that reflection, 0..1), so plate.js dims the reflection with the light (a neon dip, a lantern
    guttering): a sign that flickers over an unchanging reflection is a tell (user 2026-10-19).
    The key art's reflections are painted, not mirrored exactly, so they are matched the way a viewer reads them:
    a streak on the wet ground below a light, brighter than its surroundings, in that light's color (the street's
    own tint mixed in), roughly under it (the window widens for lights higher above the ground). Where two lights
    could own a streak, the better color match wins, then the light nearer the ground (a lamp standing on the
    street owns the streak under it, not the sign high on the wall above). refl_preview.jpg: the plate darkened,
    each light boxed and its reflection in green."""
    (out / "refl.png").unlink(missing_ok=True)
    (out / "refl_preview.jpg").unlink(missing_ok=True)
    rp, mp = out / "regions.png", out / "regions.json"
    if not (rp.exists() and mp.exists()):
        return
    meta = json.loads(mp.read_text())
    reg = np.asarray(Image.open(rp).convert("RGB"))
    ids, rw = reg[..., 0], reg[..., 1].astype(np.float32) / 255
    a = np.asarray(plate, np.float32) / 255
    H, W = ids.shape
    lin = srgb_to_linear(a)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    base = cv2.GaussianBlur(lum, (0, 0), 0.02 * W)
    chroma = lin / np.maximum(lin.sum(-1, keepdims=True), 1e-4)
    cn = chroma / np.maximum(np.linalg.norm(chroma, axis=-1, keepdims=True), 1e-6)
    wetm = wet > 0.5
    # the street's own color: what a reflection's color is mixed with
    amb = chroma[wetm].mean(0) if wetm.any() else np.full(3, 1 / 3, np.float32)
    frac = np.clip((lum - base) / np.maximum(lum, 1e-4), 0, 1) * np.clip((lum - 1.12 * base) / np.maximum(0.25 * base, 1e-4), 0, 1)
    rid = np.zeros((H, W), np.uint8)
    rwt = np.zeros((H, W), np.float32)
    score = np.zeros((H, W), np.float32)
    found = {}
    for g in meta:
        if g["kind"] not in kinds:
            continue
        m = (ids == g["id"]) & (rw > 0.3)
        if m.sum() < 20:
            continue
        ys, xs = np.nonzero(m)
        L = lum[m]
        hot = L >= np.percentile(L, 90)
        c = chroma[m][hot].mean(0)
        x0, x1, ybot = int(xs.min()), int(xs.max()), int(ys.max())
        rows = []
        for x in range(x0, x1 + 1, max(1, (x1 - x0) // 24)):
            hit = np.flatnonzero(wetm[ybot:min(H, ybot + int(0.4 * H)), x])
            if hit.size:
                rows.append(ybot + int(hit[0]))
        if len(rows) < 3:
            continue
        yb = int(np.median(rows))
        hgt = max(yb - ybot, 0)
        # it must stand over that ground (a sign on the wall above it): a light much nearer than the ground below
        # it (a lantern in the stall in front of the street) mirrors far below the visible street, if anywhere
        if float(np.median(disp[m])) > 1.6 * float(np.median(disp[min(H - 1, yb + 2), x0:x1 + 1])) + 0.02:
            continue
        xm = int(0.35 * (x1 - x0) + 0.3 * hgt) + 6
        xa, xz = max(0, x0 - xm), min(W, x1 + xm + 1)
        ya, yz = yb, min(H, yb + int(0.45 * H))
        sl = (slice(ya, yz), slice(xa, xz))
        # best of the pure light color and its mixes with the street's tint
        best = np.zeros((yz - ya, xz - xa), np.float32)
        for k in (0.0, 0.25, 0.5):
            t = (1 - k) * c + k * amb
            t = t / np.linalg.norm(t)
            best = np.maximum(best, (cn[sl] * t).sum(-1))
        match = np.clip((best - 0.9) / 0.07, 0, 1)
        xx = np.arange(xa, xz)[None, :]
        cx, hw = 0.5 * (x0 + x1), 0.5 * (x1 - x0) + xm
        across = np.clip(1.6 - 1.6 * np.abs(xx - cx) / hw, 0, 1)
        yy = np.arange(ya, yz)[:, None]
        along = np.clip(1.4 - (yy - yb) / (0.35 * H), 0, 1)
        w = (match * frac[sl] * across * along * wetm[sl]).astype(np.float32)
        w = cv2.GaussianBlur(w, (0, 0), 1.0 * W / 3840)
        if float(w.max()) < 0.05:
            continue
        sc = w * (best + 0.02) * np.exp(-hgt / (0.5 * H))
        take = sc > score[sl]
        score[sl] = np.where(take, sc, score[sl])
        rwt[sl] = np.where(take, w, rwt[sl])
        rid[sl] = np.where(take, g["id"], rid[sl])
        found[g["id"]] = g["name"]
    found = [f"{n}({float(((rid == i) & (rwt > 0.2)).sum()) / 1e3:.1f}k px)" for i, n in found.items() if ((rid == i) & (rwt > 0.2)).sum() > 0]
    if not found:
        return
    Image.fromarray(np.stack([rid, np.round(np.clip(rwt, 0, 1) * 255).astype(np.uint8), np.zeros_like(rid)], -1), "RGB").save(out / "refl.png")
    pv = a * 0.45
    pv = pv * (1 - rwt[..., None]) + np.array([0.1, 1.0, 0.2], np.float32) * rwt[..., None]
    for g in meta:
        if g["kind"] in kinds:
            ys, xs = np.nonzero(ids == g["id"])
            if ys.size:
                cv2.rectangle(pv, (int(xs.min()), int(ys.min())), (int(xs.max()), int(ys.max())), (1.0, 1.0, 0.0), max(1, W // 1280))
    Image.fromarray((np.clip(pv, 0, 1) * 255).astype(np.uint8)).resize((W // 2, H // 2)).save(out / "refl_preview.jpg", quality=88)
    print(f"  light reflections on the wet ground: {', '.join(found)} -> refl.png (check refl_preview.jpg)")


def light_groups(img, outdoor, water, disp, ov):
    """Individually controllable lights (scene events switch them: windows going dark late at night, a
    lantern guttering). Returns (id map, share map, 'lights off' plate float RGB 0..1, metadata list).
    Per pixel, the 4 lights whose own switch-off changes it most and their shares of the all-lights-off
    delta. A light that goes off removes only its share, so it never pulls in a neighbor's darkening
    (hard-edged discs) and fades out with its own halo. Packed in two uint8 RGB maps (no alpha: browsers
    may premultiply it): ids RGB = id1..id3 in the low 6 bits, id4 spread over their top 2 bits;
    shares RGB = w1..w3 (w4 = 1 - w1 - w2 - w3). Ids are 1..63 (0 = none).
      lanterns: large bright warm cores (porch lanterns), grouped within ~150 px; off = dimmed (they only dip)
      windows:  small warm cores outdoors (distant cabins/treehouses), grouped within ~40 px, never on
                water (reflections), within the window_disp band; off = pane compressed to its
                surroundings' level (cooled) + warm spill dimmed
    A window whose reflection is visible (water right below it) is marked reflective (events skip it)."""
    a = np.asarray(img, np.float32) / 255
    H, W = disp.shape
    r = W / 3840
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    gr = G / np.maximum(R, 1e-3)
    loc = cv2.GaussianBlur(lum, (0, 0), 10 * r)
    warm = (R > B + 0.25) & (gr > 0.55)
    lw = np.array([0.2126, 0.7152, 0.0722], np.float32)
    top_s = np.zeros((5, H, W), np.float32)   # per pixel, the 5 strongest solo deltas (descending) and ids
    top_i = np.zeros((5, H, W), np.uint8)
    off = a.copy()
    meta = []

    def group(mask, min_a, max_a, link):
        n, lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        keep = [k for k in range(1, n) if min_a <= st[k][4] <= max_a]
        pts = np.array([cen[k] for k in keep]).reshape(-1, 2)
        used = np.zeros(len(pts), bool)
        out = []
        for i in range(len(pts)):
            if used[i]:
                continue
            stack, g = [i], []
            used[i] = True
            while stack:
                j = stack.pop()
                g.append(j)
                near = np.flatnonzero((np.hypot(*(pts - pts[j]).T) < link) & ~used)
                used[near] = True
                stack.extend(near.tolist())
            out.append(np.isin(lab, [keep[j] for j in g]))
        return out

    # Lanterns (near, big): bright warm cores of >= 300 px (4K) on near geometry (disparity > 0.15, not
    # outdoors) with a compact body; floor/rail reflections are flat and dimmer, so they fail lum/shape.
    lant = (lum > 0.62) & (R > 0.8) & warm & (B < 0.65) & (disp > 0.15) & (outdoor < 0.5)
    lanterns = [m for m in group(lant, int(300 * r * r), 10 ** 9, 150 * r)
                if (lambda ys, xs: np.ptp(ys) > 40 * r and np.ptp(xs) > 25 * r and lum[m].mean() > 0.7)(*np.nonzero(m))]
    if ov.get("auto_lanterns") is False:   # analyzed scenes: near lights are regions (flicker kinds) instead
        lanterns = []
    # Windows (far, small): warm cores well above their surroundings, outdoors, not on water.
    win = (lum > 0.5) & (lum - loc > 0.18) & warm & (outdoor > 0.5) & (water < 0.3)
    win = cv2.dilate(win.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & (lum > 0.3) & warm   # whole pane
    for m in lanterns:
        win &= ~(cv2.dilate(m.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0)
    windows = group(win, max(3, int(3 * r * r)), int(2500 * r * r), 40 * r)
    # Windows are distant lights: drop warm highlights on near geometry (lantern-lit leaves and rails) and
    # on the background at infinity (sunset glints in the sky). Median disparity band, per scene in the
    # masks json ("window_disp"); check new scenes with a contact sheet of the window groups.
    dlo, dhi = ov.get("window_disp", [0.005, 0.045])
    windows = [m for m in windows if dlo <= float(np.median(disp[m])) <= dhi]
    if ov.get("auto_windows") is False:
        windows = []
    # Self-lit cores of every light (soft edge): one light's spill/halo darkening never applies to another
    # light's pane or flame, which keeps neighboring lights' off-deltas separable.
    if len(lanterns) + len(windows) > 63:
        print(f"  note: {len(lanterns) + len(windows)} lights found, only the first 63 are switchable")
    allc = np.zeros((H, W), np.float32)
    for m in (lanterns + windows)[:63]:
        allc = np.maximum(allc, cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32))
    allc = cv2.GaussianBlur(allc, (0, 0), 0.8 * r)
    for kind, groups in (("lantern", lanterns), ("window", windows)):
        for m in groups:
            if len(meta) >= 63:
                break
            gid = len(meta) + 1
            ys, xs = np.nonzero(m)
            size = max(int(np.ptp(xs)) + 1, int(np.ptp(ys)) + 1)
            core = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8))
            sig = max(3.0, 0.7 * size) if kind == "window" else max(20.0, 1.2 * size)
            halo = cv2.GaussianBlur(core.astype(np.float32), (0, 0), sig)
            halo = np.clip(halo / max(halo.max(), 1e-6) * 1.6, 0, 1)
            reg = halo > 0.02
            y0, y1 = max(0, ys.min() - int(4 * sig)), min(H, ys.max() + int(4 * sig) + 1)
            x0, x1 = max(0, xs.min() - int(4 * sig)), min(W, xs.max() + int(4 * sig) + 1)
            sl = (slice(y0, y1), slice(x0, x1))
            cs = cv2.GaussianBlur(core[sl].astype(np.float32), (0, 0), 0.8 * r)
            others = 1 - np.clip(allc[sl] - cs, 0, 1)
            if kind == "window":
                # Unlit window: compress the bright pane (and any lit wall it spills on) down to its
                # surroundings' ambient level, keeping texture, with a cooler tint; the warm spill fades.
                Ls = lum[sl]
                ring = (cv2.dilate(core[sl], np.ones((15, 15), np.uint8)) > 0) & (core[sl] == 0)
                Lbg = max(float(np.percentile(Ls[ring] if ring.any() else Ls, 35)), 0.02)
                comp = np.where(Ls > Lbg, Lbg * (Ls / Lbg) ** 0.25 / np.maximum(Ls, 1e-4), 1.0)
                f = 1 - cs * (1 - comp)
                spill = halo[sl] * (1 - cs) * others

                def unlit(src):
                    o = src * f[..., None]
                    # Glass reflects the dusk sky: desaturate the (formerly lamp-colored) pane, then cool it.
                    gray = (o @ lw)[..., None]
                    dusk = gray * np.array([0.85, 0.9, 1.15], np.float32)
                    o = o * (1 - 0.85 * cs[..., None]) + dusk * 0.85 * cs[..., None]
                    return o * (1 - 0.3 * spill)[..., None]
            else:
                def unlit(src):
                    return src * (1 - 0.6 * halo[sl] * others)[..., None]
            r3 = reg[sl][..., None]
            off[sl] = np.where(r3, unlit(off[sl]), off[sl])
            # Overlapping lights compose multiplicatively, so shares split the log-ratio (exact for halos).
            s = np.where(reg[sl], np.abs(np.log((unlit(a[sl]) + 1 / 255) / (a[sl] + 1 / 255))).mean(-1), 0.0)
            cand_s = np.where(s > 1 / 512, s, 0.0).astype(np.float32)
            cand_i = np.full(cand_s.shape, gid, np.uint8)
            ts, ti = top_s[:, y0:y1, x0:x1], top_i[:, y0:y1, x0:x1]   # views
            for k in range(5):   # insertion into the sorted top 5; the displaced entry moves down a rank
                sw = cand_s > ts[k]
                ps, pi = ts[k].copy(), ti[k].copy()
                ts[k][sw], ti[k][sw] = cand_s[sw], cand_i[sw]
                cand_s, cand_i = np.where(sw, ps, cand_s), np.where(sw, pi, cand_i)
            cx, cy = float(xs.mean() / W), float(ys.mean() / H)
            col = slice(int(xs.min()), int(xs.max()) + 1)
            below = water[int(ys.max()): min(H, int(ys.max() + 0.14 * H)), col]
            meta.append({"id": gid, "kind": kind, "x": round(cx, 4), "y": round(cy, 4), "size_px": int(size),
                         "disp": round(float(disp[int(ys.mean()), int(xs.mean())]), 4),
                         "reflective": bool(kind == "window" and below.size and (below > 0.5).mean() > 0.02)})
    tot = top_s[:4].sum(0)
    w = np.where(tot > 0, top_s[:4] / np.maximum(tot, 1e-9), 0.0)
    i4 = top_i[3].astype(np.uint16)
    ids = np.stack([top_i[k] | ((i4 >> (2 * k)) & 3) << 6 for k in range(3)], -1).astype(np.uint8)
    wts = np.stack([np.round(w[k] * 255) for k in range(3)], -1).astype(np.uint8)
    # A 5th overlapping light's share is dropped (a bounded seam if that light switches on its own).
    print(f"  light groups: {len(meta)}, max dropped 5th-light log-ratio {top_s[4].max():.3f}")
    return ids, wts, off, meta
