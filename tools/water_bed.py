"""Soft aquarium water (the aquarium; user 2026-10-22: soft running water, quieter than the rain in other videos;
2026-10-23, on the first version: the bubbles too loud and cartoony, no running water to be heard, and the music
louder than both; then, on version 3: still too loud and high pitched, so Minecraft's own water sound instead).

Two kinds: Minecraft's own flowing water (build_minecraft, cfg {"kind": "minecraft"}: what the aquarium uses since
2026-10-23), or version 3's running water made in code, described here:

Version 3 is built around running water:
  stream   the filter's return pouring into the tank: a dense cloud of small entrained bubbles (tools/audio.py bubble():
           van den Doel 2005, f0 = 3/r; r 0.5-4 mm with more small ones than big, ~1200 a second, the pitch barely
           rising), the splash of the pour (noise 600 Hz-9 kHz, 3 dB under the bubbles) and a trace of low body
           (100-500 Hz, 18 dB under), all following one babble: the flow's level wobbling a few times a second and
           swelling slowly. Dense enough that no single bubble
           stands out.
  bubbles  now and then one to three small air bubbles near the surface, soft and short; the loudest moments of the
           layer 8 dB under the stream
  room     a short room response (RT60 0.3 s), a low cut at 100 Hz and a gentle low-pass at 7 kHz
What version 2 got wrong (measured 2026-10-23): every layer was pitched bubble pings with a rising pitch (the cartoon
"bloop"), the continuous water sat 13 dB under them, and a 5.2 kHz low-pass took out the splash: its energy above 6 kHz
was 41 dB down, and its level jumped 15 dB between quiet and loud 10 ms moments (single plinks).

Seeded and periodic: the bed for [0, P) is built on a circle (grains wrap around, every filter and the room are
circular convolutions over the whole period, every slow drift has a whole number of cycles), so bed(P) = bed(0) and a
long video reads it modulo P without a seam.

  .venv\\Scripts\\python tools\\water_bed.py --seconds 60 --out out\\aquarium\\footage\\water_60s.wav [--lufs -23] [--seed 1022]
"""
import argparse
import pathlib
import sys

import numpy as np

from cozy.audio.ambience import merge  # noqa: E402
from cozy.audio.dsp import pan_gains  # noqa: E402
from audio_analyze import integrated_lufs, k_weight  # noqa: E402

SR = 48000
TAU = 2 * np.pi
VERSION = 3                   # 3: running water (a dense bubble cloud, the pour's splash) with sparse soft bubbles on top
DEFAULTS = {
    "stream": {"rate": 1200.0, "r_mm": [0.5, 4.0], "gamma": 1.6, "alpha": 1.0, "xi": [0.0, 0.1], "amp_sigma": 0.35,
               "pan": -0.1, "pan_sd": 0.15, "babble": 0.3},
    "bubbles": {"rate": 2.0, "r_mm": [1.2, 3.0], "xi": [0.02, 0.12], "amp_sigma": 0.3, "pan": 0.05, "pan_sd": 0.3},
    "levels_db": {"splash": -3.0, "body": -18.0, "bubbles": -8.0},
    "room_mix": 0.18, "rt60": 0.3, "lowpass_hz": 7000.0, "highpass_hz": 100.0,
}
# Picked 2026-10-23 from six variants the audio model heard blind (tools/listen.py): a stronger wobble (0.45) or more
# low body (-12 dB) read as "an engine running"; these read as "flowing water or stream" (match 8, natural 9, calm 9).


def periodic_drift(r, n, cycles, depth):
    """A smooth random curve over the circle of n samples (sum of sines with whole cycles), mean 0, about +-depth."""
    t = np.arange(n) / n
    x = np.zeros(n)
    for c in cycles:
        x += r.uniform(0.5, 1.0) * np.sin(TAU * (c * t + r.uniform()))
    return depth * x / (np.abs(x).max() + 1e-12)


def shaped_noise(r, n, shape):
    """Periodic noise (circular FFT filter) with the magnitude response shape(f), unit RMS."""
    X = np.fft.rfft(r.standard_normal(n))
    X *= shape(np.fft.rfftfreq(n, 1 / SR))
    y = np.fft.irfft(X, n)
    return y / (y.std() + 1e-12)


def band(lo, hi, order=2):
    return lambda f: 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * order)) / np.sqrt(1 + (f / hi) ** (2 * order))


def events(r, n, rate_nom, rate_curve):
    """Event times (samples on the circle) of a Poisson process with rate rate_nom * rate_curve(t), by thinning."""
    top = rate_nom * float(rate_curve.max())
    cnt = r.poisson(top * n / SR)
    cand = np.sort(r.integers(0, n, cnt))
    keep = r.random(cnt) < rate_nom * rate_curve[cand] / top
    return cand[keep]


def radii(r, k, lo_mm, hi_mm, gamma):
    """k bubble radii (m) from a power law p(r) ~ r^-gamma on [lo, hi] mm: more small bubbles than big ones."""
    a, b = lo_mm * 1e-3, hi_mm * 1e-3
    u = r.random(k)
    if abs(gamma - 1) < 1e-9:
        return a * (b / a) ** u
    e = 1 - gamma
    return (a ** e + u * (b ** e - a ** e)) ** (1 / e)


def damping(f0):
    """van den Doel (2005): d = 0.043 f0 + 0.0014 f0^1.5 (1/s), as tools/audio.py bubble()."""
    return 0.043 * f0 + 0.0014 * f0 ** 1.5


def grains(n, times, f0, xi, amp, pan, max_s=0.12, block=6_000_000):
    """Bubbles (sin(2 pi f0 (t + xi d t^2 / 2)) e^-dt, a 0.2 ms onset) at sample times on a circle of n samples, stereo
    float32. Vectorized: grains are grouped by pitch so a group has one length (down to -60 dB at its lowest pitch,
    at most max_s) and are summed per batch with bincount."""
    out = np.zeros((n, 2), np.float32)
    if not len(times):
        return out
    d = damping(f0)
    gl, gr = pan_gains(pan)
    edges = np.geomspace(f0.min(), f0.max() * 1.0001, 7)
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = np.where((f0 >= lo) & (f0 < hi))[0]
        if not len(sel):
            continue
        m = int(min(max_s, 6.9 / damping(lo)) * SR) + 1
        t = (np.arange(m) / SR).astype(np.float32)
        onset = (1 - np.exp(-t / 2e-4)).astype(np.float32)
        sel = sel[np.argsort(times[sel], kind="stable")]
        B = max(1, block // m)
        for i in range(0, len(sel), B):
            j = sel[i:i + B]
            ff = f0[j, None].astype(np.float32)
            dd = d[j, None].astype(np.float32)
            xx = xi[j, None].astype(np.float32)
            w = np.sin(np.float32(TAU) * ff * (t + np.float32(0.5) * xx * dd * t * t)) * np.exp(-dd * t) * onset
            t0 = times[j].astype(np.int64)
            base = int(t0[0])
            span = int(t0[-1]) - base + m
            idx = ((t0 - base)[:, None] + np.arange(m)[None, :]).ravel()
            for ch, g in ((0, gl), (1, gr)):
                acc = np.bincount(idx, weights=(w * (amp[j] * g[j]).astype(np.float32)[:, None]).ravel(),
                                  minlength=span).astype(np.float32)
                if span > n:                        # a sparse batch longer than the circle: fold it onto itself
                    head = acc[:n].copy()
                    head[: span - n] += acc[n:]
                    acc = head
                out[(base + np.arange(len(acc))) % n, ch] += acc
    return out


def cloud(r, n, rate_nom, rate_curve, c, level_curve=None):
    """A bubble layer: Poisson times (rate_nom * rate_curve), power-law radii, amplitudes ~ r^alpha with a capped
    log-normal spread (times level_curve at each bubble), pans around c['pan']."""
    times = events(r, n, rate_nom, rate_curve)
    k = len(times)
    rad = radii(r, k, *c["r_mm"], c.get("gamma", 1.0))
    f0 = 3.0 / rad
    xi = r.uniform(*c["xi"], k)
    s = c["amp_sigma"]
    amp = (rad / np.median(rad)) ** c.get("alpha", 1.0) * np.exp(np.clip(r.normal(0, s, k), -2 * s, 2 * s))
    if level_curve is not None:
        amp *= level_curve[times]
    pan = np.clip(r.normal(c["pan"], c["pan_sd"], k), -1, 1)
    return grains(n, times, f0, xi, amp, pan), k


def room_and_tone(x, r, rt60, mix, lowpass_hz, highpass_hz):
    """Circular convolution over the whole period with a small room (exponentially decaying noise) mixed under the dry
    sound, a gentle low-pass and a low cut."""
    n = len(x)
    m = int(rt60 * 1.6 * SR)
    t = np.arange(m) / SR
    decay = np.exp(-6.91 * t / rt60)
    f = np.fft.rfftfreq(n, 1 / SR)
    tone = 1 / np.sqrt(1 + (f / lowpass_hz) ** 4) / np.sqrt(1 + (highpass_hz / np.maximum(f, 1e-3)) ** 4)
    out = np.empty(x.shape, np.float32)
    for ch in range(2):
        ir = r.standard_normal(m) * decay
        ramp = int(0.004 * SR)
        ir[:ramp] *= np.linspace(0, 1, ramp)
        ir /= np.sqrt((ir ** 2).sum())
        X = np.fft.rfft(x[:, ch].astype(np.float64)) * tone
        dry = np.fft.irfft(X, n)
        wet = np.fft.irfft(X * np.fft.rfft(ir, n), n)
        out[:, ch] = dry * (1 - mix) + wet * mix * (np.std(dry) / (np.std(wet) + 1e-12))
    return out


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def build(seconds, seed=1022, cfg=None):
    """The bed for [0, seconds) on the circle, stereo float32, before loudness normalization. cfg {"kind": "minecraft",
    "minecraft": {...}} uses the game's own water (build_minecraft); otherwise version 3's running water."""
    if (cfg or {}).get("kind") == "minecraft":
        return build_minecraft(seconds, seed, merge(MC_DEFAULTS, (cfg or {}).get("minecraft")))
    c = merge(DEFAULTS, {k: v for k, v in (cfg or {}).items() if k not in ("kind", "minecraft")})
    n = int(round(seconds * SR))
    r = np.random.default_rng([seed, 0x57A7E5, VERSION])
    S, Bc, lv = c["stream"], c["bubbles"], c["levels_db"]
    # the babble: the flow's level wobbling 3-20 times a second, and slow swells (whole cycles over the period)
    slow = np.exp(periodic_drift(r, n, [max(1, round(seconds / s)) for s in (90, 53, 31, 20)], 0.18))
    wob = np.exp(S["babble"] * shaped_noise(r, n, band(3.0, 20.0)))
    flow = (slow * wob).astype(np.float32)
    flow /= flow.mean()
    stream, k_stream = cloud(r, n, S["rate"], flow, S, level_curve=np.sqrt(flow))
    ref = rms(stream)
    # the pour's splash and a little low body, following the same flow
    for name, shape, follow in (("splash", band(600.0, 9000.0), np.sqrt(flow)), ("body", band(100.0, 500.0), np.sqrt(slow))):
        common = shaped_noise(r, n, shape)
        layer = np.stack([0.8 * common + 0.6 * shaped_noise(r, n, shape) for _ in range(2)], 1) * follow[:, None]
        stream += (layer * (ref * 10 ** (lv[name] / 20) / rms(layer))).astype(np.float32)
        del common, layer
    # sparse soft bubbles: 1-3 at a time
    starts = events(r, n, Bc["rate"] / 2.0, np.ones(n, np.float32))
    times = np.sort(np.concatenate([(s0 + (r.uniform(0, 0.25, int(r.integers(1, 4))) * SR).astype(np.int64)) % n
                                    for s0 in starts])) if len(starts) else np.zeros(0, np.int64)
    k = len(times)
    rad = radii(r, k, *Bc["r_mm"], 1.0)
    s = Bc["amp_sigma"]
    bub = grains(n, times, 3.0 / rad, r.uniform(*Bc["xi"], k), np.exp(np.clip(r.normal(0, s, k), -2 * s, 2 * s)),
                 np.clip(r.normal(Bc["pan"], Bc["pan_sd"], k), -1, 1))
    if k:
        w = SR // 20
        e = np.sqrt(np.convolve(np.square(bub.mean(1), dtype=np.float64), np.ones(w) / w, "same"))
        loud = float(np.percentile(e[e > 0], 99.5))
        stream += bub * np.float32(rms(stream) * 10 ** (lv["bubbles"] / 20) / loud)
    del bub
    return room_and_tone(stream, r, c["rt60"], c["room_mix"], c["lowpass_hz"], c["highpass_hz"])


# Minecraft's own flowing water (user 2026-10-23, on version 3: still too loud and high pitched, the bubbles giving it an
# odd sound, so Minecraft's water sound instead, with a video of Minecraft water ambience as the reference).
# block.water.ambient plays liquid/water.ogg (2.6 s, mono); a flowing water block
# plays it now and then at volume 0.75-1.0 and pitch 0.5-1.5 (WaterFluid.animateTick), and a few blocks in earshot make
# the stream. Read from the user's own Java Edition install, pinned by its sha1.
MC_WATER = {"asset": "minecraft/sounds/liquid/water.ogg", "sha1": "e75c6077b1bfa4a791d62d9951d6e8891757ad1c"}
# The aquarium's pick (2026-10-23, of four the audio model heard blind, all "flowing water or a stream"): denser and farther
# than one block (rate 4 a second, gain 0.15-0.6: smoother, the 10 ms level range 8.7 dB instead of 17) and the pitch
# capped at 1.1 instead of the game's 1.5 (he found the water too high pitched): the spectral centroid 1.46 kHz instead of
# 1.85 (match 8, natural 9, calm 8).
MC_DEFAULTS = {"rate": 4.0, "pitch": [0.5, 1.1], "gain": [0.15, 0.6], "pan": 0.6, "variants": 48}


def minecraft_sample(asset=MC_WATER["asset"], sha1=MC_WATER["sha1"]):
    """A game sound from the newest asset index of the user's Minecraft install, mono float64 at SR; stops if the game's
    file is no longer the pinned one."""
    import json
    from cozy.media import run_ffmpeg
    from mc_music import minecraft_dir
    mc = minecraft_dir(None)
    idx = max((mc / "assets" / "indexes").glob("*.json"), key=lambda p: p.stat().st_mtime)
    h = json.loads(idx.read_text())["objects"][asset]["hash"]
    if h != sha1:
        sys.exit(f"water_bed: {asset} in the game ({idx.name}) is {h[:12]}, not the pinned {sha1[:12]}: listen to it, then re-pin")
    raw = run_ffmpeg(["-v", "error", "-i", str(mc / "assets" / "objects" / h[:2] / h), "-ac", "1", "-ar", str(SR),
                      "-f", "f32le", "-"]).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def repitch(x, p):
    """x played p times as fast, as the game's pitch does (p < 1: lower and longer), band-limited (FFT resampling)."""
    n = len(x)
    pad = np.concatenate([x, np.zeros(n // 4)])
    N = len(pad)
    M = int(round(N / p))
    X = np.fft.rfft(pad)
    Y = np.zeros(M // 2 + 1, complex)
    k = min(len(Y), len(X))
    Y[:k] = X[:k]
    return np.fft.irfft(Y, M)[: int(round(n / p))] * (M / N)


def build_minecraft(seconds, seed, c):
    """Minecraft's water on a circle of `seconds`: the sample at Poisson times (c['rate'] a second), each at a pitch from
    c['pitch'] (one of c['variants'] evenly spaced, as the game picks a random float), a gain from c['gain'] (the game's
    0.75-1.0 times the fall-off of a block a few metres away) and a pan within +-c['pan']. Dry, as in the game."""
    n = int(round(seconds * SR))
    r = np.random.default_rng([seed, 0x4D43, 1])
    x = minecraft_sample()
    pitches = np.linspace(*c["pitch"], int(c["variants"]))
    bank = [repitch(x, p) for p in pitches]
    k = r.poisson(c["rate"] * seconds)
    times = np.sort(r.integers(0, n, k))
    out = np.zeros((n, 2), np.float32)
    for t0 in times:
        y = bank[int(r.integers(len(bank)))] * r.uniform(*c["gain"])
        gl, gr = pan_gains(r.uniform(-c["pan"], c["pan"]))
        idx = (t0 + np.arange(len(y))) % n
        out[idx, 0] += (y * gl).astype(np.float32)
        out[idx, 1] += (y * gr).astype(np.float32)
    if c.get("lowpass_hz"):                       # a gentle low-pass on the circle (2nd order), for a softer top
        f = np.fft.rfftfreq(n, 1 / SR)
        h = 1 / np.sqrt(1 + (f / float(c["lowpass_hz"])) ** 4)
        for ch in range(2):
            out[:, ch] = np.fft.irfft(np.fft.rfft(out[:, ch].astype(np.float64)) * h, n).astype(np.float32)
    return out


def tame(x, over_rms_db=19.0):
    """A look-ahead peak limiter on the circle, its ceiling over_rms_db above the bed's RMS: it only touches rare
    stacks of grains (version 2's first 20 minute bed had one at -0.3 dBFS, 27 dB over its RMS)."""
    from music import limit
    m = SR // 4
    rms_db = 20 * np.log10(rms(x))
    ext = np.concatenate([x[-m:], x, x[:m]]).astype(np.float64)
    return limit(ext, 0, thr_db=rms_db + over_rms_db)[m: m + len(x)]


def normalize(x, lufs):
    x = np.asarray(x, np.float64)
    x = x * 10 ** ((lufs - integrated_lufs(k_weight(x))) / 20)
    x = tame(x)
    return x * 10 ** ((lufs - integrated_lufs(k_weight(x))) / 20)


def write_wav(path, x):
    import wave
    y = np.clip(x, -1, 1)
    pcm = (y * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=1022)
    ap.add_argument("--lufs", type=float, default=-23.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minecraft", action="store_true", help="Minecraft's own flowing water (the game's sound, from the install)")
    a = ap.parse_args()
    x = normalize(build(a.seconds, a.seed, {"kind": "minecraft"} if a.minecraft else None), a.lufs)
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    write_wav(a.out, x)
    peak = 20 * np.log10(np.abs(x).max() + 1e-12)
    print(f"water bed v{VERSION}: {a.seconds:g} s, {integrated_lufs(k_weight(x)):.1f} LUFS, sample peak {peak:.1f} dBFS, "
          f"join step {np.abs(x[0] - x[-1]).max():.4f} -> {a.out}")


if __name__ == "__main__":
    main()
