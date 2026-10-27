# Commands

The full command list (moved here from AGENTS.md on 2026-10-21 to keep the always-loaded file small). AGENTS.md keeps the everyday ones.

```powershell
# AUTOPILOT (default since 2026-10-21): one idea in, a reviewed 5 minute sample with music out; one stop for Truman's OK
.venv\Scripts\python tools\autopilot.py run "<idea>" [--look <id>] [--pick <png>] [--budget 6]   # state, log and per-stage logs in out/<scene>/auto/
.venv\Scripts\python tools\autopilot.py run --scene <scene> --from <stage>   # resume after a fix (gates: checks, review, critic)
.venv\Scripts\python tools\autopilot.py run --scene <scene> --weather "<his answer>"   # after exit 4: his line named no weather, so you asked him (L155)
.venv\Scripts\python tools\autopilot.py status <scene> | look "<idea>" [--apply]
.venv\Scripts\python tools\plate_features.py <scene> [--only perch,moth,smoke,petals,liquid,critter,ant] [--dry] [--force] [--reuse]   # what the plate offers -> scene.json; check out/plates/<scene>/features_preview.jpg
.venv\Scripts\python tools\critic.py <scene> --render out\<scene>\render\<tag> [--only steam,pet,...] [--refs <dir>]   # the vision model's eye checks -> <render>/critic/critic.md (exit 1 on a confident FAIL)
.venv\Scripts\python tools\hand_region.py <scene> --box x0,y0,x1,y1 --kind plant|curtain --name <name> [--outdoor|--indoor] [--sway amp,hz,gust] | --from-static <render>\review\first40s_static.json   # a region the analysis missed (foliage, cloth): SAM from a box -> hand.json + its sway, masks rebuilt
.venv\Scripts\python tools\critic.py <scene> --render <approved render> --approve --note "his words"   # after his OK: approved references for the next scene of the look
.venv\Scripts\python tools\critic_selftest.py   # the judge against approved references and synthetic failures of his past complaints (must score every case right after any rubric change: 15/15 on 2026-10-21)
.venv\Scripts\python tools\music_auto.py <look> [--scene <scene>] [--budget 2] [--dry-run]   # a playlist for a look without music: CC0 and open-lofi sources, screened, curated, ledgered
.venv\Scripts\python tools\finish_video.py <scene>   # after his OK on the sample: loop window, 10 h with music, thumbnails, upload folder

# REAL FOOTAGE (user 2026-10-22, the aquarium): his own locked-off recording looped to 10 h. Settings: scenes/<scene>/footage.json
.venv\Scripts\python tools\footage_loop.py analyze <scene>   # one decode at 320x180 RGB of the part from footage.json "in" (~10 min for 18 min of 4K 4:2:2), then seam; loop_seconds must fit in that part with the dissolve and divide target_s (C0140: 1000 s, 36 loops)
.venv\Scripts\python tools\footage_loop.py seam <scene>      # the loop with the fewest fish ghosts + the busiest opening; look at out/<scene>/footage/seam_dissolve.jpg (the biggest fish in the middle row: one fish, not two) and opening_strips.jpg, then pin loop_start and opening in footage.json (frames of the whole recording)
.venv\Scripts\python tools\footage_loop.py heroes <scene>    # 4K stills of the fish for thumbnails -> out/<scene>/stills/hero_f<frame>.png, hero_crops.jpg
.venv\Scripts\python tools\color_edit.py <scene> [--port 8765] [--no-browser] [--no-open]   # HIS COLOR EDITOR (user 2026-10-23): http://127.0.0.1:8765, a 4K frame of any moment of the loop with iPhone's sliders and Sharpness (tools/color_grade.py), previewed on the GPU through the render's own LUT and kernel; Save look -> footage.json "grade" (+ out/<scene>/color/saved_<look>.jpg made by ffmpeg, history.jsonl); Preview clip -> 20 s 4K with the look at the 10 h's settings, opened in his player. A saved look reaches the 10 h only through a new window --tag, then master
.venv\Scripts\python tools\footage_loop.py grades <scene> [--frame N]   # six looks A to F on one frame (highlights, contrast, brilliance) -> out/<scene>/footage/grades.jpg, without the editor; footage.json "grade" is applied in 10-bit by window, cut and heroes (one 3D LUT on the camera's codes; a new look needs a new --tag)
.venv\Scripts\python tools\footage_loop.py cut <scene> [--tag cut_v1]   # his review cut: the source from footage.json "in" (s) to the end, one encode, the soundtrack the 10 h will have, no loop -> out/<scene>/render/<tag>/cut_music.mp4, water_only_60s.wav, qa.md (music_over_water: the music stays louder than the water)
.venv\Scripts\python tools\footage_loop.py window <scene> [--tag loop20_v1]   # i.mp4 (12 s with the opening line), a.mp4, b.mp4 (the rest, the dissolve inside): HEVC 10-bit NVENC, VBR 46 Mbit/s, ~30 min
.venv\Scripts\python tools\footage_loop.py master <scene> [--tag loop20_v1] [--name 10h_v1]   # the water bed + music over footage.json target_s (10 h), i, b, (a, b) x (loops - 1) by stream copy, the first 12 s once more to pass 10:00:00, QA -> master_music.mp4, qa.md
.venv\Scripts\python tools\water_bed.py --seconds 60 --out <wav> [--lufs -23] [--minecraft]   # water for the aquarium: running water made in code (v3), or Minecraft's own flowing water from his install (--minecraft; footage.json water.cfg {"kind": "minecraft"}), periodic
.venv\Scripts\python tools\listen.py <audio or video> [--start 10] [--want "what it should be"]   # the audio model hears 30 s: blind first, then rated (~$0.03)

# NEW VIDEO in any aesthetic (new-video skill; three stops: key-art pick, sample approval, music pick). Scenes are data: scenes/<scene>/scene.json
.venv\Scripts\python tools\new_video.py plan <scene> --aesthetic <id> --auto [--hint "..."]   # brief (config/aesthetics.json) + keyart.json
.venv\Scripts\python tools\new_video.py keyart <scene> [--n 2]        # candidates + out/<scene>/keyart_sheet.jpg   (STOP 1: user picks)
.venv\Scripts\python tools\new_video.py pick <scene> <png | --auto>   # record the hero (--auto: the vision model scores)
.venv\Scripts\python tools\new_video.py prep <scene>                  # 4K plate + depth (plate_prep.py)
.venv\Scripts\python tools\new_video.py analyze <scene>               # vision model + SAM 2 -> regions, masks json, scene.json draft (analyze_plate.py [--reuse] [--verify] [--force-scene])
.venv\Scripts\python tools\analyze_plate.py <scene> --critter-occ      # after moving or adding a critter path: what every track hides behind at its ends -> occ.png + occ_<track>.png (check occ_preview.jpg)
.venv\Scripts\python tools\critter_ends.py <scene>                   # every critter's ends hidden by the renderer's own rule, and every cover standing, not flat ground (exit 1 if not; review lint L144)
.venv\Scripts\python tools\art_edit.py <scene> --name <n> --sky | --sam "x,y;x,y" | --green <polygon> --prompt "..." [--grow 6] [--dry]   # an art change he asks for on a key art in use (a prettier sky, other crops): masked edit of clean.png, no color fit, logged in clean.json, plate rebuilt with --keep-depth
.venv\Scripts\python tools\pet_sprite.py <scene> ref | patches [--only drowsy,half,awake,empty] | pose <rise|sit|stand|views> [--dry] | posecut <name> | pderive [--only walk_side,walk_back,walk_front,wag_back] [--dry] | cut | sheet   # MOCK: the painted pet as pixel sprites for src/library/petsprite.js. Every pose painted from the one before it (the painted head carried up by whole cells, only the body between painted; rig.json `poses`), the views beside the standing dog, the cycles repaint only legs or tail (`zones`). --dry first: it spends nothing. Order: ref, patches, pose rise/sit, pose stand, pose views, posecut each, pderive, cut
.venv\Scripts\python tools\new_video.py clean <scene>                 # remove painted steam, flames, hanging drops, drips anywhere (vision scan) (plate_clean.py, Azure image edit) + rebuild the plate; check clean_preview.jpg, strands_verify.jpg
.venv\Scripts\python tools\new_video.py life <scene>                  # critter sprite (critter.py), the fire's clips (fire_clips.py: local Wan 2.2, ~10 min GPU per clip) and the simulated steam over every cup, bowl and pot (steam_sim.py, ~2-3 min GPU each); keep the GPU free. No pet clips: a painted pet only breathes
.venv\Scripts\python tools\steam_sim.py <scene> [--region <name>] [--preview 20] [--set k=v,...] [--out <dir>]   # the steam fluid simulation alone -> out/plates/<scene>/steam/<region>/ (looping flipbook for steam.js; steam.json edge_max and down_max must stay ~0, review.py checks)
.venv\Scripts\python tools\leak_check.py <scene>                      # no weather over pets, cups, candles, lanterns (must PASS)
.venv\Scripts\python tools\weather_audit.py <scene>                   # every weather source over the plate (rain, rings, upright wet, drops, strand drips, runoff) + dry pockets (gaps without rain; crops in audit_pockets/) + wet frames (rain over a frame, mullion or handle; crops in audit_frames/); exit 1 on either -> out/plates/<scene>/weather_audit.jpg
.venv\Scripts\python tools\mask_edges.py <scene>                      # straight lines in the rain and ring masks where the picture has none (a box's edge through open ground, L151); exit 1 on a rain line -> out/plates/<scene>/mask_edges.jpg
.venv\Scripts\python tools\outdoor_check.py <scene> [--repair] [--rounds 3] [--first-pass auto|on|off]   # the vision model on every tile of where the weather draws (tinted, 1:1): nothing inside, no frame, no indoor water under it (must PASS; cached per tile); --repair traces what it finds with SAM and cuts it (hand.json outdoor_cuts) -> out/plates/<scene>/outdoor_check/; with --repair the local model screens first (free), Azure confirms its flags and has the final look at every tile (config/local_vision.json first_pass, L122)
.venv\Scripts\python tools\outdoor_check.py --selftest                # its fixtures (assets/reference/selftest/outdoor_*): must score 3 of 3 after any change to its prompt or evidence
.venv\Scripts\python tools\local_vision.py [--model qwen3.5-9b] compare   # a local vision model (llama.cpp on this PC's GPU, config/local_vision.json) on outdoor_check's own evidence, scored on labeled cases (assets/reference/selftest/outdoor_cut_labels.json), no Azure -> out/local_vision/compare_<model>.md; nothing is routed to it until Truman OKs (config "purposes" empty); serve | stop | status | ask <image> "q"
.venv\Scripts\python tools\review.py <scene> [--render out\<scene>\render\<tag> | --clip <mp4>]   # every check from the lessons (.agents/skills/new-video/references/lessons.md) + the eye-check list; must PASS before anything is shown
.venv\Scripts\python tools\new_video.py sample <scene> [--seconds 10] # busiest 10 s with sound -> out/samples/<scene>.mp4   (STOP 2: user approves)
.venv\Scripts\python tools\motion_review.py <clip.mp4> [--crops ...] [--ask]   # motion heatmap + crop strips (+ the vision model's opinion)
.venv\Scripts\python tools\motion_review.py <clip.mp4> --static <scene>      # nothing that should move may be still, measured in the thing itself, rain in front doesn't count (must exit 0 before showing)
.venv\Scripts\python tools\rain_motion.py <render dir or mp4> [--at 90] [--box x,y,w,h]   # where the rain moves over a dozen frames -> <render>/review/rain_motion.jpg (review.py makes it): no dark hole in the shape of anything out in the view (L121); red boxes where the rain falls in front of the dark but doesn't show (L152, review fails over 10%)
.venv\Scripts\python tools\event_sheets.py out\<scene>\render\<tag>            # contact sheets of every event (birds, critter, ant, neon, lightning...) + steam and water x-t strips -> <tag>/review/
.venv\Scripts\python tools\audio_layers.py out\<scene>\timeline.json           # loudness of each layer of a sound bed
.venv\Scripts\python tools\new_video.py catalog | status | spend      # near-duplicate check, stages done, Azure spend (out/azure_usage.jsonl)
# key art (Azure, keyless) -> assets/keyart/<scene>/*.png + .json sidecars
.venv\Scripts\python tools\keyart.py scenes\<scene>\keyart.json [--only id] [--model gpt-image-2]
# plate: 4K + depth + masks -> out/plates/<plate>/ (masks: assets/keyart/<plate>.masks.json; hand fixes for analyzed scenes: <plate>.hand.json)
.venv\Scripts\python tools\plate_prep.py assets\keyart\<plate>.png --name <plate> [--masks-only | --redepth]
# render (three.js in Electron, NVENC HEVC); --params k=v,... reaches the scene as ctx.params
node src/cli.mjs still    scenes/<scene> [--frames 0,900] [--width 1920 --height 1080] [--params debug=rain]
node src/cli.mjs preview  scenes/<scene> [--seconds 10] [--start <frame> | --event lightning:0 | --event farflash:3 | --event boat:1 | --event heron:0 | --event fish:2 | --event flurry:0] [--audio off]   # A/V preview (audio muxed)
node src/cli.mjs timeline scenes/<scene> [--duration 1h]   # seeded event timeline + weather sync -> out/<scene>/timeline.json
# master render: segmented (5 min) + resumable (re-run after a crash), video on the GPU while audio segments render on the CPU;
# -> out/<scene>/render/<tag>/ master.mp4 (+ master_music.mp4), ambience.flac/.m4a, timeline.json, thumbs/, credits.txt, qa.md
node src/cli.mjs render   scenes/<scene> [--duration 1h|10h] [--seed N] [--segment 300] [--name tag] [--music auto|off] [--cq 19] [--qa full|quick|off] [--force]
node src/cli.mjs render   scenes/<scene> --from 8h --length 1h    # one window of the real master (e.g. the CP4 test hour)
# the 10 h upload is a 20 min window looped (user 2026-10-19): scene.json events.loop.period 1200 makes the timeline repeat,
# so frames and sound join exactly; loop_master adds the intro title segment, plans music over the whole length, QA (loop_seam, joins, music_transitions)
node src/cli.mjs render   scenes/<scene> --from 20m --length 20m --name loop20_<v> --music off   # the loop window
.venv\Scripts\python tools\loop_master.py out\<scene>\render\loop20_<v> --times 2 --name preview_40min   # 40 min with title and music for Truman's ears; then --times 30 --name 10h_<v>
.venv\Scripts\python tools\intro_title.py <scene>      # the opening line (scene.json intro) in the look's title_font (config/fonts.json) -> out/plates/<plate>/intro.png + intro_preview.jpg
# older scenes without events.loop (Treetop): loop an approved test hour, without rendering (user 2026-10-16): seamless audio joins, QA;
# with tracks in music/ also master_music.mp4 (playlist planned over the whole 10 h); an up-to-date master.mp4 is kept
.venv\Scripts\python tools\loop_master.py out\<scene>\render\<tag> [--times 10] [--xfade 3] [--offset 5m] [--music auto|off] [--music-lufs -16.5] [--ambience-db -2] [--force]   # -> out/<scene>/render/10h_loop_<tag>/
.venv\Scripts\python tools\loop_master.py out\<scene>\render\<tag> --preview 7m-11m "--ambience-db=0,-2,-3.5" [--offset 5m]   # short frame-exact A/V clips of the music version: approve the sound before building
# audio: procedural ambience + thunder + event sounds from the timeline (random access, deterministic); loudness report
.venv\Scripts\python tools\audio.py out\<scene>\timeline.json --start <s> --duration <s> --out out\<scene>\audio.wav [--stems] [--report] [--music out\<scene>\music_plan.json]
# music slot: tracks in folders under music/ (gitignored), each with a sidecar <file>.json {title, artist, source, license[, license_url, attribution, origin]}.
# Each look has its own folders (scene.json audio.music.dirs, else music_dirs in config/aesthetics.json); the root music/ is the Mojang allowlist, Minecraft looks only
.venv\Scripts\python tools\mc_music.py check | import | list   # Minecraft music: verify the allowlist on the live Creator-Safe Playlist, copy it from the game files into music/
.venv\Scripts\python tools\music_fetch.py fma <artist>/<album> | openlofi <category> --to music\_candidates\<style>   # candidates from checked sources (license read per track; CC0 unless --allow with Truman's OK)
.venv\Scripts\python tools\music_screen.py music\_candidates\<style> --scene <scene> [--style "..."]   # an audio model (Azure gpt-audio-1-5) listens: vocals, mood, fit -> screen.json + ranking
.venv\Scripts\python tools\music_samples.py out\<scene>\render\<tag> music\_candidates\<style> [--top 6] [--seconds 70] [--start 0]   # one A/V clip per candidate track over the render (picture, ambience, music mixed as the real video) -> out/samples/music/<scene>/ + index.md (STOP 3: Truman picks)
.venv\Scripts\python tools\music_like.py <favorite> [<favorite> ...] --in music\_candidates\<style> --pick 28 --to music\<look-folder>   # curate around his picks: CLAP likeness (local), clean tracks only, a quota per favorite
.venv\Scripts\python tools\music.py plan    out\<scene>\timeline.json     # seeded playlist from the scene's folders (audio.music: order smooth, opener, body_db, fit) -> music_plan.json
.venv\Scripts\python tools\music.py credits out\<scene>\music_plan.json   # credits.txt for the YouTube description
.venv\Scripts\python tools\music.py ledger  out\<scene>\music_plan.json   # upsert the tracks into docs/asset-ledger.csv
# YouTube thumbnails: frame (rendered + cached), punchy grade, the channel's pixel font (tools/pixelfont.py); up to 3 variants for Test & compare
.venv\Scripts\python tools\thumbnail.py assets\thumbnails\<scene>.json [--only <name>] [--refresh]   # -> out/<scene>/thumbnails/<name>.jpg (4K) + _1280.jpg + preview.png
# upload package (user 2026-10-16): one folder per video with the video (hard link), the suggested thumbnail + all alternatives,
# title/description/tags/credits and a README of the YouTube Studio steps; checks YouTube limits, Mojang naming, no-AI text, voice rules
.venv\Scripts\python tools\upload_package.py assets\publish\<scene>.json   # -> upload/<slug>/
.venv\Scripts\python tools\audio_analyze.py <audio or video file>             # spectrum, LUFS, true peak, stereo, impulsiveness
# weather QA: rain leaks, loop seam + determinism, visibility per band, lightning flash safety, calibration vs footage
.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --leak --seam [--flash] [--profile] [--calibrate docs/reference/treehouse-rain-stats.json] [--params rain.alphaRef=0.4]   # --params: profile/calibrate only
.venv\Scripts\python tools\rain_analyze.py <frames_dir f_*.png> <out_dir>   # streak/speed stats of any clip
# promotion drafts (text files in marketing/drafts/<slug>/): voice rules, length limits, spam wording, @mentions, one link
.venv\Scripts\python tools\marketing_check.py marketing\drafts\<slug>
# Azure resources (idempotent / teardown)
.venv\Scripts\python tools\azure_provision.py [--teardown]
# code changes (TASKS.md, 2026-10-26): the free offline safety net, before and after any change to tools/, src/ or scenes/
.venv\Scripts\python -m unittest discover -s tests -v   # every tool imports, every cross-tool reference resolves, every JS module, scene and dynamic import resolves in Node, each scene's timeline and the sound match tests/goldens, the JS and Python formulas agree, types.json, ruff (~1 min)
$env:COZY_SLOW = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_goldens.py; Remove-Item Env:COZY_SLOW   # also the stills of 17 scenes against tests/goldens/stills.json (~2 min), after any change to src/ or scenes/
$env:UPDATE_GOLDENS = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_scenes.py; Remove-Item Env:UPDATE_GOLDENS   # record the timeline goldens again, on code you trust, after a deliberate timeline change
# going public (security review 2026-10-26): the pre-commit hook runs secret_scan --staged on every commit
.venv\Scripts\python tools\secret_scan.py --tracked     # or --history: keys, tokens, this PC's user folder, .git/info/private-terms
.venv\Scripts\python tools\go_public.py C:\dev\cozy-vibe-vids-public   # the public repo (github.com/TrumanBrown/cozy-vibe-vids-public; the folder is its clone): a snapshot of main without the private notes, checked (secrets, private paths, his words, binaries), committed; then git -C C:\dev\cozy-vibe-vids-public push
```

- Launch Electron only via `node src/cli.mjs` (`electron.exe` is a GUI-subsystem binary, so the shell won't wait for it).
- PowerShell: pass negative-number flags as `--target=-4,1,-40`. Windows PowerShell 5 corrupts UTF-8 when piping text into Node/Python, so write script files instead.
