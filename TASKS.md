# Refactoring tasks

From the code review of 2026-10-26. The goal is code that is easier to change without breaking a video. Work top to bottom, one task per commit. AGENTS.md's rules (deterministic, joins without seams, nothing frozen) win over anything here. How the parts fit together, with more evidence for most of these findings: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

For every task:
- Run `.venv\Scripts\python -m unittest discover -s tests` before and after (about a minute, free, offline; `COZY_SLOW=1` adds the stills of 17 scenes, about two minutes more).
- Tool names and flags stay as they are: docs, skills and lessons call them by name. A moved helper stays importable from its old place for one round, then the callers move.
- Anything the render fingerprint covers (src/engine, src/library, scenes, assets/keyart, tools/audio.py, music.py, audio_analyze.py) changes every render's fingerprint, so a render in progress can't resume. Do those tasks between renders.
- Deleting anything needs Truman's OK.

## Order of work

| # | Task | Size | Needs | Status |
|---|---|---|---|---|
| T1 | Free offline safety net: tools import, cross-tool references, JS modules, timeline goldens | S | | done 2026-10-26 |
| T2 | Sound and picture goldens | M | T1 | done 2026-10-26 |
| T3 | Audio beds without reading audio.py's source text | S | T1 | done 2026-10-26 |
| T4 | One Azure client (keyart.py) | S | T1 | done 2026-10-26 |
| T5 | Main guard for rain_analyze.py; no private or silent calls across tools | S | T1 | done 2026-10-26 |
| T6 | Missing render inputs fail loudly | S | T1 | done 2026-10-26 |
| T7 | Pet motion defaults that match the rules | S | T1 | done 2026-10-26 |
| T8 | Pin the Python packages and model revisions | S | | done 2026-10-26 |
| T9 | Render fingerprint and cache keys that see every input | M | T1 | done 2026-10-26 |
| T10 | tools/cozy/paths.py: one ROOT, one PY, path and config helpers, one scene.json writer | M | T1 | done 2026-10-26 |
| T11 | tools/cozy/media.py: one ffmpeg and ffprobe wrapper | M | T10 | done 2026-10-26 |
| T12 | Shared code out of the CLI scripts; break the two import cycles | M | T10 | done 2026-10-26 |
| T13 | Remove duplicate helpers | S | T12 | done 2026-10-26 |
| T14 | Contracts written in both JS and Python: formulas pinned by a test, one list of types | M | T2, T10 | done 2026-10-26 |
| T15 | Split finish_video.py | M | T12 | done 2026-10-26 |
| T16 | Split plate_prep.py | L | T12 | done 2026-10-26 |
| T17 | Split audio.py | L | T2, T9 | done 2026-10-26 |
| T18 | Break up the longest Python functions | M | T1 | done 2026-10-26 |
| T19 | plate.js shaders to their own file; split timeline.js | M | T2 | done 2026-10-26 |
| T20 | One RNG and shared helpers in JS | M | T2 | done 2026-10-26 |
| T21 | Retire superseded code: voxel engine, pet mocks, spikes | M | his OK, T2 | |
| T22 | Docs and file encodings that drifted | S | T21 | done 2026-10-26 |
| T23 | A linter that finds bugs, no reformatting | S | T9 | done 2026-10-26 |

S is under an hour, M about a session, L more than one session.

## What the review found

About 39,800 lines: 26,200 of Python in 59 tools and 13,500 of JavaScript in src/. Nine files are over 900 lines.

What works and should stay:
- Determinism is built in: seeded RNG, time from the frame index, and a render manifest that resumes and re-renders a segment to prove the bytes match.
- Scenes are data: 9 of the 17 scenes are a 4-line scene.js over scene.json and [autoscene.js](src/library/autoscene.js).
- Azure calls mostly go through one client with a spend log and a budget guard.
- Every tool opens with a docstring of what it does and how to run it, 52 of 59 use argparse, and there is no bare `except:`.

What makes it hard to change, worst first:
1. No tests. The only self-tests call paid vision models (critic_selftest.py, `outdoor_check.py --selftest`). Nothing checked that a change keeps timelines, sound or pictures identical, which AGENTS.md requires and which rebuilding a posted video after a claim depends on. T1 starts this, T2 finishes it.
2. Checks that can't see what changed. The render fingerprint hashes the plate folder by file name and size, and its fire/ and steam/ subfolders (397 and 3,601 files for the Burdock Shelter) read as size 0, so regenerated clips don't count as a change and a resumed render can mix old and new ones. It also covers every scene and all key art, so editing one scene stops every render from resuming. Caches are keyed on one file's bytes (loop_master on audio.py, footage_loop on water_bed.py) or on mtimes, and autopilot.py finds the audio beds with a regex over audio.py's source text. T3, T9.
3. Silent failures. 9 fetches of render inputs in src/library fall back to null or an empty value, so a missing file draws nothing, and the page's `console.log` never reaches the render log. Two QA helpers in motion_review.py return None on any exception. T5, T6.
4. Tools are each other's libraries. ROOT is defined in 51 tools, sys.path is patched in 37, and 139 scene, plate and key-art paths are built by hand in 36 files. Shared code lives inside CLI scripts: azure_ai is imported by 22 tools, music by 12, plate_prep by 9, analyze_plate by 8 (all of them for its SAM 2 Segmenter). Two import cycles hide behind imports inside functions. T10, T12.
5. Duplication. A second Azure client in keyart.py that has drifted from azure_ai.py. ffmpeg or ffprobe called directly from 21 tools, probe() written 4 ways. In JS, mulberry32 is written 5 times in 3 ways, and pixelsOf, avg, dirLight, quad and loadTex are copied between layers. Across languages, audio.py's flow() calls itself an "Exact copy of flowAt() in rain.js" and gust() mirrors windAt(), with no test comparing them, and the layer and event types are plain strings with no schema. T4, T11, T13, T14, T20.
6. Monoliths. plate_prep.py 2,169 lines, finish_video.py 2,072, audio.py 1,278, timeline.js 1,124, plate.js 858 (519 of them one shader string). Functions over 200 lines: dog3dLayer 559, analyze_plate.main 353, timeline's ambientEvents 335, loop_master.main 283, upload_package.main 254, plate_prep.masks 245, antLayer 237, petSpriteLayer 237, review.lint 227, steam_sim.simulate 223, critterLayer 207. T15 to T19.
7. Superseded and forbidden code in the live path. About 8,100 lines, a fifth of the code, that no video uses: the voxel engine (superseded 2026-10-15), the pet mocks and the Phase 0 spikes. The engine still builds the voxel Builder and Foliage for every plate scene. timeline.js still defaults to ear flicks and tail twitches, which the painted-pet rule forbids, and the retired pet_clips.py still loads the model for fire_clips.py. T7, T12, T21.
8. Reproducibility and docs. requirements.txt has no versions and leaves out torch, numpy makes the sound, and none of the 15 `from_pretrained` calls pins a model revision. README still says Python is "not needed yet". T8, T22.

## Modules

How the code groups today. The target layout below is where T10 to T20 take it; nothing has moved yet.

| Module | Files | Lines | What it does |
|---|---|---|---|
| Orchestration | tools/autopilot.py, new_video.py, finish_video.py | 3,520 | one idea to a sample, the sample to an upload folder |
| Key art and image edits | keyart.py, keyart_revise.py, art_edit.py, critter.py, critter_concept.py, cast_eyes.py | 1,399 | Azure image generation and masked edits |
| Plate preparation and analysis | plate_prep.py, analyze_plate.py, plate_clean.py, plate_features.py, hand_region.py, critter_ends.py, mask_edges.py | 5,350 | 4K plate, depth, masks, SAM regions, the scene.json draft |
| Motion assets | fire_clips.py, steam_sim.py, pet_clips.py | 1,455 | fire clips, the steam simulation |
| QA gates | review.py, critic.py, critic_selftest.py, motion_review.py, weather_audit.py, outdoor_check.py, local_vision.py, leak_check.py, rain_motion.py, rain_qa.py, rain_analyze.py, event_sheets.py, render_qa.py | 3,974 | what must pass before Truman sees anything |
| Audio and music | audio.py, audio_analyze.py, audio_layers.py, water_bed.py, music.py, music_auto.py, music_fetch.py, music_screen.py, music_samples.py, music_like.py, mc_music.py, listen.py | 4,045 | ambience synthesis, loudness, playlists, finding music |
| Mastering and footage | loop_master.py, footage_loop.py, color_grade.py, color_edit.py and .html, intro_title.py | 3,497 | 20 min window to 10 h, his own footage, the opening line |
| Publishing | thumbnail.py, pixelfont.py, upload_package.py, marketing_check.py | 1,740 | thumbnails, the upload folder, text rules |
| Shared | azure_ai.py, azure_provision.py | 457 | the Azure client and spend log |
| Legacy and mocks (Python) | gen_textures.py, gen_leaves.py, enhance.py, pet_sprite.py | 1,537 | voxel textures, SDXL repaint, the sprite dog mock |
| CLI and render pipeline | src/cli.mjs, src/render/ | 836 | still, preview, timeline, segmented render, QA |
| Engine core | src/engine/engine.js, rng.js, output.glsl.js | 442 | page setup, camera, output shader |
| Timeline | src/library/timeline.js | 1,124 | every seeded event and the weather track; pure, runs in Node |
| Plate and scene assembly | plate.js, overlay.js, autoscene.js, title.js, blink.js | 1,388 | the plate shader, shared overlay helpers, scene.json to layers |
| Weather layers | rain.js, drips.js, glass.js, particles.js, leaves.js, petals.js | 1,715 | rain, drips, rain on glass, snow and flurries, leaves, petals |
| Fire, light and steam | fire.js, smoke.js, steam.js, liquid.js, traffic.js | 1,339 | |
| Creatures | birds.js, perch.js, moth.js, critters.js, ant.js, fish.js, heron.js, boat.js, pet.js | 2,903 | |
| Pet mocks (JS) | cat3d.js, dog3d.js, petsprite.js | 1,598 | not in any video |
| Voxel (superseded) | engine/builder.js, foliage.js, textures.js; library/blocks.js, creatures.js, exteriors.js, nature.js, props.js, structures.js, effects.js | 2,378 | the code-built look before 2026-10-15 |

Scenes: 9 data scenes on autoscene.js, treetop-plate (Treetop, written by hand), aquarium (his footage), 3 voxel scenes (treetop, lakeside, loft) and 4 mocks (catmock-pixel, catmock-treetop, dogmock-greenhouse, petmock-greenhouse).

Target layout, reached one task at a time:

```text
tools/              CLI entry points, names and flags unchanged
tools/cozy/         shared code, no CLI: paths, media, azure, segment, masks, voice, wan, plate/, audio/, publish/
src/library/        layers; shared helpers in overlay.js or a new util.js; timeline/ behind one index.js
tests/              the safety net
```

`python tools/x.py` already puts tools/ first on the path, so `import cozy` needs no path patch.

## Tasks

### T1. Free offline safety net (done 2026-10-26)

- [tests/test_tools.py](tests/test_tools.py): each tool imports in its own process, and 316 references from one tool into another must resolve. Most of those are imports inside functions, which a plain import never runs.
- [tests/test_scenes.py](tests/test_scenes.py) with [tests/js_scenes.mjs](tests/js_scenes.mjs): all 42 modules in src/engine and src/library and all 17 scenes import in Node, and the 22 names reached through a dynamic import (autoscene's layers, the CLI's helpers) exist; a plain import never checks those. Each scene's 10 h timeline is identical across two runs and matches [tests/goldens/timelines.json](tests/goldens/timelines.json). A golden is keyed by the scene's inputs (scene.js, scene.json, the scenes it imports, its local plate.json), so changed scene data is skipped, never blamed on the code.
- Proven by breaking things on purpose, one at a time: a moved helper (6 failures, each naming the caller and line), a moved helper used through an alias (3), a renamed JS export (30), a changed constant in timeline.js (4 scenes), an unseeded random in the timeline output (all 17), an edited scene.json (skipped, not failed), and a name missing behind a dynamic import (caught in a scratch copy while the plain import passed).
- Limits: it never renders a frame or a sound (T2) and never runs a tool's main().
- After a deliberate change to a timeline, record the goldens again on code you trust: `$env:UPDATE_GOLDENS = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_scenes.py; Remove-Item Env:UPDATE_GOLDENS`

### T2. Sound and picture goldens

Why: the biggest splits (audio.py, the plate shader, timeline.js, the JS helpers) need proof that not one sample or pixel changed.

Do:
- Sound: 3 s of `audio.py --stems` at two starts for three scenes, from recorded timelines. Store a small fingerprint per stem (RMS per 50 ms) and compare to 1e-6, so numpy's last bits on the laptop don't fail it.
- Pictures: `node src/cli.mjs still` at 1920x1080 for four scenes at three frames each, hashed. A slow tier (GPU, Electron, local plates) that runs when `COZY_SLOW=1`.
- Key both by their inputs, like the timelines: plates and fire clips are local.

Check: break an impact kernel in audio.py and one uniform in plate.js on purpose. Both must fail.

Done 2026-10-26: [tests/test_goldens.py](tests/test_goldens.py). Sound: 4 scenes (the ramen alley, the Burdock Shelter, Treetop, the snowy cottage) at 5 minutes and just before the first sound event, in the default tier (about 40 s; the first run on a machine calibrates loudness, about 100 s). Pictures with `COZY_SLOW=1`: all 17 scenes at 3 frames each, about 100 s, keyed by the plate folder's content through [src/render/inputs.mjs](src/render/inputs.mjs), which T9's fingerprint uses too. Two recordings in a row matched exactly. Broken on purpose: a changed bubble damping in audio.py failed the 3 rain scenes' sound, and a changed rain-ring default in plate.js failed Treetop's lake frame (581 pixels, by up to 4 levels, with their box).

### T3. Audio beds without reading audio.py's source

Why: `allowed()` in [autopilot.py](tools/autopilot.py) finds the beds with a regex over audio.py's text (`^\s*"(\w+)": \{"rain"`). A bed written in another shape, or a formatter run, empties the list without an error.

Do: `from audio import BEDS` inside allowed() and use `list(BEDS)`. audio.py itself doesn't change: it's in the render fingerprint and a cache key.

Check: allowed()["audio_bed"] gives the same 13 names in the same order before and after (checked 2026-10-26: `list(BEDS)` matches the regex today).

Done 2026-10-26: the same 13 beds in the same order.

### T4. One Azure client

Why: [keyart.py](tools/keyart.py) has its own token cache, POST and retry loop next to [azure_ai.py](tools/azure_ai.py). The copies have drifted (only azure_ai converts `expires_on` to a number, only keyart waits out a 404 DeploymentNotFound) and every fix has to be made twice.

Do: keyart's generate() calls azure_ai.generate_image(), and azure_ai's `_post` learns to wait out DeploymentNotFound (seen right after azure_provision.py creates a deployment). Keyart's flags, file names and sidecars stay. azure_provision.py's own `az` lookup goes through azure_ai too.

Check: T1, plus a test with requests.post and the token mocked for each retry path, so nothing is spent.

Done 2026-10-26: keyart's generate() calls azure_ai.generate_image(retry_unfinished=False), which logs the spend once. `_post` waits out DeploymentNotFound for every caller, and with `retry_unfinished=False` it raises azure_ai.Unfinished instead of sending a timed-out or broken-off request again (keyart's rule since d8e97a3; chat still retries). [tests/test_azure.py](tests/test_azure.py) covers each path with the network mocked.

### T5. Main guard; no private or silent calls across tools

- [rain_analyze.py](tools/rain_analyze.py) does its work at import (no main guard), so nothing can import or test it. Wrap it in main() and drop it from `SCRIPT_ONLY` in tests/test_tools.py.
- motion_review.py calls plate_prep's private `_derain_pass`. Give it a public name; it moves in T16.
- motion_review.py's `thing_mask()` and `painted_streaks()` return None on any exception, so a broken import quietly weakens a QA gate. Catch ImportError and FileNotFoundError only, and say so in the review output.

Done 2026-10-26: rain_analyze.py runs from main() and is imported by T1 like every other tool. plate_prep's `derain_pass` is public. motion_review catches only ImportError and FileNotFoundError and prints a `note:` line saying which measure it ran without.

### T6. Missing render inputs fail loudly

Why: 9 fetches of render inputs in src/library fall back to null or an empty value when the file is missing: regions.json in overlay.js (most layers read it), fire.json, steam.json, pet.json, intro.json, eyes.json and three image loads. A missing input draws nothing. title.js and blink.js report it with `console.log`, and [electron-main.cjs](src/render/electron-main.cjs) forwards only errors, warnings and progress lines. critter_ends.py's docstring records the cost: a beetle faded in on open moss, and "the render only prints a page warning that its log drops".

Do: an input a layer needs throws with its path, an input that may be missing is marked optional where the scene asks for it, and every page message reaches the render log. Check what is already handled before starting.

Check: T1, then remove one fire clip from a copy of a plate: the still fails and names the file.

Done 2026-10-26: overlay.js `fetchJson()` reads a layer's JSON input and throws with the file's path and what makes it. fire.json, steam.json (for a vessel with a measured opening), intro.json and eyes.json are required where the scene asks for the layer; regions.json may be missing (a hand-measured plate). autoscene reads plate.json from the engine (`ctx.plateMeta`) instead of fetching it again with a `{}` fallback. Every page message reaches the log tagged with its level; the render keeps them in render.json, logs each warning once, and its QA has a `page` check that fails on a warning (a shader compiler's precision note excepted) and lists them in qa.md. Hiding fire.json, intro.json or eyes.json of the Burdock Shelter's plate failed its still with the file and the fix; no scene printed a warning at 3 s in, and the 17 scenes' stills are unchanged.

Follow-up 2026-10-27: a module that stopped the render page's import graph (a syntax error, a missing file) left electron-main.cjs waiting for `window.cvv` forever, so a still, a preview or an autopilot render stage hung instead of failing. page.html now records what stopped the graph and the run ends with it (a 120 s limit backs it up). Electron also ended a failed run with exit code 0 (`app.quit()` ignores `process.exitCode`), so only the ERROR line in its output told the CLI and the pipeline; a failed run now exits 1. [tests/test_render_start.py](tests/test_render_start.py) (`COZY_SLOW=1`) breaks a copy of src/ and expects the error within a minute; the old code hung past its 25 s limit on the same copy.

### T7. Pet motion defaults that match the rules

Why: AGENTS.md says a painted pet only breathes, with no ear flicks or tail twitches. [timeline.js](src/library/timeline.js) still defaults to 8 ear and 5 tail events an hour and an ear twitch after 75% of near thunder, and every data scene switches them off by repeating `"ear": 0, "tail": 0, "thunderEar": 0`, which analyze_plate.py writes into each draft. One missing key brings the forbidden motion back.

Do: write today's values into any scene that relies on the defaults (Treetop sets its own), then make the defaults 0 and drop the zeros from the drafts. The ear and tail code in plate.js goes in T21.

Check: T1's timeline goldens: no scene's timeline moves.

Done 2026-10-26: no scene relied on the defaults (Treetop sets 18 ear, 11 tail and 0.75 thunderEar itself, the data scenes their zeros). ear, tail and thunderEar now default to 0 and analyze_plate's draft writes sighs only. No timeline moved, and [tests/test_rules.py](tests/test_rules.py) fails on the old defaults (a pet with no rates got ear flicks and tail twitches through a storm).

### T8. Pin the Python packages and model revisions

Why: requirements.txt has no versions and leaves out torch (SETUP.md installs it from the CUDA index). numpy makes the ambience, so an upgrade can change the sound of a rebuilt video. None of the 15 `from_pretrained` calls pins a revision, so the same key art can give a different plate later. package.json already pins three and Electron exactly.

Do: requirements.lock.txt from the desktop venv's `pip freeze`, installed by SETUP.md; requirements.txt stays the short list. Each `from_pretrained` gets the revision in use today.

Check: a fresh venv on the WSL laptop installs it and T1 passes.

Done 2026-10-26: [requirements.lock.txt](requirements.lock.txt) is the desktop venv's freeze (pip check clean), and SETUP.md installs from it. The 15 `from_pretrained` calls pin the revisions in [tools/cozy/models.py](tools/cozy/models.py), the ones cached today, all of which load offline. Still to do: install the lock in a fresh venv on the WSL laptop (it needs the Linux torch wheel of the same version).

### T9. Render fingerprint and cache keys that see every input

Why: five places decide whether a render or a cached file is still good, and they miss changes.
- `fingerprint()` in [pipeline.mjs](src/render/pipeline.mjs) hashes the plate folder by file name and size. Subfolders read as size 0, so regenerating fire clips or steam (`new_video.py life --force`) leaves it unchanged, and a resumed render can mix segments made with old and new clips.
- The same function hashes all of scenes/ and assets/keyart, so editing any scene, or new key art for the next video, stops every render in progress from resuming, and `--force` deletes its segments.
- loop_master's stem cache hashes tools/audio.py only, not audio_analyze.py or music.py, which audio.py imports. footage_loop's water cache hashes water_bed.py only, which imports audio.py. color_grade hashes its own file, and finish_video compares the mtimes of thumbnail.py and pixelfont.py. After T17 a change in a new audio module would leave old stems in cache/loop/ that look valid.

Do: hash the plate folder's contents, subfolders included (or a manifest each plate tool writes with content hashes). Hash only the rendered scene's folder, the scenes it imports and its own key art. One `code_hash(module)` in Python hashes a tool and every tool module it imports, transitively (T1's reference scan already finds them), for loop_master, footage_loop, color_grade and the fingerprint's Python part.

Check: replacing one steam frame changes the fingerprint, an edit to another scene doesn't, and an edit to audio_analyze.py misses the stem cache.

Watch out: changing the fingerprint function changes every fingerprint once. Do it when nothing is rendering.

Done 2026-10-26: `fingerprint()` hashes the plate through src/render/inputs.mjs (content, clip subfolders included, the checks' outputs left out), the rendered scene and the scenes it imports with their key art folders (critter sprites), assets/textures and assets/models, src/render/page.html, and the audio code through [tools/cozy/code.py](tools/cozy/code.py)'s `code_hash("audio", "music")`, which follows imports. loop_master's stems, footage_loop's water bed and color_grade's key use `code_hash`, and finish_video's mtime checks take the closure's files (`code_files`). [tests/test_inputs.py](tests/test_inputs.py) covers the plate hash, the scene closure and the code closure. A 20 s render passed QA, resumed without rendering a frame, and still resumed after another scene's scene.js changed. Every render folder made before this change needs `--force` or a new `--name` to render again.

### T10. tools/cozy/paths.py

Why: ROOT is defined in 51 tools in two spellings. sys.path is patched in 37, which a tool run as `python tools/x.py` doesn't need. The venv's Python is found two ways (art_edit.py and new_video.py prefer `.venv\Scripts\python.exe`, the rest use sys.executable). 139 scene, plate and key-art paths are built by hand in 36 files, and the config files are opened in 29 places. Five tools write scene.json (analyze_plate, autopilot, hand_region, pet_clips, plate_features) with two indent widths and two newline styles, so each rewrite reformats the whole file.

Do: tools/cozy/__init__.py and paths.py with ROOT, PY, scene_dir(), plate_dir(), keyart_dir(), out_dir(), config(name) and load_scene()/save_scene() in one format. Move a few tools per commit, smallest first, and leave the files T9 is about until T9 is done.

Check: T1 after each commit. The first save_scene() reformats each scene.json once: its timeline golden is then skipped until recorded again.

Done 2026-10-26 (6 commits): tools/cozy/paths.py has ROOT, PY, scene_dir(), plate_dir(), keyart_dir(), out_dir(), config(), load_scene() and save_scene() (indent 2, LF, written atomically), load_json() and rel(). Every tool takes ROOT and PY from it, and the five scene.json writers use save_scene(). The 139 hand-built scene, plate and key-art paths aren't rewritten yet: the helpers are there for the next change that touches them. [tests/test_paths.py](tests/test_paths.py).

### T11. tools/cozy/media.py

Why: 21 tools call ffmpeg or ffprobe directly. probe() is written 4 ways (loop_master, motion_review, rain_motion, upload_package), grabbing a frame 3 ways (critic, footage_loop, rain_motion), psnr() twice.

Do: probe(), grab_frame() and run_ffmpeg() with one error format, then move the callers over.

Watch out: a frame grab that feeds a QA number (PSNR at the joins, the seam check) must keep its filter and pixel format, or the thresholds in the lessons move. Compare the numbers on one render before and after.

Done 2026-10-26 (2 commits): [tools/cozy/media.py](tools/cozy/media.py); encodes, audio decodes, probes and every frame grab in 20 tools go through it. Old against new on existing renders, every QA number is identical: rain_motion on the ramen alley's loop window (mean 37.243), motion_review on the rainy café sample (0.003108), loop_master's hour join on the Burdock Shelter's 10 h build, footage_loop's seam PSNR (20.0729 and 20.0875), the thunder QA (2.88 dB over the bed). Five streaming ffmpeg pipes stay on subprocess. [tests/test_media.py](tests/test_media.py).

### T12. Shared code out of the CLI scripts

Why: tools import each other's insides. analyze_plate's SAM 2 Segmenter is used by 8 tools. plate_prep is imported by 9 tools for its mask helpers (region_raster, poly_mask, pixelize, pane_structure, flat_surface, DRY_KINDS). upload_package's voice rules (AI_WORDS, voice_problems) are used by 3 and intro_title's BRANDS by finish_video. fire_clips.py loads the Wan model through pet_clips.py, which is retired for pets. Two import cycles hide behind imports inside functions: analyze_plate with plate_features, outdoor_check with local_vision.

Do: tools/cozy/segment.py, masks.py, voice.py and wan.py. The old module re-exports the names for one round, the callers move, then the re-exports go. azure_ai.py moves last (22 importers) and leaves a one-line shim.

Check: T1. The cycles are gone when no tool needs an import inside a function to avoid one.

Done 2026-10-26: tools/cozy/segment.py, masks.py, voice.py and wan.py, plus llama.py (local_vision's server start and stop, which outdoor_check needed to end its cycle) and images.py. The 26 moved definitions are identical text, the old modules re-export them for one round, and every caller moved. Both import cycles are gone. Masks, occ maps and contours match on 3 plates. azure_ai.py stays where it is. Still to do: drop the re-exports once no note or skill uses the old names.

Done 2026-10-27, that round: the last callers moved (fire_clips and motion_review to cozy.plate, water_bed, audio_layers, autopilot and analyze_plate to cozy.audio, three tools from music.rel to cozy.paths.rel), and the 65 names that audio, finish_video, local_vision, upload_package, plate_prep and analyze_plate imported only to pass on are gone (ruff with the old noqa ignored found them). Every module now imports only what it uses.

### T13. Duplicate helpers

- The same code twice: rel() in finish_video.py and music.py, merge() in audio.py and water_bed.py, normal_map() in gen_leaves.py and gen_textures.py.
- The same name with different code, so read each before merging: slug() 3 times, poly_mask() 3 times, mmss(), load_json(), iou(), psnr() and lum() twice each.

Done 2026-10-26: rel() and load_json() are in cozy/paths.py, water_bed uses audio.merge(), normal_map() and lum() are in cozy/images.py, and iou() became box_iou() and mask_iou(). The slug, poly_mask, mmss and psnr copies behave differently and stay. The regenerated leaf textures are byte-identical.

### T14. Contracts written in both JS and Python: formulas pinned by a test, one list of types

Why: the picture is made in JS and GLSL and the sound and the checks in Python, and some rules exist in both. audio.py's `gust()` follows `windAt()` and its `flow()` is an "Exact copy of flowAt() in rain.js"; the gust flurry is in rain.js, timeline.js and audio.py. When one copy changes, the gust you hear drifts from the gust you see, and nothing fails. The types are plain strings too: autoscene.js picks one of 21 layer types through an if/else chain, and scene.json has no schema, only the header comment of autoscene.js.

Do:
- A test that runs the JS and Python versions at fixed times and compares them. flowAt() lives only in GLSL, so first give it a JS twin the shader string is built from. Longer term Node can write the sampled tracks into timeline.json for audio.py to read, which removes the copies.
- A layer registry in autoscene.js (type to module and function) and a JSON Schema for scene.json and timeline.json, checked when a tool writes them (T10's save_scene()), holding the one list of layer and event types.

Check: change one constant in the JS wind on purpose and the test fails; a scene.json with a misspelled layer type fails on save.

Done 2026-10-26: autoscene.js picks a layer from a registry (`LAYERS`). rain.js builds its shader's flowAt from the same constants as a JS twin (the generated GLSL is byte-identical), and [tests/test_parity.py](tests/test_parity.py) compares audio.py's gust(), flow() and flurry_env() with the JS at about 4,900 times in 4 scenes (26 runoff streams, worst difference 2e-12); changing one constant on either side fails it. [src/library/types.json](src/library/types.json) lists the 21 layer types, 22 event types and 23 scene keys; [tests/test_types.py](tests/test_types.py) holds autoscene, every timeline, every scene.json and every type comparison in the tools to it, and save_scene() refuses a scene with an unknown key or layer type (a key starting with _ is a note). Not done: a JSON Schema with the value types, and Node writing the sampled tracks for audio.py.

Fixed 2026-10-27: timeline.js `flurryEnv` (the vines' sway and the steam's drafts) capped a gust before its raised cosine and audio.py `flurry_env` after, so they differed while a gust was over 2 m/s. flurryEnv is now the sound's definition, min(|flurryWind| / 2, 1). Only the snowy cottage, a 2026-10-16 mock never published, has such gusts (5 at 2.13 m/s); every other scene's envelope was bit-identical before and after at about 290,000 times through every gust, and the 17 scenes' stills and the sound goldens are unchanged. At the snowy cottage's worst moment 0.2% of the frame (the cocoa's steam) moves by at most 2 levels. The parity test now holds the strong gusts too.

### T15. Split finish_video.py (2,072 lines)

It does three things: writes the title and description (facts() to draft_words(), about 400 lines), builds the thumbnail specs (class ThumbSpec, about 740) and runs the stages (class Finish, about 650).

Do: tools/cozy/publish/words.py and thumb_spec.py, next to the voice rules from T12. finish_video.py keeps Finish and main().

Check: T1, then draft the words and thumbnail specs for a finished scene into a scratch folder before and after, and diff them. Never write into a live upload/ folder.

Done 2026-10-26: tools/cozy/publish/words.py (facts() to draft_words(), 380 lines) and thumb_spec.py (ThumbSpec and its helpers, 796 lines); finish_video.py went from 2,067 to 926 lines and re-exports the 31 moved names. With the network, child processes and writes blocked and the chat model raising, the facts, prompts, words, word checks, thumbnail plans and specs of four scenes (618 KB of JSON) are identical before and after, and so are the dry runs. The tools tests now look inside tools/cozy's subpackages too.

### T16. Split plate_prep.py (2,169 lines)

It holds the image steps (upscale, depth, guided filter), the mask primitives, the weather masks (masks() alone is 245 lines, plus gap_fill, shelters, see_through, water_only), derain and the pixel grid, window and lantern lights (light_groups is 138 lines), the weather sources (runoff edges, drips, beads, strands, fire beds) and the pet maps.

Do: tools/cozy/plate/ with one module per group. plate_prep.py keeps main().

Check: T1, then `plate_prep.py --masks-only` on two plates gives byte-identical files before and after. It writes in place, so back the plate folder up first.

Done 2026-10-26: tools/cozy/plate/ (image, primitives, regions, weather, derain, lights, sources, pets); plate_prep.py went from 2,004 to 278 lines and keeps main() with a re-export of every moved name. On scratch copies, `--masks-only` wrote byte-identical files on six plates (the Burdock Shelter 50 of 50, the ramen alley 43 of 43, and the pixel, waterfall, snow and Treetop plates), and every moved function's bytecode is unchanged.

### T17. Split audio.py (1,278 lines)

It already has sections: signal helpers, impact kernels, event sounds, the Ambience renderer (about 630 lines) and the report.

Do: tools/cozy/audio/ with dsp, kernels, events and ambience. tools/audio.py stays the CLI and re-exports BEDS, Ambience, make_cfg, pan_gains and choose_bed, which autopilot, analyze_plate, water_bed and audio_layers use.

Check: T2's sound goldens identical to the bit on this machine.

Watch out: without T9 the stem cache keeps stale sound. VERSION stays the switch for the loudness calibration cache.

Done 2026-10-26: tools/cozy/audio/ (dsp, kernels, events, ambience); audio.py went from 1,276 to 136 lines, keeps main() and report(), and re-exports BEDS, Ambience, make_cfg, pan_gains, choose_bed, merge, write_wav, SR and VERSION (still 3). The 40 stems of 4 scenes at 2 starts (thunder, boats, cars, the loop join), 8 fresh loudness calibrations and 8 reports are byte-identical, and the sound goldens match to the bit. code_hash("audio") follows the package (T9 follow-up), so the stem cache and the render fingerprint see every module.

### T18. Break up the longest Python functions

analyze_plate.main (353 lines), loop_master.main (283), upload_package.main (254), review.lint (227), steam_sim.simulate (223), plate_features.main (168) and music_auto.run (160): each into named steps in the same order, with no logic change. One function per commit.

Done 2026-10-26 (7 commits): each is a short list of named steps in the old order. review.lint went from 227 to 17 lines, steam_sim.simulate 223 to 46, upload_package.main 253 to 38, music_auto.run 160 to 56, analyze_plate.main 358 to 33, plate_features.main 166 to 26, loop_master.main 283 to 40. Every removed line comes back unchanged apart from its indentation, no step reads a module global where the old function had a local, and the parameters a step reassigns are lists it extends in place. Old and new ran on the same inputs in a scratch folder and wrote the same files and output: lint for the 9 scenes with a scene.json, two small GPU steam runs, every upload spec, every look's music, analyze_plate and plate_features on every scene with SAM and the uncached vision calls stubbed, and 24 loop_master runs on synthetic renders. To keep the lines unchanged the steps take explicit parameters and return tuples, so a few signatures are long (22 parameters in loop_master._music); tidy one when it changes for a real reason. finish_video compares upload_package's file time, so it rebuilds upload folders once.

Done 2026-10-27, the other functions over 200 lines the review named (4 commits, each body moved unchanged):
- timeline ambientEvents (336 lines): one function per stream in the old order. tests/test_streams.py, recorded before the split, pins all 16 event types with every option on two synthetic specs, which no scene covers (the shooting star, pet acts, birds and a boat already out at the start); those and the 17 scenes' timelines are identical.
- critterLayer (209) and antLayer (239): named steps for the loads, samplers, meshes, the walk over a far edge, the render-target pass and the per-frame update. 36 stills where four scenes' critters crawl or their trails dry, and 39 of the ramen alley's ants walking, in single file, over the counter's far edge or hidden behind it, are byte-identical before and after (renders of those frames are identical run to run).
- cozy/plate/weather.py masks (245): 13 named steps. On all 12 plates the old and new masks are identical, and so are the files they write, their printed lines and the dry regions they mark (a changed constant shows up on the first plate).
- Left: dog3dLayer (542) and petSpriteLayer (230) are pet mocks (T21); plate_prep.main (191) and analyze_plate.draft_scene (187) are under 200.

### T19. plate.js shaders to their own file; split timeline.js

- plate.js is 858 lines, and lines 12 to 534 are its two GLSL strings (the fragment shader alone is 519 lines). Move them to plate.glsl.js the way engine/output.glsl.js is done, byte for byte.
- timeline.js has 1,124 lines and 20 exports used by 17 modules, and ambientEvents() alone is 335 lines. Split it into timeline/ (random and hashing, the weather track, lights and windows, flurries and wind, leaf and petal schedules, ambient events) behind an index.js that keeps every export.

Check: T1's timelines and T2's stills identical.

Done 2026-10-26: plate.glsl.js holds the two shaders byte for byte, and timeline.js re-exports src/library/timeline/ (random, lightning, weather, lights, wind, leaves, pet, spotlight, ambient, build) with the same 20 exports. Timelines and the 17 scenes' stills are identical.

### T20. One RNG and shared helpers in JS

- mulberry32 is written 5 times in 3 ways: engine/rng.js, timeline.js, and one `rng()` copied into fire.js, particles.js and rain.js (signed or unsigned state). They should give the same numbers for integer seeds. Prove it with a test over many seeds (negative, huge and fractional too) before pointing them all at rng.js.
- Copies to share: pixelsOf() in cat3d.js and dog3d.js is overlay.js's imagePixels(), avg() and dirLight() are in both cat3d.js and dog3d.js, quad() in particles.js is quadGeo() in steam.js, and loadTex() is in 5 layers with 3 bodies.
- Two Electron launchers: cli.mjs passes its runElectron() to renderMaster(), which ignores it and starts Electron with its own electron().

Check: T1, and T2's stills identical.

Done 2026-10-26: one mulberry32 (engine/rng.js) for the timeline, fire, particles, rain and petsprite (a sixth copy), proven equal for every seed each call site can pass; they differ only for negative fractional and huge seeds, which none passes. util.js and overlay.js hold the shared smooth, toLin, hash, loadTex, instancedQuad, dirLight, boxMean and imagePixels; the look-alikes that behave differently stay. [src/render/launch.mjs](src/render/launch.mjs) is the one Electron launcher. [tests/test_js_helpers.py](tests/test_js_helpers.py); stills identical.

### T21. Retire superseded code (needs Truman's OK)

About 8,100 lines that no video uses:
- the voxel engine with its scenes and tools, 3,568 lines in 17 files (superseded 2026-10-15 and "kept for reference")
- the pet mocks, 3,018 lines in 8 files: cat3d.js, dog3d.js, petsprite.js, pet_sprite.py and the 4 mock scenes ("kept as a mock, not used")
- the Phase 0 spikes, 1,539 lines, and scenes/treetop/scene.v1.js

Do: with his OK, tag the commit before (`pre-legacy-cleanup`) and delete them, or move them to legacy/ if he wants them close. Then engine.js stops building the voxel Builder and Foliage for plate scenes, and the ear and tail warps leave plate.js (T7 first).

Watch out: scenes/ and src/ are in the render fingerprint, and README, DECISIONS and the skills mention these paths.

Done 2026-10-27, the part that deletes nothing: engine.js loads the voxel builder and foliage only for a scene without a plate (treetop, lakeside, loft), so plate scenes no longer import or build them; the stills of all 17 scenes, the voxel three among them, are identical. The ear and tail warps stay in plate.js: Treetop, a published video, sets ear 18, tail 11 and thunderEar 0.75, so its scene could no longer be rendered as it was without them (T7 made the defaults 0 for every other scene).

The deletion itself waits for Truman in pull request #1: the voxel engine with its scenes, library, SDXL tools and texture pack, and the Phase 0 spikes (80 files, 5,570 lines; the tag `pre-legacy-cleanup` keeps them). The pet mocks are not in it: his call on 2026-10-21 keeps them as tools ("a moving pet comes back only if he asks"), and AGENTS.md asks before deleting his files.

### T22. Docs and file encodings that drifted

- README says Python is "not needed yet" and its Phase 0 spikes section reads as current. package.json's description says voxel. new_video.py's docstring still describes the flow autopilot replaced.
- 15 tracked files start with a UTF-8 byte order mark, among them src/cli.mjs (before its `#!` line) and electron-main.cjs; most of the rest go with T21. The first comment in .gitignore has a broken dash.

Watch out: these files are in the render fingerprint, so between renders.

Done 2026-10-26 (4 commits): README's goals, setup and repo map, package.json's description and new_video.py's docstring describe today's flow. No tracked file has a byte order mark or double-encoded characters any more (STATUS.md had 35), and .gitignore's first comment uses a colon. The skills, SETUP and the scene template point at the code's new homes after T12 to T19 (tools/cozy/audio, src/library/timeline/, cozy/plate, cozy/wan), and the add-an-event recipe says to list a new type in types.json. 65 tracked files are CRLF on disk only: git stores LF, and every hash normalizes line endings.

### T23. A linter that finds bugs, no reformatting

ruff with only the checks that find bugs (undefined and unused names, redefinitions, bare except) and no formatter. Reformatting changes the bytes the render fingerprint and the caches hash, and would have emptied T3's regex. Do it after T9.

Done 2026-10-26 (2 commits): [ruff.toml](ruff.toml) selects pyflakes (F) and bare except (E722), no style rules and no formatter; ruff 0.17.3 is in [requirements-dev.txt](requirements-dev.txt). It found 15 things, all dead code (unused locals and imports, an f-string with nothing to fill in), now gone, and no undefined name. [tests/test_lint.py](tests/test_lint.py) fails on any finding (a probe file with an unused import failed it) and is skipped where ruff isn't installed.
