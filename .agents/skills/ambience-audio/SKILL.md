---
name: ambience-audio
description: 'Procedural, deterministic ambience audio for plate scenes: tools/audio.py (canonical 15 s blocks with 3 s warm-up, per-second seeded slots, bit-identical random access; layers wash, patter, near, roof, water, runoff, drips, wind, reverb; thunder N-waves with distance delay; events stem with boat wash, wake laps, lantern gutter, fish plops, creaks; gust-flurry wind swells; loudness calibration cache; --stems and --report checks), tools/audio_analyze.py, tools/music.py (music folders per look, <file>.json sidecars, plan, credits, ledger, -16.5 LUFS music bus, limiter, audio.py --music), music for a new look (music_fetch.py with license checks, music_screen.py with an audio model, music_samples.py clips; the checked sources: HoliznaCC0, open-lofi, YouTube Audio Library, Pixabay, incompetech) and the GOALS loudness targets. Use when: rendering or checking the audio of a scene, audio sounds wrong, too loud or too quiet, adding a sound for a new event, adding an ambience layer for another setting (surf, crickets, fire, wind in pines), finding music for a look (lofi, jazz, piano), adding music tracks and credits, or verifying loudness, true peak, thunder over the bed and determinism.'
argument-hint: 'scene and goal, e.g. "beach-hut: add a surf layer"'
---

# Ambience audio: synthesized, deterministic, synced to the picture

`tools/audio.py` synthesizes all sound from the scene's timeline JSON: no samples, no recordings (asset ledger: original). The rain bed follows the same gusts, weather track and runoff flow as the shaders, thunder arrives at flash + distance / 343 m/s, and event sounds follow the events' stored parameters. Audio is random access: any time range synthesizes the same signal as a longer render containing it (up to the WAV dither), so the master render runs 5 min audio segments in parallel and joins them with no seams. The user approved the thunder and ambience as they were on 2026-10-15; the mix was tuned by measurement, so expect listening feedback.

Internals (every layer, level, rate, event sound, the determinism machinery): [references/audio-internals.md](./references/audio-internals.md).

## Commands

```powershell
node src/cli.mjs timeline scenes/<scene>                                    # -> out\<scene>\timeline.json (the audio's only input)
.venv\Scripts\python tools\audio.py out\<scene>\timeline.json --start 600 --duration 60 --out out\<scene>\audio\a.wav [--stems] [--report] [--music out\<scene>\music_plan.json]
.venv\Scripts\python tools\audio_analyze.py <audio or video file> [--out stats.json] [--start s --duration s]
.venv\Scripts\python tools\music.py plan    out\<scene>\timeline.json   [--music-dir music] [--out ...\music_plan.json]
.venv\Scripts\python tools\music.py credits out\<scene>\music_plan.json [--out ...\credits.txt]
.venv\Scripts\python tools\music.py ledger  out\<scene>\music_plan.json
```

- `audio.py` defaults: `--start 0`, `--duration 60`; `--out` is required. It writes a 24-bit 48 kHz stereo WAV and prints one JSON line (`master_db`, `sample_peak_dbfs`, seconds). `--stems` adds `<out>_rain/_runoff/_thunder/_events.wav` (+ `_musicbus.wav`). `--music <plan>` also writes `<out>_music.wav` (ambience + music, limited). Speed: ~6 s of CPU per minute of audio.
- `node src/cli.mjs preview` renders and muxes the audio automatically (AAC 320k) when the scene has an `audio` key; `--audio off` skips it. The master render runs `audio.py` per segment (master-render skill).

## How it works

- **Blocks:** canonical 15 s blocks, each computed from 3 s before it (warm-up longer than any filter or kernel). All randomness comes from generators keyed by (seed, layer id, key, whole second), so any range regenerates identical values.
- **Bed** (stems `rain` and `runoff`): `wash` (distant roar), granular `patter`, `near`, `roof`, `water` (bubbles) and `runoff` (splashes per roof stream, following the shader's flow 1.3 s later), sparse `drips`, gust-driven `wind` (whoosh + leaf rustle), and a porch reverb. Grain rates follow slow micro drift × the timeline's `track.rain` × gusts.
- **Thunder** (stem `thunder`): N-waves from a random lightning channel, each segment arriving at its distance / 343 m/s, low-passed by distance, valley reverb, 0.4 s soft onset, starting at the timeline's `thunder.t`; 1.2–4.5 dB over the bed (nearer = louder).
- **Events** (stem `events`): boat hull wash along the boat's `profile`, its wake lapping 18–30 s after the closest approach, lantern guttering shaped like the light dips, fish rises (a deep bubble "bloop" plus a soft splash, attenuated by distance), and wood creaks at strong gust peaks and strong flurries (audio-only). Each is a self-contained wave seeded by its event and placed at its start sample. Gust flurries also swell the `wind` layer (whoosh and leaf rustle) and lift the rain intensity by up to +0.8 × the gust envelope. Distant flashes (`farflash`) get a soft, deep rumble in the `thunder` stem that stays under the rain (`far_thunder`).
- **Loudness:** `calibrate()` measures one loop of the bed at nominal weather and stores the master gain in `<timeline folder>/audio_cal.json`, so the bed sits at the scene's `audio.lufs` (−20). The weather drift then moves it around that level.
- **Scene config:** the scene's `audio` object is deep-merged over `DEFAULTS` (layer levels, grain rates, reverb, thunder, event levels, `lufs`, and `music` for `tools/music.py`).

## Loudness targets and checks

| What | Target (docs/GOALS.md) | Checked by |
|---|---|---|
| Ambience-only mix | ≈ −20 LUFS integrated | `--report`; master `qa.md` (−20 ± 1.5 on the uploaded AAC) |
| Music mix | ≈ −16 LUFS: the music bus (−16.5) over the ambience lowered 2 dB (`ambience_db`, user 2026-10-16) | `--report` with `--music` and `qa.md`: within 1.5 LU of `music.mix_target` (judge over minutes; 30 s of a quiet passage reads low) |
| True peak | ≤ −1.5 dBTP | both |
| Thunder | ≤ ~6 dB over the bed (short-term 3 s), never startling | `--report` per strike in the range; `qa.md` on the final AAC |
| Event sounds | ≥ 3 dB under the bed (momentary 0.4 s) | `--report` |
| Clicks, gaps | none | listen at segment joins; block design |

`--report` prints integrated LUFS, short-term range and true peak, then one line per thunder in the range and the loudest event moment, ending in `AUDIO PASS` or `AUDIO FAIL` (and `MUSIC PASS/FAIL`). Treetop's 1 h test: −19.5 LUFS, −4.2 dBTP, thunder +1.5 to +3.4 dB over the bed.

`tools/audio_analyze.py` measures any file (ours or a reference): third-octave spectrum, spectral tilt and centroid, BS.1770 integrated and short-term loudness (its meter matches ffmpeg ebur128), true peak, crest factor, HF kurtosis (impulsiveness), stereo correlation per band, and tonal peaks (music or hum). Treetop's bed: tilt ≈ −1.0 dB/oct, centroid ≈ 1.6 kHz, HF kurtosis ≈ 4. The user's reference recording was mostly music, so it is not a rain reference.

## Music slot (`tools/music.py`)

- Tracks live in folders under `music/` (gitignored), one style per folder (`music/lofi/` ...): `.wav .flac .mp3 .ogg .m4a .aac .opus`, each with a sidecar `<file>.json` (e.g. `song.mp3.json`; `song.json` also works): `{"title", "artist", "source", "license", "license_url"?, "attribution"?, "origin"?, "ai_made"?}`. A track without the four required fields is skipped with a message; tracks shorter than ~28 s after trimming are dropped silently. Licensing is the user's call: only licenses that allow monetized YouTube use.
- **Each look has its own music** (`scene_music`, 2026-10-19): the scene's `audio.music.dirs`, else the look's `music_dirs` in config/aesthetics.json, else none (ambience only). The root `music/` folder is the Mojang allowlist: hand-built scenes without a scene.json (all Minecraft looks) use it, and `plan` refuses Mojang tracks for any other look. Mojang's disclaimer goes into `credits.txt` only for Minecraft looks (upload_package checks both ways). `--music-dir` (repeatable) overrides the folders in `music.py plan` and `loop_master.py`.
- **Minecraft music** (DECISIONS 2026-10-16): only the Mojang-owned allowlist in `config/minecraft_music.json`. It covers Lena Raine, Kumi Tanioka, Aaron Cherof, Amos Roddy and fingerspit, on the official Creator-Safe Playlist, chill tracks only. Never C418 or "Lava Chicken".
  - `tools/mc_music.py check` verifies the allowed tracks on the live playlist (run it before each new video; `--snapshot` saves a dated copy to `docs/reference/`).
  - `import` copies them from the user's game install into `music/mc_*.ogg` with sidecars ("Music courtesy of Mojang Studios"). `list` shows every game track's status.
  - To drop a track, set `"use": false` and re-import.
- `plan` (seeded by the seed and the exact set of track hashes; adding a track changes the plan): whole tracks, silence trimmed (−60 dB), reshuffled every cycle, never the same track twice in a row, equal-power crossfades of 6 s or the track's own fade-out up to 12 s; each track BS.1770-normalized so the bus sits at −16.5 LUFS; 4 s fade-in at the video start, 8 s fade-out at the end. Settings come from the scene's `audio.music` (`lufs`, `crossfade`, `max_crossfade`, `fade_in`, `fade_out`, `silence_db`, `ambience_db`, `thunder_db`, `opener_lead`, `trim_intro`).
- **The opener** (user 2026-10-16: the start is when people look hardest; music should come in quickly). The video opens with the first track in the shuffle that reaches its normal level within `opener_lead` s (default 5; 0 = off).
  - Each track's `lead` is measured as seconds until its short-term loudness first comes within 6 dB of its integrated loudness.
  - Some tracks are nearly silent for a long time: Comforting Memories 68 s, yakusoku 57 s, Left to Bloom 52 s, pokopoko 50 s, Home 42 s, An Ordinary Day 40 s.
  - At full level in the first second: A Familiar Room, Broken Clocks, Bromeliad, Lilypad.
- Mix: `audio.py --music <plan>` adds the bus to the ambience and runs a local look-ahead limiter (−2.5 dBFS sample peak; −3.1 dBTP measured). It only looks ~0.1 s around each sample and `audio.py` renders 0.25 s extra on both sides, so separately rendered segments are sample-exact. `limit(..., spots=...)` takes lower ceilings for short ranges: loop_master uses them where the AAC encode overshot a transient (master-render skill, "The encode is checked").
  - **Under music the ambience (rain, events) is lowered by `ambience_db`** (default −2 dB). The user found the rain a touch too loud over the music and picked −2 dB from A/B clips at 0, −2 and −3.5 dB.
  - **The thunder keeps its own level, `thunder_db`** (default 0, as in the ambience-only mix). The user asked for it a little louder than in the −2 dB clips.
    - `audio.py` uses its `thunder` stem.
    - `loop_master` renders the hour's thunder stem with `audio.py --stems` (parallel 5 min chunks, checked against the render's FLAC, cached in `cache/loop/`).
  - **Near-silent song intros are cut to their last 3 s when they last `trim_intro` or longer** (default 40 s; 0 keeps them). In the Minecraft set that's six songs: An Ordinary Day, Home, pokopoko, Left to Bloom, yakusoku and Comforting Memories. The analysis records `intro_cut`, and the crossfade fades in what remains.
  - In Treetop the music then sits ~4–5 LU over the rain, and the 10 h music mix measures ~−16 LUFS. The ambience-only mix is unchanged.
- **Judge the sound on short clips, never on a 10 h build** (user 2026-10-16): `tools/loop_master.py <hour> --preview 7m-11m --ambience-db=0,-2,-3.5` writes one frame-exact A/V clip per level in a few minutes. Use a window with thunder and a song change, plus `--preview 0-1m30s` for the opening.
- `credits` writes `credits.txt`: only what asks for credit, in the form Truman published (2026-10-20). Tracks with an `attribution` in their sidecar (Mojang's: "Music courtesy of Mojang Studios") or a license that isn't CC0 or public domain go under that credit line, one "Title - Artist" per track in order of first play, with no timestamps (a list starting at 0:00 would become YouTube chapters). CC0 music gets no lines; the ledger keeps its provenance. Then come ledger attributions for other assets and, on Minecraft looks only, Mojang's disclaimer. The file is empty when nothing asks for credit. How the video is made is in his blurb (`assets/publish/description_blurb.txt`), which upload_package adds. `ledger` upserts the tracks into `docs/asset-ledger.csv` (keyed by path; a sidecar's `origin` goes into the notes). Decoded tracks are cached in `cache/music/<sha1>.npy`.
- No tracks: the plan is empty and every output is ambience-only. Test with synthesized tones kept in `out/`, never in `music/`.

## Music for a new look (autopilot, user 2026-10-21; by hand: new-video STOP 3, 2026-10-19)

**Autopilot does this by itself:** `.venv\Scripts\python tools\music_auto.py <look> [--scene <scene>] [--budget 2] [--dry-run]` reads the genre family named first in the look's `music` (lofi, jazz, synthwave, ambient, piano, acoustic, orchestral, chiptune), reuses screened pools in `music/_candidates/` that fit, fetches and screens more from the checked CC0 sources only when needed (within the budget; ~$0.04 a track), curates 24 tracks into `music/<look>/`, writes sidecars, ledger rows, `music_dirs` and a README. Truman hears the result in the sample. Coverage (2026-10-21): lofi, ambient and chiptune pools are deep, piano and jazz are enough, acoustic and orchestral are thin, so a new look names a well-stocked genre first ("lofi with soft acoustic guitar"). When he wants different music, use the manual steps below and let him pick from clips.

The style is the look's `music` in config/aesthetics.json. For the ramen alley Truman first named lofi or jazz, then chose lofi (the more popular of the two at the time), with "90's Chill Lofi, Study Music, Lofi Rain, Chillhop Beats" (youtube.com/watch?v=sF80I-TQiW0) as the reference.

```powershell
.venv\Scripts\python tools\music_fetch.py fma holiznacc0/lo-fi-and-chill --to music\_candidates\lofi   # license read on each track's page (CC0 only unless --allow)
.venv\Scripts\python tools\music_fetch.py openlofi chillhop late-night --to music\_candidates\lofi    # CC0, made with Suno (sidecar ai_made)
.venv\Scripts\python tools\music_screen.py music\_candidates\lofi --scene <scene> [--style "..."]   # an audio model listens: vocals, mood, fit -> screen.json + ranking (~$0.03 a track)
.venv\Scripts\python tools\music_samples.py out\<scene>\render\<tag> music\_candidates\lofi --top 6   # one 70 s clip per track over the render's opening -> out/samples/music/<scene>/
```

- **Screening** (`music_screen.py`): Azure `gpt-audio-1-5` (config/azure.json `audio_deployment`; the vision model takes no audio) hears two 30 s excerpts per track. A track with lyrics is out; wordless vocals cost 2 points; score = 0.4 style match + 0.35 calm + 0.25 quality. It only narrows the field: Truman's ears decide.
- **Clips** (`music_samples.py`): the render's own picture and ambience with one track as the whole playlist, mixed exactly as the video would be (bus −16.5 LUFS, ambience −2 dB, thunder at its level, the 4 s fade-in, the limiter). Each sampled track gets a ledger row ("music candidate") before it is mixed. Each finished clip is then heard by the audio model over the 30 s with its first storm strike (music, rain and thunder audible, the balance, anything harsh): the agent can't listen, so that stands in for its ears before Truman's. `index.md` in the output lists every clip with what was heard, its license and source. The ramen clips (2026-10-19) measured −15.2 to −15.8 LUFS, true peak −2.4 to −3.0 dBTP, thunder 1.6 to 4.1 dB over the music; the model heard all three layers with the balance "about right".
- **After his pick:** curate around the tracks he liked (below), set `music_dirs` in aesthetics.json, `music.py ledger` when the plan is built, delete the rest of the candidates with their ledger rows.

### Curating around his favorites (user 2026-10-19: he picked clip 6, then 3, and asked to curate around that sound)

```powershell
.venv\Scripts\python tools\music_screen.py music\_candidates\lofi --scene <scene>   # screen the pool first (vocals out); cached per folder in screen.json
.venv\Scripts\python tools\music_like.py music\_candidates\lofi\<fav1>.mp3 music\_candidates\lofi\<fav2>.mp3 --in music\_candidates\lofi --pick 28 --to music\<look-folder>
```

- **Likeness** (`music_like.py`): CLAP (`laion/larger_clap_music`, Apache-2.0, runs locally, cached in cache/hf) embeds eight 10 s windows per track. Raw lofi tracks all sit at about 0.99 cosine to each other, so the pool's mean embedding is taken out first. A track's score is its best similarity to one favorite times that favorite's weight (1 for the first, 0.85 for the second; `--weights`): his two ramen favorites are far apart (−0.09 to each other), and averaging would pick tracks like neither. `--pick N` fills a quota per favorite by weight, only with clean tracks (screened, no vocals in any excerpt, a screen score of 8.5 or more, at least 100 s; it warns when top-ranked tracks aren't screened yet); `--to` copies the picks with sidecars and writes `vibe` (the favorite it is near) and `picked` into each.
- The audio model can't judge likeness (it rated a track 7/10 against itself); use it for vocals and fit only.
- Listen-check a few picks (`music_samples.py <render> music\<look-folder> --top 6`) before building: CLAP finds the sound, not the quality.

### Playlist settings that play smoothly (scene.json `audio.music`)

The ramen alley: `{"order": "smooth", "opener": "openlofi_moon-through-bamboo.mp3", "body_db": 6, "crossfade": 8, "fit": true}`.

- `order: "smooth"`: each track's tempo (onset autocorrelation, folded into 60-120 BPM, cached as `cache/music/<hash>.tempo`) and `vibe` give a cost between any two tracks (octave-aware tempo distance plus vibe distance). Each cycle is the best of 48 seeded walks, each step to one of the 3 nearest unplayed tracks (score: sum + 3 × the worst change); the first third of a cycle avoids the last third of the one before. Default `"shuffle"` is the old reshuffle (Treetop's plan is unchanged).
- `opener`: the file name or title of the track that opens the video (his favorite).
- `body_db`: each track plays its body only: from 1 s before it first comes within this many dB of its own level to 0.5 s after it last holds it (stored as `outro_cut`). Long quiet intros and fade-outs made changes dip up to 19 dB.
- `fit: true`: every change gets its own trim of the outgoing track (0-3 s), skip into the incoming one (0-3 s) and overlap (6, 8 or 10 s), chosen to keep the level up across it (entries carry `skip`, `trim` and `fit_dip_db`). Ramen, measured with `music.py` `transitions()`: dips median 1.8 dB, max 4.5 dB, against median 2.0 and max 9.6 inside tracks; level jumps between songs median 1.8 dB (natural differences). A level-matching term in the order was tried and dropped: tracks repeated after 25 minutes instead of 36.
- loop_master's QA `music_transitions` measures the first 24 changes of the built plan; a fitted plan fails with any dip over 6 dB.

### Music sources (terms checked 2026-10-19)

| Source | License | Fit | Notes |
|---|---|---|---|
| Free Music Archive, HoliznaCC0 (`music_fetch.py fma holiznacc0/<album>`) | CC0 1.0, shown on each track's page and on the artist's Bandcamp | lofi, chill, some jazz guitar | human-made; direct MP3s; popular, so a stranger could register a track with Content ID: keep the license page as dispute evidence |
| github.com/btahir/open-lofi (`music_fetch.py openlofi <category>`) | CC0 1.0 (LICENSE and catalog.json) | 166 lofi tracks in 10 categories (chillhop, jazzhop, late-night, asian-lofi, seasonal-weather, activities ...) | **made with Suno v5** (sidecar `ai_made: true`): per DECISIONS 2026-10-16 a video using AI-generated music answers YouTube's AI question Yes; public text still never mentions AI |
| YouTube Audio Library | YouTube's own; some tracks CC BY | lofi, jazz | no Content ID claims on Standard tracks; downloads only in Truman's YouTube Studio (an agent can't fetch them) |
| Pixabay Music | Pixabay Content License (not CC0) | large lofi and jazz catalog | needs Truman's OK; composers sometimes register tracks with Content ID (clear it with Pixabay's license certificate) |
| Kevin MacLeod, incompetech.com | CC BY 4.0 (credit line required) | jazz, lounge | needs Truman's OK; FreePD.com (his public-domain site) is offline |
| Lofi Girl / Lofi Records | not free in videos published after 2026-05-20 | | out |
| Uppbeat, StreamBeats | exclude music-listening videos and music-only "radio" | | out for 10 h music-under-ambience videos |
| Chillhop | Creator Program only, credit required, not for music-forward videos | | out |

## Add a sound for a new event

1. Store everything the sound needs on the timeline event (position or pan, dips, a `seed`); if it needs per-time data only the renderer has, add it in `writeTimeline` (`src/cli.mjs`) with the renderer's own code (as `boatProfile`). See the ambient-events skill.
2. In `tools/cozy/audio/ambience.py` (the code `tools/audio.py` runs): add the next unused integer to `LAYER` (never renumber existing ids) and a level to `DEFAULTS["events"]` (e.g. `"my_db": -12.0`); write a pure synthesis function `def my_sound(r, ...)` in `tools/cozy/audio/events.py` that uses only its `r` generator.
3. In `Ambience.__init__` (ambience.py) collect the events (`self.mine = [e for e in tl.get("events", []) if e["type"] == "my"]`), and in `event_waves(t0, t1)` add a loop: skip events whose sound can't overlap `[t0, t1)` (allow for the sound's full length, as boats allow 90 s for the laps), build the wave once per event with `rng(self.seed, LAYER["my"], ev["seed"])`, cache it under `("my", ev["id"])`, level it with `self._level(wave, ec["my_db"], 0.4)` (momentary) or `3.0` (short-term for long sounds), pan it from the screen x (`(x − 0.5) × 1.6`, clipped to ±0.9) with `stereo()`, and return `(start_s, wave)`.
4. A sound with no visual counterpart can be decided statelessly per trigger, like `creaks()` (seeded by the trigger index, so any range agrees).
5. Check: `audio.py <timeline> --start <t−5> --duration <length+20> --out ... --stems --report` (events ≥ 3 dB under the bed), listen to `_events.wav` and to the mix in a `preview --event`.

## Add an ambience layer for another setting

1. **Pick the mechanism.** Impulsive textures (crickets, fire crackle, surf foam, heavy canopy drips) are grain layers: a bank of 12–16 kernels `k_<name>(r)` (unit energy, well under 3 s) in `banks`, plus an entry in the `specs` dict in `block()` (bank, rate, amplitude σ, pan law, seed key). Continuous textures (surf roar, wind in pines, room tone) are noise layers: `self._noise(layer, key, t0)` through a FIR from `design_fir([(Hz, dB), ...])`, as `wash` and `wind` do. Anything longer than the 3 s warm-up (a breaking wave's wash, a distant train) must be a self-contained wave placed from a seeded schedule, like the event sounds and `creaks()`.
2. **Modulate from absolute time only:** `self.intensity(t, key)`, `self.gust(t)`, `self.track(key, t)` (weather track), `self.snoise(key, t, period)` (seeded smooth noise). If the picture shows the same rhythm (surf sets, fire flicker), share one formula or one schedule through the timeline JSON, as runoff shares `flowAt`.
3. **Register it:** a new `LAYER` id, `levels_db`, `rates` (grain layers) and `reverb.sends` entries in `DEFAULTS`. New dry layers join the `rain` stem automatically; a separate stem needs changes in `block()` and `render()`.
4. **Remove what doesn't belong:** the Treetop bed always includes roof drumming, lake bubbles and creaks. There is no on/off switch: lower a layer's level (e.g. `levels_db.roof: -120`) or add a scene switch in `block()`. Never set a grain rate to 0 (`_norm` divides by it and the layer turns into NaN).
5. **Bump `VERSION`** (re-calibrates loudness), then check determinism (render a range twice, and a sub-range of a longer render: identical up to the WAV dither), `--report`, a spectrum with `audio_analyze.py`, and listen on headphones and speakers. Keep levels relative to the bed; calibration rescales the whole bed to `lufs`, so a loud new layer quietly lowers the others.

Beds per setting exist since 2026-10-16 (`BEDS` in tools/cozy/audio/ambience.py; `choose_bed()` picks one from the weather and whether there's a fire; scene `audio.bed`, `audio.extra_db` overrides, `null` removes a layer):
- `rain` lists the rain layers that play (the others are skipped, no `-120 dB` trick needed), `muffle` dulls rain heard through glass, `extra` adds non-rain layers with levels.
- Layers: `fire` (low roar + hiss + crackle and pop grains, panned by `fire_pan`), `murmur` (a distant café crowd: 10 band-limited voices with syllable and phrase envelopes), `clink` (ceramic modes), `howl` (wind through gaps: resonant bands following the gusts and flurries), `room` (room tone), `city` (low traffic hum).
- Event sounds: car tire hiss, distant train, log settling, neon buzz, candle gutter (`events2` levels).
- Balance by numbers: `tools/audio_layers.py out/<scene>/timeline.json` prints each layer's loudness and share of the bed.

Still to build: surf = low roar noise × an irregular wave-set envelope plus placed wash/foam waves; crickets = tonal chirp kernels (pulse trains on a 4–5 kHz carrier) at a slowly drifting rate; wind in pines = a retuned `wind` layer (broader whoosh, more hiss).

## Gotchas

- The audio only knows what is in the timeline JSON: re-run `node src/cli.mjs timeline` after any change to the scene's `events`, `weather` or `audio` (preview and render do it for you).
- `audio_cal.json` lives next to the timeline JSON; it is re-made automatically when `VERSION`, the seed, the merged config, the weather block or the loop length change. Delete it if you change synthesis without bumping `VERSION`.
- Only runoff sources with `rate` ≥ 10 get splash grains; drips come from the separate seeded `drips` layer (not synced to the visual drips).
- Thunder and event waves are placed by their start time: a range that starts inside a long sound still gets its tail (render() looks back 40 s for thunder; event loops must allow for their own length).
- 24-bit output is TPDF-dithered with a seed from the file length; compare different-length renders with a tolerance.
- The music plan is part of the master render's fingerprint: decide on music before a long render.
