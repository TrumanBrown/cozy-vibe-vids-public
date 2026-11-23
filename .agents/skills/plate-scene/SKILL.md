---
name: plate-scene
description: 'End-to-end recipe for a new animated plate scene in cozy-vibe-vids: hero key art, 4K plate (tools/plate_prep.py), hand masks json (outdoor_disp, traced only_water, sky/foliage, not_derain, waterfall, window_disp, qa_regions), plate measurements, scenes/<scene>/scene.js from a commented template (plateLayer, rainLayer, leavesLayer, boatLayer, fishLayer, heronLayer, events spec), timeline, audio, QA, previews and the master render. Use when: starting a new video or scene (jungle, mountains, beach, snowy cabin, city, lighthouse), porting the Treetop setup to new key art, measuring a plate (gridded crops, disparity histogram, water disparity vs row, lake camera horizon and height, runoff lips from edges_preview.png, pet rig coordinates, window light groups), writing or reviewing a scene.js, deciding what must differ between videos for YouTube monetization, or planning new modules for other settings (snow, surf, fog banks, canopy drips).'
argument-hint: 'scene name and setting, e.g. "jungle-hut: rainy jungle afternoon with a parrot"'
---

# Plate scene: from key art to a finished 10 h video

> **New videos in any aesthetic start with the [new-video skill](../new-video/SKILL.md)**: the analysis writes the masks and a data-driven `scene.json` automatically. This skill is the hand-measured path (Treetop) and the reference for pet rigs, the lake camera, boat routes and measurement scripts; use it to go beyond what the automatic analysis does.

A scene is one AI key-art image turned into a 4K plate (depth + masks) and animated in code: a full-screen plate shader (mist, ripples, sway, flicker, waterfalls, pet, switchable lights, lightning light), physically based rain and roof runoff, falling leaves, a lantern boat, fish rises and a distant heron, all driven by one seeded timeline, with procedural audio and a segmented master render. The reference is `scenes/treetop-plate/scene.js` (Treetop; the user approved its rain, lightning and audio on 2026-10-15, then asked for more frequent events: timeline v4).

| Stage | Details |
|---|---|
| Key art (Azure gpt-image), `tools/plate_prep.py`, mask basics, leak QA | [keyart-pipeline](../keyart-pipeline/SKILL.md) |
| Rain, runoff, wind, weather drift, lightning, thunder sync | [plate-weather](../plate-weather/SKILL.md) |
| Event timeline, rare events, adding event types | [ambient-events](../ambient-events/SKILL.md) |
| Ambience, thunder, event sounds, music slot | [ambience-audio](../ambience-audio/SKILL.md) |
| Segmented master render, QA report, upload | [master-render](../master-render/SKILL.md) |
| Weather patterns to adapt (snow, splashes, storms) | [threejs-weather](../threejs-weather/SKILL.md) |

## Before you start

- Read `docs/STATUS.md`, `docs/GOALS.md` (spec, checkpoints, loudness), the motion quality bar in `docs/REFERENCE.md` and `AGENTS.md` (non-negotiables). Update `docs/STATUS.md` before you stop.
- Ask before spending beyond a small key-art batch. Log every key-art image used in `docs/asset-ledger.csv` before use.
- Stop for the user's approval of the key art and of a preview before any master render (GOALS checkpoints).
- Don't add or edit files under `scenes/` or `assets/keyart/` while a master render is running: both folders are part of its fingerprint, so it could no longer resume (master-render skill).

## Procedure

1. **Decide what makes this video different** ([below](#what-to-vary-per-scene-monetization)) before generating anything.
2. **Key art:** write `scenes/<scene>/keyart.json` and generate a few candidates (keyart-pipeline). Ask for things the code can animate: open sky, calm water seen from above with a misty far end, hanging foliage at the frame edges, lanterns and distant lit windows, a roof edge to pour from, a pet asleep or resting (it only breathes and sighs: DECISIONS 2026-10-18), **and 1–2 animatable props** (a steaming mug, a fire, a clock; see keyart-pipeline "Animatable props"). View every candidate and pick the hero.
3. **Plate:** `.venv\Scripts\python tools\plate_prep.py <hero.png> --name <plate>` writes `out/plates/<plate>/`. Look at:
   - `preview_masks.png`: left = plate tinted (magenta outdoors, blue sky, cyan water, green foliage, white lights), right = disparity.
   - `edges_preview.png`: the outdoors' top edge (cyan dots) and runoff candidates (red = vine/leaf tips, green = flat eaves, blue = columns open to the frame top), labeled with x.
   - `lights_preview.png`: switchable light groups (green = windows that can go dark, orange = lanterns, blue = windows over water, never switched).
4. **Masks:** write `assets/keyart/<plate>.masks.json` ([keys](#masks-json-keys)), re-run `plate_prep.py <hero.png> --name <plate> --masks-only` (reuses the upscale and depth), and check the previews again. Iterate until outdoors covers only the world outside the opening.
5. **Measure** with this skill's scripts: [checklist](#per-scene-measurement-checklist), how-to in [references/measure.md](./references/measure.md).
6. **Scene module:** copy [assets/scene.template.js](./assets/scene.template.js) to `scenes/<scene>/scene.js`, replace every `<placeholder>` and every value marked MEASURE or TUNE, and delete the layers and `events` entries the scene doesn't have.
7. **Timeline:** `node src/cli.mjs timeline scenes/<scene>` writes `out/<scene>/timeline.json` and prints events per hour. Tune the rates in `events`, try a few seeds and keep one that spreads events well and has a rich hour for the test render (ambient-events). **The video's first minutes must be the busiest** (user 2026-10-16): choose the test hour and loop `--offset` so it opens on a storm cell and a spotlight event, and music comes in within seconds (ambient-events "Strong opening").
8. **Audio:** `tools/audio.py` synthesizes the bed, thunder and event sounds from that timeline. Set `audio` overrides and check `--report` (ambience-audio). A setting without rain or a roof needs new layers.
9. **QA** (all must pass):
   ```powershell
   .venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --leak --seam --flash --profile
   .venv\Scripts\python tools\audio.py out\<scene>\timeline.json --start 600 --duration 120 --out out\<scene>\audio\check.wav --report
   ```
   `--leak` uses 8 frames from the first loop only; add `--frames <f,...>` with frames during a boat trip (frame = event `t` × 30) to cover the boat and leaves. Then look like a viewer: 1:1 crops of stills, frame differences (`scripts/plate_measure.py diff`), and a side-by-side with the reference stills in `cache/reference/` (desktop only).
10. **Previews:** `node src/cli.mjs still scenes/<scene> --frames 0,1800`, `node src/cli.mjs preview scenes/<scene> --seconds 10`, then 60 s, then each event type: `--event lightning:0 --seconds 24`, `--event boat:0 --seconds 160`, `--event lantern:0 --seconds 12`, `--event heron:0 --seconds 50`, `--event fish:0 --seconds 18`, `--event flurry:0 --seconds 20`; window presence and pet motions via `--start <frame>` from `timeline.json`. An `--event` clip starts 6 s before the event; pass `--out out\<scene>\<name>.mp4` so clips don't overwrite each other. Ladder: 10 s, 60 s, a 1 h test window, 10 h; step up only after approval.
11. **Master:** `node src/cli.mjs render scenes/<scene> --from <h> --length 1h` for the test hour, then `--duration 10h` or loop the approved hour with `tools/loop_master.py` (master-render). Get the sound approved on `loop_master.py --preview` clips (music level, opening) before the 10 h build, so it's built once.
12. **Thumbnails and upload package** (master-render "Thumbnails", "Upload checklist"):
    - Write `assets/thumbnails/<scene>.json`: the suggested layout (place card + music badge + weather chip + pet close-up) **plus several alternative concepts**. The user always wants options.
    - Write `assets/publish/<scene>.json`: titles, description lines, tags, the suggested thumbnail.
    - Run `tools/upload_package.py assets/publish/<scene>.json`. The user uploads from `upload/<slug>/` only.
13. **Record:** a dated `docs/DECISIONS.md` entry (what differs from earlier scenes, measured values, QA numbers), `docs/STATUS.md`, and the ledger.

### Masks json keys

`assets/keyart/<plate>.masks.json` holds normalized polygons (lists of `[x, y]`, y down; each key takes a list of polygons) for the channels `sky`, `water`, `foliage`, `lights`, `outdoor`: `<ch>` adds to the automatic mask, `not_<ch>` removes, `only_<ch>` limits (applied in that order).

| Key | Meaning | How to set it |
|---|---|---|
| `outdoor_disp` | outdoors (where weather exists) = disparity below this, edge-snapped with a guided filter (plate_prep default 0.15) | `plate_measure.py disp`: below the low percentiles of every solid object near the opening (Treetop 0.105; porch ≥ 0.15) |
| `only_outdoor` | clip outdoors to the opening | a box or polygon around the opening (Treetop x 0.02–0.835, y 0–0.86) |
| `not_outdoor` | remove outdoors where depth is wrong (thin vines, glass) | also add a `qa_regions` box there. Never paint outdoors over solid objects. Trace the object itself, never a box around it: the view between its legs or rails must keep its rain (the ramen stool and the Treetop railing; `weather_audit.py` reports such dry pockets). |
| `only_water` | traced water polygons | trace the shoreline on gridded crops; water seen through rail gaps is a separate polygon |
| `only_sky`, `not_sky` | where mist and the lightning glow treat the image as sky; cut out hanging lanterns | gridded crop |
| `only_foliage`, `not_foliage` | where sway applies (near leaves and vines); cut out lanterns | gridded crop |
| `derain` | painted-rain removal: `{"strength": 1.5}` (default) or `false` | `false` if the key art has no painted rain |
| `not_derain` | protect waterfalls and other thin bright vertical features from de-rain | box around each |
| `waterfall` | polygons around each waterfall: `flow.png` (R weight, G progress down the fall, B height) drives scrolling streaks in `plate.js` | one polygon per fall, top edge at the lip; check with stills 1 s apart |
| `window_disp` | `[min, max]` median disparity of a switchable window (default `[0.005, 0.045]`): drops lantern-lit leaves and rails (near) and sunset glints (sky) | contact sheet of the window groups vs `disp` (Treetop: real windows 0.007–0.040, false ones ≥ 0.053) |
| `qa_regions` | named boxes `[x0, y0, x1, y1]` that must get exactly zero rain | pet, ceiling, lanterns, posts, deck, interior |

The automatic masks are crude: water = every outdoor pixel below y 0.35, foliage = warm saturated (autumn-colored) pixels that are not outdoors. Always trace `only_water`. A plate without water needs a full-frame `not_water` polygon (an empty `only_water` list is ignored). Green foliage needs explicit `foliage` polygons.

## Per-scene measurement checklist

Scripts: `.venv\Scripts\python .agents\skills\plate-scene\scripts\plate_measure.py <cmd>` and `node .agents/skills/plate-scene/scripts/lake_camera.mjs <cmd>`. Write images to `out/<scene>/measure/` and view them. Details: [references/measure.md](./references/measure.md).

- [ ] **Gridded crops** (`plate_measure.py grid`) of every region you will read coordinates from.
- [ ] **outdoor_disp** from `plate_measure.py disp` (histogram plus `qa_regions` percentiles), previewed with `--thr`, then `rain_qa.py --leak` PASS.
- [ ] **only_outdoor** around the opening; **qa_regions** on every solid thing near it.
- [ ] **See-through gaps** (railings, fences, lattices, window bars, gaps between posts, especially low ones near the floor): view the outdoor mask at 1:1 over every gap. Use crops of `preview_masks.png`, or the plate tinted by `lights.png` G.
  - Monocular depth fills thin gaps near the camera with the near depth. Treetop shipped with no rain or leaves under the railing's lower rail: those gaps read 0.16–0.32 against its 0.105 threshold, while the same scenery above the rail reads 0.02–0.04.
  - Fix with tight `outdoor` polygons, one quad per gap, inset a few px from the solid edges. Then a `debug=rain` still must show rain in every gap, and `rain_qa.py --leak` must still pass.
  - Prefer key art without many low, thin gaps right in front of the camera.
- [ ] **only_water** traced; a 2-still frame difference shows ripples only on water; `plate_measure.py rows` shows disparity rising smoothly with y (drops or jumps = shore, island or a separate stretch); `lights_preview.png` re-checked (windows over water are never switched).
- [ ] **Sky/foliage** limits and `not_derain` boxes on waterfalls.
- [ ] **Runoff lips** from `edges_preview.png` and `plate_measure.py cands`: streams only in open sky columns, drips at vine ends; checked with `--params only=runoff,debug=rain` stills.
- [ ] **Pet** breathing ellipse from a fine grid (step 0.005, zoom 3), checked with stills at a breath and a sigh. New scenes get no ear or tail rig: a painted pet only breathes and sighs (DECISIONS 2026-10-18). Treetop's ear flicks and tail twitches predate that rule.
- [ ] **Lake camera** (if there is calm water): shore-block widths at 2+ rows, `lake_camera.mjs fit`, `pts` (1 block ≈ 1 m); boat path far end in mist, near end behind solid foreground; `lake_camera.mjs route scenes/<scene>`.
- [ ] **Light groups:** ≤ 63 ids (plate.js switches ids 1–63 only), lanterns found if you want lantern events. Make a contact sheet of every window group (crop, id, size, median disparity) and tune `window_disp` until only real distant lights remain. A false "window" (a lit leaf or rail top) that switches off reads as a glitch. `plate_prep.py` prints the largest dropped 5th-light log-ratio (should be ≲ 0.02).
- [ ] **Waterfalls:** `waterfall` polygons; the flow streaks run down the fall at a believable speed (two stills 1 s apart).
- [ ] **Leaves:** `foliage_palette` indices and the spawn x range under the canopy.

## What to vary per scene (monetization)

YouTube's inauthentic-content policy targets interchangeable, template-made videos, and "a still image plus overlays" is the risky pattern (AGENTS.md, GOALS.md). A new seed, rate tweak or palette swap is **not** a new video.

| Dimension | Treetop | A new scene must bring |
|---|---|---|
| Place and layout | autumn treehouse porch over a river valley, opening left of center, cat lower right | a different place, camera height and composition |
| Time and weather | rainy dusk with passing storms | another time of day and/or weather (drizzle, snow, fog, clear night) and its own drift |
| Signature motion | the lantern boat coming out of the mist | at least one new signature event or motion (a new module) |
| Creature | calico cat asleep on a cushion (ears, tail, sighs) | a different animal or pose, or none |
| Animated props | none besides the cat (a gap: the user asked for more, 2026-10-16) | 1–2 props the code animates: steaming mug, fire, clock, candle, chimes (keyart-pipeline) |
| Rare events | lightning (~6/h), lantern gutter, boat, heron; ambient fish rises, gust flurries, people at distant windows | a different mix, at least one event type not used before |
| Light | warm lanterns against blue dusk; windows going dark late | its own light sources and light events |
| Sound | rain on a plank roof, lake drops, runoff, wood creaks, thunder | a bed that matches the place (surf, crickets, fire, wind in pines) |
| Music | none yet (user slot) | its own playlist, if any |

GOALS asks for a catalog of each video's "fingerprint" to catch near-duplicates; it doesn't exist yet, so record the differences in the scene's DECISIONS entry.

## Adapting to other settings

**Carries over unchanged:** plate prep (upscale, depth, outdoors from depth, `env.png`, `flash.png`, light groups, de-rain, waterfall flow); `plate.js` (mist, ripples and rain rings, sway, flicker, waterfalls, pet warps, switchable lights, lightning light); `rain.js` for any rainy scene (falling rain plus runoff from any edge, gust flurries); `leaves.js` for any deciduous canopy (colors from the plate's palette); `boat.js` for calm water seen from above with a misty far end (the covered lantern skiff is the only model); `fish.js` for any open water; `heron.js` for a large bird crossing far away (retune the silhouette for gulls or egrets, and keep its path in front of bright sky); the timeline (weather drift, calibrated lightning, rare and ambient schedulers, night lights, window presence, pet schedule); the audio engine (blocks, thunder, events stem, music); the render pipeline and every QA tool.

**Needs new modules:**

| Setting | Missing | Start from |
|---|---|---|
| Snowy cabin | falling snow (slow flakes, flutter, blizzard swells), maybe settling | `rain.js` instancing and `leaves.js` flutter; threejs-weather "a blizzard is a slow envelope" and "falling and settled snow are two variables" (settling must be a pure function of time, e.g. integrated from the weather track); a quieter bed without rain layers |
| Beach | surf: breaking wave lines, foam, swash on sand; a sea horizon | `lakeCamera` (the horizon is the real one); a new layer driven by a seeded, irregular wave-set schedule in the timeline that the audio reads too (like runoff's shared `flowAt`) |
| Jungle | heavy canopy drips, green sway, insects and frogs | many low-rate runoff sources (drips), `foliage` polygons, new audio grain layers |
| Mountains, fog | fog banks drifting in depth layers, wind in pines | `plate.js` mist (fbm over far terrain) as a start; a layer using `depth8.png` per band, integer-cycle drift; retuned wind layer |
| Fireplace, campfire | visible flames and embers, crackle | flicker exists (lights mask); flames need a layer; a crackle grain layer |
| Any | new rare or ambient events | ambient-events "Add a new event type" |

Rules for any new module: a pure function of absolute time `t = frame / fps` with seeded randomness; integer cycles per 120 s loop for periodic parts; occluded by the outdoor mask (`lights.png` G) and limited to water by `masks.png` G where it belongs; lit by `env.png`, the light glow and `flashAt`; no strobing (≤ 3 flashes/s, soft ramps); event sounds under the bed; locked camera; QA with `rain_qa.py --leak --seam --flash` and `audio.py --report`. Look up how the real phenomenon behaves before inventing it (REFERENCE motion quality bar).

## Gotchas

- `rain_qa.py --leak` only finds rain drawn **on** solid things. Missing rain in a see-through gap passes every QA, and so do leaves vanishing behind "solid" air. Check gaps by eye (checklist "See-through gaps"): it happened in Treetop under the railing.
- Keep `fps` and `loopSeconds` as numeric literals in the scene (`rain_qa.py` parses them with a regex) and keep the loop at 120 s: plate.js and rain.js use fixed integer cycle counts per loop that were tuned for 120 s.
- Layers assume a 3840×2160 plate (`W`, `H` constants in rain.js, leaves.js, boat.js).
- `--params events=off` drops the whole timeline: no lightning, weather drift, leaves, boat, lights or pet motions.
- Lantern events need lantern light groups; night lights need non-reflective window groups. Groups above id 63 never switch.
- Rain rings on the water are always drawn (scaled by the weather track's rain); a dry scene with water needs a code switch.
- `tools/audio.py` is tuned for a covered porch over a lake in rain (roof drumming, lake bubbles, treehouse creaks are always on). Review every layer for a new setting; mute by level, never by a 0 grain rate (it divides by the rate).
- The description's blurb (`assets/publish/description_blurb.txt`, Truman's own words) mentions rain, wind and thunder; check it fits the scene, and give the publish spec its own `blurb` lines if it doesn't.
- `preview` muxes audio only if the scene has an `audio` key.
- The 4K plate is downscaled when viewed whole: read coordinates from gridded crops, never from the full image.
