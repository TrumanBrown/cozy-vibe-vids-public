"""Analyze the audio of a clip (reference footage or our own mixes): spectrum, loudness, dynamics,
impulsiveness and stereo image, so procedural ambience can be calibrated against footage by numbers.

Usage (repo root):
  .venv/Scripts/python tools/audio_analyze.py <audio/video file> [--out stats.json] [--start s --duration s]

Reports (and writes as JSON):
  third_octave_db   band levels (dB re full scale, 25 Hz .. 20 kHz) of the average power spectrum
  tilt_db_per_oct   least-squares spectral slope over 250 Hz .. 8 kHz
  centroid_hz       spectral centroid
  lufs_integrated   ITU-R BS.1770-4 integrated loudness (K-weighting, 400 ms blocks, gated)
  short_term_lufs   min / p10 / p50 / p90 / max of 3 s short-term loudness (1 s hop); max_rise_db_per_s
  true_peak_dbtp    4x oversampled peak
  crest_db          peak / RMS (per channel, mean)
  kurtosis_hf       kurtosis of the 2-8 kHz band (impulsive patter >> 3, smooth noise ~3)
  stereo_corr       L/R correlation overall and in low/mid/high bands (1 = mono, 0 = fully wide)
  tonal_peaks       strongest narrow spectral peaks above the local median (music / hum detection)
"""
import argparse
import json
import pathlib
import sys

import numpy as np

from cozy.media import run_ffmpeg

SR = 48000


def load(path, start=None, dur=None):
    cmd = ["-hide_banner", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", str(path), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    raw = run_ffmpeg(cmd).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def lfilter(b, a, x):
    """2nd-order IIR filter along axis 0, applied as an FFT convolution with its impulse response
    (truncated once it decays below 1e-14; exact enough for metering, no scipy needed)."""
    b = np.asarray(b, np.float64) / a[0]
    a = np.asarray(a, np.float64) / a[0]
    hh = np.zeros(1 << 16)
    hh[0] = 1.0
    for i in range(1, len(hh)):
        hh[i] = -a[1] * hh[i - 1] - (a[2] * hh[i - 2] if i >= 2 else 0.0)
        if i > 64 and abs(hh[i]) < 1e-14 and abs(hh[i - 1]) < 1e-14:
            hh = hh[: i + 1]
            break
    fir = np.convolve(b, hh)
    L = x.shape[0] + len(fir) - 1
    N = 1 << int(np.ceil(np.log2(L)))
    F = np.fft.rfft(fir, N)
    return np.fft.irfft(np.fft.rfft(x, N, axis=0) * F[:, None], N, axis=0)[: x.shape[0]]


def k_weight(x):
    """ITU-R BS.1770 K-weighting at 48 kHz (pre-filter shelf + RLB high-pass)."""
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x))


def loudness_blocks(xk, win, hop):
    n = 1 + max(0, (len(xk) - win) // hop)
    p = np.array([(xk[i * hop: i * hop + win] ** 2).mean(0).sum() for i in range(n)])
    return -0.691 + 10 * np.log10(np.maximum(p, 1e-20)), p


def integrated_lufs(xk):
    l, p = loudness_blocks(xk, int(0.4 * SR), int(0.1 * SR))
    g = p[l > -70]
    if not len(g):
        return -np.inf
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    g2 = p[(l > -70) & (l > rel)]
    return float(-0.691 + 10 * np.log10(g2.mean()))


def true_peak(x):
    N = len(x)
    X = np.fft.rfft(x, axis=0)
    Y = np.zeros((4 * N // 2 + 1, x.shape[1]), complex)
    Y[: X.shape[0]] = X
    up = np.fft.irfft(Y, 4 * N, axis=0) * 4
    return float(20 * np.log10(max(np.abs(up).max(), 1e-12)))


def band(x, lo, hi):
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x), axis=0)


def analyze(x):
    st = {}
    # Average power spectrum (Welch, 8192-point Hann, 50 % overlap), summed over channels.
    w = np.hanning(8192)
    segs = [x[i:i + 8192] for i in range(0, len(x) - 8192, 4096)]
    P = np.mean([np.abs(np.fft.rfft(s * w[:, None], axis=0)) ** 2 for s in segs], 0).sum(1) / (w ** 2).sum()
    f = np.fft.rfftfreq(8192, 1 / SR)
    centers = 1000 * 2.0 ** (np.arange(-16, 14) / 3)
    centers = centers[(centers >= 25) & (centers <= 20000)]
    tob = {}
    for c in centers:
        m = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        tob[f"{c:.0f}"] = float(10 * np.log10(max(P[m].sum(), 1e-20)))
    st["third_octave_db"] = tob
    cs = np.array([float(k) for k in tob])
    lv = np.array(list(tob.values()))
    sel = (cs >= 250) & (cs <= 8000)
    st["tilt_db_per_oct"] = float(np.polyfit(np.log2(cs[sel]), lv[sel], 1)[0])
    st["centroid_hz"] = float((f * P).sum() / P.sum())
    # Tonal peaks: bins far above the local median (music, hum).
    med = np.array([np.median(P[max(0, i - 40): i + 40]) for i in range(len(P))])
    ratio = 10 * np.log10(np.maximum(P, 1e-30) / np.maximum(med, 1e-30))
    idx = np.argsort(ratio)[::-1]
    peaks = []
    for i in idx:
        if f[i] < 40 or any(abs(f[i] - p[0]) < 30 for p in peaks):
            continue
        peaks.append((float(f[i]), float(ratio[i])))
        if len(peaks) == 8:
            break
    st["tonal_peaks"] = peaks
    xk = k_weight(x)
    st["lufs_integrated"] = integrated_lufs(xk)
    ls, _ = loudness_blocks(xk, 3 * SR, SR)
    st["short_term_lufs"] = {k: float(v) for k, v in zip(["min", "p10", "p50", "p90", "max"], np.percentile(ls, [0, 10, 50, 90, 100]))}
    st["short_term_max_rise_db_per_s"] = float(np.max(np.diff(ls))) if len(ls) > 1 else 0.0
    st["true_peak_dbtp"] = true_peak(x)
    rms = np.sqrt((x ** 2).mean(0))
    st["crest_db"] = float(np.mean(20 * np.log10(np.abs(x).max(0) / np.maximum(rms, 1e-12))))
    hf = band(x, 2000, 8000)
    st["kurtosis_hf"] = float(np.mean(((hf - hf.mean(0)) ** 4).mean(0) / np.maximum(hf.var(0) ** 2, 1e-30)))

    def corr(a):
        return float((a[:, 0] * a[:, 1]).sum() / np.sqrt((a[:, 0] ** 2).sum() * (a[:, 1] ** 2).sum() + 1e-30))
    st["stereo_corr"] = {"all": corr(x), "low_<250": corr(band(x, 20, 250)), "mid_250-2k": corr(band(x, 250, 2000)), "high_>2k": corr(band(x, 2000, 20000))}
    st["duration_s"] = len(x) / SR
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--out")
    ap.add_argument("--start", type=float)
    ap.add_argument("--duration", type=float)
    a = ap.parse_args()
    x = load(a.file, a.start, a.duration)
    st = analyze(x)
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(json.dumps(st, indent=1))
    print(json.dumps({k: v for k, v in st.items() if k != "third_octave_db"}, indent=1))
    print("third-octave (dB):", " ".join(f"{k}:{v:.1f}" for k, v in st["third_octave_db"].items()))


if __name__ == "__main__":
    sys.exit(main())
