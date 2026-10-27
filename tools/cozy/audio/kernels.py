"""The impact kernels of the ambience (TASKS.md T17), moved verbatim from tools/audio.py: short synthesized sounds
with unit energy, each drawn from the generator it is given. Ambience plays them as seeded grains (drip_wave once per
drip), and events.log_settle plays the fire's.

  k_patter, k_near, k_roof, k_water, k_runoff   rain on leaves, close drops, the roof, the lake; a stream's splash
  drip_wave                                     one close drip: a puddle plink or a wooden tok
  k_crackle, k_pop                              the fire's crackles and pops
  k_clink                                       a spoon on a cup
"""
import numpy as np

from cozy.audio.dsp import SR, TAU, bandpass_noise, bubble, fade_tail, onepole, unit


def k_patter(r):
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    fc = np.exp(r.uniform(np.log(1000), np.log(5000)))
    burst = bandpass_noise(r, n, fc, r.uniform(1.0, 2.2)) * np.exp(-t / r.uniform(1.0e-3, 5.0e-3)) * (1 - np.exp(-t / 3e-4))
    x = unit(burst)
    if r.random() < 0.7:  # leaf / wood resonance
        ft = np.exp(r.uniform(np.log(400), np.log(2200)))
        tick = np.sin(TAU * ft * t) * np.exp(-t / r.uniform(2e-3, 9e-3)) * (1 - np.exp(-t / 3e-4))
        x = x + r.uniform(0.2, 0.55) * unit(tick)
    return unit(fade_tail(onepole(x, 7000)))


def k_near(r):
    """A close drop on the railing/leaves: a soft 'tik/tok', longer and duller than distant patter
    (peaks stay low for its energy, so individual drops read without sharp clicks)."""
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    fc = np.exp(r.uniform(np.log(700), np.log(2600)))
    burst = bandpass_noise(r, n, fc, r.uniform(0.8, 1.6)) * np.exp(-t / r.uniform(3e-3, 8e-3)) * (1 - np.exp(-t / 8e-4))
    ft = np.exp(r.uniform(np.log(300), np.log(1400)))
    tok = np.sin(TAU * ft * t + r.uniform(0, TAU)) * np.exp(-t / r.uniform(6e-3, 16e-3)) * (1 - np.exp(-t / 8e-4))
    x = unit(burst) + r.uniform(0.5, 0.9) * unit(tok)
    return unit(fade_tail(onepole(x, 4500)))


def k_roof(r):
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    f1 = np.exp(r.uniform(np.log(85), np.log(330)))
    tau = r.uniform(0.02, 0.06)
    x = np.zeros(n)
    for ratio, amp in ((1.0, 1.0), (r.uniform(2.2, 2.9), 0.55), (r.uniform(3.9, 5.3), 0.3)):
        x += amp * np.sin(TAU * f1 * ratio * t + r.uniform(0, TAU)) * np.exp(-t / (tau / ratio ** 0.6))
    click = onepole(r.standard_normal(n) * np.exp(-t / 1.2e-3), 1600)
    x = unit(x) + 0.6 * unit(click)
    x = onepole(x * (1 - np.exp(-t / 3e-4)), r.uniform(1100, 2100))  # muffled through the roof
    return unit(fade_tail(x))


def k_water(r):
    radius = np.exp(r.uniform(np.log(0.4e-3), np.log(2.5e-3)))   # ~1.2-7.5 kHz
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    b, d = bubble(radius, r.uniform(0.05, 0.25), t)
    impact = r.standard_normal(n) * np.exp(-t / 2e-4)
    x = unit(b * (1 - np.exp(-t / 1.5e-4))) + 0.3 * unit(impact)
    return unit(fade_tail(onepole(x, 5000)))  # distant: air absorption


def k_runoff(r):
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    if r.random() < 0.55:
        b, _ = bubble(np.exp(r.uniform(np.log(0.8e-3), np.log(4e-3))), r.uniform(0.1, 0.4), t)
        x = unit(b * (1 - np.exp(-t / 1e-4)))
    else:
        x = unit(bandpass_noise(r, n, np.exp(r.uniform(np.log(400), np.log(2600))), 1.5) * np.exp(-t / r.uniform(3e-3, 15e-3)) * (1 - np.exp(-t / 2e-4)))
    return unit(fade_tail(onepole(x, 4500)))


def drip_wave(r):
    """One close drip: a puddle plink (low bubble, strongly rising) or a wooden tok, with a soft splash."""
    n = int(0.14 * SR)
    t = np.arange(n) / SR
    if r.random() < 0.6:
        b, _ = bubble(np.exp(r.uniform(np.log(1.4e-3), np.log(3.5e-3))), r.uniform(0.15, 0.5), t)
        x = unit(b * (1 - np.exp(-t / 1.5e-4)))
    else:
        ft = np.exp(r.uniform(np.log(550), np.log(1500)))
        x = unit(np.sin(TAU * ft * t) * np.exp(-t / r.uniform(6e-3, 18e-3)) * (1 - np.exp(-t / 2e-4)))
    x = x + 0.2 * unit(bandpass_noise(r, n, 3000, 2.0) * np.exp(-t / 1.5e-3))
    return unit(fade_tail(x))


def k_crackle(r):
    """A fire crackle: a 0.4-3 ms noise burst ringing through one or two resonances (wood fibers snapping)."""
    n = int(r.uniform(0.006, 0.03) * SR)
    t = np.arange(n) / SR
    burst = r.standard_normal(n) * np.exp(-t / r.uniform(0.0004, 0.003))
    out = 0.35 * burst
    for _ in range(int(r.integers(1, 3))):
        f, q = r.uniform(1200, 6500), r.uniform(4, 14)
        ti = np.arange(int(0.02 * SR)) / SR
        ir = np.exp(-np.pi * f / q * ti) * np.sin(TAU * f * ti)
        out = out + np.convolve(burst, ir)[:n] * r.uniform(0.02, 0.05)
    return unit(fade_tail(onepole(out, 7500), 0.2))     # a touch of air absorption: no inter-sample overs


def k_pop(r):
    """A louder pop (sap boiling off): a sharp snap with a lower body (400-1200 Hz) and a short noisy tail."""
    n = int(r.uniform(0.04, 0.09) * SR)
    t = np.arange(n) / SR
    body = np.exp(-t / r.uniform(0.004, 0.012)) * np.sin(TAU * r.uniform(400, 1200) * t + r.uniform(0, TAU))
    snap = r.standard_normal(n) * np.exp(-t / 0.0015)
    tail = r.standard_normal(n) * np.exp(-t / r.uniform(0.01, 0.03)) * 0.25
    return unit(fade_tail(body + 0.8 * snap + tail, 0.2))


def k_clink(r):
    """A spoon on a cup or two cups touching: a few inharmonic modes of a small ceramic body, quick decay."""
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f0 = r.uniform(1800, 4200)
    x = np.zeros(n)
    for ratio, a in ((1.0, 1.0), (2.32, 0.6), (4.25, 0.35), (6.63, 0.2)):
        x += a * np.exp(-t / (r.uniform(0.03, 0.18) / ratio ** 0.5)) * np.sin(TAU * f0 * ratio * t + r.uniform(0, TAU))
    x *= 1 - np.exp(-t / 0.0005)
    return unit(fade_tail(x, 0.2))
