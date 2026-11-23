"""Signal helpers for the ambience (TASKS.md T17), moved verbatim from tools/audio.py.

  SR, TAU                   the sample rate (48 kHz) and 2 pi
  unit, fade_tail           scale to unit energy; a cosine-squared fade over the tail
  design_fir                a linear-phase FIR with unit energy from [(Hz, dB), ...]
  fft_filter, _conv_causal  FFT convolution: aligned for a linear-phase filter; causal
  bandpass_noise, onepole   noise band-passed around fc; a causal one-pole low-pass
  bubble                    a bubble's ring (van den Doel 2005: f0 = 3/r, the pitch rising)
  pan_gains                 equal-power pan gains
  peak_limit                a look-ahead peak limiter
  write_wav                 24-bit WAV with TPDF dither seeded by its length
"""
import wave

import numpy as np

SR = 48000
TAU = 2 * np.pi


def unit(x):
    return x / np.sqrt((x ** 2).sum() + 1e-20)


def fade_tail(x, frac=0.15):
    m = max(int(len(x) * frac), 8)
    x = x.copy()
    x[-m:] *= np.cos(np.linspace(0, np.pi / 2, m)) ** 2
    return x


def design_fir(points, n=4097):
    """Linear-phase FIR with unit energy (white noise in -> unit RMS out) from [(Hz, dB), ...] (log-f interp)."""
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    f = np.fft.rfftfreq(nfft, 1 / SR)
    fp = np.log10([p[0] for p in points])
    gp = np.array([p[1] for p in points], float)
    H = 10 ** (np.interp(np.log10(np.maximum(f, 1.0)), fp, gp) / 20)
    h = np.roll(np.fft.irfft(H, nfft), n // 2)[:n] * np.hanning(n)
    return unit(h)


def fft_filter(x, h):
    """Linear convolution (same length, causal alignment shifted by len(h)//2) via FFT."""
    n = len(x) + len(h) - 1
    N = 1 << int(np.ceil(np.log2(n)))
    y = np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)
    o = len(h) // 2
    return y[o: o + len(x)]


def bandpass_noise(r, n, fc, oct_bw):
    X = np.fft.rfft(r.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.exp(-0.5 * (np.log2(np.maximum(f, 1.0) / fc) / (oct_bw / 2.355)) ** 2)
    return np.fft.irfft(X * g, n)


def onepole(x, fc):
    """Causal one-pole low-pass (impulse response convolution; short kernels only)."""
    a = np.exp(-TAU * fc / SR)
    m = min(len(x), int(np.ceil(np.log(1e-6) / np.log(a))) + 1)
    h = (1 - a) * a ** np.arange(m)
    return np.convolve(x, h)[: len(x)]


def bubble(radius_m, xi, t):
    """van den Doel (2005) bubble: f0 = 3/r Hz, damping d = 0.043 f0 + 0.0014 f0^1.5, pitch rising by xi*d."""
    f0 = 3.0 / radius_m
    d = 0.043 * f0 + 0.0014 * f0 ** 1.5
    ph = TAU * f0 * (t + 0.5 * xi * d * t * t)
    return np.sin(ph) * np.exp(-d * t), d


def pan_gains(p):
    th = (np.clip(p, -1, 1) + 1) * np.pi / 4
    return np.cos(th), np.sin(th)


def _conv_causal(x, h):
    n = len(x) + len(h) - 1
    N = 1 << int(np.ceil(np.log2(n)))
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[: len(x)]


def peak_limit(x, thr_db, look=0.005, release=0.15):
    """Look-ahead peak limiter for a self-contained signal (1 ms frames, smooth gain, no overshoot)."""
    thr = 10 ** (thr_db / 20)
    fr = SR // 1000
    n = int(np.ceil(len(x) / fr))
    pad = np.zeros((n * fr, x.shape[1]))
    pad[: len(x)] = np.abs(x)
    e = pad.reshape(n, fr, -1).max(axis=(1, 2))
    need = np.minimum(1.0, thr / np.maximum(e, 1e-12))
    la = int(look * 1000)
    need = np.array([need[max(0, i - 1): i + la + 1].min() for i in range(n)])   # look ahead/behind a frame
    g = np.empty(n)
    cur, rel = 1.0, np.exp(-1.0 / (release * 1000))
    for i in range(n):
        cur = need[i] if need[i] < cur else need[i] - (need[i] - cur) * rel
        g[i] = cur
    gs = np.interp(np.arange(len(x)) / fr, np.arange(n) + 0.5, g)
    return x * gs[:, None]


def write_wav(path, x):
    """24-bit PCM WAV with TPDF dither (deterministic: fixed seed per file length)."""
    d = np.random.default_rng(len(x)).random(x.shape) - np.random.default_rng(len(x) + 1).random(x.shape)
    q = np.clip(np.round(x * 8388607 + d), -8388608, 8388607).astype("<i4")
    b = q.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b)
