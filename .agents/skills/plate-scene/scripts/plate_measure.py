"""Measure a prepared plate before writing its scene (plate-scene skill).

Coordinates are normalized plate coords (x, y in 0..1, y down): the same units as scenes/<scene>/scene.js
and assets/keyart/<plate>.masks.json. <plate> is a plate name (out/plates/<plate>/, from tools/plate_prep.py).

Usage (repo root):
  .venv\\Scripts\\python .agents\\skills\\plate-scene\\scripts\\plate_measure.py grid  <image.png> --box x0,y0,x1,y1 [--step 0.01] [--zoom 2] --out <png>
  .venv\\Scripts\\python .agents\\skills\\plate-scene\\scripts\\plate_measure.py disp  <plate> [--box x0,y0,x1,y1] [--bins 24] [--thr 0.105 --out <png>]
  .venv\\Scripts\\python .agents\\skills\\plate-scene\\scripts\\plate_measure.py rows  <plate> [--box x0,y0,x1,y1] [--step 0.01]
  .venv\\Scripts\\python .agents\\skills\\plate-scene\\scripts\\plate_measure.py cands <plate>
  .venv\\Scripts\\python .agents\\skills\\plate-scene\\scripts\\plate_measure.py diff  <a.png> <b.png> --out <png> [--gain 8] [--box x0,y0,x1,y1]

  grid   crop of any 16:9 image (plate.png, a still, depth8.png) with a labeled coordinate grid, upscaled with
         nearest-neighbour so block edges stay sharp. Read pet-rig points, runoff lips, water-polygon vertices,
         boat-path points and qa_regions boxes off it. Prints the size of one grid step in 4K px.
  disp   disparity (depth.png, 0 far .. 1 near) histogram and percentiles in a box, plus percentiles inside every
         qa_regions box of <plate>.masks.json (solid objects: outdoor_disp must stay below them). --thr --out
         writes a preview of "outdoors = disparity < thr".
  rows   median disparity per row band on the water mask (masks.png G) inside the box. Flat water seen from
         above rises smoothly in disparity with y; drops or jumps mean the mask mixes in shore, islands,
         foliage, reflections or a separate stretch of water (e.g. water seen through rail gaps).
  cands  drip/stream candidates (plate.json drip_candidates, normalized) and the switchable light groups.
  diff   amplified |a - b| of two stills (what moves between two frames) and the largest changed regions.
"""
import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[4]


def box_arg(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4 or not (v[0] < v[2] and v[1] < v[3]):
        raise argparse.ArgumentTypeError("box must be x0,y0,x1,y1 with x0 < x1 and y0 < y1 (0..1)")
    return v


def px_box(box, W, H):
    x0, y0, x1, y1 = box
    return int(np.floor(x0 * W)), int(np.floor(y0 * H)), int(np.ceil(x1 * W)), int(np.ceil(y1 * H))


def plate_dir(name):
    d = ROOT / "out" / "plates" / name
    if not d.is_dir():
        sys.exit(f"no plate folder {d} (run tools/plate_prep.py first)")
    return d


def load_disp(name):
    d = cv2.imread(str(plate_dir(name) / "depth.png"), cv2.IMREAD_UNCHANGED)
    return d.astype(np.float32) / 65535.0


def load_masks_json(name):
    p = ROOT / "assets" / "keyart" / f"{name}.masks.json"
    return json.loads(p.read_text()) if p.exists() else {}


def put_label(img, text, org, color=(80, 255, 80)):
    (w, h), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    x, y = org
    cv2.rectangle(img, (x - 1, y - h - 2), (x + w + 1, y + base), (0, 0, 0), -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def cmd_grid(a):
    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"cannot read {a.image}")
    H, W = img.shape[:2]
    x0, y0, x1, y1 = px_box(a.box, W, H)
    crop = img[y0:y1, x0:x1]
    z = a.zoom
    big = cv2.resize(crop, (crop.shape[1] * z, crop.shape[0] * z), interpolation=cv2.INTER_NEAREST)
    step = a.step
    dec = 2 if abs(step * 100 - round(step * 100)) < 1e-9 else 3 if abs(step * 1000 - round(step * 1000)) < 1e-9 else 4
    for axis in (0, 1):
        lo, hi = (a.box[0], a.box[2]) if axis == 0 else (a.box[1], a.box[3])
        # Label every n-th line so labels don't overlap (x labels ~50 px wide, y labels ~18 px high).
        every = max(1, int(np.ceil((50 if axis == 0 else 18) / max(step * (W if axis == 0 else H) * z, 1e-6))))
        k0, k1 = int(np.ceil(lo / step - 1e-9)), int(np.floor(hi / step + 1e-9))
        for k in range(k0, k1 + 1):
            v = k * step
            major = k % 5 == 0
            col = (60, 255, 60) if major else (40, 150, 40)
            if axis == 0:
                p = int(round((v * W - x0) * z))
                cv2.line(big, (p, 0), (p, big.shape[0] - 1), col, 1)
                if k % every == 0:
                    put_label(big, f"{v:.{dec}f}", (p + 2, 14))
            else:
                p = int(round((v * H - y0) * z))
                cv2.line(big, (0, p), (big.shape[1] - 1, p), col, 1)
                if k % every == 0:
                    put_label(big, f"{v:.{dec}f}", (2, p - 3), (80, 230, 255))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), big)
    s4k = 3840 / W
    print(f"grid -> {out} ({big.shape[1]}x{big.shape[0]} px; image {W}x{H}, crop {x1 - x0}x{y1 - y0} px, zoom {z})")
    print(f"one grid step = {step * W * s4k:.1f} 4K px across, {step * H * s4k:.1f} 4K px down; "
          f"one image px = {z} grid-image px (x labels green, y labels yellow)")


def text_hist(v, bins, lo, hi, width=50):
    h, e = np.histogram(v, bins=bins, range=(lo, hi))
    m = max(int(h.max()), 1)
    for i in range(bins):
        bar = "#" * int(round(width * h[i] / m))
        print(f"  {e[i]:.3f}-{e[i + 1]:.3f} {h[i] / len(v) * 100:6.2f}% {bar}")


def pct(v, ps=(1, 5, 25, 50, 75, 95, 99)):
    q = np.percentile(v, ps)
    return "  ".join(f"p{p} {x:.3f}" for p, x in zip(ps, q))


def cmd_disp(a):
    disp = load_disp(a.plate)
    H, W = disp.shape
    box = a.box or [0, 0, 1, 1]
    x0, y0, x1, y1 = px_box(box, W, H)
    v = disp[y0:y1, x0:x1].ravel()
    ov = load_masks_json(a.plate)
    print(f"disparity (0 far .. 1 near) in box {box}: {len(v)} px")
    print("  " + pct(v))
    text_hist(v, a.bins, float(v.min()), float(v.max()) + 1e-6)
    print(f"current outdoor_disp in {a.plate}.masks.json: {ov.get('outdoor_disp', '(not set; plate_prep default 0.15)')}")
    regs = ov.get("qa_regions", {})
    if regs:
        print("qa_regions (solid things that must stay dry; outdoor_disp must sit below their low percentiles):")
        for name, b in regs.items():
            rx0, ry0, rx1, ry1 = px_box(b, W, H)
            r = disp[ry0:ry1, rx0:rx1].ravel()
            if len(r):
                print(f"  {name:12s} " + pct(r, (0.5, 1, 5, 50)))
    if a.thr is not None:
        if not a.out:
            sys.exit("--thr needs --out")
        plate = cv2.imread(str(plate_dir(a.plate) / "plate.png"), cv2.IMREAD_COLOR).astype(np.float32)
        m = (disp < a.thr).astype(np.float32)[..., None]
        vis = plate * 0.45 + m * np.array([180, 0, 180], np.float32) * 0.6   # BGR magenta = outdoors
        vis = cv2.resize(np.clip(vis, 0, 255).astype(np.uint8), (1920, 1080), interpolation=cv2.INTER_AREA)
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), vis)
        print(f"outdoors preview (disparity < {a.thr}, magenta; raw threshold, before plate_prep's guided filter "
              f"and only_outdoor clip) -> {out}")


def cmd_rows(a):
    disp = load_disp(a.plate)
    H, W = disp.shape
    m = cv2.imread(str(plate_dir(a.plate) / "masks.png"), cv2.IMREAD_COLOR)[..., 1] > 127   # G = water
    box = a.box or [0, 0, 1, 1]
    x0, y0, x1, y1 = px_box(box, W, H)
    ys, ds, ns = [], [], []
    print(f"water-mask disparity per row band (box {box}, band {a.step}):")
    print(f"  {'y':>6s} {'px':>8s} {'median':>8s} {'p10':>7s} {'p90':>7s}")
    y = box[1]
    while y < box[3] - 1e-9:
        r0, r1 = int(y * H), int(min(y + a.step, box[3]) * H)
        sel = m[r0:r1, x0:x1]
        v = disp[r0:r1, x0:x1][sel]
        if len(v) >= 50:
            yc = (y + min(y + a.step, box[3])) / 2
            ys.append(yc); ds.append(float(np.median(v))); ns.append(len(v))
            print(f"  {yc:6.3f} {len(v):8d} {ds[-1]:8.4f} {np.percentile(v, 10):7.4f} {np.percentile(v, 90):7.4f}")
        y += a.step
    if len(ys) < 3:
        print("  fewer than 3 bands with water pixels: nothing to check")
        return
    # Flat water seen from above: disparity must rise smoothly with y. A drop or a jump means the mask
    # mixes in something else (shore, island, foliage, a reflection, a separate stretch of water).
    D = np.array(ds)
    step = np.diff(D)
    typical = float(np.median(np.abs(step))) + 1e-6
    flagged = False
    for i, dd in enumerate(step):
        if dd < -0.5 * typical or dd > 3 * typical:
            flagged = True
            what = "drops" if dd < 0 else "jumps"
            print(f"  check y {ys[i]:.3f} -> {ys[i + 1]:.3f}: disparity {what} by {dd:+.4f} (typical step {typical:.4f})")
    if not flagged:
        print("  disparity rises smoothly with y: consistent with one flat water surface")
    print("  note: relative depth has an unknown offset, so do not read the horizon off this; "
          "calibrate it from block sizes (lake_camera.mjs fit)")


def cmd_cands(a):
    meta = json.loads((plate_dir(a.plate) / "plate.json").read_text())
    W, H = meta["width"], meta["height"]
    print(f"plate {a.plate}: {W}x{H}, outdoor_disp {meta.get('outdoor_disp')}, env_linear {meta.get('env_linear')}")
    by = {}
    for x, y, kind in meta.get("drip_candidates", []):
        by.setdefault(kind, []).append((x / W, y / H))
    names = {"tip": "tips (lowest points of hanging leaves/vines: drips)", "eave": "eaves (flat edges: streams)",
             "top": "tops (columns open to the frame top: roof edge above the frame, y < 0)"}
    for kind, pts in by.items():
        print(f"{names.get(kind, kind)}: " + "  ".join(f"({x:.3f}, {y:.3f})" for x, y in sorted(pts)))
    lg = meta.get("light_groups", [])
    kinds = {}
    for g in lg:
        kinds.setdefault(g["kind"] + (" (reflective, never switched)" if g.get("reflective") else ""), []).append(g)
    print(f"light groups: {len(lg)}" + ("  WARNING: plate.js only switches ids 1..63" if any(g['id'] > 63 for g in lg) else ""))
    for k, gs in kinds.items():
        print(f"  {k}: " + "  ".join(f"#{g['id']}({g['x']:.3f},{g['y']:.3f})" for g in gs))
    pal = meta.get("foliage_palette", [])
    if pal:
        print("foliage_palette (sRGB, dark -> bright, share): " + "  ".join(f"{i}:#{r:02x}{g:02x}{b:02x} {s:.2f}" for i, (r, g, b, s) in enumerate(pal)))


def cmd_diff(a):
    A = cv2.imread(a.a, cv2.IMREAD_COLOR)
    B = cv2.imread(a.b, cv2.IMREAD_COLOR)
    if A is None or B is None or A.shape != B.shape:
        sys.exit("cannot read both images, or their sizes differ")
    H, W = A.shape[:2]
    d = np.abs(A.astype(np.int16) - B.astype(np.int16)).max(2).astype(np.float32)
    if a.box:
        x0, y0, x1, y1 = px_box(a.box, W, H)
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    dc = d[y0:y1, x0:x1]
    print(f"|a - b| (0..255) in box: mean {dc.mean():.3f}  p99 {np.percentile(dc, 99):.1f}  max {dc.max():.0f}  "
          f"changed (> 2): {(dc > 2).mean() * 100:.2f}% of px")
    m = (cv2.GaussianBlur(dc, (0, 0), 3) > 2).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    for k in (np.argsort(-st[1:, 4])[:6] + 1 if n > 1 else []):
        x, y, w, h, area = st[k]
        print(f"  changed region x {(x0 + x) / W:.3f}-{(x0 + x + w) / W:.3f}  y {(y0 + y) / H:.3f}-{(y0 + y + h) / H:.3f}  ({area} px)")
    vis = np.clip(dc * a.gain, 0, 255).astype(np.uint8)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), vis)
    print(f"diff x{a.gain} -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("grid"); g.add_argument("image"); g.add_argument("--box", type=box_arg, required=True)
    g.add_argument("--step", type=float, default=0.01); g.add_argument("--zoom", type=int, default=2); g.add_argument("--out", required=True)
    d = sp.add_parser("disp"); d.add_argument("plate"); d.add_argument("--box", type=box_arg); d.add_argument("--bins", type=int, default=24)
    d.add_argument("--thr", type=float); d.add_argument("--out")
    r = sp.add_parser("rows"); r.add_argument("plate"); r.add_argument("--box", type=box_arg); r.add_argument("--step", type=float, default=0.01)
    c = sp.add_parser("cands"); c.add_argument("plate")
    f = sp.add_parser("diff"); f.add_argument("a"); f.add_argument("b"); f.add_argument("--out", required=True)
    f.add_argument("--gain", type=float, default=8.0); f.add_argument("--box", type=box_arg)
    a = ap.parse_args()
    {"grid": cmd_grid, "disp": cmd_disp, "rows": cmd_rows, "cands": cmd_cands, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    main()
