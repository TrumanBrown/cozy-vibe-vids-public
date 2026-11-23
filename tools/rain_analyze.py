"""Analyze rain in a clip (reference footage or our renders): separate the rain layer from the static
scene, then measure streak geometry and motion so procedural rain can be calibrated against footage.

Usage: .venv/Scripts/python tools/rain_analyze.py <frames_dir with f_*.png> <out_dir>
Outputs: rain_layer_XXX.png (amplified rain-only frames), rain_energy.png, stats.json, printed stats.
Compare our render with a reference at the same frame width (see tools/rain_qa.py --calibrate).
"""
import json
import pathlib
import sys

import cv2
import numpy as np


# Streak statistics on one frame: threshold, connected components, fit length/width/angle.
def streaks(r, thr):
    m = (r > thr).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    res = []
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if a < 3:
            continue
        ys, xs = np.nonzero(lab[y:y + h, x:x + w] == k)
        pts = np.stack([xs + x, ys + y], 1).astype(np.float32)
        c = pts.mean(0)
        u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
        d = vt[0]
        proj = (pts - c) @ d
        length = proj.max() - proj.min() + 1
        width = a / length
        ang = np.degrees(np.arctan2(d[0], d[1]))  # 0 = vertical
        ang = (ang + 90) % 180 - 90
        peak = r[lab == k].max()
        res.append((length, width, ang, peak, c[0], c[1]))
    return np.array(res)


# Per-drop speeds (count-based): track streak centroids over 3 consecutive frames and keep matches that
# move with constant velocity (c, c + v, c + 2v within 2 px). Robust to dense rain and bright streams.
def track(S0, S1, S2, max_dx=8, max_dy=90, tol=2.0):
    A, B, C = S0[:, 4:6], S1[:, 4:6], S2[:, 4:6]
    d = B[None] - A[:, None]
    ok = (np.abs(d[..., 0]) <= max_dx) & (d[..., 1] >= 1) & (d[..., 1] <= max_dy)
    ratio = S1[None, :, 0] / S0[:, None, 0]
    ok &= (ratio > 0.5) & (ratio < 2.0)
    ia, ib = np.nonzero(ok)
    if len(ia) == 0:
        return np.zeros((0, 3))
    pred = A[ia] + 2 * d[ia, ib]
    err = np.sqrt(((pred[:, None, :] - C[None]) ** 2).sum(-1)).min(1)
    good = err < tol
    best = {}
    for a, b, e in zip(ia[good], ib[good], err[good]):
        if a not in best or e < best[a][1]:
            best[a] = (b, e)
    return np.array([[d[a, b, 1], S0[a, 0], S0[a, 1]] for a, (b, _) in best.items()])  # speed, length, width


def main():
    src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob("f_*.png"))
    frames = np.stack([cv2.imread(str(f), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32) / 255 for f in files])
    T, H, W, _ = frames.shape
    lum = frames @ np.array([0.2126, 0.7152, 0.0722], np.float32)

    # Static background = temporal median over a sliding window; rain = positive residual (rain is additive light).
    bg = np.median(lum[:: max(1, T // 40)], axis=0)
    rain = np.clip(lum - bg[None], 0, 1)
    for i in (10, 11, 12, 60):
        cv2.imwrite(str(out / f"rain_layer_{i:03d}.png"), np.clip(rain[i] * 6 * 255, 0, 255).astype(np.uint8))

    S = np.concatenate([streaks(rain[i], 0.035) for i in range(5, T - 5, 15)])
    L, Wd = S[:, 0], S[:, 1]
    elong = S[L / np.maximum(Wd, 1e-3) > 3]
    stats = {
        "frames": int(T), "size": [W, H],
        "streaks_per_frame": float(len(S) / len(range(5, T - 5, 15))),
        "length_px_pct": {p: float(np.percentile(elong[:, 0], p)) for p in (10, 25, 50, 75, 90, 99)},
        "width_px_median": float(np.median(elong[:, 1])),
        "angle_deg_pct": {p: float(np.percentile(elong[:, 2], p)) for p in (10, 50, 90)},
        "peak_lum_pct": {p: float(np.percentile(elong[:, 3], p)) for p in (10, 50, 90, 99)},
    }

    # Fall speed: cross-correlation of consecutive high-passed rain frames (central window) over vertical
    # shifts dy and small horizontal shifts dx (slant). High-pass removes mist/glow drift that would
    # otherwise dominate. Reports the dominant shift and the distribution of per-streak best shifts.
    win = (slice(int(H * 0.05), int(H * 0.75)), slice(int(W * 0.18), int(W * 0.85)))
    hp = np.stack([np.clip(r - cv2.GaussianBlur(r, (0, 0), 2.5), 0, 1) for r in rain])
    shifts = []
    for i in range(5, T - 6):
        a, b = hp[i][win], hp[i + 1][win]
        h, w = a.shape
        shp = (h + 96, w + 16)  # zero padding > max shift: no wrap-around
        c = np.fft.irfft2(np.conj(np.fft.rfft2(a, shp)) * np.fft.rfft2(b, shp), shp)  # c[dy, dx] = sum a[p] b[p + d]
        sub = np.concatenate([c[:80, -6:], c[:80, :7]], 1)  # dx in -6..6
        shifts.append(sub.max(1))
    prof = np.mean(shifts, 0)
    prof = prof / prof.max()
    peaks = [int(i) for i in range(2, len(prof) - 1) if prof[i] > prof[i - 1] and prof[i] >= prof[i + 1] and prof[i] > 0.2]
    stats["fall_px_per_frame_peaks"] = peaks  # energy-weighted: bright runoff streams dominate it
    stats["xcorr_profile"] = [round(float(v), 3) for v in prof[:80]]


    trk = [track(*[streaks(rain[j], 0.035) for j in (i, i + 1, i + 2)]) for i in range(5, T - 7, 20)]
    trk = np.concatenate([t for t in trk if len(t)]) if any(len(t) for t in trk) else np.zeros((0, 3))
    if len(trk):
        stats["speed_px_per_frame_pct"] = {p: float(np.percentile(trk[:, 0], p)) for p in (10, 25, 50, 75, 90)}
        stats["speed_tracked"] = int(len(trk))

    # Time-averaged rain energy map (where rain is visible / where streams pour).
    energy = rain.mean(0)
    en8 = np.clip(energy / np.percentile(energy, 99.7) * 255, 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / "rain_energy.png"), en8)
    eb = cv2.GaussianBlur(en8.astype(np.float32), (0, 0), 6)
    stats["rain_area_fraction"] = float((eb > 0.15 * np.percentile(eb, 99)).mean())  # share of frame with visible rain
    # Column profile of energy in the top 40% (roof-runoff streams show as hot columns).
    colprof = energy[: int(H * 0.6)].mean(0)
    hot = np.argsort(colprof)[-12:]
    stats["hot_columns_x"] = sorted(int(x) for x in hot)
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items() if k != "xcorr_profile"}, indent=2))
    print("xcorr", stats["xcorr_profile"][:60])


if __name__ == "__main__":
    main()
