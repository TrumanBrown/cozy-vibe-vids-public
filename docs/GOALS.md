# Goals — cozy-vibe-vids

> Living spec. When direction changes, update this file and log the *why* in [DECISIONS.md](DECISIONS.md).

## Origin (the user's brief, lightly edited)

> I put on a ton of videos like [this one](https://www.youtube.com/watch?v=eFVPmqgZAi4) on my TV while I work from home to create a good ambiance — and judging by the views, lots of people do. I think we could automate making these without needing Blender etc. If you look at them, they're basically X-second/minute clips that are looped, with some variations: the dog sitting for a while vs. lying down, the rain on the glass dripping down occasionally, the fan spinning.
>
> Start with small steps — no automating or auto-posting to YouTube yet. Get the formula working well on one video, then generate many more with different variants (fall evening, cloudy jungle day, etc.).
>
> Start with that Minecraft-like pixel style — but it doesn't have to be, and shouldn't be, fully Minecraft. The reference has the dog, but the bed, carpet, and buildings are just block-style, clearly not from Minecraft. Mix elements into a warm scene to work to. Smooth animations (rain falling, a clock ticking, maybe a bonfire), somewhat unique, with new elements occasionally — like the dog rolling around very rarely, or lightning striking rarely in the background.

## Vision

A code-only studio that turns **a scene file + a seed** into a calm, beautiful, **10-hour ambience video**: a blocky voxel room or place, warm light, gentle weather, maybe a pet: the kind of video people keep on in the background while working, studying or sleeping. No manual 3D, animation, or editing. Video #1 proves the formula; then the system makes many *genuinely different* scenes.

## Why code fits this format

These videos are almost entirely still (locked camera, static room). The motion falls into three layers:

| Layer | Examples | Character |
|---|---|---|
| Continuous loops | rain, ceiling fan, fire flicker, pendulum, swaying plants | always on, seamless |
| State changes | pet sleeping → sitting up → lying down (only with a 3D or library pet: a painted pet only breathes, see "Pets" 2026-10-18 below) | every few minutes |
| Rare events | lightning, pet rolls over, bird lands on the sill | a few times per hour |

So "10 hours" is really a few minutes of unique animation, arranged so it never *feels* looped. That's a perfect fit for deterministic, code-driven rendering: cheap to produce, fully controllable, and 100% original.

## Video #1 specification

### Concept

- **Chosen by the user at Checkpoint 2** from **3 concepts** the agent pitches as 4K still frames.
- All three: cozy, calm, evening or night, gentle weather (rain by default), warm interior light, one static wide shot.
- At least one is a close cousin of the reference (rainy city apartment/loft at night) — with an **original** layout and props.
- Each has a **signature detail** the reference doesn't (e.g., fireplace/bonfire glow, a cat on the windowsill, a sleeper-train window, a treehouse, a lighthouse lamp room).
- **Characters:** people are optional — include one only if it clearly adds warmth (e.g., someone reading, seen from behind). Animals are welcome but **don't overdo it** — usually one pet, maybe a passing bird.

### Output

| | |
|---|---|
| Resolution / frame rate | 3840×2160, 30 fps constant |
| Duration | 10:00:00 |
| Color | SDR, BT.709, limited range — see [YouTube upload settings](https://support.google.com/youtube/answer/1722171) |
| Codec / size | Decided in Phase 0 (likely H.264 or HEVC via NVENC). Stay well under YouTube's upload limit (256 GB / 12 h — verify). Target ≤ ~100 GB unless quality demands more. |
| Audio | Stereo, 48 kHz |
| Preview ladder | 10 s → 60 s loop → 1 h test → 10 h — step up only after approval |

Watch for **banding** in dark warm gradients (bloom, fog, vignette) — it gets worse after YouTube re-encodes. Use dithering/subtle grain; test a 10-bit master if it measurably helps.

### Look & feel

- **Blocky voxel world** — everything is blocks and cuboid parts (no curves or spheres), with low-res pixel textures at **one consistent texel density** (e.g., 16 texels per block) and nearest-neighbor sampling. This is what reads as "Minecraft-like" while staying original. Furniture can use sub-block cuboid models (chair legs, lamp arms).
- **Light** — warm practical sources (lamps, fire, lit windows; ~2200–3000 K feel) with bloom/glow, soft shadows, ambient occlusion, light haze for depth, gentle vignette. Low-key and soft; no clipped whites, nothing harsh.
- **Palette** — amber, orange, and deep brown dominate (hex values in [REFERENCE.md](REFERENCE.md#palette)); a dusky blue/purple exterior may add depth and separation. Avoid saturated primaries and pure white. Other scenes may shift (a daytime jungle → soft greens) but always stay calm.
- **Camera** — one locked-off wide shot, eye level or slightly above, with foreground / midground / background depth. No camera motion.
- **Restraint** — most of the frame is still; motion is calm and sparse.

### Motion & events (starting menu — finalize per concept)

| Type | Ideas | Frequency |
|---|---|---|
| Continuous | rain outside (soft sheets + chunky pixel streaks); drops running down the glass now and then; fire/candle flicker; ceiling fan; pendulum clock; plants swaying in the fan's breeze; steam from a mug; distant windows twinkling | always, seamless |
| State changes | pet pose changes (curled asleep ↔ stretched out ↔ sitting, looking around) with smooth transitions, ear flicks, tail wags: only for a 3D or library pet (a painted pet only breathes and sighs: "Pets" 2026-10-18 below) | every ~5–20 min |
| Rare | distant lightning (soft glow lights the room, thunder 2–6 s later); pet rolls over / stretches / yawns (3D or library pet only); bird shelters on the sill; car headlights sweep the ceiling; lamp flickers once; a page turns | ~0.5–3× per hour each; one at a time; no back-to-back repeats |
| Slow evolution (optional) | distant windows go dark late at night; rain intensity drifts; clock shows real elapsed time | across the 10 h, only if the architecture allows it cheaply |

**Density, user decision 2026-10-15 (after CP4):** more often than the starting menu. Lightning ~6/h in passing storm cells; about 25 noticeable events per hour in total, mixing spotlight events (one at a time) with small ambient ones (fish rises, gusts, people at distant windows, the pet). More animation makes it feel alive, within limits: realistic and calming first. Treetop v4 rates are in DECISIONS.md.

**Density, user decision 2026-10-16 (v5):** far more often, so the scene feels alive, but never chaotic: someone should be able to study to it. Lightning about every 2 minutes, but quiet: most of it distant flashes behind the mountains with soft low rumbles. Something happens about every 30–40 s on average, mostly small, with the spotlight events still one at a time. The water moves gently all the time.

**Pets, user decision 2026-10-18:** a pet painted into the key art only breathes, with an occasional sigh; no ear flicks or tail twitches. Generated video of the painted cat (lifting its head, sitting up) looked eerie, jerky, unclear and obviously AI. A pet that changes pose or moves around must be fully rendered (a 3D model) or come from a free asset library, animated in code, and only in looks it matches (blocky, pixel art, low-poly). DECISIONS 2026-10-18.

**Animatable props, user guidance 2026-10-16:** every key art includes one or two animatable props besides the pet, such as a steaming mug on a table, a fire (Minecraft-style or realistic) or a clock. Prompt wording and animation ideas are in the keyart-pipeline skill.

**Strong opening, user guidance 2026-10-16:** the start of the video is when people look hardest, so it is heavier on animation and gets to the music quickly, with less lead-up. The first ~5 minutes hold the richest events (a storm cell, a spotlight event, fish, a gust), and music is at full level within seconds.

All randomness is seeded and written to an **event timeline (JSON)** that drives both video and audio.

### Audio

- **Ambience bed** — CC0 recordings (or synthesized): rain from an indoor perspective, fire crackle if there's a fire, faint room tone.
- **Event sync** — thunder follows each lightning flash by 2–6 s, distant and never startling; other events get subtle sounds where natural.
- **Music slot** — tracks live in folders under `music/` (gitignored), one style per folder, each track with a small sidecar (title, artist, source, license). Each look draws from its own folders (scene.json `audio.music.dirs`, else `music_dirs` in config/aesthetics.json); the root `music/` holds the Mojang allowlist for Minecraft looks. The pipeline shuffles/loops them with crossfades to fill the duration under the ambience and logs them to the [asset ledger](asset-ledger.csv) for credits. New music is found, screened and sampled by tools (`music_fetch.py`, `music_screen.py`, `music_samples.py`), and Truman picks by ear (2026-10-19).
- **Mixes** — ambience-only and ambience + music, plus stems.
- **Loudness** (starting targets — tune by ear against popular ambience videos): ambience-only ≈ −20 LUFS integrated; music mix ≈ −16 LUFS, with the music bus at −16.5 LUFS over the ambience lowered 2 dB (user 2026-10-16); true peak ≤ −1.5 dBTP; thunder no more than ~6 dB above the bed short-term. No clicks or gaps anywhere. Level changes are approved on short preview clips before a 10 h build.
- **Never** C418 music or "Lava Chicken" (third-party Content ID claims). Minecraft music only from the Mojang-owned allowlist, [config/minecraft_music.json](../config/minecraft_music.json): tracks on Mojang's Creator-Safe Playlist, imported by `tools/mc_music.py` (DECISIONS 2026-10-16 "Minecraft music").
- *Later (not video #1):* auto-source calm music (jazz, lofi, ambient piano) **only** from sources whose license explicitly allows monetized YouTube use and won't trigger Content ID — "no copyright" labels aren't enough.

### Deliverables (in gitignored `out/<scene>/`)

1. 10-hour 4K master with ambience (+ a version with music if tracks are provided).
2. Audio stems (ambience, music mix).
3. The event timeline JSON used for the render.
4. 3–5 thumbnail candidate stills (4K PNG), and the finished thumbnails: up to 3 variants for YouTube's Test & compare, made with `tools/thumbnail.py`.
5. `credits.txt` generated from the asset ledger (for the YouTube description).
6. QA report: boundary-seam checks, determinism check, loudness, render stats.

## Architecture direction (validate in Phase 0)

Guidance, not a mandate — prove or disprove it with a benchmark.

- **Scene = data.** A config file (layout, props, palette, lights, weather, creature, events, audio) plus a reusable **library** (block textures/materials, props, creatures, effects, events, sounds). New scenes mostly reuse the library.
- **Pure frame function.** `frame = render(scene, seed, timeline, frameIndex)`; time = `frameIndex / fps`, never wall-clock, so any frame can be re-rendered identically.
- **Seeded scheduler** builds the timeline — state changes and rare events at target rates, with cooldowns, no back-to-back duplicates, one rare event at a time. Video and audio both consume it.
- **Assembly strategy** — benchmark, then choose or combine:
  - **A. Clip graph** — render one base seamless loop of length *L* (every continuous element periodic in *L*), plus *variant* clips (one rare event each) and *transition* clips (pet state A→B) that start and end in known states. A seeded walk through the graph is stitched into 10 h with `ffmpeg` concat + stream copy in minutes. Cheapest; no slow evolution; variant count grows with combinations.
  - **B. Full timeline** — render all 10 h frame by frame on the GPU with hardware encoding, in resumable segments. Independent timelines per element plus slow evolution. Viable if sustained 4K render+encode is roughly ≥ 30–40 fps (≈ ≤ 8 h per video — overnight).
  - Hybrids are welcome if justified (e.g., static plates + animated layers, additive light passes for relighting).
- **Candidates** — three.js (WebGL/WebGPU) rendered headlessly via Playwright/Puppeteer, optionally through Remotion + `@remotion/three` (check for its agent skills); Godot 4 (Movie Maker mode renders at a fixed fps offline; strong glow, volumetric fog, GI). Blender only with user approval. Pick on **look × determinism × 4K throughput × how easily an agent can author scenes in code**.
- **Tooling** — ffmpeg with NVENC; one CLI entry point (e.g., `render scenes/<name> --duration 10h --seed 42`); fast previews (single frame, 10 s clip, contact sheet); automated seam / determinism / loudness checks.

## Acceptance criteria — video #1 is done when

- [ ] The user approved the concept, the 60 s loop, and the 1 h test (CP2–CP4), then the final master (CP5).
- [ ] 10:00:00, 3840×2160, 30 fps CFR; plays start to end without glitches; under the target size.
- [ ] No visible seams/pops at any loop, clip, or segment boundary (automated frame-diff at every boundary + spot checks); no flicker or shimmering edges; no obvious banding after a YouTube-like re-encode.
- [ ] Events occur at the configured rates; the timeline JSON matches what's on screen and in the audio.
- [ ] Doesn't feel looped: no identical rare-event sequence repeats within an hour; base-loop repetition isn't noticeable in a 10-minute watch.
- [ ] Audio continuous and click-free; within loudness targets.
- [ ] Deterministic: re-rendering sampled ranges with the same seed yields identical hashes.
- [ ] One documented command rebuilds the whole video from config + seed.
- [ ] Asset ledger complete; only original or CC0 assets; [do-not-copy checklist](REFERENCE.md#do-not-copy-checklist) passes.
- [ ] README quickstart, architecture overview, "how to make a new scene" guide, and DECISIONS.md are current.

## After video #1 — repeatability

- **Aesthetics (user 2026-10-16):** one channel, many aesthetics, about two new videos a week, to learn which looks get the most views. The catalog is [config/aesthetics.json](../config/aesthetics.json); the evidence and ranked shortlist are in [research-aesthetics.md](research-aesthetics.md). Photoreal and stylized are both in; no humans in key art; franchise looks are named only as a secondary part of titles.
- **Flow (user 2026-10-21; before that three stops, 2026-10-16 and 2026-10-19):** one line ("generate me a new youtube video sample for <idea>", `/new-sample`) runs `tools/autopilot.py` to a reviewed 5 minute sample with music; one stop for the user's OK; then `tools/finish_video.py` and the upload folder. Procedure: the [new-video skill](../.agents/skills/new-video/SKILL.md) (Autopilot section).
- **Future scene ideas** (not commitments): the research shortlist plus fall evening, cloudy jungle day, snowy cabin, rainy sleeper train, lighthouse in a storm, greenhouse in rain, library at night, beach hut at dusk, ramen shop in the rain.
- **Target:** a new scene = a few hours of agent work + one approval loop, rendered overnight.
- **Anti-template guardrails** (YouTube *inauthentic content* policy): each video differs in setting/layout, props, time/weather, creature, and events — never just a palette swap. `tools/new_video.py catalog` compares every brief's fingerprint and flags near-duplicates before key art is made.
- **Packaging:** the "make a new scene" workflow is the `new-video` skill.

## Roadmap & checkpoints

| Phase | Work | Checkpoint — stop and wait for the user |
|---|---|---|
| 0 | Environment setup; research existing tools/skills/MCPs/CC0 sources; benchmark spike of the top 2 renderer stacks | **CP1** — stack recommendation with benchmark numbers, sample frames, tools to install |
| 1 | 3 concepts as 4K style frames, each with a pitch, palette, signature detail, list of motions and events, and creature design | **CP2** — user picks or mixes |
| 2 | Build the chosen scene with continuous motion; a 10 s preview first, then a seamless 60 s loop | **CP3** — user reviews the loop |
| 3 | States, rare events, scheduler; ambience audio + music slot; 1 h test render + timeline + loudness report | **CP4** — user reviews (ideally uploads it unlisted to check YouTube compression) |
| 4 | 10 h master, QA, all deliverables | **CP5** — final review |
| 5 | Repeatability: new-scene workflow + a second, clearly different scene | after CP5, on request. **In progress 2026-10-16:** aesthetic catalog, scene factory (`new-video` skill), five 10 s samples in new styles waiting for the user's review |
| Later | Licensed music sourcing per aesthetic; YouTube upload automation; reading YouTube Analytics so the next aesthetic follows what performs | not now |

## Non-goals (for now)

- No YouTube upload/scheduling automation or channel management.
- No music from unchecked sources: candidates come only from sources whose terms were checked (ambience-audio skill, "Music sources"), each track's license is read on its own page, and Truman picks by ear from clips before anything is built (2026-10-19).
- No AI video generation (user 2026-10-16: not needed; one image plus code animation covers most ideas). AI images are generated once per scene and saved; AI models also analyze the image (regions, masks), never during a render.
- No camera moves, narration, or on-screen text.
- Not a general-purpose engine — build only what scenes need.

## Policy references

- [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392) — *inauthentic content* (renamed from "repetitious content" on July 15, 2025) and *reused content*.
- [YouTube recommended upload encoding settings](https://support.google.com/youtube/answer/1722171).
- [WCAG 2.3.1 — Three Flashes or Below Threshold](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html) — for lightning.
- [Minecraft Usage Guidelines](https://www.minecraft.net/en-us/usage-guidelines):
  - No Mojang assets or logos.
  - "Minecraft" only as a secondary part of a title or channel name.
  - The not-official disclaimer in the description of every Minecraft-look video (`credits.txt` adds it, only for Minecraft looks).
- [YouTube AI disclosure](https://support.google.com/youtube/answer/14328491): required only for content that seems realistic.
  - Our stylized scenes answer "AI use: No" (decided 2026-10-16). Re-check for a photorealistic scene or AI-generated music.
  - Public text doesn't mention AI and stays factual (DECISIONS 2026-10-16).
- [YouTube Partner Program](https://support.google.com/youtube/answer/72851): 1,000 subscribers plus 4,000 public watch hours in 12 months, advanced features, 2-Step Verification, and one AdSense for YouTube account. Reviewers judge the whole channel.
