"""Ambience layers played from a recording, not synthesized (2026-11-12). The hot spring's spout is a CC0 recording of
water pouring into a pool: water made from noise alone read to the audio model as rain, waves, fireworks or footsteps,
and synthesized bubbles read as cartoony to Truman (lessons L130, L132, L212), so the pour that carries the scene is
real water. Each recording is cut into seamless loops once, and a block reads them at its absolute samples by modulo:
a 15 s block stays a pure function of its time, the same rendered alone or in any order.

  RECORDINGS                 layer -> its recording (assets/audio/, with a sidecar and a ledger row) and how it plays
  decoded(path, sha1)        48 kHz stereo samples of a recording (ffmpeg), checked against its pinned sha1
  seamless_loop(x, lo, hi)   the stretch of x whose end best matches the audio just before its start, crossfaded into it
  Recorded(layer, r, pan)    the layer's loops, placed in the stereo field; read(n) at absolute samples n
"""
import functools
import hashlib

import numpy as np

from cozy.audio.dsp import SR, design_fir, fft_filter, pan_gains, peak_limit
from cozy.paths import ROOT

LOOP_V = 1        # bump when the loops are cut or placed differently (keys the loudness calibration of beds that play them)
# path: the recording (its sidecar is <path>.json, its row in docs/asset-ledger.csv); sha1: its bytes (another file is
# refused, never played); clean: the stretch used (s); loops: the length ranges of the two loops cut from its two halves
# (s), unequal so their sum never repeats; xf: each loop's crossfade (s); eq: [(Hz, dB), ...]; peak_db: peaks limited to
# this far over its RMS; pan: where it sits (-1..1; scene audio "<layer>_pan" moves it); width: how far apart the two
# channels (a mono recording: the two loops) sit around the pan.
RECORDINGS = {
    # a small swale trickling into a stream (Wikimedia Commons, CC0): a thin stream falling into water, steady within
    # 1.5 dB; its wind rumble (40-125 Hz) cut, its top softened a little, as heard from across the pool in the snow
    "spout": {"path": "assets/audio/ambience/swale.ogg", "sha1": "4f97748c715d90fda6357073f14a12e68f294d73",
              "clean": [0.5, 30.5], "loops": [[11.5, 12.9], [10.0, 11.4]], "xf": 2.0,
              "eq": [[20, -50], [60, -30], [110, -14], [160, -5], [220, 0], [500, 4], [900, 3], [1600, 0], [3000, -2], [6000, -5],
                     [10000, -8], [22000, -12]],
              "peak_db": 15.0, "pan": 0.45, "width": 0.15},
}


@functools.lru_cache(maxsize=4)
def decoded(path, sha1):
    """(n, 2) float64 at 48 kHz. The file must be the one logged: its sha1 pinned in RECORDINGS."""
    from audio_analyze import load
    p = ROOT / path
    got = hashlib.sha1(p.read_bytes()).hexdigest()
    if sha1 and got != sha1:
        raise RuntimeError(f"{path}: sha1 {got} isn't the logged recording's {sha1}")
    x = load(p)
    x.setflags(write=False)
    return x


def band_frames(x, frame_s=0.1, smooth_s=0.5):
    """Log energy in 16 bands (100 Hz to 16 kHz) per frame of the mono mix, smoothed over smooth_s: the sound's
    level and color over time, to match the two sides of a splice. Returns (frames, samples per frame)."""
    m = x.mean(1) if x.ndim == 2 else x
    n = int(round(frame_s * SR))
    k = len(m) // n
    F = np.abs(np.fft.rfft(m[: k * n].reshape(k, n) * np.hanning(n), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    edges = np.geomspace(100, 16000, 17)
    B = 10 * np.log10(np.stack([F[:, (f >= a) & (f < b)].sum(1) for a, b in zip(edges[:-1], edges[1:])], 1) + 1e-12)
    w = max(1, int(round(smooth_s / frame_s)))
    P = np.pad(B, ((w // 2, w - 1 - w // 2), (0, 0)), mode="edge")
    c = np.cumsum(np.vstack([np.zeros((1, B.shape[1])), P]), 0)
    return (c[w:] - c[:-w]) / w, n


def seamless_loop(x, lo_s, hi_s, xf_s=2.0):
    """A loop of lo_s..hi_s seconds from x that joins without a seam: the start a and length L whose last xf_s seconds
    sound most like the xf_s seconds before a (same level and color, band by band), then those last seconds crossfaded
    (equal power: the two sides are unrelated water) into the ones before a, so the loop's end runs into its start as
    the recording did. Returns (loop, a, L) in samples."""
    F, fn = band_frames(x)
    X = int(round(xf_s * SR / fn))
    best = (np.inf, 0, 0)
    for Lf in range(int(round(lo_s * SR / fn)), int(round(hi_s * SR / fn)) + 1):
        if Lf + X > len(F):
            break
        d = ((F[:-Lf] - F[Lf:]) ** 2).mean(1)               # frame i against frame i + L
        c = np.concatenate([[0.0], np.cumsum(d)])
        s = (c[X:] - c[:-X]) / X                             # the crossfade's frames, from j = a - X
        j = int(np.argmin(s))
        if s[j] < best[0]:
            best = (float(s[j]), j + X, Lf)
    if not np.isfinite(best[0]):
        raise ValueError(f"no loop of {lo_s}-{hi_s} s with a {xf_s} s crossfade fits in {len(x) / SR:.1f} s")
    a, L, n = best[1] * fn, best[2] * fn, int(round(xf_s * SR))
    loop = np.array(x[a: a + L], np.float64)
    u = (np.arange(n) + 0.5) / n
    loop[L - n:] = loop[L - n:] * np.cos(0.5 * np.pi * u)[:, None] + x[a - n: a] * np.sin(0.5 * np.pi * u)[:, None]
    return loop, a, L


class Recorded:
    """A recorded layer: two loops cut from the two halves of the recording's clean stretch, filtered (eq), placed around
    the layer's pan, at unit RMS over both channels (the bed's levels set it like a noise layer), their peaks limited.
    read(n) gives both at absolute samples n, each from its own offset (drawn from r, the scene's seeded generator); the
    bed blends them. cuts: where each loop starts in the recording and how long it is (samples)."""

    def __init__(self, layer, r, pan=None):
        spec = RECORDINGS[layer]
        x = decoded(spec["path"], spec["sha1"])
        s0, s1 = (int(round(v * SR)) for v in spec["clean"])
        x = x[s0: s1]
        eq = design_fir([tuple(q) for q in spec["eq"]])
        x = np.stack([fft_filter(x[:, c], eq) for c in range(2)], 1)
        self.mono = bool(np.array_equal(x[:, 0], x[:, 1]))
        half = len(x) // 2
        p = float(spec["pan"] if pan is None else pan)
        w = float(spec["width"])
        gl, gr = pan_gains(np.array([p - w, p + w]))
        self.loops, self.cuts = [], []
        for i, (part, (lo, hi)) in enumerate(zip((x[:half], x[half:]), spec["loops"])):
            loop, a, L = seamless_loop(part, lo, hi, spec["xf"])
            if self.mono:      # one point each side of the pan: the two loops are unrelated, so the blend has width
                st = loop[:, :1] * np.array([gl[i], gr[i]])
            else:              # each channel one side of the pan
                st = loop[:, :1] * np.array([gl[0], gr[0]]) + loop[:, 1:] * np.array([gl[1], gr[1]])
            st = st / np.sqrt((st ** 2).mean())
            self.loops.append(loop_limit(st, spec["peak_db"]))
            self.cuts.append((s0 + i * half + a, L))
        self.offsets = [int(r.integers(len(lp))) for lp in self.loops]
        self.key = [layer, LOOP_V, spec, round(p, 4)]

    def read(self, n):
        """The loops at absolute samples n (int64): [(len(n), 2), (len(n), 2)]."""
        return [lp[(n + o) % len(lp)] for lp, o in zip(self.loops, self.offsets)]


def loop_limit(x, peak_db, pad_s=0.25):
    """Peaks over peak_db (dB over x's RMS of 1) limited quickly (20 ms release, so the trickle around a loud drop isn't
    ducked), around the loop's join too: limited with its end before its start and its start after its end."""
    p = int(pad_s * SR)
    y = peak_limit(np.concatenate([x[-p:], x, x[:p]]), peak_db, release=0.02)
    return y[p: p + len(x)]
