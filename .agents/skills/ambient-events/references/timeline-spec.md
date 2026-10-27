# Timeline spec and output

`buildTimeline(spec, { seed, duration, fps, plate })` in `src/library/timeline/build.js` (exported through `src/library/timeline.js`) reads the scene's `events` object. Defaults below were checked against the code on 2026-10-15 (timeline version 4); if a number matters, re-read the function named in each heading. New event types are documented by whoever adds them (see the event catalog in [../SKILL.md](../SKILL.md)).

## `events.lightning` (`buildTimeline`, `strike`)

| Key | Default | Meaning |
|---|---|---|
| `perHour` | required (> 0 to enable) | long-run strikes per hour |
| `cluster` | [1, 3] | strikes per cluster (a passing storm cell), uniform integer |
| `withinCluster` | [80, 300] | s between strikes of a cluster |
| `minGap` | 120 | s after a cluster before the quiet spell |
| `maxGap` | 4200 | cap on a quiet spell (s); quiet spells are Gamma(2)-distributed |
| `startAfter` / `endBefore` | 240 / 45 | s kept clear at the start / end of the video |
| `delay` | [2, 6] | thunder delay range (s); distance = delay × 343 m; the low end is "near" |
| `brightness` | 1 | flash power multiplier |

Per strike: `power` = (0.5 + 0.5·near) × U(0.85, 1.1) × brightness; `strokes` [[offset s, amplitude], ...] = 1 stroke, a 2nd in 60 % of strikes (0.12–0.2 s, 0.4–0.65), a 3rd in 35 % of those (+0.14–0.24 s, 0.2–0.4); glow center `x` 0.26–0.74, `y` 0.04–0.2 (image coords); `thunder` { `t`, `delay`, `distance_m`, `gain` 0.55–1 (near = louder), `seed` }.

Rate calibration (`calibrated(gen, target)`): the generator takes a spacing scale `k` that multiplies the quiet spells; a deterministic bisection on `k` finds the schedule whose strike count is exactly `round(perHour × (end − startAfter) / 3600)`. Every seed gets the configured rate. Ambient streams use the same function.

`events.strikeBusy` = [45, 45]: spotlight events keep clear of `[t − 45, thunder.t + 45]` around each strike, but can fall between the strikes of a cluster. Treetop (v4): `{ perHour: 6, cluster: [1, 4], withinCluster: [50, 180], minGap: 90, maxGap: 1800, startAfter: 150, delay: [2, 6] }` → 60 strikes in 10 h, longest gap 32 min; within-cluster spacing ≥ 50 s keeps the WCAG flash check far from its limit.

## `events.weather` (`weatherTrack`)

| Key | Default | Meaning |
|---|---|---|
| `dt` | 5 | sample spacing (s) |
| `rainAmp` / `windAmp` | 1 / 1 | amplitude of the smooth seeded noise (rain: 25 and 7 min knots; wind: 15 and 5 min) |
| `stormRain` / `stormWind` | 0.22 / 0.35 | swell around each lightning strike (raised cosine), relative to the mean level |
| `stormHalfWidth` | 600 | s each side of a strike that the swell reaches |
| `streamLag` | 90 | s time constant of `streams` following `rain` (the roof fills) |

Output `track = { dt, rain[], streams[], wind[] }`; rain clamped to 0.7–1.35, wind to 0.5–1.7. Read with `trackAt(track, key, t)` (linear, like the shaders' 1D texture and the audio's `np.interp`).

## `events.leaves` (`leafSchedule`)

| Key | Default | Meaning |
|---|---|---|
| `perMinute` | 2.5 | base rate; thinned/boosted by the gust strength at x 0.45 |
| `gustBoost` | 1.2 | how much gusts raise the rate |
| `depth` | [2.4, 7] | m from the camera (more near leaves) |
| `size` | [0.06, 0.11] | leaf size (m) |
| `x` | [0.03, 0.83] | spawn columns (normalized) |
| `wind` | calm | `{ mean, gust, gustCycles, fronts, loop }`: the scene's wind plus the loop length |
| `focalPx` / `height` | 2700 / 2160 | camera focal length and frame height (px) for the flight duration |
| `palette` | [2, 5] | index range into `plate.json` `foliage_palette` |
| `startAfter` | 5 | s |

Each leaf stores everything its flight needs (`t`, `x`, `z`, `s`, `shape`, `c`, `vt` terminal speed 0.5–0.95 m/s, sway `A`/`f`/`ph`, tilt `B`, `spin`, flutter `fl`/`fm`, `th0`, `dur`). All parameters are drawn whether or not a leaf is accepted, so rate changes don't reshuffle the leaves. Each flurry adds its `leaves` burst (spawned between 15 % and 65 % of the gust) from a stream keyed by the flurry's `seed` and `'flurry-leaves'`. `leaves.js` draws at most 24 at once.

## `events.lights` (`lightSchedule`, `lightLevel`)

| Key | Default | Meaning |
|---|---|---|
| `offFrom` / `offTo` | 0.55 / 0.97 × duration | window in which each switchable window goes dark (s) |
| `stayOn` | 0.25 | share that stays lit all night |
| `revisit` | 0.15 | share that comes back on for 3–13 min, 10–50 min later |

Applies to `plate.json` light groups of kind `window` that are not `reflective`. Output `lights = [{ id, off: [[tOff, tOn | null], ...] }]`; switches fade over 0.6 s (`lightLevel`'s fixed `fade`; the comment's `fade` key is not read).

## `events.windows` (`windowSchedule`, `windowDip`): window presence

| Key | Default | Meaning |
|---|---|---|
| `pass` | 4 | per hour: someone walks past (dip of 60–85 % over 1.6–3.2 s, sin²) |
| `dim` | 2 | per hour: a lamp turned down or a curtain drawn (45–70 % for 25–90 s, 2 s fades) |
| `away` | 1.5 | per hour: the room goes dark for 120–420 s (0.7 s switches) |
| `minGap` | 45 | s between window changes (scene-wide) |
| `minSize` | 10 | px across (4K): smaller windows are too small to read a change |

Candidates are Poisson per kind from 60 s; accepted in time order on a random free window (lit by the night schedule for the whole event, not used in the last event + 60 s). Output `windows = [{ id, kind, t, dur, depth }]` sorted by `t`; `lightLevels` takes `min(night level, 1 − windowDip)` per light. Accepted counts are a little under the rates (no calibration; Treetop 3.5 / 2.1 / 1.2 per hour).

## Rare events: `events.lantern`, `events.boat`, `events.heron` (`rareEvents`)

| Key | Default | Meaning |
|---|---|---|
| `perHour` | 1 | long-run rate |
| `dur` | [3, 4] | event length (s); boat trips use [110, 150]; a heron's follows from its distance and speed |
| `startAfter` | 300 | s before the first candidate |
| `oversample` | 8 | candidate rate multiplier |
| `cooldown` | lantern 1200, boat 1800, heron 2700 | min s from one event's end to the next of the same type |
| `route` (boat) | — | `{ camera, path, fade }`, shared with `boatLayer`, fish, heron and the audio profile |
| `distance` / `altitude` / `speed` (heron) | [160, 280] m / [22, 42] m / [8, 10.5] m/s | crossing distance from the camera, height over the water, airspeed. At the defaults the bird is a few px over dark forest; Treetop v5 uses [60, 78] m with `screenY` |
| `screenY` + `camera` (heron) | — | instead of `altitude`: image rows [y0, y1] (0..1, y down) the bird should cross, and the lake camera `{ horizon, height }`; the altitude is solved per event so it flies in front of a bright band (Treetop [0.13, 0.18]) |
| `sink` / `glide` (heron) | [−4, 3] m / [0.15, 0.35] | climb or descent over the crossing; share of time gliding (Treetop: [−1, 1] and [0, 0], always flapping) |
| `focalPx` (heron) | 2700 | lake-camera focal length; the crossing spans the frame plus 15 m each side |
| `events.rareGap` | 120 | s kept clear before and after every rare event (Treetop v5: 45) |

Scheduler: Poisson candidates per type; a greedy pass in time order accepts a candidate when its type is under its rate credit (`count < perHour × (t − startAfter) / 3600 + 1`), past its cooldown, and `[t − rareGap, t + dur + rareGap]` overlaps no busy window (each lightning strike, see `strikeBusy`, and every accepted rare event). So rare events never overlap, never come back to back, converge to their rates without bunching, and stay clear of lightning. Lantern candidates pick a random lantern group (`light`, `x`) and store their `dips`; boats get `dir` (±1, 75 % alternate with the previous boat) and `lane`; herons get `dir`, `dist`, `alt`, `speed`, `sink` (a gentle climb or descent, m), `flapHz` 1.9–2.4, `glide` share (from `glide`, default 0.15–0.35) and `phase`.

## Ambient streams: `events.fish`, `events.flurry`, `events.farflash` (`ambientEvents`)

Gamma(2) spacing above `minGap` (capped at 0.8 × the mean spacing), from `startAfter` (120) to `endBefore` (30) s before the end, count calibrated to `perHour` like lightning. Own streams keyed `'fish'`, `'flurry'` and `'farflash'`.

| Key | Default | Meaning |
|---|---|---|
| `fish.perHour` / `minGap` | required / 0 | rises per hour (Treetop v5: 20 / 60 s) |
| `fish.zones` | required | `[[x0, y0, x1, y1, weight], ...]` open-water boxes (image coords); each rise: `x`, `y`, `size` 0.8–1.4, `dur` 6–8 s |
| `fish.jump` | 0.35 | share of rises with a visible jump (Treetop v5: 0.7) |
| `flurry.perHour` / `minGap` | required / 0 | gusts per hour (Treetop 3 / 420 s) |
| `flurry.dur` / `amp` | [5, 8] s / [1, 2] m/s | gust length and peak wind (raised cosine) |
| `flurry.leaves` | [4, 9] | leaves shaken loose per gust |
| `flurry.prevailing` | 1 | sign of 80 % of the gusts (the rest blow the other way) |
| `farflash.perHour` / `minGap` | required / 0 | distant flashes per hour (Treetop v5: 24 / 35 s, plus 6 storm strikes = ~30 flashes/h) |
| `farflash.delay` | [8, 20] s | flash to rumble; realistic for 3–7 km, but the user wanted it sooner: Treetop [3, 5] |
| `farflash.power` | [0.2, 0.45] | flash strength (storm strikes ~0.5–1.1); Treetop [0.45, 0.85] |
| `farflash.x` / `y` | [0.12, 0.8] / [0.14, 0.28] | glow center (image coords); keep it over the sky behind the peaks (Treetop x [0.2, 0.62], y [0.12, 0.25]) |
| `farflash.clear` | 20 | s kept clear of every storm strike's flash and thunder |

Each distant flash has 1–3 pulses ≥ 0.25 s apart (`strokes`) and `thunder` { `t`, `delay`, `distance_m`, `gain` 0..1 (the rumble's place in `far_thunder.over_bed_db`), `seed` }. `flashAt(tl, t)` returns storm light in `flash`/`x`/`y` and distant light in `far`/`fx`/`fy`. Distant flashes don't swell the weather, make the pet react, or block spotlight events.

Fish rises within 30 s of a boat trip are dropped. Flurry helpers: `flurryWind(tl, t)` (m/s), `flurryInt(ev, s)` (exact integral, m), `flurryDrift(tl, t0, t1)` (leaves), `flurryUniform(tl, t)` → `[t − start, dur, amp]` for shaders, `flurryEnv(tl, t)` (0..1 for sway and audio).

## `events.pet` (`petSchedule`, `petState`)

| Key | Default | Meaning |
|---|---|---|
| `ear` / `tail` / `sigh` | 8 / 5 / 3 | per hour (Poisson each, from 60 s) |
| `thunderEar` | 0.75 | chance of an ear flick 0.35–0.9 s after thunder with `gain` ≥ 0.6 |
| `minGap` | 25 | s between motions (1 s for thunder reactions) |

Durations: ear 0.6–0.9 s (25 % both ears, 35 % a second smaller flick), tail 1.0–1.5 s, sigh 4.0–5.5 s; `amp` 0.75–1.15 (thunder reactions 1.0–1.25). `petState(tl, t)` returns `{ earA, earB, tail, breath }` for plate.js.

## Output

`buildTimeline` returns `{ version: 4, seed, duration, fps, events, track, leaves, lights, windows, pet }`; `events` (lightning, rare and ambient types) is sorted by `t`, with `id` = index and `frame` = round(t × fps). `node src/cli.mjs timeline scenes/<scene>` (also `preview` and `render`) writes it to JSON with `scene`, `title`, `loopSeconds`, `weather` (`wind`, normalized `runoff` from `runoffParams`) and `audio`, and adds per-event audio data computed with the renderer's own code (boat events get `profile = { dt, dist, pan, speed, vis }` from `boatProfile`; fish rises get `dist` (m, lake camera) and `pan`).

Seeded streams: every subsystem has its own `mulberry32` stream keyed by the seed and a name (`'lightning'`, `'rare'`, `'rare-dir'`, `'fish'`, `'flurry'`, `'farflash'`, `'weather'`, `'leaves'`, `'flurry-leaves'`, `'nightlights'`, `'windows'`, `'pet'`), so adding a subsystem doesn't reshuffle the others. Rare types share the `'rare'` stream in the order of the `types` list: append new types at the end.
