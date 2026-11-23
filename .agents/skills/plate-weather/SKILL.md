---
name: plate-weather
description: 'Rain, roof runoff, vine drips, wind, gust flurries, calm water ripples, slow weather drift, and storm plus distant lightning with distance-synced thunder for plate scenes: src/library/rain.js (rainLayer options, runoff sources), plate.js lightning light, distant flashes and water ripples, src/library/timeline/ (weatherTrack, strike schedule, farflash, strikeEnvelope/flashAt, windAt), tools/rain_qa.py (--leak --seam --flash --profile --calibrate --params) and tools/rain_analyze.py. Use when: adding or tuning rain on a new plate; rain looks too heavy, too big, too uniform or too visible in one part of the frame; placing roof streams or drips; rain leaks onto the roof, pet, railing or interior; calibrating rain against reference footage; changing wind or storm drift; making lightning more frequent without making it louder; making water move or ripple; tuning lightning brightness or checking flash safety (WCAG 2.3.1); checking thunder delay and A/V sync; or reviewing the hard-won rain lessons before writing new weather (snow, fog, surf).'
argument-hint: 'scene folder and the problem, e.g. "scenes/treetop-plate: rain too visible on the right"'
---

# Plate weather: rain, runoff, wind, drift, lightning, thunder

Rain in a plate scene is physically based instanced geometry over a still plate, limited to the outdoors by a depth-derived mask, lit by its local surroundings, moved by one shared wind, slowly modulated by a seeded weather track, and lit by lightning whose thunder arrives at distance / 343 m/s. Everything is a pure function of absolute time, so any frame renders alone and the 120 s base loop is seamless. Approved by the user on 2026-10-15: rain v3.1 (the roof streams and drips as they are), lightning, thunder and audio as they were.

| File | Role |
|---|---|
| `src/library/rain.js` | `rainLayer`: falling streaks + runoff beads (instanced quads); `runoffParams` (shared with the audio) |
| `src/library/plate.js` | lightning light on sky, land, mist and the porch (`flash.png`); rain rings and mist follow the track's rain |
| `src/library/timeline/` (lightning.js, weather.js, wind.js) | strike schedule, `strikeEnvelope`/`flashAt`, `weatherTrack`/`trackAt`, `windAt`/`windDrift` |
| `src/library/leaves.js` | leaves drift on the same wind and catch the flash |
| `tools/audio.py` (code in `tools/cozy/audio/`) | thunder at `thunder.t`, gusts, runoff splashes synced to the shader's flow (ambience-audio); `tests/test_parity.py` holds its wind, flow and flurry to the JS |
| `tools/rain_qa.py`, `tools/rain_analyze.py` | leak, seam, flash, per-band profile, calibration against footage |
| `scenes/treetop-plate/scene.js` | the approved reference values |

All options with defaults and Treetop values: [references/rain-options.md](./references/rain-options.md).

## How it fits together

- **Outdoors mask** (`lights.png` G, from `tools/plate_prep.py`): disparity < `outdoor_disp`, edge-snapped, clipped by `only_outdoor`. Every rain, runoff, leaf and boat fragment is multiplied by it, so weather never shows on the roof, pet, railing or interior. Masks: plate-scene and keyart-pipeline skills.
- **Falling rain:** each drop has a depth z, a diameter D and a terminal velocity; its streak is the distance it moves while the shutter is open; its opacity is the share of the exposure it covers a pixel; it is composited "over" toward its own radiance (sky mixed with the local `env.png`, plus lantern glints near lights). Density clumps are attached to the drops; the weather track's rain decides at each drop's entry whether it shows.
- **Runoff:** beads released at a flow-modulated rate fall from rest under gravity with drag, so a stream is a continuous neck under the lip that breaks into accelerating, stretching dashes. Drips are the same sources at low rates.
- **Wind:** one object `{ mean, gust, gustCycles, fronts, turb }` shared by rain, runoff, leaves (`leavesLayer` and `events.leaves.wind`) and the audio. Gust fronts sweep across the frame; drift is the exact integral of the wind since a drop entered.
- **Weather drift** (`events.weather` → `weatherTrack`): three multipliers sampled every `dt` (5 s): `rain` (0.7–1.35), `streams` (the rain lagged by `streamLag`, 90 s, as the roof fills) and `wind` (0.5–1.7). Smooth seeded noise (rain on ~7 and ~25 min scales, wind on ~5 and ~15 min) plus storm swells within `stormHalfWidth` (600 s) of each strike (`stormRain` 0.22, `stormWind` 0.35; see `weatherTrack` for how swells are normalized). Shaders sample it at absolute time as a 1D texture; `tools/audio.py` interpolates the same samples. Without it, a 10 h video at constant rain feels like a loop.
- **Lightning:** each strike is 1–3 return strokes merged into one soft swell (0.1 s rise, 0.3 s decay per stroke, plus a 0.25 cloud afterglow that decays over ~0.9 s; 4.5 s span), at a random glow center in the sky. `flashAt(timeline, t)` sums the envelopes; plate.js multiplies the sky around the strike, the far land and mist, the porch near the opening (`flash.png`) and the room; rain drops (× 1 + 2.5 flash), leaves and the boat brighten too.
- **Thunder:** `thunder.t = t + delay`, delay 2–6 s (distance = delay × 343 m); farther strikes are dimmer (`power`) and quieter (`thunder.gain` 0.55–1). The audio's N-wave thunder starts at `thunder.t` with a 0.4 s soft onset; the cat's ears flick 0.35–0.9 s after most near thunder.

## Procedure: weather on a new plate

1. **Mask first.** Set `outdoor_disp`, `only_outdoor` and `qa_regions` (plate-scene measurement checklist). `rain_qa.py --leak` must report exactly 0 outside the mask and in every region before any look tuning.
2. **Start from Treetop's values** (the scene template) and look at a 10 s preview plus 1:1 crops of near, mid and far rain, against dark and bright backgrounds.
3. **Runoff:** streams from roof edges into open sky columns, drips at vine ends ([fields](./references/rain-options.md#runoff-sources-runoff--runoffparams)). Check placement with `still ... --params only=runoff,debug=rain`. Pin the look with `runoffLook` once it's approved.
4. **Profile per band** (below) and fix the bands that stand out.
5. **Calibrate** against footage if you have a reference clip (below).
6. **Lightning:** keep the defaults unless the plate is unusually bright or dark; tune `plateLayer({ lightning })` and `flashGain`, then `--flash`.
7. **Sync:** `node src/cli.mjs preview scenes/<scene> --event lightning:0 --seconds 24` (starts 6 s before the strike); watch and listen.
8. **QA** (below), then record the values and numbers in `docs/DECISIONS.md`.

## Tuning by symptom

| Symptom | Knobs (`rainLayer` unless noted) |
|---|---|
| Too heavy overall | `count`, `alphaRef`, `clumps.amount` |
| Drops look big or thick | `dropRange`, `dropLambda` (higher = finer), `minWidth`, `coc` |
| One side or band too visible | usually a dark background behind bright drops: raise `envMix` (local light), lower `skyGain`, lower `warmGain` or `warmNear` (lantern glints); measure with `--profile` |
| No slow far layer / speeds too uniform | `farBoost`, far end of `depth`, `depthPower` |
| Near rain dominates | raise the near end of `depth` (Treetop moved it 1.8 → 2.4 m), lower `depthPower` |
| Too uniform | `clumps.strength`, `clumps.cycles`, `clumps.across` |
| Streaks too long or short | `shutter` |
| Too vertical or too slanted | `wind.mean`, `wind.gust`, `wind.turb`. First check it is the rain: render `--params only=rain` and `ground=off` and diff the stills. On the ramen alley the slanted dashes were the ground rings' splash crowns, sized in ground units and sheared by perspective near the frame's edges (fixed 2026-10-18: crowns are round on screen at the projected impact point) |
| Rain rings on walls or step risers | plate_prep `flat_surface` keeps the wet-ground mask on level surfaces only (depth must grow down the screen like a floor's); check `tools/weather_audit.py <scene>` (red = upright surface still marked wet) |
| Streams too solid or too broken | the source's `rate`, `flow`, `burst`, `d`; `runoffGain` |
| Streams changed while tuning rain | pin `runoffLook` |
| Rain drifts too little over the hours | `events.weather.rainAmp`, `windAmp` |
| Lightning too strong indoors | `plateLayer({ lightning: { roomNear, roomAmbient } })`, `flashGain` |

Try values without editing code: `--params rain.alphaRef=0.35,rain.depth=2.4:30` on `still`/`preview` (top-level options only).

## Visibility per vertical band

`.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --profile [--params rain.envMix=0.9]` renders falling rain only (`only=falling`) and no rain (`rain=off`) on 8 frames and reports, for 8 vertical bands across the opening: mean visible energy, streaks per frame, streak length p50/p90 and width. There is no per-band knob: bands differ because of what is behind the rain and how it is lit. Rain v3 had the most visible rain at the sides (≈12 vs ≈6 at the center) because uniformly bright drops sat in front of the darkest forest; lighting drops from `env.png` (`envMix` 0.85) and shrinking lantern glints cut visible rain per band by 47–67 % (far right 11.4 → 3.7, center 5.8 → 2.8). `--params` here applies to the falling-rain render only.

## Calibrating against reference footage

1. Use a locked-camera clip (a screen recording is fine; it stays an internal reference, never an asset). Extract ~4–8 s of frames at about 1000 px width: `ffmpeg -i <clip.mp4> -t 6 -vf scale=1000:-2 out\ref\<name>\frames\f_%04d.png`. `rain_analyze.py` loads every frame into memory and needs more than 60 frames.
2. `.venv\Scripts\python tools\rain_analyze.py out\ref\<name>\frames out\ref\<name>\analysis` separates rain from the static background (temporal median) and writes `stats.json` (streaks per frame, length/width/angle/peak-luminance percentiles, tracked drop speeds, rain area), `rain_energy.png` and `rain_layer_*.png`. Check the rain layers: camera motion or flicker breaks the separation.
3. Commit the small stats file as `docs/reference/<name>-rain-stats.json` (Treetop: `docs/reference/treehouse-rain-stats.json`).
4. `.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --calibrate docs/reference/<name>-rain-stats.json` renders 6 s from frame 300, scales it to the reference width, runs the same analysis and prints reference vs ours; rows within 25 % get "ok" (angles are not judged). `--params rain.<opt>=<v>` applies here too (since 2026-10-15), so you can try values before editing the scene.
5. Streaks per area: `count`, clumps. Length: `shutter`, sizes, depth. Width: `minWidth`, `coc`. Peak luminance: `alphaRef`, `skyGain`, `envMix`. Speed spread: `depth`, `depthPower`, `farBoost`. Angle: wind.
6. The numbers are a starting point, not the goal: after v3 matched the reference within ~25 %, the user asked for finer, lighter background rain (v3.1: length p90 13 vs 23 px at 986 px, 27 % fewer streaks per rain area). Follow the user's taste and record it.

## Lightning safety and thunder sync

- Schedule (`events.lightning`): strikes come in clusters (passing storm cells) of `cluster` [min, max] strikes `withinCluster` s apart, then `minGap` plus a Gamma-distributed quiet spell capped at `maxGap`; the count is calibrated per seed to exactly `perHour` × hours; `startAfter`/`endBefore` keep the edges clear; `delay` sets the thunder range; `brightness` scales the flash. At the CP4 review Treetop had `perHour: 2` (18 strikes in 10 h for seed 11). The user found that far too rare (at least twice as often, maybe more), so timeline v4 uses `perHour: 6`, `cluster: [1, 4]`, `withinCluster: [50, 180]`, `maxGap: 1800`: 60 strikes, longest gap 32 min, WCAG still 0 flashes/s. Storm swells (`stormRain` 0.2, `stormWind` 0.32, `stormHalfWidth` 420 s) are relative to the mean, so frequent storms don't raise the average rain or loudness.
- **Distant lightning** (`events.farflash`, v5): the user then wanted quiet lightning about every 2 minutes, only to liven up the background. Don't do that with storm strikes: 30 loud thunders an hour with rain swells and cat reactions is a storm, not a study ambience. Add a tier of distant flashes instead:
  - **Rate and look:** 24/h on top of the 6 storm strikes. A wide, soft glow in the cloud bank behind the mountains (`plate.js` `farFlash`: sky mask, a little far mist, a faint river reflection; no porch light), power 0.45–0.85, 1–3 pulses ≥ 0.25 s apart.
  - **Sound:** a deep rumble 3–5 s later. Physically 8–20 s at 3–7 km, but the user found that too long.
  - Details in ambient-events and ambience-audio. WCAG swing ≤ 0.017 (the flash check includes the 2 strongest distant flashes).
- Gust flurries (ambient-events `flurry`): `rain.js` adds the flurry wind (`uFlurry`, GLSL `flurryW`/`flurryInt`) to every drop's drift and slant and to the runoff release, `plate.js` sways and leans the vines and sends a rougher ripple patch across the water, `leaves.js` pushes leaves; the audio swells the wind layer. A gust of 1–2 m/s over 5–8 s reads as weather, not an effect.
- Calm water (`plateLayer` `water: { camera, flow, sway, rough }`, v5): world-space ripples on the water plane through the lake camera, drifting downstream, swaying the painted reflections (up to 18 px vertically at 4K, sideways scaled by the grazing angle), seamless in the loop and anti-aliased. The user asked for very calm ripples, then more after the first preview: Treetop `sway: [9, 18]`, `rough: 18`. Without `water` the plate falls back to the old screen-space shimmer (`ripple`).
- `.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --flash` renders 4 s around the 4 strikes with the most strokes (960×540), takes the quarter-frame window with the largest brightening, converts to relative luminance and counts WCAG 2.3.1 transitions (opposing changes ≥ 0.1 with the darker state < 0.8). Pass: ≤ 3 flashes in any 1 s. Treetop: peak swing +0.08, so 0 flashes even for 3-stroke strikes. Keep strokes merged into one swell and the swing under 0.1.
- Sync measured on Treetop: flash at 6.03 s vs 6.00 expected; thunder energy onset 8.85 s vs 8.67 s plus the 0.4 s fade-in. Thunder must never land on the flash: keep `delay` ≥ 2 s.
- Loudness: thunder sits +1.2 to +4.5 dB over the bed (short-term, nearer = louder), limit 6 dB; checked by `tools/audio.py --report` and the master render's `qa.md`. At 6 strikes/h the densest 10 min of Treetop v4 (4 strikes) measured +1.5 to +2.5 dB, true peak −4.3 dBTP.

## QA (must pass before showing anything)

```powershell
.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --leak --seam --flash [--frames 0,900,<boat frame>]
```

| Check | Pass |
|---|---|
| `--leak` | rain-only coverage frames (`debug=rain`, bloom off, plate black) have exactly 0 energy outside the outdoors mask and in every `qa_regions` box (values ≤ 1.5/255 are output dither); writes `out/<scene>/qa/leak_overlay.png`. Default frames are in the first loop: add frames during a boat trip with `--frames` |
| `--seam` | base loop (`events=off`): frame 0 == frame loop end, the change across the seam matches the change elsewhere, a frame renders identically twice; full timeline: a frame rendered alone == the same frame rendered in a sequence |
| `--flash` | ≤ 3 WCAG flashes per second around lightning |
| `--profile`, `--calibrate` | reports only; compare with the previous version and the reference |

Exit code 1 if leak, seam or flash fails. Outputs go to `out/<scene>/qa/`.

## Hard-won lessons

1. **Outdoors comes from depth, never from hand-painted polygons over solid objects.** Hand-drawn outdoor areas once covered the cat, deck and ceiling, so it rained on the cat and through the roof. Clip with `only_outdoor`, cut with `not_outdoor`, guard with `qa_regions`. Cut the object's own outline, never a box around it: the gaps between a stool's legs or a railing's balusters must keep their rain and rings (Treetop 2026-10-16, ramen 2026-10-19; `weather_audit.py` dry pockets).
2. **Light rain from its local surroundings.** Drops refract a wide view of their environment, so they are dim in front of a dark forest and bright against misty sky (`env.png`, `envMix`). Uniformly bright drops looked too heavy on the dark side.
3. **Pin what the user approved.** `runoffLook` gives the streams their own width floor, glint and env mix, so later falling-rain tuning can't change them.
4. **Physical, not geometric.** Streak length = speed × shutter, terminal velocity per size, opacity from exposure, "over" toward the drop's radiance. Rain v2 (full-screen shader layers) was rejected twice: it moved like vectors, and rain came through the ceiling.
5. **Pure function of absolute time.** `t = frame / fps`; periodic parts use `phase = (t mod L) / L`; slow drift is sampled from the weather track at absolute t; nothing is carried from frame to frame. That makes random access, 5 min segments and determinism work.
6. **Integer cycles per loop for everything periodic:** drop re-entries, bead counts, gust cycles, clump cycles, cells and drift. Then frame `loop end` equals frame 0 exactly.
7. **Screen-space instanced quads with y down can flip the triangle winding:** use `side: THREE.DoubleSide` (the leaves were invisible until then). Also set `frustumCulled = false` and an explicit `renderOrder` on every instanced mesh (three computes bounds lazily on the first frame, which made output depend on the start frame).
8. **Remove painted rain from the key art** (`plate_prep.py` de-rain): static streaks look frozen under animated rain. Protect waterfalls with `not_derain`.
9. **Stock "greenscreen" rain doesn't work here:** it ignores depth (rains on the pet), seams over 10 h and doesn't match the plate's light.
10. **Streams need open sky columns.** A stream behind a vine or lantern gets cut by the mask and looks wrong.
11. **Lightning is its own light signal** (`flashAt`, added on top of the plate and every layer), at a new position per strike, one soft swell per strike; the threejs-weather skill's discrete strokes and `Math.random`/`setTimeout` were replaced by seeded, frame-timed envelopes.

## Gotchas

- `--params rain.<opt>=<v>` reaches top-level options only; `rain_qa.py --params` affects `--profile` and `--calibrate` (not `--leak`, `--seam` or `--flash`, which must test the scene as written).
- The order of `runoff` sources seeds their flow (and the audio's splashes): append, don't insert.
- Only sources with `rate` ≥ 10 get splash sounds; drips are covered by the audio's own seeded drip layer.
- `flowAt`/sway cycle counts and plate.js rates are per loop and tuned for a 120 s loop.
- GPU cost follows the pool (`count × max track rain`), not the visible count.
- `only=runoff` keeps one placeholder falling drop (`count: 1`).
