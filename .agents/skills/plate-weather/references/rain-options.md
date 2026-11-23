# rainLayer, runoff and related options

Every option `rainLayer(ctx, opts)` in `src/library/rain.js` reads, with its default and the approved Treetop value (`scenes/treetop-plate/scene.js`, rain v3.1 + runoff approved 2026-10-15). Sizes in px are 3840×2160 plate px. Top-level options can be overridden per render with `--params rain.<opt>=<v>` (`a:b` for a range); nested objects (`wind`, `clumps`, `runoffLook`) cannot.

## Falling rain

| Option | Default | Treetop | Meaning |
|---|---|---|---|
| `plate` | required | `'treetop_rainy'` | `out/plates/<plate>/`: `lights.png` (G = outdoors mask, B = light glow), `env.png`, `plate.json` (`env_linear.sky`) |
| `count` | 30000 | 13000 (1 with `only=runoff`) | drops visible at nominal intensity. The pool is `count × max(weather track rain)`, so heavier spells have headroom; each drop decides at entry whether it shows |
| `depth` | [3, 30] | [2.4, 30] | drop distance range (m), from just beyond the roof edge out into the valley |
| `depthPower` | 1 | 1.45 | depth pdf ∝ z^-k: 1 = log-uniform, > 1 = more near drops |
| `dropRange` | [0.5, 4.5] | [0.5, 3.6] | drop diameter range (mm) |
| `dropLambda` | 2.0 | 2.4 | exponential size distribution (1/mm, Marshall–Palmer shape); higher = finer rain |
| `focalPx` | 2700 | 2700 | focal length in px (~70° horizontal FOV); share it with `leavesLayer` and the boat camera |
| `shutter` | 1/60 | 1/110 | exposure (s); streak length = screen speed × shutter (reference footage ≈ 1/120 s) |
| `alphaRef` | 0.2 | 0.45 | opacity of a 2 mm drop at 7 m; every other drop scales physically from it |
| `farBoost` | 0 | 0.3 | opacity × (z / 7 m)^farBoost: keeps a visible slow far layer (artistic) |
| `maxAlpha` | 0.6 | 0.9 | per-drop opacity cap |
| `minWidth` | 1.6 | 3.4 | lens-blur width floor (px); opacity scales down as width grows, so energy is kept |
| `focus` | 12 | 12 | focus distance (m) |
| `coc` | 8 | 13 | defocus width in px = coc × \|1/z − 1/focus\|: near drops get wider and fainter |
| `skyGain` | 2.0 | 2.2 | gain on the sky color (`plate.json` `env_linear.sky`) and on `env.png` |
| `envMix` | 0 | 0.85 | drop light: 0 = the sky color everywhere, 1 = the local `env.png` (dim in front of dark forest, bright against the sky) |
| `warm` | `'#ffb26a'` | same | lantern glint color |
| `warmGain` | 1.0 | 0.45 | lantern glint strength (× the `lights.png` B glow) |
| `warmNear` | 5 | 3 | glints fade with distance: exp(−max(z − 3, 0) / warmNear), so only near drops catch lanterns |
| `glint` | 0.35 | default | per-drop brightness spread (× 1 ± glint) |
| `wind` | `{ mean: 0.3, gust: 0.8, gustCycles: 5, fronts: 0.6, turb: 0.35 }` | `{ mean: 0.05, gust: 0.5, gustCycles: 5, fronts: 0.6, turb: 0.75 }` | m/s; see [Wind](#wind) |
| `clumps.amount` | 1 | 1.0 | density multiplier |
| `clumps.strength` | 0.5 | 0.55 | how much the gaps between clumps thin the rain (0 = uniform) |
| `clumps.cycles` | 11 | 13 | clump pattern changes per loop (integer). The pattern is sampled where and when each drop entered, so clumps fall with the rain |
| `clumps.across` | 3 | 3 | clump cells across the frame (integer) |
| `clumps.drift` | 1 | 1 | sideways drift of the pattern in whole frame widths per loop (integer) |
| `marginX`, `marginY` | 700, 240 | defaults | px of spawn area beyond the frame edges (wind carries drops in) |
| `flashGain` | 2.5 | default | lightning: drop radiance × (1 + flash × flashGain) |
| `debug` | false | `debug=rain` | coverage only (white, additive) for `rain_qa.py --leak`; flash off |

Physics per drop (rain.js header): terminal velocity V(D) = max(0.6, 9.65 − 10.3 e^(−0.6 D)) m/s (Atlas 1973, D in mm); screen speed = V × focalPx / z; streak length = speed × shutter; width = D × focalPx / z, floored at `minWidth` plus defocus; opacity ∝ the share of the exposure the drop covers a pixel (Garg & Nayar 2007), composited "over" toward the drop's radiance (premultiplied), never additive white. Radiance = mix(sky, env.png, envMix) × skyGain + warm glow × warmGain × distance falloff, × (1 + flash × flashGain). Every drop re-enters a whole number of times per loop; its x is re-drawn each time.

## Runoff sources (`runoff: [...]`, `runoffParams()`)

| Field | Default | Meaning |
|---|---|---|
| `x`, `y` | required | lip position (normalized, y down; y < 0 = a roof edge just above the frame) |
| `z` | 3.2 | lip distance (m): sets bead size and fall speed in px (Treetop 2.3–3.4) |
| `d` | 4 | bead diameter (mm); each bead varies 0.45–1.35× and grows with flow |
| `rate` | 20 | bead releases per second at full flow, rounded to a whole number per loop. ≥ 10 = a stream (the audio adds splashes for these), ~0.5–2.5 = a drip |
| `flow` | 0.8 | mean flow 0..1 (share of release slots that fire) |
| `burst` | 0.2 | surge amplitude |
| `burstCycles` | 3 | slow swells per loop (integer) |
| `neck` | 0 | unbroken column under a visible lip (m, × flow); only drawn when y > 0 |
| `spread` | 0.02 | sideways scatter (m per m fallen) |
| `gain` | 1 | opacity multiplier |
| `warm` | 1.5 | lantern light it catches (× the light glow) |
| `wobble` | 0.006 if rate ≥ 10, else 0 | sway of the release point (m); it travels down the stream |
| `bright` | 1 | brightness multiplier |

Flow: `flow(t) = clamp(flow + burst·(0.5 sin θ + 0.3 sin(2θ + 2.1 + s) + 0.35 sin(2π·37 t/L + 3s)) + 0.22·(0.5 sin(2π·263 t/L + 5s) + 0.5 sin(2π·389 t/L + 7s)), 0.04, 1)` with θ = 2π·burstCycles·t/L + s, times the weather track's `streams`. The source seed `s` comes from its index (101 + 977·i), so **order matters**: append new sources. `flow()` in `tools/cozy/audio/ambience.py` is a copy, held to the JS by `tests/test_parity.py` (splashes lag the picture by `stream_fall_s` = 1.3 s). The cycle counts 37, 263, 389 (and the 277/443 sway) are per loop and were tuned for L = 120 s.

Beads fall from rest with quadratic drag: h = Vt·τ·ln cosh(t/τ), v = Vt·tanh(t/τ), τ = Vt/g; the wind at release pushes them sideways and relaxes.

| Runoff option on `rainLayer` | Default | Treetop | Meaning |
|---|---|---|---|
| `runoffGain` | 6 | 6 | runoff opacity gain |
| `runoffMaxAlpha` | 0.85 | default | bead opacity cap |
| `runoffLook` | `{}` | `{ minWidth: 4.5, warmGain: 1.2, envMix: 0 }` | pins runoff's own width floor, glint gain and env mix. Without it they follow the falling rain's `minWidth`, `warmGain`, `envMix`, so falling-rain tuning would change the streams |

## Wind

`wind = { mean, gust, gustCycles, fronts, turb }` in m/s. At absolute time t and screen x: `windAt = mean + gust·k·(0.75 sin φ + 0.25 sin(2φ + 1.3))`, φ = 2π(gustCycles·t/L − fronts·x/W), with k = the weather track's `wind` at t. Drift is its exact integral since the drop entered (`windDrift` in timeline/wind.js; the same formula in the shader). `gustCycles` is rounded to an integer per loop (5 per 120 s = a gust every 24 s; the timeline's `windAt` doesn't round, so keep it a whole number); `fronts` makes gusts sweep across the frame; `turb` is a per-drop constant (± m/s), so small slow drops lean more. Share the same object with `leavesLayer` and `events.leaves.wind` (+ `loop`); the audio's gust (`gust()` in `tools/cozy/audio/ambience.py`) samples it at x = 0.45.

## Plate shader options that react to weather (`plateLayer`)

| Option | Default | Meaning |
|---|---|---|
| `mist` | 0.22 | drifting mist over far terrain (disparity < ~0.12), thicker with the track's rain |
| `mistColor` | `'#2a3044'` | mist color |
| `ripple` | 0.0007 | water ripple displacement (uv) on the water mask; rain rings are added on the water, scaled by the track's rain |
| `sway` | 0.0008 | foliage sway (uv) on the foliage mask |
| `flicker` | 0.12 | light flicker on the lights mask |
| `lightning` | `{ color: '#b9c8ff', sky: 2.2, land: 0.9, roomNear: 0.45, roomAmbient: 0.08 }` | flash response: sky around the strike, far landscape and mist, the porch near the opening (`flash.png`), the room overall |

## Leaves (`leavesLayer`)

`{ plate, wind, focalPx = 2700, shutter = 1/110, ambient = 0.45 (Treetop 0.26), warm = 0.9, debug }`. Leaves drift on the same wind (`turb` unused), are lit by `env.png` and the light glow, brighten by 1 + 0.6 × flash, and are masked to the outdoors. Their schedule comes from `events.leaves` (ambient-events).
