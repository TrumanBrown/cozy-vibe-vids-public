# Ambience internals (tools/audio.py, code in tools/cozy/audio/)

Numbers are `DEFAULTS` in `tools/cozy/audio/ambience.py` (checked 2026-10-15, including the fish and flurry keys). A scene overrides any of them through its `audio` object (deep merge), e.g. `audio: { lufs: -20, levels_db: { roof: -10 }, rates: { drips: 0.5 }, reverb: { wet_db: -9 }, events: { creak_db: -14 } }`.

## Bed layers (stems `rain` and `runoff`)

| Layer | What it is | Level (dB) | Rate (/s) | Reverb send |
|---|---|---|---|---|
| `wash` | distant roar: stereo noise through a warm FIR (amplitude −4.75 dB/oct above 500 Hz), slightly decorrelated | −2 | — | 0.15 |
| `patter` | drops on leaves, vines and railing: 16 kernels of band-passed bursts (1–5 kHz) plus leaf/wood ticks | −6 | 1100 | 0.35 |
| `near` | close soft "tik/tok" drops on the railing: 12 kernels, duller and longer | −7 | 40 | 0.4 |
| `roof` | drumming on the plank roof: 12 kernels of damped plank modes (85–330 Hz fundamental) muffled through wood | −7 | 850 | 0.4 |
| `water` | drops on the lake: 16 Minnaert bubbles (van den Doel 2005, f0 = 3/r, r 0.4–2.5 mm) | −16 | 600 | 0.5 |
| `runoff` | splashes under each roof stream (`rate` ≥ 10): bubbles or band-passed splashes; rate follows the stream's `flow()` 1.3 s earlier (`stream_fall_s`) | −10 | 240 per stream at full flow | 0.5 |
| `drips` | sparse close plinks (puddle bubble) or toks (wood), individually synthesized | +6 (peak) | 0.3 | 0.6 |
| `wind` | gust whoosh (80–450 Hz) + leaf rustle (2–7 kHz), × gust^1.5 | −15 | — | 0.2 |
| reverb | porch room: rt60 1.0 s, wet −7 dB, early reflections | — | — | — |

Levels are RMS at nominal intensity before loudness normalization, so they only set the balance; `calibrate()` scales the whole bed to `lufs`. Grain rates follow `intensity(t)`: micro drift (±0.8 dB over 9 s, ±1.2 dB over 41 s, per-layer ±0.4 dB over 13 s) × the timeline's `track.rain` × (1 + `gust_boost` 0.25 × gust). `gust(t)` is the visual `windAt` at x = 0.45 with the track's wind; `flow(s, t)` is an exact copy of `flowAt` in `rain.js` × the track's streams. Grain amplitudes are lognormal, truncated at +2.2 σ so close drops stand out but never startle.

## Thunder (stem `thunder`)

Per strike (`thunder_wave`): a random tortuous channel from the ground point up 2.2–3.6 km plus an in-cloud run; each 30 m segment sends an N-wave that arrives at its distance / 343 m/s (first arrival = the timeline's `thunder.t`), loudest broadside; 4 distance bands low-passed at 320–700 Hz by nearness (× 0.85 per band); a rumble texture following the arrival density; high-pass ~30 Hz; valley reverb (rt60 4 s, wet 0.6, 0.12 s pre-delay); 0.4 s soft onset and a 2 s end fade. Level: the mix's short-term (3 s) loudness rises by `over_bed_db` 1.2–4.5 dB (nearer = more), then a look-ahead limiter at −8 dBFS. Pan from the strike's screen x. Cached per strike; waves are < 40 s long.

## Event sounds (stem `events`)

| Event | Function | Level | Notes |
|---|---|---|---|
| boat | `boat_wash(r, profile, dur)` | `boat_db` −15 (short-term 3 s) | band-passed water noise sloshing with the bob; level 60/dist × (speed/1.6)^1.5, near/far spectra cross-faded 90–240 m, pan from the screen x; 6 s fades at the trip's edges |
| boat wake | `wake_laps(r, 7–11 slaps, 1.3–2.4 s apart)` | `lap_db` −9 (momentary 0.4 s) | starts `lap_delay` 18–30 s after the boat's closest approach, panned left of center |
| lantern | `gutter(r, dips, dur, pan)` | `gutter_db` −12 + 20 log10(deepest dip / 0.6) | 8–14 Hz low flutter shaped like each light dip |
| creak | `creak(r)` from `creaks(t0, t1)` | `creak_db` −11 ± 2 | stick-slip pulse train exciting wood modes; at visual gust peaks (every loop/gustCycles s) while `track.wind` > `creak_wind` 1.15, with probability `creak_p` 0.35 × how far above; never on 2 consecutive peaks. Also at the peak (40–60 %) of flurries with \|amp\| ≥ 1.3 m/s, with probability `flurry_creak` 0.5 |
| fish | `fish_plop(r, jump, size)` (`LAYER` 17) | `fish_db` −13 at 100 m, − 20 log10(dist / 100) (min 30 m), + 3 × (size − 1) | a large entrained bubble (van den Doel, f0 = 3/r, r 5–9 mm) plus a soft 0.9–1.6 kHz splash and 2–5 droplets; a jump adds a lighter leap splash 0.45 s before the re-entry, as on screen; `dist` and `pan` come from `writeTimeline` (lake camera) |
| distant rumble | `thunder_wave` with `far_thunder` overrides (farflash events, `thunder` stem) | `far_thunder.over_bed_db` [0.3, 1.2] by the event's `gain` | the storm-thunder synthesis with a low-pass of 130–240 Hz, a 1.5 s roll-in, rt60 5 s, wet 0.75, tail 9 s: measured centroid ~75 Hz, 90 % of the energy below ~115 Hz, ~9 s long, ~8 dB under storm thunder. It arrives `delay` 3–5 s after the flash (the user found 8–20 s too long) |
| flurry | wind layer, `flurry_env(t)` = \|flurry wind\| / 2 clipped to 1 | `flurry_whoosh` 1.2, `flurry_rustle` 2.0 (gain on the envelope^1.2) | the wind layer's whoosh and leaf rustle swell with the gust; rain intensity × (1 + `gust_boost` × (gust + 0.8 × flurry)). Measured: the wind layer rises ~13 dB in a flurry and stays ~10 dB under the rain wash |

`_level(x, rel_db, win)` scales a wave so its loudest `win`-second window sits `rel_db` relative to the bed target. Every event wave is seeded by `rng(seed, LAYER[name], ev["seed"])`, cached per event, and placed at its start sample, so it is identical in every render range.

## Determinism machinery

- `SR` 48 kHz; canonical blocks `BLK` = 15 s, each computed over `MARGIN` = 3 s of warm-up plus the block (`N_EXT` = 864 000 samples, an FFT-friendly size). Every filter and kernel is shorter than the warm-up, so consecutive blocks join exactly.
- All randomness: `rng(seed, LAYER[layer], key, slot + SLOT_OFS)`, one generator per layer, key and whole second. Grains, noise, drips and modulation knots are drawn per second slot, so any range regenerates the same values.
- Never renumber `LAYER` ids or reorder draws inside a slot: that changes every render of every scene.
- Outputs: 24-bit WAV with TPDF dither seeded by the file length. The float signal of a range is bit-identical to the same range inside a longer render; the WAV files differ by the dither (±1–2 LSB) unless the lengths match. Compare with a tolerance.
- `master` gain: `calibrate()` renders one loop's worth of blocks from 300 s at nominal weather (track = 1, so the drift stays audible) and stores the gain in `<timeline folder>/audio_cal.json`, keyed by `VERSION`, seed, the merged config, the weather block and the loop length. Bump `VERSION` whenever synthesis changes.
- Fades: 2 s in at t = 0 and 3 s out at the end of the video (`fade_s`); the master render adds 1.5 s / 2 s fades at the edges of a `--from/--length` window.
