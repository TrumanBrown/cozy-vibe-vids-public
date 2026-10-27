 Architecture

How cozy-vibe-vids is built as of 2026-10-26: what it does, what each part is responsible for, how data moves through it, and the technical debt that is left. It documents the code as it is. The plan and the rules live in [GOALS.md](GOALS.md), [DECISIONS.md](DECISIONS.md) and [AGENTS.md](../AGENTS.md).

The first version of this file (commit `57c3152`) was an audit of the code at `d2767d4`. The refactor in [TASKS.md](../TASKS.md) paid most of its five main findings down the same day, one task per commit, each shown to change no frame, sample or event. Section 4 says what changed, how it was proven and what is still open. Counts are from commit `c1b570f`.

## 1. System overview

cozy-vibe-vids makes 10 hour, 4K, 30 fps ambience videos for YouTube from a one-line idea. Each video is one AI key-art image. The pipeline turns it into a 4K plate with depth and masks, works out what in the picture should move, removes painted steam and flames, and animates it in code: rain and runoff, rain on glass, snow, fire, steam, water, mist, lights, birds, critters and a breathing pet. A seeded event timeline drives both the picture and the procedural ambience audio, with curated music under it. Rule-based and vision-model gates review a 5 minute sample before Truman sees it. After his OK a 20 minute window is rendered once, looped to 10 hours and packaged for upload.

It is a batch pipeline on one machine. There is no server, database or user-facing app. A coding agent in VS Code runs the scripts, reads their logs and fixes what the gates find. Truman's touch points are his one line, his OK on the sample, and the upload.

### Production paths

| Path | Starts from | Entry points | Used for |
|---|---|---|---|
| Plate | One AI key-art image | `tools/autopilot.py`, then `tools/finish_video.py` | All published videos and every sample |
| Footage | His own camera recording | `tools/footage_loop.py`, `tools/color_edit.py` | The aquarium |
| Voxel | A 3D scene built in code | `node src/cli.mjs` on `scenes/treetop`, `loft`, `lakeside` | Superseded (STATUS.md) |

### Stack

| Layer | Technology | Lives in |
|---|---|---|
| Renderer | three.js r186 (WebGL2 through ANGLE on D3D11) in a hidden Electron 44 window | `src/` |
| Encoding | ffmpeg: HEVC on NVENC from YUV 4:2:0 packed on the GPU, FLAC and AAC audio, stream-copy joins | `src/render/`, `tools/loop_master.py`, `tools/cozy/media.py` |
| Pipeline tools | Python 3.12 with numpy, OpenCV, Pillow, PyTorch (CUDA 12.8), diffusers, transformers, requests; exact versions in `requirements.lock.txt` | `tools/`, shared code in `tools/cozy/` |
| Local models | Depth Anything V2 Small (depth), Swin2SR x4 (upscale), SAM 2.1 (segmentation), Wan 2.2 TI2V-5B (fire clips), LAION CLAP (music likeness), Qwen3.5-9B on llama.cpp (first pass of the rain check); each pinned to a revision in `tools/cozy/models.py` | `cache/hf/`, `cache/llama.cpp/` |
| Cloud AI | Azure AI Services in `rg-cozyvibevids-img`, keyless through `az login`: gpt-image-2 and gpt-image-2.5-sunburst (key art, masked edits), gpt-6-sol (vision, chat), gpt-audio-1.5 (listening) | `config/azure.json`, `tools/azure_ai.py` (the one client) |
| Tests and lint | Python unittest, with Node running the JS side; ruff for undefined and unused names only | `tests/`, `ruff.toml` |
| Agent layer | GitHub Copilot in VS Code: always-on rules, 2 custom agents, 3 prompt files, 16 skills | `AGENTS.md`, `.github/`, `.agents/skills/` |
| Machine | Windows 11, Ryzen 7 7700X, RTX 4070 SUPER 12 GB; a WSL laptop as the second machine | [SETUP.md](SETUP.md) |

### Size

| Area | Files | Lines | At `d2767d4` |
|---|---|---|---|
| `tools/` (Python, `tools/cozy/` included) | 89 | 27,896 | 59 files, 26,203 lines |
| `src/` (JS with GLSL in strings) | 62, plus `types.json` | 13,839 | 47 files, 13,663 lines |
| `tests/` (Python and the Node helpers) | 16, plus 3 golden files | 1,807 | none |
| `scenes/` (JS) | 18, plus 9 `scene.json` | 1,296 | the same |
| History | 190 commits since 2026-10-15 | | 127 |

The code grew by about 1,900 lines, mostly module headers, tests and the parameter lists of extracted steps. The big pieces shrank: 6 files are over 900 lines (9 before) and the largest is 1,176 (2,169 before); 3 Python functions are over 150 lines (10 before).

### Rules the code enforces

- Time is `frameIndex / fps` and every random draw is seeded through one generator ([rng.js](../src/engine/rng.js); `Math.random` is replaced at start), so a frame renders the same alone or in sequence.
- Everything periodic completes whole cycles per loop. With `events.loop.period` (1200 s) the engine folds time so a 20 minute window repeats exactly, and the 10 hour master is that window copied 30 times.
- Renders run in 5 minute segments, each in a fresh Electron process, and resume from `render.json` only when nothing they depend on has changed: the code that draws, the code that makes the sound, this scene, and the content of its plate folder.
- A required input that is missing stops the render instead of drawing nothing, and a warning printed by any layer fails the render's QA.
- `scene.json` is written in one format, and a write with a key or layer type the renderer doesn't know is refused.
- Every Azure call is logged with an estimated cost in `out/azure_usage.jsonl`, and a sample run stops at its budget (`config/defaults.json`, 6 USD).

## 2. Component directory

### 2.1 Top level

| Path | In git | Responsibility |
|---|---|---|
| [AGENTS.md](../AGENTS.md) | yes | Rules every agent reads first: non-negotiables, working agreements, everyday commands |
| [README.md](../README.md) | yes | Intro, repo map, setup pointers |
| [TASKS.md](../TASKS.md) | yes | The refactoring plan (T1 to T23): why, what, how each was checked, and what is left |
| [package.json](../package.json) | yes | Node dependencies, pinned: electron 44.7.2, three 0.186.1 |
| [requirements.txt](../requirements.txt), [requirements.lock.txt](../requirements.lock.txt) | yes | What the tools import, and the exact versions the desktop runs (PyTorch from its own index, [SETUP.md](SETUP.md)) |
| [requirements-dev.txt](../requirements-dev.txt), [ruff.toml](../ruff.toml) | yes | ruff, and the checks it runs: undefined and unused names, redefinitions, bare `except:`. No style rules and no formatter |
| [skills-lock.json](../skills-lock.json) | yes | Versions of the third-party agent skills |
| [.github/agents/](../.github/agents/) | yes | Custom agents: Video Studio (makes and fixes videos), Media and Outreach (drafts promotion) |
| [.github/prompts/](../.github/prompts/) | yes | Slash commands `/new-sample`, `/finish-video`, `/record-published` |
| [.agents/skills/](../.agents/skills/) | yes | 16 agent skills: 8 written for this repo (procedures and references), 8 third-party |
| [.githooks/](../.githooks/) | yes | The pre-commit check for keys, user folders and private terms (`tools/secret_scan.py`) |
| [src/](../src/) | yes | The renderer: CLI, Electron host, engine, animation layers |
| [tools/](../tools/) | yes | The rest of the pipeline: one Python script per job, and the code they share in `tools/cozy/` |
| [tests/](../tests/) | yes | The free offline safety net and its goldens |
| [scenes/](../scenes/) | yes | One folder per video: brief, key-art prompts, scene definition |
| [config/](../config/) | yes | Catalogs and settings shared by every video |
| [assets/](../assets/) | yes | Key art and its hand data, publish and thumbnail specs, judge references |
| [docs/](./) | yes | Goals, decisions, status, records of published videos, archived sessions |
| [marketing/](../marketing/) | yes | Campaign log and post drafts (`marketing/private/` stays local) |
| [spikes/](../spikes/) | yes | Phase 0 renderer comparison: three.js in Electron against Godot |
| `out/` | no | Everything generated, plus pipeline state, logs and the reference stills of the picture goldens |
| `cache/` | no | Model weights (`cache/hf`, about 46 GB on this machine), llama.cpp, music analysis, fonts |
| `music/` | no | Music tracks with a license sidecar each, one folder per style |
| `upload/` | no | One folder per video for YouTube Studio; the masters are hard links |
| `.venv/`, `node_modules/` | no | Toolchains |

### 2.2 `src/`: the renderer

Entry and render host:

| File | Responsibility |
|---|---|
| [cli.mjs](../src/cli.mjs) | Commands `still`, `preview`, `timeline`, `render`, `guides`, `palette`. Builds the event timeline in Node (`writeTimeline`), launches Electron, muxes preview audio |
| [render/pipeline.mjs](../src/render/pipeline.mjs) | The `render` command: 5 minute segments, resume by fingerprint, audio jobs in parallel, FLAC and AAC encode, mux, credits, thumbnail stills, the QA report. Keeps every page message in `render.json` |
| [render/inputs.mjs](../src/render/inputs.mjs) | The content hash of a plate folder, subfolders included, check and preview images left out. Used by the fingerprint and the picture goldens |
| [render/launch.mjs](../src/render/launch.mjs) | The one Electron launcher, for `cli.mjs` and the pipeline |
| [render/electron-main.cjs](../src/render/electron-main.cjs) | Electron main process: a hidden window, a static file server for the repo on 127.0.0.1, drives the page through `executeJavaScript`, forwards every page message with its level |
| [render/page.js](../src/render/page.js) | The page: imports `scenes/<s>/scene.js`, runs the engine, writes stills, depth guides or video frames (three buffers, async readback) |
| [render/sink.cjs](../src/render/sink.cjs) | ffmpeg sinks: NVENC video from packed YUV 4:2:0, PNG stills |

`engine/`:

| File | Responsibility |
|---|---|
| [engine.js](../src/engine/engine.js) | The frame function: scene setup, `plate.json` read first (a missing one stops the render) and handed to autoscene as `ctx.plateMeta`, timeline, post chain (GTAO, bloom, tone mapping), output pass, time folding for loops, depth guides |
| [output.glsl.js](../src/engine/output.glsl.js) | Output shader: grade, vignette, dither, YUV packing, the pixel-art grid |
| [rng.js](../src/engine/rng.js) | The one seeded random generator (mulberry32 with forks) and the `Math.random` replacement |
| [builder.js](../src/engine/builder.js), [textures.js](../src/engine/textures.js), [foliage.js](../src/engine/foliage.js) | Voxel scene building: boxes, procedural textures, instanced leaves. `Engine.init` loads and builds them only for a scene without a plate (the three voxel scenes, T21) |

`library/`, by job:

| Group | Files | Responsibility |
|---|---|---|
| Scene assembly | [autoscene.js](../src/library/autoscene.js), [types.json](../src/library/types.json) | `autoscene.js` turns `scene.json` into a scene module: the layer registry (`LAYERS`, type to function), default effects per region kind (`REGION_FX`), pixel-art adjustments. `types.json` is the one list of layer types, event and pet-motion types and `scene.json` keys, read by the tools and the tests |
| Plate compositor | [plate.js](../src/library/plate.js), [plate.glsl.js](../src/library/plate.glsl.js), [overlay.js](../src/library/overlay.js) | One full-screen shader over the plate: sway, ripples, mist, flicker, switchable lights, lightning, the breathing pet. Its GLSL is in `plate.glsl.js`. `overlay.js` holds the shared plate texture cache, `loadTex`, `fetchJson` (a missing required input throws), `regions.json` lookups and GLSL helpers |
| Shared helpers | [util.js](../src/library/util.js) | `smooth`, `toLin`, `hash`, used by the layers in place of their own copies |
| Timeline | [timeline/](../src/library/timeline/), [timeline.js](../src/library/timeline.js) | The seeded event timeline (the event and pet-motion types listed in `types.json`), loop folding, the weather track, light schedules, in modules: random, lightning, weather, lights, wind, leaves, pet, spotlight, ambient, build. `timeline.js` re-exports them. Runs in Node (`cli.mjs`) and in the page |
| Weather | rain.js, glass.js, drips.js, leaves.js, petals.js, particles.js | Rain and roof runoff, rain on glass, drips, leaves, petals, snow, dust and embers. `rain.js` builds its shader's runoff `flowAt` from the same constants as a JS twin the parity test runs |
| Fire, steam, light | fire.js, steam.js, smoke.js, liquid.js, traffic.js, title.js, blink.js | Fire clips, simulated steam flipbooks, chimney smoke, drink surfaces, car lights, the opening line, the cast's blinks |
| Life | birds.js, perch.js, moth.js, critters.js, ant.js, fish.js, heron.js, boat.js | Birds in flight and on wires, the moth at a lamp, crawling critters, the ant, fish rises, the heron, boats and the lake camera |
| Pets, retired or mock | pet.js, petsprite.js, cat3d.js, dog3d.js | Generated pet clips (forbidden since 2026-10-18), sprite and 3D pet mocks |
| Voxel, superseded | blocks.js, props.js, effects.js, nature.js, structures.js, exteriors.js, creatures.js | Code-built voxel scenes |

### 2.3 `tools/`: the pipeline

| Group | Scripts | Responsibility |
|---|---|---|
| Orchestration | [autopilot.py](../tools/autopilot.py), [new_video.py](../tools/new_video.py), [finish_video.py](../tools/finish_video.py) | `autopilot`: one idea to a reviewed 5 minute sample in 16 resumable, budgeted stages. `new_video`: the stage commands autopilot calls. `finish_video`: an approved sample to the 10 h master, thumbnails, publish spec and upload folder (its words and thumbnail specs are in `cozy/publish/`) |
| AI access | [azure_ai.py](../tools/azure_ai.py), keyart.py, azure_provision.py, local_vision.py, listen.py | Azure chat, vision, image generation and edits with the spend log and budget guard, for every caller; key-art candidates (through `azure_ai.generate_image`); provisioning the resource group; the local llama.cpp vision judge; the audio model |
| Key-art edits | keyart_revise.py, art_edit.py, critter_concept.py | Masked revisions before and after the plate exists; concept stills for an idea |
| Plate build | [plate_prep.py](../tools/plate_prep.py), [analyze_plate.py](../tools/analyze_plate.py), plate_clean.py, plate_features.py, hand_region.py, mask_edges.py | `plate_prep` is the command line over `cozy/plate/`: upscale, depth and every mask the layers read. Regions from the vision model and SAM, and the draft `scene.json`; removing painted transients; placing birds, the moth and critter paths; adding missed regions; straight edges in masks |
| Assets for layers | steam_sim.py, fire_clips.py, critter.py, cast_eyes.py, intro_title.py, pixelfont.py | Steam flipbooks from a 2D fluid simulation, fire clips from the key art's own fire (Wan 2.2), critter sprites, eye maps for blinks, the opening-line image, the channel's pixel font |
| Sound | [audio.py](../tools/audio.py), audio_layers.py, audio_analyze.py, music.py, music_auto.py, music_fetch.py, music_screen.py, music_like.py, music_samples.py, mc_music.py, water_bed.py | `audio.py` is the command line over `cozy/audio/`, the procedural ambience in sync with the timeline. The music plan, credits and ledger rows; finding, screening and curating music for a look; the Minecraft allowlist; aquarium water |
| Gates and QA | [review.py](../tools/review.py), [critic.py](../tools/critic.py), critic_selftest.py, outdoor_check.py, weather_audit.py, leak_check.py, critter_ends.py, rain_qa.py, rain_motion.py, rain_analyze.py, motion_review.py, event_sheets.py, render_qa.py | Lint against the lessons; the vision judge with approved references, and its calibration; weather over indoor things, tile by tile; mask, leak and dry-pocket checks; still-motion and rain-motion maps; event contact sheets; frame comparisons for render QA |
| Long master and publishing | loop_master.py, thumbnail.py, upload_package.py, marketing_check.py | The 20 minute window looped to 10 h without re-rendering; thumbnails; the upload folder and its text rules; checks on promotion drafts |
| His own footage | footage_loop.py, color_edit.py (with color_edit.html), color_grade.py | Looping a recording to 10 h; a color editor in the browser; the grade |
| Repo care | secret_scan.py, go_public.py | The pre-commit check for keys and private terms; a cleaned public copy that never repeats the owner's chat messages |
| Superseded and mocks | gen_textures.py, gen_leaves.py, enhance.py, pet_clips.py, pet_sprite.py | SDXL textures and frame repaint for voxel scenes; pet clips (retired); pixel pet sprites (mock) |

### 2.4 `tools/cozy/`: code the tools share

A package with no command line. A tool run as `python tools/x.py` imports it with no `sys.path` patch.

| Module | Holds |
|---|---|
| [paths.py](../tools/cozy/paths.py) | `ROOT`, `PY` (the venv's Python for child processes), `scene_dir`, `plate_dir`, `keyart_dir`, `out_dir`, `config()` (read again on every call), `load_scene` and `save_scene` (one format, written atomically, checked against `types.json`), `load_json`, `rel`, `safe_name` |
| [media.py](../tools/cozy/media.py) | ffmpeg and ffprobe: probes, frame grabs, encodes, audio decodes, one error format |
| [models.py](../tools/cozy/models.py) | The revision every local model is loaded at |
| [code.py](../tools/cozy/code.py) | `code_files` and `code_hash`: a tool module's import closure, for cache keys and the render fingerprint |
| [segment.py](../tools/cozy/segment.py) | The SAM 2 `Segmenter` and the plate helpers that go with it |
| [masks.py](../tools/cozy/masks.py) | Mask helpers: region rasters, polygons, pixelize, window panes, flat surfaces, `DRY_KINDS` |
| [voice.py](../tools/cozy/voice.py) | Truman's voice rules for public text, the part a program can check |
| [wan.py](../tools/cozy/wan.py), [llama.py](../tools/cozy/llama.py) | The Wan 2.2 loader (fire clips); starting and stopping the local llama.cpp server |
| [images.py](../tools/cozy/images.py) | `normal_map` and `lum` |
| [plate/](../tools/cozy/plate/) | The steps of `plate_prep.py`: image and depth, primitives, regions, weather masks, derain (painted transients), lights, pets, sources (drops, flames, steam) |
| [audio/](../tools/cozy/audio/) | The ambience: `dsp`, `kernels` (impacts), `events` (event sounds), `ambience` (the `Ambience` renderer) |
| [publish/](../tools/cozy/publish/) | `words.py` (place name, thumbnail tags, publish text) and `thumb_spec.py` (`ThumbSpec`) |

### 2.5 `tests/`

`.venv\Scripts\python -m unittest discover -s tests` runs the default tier in about a minute, free and offline. `COZY_SLOW=1` adds the stills.

| File | Checks |
|---|---|
| [test_tools.py](../tests/test_tools.py) | Every tool and `cozy` module imports, and every cross-tool reference resolves |
| [test_scenes.py](../tests/test_scenes.py), js_scenes.mjs | Every JS module, scene and dynamic import loads in Node; each scene's timeline comes out the same twice and matches `goldens/timelines.json` |
| [test_goldens.py](../tests/test_goldens.py) | Sound: the ambience of 4 scenes at 2 starts against `goldens/sound.json`. Pictures (`COZY_SLOW=1`): 17 scenes at 3 frames against `goldens/stills.json`, with the reference images in `out/goldens/` |
| [test_inputs.py](../tests/test_inputs.py) | What decides whether a render or a cached file is still good: the plate hash, the scene closure, the code closure |
| [test_parity.py](../tests/test_parity.py), js_parity.mjs | The sound's wind, runoff and flurry formulas against the picture's, at about 4,900 times in 4 scenes |
| [test_types.py](../tests/test_types.py), js_types.mjs | `types.json` against autoscene, every timeline, every `scene.json` and every type comparison in the tools |
| [test_js_helpers.py](../tests/test_js_helpers.py), js_helpers.mjs | The shared JS helpers against the copies they replaced |
| [test_paths.py](../tests/test_paths.py), [test_media.py](../tests/test_media.py), [test_azure.py](../tests/test_azure.py) | `cozy.paths`, `cozy.media`, and the Azure client with the network mocked |
| [test_rules.py](../tests/test_rules.py) | Standing rules the code must keep: a painted pet only breathes |
| [test_lint.py](../tests/test_lint.py) | ruff over `tools/` and `tests/` (skipped when ruff isn't installed) |

### 2.6 `scenes/`

| Kind | Folders | Files |
|---|---|---|
| Plate scenes from data | blossom-teahouse-rain, leaf-campfire-rain, pixel-farmhouse, pixel-greenhouse-rain, rainy-cafe, ramen-alley, real-life-farmscape, snowy-cottage, wizard-library | `brief.json` (setting, pet, props, weather, place name, opening line, hero), `keyart.json` (prompts), `scene.json` (layers, events, audio, intro, post), `scene.js` (three lines: `autoScene(spec)`) |
| Plate scene by hand | treetop-plate | `scene.js` for the first published video |
| Footage | aquarium | `footage.json` (source, in point, grade); the recordings stay local |
| Voxel, superseded | treetop, loft, lakeside | `scene.js`, and `treetop/scene.v1.js` |
| Mocks | catmock-pixel, catmock-treetop, dogmock-greenhouse, petmock-greenhouse | A `scene.js` that wraps another scene and adds a moving pet |

### 2.7 `config/`

| File | Holds | Written by |
|---|---|---|
| [aesthetics.json](../config/aesthetics.json) | 19 looks: style prompt, avoid list, weather, motions, sound bed, music folders, fonts, thumbnail motifs, intro style, tier | People, and `autopilot.add_look` for a new look |
| [defaults.json](../config/defaults.json) | His settled defaults: event rates, loop period, music settings, sample length, budget, number of key-art candidates | People |
| [cast.json](../config/cast.json) | The channel's own creatures and the first cast video's four | People |
| [azure.json](../config/azure.json) | Endpoint, deployments, prices for the spend estimate | `azure_provision.py`, people |
| [local_vision.json](../config/local_vision.json) | The local model, its server, and which purposes may use it | People |
| [fonts.json](../config/fonts.json) | The channel's pixel font and the approved OFL fonts: source, license, feel | People |
| [minecraft_music.json](../config/minecraft_music.json) | The Mojang allowlist | People |

### 2.8 `assets/`

| Path | Holds | Written by |
|---|---|---|
| `keyart/<s>/` | Key-art candidates with JSON sidecars (prompt, model, time), `clean.png`, critter sprites | `keyart.py`, `plate_clean.py`, `critter.py` |
| `keyart/<s>.masks.json` | Regions and mask polygons | `analyze_plate.py` |
| `keyart/<s>.hand.json` | Hand fixes over `masks.json`: shelters, openings, extra regions | People, `hand_region.py`, `outdoor_check.py --repair` |
| `keyart/<s>.clean.json` | Painted transients to remove | `analyze_plate.py`, `plate_clean.py` |
| `publish/` | `<s>.json` publish specs (titles, description, thumbnails), his standing blurb, the channel page | `finish_video.py` once, then people |
| `thumbnails/<s>.json` | Thumbnail specs | `finish_video.py` once, then people |
| `reference/approved/`, `selftest/`, `styles/` | Critic references from his approvals, calibration cases, style references for looks | `critic.py --approve`, people |
| `textures/`, `models/quaternius/` | Voxel textures (superseded), a CC0 Shiba Inu model for the dog mock | |

### 2.9 `docs/` and the lessons

| Path | Holds |
|---|---|
| [STATUS.md](STATUS.md) | Current state per video; every agent reads its top first |
| [DECISIONS.md](DECISIONS.md), [decisions/](decisions/) | Dated decision log and the tech-stack ADR |
| [GOALS.md](GOALS.md), [REFERENCE.md](REFERENCE.md), [SETUP.md](SETUP.md) | Spec and roadmap, the reference video's analysis, machine setup |
| [ARCHITECTURE.md](ARCHITECTURE.md) | This file |
| [asset-ledger.csv](asset-ledger.csv) | Provenance of every external or AI-made asset |
| [records/](records/) | What went out, per video: `published.md`, `loop.json`, `music_plan.json`, `qa.md` |
| [history/](history/) | Archived sessions that grew too big to open |
| `research-*.md`, `CONCEPTS.md`, `IDEAS.md` | Research notes, concepts, ideas that need new code |
| [lessons.md](../.agents/skills/new-video/references/lessons.md) | 160 rows, one per revision he asked for (what he saw, the fix, the check); `review.py` and `critic.py` parse it |

### 2.10 Generated, not in git

| Path | Holds |
|---|---|
| `out/plates/<s>/` | The plate build, read by the renderer at render time: `plate.png`, `plate_off.png`, depth, masks, lights, regions, `plate.json`, `analysis.json` (the cached vision answer), `features.json`, `intro.json`, `eyes.json`, `fire/` clips, `steam/` flipbooks, `outdoor_check/` tiles. About 400 MB for the Burdock Shelter |
| `out/<s>/auto/` | autopilot's `state.json`, `progress.md`, one log per stage, `sample.md` |
| `out/<s>/render/<tag>/` | `render.json` (fingerprint, segment status, page messages), `timeline.json`, `music_plan.json`, `seg/`, `master.mp4`, `master_music.mp4`, `qa/`, `review/`, `critic/`, `thumbs/`, `credits.txt` |
| `out/<s>/` | `finish.md`, `finish_words.json`, `keyart_sheet.jpg`, `thumbnails/`, and loose check images from agent sessions |
| `out/samples/<s>/` | Samples for his review |
| `out/goldens/` | The reference stills the picture goldens compare against |
| `out/azure_usage.jsonl` | Append-only spend log; budgets and spend reports read it |

## 3. State and data flow

There is no database and no long-running service. State is files: JSON in git for what a person decides or tunes, files under `out/` for everything generated, and an append-only JSONL log for spend. Programs talk through those files, exit codes and printed lines. The only HTTP is local: the Electron main process serves the repo to the hidden render page on 127.0.0.1, and `color_edit.py` serves its editor to a browser (Save look writes `scenes/<s>/footage.json`).

### 3.1 From one line to the upload folder

```text
his one line ("generate me a new youtube video sample for <idea>")
  |
  v
tools/autopilot.py                        state: out/<s>/auto/state.json, progress.md
  look ............ config/aesthetics.json (may add a look)
  plan, keyart, pick, prep, analyze, clean, life
                    -> tools/new_video.py -> one script per stage
                    -> scenes/<s>/, assets/keyart/<s>*, out/plates/<s>/
  features ........ tools/plate_features.py
  setup ........... config/defaults.json applied to scenes/<s>/scene.json
  music ........... tools/music_auto.py or tools/mc_music.py -> music/<folder>/
  checks  (gate) .. tools/outdoor_check.py --repair, tools/review.py
  render .......... node src/cli.mjs render (5 minute sample)
  review  (gate) .. tools/review.py --render
  critic  (gate) .. tools/critic.py
  report .......... out/<s>/auto/sample.md, out/samples/<s>/
  |
  v
Truman's OK  (critic.py --approve adds the sample's evidence to assets/reference/approved/)
  |
  v
tools/finish_video.py                     log: out/<s>/finish.md
  check ........... review.py passes; loop period and intro present
  window .......... node src/cli.mjs render --from 20m --length 20m   (one loop period)
  master .......... tools/loop_master.py --times 30                   (10 h, nothing re-rendered)
  thumbs .......... assets/thumbnails/<s>.json -> tools/thumbnail.py
  publish ......... assets/publish/<s>.json (the chat model drafts, word rules check)
  package ......... tools/upload_package.py -> upload/<slug>/
  |
  v
Truman uploads (Private first); /record-published <link> -> docs/records/<slug>/
```

### 3.2 Sample stages: what each reads and writes

| Stage | Runs | Reads | Writes |
|---|---|---|---|
| look | `autopilot.resolve` (chat model) | `aesthetics.json` | The look id; a new look in `aesthetics.json` |
| plan | `new_video.py plan --auto` (chat model) | `aesthetics.json`, `cast.json`, every other brief | `scenes/<s>/brief.json`, `keyart.json` |
| keyart | `new_video.py keyart`, then `keyart.py` | `keyart.json` | `assets/keyart/<s>/*.png` with sidecars, `out/<s>/keyart_sheet.jpg` |
| pick | `new_video.py pick --auto` (vision model) | The candidates | `hero` in `brief.json` |
| prep | `new_video.py prep`, then `plate_prep.py` | The hero, `masks.json`, `hand.json` | `out/plates/<s>/` |
| analyze | `new_video.py analyze`, then `analyze_plate.py` (vision model, SAM 2.1), which reruns `plate_prep.py --masks-only` | The plate, the brief | `analysis.json`, `<s>.masks.json`, `<s>.clean.json`, `scene.json`, `scene.js` |
| clean | `new_video.py clean`, then `plate_clean.py` (image edit) and `plate_prep.py` | `clean.json` | `keyart/<s>/clean.png`, a rebuilt plate |
| features | `plate_features.py` (vision model, SAM) | The plate, `scene.json` | `features.json`, more layers in `scene.json` |
| life | `new_video.py life`, then `critter.py`, `fire_clips.py`, `cast_eyes.py`, `steam_sim.py` | Regions, the plate | Sprites, `fire/`, `steam/`, `eyes.json` |
| setup | `autopilot.st_setup`, `intro_title.py` | `defaults.json`, the brief, `aesthetics.json` | Rates, loop period, intro, music settings and sound bed in `scene.json`; `intro.json`, `intro.png` |
| music | `music_auto.py` or `mc_music.py` | The look's music folders | `music/<folder>/`, ledger rows |
| checks (gate) | `outdoor_check.py --repair`, `review.py` | `scene.json`, the plate | Fixes in `hand.json`, the tile cache |
| render | `node src/cli.mjs render --length 300s` | `scene.js`, `scene.json`, the plate, the music | `out/<s>/render/<tag>/` |
| review (gate) | `review.py --render` | The render | Review images and event sheets |
| critic (gate) | `critic.py` (vision model) | The render, approved references | `critic.md` and its evidence |
| report | autopilot | `state.json` | `sample.md`, `out/samples/<s>/` |

A failed gate exits with code 2 and its findings. The agent fixes the cause and resumes with `--from <stage>`. The review gate can also send the run back to `render` by itself, after `hand_region.py` adds a sway region for something the static check found frozen (at most twice per run).

### 3.3 Inside one render

1. `cli.mjs` imports `scenes/<s>/scene.js` in Node, reads `out/plates/<s>/plate.json` and builds the timeline with `timeline/`. It adds boat distance profiles and fish distances for the audio and writes `timeline.json`.
2. `pipeline.mjs` gets `music_plan.json` from `music.py plan` and fingerprints what the segments depend on: the code that draws (`src/engine`, `src/library`, the page and its sinks), the audio code with every tool module it imports (`cozy/code.py`), this scene and the scenes its `scene.js` imports with their key-art folders, the textures and models, the content of the plate folder (`inputs.mjs`), the timeline, the music plan and the settings. Line endings are normalized, so a commit or a checkout doesn't change it. QA scripts and other scenes are left out, so fixing a check or editing the next video doesn't block a resume. A mismatch with an existing `render.json` stops the run unless `--force` is given.
3. Audio jobs start on the CPU at below-normal priority. `audio.py` renders each segment's ambience (and the music mix) from `timeline.json` in 15 second blocks that join exactly.
4. Video segments run one at a time on the GPU, each in a new Electron process. The page imports `scene.js` again, seeds the RNG, reads `plate.json` once, builds the same timeline again and runs `scene.build(ctx)`. For plate scenes that is `autoscene.js`: `plateLayer` first, then each layer in `scene.json` order, looked up in `LAYERS`. Each layer fetches its textures and clips from `/out/plates/<s>/`, and a required file that is missing throws (`fetchJson`).
5. Each frame: `prefetch(t)` loads clip frames, `update(t)` calls every layer's animate function with folded time, the composer renders, the output shader packs YUV, an async readback hands the bytes to `sink.cjs`, and ffmpeg encodes them from stdin.
6. Segments are joined by stream copy, audio is encoded to FLAC and AAC, and `master.mp4` (ambience) and `master_music.mp4` are muxed. Then come credits (`music.py`), thumbnail stills, and QA: frame count and timestamps, segment joins against fresh renders, a determinism re-render, loudness, events per hour, and `page`, which fails when any layer printed a warning. Every page message is kept in `render.json` with the segments that printed it.

The timeline is computed twice from the same code and seed: in Node for the audio and the checks, in the page for the picture. They agree as long as both read the same `plate.json` and duration. The sound's own copies of the wind, runoff and flurry formulas are held to the picture's by `tests/test_parity.py`.

### 3.4 Where state lives

| Store | Writers | Readers | In git |
|---|---|---|---|
| `scenes/<s>/brief.json` | `new_video.py` (plan, pick), `autopilot.py` (`--from pick`) | Most tools | yes |
| `scenes/<s>/scene.json` | Through `cozy.paths.save_scene`: `analyze_plate.py` (draft), `plate_features.py`, `autopilot.py` (setup), `hand_region.py`, `pet_clips.py`. People | `autoscene.js`; `review.py`, `critic.py`, `finish_video.py` and others | yes |
| `assets/keyart/<s>.masks.json`, `.hand.json`, `.clean.json` | `analyze_plate.py`, `hand_region.py`, `outdoor_check.py`, `plate_clean.py`, people | `plate_prep.py` and the checks | yes |
| `out/plates/<s>/` | `plate_prep.py`, `analyze_plate.py`, `plate_features.py`, the life tools, `intro_title.py`, `cast_eyes.py` | The renderer at render time, the checks | no |
| `config/aesthetics.json` | `autopilot.py` (new look), people | 15 tools, most through `cozy.paths.config` | yes |
| `docs/asset-ledger.csv` | `autopilot.py`, `finish_video.py`, `music.py`, people | `music.py` (credits), `finish_video.py` (fonts) | yes |
| `lessons.md` | People and agents | `review.py`, `critic.py` (a regex over the table) | yes |
| `assets/reference/approved/` | `critic.py --approve` | `critic.py` | yes |
| `out/<s>/auto/state.json` | `autopilot.py` | `autopilot.py` | no |
| `out/<s>/render/<tag>/render.json` | `pipeline.mjs` | `pipeline.mjs` (resume), `loop_master.py`, `finish_video.py`, `review.py`, `event_sheets.py`, `music_samples.py` | no |
| `out/azure_usage.jsonl` | `azure_ai.py`, on every call | The budget guard, spend reports | no |
| `music/<folder>/*.json` | `music_fetch.py`, `mc_music.py`, `music_auto.py` | `music.py` | no |

### 3.5 Contracts between programs

| Contract | Producer | Consumers | Defined and checked by |
|---|---|---|---|
| `scene.json` | Python tools, people | `autoscene.js` | `types.json` (keys and layer types) and the header comment of `autoscene.js`; `save_scene` refuses an unknown key or layer type, `test_types.py` checks every scene |
| `timeline.json` | `cli.mjs` through `timeline/` | `audio.py`, `review.py`, `critic.py`, `event_sheets.py`, `finish_video.py` | `types.json` (event types); `test_types.py` checks every timeline and every comparison in the tools |
| Formulas in both languages | `timeline/wind.js`, `rain.js` | `cozy/audio` | `test_parity.py`: wind, runoff and the flurry envelope at fixed times |
| Plate files | `plate_prep.py` and the life tools | The layers, over local HTTP | The docstring of `plate_prep.py`; a missing required file stops the render |
| `render.json` | `pipeline.mjs` | `loop_master.py`, `finish_video.py`, `review.py`, `event_sheets.py`, `music_samples.py` | `pipeline.mjs` |
| Exit codes | `autopilot.py` | The agent | 0 sample ready, 1 failed, 2 gate, 3 budget spent, 4 a question for Truman |
| Printed lines | `review.py`, `outdoor_check.py`, `plate_features.py`, `hand_region.py`, Electron | `autopilot.py`, `pipeline.mjs` | Conventions: findings start with `- `, a crash is a `Traceback` line, counts are read from lines such as `hand_region: 2 added`, `ERROR` or `FATAL` fails a segment, and page messages arrive tagged `[page]`, `[page warning]` or `[page error]` |

### 3.6 Outside this machine

- Azure: every call goes through `azure_ai.py`, key art included. Every call is logged with an estimated cost, and autopilot stops a run before a paid stage once its budget is spent.
- Local models load from the Hugging Face cache at the revisions in `cozy/models.py`; `local_vision.py` starts and stops the llama.cpp server through `cozy/llama.py`.
- `music_fetch.py` downloads candidate music with license checks, and `mc_music.py check` reads the live Creator-Safe Playlist.
- Nothing is uploaded or posted by code. Truman uploads, and promotion is drafts only.

## 4. Technical debt: the top 5 and where each stands

The audit ranked these by risk to the output. Every refactoring commit was checked against goldens recorded before it: each scene's timeline, the ambience of 4 scenes at 2 starts (to the bit on this machine), and the stills of 17 scenes at 3 frames each (to within one level per channel). Each golden was broken on purpose once to prove it catches a change. Task numbers are [TASKS.md](../TASKS.md)'s.

### 4.1 Render inputs outside git and outside the resume check; missing ones failed quietly

Was: the fingerprint hashed the plate folder's file names and sizes, so new steam or fire clips let a render resume and mix old and new segments. Missing inputs drew nothing, and the page's warnings never reached the render log. Nothing was pinned.

Done:
- The fingerprint hashes the plate folder's content, its clip subfolders included, and only what this scene depends on (T9). A regenerated clip now stops a resume, and editing another scene no longer does. `cozy/code.py` follows imports, so caches keyed on a tool's code (loop_master's stems, footage_loop, color_grade, finish_video) see every module it runs.
- `fire.json`, `steam.json`, `intro.json` and `eyes.json` are required inputs, every page message reaches the render log and `render.json`, and the QA `page` check fails on any layer warning (T6).
- `requirements.lock.txt` holds the desktop's exact versions, and every local model loads at a pinned revision (T8).

Still open:
- The plate is still made by GPU models and cached Azure answers that live only in this machine's `out/plates/`. The hashes catch a change, but a lost folder can't be rebuilt to the same bytes.
- The WSL laptop has no lock of its own: it needs the Linux torch wheel of the same version.

### 4.2 Logic and data contracts written twice, in JS and Python

Was: the wind, runoff and flurry formulas were in GLSL, JS and Python with no test between them, and layer and event types were plain strings in 17 Python tools with no schema.

Done:
- `tests/test_parity.py` runs the sound's `gust()`, `flow()` and `flurry_env()` against the JS at about 4,900 times in 4 scenes; the worst difference is 2e-12. `rain.js` builds its shader's `flowAt` from the same constants as a JS twin (the generated GLSL is byte-identical) (T14).
- `src/library/types.json` lists the 21 layer types, 22 event and pet-motion types and 23 scene keys. `test_types.py` holds autoscene, every timeline, every `scene.json` and every type comparison in the tools to it, and `save_scene` refuses a scene with an unknown key or layer type (T14).

Still open:
- The flurry envelope differed (fixed 2026-10-27). `timeline.js` capped a gust before its raised cosine and the sound after, so they disagreed while a gust was over 2 m/s; only the snowy cottage, an unpublished mock, has such gusts. The picture now uses the sound's definition, every other scene is bit-identical, and the parity test holds the strong gusts too.
- The sound and the rain shader round `gustCycles` to whole numbers and the timeline's `windAt` doesn't. Every scene uses whole numbers today, so nothing differs yet.
- The formulas are still written twice, now pinned by a test. Node could write the sampled tracks into `timeline.json` for the sound to read, which would remove the Python copies. `critter_ends.py` is still a Python port of `critters.js` path ends with no parity case.
- `types.json` lists names only. A JSON Schema with the value types is not done.

### 4.3 Copy-pasted plumbing in place of shared modules

Was: 37 scripts patched `sys.path`, 51 defined their own `ROOT`, 21 spawned ffmpeg directly, two Azure clients had different retry rules, scripts imported whole scripts for one symbol (with two import cycles), and the JS had six RNG copies and two Electron launchers.

Done:
- `tools/cozy/` (2.4). No tool patches `sys.path`, and every tool takes `ROOT` and `PY` from `cozy.paths` (T10). Probes, frame grabs, encodes and audio decodes in 20 tools go through `cozy.media`, with every QA number identical before and after (T11). The SAM wrapper, mask helpers, voice rules, Wan loader and llama.cpp server moved out of the scripts that owned them, and both import cycles are gone (T12). The exact duplicates are one function each (T13).
- `keyart.py` generates through `azure_ai.generate_image`: one token, one spend log, one set of retry rules (T4).
- One `mulberry32` in `rng.js`, shared helpers in `util.js` and `overlay.js`, one Electron launcher (`launch.mjs`) (T20).

Still open:
- 140 scene, plate and key-art paths in 38 tools are still built by hand from `ROOT`. The helpers are in `cozy.paths` for the next change that touches each one.
- The re-exports are gone (2026-10-27). Every caller imports a moved name from its home in `tools/cozy/`, and `audio.py`, `finish_video.py`, `local_vision.py`, `upload_package.py`, `plate_prep.py` and `analyze_plate.py` import only what they use themselves.
- Left on purpose: five streaming ffmpeg pipes stay on `subprocess`; the `slug`, `poly_mask`, `mmss` and `psnr` look-alikes, and the two JS deep merges, behave differently and stay.

### 4.4 Big modules that grew one complaint at a time, with no tests

Was: `finish_video.py` 2,072 lines and `plate_prep.py` 2,169, functions up to 353 lines, layers picked by a 21-branch if/else, and no tests, CI, linter or formatter.

Done:
- `tests/` (2.5): 48 tests in about a minute, free and offline, plus the stills of 17 scenes with `COZY_SLOW=1` (T1, T2 and every task after). ruff checks for undefined and unused names and bare `except:`, with no style rules, so it never changes bytes the caches hash (T23).
- `finish_video.py` is 926 lines, with its words and thumbnail specs in `cozy/publish/` (T15). `plate_prep.py` is 278, its steps in 8 modules of `cozy/plate/`; the masks of 6 plates are byte-identical (T16). `audio.py` is 136, the ambience in `cozy/audio/`; 40 WAVs are byte-identical (T17). The plate shaders are in `plate.glsl.js` and the timeline is 10 modules (T19). `autoscene.js` picks layers from `LAYERS` (T14).
- The seven longest functions are named steps in the same order: `analyze_plate.main`, `loop_master.main`, `upload_package.main`, `review.lint`, `steam_sim.simulate`, `plate_features.main`, `music_auto.run` (T18).

Still open:
- Two Python functions are still over 150 lines: `plate_prep.main` (191) and `analyze_plate.draft_scene` (187); `masks` (245) and the three JS functions over 200 that video code uses (`ambientEvents`, `antLayer`, `critterLayer`) became named steps on 2026-10-27. T18's steps kept every moved line as it was, so they take explicit parameters and return tuples, and a few signatures are long (22 parameters in `loop_master._music`). Tidy each when it changes for a real reason.
- `lessons.md` (160 rows) is still parsed by a regex, and a lesson's check is found by prose. A registry of check functions keyed by lesson ID, each with a small fixture, is the next step.
- The sound bed is still chosen by substring ("porch", "veranda") in `autopilot.st_setup`.
- Nothing runs the tests automatically. AGENTS.md asks for them before and after any code change; a commit hook would add a minute to every commit.
- The vision judges' self-tests spend Azure credit, by design.

### 4.5 Retired and forbidden features still in the live path

Was: about 7,300 lines in `src/`, `tools/` and `scenes/` that STATUS.md calls superseded or the rules forbid, with ear flicks and tail twitches on by default for any pet, and the fire clips loading their model through the retired pet tool.

Done:
- The timeline's ear, tail and thunder-ear defaults are 0, and `analyze_plate.py` drafts sighs only; `test_rules.py` holds it (T7).
- The Wan loader is in `cozy/wan.py`, so `fire_clips.py` no longer imports `pet_clips.py` (T12).
- README, `new_video.py`'s docstring and `package.json` describe today's flow (T22).

Still open, needs Truman's OK (T21): about 8,100 lines no video uses, counting the spikes. The voxel engine with its scenes and tools (3,568 lines in 17 files), the pet mocks (3,018 in 8), the Phase 0 spikes (1,539) and `scenes/treetop/scene.v1.js`. Since 2026-10-27 `engine.js` loads the voxel `Builder` and `Foliage` only for the three voxel scenes, so plate scenes no longer build them. The ear and tail warps stay in `plate.js` while Treetop, a published video, uses them.

### Smaller findings

| Finding | Status |
|---|---|
| A stage counts as done when its output file exists, so a new hero or a changed `hand.json` doesn't redo later stages unless someone passes `--from` (`autopilot.py`: `st_keyart`, `st_prep`, `st_analyze`, `st_features`) | Open |
| `scene.json` had five writers with different formats | Fixed: `save_scene`, indent 2, LF, written atomically and checked (T10, T14) |
| Process trees run four deep, and results come back as printed lines | Open, by design; the conventions are in 3.5 |
| The Python interpreter was chosen three ways | Fixed in the tools (`cozy.paths.PY`); `cli.mjs` looks in the same order |
| BOMs in 15 files, mojibake in 7 | Fixed (T22). 65 tracked files are CRLF on disk, but git stores LF and every hash normalizes line endings |
| README was behind | Fixed (T22) |
| The docs every agent loads are large (STATUS.md, lessons.md 106 KB, DECISIONS.md) | Open |
| `preview` assumed 30 fps instead of reading the scene's fps | Fixed |
| Seven layers (boat, drips, leaves, particles, petals, petsprite, rain) fetch `plate.json` again instead of using `ctx.plateMeta` | Open. Harmless today: the engine has already stopped the render if it's missing |
| Importing `gen_leaves.py` rewrote textures, and `rain_analyze.py` ran on import | Fixed: both run from `main()` (T5) |
| `motion_review.py` returned None on any exception, so a broken import quietly weakened a QA gate | Fixed: it catches only `ImportError` and `FileNotFoundError` and prints a `note:` line saying which measure it ran without (T5) |
| A render page module that failed to load left the renderer waiting forever, and Electron ended a failed run with exit code 0 | Fixed 2026-10-27: the run ends with the page's error, exits 1, and `tests/test_render_start.py` holds it |
| The security change that made model names plain (2026-10-26) turned "shield bug" into `shield_bug`, which no creature table knew: the bug was drafted at a snail's pace and review's L112 failed the scene's own signature critter, stopping autopilot at the checks gate | Fixed 2026-10-27: `cozy.paths.creature_id()` is the one form for the sprite's file name, every creature table and review's comparison; `tests/test_creatures.py` holds the tables and the scenes to it |
| A tool stopped by the daily Azure cap exited 1 without a traceback, so autopilot reported an empty gate ("NEEDS FIX at critic:", resume `--from render`) or skipped the music | Fixed 2026-10-27: the run stops with exit 3 and the cap's own line, as at its budget; `tests/test_autopilot.py` |

## 5. Keeping it clean

- Run the tests before and after any code change, with `COZY_SLOW=1` when the picture code changes. Record a golden again only after a deliberate change to the output, never to make a refactor pass.
- Shared code goes in `tools/cozy/` or in `src/library/util.js`, `overlay.js` and `src/engine/rng.js`. A second copy of a helper is a bug.
- Write `scene.json` only through `cozy.paths.save_scene`. A new layer or event type goes in `types.json` first.
- A formula the picture and the sound both use gets a case in `tests/test_parity.py`.
- ruff checks for bugs only. Don't add a formatter: it would change the bytes every cache and fingerprint hashes.
