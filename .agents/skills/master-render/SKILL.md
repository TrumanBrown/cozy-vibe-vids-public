---
name: master-render
description: 'Segmented, resumable 4K master render of a scene with node src/cli.mjs render (src/render/pipeline.mjs), and the default 10 h upload built by looping an approved test hour with tools/loop_master.py (no rendering, seamless audio joins): flags (--duration, --from/--length test windows, --segment, --name, --seed, --music, --audio-jobs, --cq, --codec, --qa, --thumbs, --force, --keep-wav), output folder layout, resume and fingerprint rules, the qa.md checks (frames, joins, determinism, loudness, thunder, A/V sync), disk and time budgets, troubleshooting, the YouTube upload checklist and click-worthy thumbnails (tools/thumbnail.py: a lightning-lit frame, punchy grade, the channel''s own pixel font, 3 variants for Test & compare). Use when: rendering a 1 h test, making the 10 h video (loop the hour or a full render), resuming after a crash, sleep or Windows Update restart, a fingerprint mismatch error, a QA FAIL in qa.md, estimating disk space or render time, choosing quality (CQ) or codec, making thumbnails, or preparing the upload (master.mp4, thumbnails, credits.txt, timeline.json, qa.md) and cleaning up seg/.'
argument-hint: 'scene folder and length, e.g. "scenes/treetop-plate --duration 10h" or "--from 8h --length 1h"'
---

# Master render: segmented, resumable, self-checking

**After Truman's OK on an autopilot sample, one command does this whole skill:** `.venv\Scripts\python tools\finish_video.py <scene>` (the loop window, the 10 h with music, thumbnails, the publish spec in his form and the upload folder; resumable; report in `out/<scene>/finish.md`; `/finish-video <scene>`). The sections below are what it runs, for fixing a stage or doing one by hand.

One command rebuilds a whole video from the scene config and seed: `node src/cli.mjs render scenes/<scene>`. It writes the timeline and music plan, renders 5 min video segments on the GPU (three.js in Electron → NVENC HEVC) while `tools/audio.py` renders the matching audio segments on the CPU, encodes the audio once, muxes the master with stream copy, then makes thumbnails, `credits.txt` and a QA report. Re-running the same command resumes. Code: `src/render/pipeline.mjs`. Design: `docs/DECISIONS.md` 2026-10-15 "Long-render pipeline".

## Before you render

- [ ] The user approved the previews at the current checkpoint (GOALS ladder: 10 s → 5 min sample → the 40 min preview with music → 10 h). Since 2026-10-19 the 10 h video is a 20 minute window looped (below); the old ladder rendered a 1 h test.
- [ ] Scene QA passes: `tools/rain_qa.py --leak --seam --flash` and `tools/audio.py ... --report` (plate-weather, ambience-audio).
- [ ] Music decided and picked by Truman from clips (new-video STOP 3): the scene's music folders hold the tracks (scene.json `audio.music.dirs`, else the look's `music_dirs` in config/aesthetics.json; none = ambience only; Minecraft looks: the Mojang allowlist in `music/` via `tools/mc_music.py check` + `import`). The music plan is part of the fingerprint; adding tracks later means re-rendering (`--force`) or a manual re-mux. For a looped upload, `loop_master.py` plans the music itself.
- [ ] Assets logged in `docs/asset-ledger.csv` (key art, music via `tools/music.py ledger`).
- [ ] Disk: ~11 GB per hour of master plus the same again for segments; keep ~250 GB free for 10 h (`Get-PSDrive C`).
- [ ] Machine: plugged in; Windows Update paused or active hours set; no other GPU work (previews, stills, games) during the render.
- [ ] Nothing will edit fingerprinted files during the render (see Resume): not this scene, not other scenes, not key art, not the library or audio code. Each segment starts a fresh Electron process and loads the code then, so an edit mid-render silently mixes code versions within one video (resume would catch it, a running render doesn't). Docs, skills and QA scripts are safe to edit.

## Commands

```powershell
node src/cli.mjs render scenes/<scene> --from 20m --length 20m --name loop20_<v> --music off   # the 20 min loop window (scene.json events.loop.period 1200)
.venv\Scripts\python tools\loop_master.py out\<scene>\render\loop20_<v> --times 2 --name preview_40min   # 40 min with the title and music: for his ears
.venv\Scripts\python tools\loop_master.py out\<scene>\render\loop20_<v> --times 30 --name 10h_<v>       # the 10 h upload, once he approved the sound
node src/cli.mjs render scenes/<scene> --from 8h --length 1h        # a test hour cut from the real 10 h master (same frames and timeline)
node src/cli.mjs render scenes/<scene> --duration 1h                # a standalone 1 h video with its own 1 h timeline
node src/cli.mjs render scenes/<scene> --duration 10h               # the full master (default length = the scene's duration)
.venv\Scripts\python tools\loop_master.py out\<scene>\render\<tag> --times 10   # the older hour loop (scenes without events.loop, e.g. Treetop); + master_music.mp4 when the scene's music folders have tracks
.venv\Scripts\python tools\loop_master.py out\<scene>\render\<tag> --preview 7m-11m "--ambience-db=0,-2,-3.5"   # sound check on short clips first, then build once (add --offset 5m to both to open on the busy part)
```

## The 10 h upload: a 20 minute seamless loop (the default since 2026-10-19)

Decided 2026-10-19: a 10 to 20 minute render, looped, is enough for the 10 hour video. Key events matter, but none is so rare that it happens less than 3 to 6 times an hour; what matters is that the music changes smoothly and nothing jumps on screen where the loop joins.

- **The timeline repeats** (scene.json `events: {"loop": {"period": 1200}}`, src/library/timeline/build.js `loopTimeline`): one 20 minute period of events is generated; what spills past its end (a boat still crossing, thunder rolling) comes back at its start, and early events that would clash with that spill-over are dropped (one ant, boat, moth, lantern or critter at a time; perch slots; minimum gaps). The weather track and storms wrap too. The period must be a whole number of `loopSeconds` (1200 = 10 × 120) and every event type needs a rate of 3 an hour or more, so each period holds it (review.py L54).
- **The picture repeats exactly:** the engine folds time into the period for every layer (`ctx.realTime()` keeps the real time for the title). Frames t and t + 1200 s are bit-identical; loop_master's `loop_seam` check renders the frame just past the window and its first frame and compares them (max diff must be ≤ 2; ramen: 0).
- **The sound repeats exactly:** tools/audio.py folds time the same way and crossfades its rain and runoff bed over the first 3 s of each period from the stream running on (thunder and event sounds are identical waves and pass as they are; blending identical waves would swell them 3 dB). The pipeline leaves the window's edges unfaded, and loop_master plays its FLAC back to back with fades only at the video's real start and end. Ramen: each period identical to the last bit, the level steady within 0.1 dB across the join.
- **Render the window one period in** (`--from 20m --length 20m`): the picture and sound of [1200, 2400) are the same as every other period, and audio.py's own fades at 0 stay out of it. Segments of 300 s.
- **The title** (scene.json `intro`, tools/intro_title.py, src/library/title.js) shows only at the video's real start: loop_master renders the first segment again with `--params intro=<t0>` into `<window>_intro_at<t0>/` and puts it first. It re-renders when the title changes (intro.json's key, the segment's `intro_key.txt`). `--intro off` leaves it out.
- **Music** is planned over the whole 10 h (never repeating with the picture), with the scene's `audio.music` settings read fresh from scene.json: `order: "smooth"`, the `opener`, `body_db` and `fit` (ambience-audio skill). QA adds `music_transitions`: the level over each of the first 24 track changes against the 10 s on each side; a fitted plan fails with a dip over 6 dB.
- **Cost:** the window renders in about 10 minutes of GPU; the 40 minute preview takes about 10 minutes (the intro segment ~3, the music mix ~5); the 10 h build about 30-60 min (stream copy, the music mix of 10 h on the CPU). Size depends on the rain: Treetop is ~110 GB per file, the ramen alley 250 GB (55.6 Mbps at cq 19), and there are two files (master.mp4 and master_music.mp4), so check free disk first. Keep cq 19 while the file fits YouTube's 256 GB limit: cq 23 smoothed the ramen alley's faint sky rain against a lossless still (lessons L59; upload_package refuses a file over the limit).
- Everything below about the hour loop still applies to scenes without `events.loop` (Treetop).

## The older hour loop (Treetop, and scenes without events.loop)

Decided 2026-10-16: instead of rendering 10 h, loop an approved 1 h window ten times; the video is background ambience. Render a 1 h window with `--from <h> --length 1h`, get it approved, then run `tools/loop_master.py <render dir> --times 10`. It takes ~15 min and renders nothing:

- **Video:** the hour's `seg/` files listed 10 times, stream copy (the pipeline's own mux), so keep `seg/` until the loop exists. A window is a whole number of 120 s base loops, so rain, sway, flicker, breathing and waterfalls line up at every join.
- **Audio:** a window's ambience has fades at its edges (1.5 s in, 2 s out); repeated as is, it would dip ~17 dB every hour. The tool re-synthesizes the unfaded seconds and the hour's continuation with `tools/audio.py` (random access: they must match the render's FLAC to ≤ 8 LSB, else it stops, e.g. after code changes). It then crossfades them over 3 s (`--xfade`) and encodes AAC 384k once. The first fade-in and the last fade-out stay.
- **Each hourly join** shows only slow state steps:
  - lights switched during the hour come back on;
  - the weather track's rain and wind level steps once.

  Choose a test hour whose end state is close to its start (few lights switching near its end, similar rain level) if the join matters.
- **The window must come from the middle of the video**, so `audio.py`'s own master fades at 0 and the end don't reach the edges.
- **Output:** `out/<scene>/render/10h_loop_<tag>/` with `master.mp4` (~110 GB), `ambience.m4a`, `credits.txt`, `thumbs/`, `loop.json`, `qa.md` (+ `master_music.mp4`, `music_mix.m4a`, `music_plan.json` with music).
- **QA (`qa.md`):**
  - exact frame count and A/V length;
  - the frames at the first join decode identical to the hour's end and start;
  - the audio join has no level dip (< 3 dB) and no step;
  - loudness −20 ± 1.5 LUFS, true peak ≤ −1.5 dBTP.
- **Music (`--music auto`, the default):** with tracks in the scene's music folders (Minecraft: `tools/mc_music.py import` into `music/`), the tool also writes `master_music.mp4`. That's the same video with `music_mix.m4a`.
  - The playlist (`music_plan.json`) is planned over the whole looped length, so it doesn't repeat with the hour.
  - It's mixed over the looped rain in 60 s chunks through the music limiter; chunk joins are sample-exact.
  - **The encode is checked, not just the mix** (2026-10-20). The limiter holds the mix to −2.5 dBFS, but AAC can overshoot a sharp transient by 3 to 4 dB: the ramen 10 h decoded at +0.8 dBFS on one drum hit in Blue Skies at 4:56:41, while its other 7 plays stayed under (it depends on where the hit falls in the encoder's frames), so the 40 minute preview passed and the 10 h failed `music_loudness`. Now `overshoots()` decodes the finished `music_mix.m4a` from the start, as a player does, and finds every 100 ms block over −2 dBTP (4x oversampled). Each one gets a lower limiter ceiling for ±50 ms, by its excess plus 0.5 dB, and the mix is encoded again, up to 3 passes. Nothing else changes, sample for sample, so the sound that was approved stays. `loop.json` lists them under `music.limited_spots`. Seeking into these m4a files shifts the decode by a few ms, so measure peaks from a full decode. Re-encoding shifts the encoder's choices a little, so a later pass can find a few new spots (ramen: 8, then 3 near −1.8, then clean at −2.0 dBTP).
  - **Disk:** the mux writes the new `master_music.mp4` next to the old one before swapping, so the build needs a whole video's worth of free disk (ramen: 250 GB) and checks for it before the mix. If the old music master is being replaced anyway (it failed QA), delete it first. A finished mix is stamped (`music_mix.new.json`: plan, window, levels, spots), so after a failed mux a re-run goes straight to the mux.
  - QA adds `music_length_sync`, `music_hour_join_audio` (no step) and `music_loudness`. The mix must land within 1.5 LU of `music.mix_target`: the measured ambience lowered by `ambience_db`, plus the music bus (−15.4 nominal for −20 / −2 / −16.5; it measures ~−16, since gating counts the music's quiet passages). True peak ≤ −1.5 dBTP.
  - `--music-lufs <level>` sets the music bus, and `--ambience-db <dB>` sets the rain under music (default −2). Either changes the plan, so only `master_music.mp4` is rebuilt.
  - `credits.txt` then lists the music. Log the tracks first: `tools/music.py plan` on the hour's timeline (`--out` outside the render folder), then `ledger`.
- **Sound first** (user 2026-10-16: settle the sound before any 10 h video is rendered again). Before any build that changes audio, make short clips and get them approved:
  - `--preview 7m-11m --ambience-db=0,-2,-3.5` writes `preview_music_<window>_rain<dB>.mp4`, one per level.
  - The clips are frame-exact (the picture is re-encoded with NVENC, ~1–2 min per 5 min of clip) and carry exactly the music mix the 10 h file will have there.
  - Pick a window with thunder and a song change, plus `--preview 0-1m30s` for the opening.
  - Nothing else is written. Delete the clips once the choice is made, so the upload folder stays clear.
  - **Approval means listening.** The user's choice in a form ("−2 dB") is not approval of the sound.
    1. Make clips of exactly the chosen settings (level, opener, `--offset`).
    2. Wait for "yes" after the user has heard them.
    3. Then build.
    
    (2026-10-16: a build started straight from form answers had to be stopped.)
- **`--offset 5m` starts the video 5 minutes into the hour.** It must be a multiple of the segment length, and needs no rendering. Use it to open on the busy part of the hour (user 2026-10-16: the start is when people look hardest).
  - The segment list starts at that segment and wraps.
  - The audio reads the same seamless loop 5 minutes later, with fresh linear fades (1.5 s in, 2 s out) at the video's own start and end.
  - The hour joins move to 55:00 + n h; QA checks the first one there. Event times in the video are the hour's times minus 5 minutes (mod 60).
- **Re-running is cheap:** a `master.mp4` that passed QA with the same source, `--times`, `--xfade` and `--offset` is kept, since it may be uploading. So is a `master_music.mp4` with the same music plan. `--force` rebuilds both.
  - New files are written as `*.new.*` and swapped in when complete. The plan and `credits.txt` are written last.
  - So a stopped run leaves the previous, matching set. A file that's open in another program (an upload) stops the swap with a message.
- A full `--duration 10h` render (~4 h, ~200 GB with segments) is still possible when a video's slow evolution matters (lights going dark over the night, no hourly repeat).

Pick the test hour from `node src/cli.mjs timeline scenes/<scene>` (the CP4 test used hour 8 of seed 11: 4 strikes incl. a near one, the boat, a lantern gutter, 17 cat motions; hour 0 had 1 strike and no boat). Also pick where the loop starts (`--offset`): the first 5 minutes should be the richest of the hour (a storm cell, a spotlight event, fish jumps, a gust; ambient-events "Strong opening"). A `--duration 1h` video is a real 1 h video with its own events inside the hour, not the first hour of the 10 h timeline.

| Flag | Default | Meaning |
|---|---|---|
| `--duration` | scene `duration` (Treetop 36000 s) | video length: `10h`, `90m`, `300s` or seconds; also the timeline's length |
| `--from`, `--length` | whole video | render only the window [from, from + length) of the full video; the audio gets 1.5 s / 2 s fades at the window edges |
| `--seed` | scene `seed` | overrides the seed (timeline, audio, music plan) |
| `--segment` | 300 | segment length (s); 10 h = 120 segments |
| `--name` | `<duration>_seed<N>` or `<length>_at<from>_seed<N>` | output folder tag, e.g. `10h_seed11`, `1h_at8h_seed11` |
| `--music` | `auto` | `auto` plans from the scene's music folders (tools/music.py `scene_music`; none = ambience only); `off` writes an empty plan |
| `--audio-jobs` | 4 | parallel `tools/audio.py` processes (below-normal priority) |
| `--cq` | encoder default (HEVC 19, H.264 18) | NVENC constant quality; lower = better and bigger; `--cq 21`–`23` for a smaller master |
| `--codec` | `hevc_nvenc` | or `h264_nvenc` if an upload ever misbehaves |
| `--qa` | `full` | `full`, `quick` (2 random frames, no determinism re-render) or `off` |
| `--thumbs` | 5 | thumbnail candidates (0 = none) |
| `--force` | off | start over when the fingerprint changed (deletes the segments) |
| `--keep-wav` | off | keep the audio segment WAVs after encoding |
| `--width`, `--height`, `--params` | 3840, 2160, none | passed to the renderer and part of the fingerprint; leave them alone for masters |

## What it does, in order

1. Writes `timeline.json` (with boat audio profiles) for exactly this video length, and `music_plan.json` (`tools/music.py plan`).
2. Checks `render.json`: same fingerprint → resume; different → stop (unless `--force`).
3. Starts the audio segments on the CPU (`--audio-jobs` in parallel) unless the encoded audio already exists.
4. Renders video segments one by one, each in a fresh Electron process, with one automatic retry. Progress every ~15 s: `[render h:mm:ss] video seg k/N i/n @ fps | total % | audio a/N | ETA`.
5. Encodes the audio once from the concatenated PCM (24-bit FLAC master + AAC 384k, so there are no encoder gaps at the joins) and deletes the WAVs; muxes `master.mp4` straight from the segment list (stream copy) plus the AAC (and `master_music.mp4` with music). `+faststart` only up to 2 h.
6. `credits.txt`, thumbnails (calm moments ≥ 10 s from any lightning, plus the boat at its best: fully visible, ~125 m away), then QA.

Progress can also be read from the manifest: `node -e "const m=require('./out/<scene>/render/<tag>/render.json'); console.log(m.segments.filter(s=>s.video&&s.video.done).length+'/'+m.segments.length+' video, '+m.segments.filter(s=>s.audio&&s.audio.done).length+' audio')"`.

## Output: `out/<scene>/render/<tag>/`

| Path | What |
|---|---|
| `master.mp4` (`master_music.mp4`) | the upload: all video segments + AAC 384k ambience (or the music mix) |
| `ambience.flac` / `.m4a` (`music_mix.flac` / `.m4a`) | 24-bit FLAC audio master and the uploaded AAC |
| `timeline.json`, `music_plan.json`, `audio_cal.json` | the timeline used (its duration = this video), the playlist, the loudness calibration |
| `render.json` | manifest: fingerprint, per-segment status, size, sha256, timing, outputs, QA summary |
| `seg/v_###.mp4` | video segments (~0.9–1.0 GB per 5 min), kept for resume and re-mux; `seg/a_###.wav` exist only while audio is pending |
| `qa.md`, `qa.json`, `qa/` | the QA report and its working files (decoded vs fresh frames, `compare.json`, `thunder.json`) |
| `thumbs/thumb_f<frame>.png` | 4K thumbnail candidates |
| `credits.txt` | for the YouTube description |

## Resume and fingerprint

- Re-run the **same command** after a crash, a closed terminal, sleep or a restart. Finished video segments are skipped when `render.json` marks them done and the file exists with the recorded size; the audio is skipped once `ambience.flac` is encoded, otherwise unfinished audio segments are redone. Assembly, thumbnails and QA run again on every invocation (`--qa off` skips QA).
- To redo one bad segment, delete `seg/v_###.mp4` and re-run.
- The fingerprint is a content hash (CRLF-insensitive, tracked and untracked non-ignored files) of `src/engine/`, `src/library/`, `src/render/page.js`, `sink.cjs`, `electron-main.cjs`, **all of `scenes/`**, `tools/audio.py`, `tools/music.py`, `tools/audio_analyze.py` and **all of `assets/keyart/`**; the plate folder (file names, sizes, `plate.json`); the timeline and music plan; and the settings (seed, duration, from/length, fps, segment, codec, cq, width, height, params). Commits alone, docs, `pipeline.mjs` and the QA scripts don't count.
- A mismatch stops with "`render.json` was rendered from different code/config. Re-run with --force to start over, or use --name <new tag>." Revert the change if it was accidental; otherwise `--force` (deletes this folder's segments and starts over) or `--name <tag>` (a new folder; the old one stays). A video never mixes code versions.

## QA report (`qa.md`)

| Check | Pass condition | Meaning |
|---|---|---|
| `frames` | every frame present once, timestamps at k/30 s (error < 1/4 frame) | nothing dropped or duplicated in the mux |
| `joins` | the last and first frame of every join, plus random frames (3 + hours; quick: 2), decoded from `master.mp4` match their own fresh render better than both neighbours (+0.5 dB) and at ≥ 34 dB PSNR | segment boundaries are frame-exact (NVENC uses B-frames, so this is proven, not assumed) |
| `determinism` | one random segment re-rendered is byte-identical (sha256) | the scene is a pure function of the frame index (full QA only) |
| `loudness_ambience` | uploaded AAC −20 ± 1.5 LUFS, true peak ≤ −1.5 dBTP (FLAC also reported) | GOALS loudness |
| `loudness_music` | −16.5 to −13.5 LUFS, ≤ −1.5 dBTP (only with music) | GOALS loudness |
| `thunder` | every strike in the window ≤ 6 dB over the bed (short-term, on the final AAC) | never startling |
| `av_sync` | video and audio streams within 50 ms of the length | no drift or truncation |

Plus events per hour in the window (lightning, boat, lantern, …) and render stats (video fps, audio CPU s, master GB, Mbit/s). The 1 h CP4 test: all PASS; 108 000 frames; 11 joins with min PSNR 39.5 dB and neighbours ≥ 4.7 dB lower; byte-identical re-render; −19.5 LUFS / −4.2 dBTP; thunder ≤ 3.4 dB; A/V 3600.00 s.

## Time and disk (RTX 4070 SUPER, Ryzen 7 7700X)

| | 1 h test (measured) | 10 h master (estimate) |
|---|---|---|
| Wall time | 26 min | ≈ 3.7 h |
| Video | 21.8 min at 82.5 fps average: ~55–58 fps while the 4 audio jobs run (memory-bandwidth contention; lower CPU priority doesn't help), ~100 fps after | same rates |
| Audio | 4 parallel jobs, ~210 s wall per 5 min segment while the GPU renders (`audio_cpu_s` ≈ 2000 sums those); done after ~8 min | 120 segments, so the audio jobs (and the slow video phase) last roughly the first half of the render |
| Size | 10.85 GB at 23.7 Mbit/s (HEVC CQ 19) | ~110 GB master + ~100 GB segments |

Run long renders in the background and poll the output or `render.json`; Electron's power-save blocker keeps Windows from sleeping while a segment renders.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Fingerprint mismatch error | see Resume. Typical causes: an edit under `scenes/` or `assets/keyart/` (any scene), library or audio code, a re-run of `plate_prep.py`, new music tracks, a different `--cq`/`--segment`/`--params` |
| Crash, closed terminal, Windows Update restart, sleep | re-run the same command; at most one segment is lost |
| A segment fails twice (`electron exit ...: ERROR ...`) | read the error lines; check free disk space, GPU driver, that no other GPU job is running; re-run |
| `joins` FAIL | open `qa/dec_f<frame>.png` vs `qa/fresh_f<frame>.png` and `qa/compare.json`: matching a neighbour = a dropped or duplicated frame at a join, low PSNR = a bad encode. Find the segment in `render.json` (each lists its first frame `start` and `count`), delete that `seg/v_###.mp4` and re-run |
| `determinism` FAIL | something isn't a pure function of the frame: `Math.random` or wall-clock time, state carried between frames, an instanced mesh without `frustumCulled = false` and `renderOrder`. Reproduce with stills (a frame alone vs in a sequence, `rain_qa.py --seam`), fix, then `--force` |
| `loudness` or `thunder` FAIL | check a range with `tools/audio.py ... --report`, adjust the scene's `audio` config (`lufs`, `thunder.over_bed_db`), `--force` |
| ffmpeg or NVENC errors | `ffmpeg` and `ffprobe` must be on PATH; `ffmpeg -hide_banner -encoders` must list `hevc_nvenc`; update the NVIDIA driver; close other encoders; `--codec h264_nvenc` as a fallback |
| Video slower than ~55 fps throughout | another GPU or memory-heavy job is running |

## Upload checklist

**Once per channel:**
- A Brand Account channel with 2-Step Verification on.
- The phone verified: needed for uploads over 15 min.
- Advanced features unlocked, through video or ID verification or channel history, before the first upload. YouTube's [feature table](https://support.google.com/youtube/answer/9890437) puts these behind them: Content ID appeals, A/B testing (Test & compare), clickable description links, pinned comments, chapters and applying for YPP.
- YPP: 1,000 subscribers plus 4,000 public long-form watch hours in 12 months. Then Studio → Earn → apply, and link one AdSense for YouTube account.
- Reviewers judge the whole channel: its main theme, top and newest videos, titles, thumbnails, descriptions and About text.
- The About text, keywords and channel settings (audience "not made for kids", upload defaults) are in [assets/publish/channel.md](../../../assets/publish/channel.md). Its text follows the voice rules in step 4.
- Profile picture (800x800) and banner (2560x1440, text inside the middle 1546x423) come from the channel's own scenes, so they match the thumbnails.

**Per video, the deliverable is an upload package** (user 2026-10-16: one folder with the final video, the thumbnail and every asset).

```powershell
.venv\Scripts\python tools\upload_package.py assets\publish\<scene>.json   # -> upload/<slug>/ (gitignored)
```

- **Contents:**
  - `README.md`: steps 2–5 below, filled in for this video.
  - The video: a hard link to the master, so no extra disk space.
  - `thumbnail.jpg`: the suggested one, plus `_1280.jpg`.
  - `thumbnail-options/`: **every** variant, `preview.png` and `feed_compare.png`. The user always wants alternatives to choose from, so every video gets several thumbnail concepts, not just the pick.
  - `title.txt` (suggested title, then alternatives), `description.txt` (paste-ready, ending with `credits.txt`), `tags.txt`, `credits.txt`, `qa.md`.
- **The publish spec** (`assets/publish/<scene>.json`, committed) holds:
  - the render folder and video file;
  - the thumbnail spec, the suggested variant and the Test & compare trio;
  - the titles, description lines, hashtags, tags and category;
  - `draft_text`.
- **The tool refuses to write the package** if:
  - a title is over 100 characters, starts with "Minecraft", or doesn't say 4K;
  - the suggested or a Test & compare thumbnail lacks 4K or the length (e.g. "10 HR");
  - the description is over 5000 characters, lacks Mojang's disclaimer on a Minecraft look, or carries it on any other look;
  - the tags are over 500 characters;
  - any text contains `<` or `>` or mentions AI;
  - a title, description line, tag or hashtag has an em or en dash, an emoji, an exclamation mark or a stock AI word (`voice_problems`; thumbnails and the generated credits are exempt);
  - "music" is promised with an ambience-only master;
  - the QA didn't pass.
- **Re-run it** after a re-render or a spec change: it regenerates the thumbnails, re-links the video and rewrites the text.

1. `qa.md` says **Overall: PASS** (for a looped upload, both the hour's `qa.md` and the loop folder's). Spot-check `master.mp4` in a player: the start, a segment join (for a loop: an hourly join, e.g. 1:00:00), a lightning strike with its thunder, a boat or other rare event, the end.
2. Upload the package's `.mp4` (`master_music.mp4` with music, else `master.mp4`) as **Private** to the right channel (check the avatar in YouTube Studio). ~110 GB takes ~12 h at 20 Mbit/s. Publish only after the 4K version has finished processing, which takes hours for 10 h.
   - **With music, also wait for Studio's Checks step to report no copyright issues** (it runs on the private upload) before publishing.
   - If a Minecraft track gets a claim, set it to `"use": false` in `config/minecraft_music.json`, then re-run `mc_music.py import` and `loop_master.py`. Upload the new file, or the ambience-only `master.mp4`.
3. Settings:
   - **Audience:** "No, it's not made for kids" (sleep and study). The Minecraft look appeals to kids, so aim titles and thumbnails at adults.
   - **AI use:** No for stylized scenes with synthesized sound; YouTube requires disclosure only for content that seems realistic ([help](https://support.google.com/youtube/answer/14328491)). Yes for a photorealistic scene or AI-made music: the README says so from the tracks' `ai_made` flags (the ramen alley: 12 Suno tracks).
   - **Category:** Film & Animation (his choice on both videos).
   - **Ad breaks** (once in YPP): mid-rolls off. Both videos promise no ads ("no ads" in the title, "Never interrupting with ads" in the description).
4. **Title and description, drafted the way he publishes them** (user 2026-10-20: learn from how he changed the description, and reproduce his changes). What's live, and what he changed from each draft: [docs/records/rainy-ramen-alley/published.md](../../../docs/records/rainy-ramen-alley/published.md) (the reference) and [docs/records/autumn-treetop/published.md](../../../docs/records/autumn-treetop/published.md). `upload_package.py` builds the description from the spec's opening, his blurb, the credits that are needed and the hashtags. The ramen spec reproduces his published text exactly.
   - **Title,** like "Lofi Ramen Alley. Study and relax with calming rain. 4K, 10 hours, no Ads" (his published ramen title had a scene emoji and a weather emoji where the periods are; since 2026-10-26 no emoji, L157):
     1. the music and a name for the place, capitalized as a name ("Lofi Ramen Alley");
     2. what it's for, in plain words ("Study and relax with calming rain");
     3. the specs: "4K, 10 hours, no Ads".

     At most 100 characters and no emoji (upload_package refuses one, except in a spec from before with `"title_emoji": 2`). His own words can lead instead of the place name, as on the Burdock Shelter: "Welcome Home, Critter. Come rest with your PNW friends in the rain. 4K, 10 hours". On Minecraft looks "Minecraft" stays a secondary part, never the first word or the dominant part ([Mojang usage guidelines](https://www.minecraft.net/en-us/usage-guidelines)). Treetop's title, which he kept as drafted, is the other accepted form: "4K rainy autumn treehouse with calm Minecraft music and distant thunder, no ads (10 hours)".
   - **Description:** the spec's `description` is only the opening; the rest is added.
     1. **The opening,** written for this video: "Come relax with rain on <the scene, concrete>, with <the music> and <the weather>." Then "10 hours of 4K, calming ambience with smooth music. Never interrupting with ads." With the channel's own creatures, it also names each one's species by its common name and what it's doing (config/cast.json `species`; user 2026-10-26: the description names the species), like the Burdock Shelter's "A polyphemus moth, a pygmy short-horned lizard and a northwestern garter snake wait for their soup by the fire, and a western red-backed salamander keeps watch out in the rain with its lantern. All four are native to the Pacific Northwest."
     2. **His blurb,** the same on every video by his choice: [assets/publish/description_blurb.txt](../../../assets/publish/description_blurb.txt). It holds his story (the TV while he works from home, "one scene I designed for this channel", "Excited to continue to develop more"), how it's made in first person ("made by myself ... synthesized in my engine. I love making these videos, so please let me know what you would like to see next.") and "No stock footage, recordings or sound-effect libraries." If its "(rain, wind, thunder and every other effect)" doesn't fit a scene, give the spec its own `blurb` lines.
     3. **Credits, only where a track asks for them** (`tools/music.py credits`): Mojang's tracks under "Music courtesy of Mojang Studios", one "Title - Artist" per line, as he published Treetop. CC-BY and the like get their credit line. CC0 gets none, and he dropped the ramen's 28-track list. On Minecraft looks, Mojang's disclaimer comes last: its Essential guidelines ask for it in the description.
     4. **Hashtags,** about 8. First the three YouTube shows above the title (music, sound, use: #lofi #rainsounds #studymusic), then #study #relaxing #relax #4k #10hours. At most 15.
     - **No list of moments by default.** He dropped it on the ramen video; Treetop kept one ("What happens every hour:"). Tell him about a strong moment in your message, and leave it out of the spec unless he asks.
   - **Tags:** optional. He left them out on the ramen video. On Treetop he typed short single words (minecraft, rain, study, relax, calm, cozy). The hashtags carry the search terms.
   - **Public text never mentions AI, and stays true:** no "hand-drawn", "no AI" or stock-library claims (DECISIONS 2026-10-16). His blurb's first person ("made by myself", "my engine") is his own wording; keep it as he wrote it.
   - **Voice:** his published text is the reference: first person, warm and plain ("Come relax", "I love making these videos"). Write with the user-level `truman-voice` and `humanizer` skills; he rejected the first drafts of 2026-10-16 as obviously AI-written.
     - No em or en dashes, no exclamation marks, no stock words (stunning, immersive, vibrant, delve…), no "not just X". upload_package checks these.
     - No emoji anywhere, the title included (user 2026-10-26).
     - The title and opening are new for every video. The blurb repeats on purpose.
     - Every fact is checked against the timeline and the scene.
5. Thumbnail: `tools/thumbnail.py` (below); the package copies the suggested one and all the others. Upload the 4K `thumbnail.jpg` from a computer; the `_1280.jpg` copy fits the 2 MB mobile limit. With advanced features, put the spec's 3 `test_and_compare` variants into YouTube's **Test & compare**, which keeps the one with the most watch time.
6. Keep the video's records: `master.mp4`, `ambience.flac`, `timeline.json`, `qa.md`, `credits.txt` and `thumbs/` (the timeline says what happens when, for chapters later). For a loop, also keep the source window or hour folder **with its `seg/`**: loop_master rebuilds the loop from those segments, which is how a claimed track gets replaced. When a published video's 10 h folder is deleted to free disk (Treetop, 2026-10-20), first copy its `qa.md`, `loop.json`, `music_plan.json` and `credits.txt` into `docs/records/<slug>/` and note the rebuild command in `docs/records/README.md`. Pass `--offset` again if the loop used one: the tool reads the old offset from the 10 h folder's `loop.json`, and that's gone.
7. After YouTube has processed the upload (4K available) and it plays through, delete the `seg/` of a rendered 10 h master (~100 GB). Without the segments that folder can't resume or re-mux. Keep the segments of a loop's source window or hour (8 to 11 GB): they're the only way to rebuild the loop.
8. Update `docs/STATUS.md` (what was uploaded, where, QA numbers).
9. **Once it's live,** read its page and record what he published: title, description, tags, category and thumbnail, in `docs/records/<slug>/published.md`, with what he changed from the draft. Set the spec to the published text (`published: {url, date}`) and turn each change into a rule here and a row in the lessons. That's how the next draft starts closer to what he'd write. The live page's `ytInitialPlayerResponse` holds the title, description, keywords and category. Compare its `maxresdefault.jpg` with the variants to see which thumbnail he picked.

## Thumbnails

```powershell
.venv\Scripts\python tools\thumbnail.py assets\thumbnails\<scene>.json [--only <name>] [--refresh] [--feed docs\reference\thumbnail-feed-2026-10-16.json]
# -> out/<scene>/thumbnails/<name>.jpg (3840x2160) + <name>_1280.jpg + preview.png (+ _feed_compare.png)
```

The spec lists the variants. Keep up to 3 for YouTube's Test & compare; more are fine while exploring. The format is in the tool's docstring. Treetop's is `assets/thumbnails/treetop-plate.json`. Each variant has:
- a frame, an optional crop and grade overrides;
- `bands`: letterbox bars or a feathered scrim under text;
- `mat`: the frame as a photo on a paper mat, like a polaroid;
- `panels`: pixel-cornered cards, such as a music-player card;
- `insets`: a magnified picture-in-picture in a pixel-bordered rectangle or pixel circle, optionally boxed and connected to its place in the main image (`callout`);
- `chips`: rows of tags;
- `badges` (spec top level): the same rows on every variant, unless a variant sets its own `badges`;
- the text.

Text items can stack lines (`\n`), align left or right, use `rules` (lines either side of a title), a pixel-cornered `box`, `opacity`, and a wooden-sign box (`planks`, `hang` chains). Styles: `title`, `kicker`, `amber`, `label`, `badge` (dark on a warm tag), `chip`, `ink` (on paper) and `sign`.
- **Frame:** a frame index of the video. The tool renders it once with `node src/cli.mjs still` and caches it in `out/<scene>/stills/`; `--refresh` re-renders. A path to an image works too.
- **Output:**
  - `preview.png` shows every variant at YouTube's desktop, phone and sidebar sizes, with the duration badge.
  - `--feed` adds `_feed_compare.png`: each variant in a row of the niche's real top thumbnails at phone size. It's the test for "does it stand out". The competitor thumbnails are cached in the gitignored `out/` and used only for that sheet.
  - Look at both before showing anyone.

**Each look gets its own thumbnails** (user 2026-10-20: not Minecraft style for every video; take liberties so each fits its video's own look, and keep 10 HR and 4K on all of them):
- The look's `thumb` in `config/aesthetics.json` lists its fonts (`config/fonts.json`, OFL, in the ledger before first use) and motifs from its own world to put the text on. For a look that isn't pixel art, upload_package wants at least 3 concepts in those fonts among the options. The channel's pixel set can be offered too, and his pick can be any of them: he published the ramen alley with `pixel-bowl`.
- `tools/thumbnail.py` draws smooth text in any catalog font (`font`, `size` in px at 4K) with effects that suit a look:
  - neon tubes (`neon`), brush and gold lettering, soft shadows, vertical Japanese text;
  - `cards`: flat things in the picture with text on them, such as a paper ticket, a sign board, or a noren with slits, folds and a sagging hem;
  - `scrims` to shade behind text, and smooth tags for 4K and 10 HR.
- **Take liberties.** Make several different concepts per video, each built from something in the scene, then judge them at phone size. The ramen alley (2026-10-20):
  - the title as neon tubes like the alley's own signs;
  - らーめん brushed on an indigo noren;
  - a meal ticket (食券) reading "lofi ramen", with "10 HR" and a red 4K seal;
  - a vertical ラーメン横丁 ("ramen alley") shop sign;
  - the sleeping cat with a handwritten "shh, the cat's asleep";
  - the steaming bowl, and a polaroid with a handwritten caption.

  I suggested `neon-sign`. **He published `pixel-bowl`:** the bowl close-up with "Ramen Alley" in amber pixel letters and the "♫ chill lofi music & rain" tag. His picks so far are both a big hero (the cat close-up inset on Treetop, the bowl on the ramen alley) with the place name and the music tag in the channel's pixel font. Make that concept every time, next to the look-styled ones, and suggest it first.
- **4K and the length stay on every one:** on smooth tags in the look's font (about 190 px at 4K reads on a phone), or on the motif itself, like the ticket's "10 HR" and its 4K seal.
- **Every line must stand out from what's right behind it** (lessons L65). A warm orange neon "lofi & rain" over the warm, lantern-lit street didn't show up. Pick a color that contrasts with that spot (the cyan tube there, next to the pink "ramen") and add a dark halo under neon, like a sign's backing board. Check each line at phone size, not just the thumbnail as a whole.
- Japanese text uses common, correct words: らーめん (ramen), ラーメン横丁 (ramen alley), 食券 (meal ticket). Vertical text turns the long-vowel mark ー upright.

**Style.** Researched 2026-10-16 from the niche's most-viewed videos (Drift Away Ambience at 19M views, CozyCraft, Sound; DECISIONS 2026-10-16 "Thumbnails", "Thumbnails v2" and "Thumbnails v3"). The niche's template is a calm lowercase phrase in white pixel font, centered on a glowing scene ("you need sleep", "time to sleep", "relax here"). It's everywhere, so **don't copy it.**
- **Rejected by the user** as too close to existing ones: "stay a while", "sleep well".
- **Liked:** "let it rain", and the place card (the scene's name in amber between rules) with the sleeping cat highlighted in a corner close-up.
- **Chosen for Treetop (2026-10-16): `place-card-cat`.** Use it as the template for a Minecraft look's main thumbnail. From the top down, largest to smallest:
  1. the place name in amber between rules;
  2. the warm music `badge`;
  3. one small dark `chip` naming the weather ("🌧 rain & distant thunder", one size smaller than the badge; the user asked for the rain chip to stay small);
  4. the pet in a pixel-bordered corner close-up, kept clear of the duration badge.
- **Every Minecraft-look thumbnail says it's calm Minecraft music** (user 2026-10-16). Use the warm `badge` "♫ calm minecraft music": a solid tag that no competitor uses, readable at phone size. Other looks name their own music in their own style (ramen: "lofi & rain").
  - Only on thumbnails of the music version (`master_music.mp4`).
  - "Minecraft" is always the secondary line, in our own font. Never the biggest text, never logo-style lettering, never "MINECRAFT" on its own (Mojang usage guidelines).
- **Ways to stand out, judged in the feed sheet:**
  - **Words** that name what's special in this scene: a place name, the storm, the cat, a real moment. Avoid generic comfort phrases.
  - **Layout** off the centered phrase: a top/bottom letterbox with a small-caps place name, a left-aligned card or panel, a bottom block over a feathered scrim, a tiny "⚡ 1.1 km" tag.
  - **Image** that isn't only the wide shot:
    - An extreme close-up of the pet (zoom 3.4; the blocky art survives it). No other thumbnail in the feed has a creature filling the frame.
    - The pet as a corner or circle inset over the wide shot.
    - A hero prop, such as the hanging lantern at zoom 2.7 against the rain.
  - **Frames** that change the thumbnail's outline in the feed: the cream polaroid mat stands out most, then letterbox bars.
  - **Contrast** against the niche's dark scenes: our lightning-lit violet sky is the brightest thing in the feed.
- **Truth:** every claim on the thumbnail must be true of the video, such as the strike distance from the timeline (`thunder.distance_m`) or "minecraft music" only with the music version. Use no Mojang logo or logo-style lettering.
- **Font (Minecraft and pixel looks):** the channel's own pixel font, `tools/pixelfont.py`, drawn in code, with icons (⚡ ♫ ▶ 📍 🐱) and progress-bar pieces. Titles are white or amber with a 1-font-pixel dark drop shadow and a soft dark glow. Other looks use their own fonts (above).
  - Kicker, badge and label lines are bold, because 1-px strokes disappear on phones. Bold keeps 1-px gaps open; before 2026-10-16 it filled them, and m/w/k/x read as blobs.
- **Frame:**
  - The strongest frame is a storm strike at its peak: the event's `frame` + 3, since the flash peaks 0.1 s after it starts. The lightning lights the sky cool violet against the warm lanterns and makes the rain streaks visible, and it's a real moment of the video.
  - The boat (~40 px at 4K) and the heron (~10 px) are too small for a thumbnail.
- **Grade:** lantern bloom, a soft glow, lifted midtones, more saturation and a vignette, so a dusk scene doesn't read as dark at 360 px.
  - A crop of ~1.1 removes dead corners, such as dark foreground blocks.
- **Safe areas:** keep the title and the pet out of the bottom-right corner, where YouTube draws the duration badge.
- **4K and the length** (user 2026-10-16, DECISIONS 2026-10-16): every thumbnail says both, as the spec's `badges` at top-left, clear of the duration badge. If a variant's own top-left text collides, move that text or give the variant its own `badges` (pin-chips, count-the-seconds and letterbox were fixed this way; the close-ups cat-music and cat-asleep use 18 px). Check every variant in `preview.png`. "NO ADS" is Treetop's choice; other scenes don't need it.
- **Sizes:** pixel text: `px` and text positions are multiples of 3, so the 1280×720 copy (a 3× area downscale) stays pixel-sharp, and kickers are bold, because 1-px strokes disappear on phones. Smooth text: `size` is the font size at 4K; a main line of 250 to 560 px and tags of about 190 px read at phone size.
- **Wording:** keep it short and specific to the scene. Every video has its own frame, crop and words, and outside Minecraft looks its own fonts and motifs. What every thumbnail shares is 4K, 10 HR and the truth rules.
