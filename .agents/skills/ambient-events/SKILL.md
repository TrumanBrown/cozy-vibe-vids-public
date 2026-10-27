---
name: ambient-events
description: 'Seeded event timeline for plate scenes and how to add new event types: src/library/timeline/ buildTimeline (storm lightning clusters calibrated to a rate, distant lightning flashes, weather track, falling leaves, night lights, window presence, lantern dips, pet micro-motions, rare spotlight events such as boat, heron and lantern gutter with rate credit, cooldowns and busy windows, ambient streams such as fish rises, gust flurries and distant flashes), the v5 event-density baseline (alive but calm enough to study to), how layers read ctx.timeline (src/engine/engine.js, plate.js uniforms, rain.js, leaves.js, boat.js, fish.js, heron.js), event-layer patterns (screen-box quad, sub-sample anti-aliasing, outdoor and water mask occlusion, haze as airlight, lake-camera projection), switchable lights (lightid/lightw shares), audio hooks in tools/cozy/audio event_waves, previews with --event type:n, and QA. Use when: adding a new event type or rare event, changing event rates, cooldowns or spacing, making events more or less frequent, debugging why an event does or does not appear, previewing an event, checking events per hour, windows or lanterns switching with artifacts, an animal or object that is too small or moves too mechanically, or reviewing viewer-comfort and motion-realism rules before animating anything.'
argument-hint: 'event and scene, e.g. "owl landing on the railing in scenes/treetop-plate"'
---

# Ambient events: the seeded timeline

Everything that changes over the 10 hours comes from one timeline: `buildTimeline(spec, { seed, duration, fps, plate })` in `src/library/timeline/build.js` (one module per generator in that folder; `timeline.js` re-exports them), a pure function of the scene's `events` object, the seed and the video length. It always spans the whole video, so a preview at time t shows exactly what the master shows at t, and the renderer and the audio see the same events. Layers never keep state between frames: they look up the timeline at absolute time `t = frame / fps`.

## Who builds and reads it

- **Renderer:** `src/engine/engine.js` builds the timeline itself (fetching `out/plates/<plate>/plate.json` for the light groups) unless `--params events=off`, and passes it to the scene as `ctx.timeline`. `--duration` gives a test video its own timeline.
- **Audio:** `node src/cli.mjs timeline scenes/<scene>` (also run by `preview` and `render`) writes the same timeline to `out/<scene>/timeline.json` plus `weather`, `audio`, `loopSeconds` and per-event audio data (boat `profile`). `tools/audio.py` reads that file.
- **Layers** (in `ctx.animate((t) => ...)`):
  - `plate.js`: `flashAt` (lightning light; `.far`, `.fx`, `.fy` for distant flashes in the cloud bank), `trackAt(track, 'rain')` (rain rings, mist), `lightLevels(tl, t, 64)` → `uLevel[64]` (night lights, window presence and lantern dips; each light removes only its own share of the lights-off delta, see "Switchable lights" below), `petState` → ear rotation, tail lift, breath, `flurryEnv`/`flurryWind` → vines sway and lean in gusts, `flurryUniform` → the gust patch on the water.
  - `rain.js`: the weather track as a 1D texture sampled at absolute time, `trackAt(track, 'wind')` for gusts, `flurryUniform` → the flurry gust in GLSL (`flurryW`/`flurryInt`: drop drift, slant and runoff release), `flashAt` for drop brightness.
  - `leaves.js`: binary search over `tl.leaves` (sorted by `t`), up to 24 active leaves, each a pure function of time; `flurryDrift` pushes them in gusts.
  - `boat.js`: the active `boat` event, `boatPose` on the route, `flashAt`.
  - `fish.js`: active `fish` events (rings, splash crown, droplets, the odd jump) projected through the lake camera.
  - `heron.js`: the active `heron` event (`heronPose`), airlight haze and depth occlusion.

Spec keys, defaults and output fields: [references/timeline-spec.md](./references/timeline-spec.md).

## Scheduling rules (existing types)

- **Lightning:** clusters of `cluster` strikes (default 1–3; a passing storm cell), then a Gamma(2) quiet spell with a cap. The count is calibrated per seed (`calibrated()`: deterministic bisection on a spacing scale), so a 10 h video at `perHour: 6` has exactly 60 strikes, whatever the seed. Each strike: power, 1–3 strokes merged into one soft envelope, glow position, and `thunder` (`t` = flash + distance / 343 m/s, `gain`, `seed`).
- **Rare (spotlight) events** (`lantern`, `boat`, `heron`): oversampled Poisson candidates per type; a greedy pass accepts a candidate only if its type is under its rate credit (`count < perHour × (t − startAfter)/3600 + 1`), past its cooldown (defaults lantern 1200 s, boat 1800 s, heron 2700 s; `cooldown` overrides), and clear of every busy window, padded by `rareGap` (120 s). Busy windows: each lightning strike from 45 s before the flash to 45 s after its thunder (`events.strikeBusy`), and every accepted rare event. One spotlight event at a time, never back to back, never during a strike, but they can fall between the strikes of a passing storm. Consecutive boats alternate direction 75 % of the time.
- **Ambient streams** (`fish`, `flurry`, `farflash`, in `tl.events`): frequent small events that may overlap spotlight ones. Gamma(2) spacing above `minGap`, count calibrated to `perHour` like lightning. Fish rises are dropped while a boat is out (±30 s): its wake owns the water. Distant flashes are dropped within `clear` s (20) of a storm strike's flash or thunder.
- **Window presence** (`tl.windows`): `pass` (someone walks past: a 1.6–3.2 s dip of 60–85 %), `dim` (a lamp turned down for 25–90 s) and `away` (the room goes dark for 2–7 min) per hour, on lit, non-reflective windows at least `minSize` px across, one change at a time, `minGap` s apart, a window rests 60 s after its event, never on a window the night schedule has switched off.
- **Pet micro-motions** (`tl.pet`): Poisson ear flicks, tail twitches and sighs at their own rates, `minGap` apart, plus an ear flick 0.35–0.9 s after most near thunder.
- **Leaves** (`tl.leaves`): a Poisson stream thickened by the gusts (gusts shake leaves loose), plus a burst of `leaves` per flurry from its own stream (`'flurry-leaves'`).
- **Night lights** (`tl.lights`): each switchable window goes dark once between `offFrom` and `offTo`; some stay on, some come back on for a few minutes.
- **Weather drift** (`tl.track`): slow rain, streams and wind multipliers with storm swells around strikes (plate-weather skill).

Every subsystem draws from its own seeded stream (`mulberry32` keyed by seed and a name), so adding one doesn't reshuffle the others. Rare types share one stream in list order: append new types at the end. Expect existing rare events to move when you add a type: they compete for the same free time.

At the CP4 review (seed 11, 10 h) Treetop had 18 strikes, 8 lantern gutters, 7 boats, 148 pet motions and 2057 leaves. The user asked for more frequent events (lightning at least twice as often; more animation makes it feel human, but still calm). Timeline v4 (2026-10-15, seed 11, 10 h) has 60 strikes (longest gap 32 min), 40 fish rises, 30 flurries, 15 lantern gutters, 13 boats, 6 herons, 68 window changes (35 pass, 21 dim, 12 away), 228 pet motions and 2156 leaves. That is about 6 lightning strikes and 25 noticeable events an hour, aiming for "alive but calm".

The user then asked for far more, but never chaotic: someone should be able to study to it. **Timeline v5 (2026-10-16) is the current baseline for new scenes.** Seed 11, 10 h:

| Event | Count | Per hour |
|---|---|---|
| storm strikes | 60 | 6 |
| distant flashes | 239 | 24 |
| fish rises | 199 | 20 (2/3 jump) |
| boats | 39 | 4 |
| herons | 31 | 3 |
| flurries | 30 | 3 |
| lantern gutters | 16 | 1.6 |
| window changes | 68 | 7 |
| cat motions | 342 | 34 |
| leaves | 3109 | 311 |

In total about 60 events an hour, so something happens every 30–40 s, mostly small, with the spotlight events still one at a time. The user approved the previews at these rates.

**Strong opening (user 2026-10-16, for every new video):** the start is when people look hardest and want to see every detail, so it is heavier on animation and gets to the music quickly, with less lead-up.
- In Treetop's looped hour, the first 6 minutes had only 2 fish rises and 2 distant flashes; the first strike came at 6:39 and the boat at 13:47. Viewers who opened the video saw almost nothing happen.
- **This video:** `tools/loop_master.py --offset 5m` starts it 5 minutes into the hour, which needs no rendering. The storm cell then lands at 1:39–5:13, a gust at 7:05 and the boat at 8:47.
- **Next scene:**
  - Pick the test hour and the `--offset` so the video opens on a busy stretch. Read the event list of `node src/cli.mjs timeline` and choose the hour start with the richest first 5 minutes: a storm cell, a spotlight event (boat or heron), fish jumps and a gust.
  - Better still, add an opening showcase to `buildTimeline`: within the first ~3 minutes, schedule one storm strike (or a distant flash), one spotlight event, a fish jump, a gust with leaves and a cat motion, then fall back to the normal rates. For a looped upload, it goes at the start of the test hour.
  - Not built yet. Preview it and keep the comfort rules: one spotlight event at a time, and no strike in the first ~20 s.
- Music comes in within seconds too (`opener_lead`, ambience-audio skill).

## Event catalog

**Where the numbers come from in a new scene (2026-10-21):** the analysis drafts rain, birds, a critter, fire, neon and the storm; `tools/plate_features.py` places what the plate offers (perches on wires and crossarms, the moth's lamp, chimney smoke, the petal tree, fish zones and their lake camera, more critter paths, the ant when it is the signature) and judges its own placements; `tools/autopilot.py` setup raises every rate to at least `config/defaults.json` (the ramen alley's approved density). Tune a scene's own `events` only for that video; change defaults.json when Truman asks for more or less of something in general.

| Type (timeline field) | Picture (module) | Rate keys (`events.*`) | Audio (`tools/audio.py`) |
|---|---|---|---|
| `lightning` (`events`) | strike envelope → `flashAt` in `plate.js` (sky, land, porch via `flash.png`), `rain.js`, `leaves.js`, `boat.js` | `lightning.perHour`, `cluster`, `withinCluster`, `minGap`, `maxGap`, `delay`, `first` (2026-10-18: the first strike within that many seconds after `startAfter`; without it the draw order is unchanged). Ramen (2026-10-19, a little more often): 18 an hour, clusters of 3-4, 35-100 s apart within a cluster, quiet spells capped at 900 s | thunder N-waves at `thunder.t` (`thunder` stem); level `audio.thunder.over_bed_db` (default [1.2, 4.5]; ramen [2.0, 5.5] with `peak_dbfs` -6, a little louder); cat ear flick via `pet.thunderEar` |
| `lantern` (`events`, rare) | `lanternDips` → `lightLevels` → `plate.js` `uLevel` (removes the lantern's share of the lights-off delta) | `lantern.perHour`, `dur`, `cooldown`; needs `lantern` light groups | flame flutter `gutter()` shaped like the dips (`events` stem) |
| `boat` (`events`, rare) | `boat.js` `boatLayer`: ray-marched skiff on `boat.route`, reflection, wake, glitter | `boat.perHour`, `dur`, `cooldown`, `startAfter`, `route` | hull wash `boat_wash()` along its `profile`, wake laps `wake_laps()` 18–30 s after closest approach (`events`) |
| `ear`, `tail`, `sigh` (`pet`) | `petState` → `plate.js` warps (`petRig`, breathing ellipse) | `pet.ear`, `pet.tail`, `pet.sigh` (per hour), `minGap` | none |
| falling leaf (`leaves`) | `leaves.js` `leavesLayer` | `leaves.perMinute`, `gustBoost` | none (leaf rustle is part of the wind layer) |
| window going dark (`lights`) | `lightLevels` → `plate.js` `uLevel` | `lights.offFrom`, `offTo`, `stayOn`, `revisit`; needs non-reflective `window` groups | none |
| weather drift (`track`) | `rain.js` (density, runoff flow, gusts), `plate.js` (`rainK`), `leaves` rate | `weather.rainAmp`, `windAmp`, `stormRain`, `stormWind` | rain, runoff and wind layers follow the same samples |
| creak (audio only) | none: decided per visual gust peak in `creaks()` | `audio.events.creak_wind` (1.15), `creak_p` (0.35) | stick-slip wood creak (`events` stem), ≥ ~70 s apart |
| `heron` (`events`, rare) | `heron.js` `heronLayer`: side-view silhouette, always flapping (glides looked fake: `glide: [0, 0]`), each wingbeat a little different, gently undulating flight line; airlight haze, hidden behind nearer geometry by disparity. Treetop: 60–78 m out (60–80 px wingspan at 4K), height from `screenY` so it crosses the bright misty band | `heron.perHour`, `cooldown`, `startAfter`, `distance`, `altitude` or `screenY` + `camera`, `sink`, `glide`, `speed`, `focalPx` | none (too far to hear over the rain) |
| `farflash` (`events`, ambient) | distant lightning: `flashAt().far` → `plate.js` wide soft glow in the cloud bank (sky mask), a little far mist, faint river reflection; no porch light | `farflash.perHour`, `minGap`, `delay` (Treetop 3–5 s; the user found realistic 8–20 s too long), `power`, `x`, `y`, `clear` | `far_thunder`: deep rumble (≲ 115 Hz, ~9 s, 1.5 s roll-in), mix +0.3 to +1.2 dB over the bed (`thunder` stem) |
| calm water (continuous, not an event) | `plate.js` `opts.water`: world-space ripples through the lake camera drifting downstream, swaying reflections; a rougher patch sweeps across in each flurry | `plateLayer` `water: { camera, flow, sway, rough }` | none |
| `fish` (`events`, ambient) | `fish.js` `fishLayer`: perspective ripple rings, inner glow, splash crown and droplets, a jump in 35 %; water and outdoor masks | `fish.perHour`, `minGap`, `jump`, `zones` ([x0, y0, x1, y1, weight] on open water) | `fish_plop()` attenuated by distance (`dist`, `pan` added by `writeTimeline`), `audio.events.fish_db` |
| `flurry` (`events`, ambient) | raised-cosine gust (`flurryWind`/`flurryInt`): rain slants and drifts (`rain.js`), vines sway and lean (`plate.js`), leaves pushed plus a burst shaken loose (`leaves.js`) | `flurry.perHour`, `minGap`, `dur`, `amp` (m/s), `leaves`, `prevailing` (±1, 80 % of gusts) | wind layer swells, `flurry_whoosh`, `flurry_rustle`, and a creak at strong peaks (`flurry_creak`) |
| window presence (`windows`) | `windowDip` → `lightLevels` → `plate.js` `uLevel` (`pass` / `dim` / `away`) | `windows.pass`, `dim`, `away` (per hour), `minGap`, `minSize` (px) | none |
| waterfall flow (continuous, not an event) | `plate.js`: scrolled noise along `flow.png` (from `waterfall` polygons in the masks json), periodic in the loop | `plateLayer` option `waterfall` (0.22) | none |
| `neon` (ambient, 2026-10-16) | a neon sign region flickers: 2-4 soft dips within ~1 s, >= 0.34 s apart; its reflection on the wet ground dips with it (plate_prep `refl.png`, 2026-10-19) | `events.neon: { perHour, minGap, regions?, depth }` (regions default: every `neon` region) | neon buzz (`events2.neon_db`) |
| `gutter` (ambient) | a candle / lamp / lantern region dips 2-3 times over 2-3.5 s (lantern dips, scaled by `depth`) | `events.gutter: { perHour, minGap, regions?, depth }` | flame flutter (`events2.gutter_db`) |
| `car` (ambient) | traffic.js: headlights or tail lights pass along the road path, light pool, wet-road reflections | `events.car: { perHour, minGap, dur, rightward, headlights }` + a `traffic` layer with `path` | tire hiss on a wet road (`events2.car_db`) |
| `ember` (ambient) | a log settles: a burst of sparks from the fire region (particles.js `embers`) | `events.ember: { perHour, minGap }` | thud + crackles (`events2.ember_db`) |
| `star` (ambient) | a shooting star: a soft streak across the sky (masks.png sky only) | `events.star: { perHour, minGap, box }` + a `particles` layer `mode: stars` | none |
| `train` (spotlight) | traffic.js: a chain of lit windows along the rail path | `events.train: { perHour, dur, cooldown }` + `traffic.train: { path, scale, windows }` | distant rumble and clacks (`events2.train_db`) |
| `birds` (ambient, 2026-10-16) | birds.js: a flock of 1-5 small birds crosses the open sky band, each flapping at its own rate with glides and a bob per beat; hidden behind nearer things (plate disparity `disp`) | `events.birds: { perHour, minGap, band, size: [px, px] wingspan at 4K, count, speed, flap, first }` + a `birds` layer | none (too far to hear over the rain) |
| `critter` (ambient) | critters.js: a sprite creature (tools/critter.py) crawls the layer's `path` from one end to the other over minutes with two pauses; eye stalks sway; a glossy trail lies flat on the surface and dries (`trailLife`: 30 s when it rains on it, 10 min dry), with a flat contact shadow. Several creatures: `events.critter` as a list, entry i played by the critter layer with `track: i` (entry 0 keeps the stream key `critter`, so adding more leaves its events unchanged) | `events.critter: { perHour, dur: [s, s], startAfter, first, forward }` or `[{...}, {...}]` + `critter` layers `{ creature, path, size, sizeEnd, track }` | none |
| `ant` (ambient, 2026-10-18) | ant.js: a 3D ant rendered from the camera's angle walks one of the layer's `paths` (either way) in bursts with 1-3 stops, antennae tapping while it stands; hidden where the plate isn't the surface (a plane fitted to the depth along the paths), so it comes out from behind a cup; at a far edge (found where each path crosses the outdoor mask for an indoor counter, or the depth for a table outdoors) it turns, walks over the corner with its back feet on top and front feet down the far side, and a depth-only block for the surface hides it (2026-10-19: the soft depth edge made it sink into the counter); a path that starts beyond climbs up the same way. Path ends 2-3 body lengths past the edge. Blurred like the surface at its depth (`defocus.png`). With `file` (a share of the visits) 2 or 3 ants come along the same trail one after another (`ev.n`): followers are the leader's walk delayed, each lag the shortest that keeps it 1.9 body lengths behind through the stops, plus a little, each a little smaller with its own gait phase. Ramen: 20 an hour (2026-10-19 round 3, was 12; more often, or more ants) plus 3 in the opening 5 minutes (`intro`), first at ~13 s, `file: 0.45`; the ramen alley's signature detail | `events.ant: { perHour, dur: [s, s], paths (count), startAfter, first, intro, file }` + an `ant` layer `{ paths, size }` | none |
| `petals` (timeline `petals`, 2026-10-19) | petals.js: specks drifting down from the tree's canopy box and across the scene on a light breeze (`drift` m/s along the wind), and near petals blown past the opening that land on the wet ground (camera height `camH`) and lie flat `stay` s; a burst of both in each gust flurry; masked to the outdoors and behind anything nearer than the tree. Ramen: ~45 tree petals and ~3 near ones a minute | `events.petals: { tree: { perMinute, box, fall, drift }, near: { perMinute, depth, x, stay, drift }, flurry: { tree, near }, gustBoost, dir }` (autoscene adds the scene wind) + a `petals` layer `{ tree: region name }` | none |
| `boat` ambient (2026-10-19) | `boat.ambient: true`: boats are everyday traffic instead of a rare spotlight event: one after another with `idle` gaps, never two at once, also during storms; `atStart` puts one on the water at t = 0 (part way along, `u0`). Ramen: 130-170 s passes, 15-70 s gaps, a boat out ~75% of the time; the sampan model, lanes 3 m, `occlude` hides it behind the railing, posts and lamps | `events.boat: { ambient, dur, idle, atStart, first, route: { camera, path, fade, lanes } }` + a `boat` layer `{ model, lanternColor, occlude: { ratio, below }, haze }` | hull wash at `audio.events.boat_db` (ramen -20 dB), wake laps off (`lap_db` -45) |
| `moth` (ambient, 2026-10-19) | moth.js: a moth comes out of the dark, circles a lamp in erratic loops (a wavering orbit with darts), lands on the lit pane 0-2 times as a silhouette (only from in front of the lamp, so it never flies through it) and flies off; lit by the lamp's own color, falling off with distance; hidden behind the lamp's region when behind it, nearer things and the indoors; two can overlap. Ramen: 24 visits an hour, 45-140 s each | `events.moth: { perHour, dur: [s, s], lands, startAfter, first }` + a `moth` layer `{ lamp: region, center, unit (px), size (px) }` | none |
| `perch` (ambient, 2026-10-19) | perch.js: a group of 1-4 small birds lands one by one on a wire or crossarm (flapping in, braking, a swoop up onto it), each sits minutes (head turns, tail flicks, a rain shake, a shuffle) and flies off, some groups together. A near thunderclap (`lightning` thunder) flushes every sitting bird; none lands for `calm` s after one, and often a few come back. `atStart` birds are already sitting at t = 0. Ramen: 20 groups an hour, birds sit ~70% of the time | `events.perch: { perHour, slots: [count per perch], group, stay: [s, s], together, atStart, calm (25), comeBack (0.75), first, intro }` + a `perch` layer `{ perches: [{ name, pts, slots, size, lift }], disp, haze }` | none (too small to hear over the rain) |
| `petact` (ambient, **retired 2026-10-18**) | pet.js: a generated behavior clip of the painted pet (tools/pet_clips.py) forward to its rest frame, held, then backward. It looked eerie and obviously AI: never add it to a scene (DECISIONS 2026-10-18). No scene uses it since the ramen alley's v5 | `events.petAct` + a `pet` layer | none |

Region effects that are continuous (not events) are set per region in `scene.json` / `REGION_FX` (autoscene.js): `sway`, `bob`, `pendulum`, `flow` (with `wobble`), `flicker` (styles fire, candle, neon, lamp, screen; `spill` lights the room), `twinkle`, `shimmer`, `breathe`. `regionDip(tl, name, t)` in timeline/lights.js applies `neon`/`gutter` dips to a region's flicker level.

Every ambient stream also takes `first` (seconds): its first event comes within that long after `startAfter`, for a strong opening (2026-10-16). Without it the draw order is unchanged, so older timelines stay identical.

## Add a new event type

1. **Design it on paper.** What real thing happens, how often (per hour), how long, where on screen, how it moves physically, and what it sounds like. Is it a spotlight event (rare, one at a time: use the rare scheduler) or a small frequent one (its own stream)? Check the comfort and realism rules below before writing code.
2. **Timeline entry** (`src/library/timeline/`), and the type's name in the `events` list of `src/library/types.json` (`tests/test_types.py` fails without it):
   - Rare: in `rareEvents()` (spotlight.js), append `if (spec?.<type>) types.push({ type: '<type>', cooldown: <s>, ...spec.<type> });` and draw its per-event parameters with the shared `r` inside the candidate loop (`if (T.type === '<type>') { ... }`).
   - Frequent or independent: a new function with its own stream, `mulberry32((Math.imul(seed, <odd constant>) ^ hashStr('<type>')) >>> 0)`, added to `events` (or to its own field) in `buildTimeline` (build.js).
   - Store on the event everything both the picture and the sound need (positions, direction, dips, a `seed`), the way lanterns store `dips` and boats `dir`. Events are sorted afterwards and get `id` and `frame`.
   - If the audio needs per-time data that only the renderer can compute, add it in `writeTimeline` (`src/cli.mjs`) with the renderer's own functions (as `boatProfile`).
   - Export a pure state function (`<type>State(tl, t)`) if several modules need the pose, like `petState` and `flashAt` (binary search on the sorted list).
3. **Layer or shader:** a new `src/library/<type>.js` with `export async function <type>Layer(ctx, opts)` (or new uniforms in `plate.js` for warps of the plate itself), wired into the scene's `build()`; for a `scene.json` scene, an entry in `LAYERS` (autoscene.js) and its name in the `layers` list of `types.json`. Patterns with code in [references/layer-patterns.md](./references/layer-patterns.md):
   - a screen-box quad (draw only the event's box; invisible when no event is active);
   - sub-sample anti-aliasing (4 rotated-grid samples) or pixel-art AA, and motion blur over the shutter;
   - occlusion by the outdoors mask (`lights.png` G), water-only effects by `masks.png` G; paths that start and end hidden (mist or solid foreground), never popping in;
   - haze as airlight: an opaque object mixed toward a mip-blurred plate (`textureLod(tPlate, uv, lod)`), never made transparent (the 2026-10-15 boat fix: a see-through hull showed the bright reflections behind it);
   - the lake camera (`lakeCamera`, `makePath`, `boatPose` in `boat.js`) for anything on or above the water;
   - light from `env.png`, the light glow (`lights.png` B) and `flashAt`; a `debug` mode that outputs coverage for `debug=rain`.
4. **Audio hook** (`tools/cozy/audio/`, ambience-audio skill): a seeded synthesis function, the next unused `LAYER` id, a level in `DEFAULTS["events"]`, and a loop in `event_waves(t0, t1)` that includes every event whose sound overlaps the range. Event sounds stay ≥ 3 dB under the bed.
5. **Preview:** `node src/cli.mjs timeline scenes/<scene>` (count and spacing), then `node src/cli.mjs preview scenes/<scene> --event <type>:0 --seconds <dur + 12> --out out\<scene>\<type>0.mp4`. `--event` works for types in `events` and starts 6 s before the event; for `pet`, `leaves` or `lights` entries use `--start <frame>`.
6. **QA:**
   - stills inside the event and `rain_qa.py scenes/<scene> --plate <plate> --leak --frames <event frames>` (zero coverage over solid geometry and `qa_regions`);
   - random access: `still --frames <f-2>,<f-1>,<f>` and `still --frames <f>` with different `--name`, then compare the two `f` PNGs with `Get-FileHash` (must be identical);
   - `rain_qa.py --seam` (the base loop must stay seamless and `events=off` must hide the new layer);
   - `tools/audio.py ... --start <t-5> --duration <dur+20> --stems --report` and listen to `_events.wav`;
   - a 1 h window render before any 10 h master (master-render).
7. **Record** a dated `docs/DECISIONS.md` entry (what, why, rates, numbers), update STATUS, and add a row to the event catalog above.

## Viewer comfort (hard rules)

- No strobing: lightning is a soft ramped glow, at most 3 flashes per second (WCAG 2.3.1); keep large-area brightness swings under 0.1 relative luminance. Any new brightening ramps over tenths of a second (lantern dips are cosine-shaped, at most 2 per second).
- No sudden loud sounds: event sounds ≥ 3 dB under the bed (momentary), thunder ≤ ~6 dB over the bed (short-term) with a soft onset.
- Locked camera: no shake, zoom or reframing, ever.
- Calm density: one spotlight event at a time, cooldowns per type, nothing back to back, nothing on top of lightning. Small motions should be noticed by an attentive viewer, not demand attention.

## Realism (the motion quality bar, docs/REFERENCE.md)

- Physically motivated: model the real thing (speeds, sizes, gravity, drag, wakes); look up how it really behaves before inventing.
- Irregular: per-instance variety and seeded jitter in timing, size, speed and brightness; no grids, no equal spacing, no constant rates.
- Depth: size, speed and haze follow from distance (one camera for everything on the water).
- Lit by the scene: environment light, warm glints near lanterns, the lightning flash.
- Correct occlusion: never through solid geometry; verify with `--leak` coverage and frame differences.
- Verify like a viewer: watch the preview at full size, 1:1 crops, frame differences, side-by-side with the reference stills. The first boat draft (a flat side-view sprite on straight screen lanes) was invisible and started on land; a world-space model on a calibrated camera fixed both.
- Contrast needs a background: a dark silhouette only reads against something bright. The first heron (190 m out, over the dark far forest) was ~15 px and invisible in the test render. v5 uses `screenY` to pin the crossing to the bright misty band, 60–78 m out, and the user could see it. Project the path through the camera and check the sky mask and luminance behind it, then confirm with a difference of frames one loop (120 s) apart, which isolates the event from the base animation.
- Living things never move like vectors: no rigid straight-line glides, no constant-amplitude cycles. Vary each wingbeat a little and let the path rise and fall (heron v5, after the user found the glides fake and low effort).

## Gotchas

- `--params events=off` removes the whole timeline (base-loop QA); layers must return `null` or stay hidden without it.
- Lantern events exist only if `plate.json` has `lantern` light groups; plate.js switches light ids 1–63 only.
- **Switchable lights** (`light_groups` in `tools/cozy/plate/lights.py`): each pixel stores the 4 lights whose own switch-off changes it most (`lightid.png`, packed ids) and their shares of the all-lights-off log-ratio (`lightw.png`); a light that dims removes only its share. Never go back to one owner per pixel blending toward `plate_off.png`: switching one window then pulled in the porch lantern's darkening as a hard-edged dark disc (fixed 2026-10-15). Windows must lie in the masks json `window_disp` disparity band (default 0.005–0.045), or lantern-lit leaves and rail tops and sunset glints become "windows". Check new plates with a contact sheet of the window groups.
- Pet motions, leaves and night lights are not in `tl.events`, so `--event` can't find them; compute frames from `out/<scene>/timeline.json` (`frame = round(t × 30)`).
- `id`s are reassigned after sorting, so they change when any event is added or removed; key caches by type and id within one run only.
- Changing a rate re-runs acceptance for all rare types; re-check every type's count per hour afterwards.
