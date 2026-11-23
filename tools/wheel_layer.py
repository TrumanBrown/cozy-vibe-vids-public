"""Take a painted waterwheel apart so it can turn (Truman 2026-11-08: the mill's waterwheel turning the whole video).

  .venv\\Scripts\\python tools\\wheel_layer.py <scene> [--no-clean-item] [--preview]

Reads assets/keyart/<scene>.hand.json "wheel" (px of the 4K plate):
  {"rim": [cx, cy, a, b, angle]       a first guess of the front rim's ellipse (refined on its painted edge),
   "spoke_lines": [[[x, y], [x, y]], ...]   two points on each visible spoke: they meet at the hub,
   "ref_spoke": 0                     the spoke (index into spoke_lines) every spoke of the turning wheel is drawn from,
   "spokes": 8, "depth": [dx, dy]     a first guess of how far the back rim sits from the front one (refined),
   "depth_reach": 36                  how far (px) the refinement may move it: narrow it when the back rim's edge sits
                                      near another strong edge (a roof's eave, a log wall's lines) that it would take
                                      instead (the Sleeping Hound Inn's mill, 2026-11-15: 36 px took the back rim up
                                      past the painted one, tilting the paddles against the painting's),
   "rim_arc": [0, 180]                the arc of the front rim (wheel degrees) that shows whole: its texture's period,
   "occluders": [{"box": [x0, y0, x1, y1], "points": [[x, y], ...], "neg": [[x, y], ...], "poly": [[x, y], ...]}, ...]
                                      each part that stands in front of the wheel (a trestle's post and legs, the hub
                                      cap), SAM in its own tight box, unioned with the part's traced outline if given (a
                                      thin plank), holes closed,
   "waterline": [[x, y], ...]         the water's edge across the wheel: below it the water is in front,
   "turn_s": 16, "dir": 1             one turn in that many seconds (whole turns per loop), 1 = counterclockwise as seen,
   "band_alpha": 0.9                  the least alpha anywhere on the paddle band (optional): the band's alpha comes from
                                      brightness, lit boards and dark gaps; boards painted dark and lit only along their
                                      edges need a floor, or the wall behind shows through the band,
   "band_contrast": 2.2               (optional) each band row stretched away from its gaps' level: the fold's median
                                      over the periods softens the boards,
   "reflect": 110}                    px of water under the waterline that mirror the wheel (0: none)
and writes out/plates/<scene>/wheel/: rim.png, spoke.png, band.png (the textures that repeat as it turns), occ.png
(what stays in front, over the wheel's box), wheel.json (the geometry, cozy/plate/wheel.py), preview.jpg (the fit
over the painting) and turns.jpg (the wheel drawn turned by a quarter spoke, half and a whole spoke). Unless
--no-clean-item, it writes the clean.json item "waterwheel" that repaints the wall and water behind the wheel
(tools/plate_clean.py), so the plate under the turning wheel never shows the painted one.
"""
import argparse
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image

from cozy.paths import ROOT
from cozy.plate import wheel as WH


def source(scene):
    """The key art as painted, at the plate's size: textures come from the wheel before its wall was repainted."""
    out = ROOT / "out" / "plates" / scene
    clean = ROOT / "assets" / "keyart" / scene / "clean.png"
    if clean.exists() and clean.with_suffix(".json").exists():
        from cozy.plate.image import original_4k
        return original_4k(clean, out)
    return Image.open(out / "plate_raw.png").convert("RGB")


def across(img, geo, angle, span=0.14):
    """The painted spoke's center and half width across it (local units): its bright run in the median profile."""
    t = np.linspace(0.35, 0.75, 120)
    w = np.linspace(-span, span, 141)
    T, Wd = np.meshgrid(t, w, indexing="ij")
    lx, ly = T * np.cos(angle) - Wd * np.sin(angle), T * np.sin(angle) + Wd * np.cos(angle)
    x, y = WH.to_img(geo, np.hypot(lx, ly), np.arctan2(ly, lx))
    prof = np.median(WH._sample(img, x, y) @ WH.LUM, 0)
    bg = np.percentile(prof, 30)
    k = int(np.argmax(prof))
    mid = bg + 0.5 * (prof[k] - bg)
    i0, i1 = k, k
    while i0 > 0 and prof[i0 - 1] > mid:
        i0 -= 1
    while i1 < len(prof) - 1 and prof[i1 + 1] > mid:
        i1 += 1
    return float((w[i0] + w[i1]) / 2), float((w[i1] - w[i0]) / 2 + (w[1] - w[0]) / 2)


def rim_band(img, geo, arc):
    """The rim's inner and outer radius (local units) from its radial profile over the visible arc."""
    r = np.linspace(0.6, 1.08, 240)
    th = np.deg2rad(np.linspace(arc[0] + 10, arc[1] - 10, 90))
    RR, TT = np.meshgrid(r, th, indexing="ij")
    prof = np.median(WH._sample(img, *WH.to_img(geo, RR, TT)) @ WH.LUM, 1)
    inner = prof[(r > 0.62) & (r < 0.75)].mean()
    rim = np.percentile(prof[(r > 0.85) & (r < 0.99)], 60)
    mid = inner + 0.5 * (rim - inner)
    i = int(np.searchsorted(r, 0.93))
    lo = i
    while lo > 0 and prof[lo - 1] > mid:
        lo -= 1
    hi = i
    while hi < len(r) - 1 and prof[hi + 1] > mid:
        hi += 1
    return [float(r[lo]), float(min(r[hi], 1.02))]


def occluders(img, spec, shape):
    """What stays in front of the turning wheel, as (parts, water): each part SAM finds in its own tight box (the
    trestle's post and legs, the hub cap: one object in one box, prompted as a whole, took the wheel with them), and
    the water under the waterline. Of SAM's candidates the smallest that holds every point on the part and none of
    the points off it."""
    H, W = shape
    m = np.zeros((H, W), bool)
    water = np.zeros((H, W), bool)
    parts = spec.get("occluders") or []
    seg = None
    for part in parts if isinstance(parts, list) else [parts]:
        if not part.get("points"):
            continue
        if seg is None:
            from cozy.segment import Segmenter
            seg = Segmenter()
        x0, y0, x1, y1 = [int(v) for v in part["box"]]
        pad = 24
        cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
        crop = img.crop((cx0, cy0, cx1, cy1))
        pos = [(x - cx0, y - cy0) for x, y in part["points"]]
        neg = [(x - cx0, y - cy0) for x, y in part.get("neg", [])]
        cands = seg.prompt_candidates(crop, (x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0), pos + neg, [1] * len(pos) + [0] * len(neg))

        def fits(c):
            mm = c[0]
            return all(mm[int(y), int(x)] for x, y in pos) and not any(mm[int(y), int(x)] for x, y in neg)
        ok = [c for c in cands if fits(c)] or cands
        best = min(ok, key=lambda c: c[0].sum())[0]
        best &= np.pad(np.ones((y1 - y0, x1 - x0), bool), ((y0 - cy0, cy1 - y1), (x0 - cx0, cx1 - x1)))
        if part.get("poly"):
            # a thin plank's traced outline: SAM leaves holes in a leg a dozen px wide
            pm = np.zeros(best.shape, np.uint8)
            cv2.fillPoly(pm, [np.round(np.asarray(part["poly"], float) - [cx0, cy0]).astype(np.int32)], 1)
            best |= pm > 0
        best = cv2.morphologyEx(best.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        m[cy0:cy1, cx0:cx1] |= best
    wl = spec.get("waterline")
    if wl:
        xs = np.arange(W)
        pts = np.asarray(wl, float)
        yw = np.interp(xs, pts[:, 0], pts[:, 1])
        water = np.arange(H)[:, None] >= yw[None, :]
    return m, water


def render(img_bg, geo, tex, occ, phi, box):
    """The wheel turned by phi (rad) over img_bg inside box, in numpy: the shader's rule, for the previews."""
    x0, y0, x1, y1 = box
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    M = WH.ellipse_M(*geo["rim"][2:])
    Mi = np.linalg.inv(M)
    Ki = np.linalg.inv(WH.homography(geo))
    c = np.asarray(geo["rim"][:2])
    d = np.asarray(geo["d"])

    def face(px, py):
        """Premultiplied (r, g, b, a): the spokes, the rim over them."""
        xn = Mi @ np.stack([(px - c[0]).ravel(), (py - c[1]).ravel()])
        loc = Ki @ np.vstack([xn, np.ones(xn.shape[1])])
        lx, ly = loc[0] / loc[2], loc[1] / loc[2]
        rho, th = np.hypot(lx, ly), np.arctan2(ly, lx) - geo["dir"] * phi
        out = np.zeros((len(rho), 4))
        n = geo["spokes"]
        k = np.round((th - geo["spoke0"]) / (2 * np.pi / n))
        a = th - (geo["spoke0"] + k * 2 * np.pi / n)
        t, w = rho * np.cos(a), rho * np.sin(a)
        sp = tex["spoke"]
        u = (w - (geo["spoke_c"] - 1.6 * geo["spoke_h"])) / (3.2 * geo["spoke_h"])
        v = (t - geo["spoke_t"][0]) / (geo["spoke_t"][1] - geo["spoke_t"][0])
        ok = (u >= 0) & (u < 1) & (v >= 0) & (v < 1) & (t > 0)
        s = sp[(v[ok] * (sp.shape[0] - 1)).astype(int), (u[ok] * (sp.shape[1] - 1)).astype(int)]
        out[ok] = np.concatenate([s[:, :3] * s[:, 3:4], s[:, 3:4]], 1)
        rm = tex["rim"]
        r0, r1 = geo["rim_tex_rho"]
        v = (rho - r0) / (r1 - r0)
        u = ((th - geo["rim_start"]) % geo["rim_period"]) / geo["rim_period"]
        ok = (v >= 0) & (v < 1)
        s = rm[(v[ok] * (rm.shape[0] - 1)).astype(int), (u[ok] * (rm.shape[1] - 1)).astype(int)]
        al = s[:, 3:4]
        out[ok] = np.concatenate([s[:, :3] * al, al], 1) + out[ok] * (1 - al)
        return out.reshape(px.shape + (4,))

    def band(px, py):
        """Premultiplied (r, g, b, a): the paddle band on the side the wheel shows."""
        e = Mi @ d
        wv = Mi @ np.stack([(px - c[0]).ravel(), (py - c[1]).ravel()])
        A = e @ e
        B = -2 * (wv * e[:, None]).sum(0)
        C = (wv * wv).sum(0) - 1
        disc = B * B - 4 * A * C
        out = np.zeros((wv.shape[1], 4))
        sq = np.sqrt(np.maximum(disc, 0))
        for s in ((-B - sq) / (2 * A), (-B + sq) / (2 * A)):
            q = wv - s[None] * e[:, None]
            ok = (disc >= 0) & (s >= 0) & (s <= 1) & ((q * e[:, None]).sum(0) > 0) & (out[:, 3] == 0)
            loc = Ki @ np.vstack([q, np.ones(q.shape[1])])
            psi = np.arctan2(loc[1] / loc[2], loc[0] / loc[2]) - geo["dir"] * phi
            bt = tex["band"]
            u = ((psi - geo["paddle_phase"] + geo["paddle_period"] / 2) % geo["paddle_period"]) / geo["paddle_period"]
            v = bt[np.clip((s[ok] * (bt.shape[0] - 1)).astype(int), 0, bt.shape[0] - 1), (u[ok] * (bt.shape[1] - 1)).astype(int)]
            out[ok] = np.concatenate([v[:, :3] * v[:, 3:4], v[:, 3:4]], 1)
        return out.reshape(px.shape + (4,))

    f = face(xs, ys)
    bnd = band(xs, ys)
    bk = face(xs - d[0], ys - d[1])
    bk[..., :3] *= geo["back_dark"]
    acc, a = f[..., :3], f[..., 3:4]
    acc = acc + (1 - a) * bnd[..., :3]
    a = a + (1 - a) * bnd[..., 3:4]
    acc = acc + (1 - a) * bk[..., :3]
    a = a + (1 - a) * bk[..., 3:4]
    keep = 1 - occ[y0:y1, x0:x1, None]
    base = img_bg[y0:y1, x0:x1]
    return base * (1 - a * keep) + acc * keep


def at_rest(wheel_dir, img):
    """img (float RGB at the plate's 4K size) with the wheel drawn over it unturned, from the layer's saved textures:
    the picture as the viewer sees it where the clean took the painted wheel out (the critic judged the bare trestle
    standing in the water a pale figure, 2026-11-08). img itself when there is no wheel."""
    wd = pathlib.Path(wheel_dir)
    if not (wd / "wheel.json").exists():
        return img
    geo = json.loads((wd / "wheel.json").read_text(encoding="utf-8"))
    tex = {k: np.asarray(Image.open(wd / f"{k}.png").convert("RGBA"), np.float64) / 255 for k in ("rim", "spoke", "band")}
    x0, y0, x1, y1 = geo["box"]
    occ = np.zeros(img.shape[:2], np.float64)
    o = np.asarray(Image.open(wd / "occ.png").convert("RGB"), np.float64) / 255
    occ[y0:y1, x0:x1] = np.maximum(o[..., 0], o[..., 1])
    out = img.copy()
    out[y0:y1, x0:x1] = render(img, geo, tex, occ, 0.0, geo["box"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene")
    ap.add_argument("--no-clean-item", action="store_true")
    a = ap.parse_args()
    hand = json.loads((ROOT / "assets" / "keyart" / f"{a.scene}.hand.json").read_text(encoding="utf-8"))
    spec = hand.get("wheel")
    if not spec:
        sys.exit(f"no \"wheel\" in assets/keyart/{a.scene}.hand.json")
    out = ROOT / "out" / "plates" / a.scene / "wheel"
    out.mkdir(parents=True, exist_ok=True)
    pil = source(a.scene)
    img = np.asarray(pil, np.float32) / 255
    H, W = img.shape[:2]
    lum = img @ WH.LUM
    rim, rs = WH.fit_rim(lum, spec["rim"])
    hub = WH.hub_from_lines(spec["spoke_lines"])
    M = WH.ellipse_M(*rim[2:])
    geo = {"rim": rim, "hub": hub.tolist(), "hn": (np.linalg.inv(M) @ (hub - rim[:2])).tolist()}
    d, ds = WH.fit_depth(lum, rim, spec.get("depth", [100, 0]), reach=float(spec.get("depth_reach", 36.0)))
    geo["d"] = d
    ref = spec["spoke_lines"][spec.get("ref_spoke", 0)]
    ang, _ = WH.local_angle(geo, ref[1])
    c, h = across(img, geo, ang)
    # the bright core of the painted spoke, and its ink outline on both sides (about a third of its half width)
    h += float(spec.get("spoke_outline", 0.4)) * h
    arc = spec.get("rim_arc", [0, 180])
    band = rim_band(img, geo, arc)
    geo.update({"spokes": int(spec.get("spokes", 8)), "spoke_ref": ang, "spoke_c": c, "spoke_h": h, "rim_band": band})
    # the ideal spokes: evenly spaced from the reference spoke; their texture runs from the hub to under the rim
    geo["spoke0"] = ang
    geo["spoke_t"] = [0.0, band[0] + 0.03]
    parts, water = occluders(pil, spec, (H, W))
    occ = parts | water
    # the band: the columns that show, the paddles' spacing, one period folded
    psi = np.linspace(-np.pi, np.pi, 1440, endpoint=False)
    vis = WH.band_visible(geo, psi, occ.astype(np.float32))
    bstrip, psi_b, s_b = WH.band_unwrap(img, geo, (psi[vis].min(), psi[vis].max()), n_psi=900)
    vis_b = WH.band_visible(geo, psi_b, occ.astype(np.float32))
    period, phase = WH.paddle_period(bstrip[:, vis_b], psi_b[vis_b])
    # a whole number of paddles a turn: the band repeats exactly after every turn, so the loop's seam (whole turns) is
    # seamless (24.03 measured on the mill's wheel would have jumped a quarter paddle at the seam)
    paddles = max(3, int(round(2 * np.pi / period)))
    period = 2 * np.pi / paddles
    geo.update({"paddle_period": period, "paddle_phase": phase, "paddles": paddles})
    tex = {"rim": WH.rim_texture(img, geo, np.deg2rad(arc[0]), np.deg2rad(arc[1] - arc[0])),
           "spoke": WH.spoke_texture(img, geo, ang, c, h, tuple(geo["spoke_t"])),
           "band": WH.band_texture(bstrip, psi_b, period, phase, vis_b)}
    if spec.get("band_alpha"):
        # boards painted dark and lit only along their edges read as gaps by brightness, and the wall behind showed
        # through the band (the Sleeping Hound Inn's mill, 2026-11-15): there the gaps are the wheel's dark inside
        tex["band"][..., 3] = np.maximum(tex["band"][..., 3], float(spec["band_alpha"]))
    if spec.get("band_contrast"):
        # the fold's median over the periods in view softens the boards; stretch each row away from its gaps' level
        t = tex["band"]
        base = np.percentile(t[..., :3], 20, axis=1, keepdims=True)
        t[..., :3] = np.clip(base + float(spec["band_contrast"]) * (t[..., :3] - base), 0, 1)
    if (2 * np.pi / np.deg2rad(arc[1] - arc[0])) % 1:
        sys.exit(f"rim_arc {arc}: its span must divide a turn (180, 120, 90 degrees...), or the rim jumps at the loop's seam")
    geo.update({"rim_start": float(np.deg2rad(arc[0])), "rim_period": float(np.deg2rad(arc[1] - arc[0])), "rim_tex_rho": [0.78, 1.05],
                "back_dark": float(spec.get("back_dark", 0.45)), "dir": int(spec.get("dir", 1)), "turn_s": float(spec.get("turn_s", 16)),
                "reflect": float(spec.get("reflect", 0))})
    for k, t in tex.items():
        WH.save_rgba(out / f"{k}.png", t)
    sil = WH.silhouette(geo, (H, W))
    ys, xs = np.nonzero(sil)
    pad = 8
    box = [int(max(0, xs.min() - pad)), int(max(0, ys.min() - pad)), int(min(W, xs.max() + pad)), int(min(H, ys.max() + pad))]
    if geo["reflect"]:
        box[3] = int(min(H, box[3] + geo["reflect"]))
    geo["box"] = box
    # what stays in front, over the wheel's box: R the trestle's parts and the hub cap, G the water under the waterline
    occ_rgb = np.stack([cv2.GaussianBlur(parts.astype(np.float32), (0, 0), 0.8), cv2.GaussianBlur(water.astype(np.float32), (0, 0), 0.8),
                        np.zeros((H, W), np.float32)], -1)
    Image.fromarray((occ_rgb[box[1]:box[3], box[0]:box[2]] * 255).round().astype(np.uint8), "RGB").save(out / "occ.png")
    if spec.get("waterline"):
        geo["waterline"] = spec["waterline"]
    WH.write_meta(out / "wheel.json", geo, {"fit": {"rim_edge": round(rs, 4), "depth_edge": round(ds, 4)}})
    print(f"wheel: rim {np.round(rim, 1).tolist()} (edge {rs:.3f}), hub {np.round(hub, 1).tolist()}, depth {d} (edge {ds:.3f}), "
          f"spoke {np.degrees(ang):.1f} deg c {c:+.3f} half {h:.3f}, rim {np.round(band, 3).tolist()}, paddles {geo['paddles']} "
          f"(period {np.degrees(period):.2f} deg), box {box}")
    # previews: the fit over the painting, and the wheel turned
    o = (img * 255).astype(np.uint8).copy()
    th = np.linspace(0, 2 * np.pi, 360)
    for sh, col in (((0, 0), (255, 255, 0)), (tuple(d), (0, 255, 255))):
        x, y = WH.to_img(geo, np.ones_like(th), th, sh)
        cv2.polylines(o, [np.stack([x, y], 1).round().astype(np.int32)], True, col, 1)
    for k in range(geo["spokes"]):
        rr = np.linspace(0, 1, 30)
        x, y = WH.to_img(geo, rr, np.full_like(rr, geo["spoke0"] + k * 2 * np.pi / geo["spokes"]))
        cv2.polylines(o, [np.stack([x, y], 1).round().astype(np.int32)], False, (255, 0, 255), 1)
    o[occ] = (o[occ] * 0.5 + np.array([255, 80, 0]) * 0.5).astype(np.uint8)
    x0, y0, x1, y1 = box
    Image.fromarray(o[y0:y1, x0:x1]).resize(((x1 - x0) * 2, (y1 - y0) * 2), Image.NEAREST).save(out / "preview.jpg", quality=90)
    bg = img.copy()
    bg[sil & ~occ] *= 0.25                                # the repainted wall is unknown here: a dark stand-in
    tiles = [render(bg, geo, tex, occ.astype(np.float32), f * 2 * np.pi / geo["spokes"], box) for f in (0.0, 0.25, 0.5, 1.0)]
    row = np.concatenate(tiles, 1)
    Image.fromarray((np.clip(row, 0, 1) * 255).round().astype(np.uint8)).save(out / "turns.jpg", quality=90)
    if not a.no_clean_item:
        clean_item(a.scene, geo, sil, parts, (W, H))


def clean_item(scene, geo, sil, parts, size):
    """The clean.json item that repaints what is behind the wheel: its silhouette above the water, less what stays in
    front (the trestle, the hub cap), and the wheel's mirror image in the water under it (the trestle's stays painted)."""
    from cozy.segment import contours
    W, H = size
    m = sil & ~parts
    if geo.get("waterline"):
        pts = np.asarray(geo["waterline"], float)
        yw = np.round(np.interp(np.arange(W), pts[:, 0], pts[:, 1])).astype(int)
        above = np.arange(H)[:, None] < yw[None, :]
        wheel = m & above
        m = wheel.copy()
        for dy in range(int(geo.get("reflect") or 0)):
            src = np.clip(yw - 1 - dy, 0, H - 1)
            dst = np.clip(yw + dy, 0, H - 1)
            cols = np.arange(W)
            m[dst, cols] |= wheel[src, cols]
    m = cv2.dilate(m.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    keep = parts.copy()
    m &= ~keep
    cp = ROOT / "assets" / "keyart" / f"{scene}.clean.json"
    cj = json.loads(cp.read_text(encoding="utf-8"))
    # the trestle and the hub cap are holes in the mask; contours keep only outer edges, so they go as "keep"
    item = {"name": "waterwheel", "kind": "other", "polys": contours(m, W, H, eps=1.0, min_area=20),
            "keep": contours(keep, W, H, eps=0.8, min_area=4),
            "what": "wooden waterwheel (its rim, spokes and paddles) and its reflection in the water",
            "behind": ("the mill's dark wall of rough horizontal logs over a foundation of rounded stones, and the calm dark water "
                       "of the mill race below it with soft ripples; the wooden trestle that holds the axle and the round hub cap "
                       "on it stay exactly as they are"),
            "note": "tools/wheel_layer.py: the wheel turns on its own layer (src/library/wheel.js), so the plate shows what is behind it"}
    cj["items"] = [i for i in cj.get("items", []) if i.get("name") != "waterwheel"] + [item]
    cp.write_text(json.dumps(cj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"clean.json: item \"waterwheel\" ({len(item['polys'])} polygon(s)): run tools/plate_clean.py {scene} --only waterwheel")


if __name__ == "__main__":
    main()
