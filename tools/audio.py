"""Procedural ambience audio for plate scenes: original (no samples), deterministic, synced to the video.

Rain heard from a covered treehouse porch, roof runoff and drips, wind gusts, and thunder after each
lightning flash. It is driven by the scene's timeline JSON (`node src/cli.mjs timeline scenes/<scene>`):
gusts and stream flow use the same formulas as the shaders, and thunder follows each flash after its
distance / 343 m/s.

Usage (repo root):
  .venv/Scripts/python tools/audio.py out/<scene>/timeline.json --start 0 --duration 60 --out out/<scene>/audio.wav [--stems]

The code is in tools/cozy/audio/ (TASKS.md T17): dsp, kernels, events and ambience. This file is the command line,
and the names other tools import from audio stay importable from here.

Design (docs/DECISIONS.md, 2026-10-15 "Procedural ambience audio"):
- Random access, click-free: audio is made in canonical 15 s blocks, each computed from 3 s before it.
  Every filter is a convolution shorter than that, and all randomness comes from per-second seeded slots,
  so any time range renders bit-identically and consecutive blocks join exactly.
- Granular rain: each layer has a bank of synthesized impact sounds ("kernels"), triggered by seeded
  Poisson grains whose rate follows the gusts and slow intensity drift:
    patter  drops on leaves, vines and the railing nearby (band-passed noise bursts + resonant ticks)
    roof    rain drumming on the plank roof overhead (damped low plank modes, muffled through wood)
    water   drops on the lake and puddles: Minnaert bubbles, van den Doel (2005): f0 = 3/r, rising pitch
    runoff  each roof stream's splash below; rate and level follow the stream's visual flow(t)
  wash = distant rain roar (shaped stereo noise); wind = gust whoosh + leaf rustle; drips = sparse
  close plinks/toks; a synthetic porch reverb on a send bus.
- Thunder: per strike, N-waves from a random tortuous lightning channel (arrival = distance / 343 m/s),
  low-passed by distance, long valley reverb, 0.4 s soft onset. Peak short-term loudness sits 1.5-4.5 dB
  over the bed (docs/GOALS.md: <= ~6 dB, never startling).
- Event sounds (stem "events"), all well under the bed: a passing boat's hull wash (level, brightness and
  pan follow its distance/screen profile from the timeline), its wake lapping on the shore below the
  porch ~20-30 s after its closest approach, a lantern's flame flutter at each light dip, and treehouse
  wood creaks (stick-slip) at strong gust peaks in windy spells (~3.5/h, >= 70 s apart).
- The bed is normalized to the scene's loudness target (-20 LUFS ambience), cached per configuration.
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np

from audio_analyze import integrated_lufs, k_weight, loudness_blocks  # noqa: E402
from cozy.audio.ambience import Ambience, make_cfg
from cozy.audio.dsp import SR, write_wav


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stems", action="store_true", help="also write <out>_rain/_runoff/_thunder/_events.wav (+ _musicbus.wav)")
    ap.add_argument("--report", action="store_true", help="loudness / true peak / thunder-over-bed report")
    ap.add_argument("--music", help="music_plan.json (tools/music.py plan): also write <out>_music.wav = ambience + music")
    a = ap.parse_args()
    tl = json.loads(pathlib.Path(a.timeline).read_text())
    cfg = make_cfg(tl)
    t0 = time.time()
    amb = Ambience(tl, cfg)
    master = amb.calibrate(pathlib.Path(a.timeline).parent)
    music = json.loads(pathlib.Path(a.music).read_text()) if a.music else None
    if music and not music["entries"]:
        print("music: the plan has no tracks; writing the ambience-only mix", file=sys.stderr)
        music = None
    # With music, render 0.25 s more on each side: the mix limiter is local, so the cropped range is
    # sample-exact whatever the segmentation.
    N0, N1 = int(round(a.start * SR)), int(round((a.start + a.duration) * SR))
    S0, S1 = (max(0, N0 - SR // 4), N1 + SR // 4) if music else (N0, N1)
    ext = amb.render(S0 / SR, (S1 - S0) / SR)
    stems = {k: v[N0 - S0: N1 - S0] for k, v in ext.items()}
    mix = sum(stems.values())
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(out, mix)
    if a.stems:
        for k, v in stems.items():
            write_wav(out.with_name(f"{out.stem}_{k}.wav"), v)
    peak = 20 * np.log10(np.abs(mix).max() + 1e-12)
    info = {"out": str(out), "start": a.start, "duration": a.duration, "master_db": round(master, 2), "sample_peak_dbfs": round(float(peak), 2)}
    mmix = None
    if music:
        import music as M
        bus = M.render(music, S0 / SR, (S1 - S0) / SR)
        mc = music["cfg"]
        ga = 10 ** (mc.get("ambience_db", 0.0) / 20)                        # the ambience sits a little lower under music,
        gt = 10 ** (mc.get("thunder_db", mc.get("ambience_db", 0.0)) / 20)  # the thunder at its own level
        mmix = M.limit(sum(v * (gt if k == "thunder" else ga) for k, v in ext.items()) + bus, S0)[N0 - S0: N1 - S0]
        write_wav(out.with_name(f"{out.stem}_music.wav"), mmix)
        if a.stems:
            write_wav(out.with_name(f"{out.stem}_musicbus.wav"), bus[N0 - S0: N1 - S0])
        info["music_out"] = str(out.with_name(f"{out.stem}_music.wav"))
    print(json.dumps({**info, "sec": round(time.time() - t0, 1)}))
    if a.report:
        report(amb, mix, a.start, cfg, stems)
        if mmix is not None:
            import music as M
            from audio_analyze import true_peak
            lu, tp = integrated_lufs(k_weight(mmix)), true_peak(mmix)
            want = M.mix_target(cfg["lufs"], music["cfg"])
            ok = abs(lu - want) <= 1.5 and tp <= -1.5
            print(f"music mix: integrated {lu:.1f} LUFS (target {want - 1.5:.1f}..{want + 1.5:.1f}) | true peak {tp:.1f} dBTP (<= -1.5)")
            print("MUSIC", "PASS" if ok else "FAIL")


def report(amb, mix, start, cfg, stems=None):
    """Loudness targets (docs/GOALS.md): ambience ~ -20 LUFS integrated, true peak <= -1.5 dBTP, thunder
    <= ~6 dB over the bed (short-term, 3 s); event sounds stay under the bed (momentary <= bed - 3 dB)."""
    from audio_analyze import true_peak
    xk = k_weight(mix)
    st, _ = loudness_blocks(xk, 3 * SR, SR // 10)
    tp = true_peak(mix)
    print(f"integrated {integrated_lufs(xk):.1f} LUFS (target {cfg['lufs']:.0f}) | short-term {np.percentile(st, 5):.1f}..{st.max():.1f} | "
          f"true peak {tp:.1f} dBTP (<= -1.5)")
    ok = tp <= -1.5
    for ev in amb.thunders:
        ts = ev["thunder"]["t"] - start
        if not (0 <= ts < len(mix) / SR):
            continue
        pre = st[max(0, int((ev["t"] - start - 6) * 10)): max(1, int((ev["t"] - start - 1.5) * 10))]
        post = st[int(ts * 10): int((ts + 14) * 10)]
        if len(pre) and len(post):
            over = float(post.max() - np.median(pre))
            ok &= over <= 6.0
            print(f"  {'far rumble' if ev['type'] == 'farflash' else 'thunder'} #{ev['id']} at {ev['thunder']['t']:.2f} s ({ev['thunder']['distance_m']} m): {over:+.1f} dB over the bed (<= 6)")
    if stems is not None and np.abs(stems["events"]).max() > 0:
        me, _ = loudness_blocks(k_weight(stems["events"]), int(0.4 * SR), SR // 10)
        rel = float(me.max() - cfg["lufs"])
        ok &= rel <= -3.0
        print(f"  events: loudest momentary {me.max():.1f} LUFS at {start + me.argmax() * 0.1 + 0.2:.1f} s = bed {rel:+.1f} dB (<= -3)")
    print("AUDIO", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
