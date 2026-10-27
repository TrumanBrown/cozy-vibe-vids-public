"""The event sounds of the ambience (TASKS.md T17), moved verbatim from tools/audio.py: self-contained waves, each
drawn from the generator it is given. Ambience levels each against the bed and places it at its event's time; the
thunder is Ambience.thunder_wave.

  stereo                  mono to stereo with an equal-power pan
  boat_wash, wake_laps    a passing boat's hull wash; its wake slapping the shore (lap_slap: one slap)
  gutter                  a lantern or candle flame guttering at each light dip
  fish_plop               a fish rising or jumping
  creak                   a treehouse wood creak
  car_hiss, train_pass    a car on a wet road; a distant train
  log_settle, neon_buzz   a log settling in the fire; neon buzz while the sign flickers
"""
import numpy as np

from cozy.audio.dsp import SR, TAU, bandpass_noise, bubble, design_fir, fade_tail, fft_filter, onepole, pan_gains, unit
from cozy.audio.kernels import k_crackle, k_pop


def stereo(x, pan):
    """Mono -> stereo with an equal-power pan (scalar or per-sample)."""
    L, R = pan_gains(np.asarray(pan, float))
    return np.stack([x * L, x * R], 1)


def boat_wash(r, prof, dur):
    """Hull wash of a distant boat: band-passed water noise sloshing with the boat's bob, its level and
    brightness following the distance (1/r spreading; air absorption and rain masking dull it far away),
    louder with speed, panned along its screen position; 6 s fades at the event edges."""
    n = int((dur + 1.0) * SR)
    t = np.arange(n) / SR
    k = np.arange(len(prof["dist"])) * prof["dt"]
    dist = np.interp(t, k, prof["dist"])
    pan = np.interp(t, k, prof["pan"])
    speed = np.interp(t, k, prof["speed"])
    near = fft_filter(r.standard_normal(n), design_fir([(20, -40), (120, -12), (300, 0), (900, -2), (2500, -10), (6000, -24), (22000, -60)]))
    far = fft_filter(r.standard_normal(n), design_fir([(20, -40), (90, -10), (200, 0), (500, -4), (1000, -16), (3000, -40), (22000, -70)]))
    w = np.clip((dist - 90.0) / 150.0, 0, 1)
    x = near * (1 - w) + far * w
    ph = r.uniform(0, TAU)
    slosh = 0.45 + 0.55 * np.maximum(np.sin(TAU * 0.42 * t + ph), 0) ** 1.5 + 0.15 * np.sin(TAU * 1.13 * t + 2 * ph)
    env = (60.0 / dist) * (speed / 1.6) ** 1.5 * slosh
    edge = np.clip(t / 6.0, 0, 1) * np.clip((dur - t) / 6.0, 0, 1)
    return stereo(x * env * (0.5 - 0.5 * np.cos(np.pi * edge)), pan * 0.8)


def lap_slap(r, n):
    """One wake wave slapping the shore stones: a soft splosh (attack 25 ms, quick decay + water running
    back), a low thump and a few bubbles."""
    t = np.arange(n) / SR
    att = np.clip(t / 0.025, 0, 1)
    s = bandpass_noise(r, n, np.exp(r.uniform(np.log(260), np.log(520))), 2.2)
    x = unit(s * att * (np.exp(-t / r.uniform(0.12, 0.22)) + 0.3 * np.exp(-t / r.uniform(0.45, 0.8))))
    x = x + 0.35 * unit(np.sin(TAU * r.uniform(70, 110) * t) * np.exp(-t / 0.07) * att)
    for _ in range(r.integers(3, 8)):
        t0 = r.uniform(0.04, 0.5)
        b, _ = bubble(np.exp(r.uniform(np.log(2e-3), np.log(6e-3))), r.uniform(0.1, 0.4), np.maximum(t - t0, 0))
        x = x + r.uniform(0.03, 0.09) * b * np.clip((t - t0) / 0.001, 0, 1)
    return fade_tail(x, 0.2)


def wake_laps(r, count, gap):
    """A boat's wake reaching the shore: `count` slaps ~`gap` s apart, rising over three then dying away."""
    n = int((count * gap[1] + 2.0) * SR)
    out = np.zeros((n, 2))
    tt = 0.0
    for i in range(count):
        a = min(1.0, 0.4 + 0.3 * i) * 0.82 ** max(0, i - 2) * r.lognormal(0, 0.15)
        m = int(1.2 * SR)
        i0 = int(tt * SR)
        w = lap_slap(r, m) * a
        out[i0: i0 + m] += stereo(w, -0.35 + r.uniform(-0.25, 0.25))[: n - i0]
        tt += r.uniform(*gap)
    return out


def gutter(r, dips, dur, pan):
    """Lantern flame guttering: per dip, a soft low flutter (8-14 Hz) shaped like the light's dip."""
    n = int((dur + 0.5) * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for c, w, depth in dips:
        u = np.clip((t - c) / (w * 1.4), -1, 1)
        env = depth * 0.5 * (1 + np.cos(np.pi * u))
        fl = 0.55 + 0.45 * np.abs(np.sin(TAU * r.uniform(4, 7) * t + r.uniform(0, TAU)))
        x += unit(bandpass_noise(r, n, np.exp(r.uniform(np.log(140), np.log(260))), 2.0)) * np.sqrt(n) * env * fl
    return stereo(x, pan)


def fish_plop(r, jump, size):
    """A fish rising: a deep 'bloop' (a large entrained bubble, van den Doel: f0 = 3/r) with a short soft
    splash; on a jump, a lighter leap splash first and the bigger re-entry 0.45 s later (as on screen)."""
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)

    def entry(t0, k):
        tt = np.maximum(t - t0, 0)
        on = np.clip((t - t0) / 0.002, 0, 1)
        rad = np.exp(r.uniform(np.log(5e-3), np.log(9e-3))) * (0.8 + 0.3 * size)
        b, _ = bubble(rad, r.uniform(0.25, 0.6), tt)
        s = bandpass_noise(r, n, r.uniform(900, 1600), 2.2) * np.exp(-tt / r.uniform(0.04, 0.08)) * on
        return k * (unit(b * on) + 0.45 * unit(s))

    if jump:
        out += 0.45 * entry(0.0, 1.0) + entry(0.45, 1.0)
    else:
        out += entry(0.0, 1.0)
    for _ in range(r.integers(2, 6)):          # a few droplets falling back
        t0 = r.uniform(0.15, 0.7) + (0.45 if jump else 0)
        b, _ = bubble(np.exp(r.uniform(np.log(1.5e-3), np.log(3e-3))), r.uniform(0.1, 0.4), np.maximum(t - t0, 0))
        out += r.uniform(0.05, 0.15) * b * np.clip((t - t0) / 0.001, 0, 1)
    return fade_tail(onepole(out, 5000), 0.2)


def creak(r):
    """A treehouse wood creak (stick-slip friction): an irregular pulse train gliding in rate, exciting a
    few damped wood modes; 0.45-1.3 s."""
    D = r.uniform(0.45, 1.3)
    n = int((D + 0.25) * SR)
    f0, f1 = r.uniform(25, 50), r.uniform(60, 140)
    if r.random() < 0.5:
        f0, f1 = f1, f0
    imp = np.zeros(n)
    tt = 0.0
    while tt < D:
        u = tt / D
        rate = f0 + (f1 - f0) * u * u * (3 - 2 * u)
        a = np.sin(np.pi * u) ** 0.6 * r.lognormal(0, 0.25)
        imp[int(tt * SR)] += a
        tt += (1.0 / rate) * r.lognormal(0, 0.08)
    m = int(0.12 * SR)
    th = np.arange(m) / SR
    modes = np.zeros(m)
    for k, (lo, hi) in enumerate([(180, 260), (380, 520), (650, 900), (1100, 1500)]):
        modes += 0.7 ** k * np.sin(TAU * r.uniform(lo, hi) * th) * np.exp(-th / r.uniform(0.015, 0.04))
    x = np.convolve(imp, modes)[:n]
    return fade_tail(x, 0.1)


def car_hiss(r, dur, direction):
    """Tires on a wet road passing by: band-passed spray noise swelling as the car nears and fading as it goes,
    a little brighter at the closest point (more spray, less air absorption), and a low engine hum; the pan
    sweeps across with the car."""
    n = int((dur + 1.5) * SR)
    t = np.arange(n) / SR
    s = np.clip(t / dur, 0, 1)
    near = np.exp(-((s - 0.5) / 0.22) ** 2)
    nz = r.standard_normal((n, 2))
    spray = np.stack([fft_filter(nz[:, c], design_fir([(20, -60), (400, -24), (1200, -6), (3000, 0), (6000, -4), (12000, -18), (22000, -40)])) for c in range(2)], 1)
    hum = np.sin(TAU * r.uniform(55, 85) * t + 0.3 * np.sin(TAU * 0.7 * t)) * 0.15
    env = (0.08 + near) ** 1.4 * np.clip(t / 0.4, 0, 1) * np.clip((dur + 1.5 - t) / 1.0, 0, 1)
    pan = np.clip((s - 0.5) * 1.6 * direction, -0.85, 0.85)
    L, R = pan_gains(pan)
    x = (spray * env[:, None]) + (hum * env)[:, None] * 0.6
    return np.stack([x[:, 0] * L, x[:, 1] * R], 1)


def train_pass(r, dur, direction):
    """A distant train: a low rumble swelling and fading over the pass with paired wheel clacks at the rail
    joints, everything low-passed by distance."""
    n = int((dur + 2.0) * SR)
    t = np.arange(n) / SR
    s = np.clip(t / dur, 0, 1)
    env = np.sin(np.pi * s) ** 1.2 * np.clip((dur + 2 - t) / 2.0, 0, 1)
    rum = fft_filter(r.standard_normal(n), design_fir([(10, -40), (30, -6), (60, 0), (180, -3), (400, -18), (1500, -45), (22000, -70)]))
    cl = np.zeros(n)
    tc, gap = r.uniform(0.2, 0.6), r.uniform(0.7, 1.0)
    while tc < dur:
        for dt in (0.0, r.uniform(0.11, 0.16)):
            i = int((tc + dt) * SR)
            if i < n:
                cl[i] += r.uniform(0.7, 1.0)
        tc += gap * r.uniform(0.95, 1.05)
    m = int(0.06 * SR)
    th = np.arange(m) / SR
    clack = np.exp(-th / 0.012) * np.sin(TAU * r.uniform(220, 360) * th)
    cl = fft_filter(np.convolve(cl, clack)[:n], design_fir([(20, 0), (700, 0), (1500, -15), (4000, -40), (22000, -70)]))
    x = (unit(rum) * 30 + unit(cl) * 18) * env
    pan = np.clip((s - 0.5) * 1.2 * direction, -0.7, 0.7)
    L, R = pan_gains(pan)
    return np.stack([x * L, x * R], 1)


def log_settle(r, n_crackles, pan):
    """A log settling in the fire: a soft wooden thud and a quick burst of crackles and pops."""
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    thud = np.exp(-t / 0.08) * np.sin(TAU * r.uniform(70, 140) * t) * (1 - np.exp(-t / 0.003))
    thud += 0.3 * fft_filter(r.standard_normal(n), design_fir([(20, 0), (300, 0), (800, -20), (22000, -60)])) * np.exp(-t / 0.05)
    x = 0.8 * thud
    for _ in range(n_crackles):
        k = k_crackle(r) if r.random() < 0.8 else k_pop(r)
        i = int(r.uniform(0.02, 0.9) ** 1.6 * SR)
        m = min(len(k), n - i)
        x[i:i + m] += k[:m] * r.uniform(0.3, 1.0) * 0.6
    return stereo(fade_tail(x, 0.1), pan)


def neon_buzz(r, dips, dur):
    """Neon transformer buzz that crackles while the sign flickers (120 Hz harmonics, gated by the dips)."""
    n = int((dur + 0.3) * SR)
    t = np.arange(n) / SR
    saw = sum(np.sin(TAU * 120 * k * t + r.uniform(0, TAU)) / k for k in range(1, 12))
    g = np.zeros(n)
    for c, w, d in dips:
        g = np.maximum(g, d * np.exp(-((t - c) / max(w, 0.02)) ** 2))
    return stereo(saw * (0.15 + g) * np.clip((dur + 0.3 - t) / 0.2, 0, 1) * np.clip(t / 0.05, 0, 1), r.uniform(-0.4, 0.4))
