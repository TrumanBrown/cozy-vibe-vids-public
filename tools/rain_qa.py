"""Weather QA for plate scenes: rain leak check, loop seam + determinism, rain visibility profile,
lightning flash safety, calibration against reference footage.

Usage (repo root):
  .venv/Scripts/python tools/rain_qa.py <sceneDir> --plate <plate> [--leak] [--seam] [--profile] [--flash] [--calibrate <ref stats.json>]
  e.g. tools/rain_qa.py scenes/treetop-plate --plate treetop_rainy --leak --seam --flash --calibrate docs/reference/treehouse-rain-stats.json

--leak       renders rain-only frames (scene param debug=rain: rain coverage as white on black, no bloom)
             and measures rain energy outside the plate's outdoor mask (lights.png G) and inside the
             named `qa_regions` boxes of assets/keyart/<plate>.masks.json. Must be exactly 0.
--seam       renders frames 0 / loop end (must be identical), the frame pairs across the loop seam vs.
             elsewhere (frame-to-frame change must match), and one frame twice (determinism).
--profile    falling-rain visibility per vertical band (render minus no-rain render).
--flash      WCAG 2.3.1: counts flashes around lightning strikes (<= 3/s required; design: 1 per strike).
--calibrate  renders a few seconds, downscales to the reference's width, runs tools/rain_analyze.py and
             prints our streak statistics next to the reference's (match within ~25%).
Outputs go to out/<scene>/qa/. Exit code 1 if leak/seam/flash checks fail.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

import cv2
import numpy as np

from cozy.paths import ROOT, PY
from cozy.media import run_ffmpeg


def node(*args):
    r = subprocess.run(["node", str(ROOT / "src" / "cli.mjs"), *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"render failed: {r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def still(scene, frames, out, name, params=None):
    args = ["still", scene, "--frames", ",".join(map(str, frames)), "--out", str(out), "--name", name]
    if params:
        args += ["--params", params]
    node(*args)
    return {f: cv2.imread(str(out / f"{name}_4k_f{f:06d}.png"), cv2.IMREAD_COLOR) for f in frames}


def loop_frames(scene):
    src = (ROOT / scene / "scene.js").read_text()
    fps = int(re.search(r"fps:\s*(\d+)", src).group(1)) if re.search(r"fps:\s*(\d+)", src) else 30
    sec = float(re.search(r"loopSeconds:\s*([\d.]+)", src).group(1))
    return int(round(fps * sec)), fps


def leak(scene, plate, out, frames):
    o = cv2.imread(str(ROOT / "out" / "plates" / plate / "lights.png"))[..., 1].astype(np.float32) / 255
    H, W = o.shape
    outside = cv2.dilate((o > 0).astype(np.uint8), np.ones((3, 3), np.uint8)) == 0
    ov = json.loads((ROOT / "assets" / "keyart" / f"{plate}.masks.json").read_text())
    regions = ov.get("qa_regions", {})
    imgs = still(scene, frames, out, "leak", "debug=rain")
    ok = True
    for f, im in imgs.items():
        rain = im.astype(np.float32).mean(2) / 255
        rain[rain <= 1.5 / 255] = 0  # the output stage dithers by +-1/255; that is not rain
        tot, lk = float(rain.sum()), float(rain[outside].sum())
        line = f"frame {f:5d}: rain energy {tot:9.1f}  outside-mask {lk:.3f} (max px {float(rain[outside].max()):.4f})"
        for name, (x0, y0, x1, y1) in regions.items():
            e = float(rain[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)].sum())
            line += f"  {name} {e:.3f}"
            ok &= e == 0.0
        print(line)
        ok &= lk == 0.0
        if lk > 0:
            m = (outside & (rain > 0)).astype(np.uint8)
            n, _, st, _ = cv2.connectedComponentsWithStats(m)
            for k in np.argsort(-st[1:, 4])[:5] + 1:
                x, y, w, h, a = st[k]
                print(f"   leak blob at x {x / W:.3f}-{(x + w) / W:.3f} y {y / H:.3f}-{(y + h) / H:.3f} ({a} px)")
    if imgs:
        f0 = max(imgs, key=lambda f: imgs[f].sum())
        vis = imgs[f0].astype(np.float32) / 255
        vis[outside] = vis[outside] * 0.5 + np.array([0, 0, 0.35])  # BGR: outside the mask tinted red
        cv2.imwrite(str(out / "leak_overlay.png"), cv2.resize((np.clip(vis * 1.5, 0, 1) * 255).astype(np.uint8), (1920, 1080), interpolation=cv2.INTER_AREA))
    print("LEAK", "PASS" if ok else "FAIL")
    return ok


def seam(scene, out):
    """Base loop (events/weather off) must be periodic and seamless; with events on, random access must
    be exact (a frame rendered alone == the same frame rendered mid-sequence), which is what segmented
    full-timeline renders rely on."""
    N, fps = loop_frames(scene)
    mid = N // 2
    pairs = [int(N * k / 7) + 3 * k for k in range(1, 7)]  # comparison pairs (f-1, f) spread over the loop
    a = still(scene, [0, N - 1, N] + [f for p in pairs for f in (p - 1, p)], out, "seamA", "events=off")
    b = still(scene, [mid], out, "seamB", "events=off")
    c = still(scene, [mid], out, "seamC", "events=off")
    same = np.array_equal(a[0], a[N])
    det = np.array_equal(b[mid], c[mid])

    def mad(x, y):
        return float(np.abs(x.astype(np.int16) - y).mean())
    d_seam = mad(a[N], a[N - 1])
    d_ref = [mad(a[p], a[p - 1]) for p in pairs]
    print(f"base loop: frame 0 == frame {N}: {same}   frame {mid} identical across runs: {det}")
    print(f"base loop: frame-to-frame change across the seam {d_seam:.3f}; elsewhere {min(d_ref):.3f}..{max(d_ref):.3f}")
    ok = same and det and 0.7 * min(d_ref) <= d_seam <= 1.3 * max(d_ref)
    # Random access with the full timeline (events + weather): frames from a sequence vs. rendered alone.
    k = 3 * N + 4321
    seq = still(scene, [k - 2, k - 1, k], out, "raSeq")
    alone = still(scene, [k], out, "raAlone")
    ra = np.array_equal(seq[k], alone[k])
    print(f"full timeline: frame {k} rendered alone == rendered in sequence: {ra}")
    ok = ok and ra
    print("SEAM", "PASS" if ok else "FAIL")
    return ok


def calibrate(scene, out, ref_path, seconds=6, start=300, extra=""):
    ref = json.loads(pathlib.Path(ref_path).read_text())
    rw = ref["size"][0]
    frames = out / "cal_frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    mp4 = out / "cal.mp4"
    node("preview", scene, "--seconds", str(seconds), "--start", str(start), "--out", str(mp4), *([f"--params={extra}"] if extra else []))
    run_ffmpeg(["-hide_banner", "-loglevel", "error", "-i", str(mp4), "-vf", f"scale={rw}:-2:flags=area", str(frames / "f_%04d.png")], capture=False)
    subprocess.run([PY, str(ROOT / "tools" / "rain_analyze.py"), str(frames), str(out / "cal")], check=True, capture_output=True)
    ours = json.loads((out / "cal" / "stats.json").read_text())

    def area(stats, png):
        if "rain_area_fraction" in stats:
            return stats["rain_area_fraction"]
        e = cv2.GaussianBlur(cv2.imread(str(png), 0).astype(np.float32), (0, 0), 6)
        return float((e > 0.15 * np.percentile(e, 99)).mean())
    ra = area(ref, pathlib.Path(ref_path).parent / "rain_energy.png")
    oa = area(ours, out / "cal" / "rain_energy.png")
    rows = [("streaks per rain-covered area", ref["streaks_per_frame"] / max(ra, 1e-3), ours["streaks_per_frame"] / max(oa, 1e-3))]
    rows += [(f"length p{k} (px)", ref["length_px_pct"][k], ours["length_px_pct"][k]) for k in ("10", "50", "90", "99")]
    rows += [("width median (px)", ref["width_px_median"], ours["width_px_median"])]
    rows += [(f"angle p{k} (deg)", ref["angle_deg_pct"][k], ours["angle_deg_pct"][k]) for k in ("10", "50", "90")]
    rows += [(f"peak lum p{k}", ref["peak_lum_pct"][k], ours["peak_lum_pct"][k]) for k in ("10", "50", "90", "99")]
    for k in ("10", "25", "50", "75", "90"):
        if k in ref.get("speed_px_per_frame_pct", {}) and k in ours.get("speed_px_per_frame_pct", {}):
            rows.append((f"drop speed p{k} (px/frame)", ref["speed_px_per_frame_pct"][k], ours["speed_px_per_frame_pct"][k]))
    print(f"{'metric':32s} {'reference':>10s} {'ours':>10s}")
    for name, r, o in rows:
        flag = "" if "angle" in name else ("  ok" if abs(o - r) <= 0.25 * max(abs(r), 1e-6) else "  <-")
        print(f"{name:32s} {r:10.3f} {o:10.3f}{flag}")
    print(f"rain-covered area: reference {ra:.2f}, ours {oa:.2f} (depends on the scene's opening)")


def profile(scene, plate, out, frames, bands=8, extra=""):
    """Visible falling-rain contribution per vertical band of the opening: mean |render - no-rain|
    luminance over outdoor pixels, streak count and median streak size (connected components)."""
    o = cv2.imread(str(ROOT / "out" / "plates" / plate / "lights.png"))[..., 1].astype(np.float32) / 255
    H, W = o.shape
    a = still(scene, frames, out, "profA", "only=falling" + ("," + extra if extra else ""))
    b = still(scene, frames, out, "profB", "rain=off")
    xs = np.flatnonzero((o > 0.5).any(0))
    x0, x1 = xs.min(), xs.max() + 1
    edges = np.linspace(x0, x1, bands + 1).astype(int)
    rows = []
    for i in range(bands):
        sl = slice(edges[i], edges[i + 1])
        m = o[:, sl] > 0.5
        e, n, ln, wd = [], 0, [], []
        for f in frames:
            d = np.abs(a[f].astype(np.float32) - b[f].astype(np.float32)).mean(2)[:, sl] / 255
            e.append(float(d[m].mean()))
            bw = ((d > 0.02) & m).astype(np.uint8)
            k, _, st, _ = cv2.connectedComponentsWithStats(bw)
            st = st[1:]
            st = st[st[:, 4] >= 6]
            n += len(st)
            ln += st[:, 3].tolist()
            wd += (st[:, 4] / np.maximum(st[:, 3], 1)).tolist()
        rows.append((edges[i] / W, edges[i + 1] / W, float(np.mean(e)), n / len(frames), float(np.median(ln)) if ln else 0, float(np.percentile(ln, 90)) if ln else 0, float(np.median(wd)) if wd else 0))
    print(f"{'x band':13s} {'energy':>8s} {'streaks':>8s} {'len p50':>8s} {'len p90':>8s} {'width':>6s}   (4K px, falling rain only)")
    for r in rows:
        print(f"{r[0]:.2f}-{r[1]:.2f}    {r[2] * 1000:8.2f} {r[3]:8.0f} {r[4]:8.1f} {r[5]:8.1f} {r[6]:6.2f}")
    return rows


def wcag_transitions(s, thr=0.1):
    """WCAG 2.3.1 general flash: opposing changes in relative luminance >= thr where the darker state is
    below 0.8. Returns the frame indices of counted transitions (two transitions = one flash)."""
    out, hi, lo, state = [], s[0], s[0], 0
    for i, v in enumerate(s):
        hi, lo = max(hi, v), min(lo, v)
        if state >= 0 and hi - v >= thr and v < 0.8:
            out.append(i); state = -1; lo = hi = v
        elif state <= 0 and v - lo >= thr and lo < 0.8:
            out.append(i); state = 1; lo = hi = v
    return out


def flash(scene, out, events=4):
    """Renders 4 s around the first lightning strikes (preferring multi-stroke ones) and the strongest
    multi-pulse distant flashes, and counts WCAG flashes on the brightest 1/4-frame region.
    Pass: <= 3 flashes in any 1 s window (target: 1 per strike)."""
    node("timeline", scene, "--out", str(out / "timeline.json"))
    tl = json.loads((out / "timeline.json").read_text())
    ev = sorted([e for e in tl["events"] if e["type"] == "lightning"], key=lambda e: -len(e["strokes"]))[:events]
    ev += sorted([e for e in tl["events"] if e["type"] == "farflash"], key=lambda e: (-len(e["strokes"]), -e["power"]))[:2]
    ok = True
    for e in sorted(ev, key=lambda e: e["t"]):
        f0 = max(0, e["frame"] - 15)
        mp4 = out / f"flash_{e['id']}.mp4"
        node("preview", scene, "--seconds", "4", "--start", str(f0), "--width", "960", "--height", "540", "--codec", "h264_nvenc", "--audio", "off", "--out", str(mp4))
        cap = cv2.VideoCapture(str(mp4))
        L = []
        while True:
            okf, fr = cap.read()
            if not okf:
                break
            c = fr[..., ::-1].astype(np.float32) / 255
            c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
            L.append(c @ np.array([0.2126, 0.7152, 0.0722], np.float32))
        L = np.stack(L)
        H, W = L.shape[1:]
        gain = (L.max(0) - L[0])
        best, bs = None, -1.0
        for y in range(0, H - H // 2 + 1, H // 8):        # quarter-frame windows; brightest swing wins
            for x in range(0, W - W // 2 + 1, W // 8):
                v = gain[y:y + H // 2, x:x + W // 2].mean()
                if v > bs:
                    bs, best = v, (y, x)
        y, x = best
        s = L[:, y:y + H // 2, x:x + W // 2].mean((1, 2))
        tr = wcag_transitions(s)
        per_s = max((sum(1 for t in tr if a <= t < a + 30) for a in range(len(s))), default=0) / 2
        ok &= per_s <= 3
        print(f"{e['type']} #{e['id']} ({len(e['strokes'])} strokes): region lum {s.min():.3f}..{s.max():.3f}, "
              f"WCAG transitions {len(tr)} -> {len(tr) / 2:.1f} flashes, max {per_s:.1f}/s")
    print("FLASH", "PASS" if ok else "FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--plate", required=True)
    ap.add_argument("--leak", action="store_true")
    ap.add_argument("--seam", action="store_true")
    ap.add_argument("--profile", action="store_true", help="falling-rain visibility per vertical band")
    ap.add_argument("--flash", action="store_true", help="WCAG 2.3.1 flash check around lightning strikes")
    ap.add_argument("--params", default="", help="extra scene params for --profile/--calibrate (e.g. rain.alphaRef=0.2)")
    ap.add_argument("--calibrate")
    ap.add_argument("--frames", default="", help="leak/profile frames (default: 8 spread over the loop)")
    a = ap.parse_args()
    out = ROOT / "out" / pathlib.Path(a.scene).name / "qa"
    out.mkdir(parents=True, exist_ok=True)
    ok = True
    N, _ = loop_frames(a.scene)
    frames = [int(f) for f in a.frames.split(",")] if a.frames else [int(N * k / 8) + 7 * k for k in range(8)]
    if a.leak:
        ok &= leak(a.scene, a.plate, out, frames)
    if a.profile:
        profile(a.scene, a.plate, out, frames, extra=a.params)
    if a.flash:
        ok &= flash(a.scene, out)
    if a.seam:
        ok &= seam(a.scene, out)
    if a.calibrate:
        calibrate(a.scene, out, a.calibrate, extra=a.params)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
