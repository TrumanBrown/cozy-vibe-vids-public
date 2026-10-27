# cozy-vibe-vids

Code-animated **10-hour cozy ambience videos** for working, studying and sleeping, in many aesthetics (a Minecraft treehouse, a wizard library, a rainy café, a Ghibli-like cottage, a ramen alley, pixel art), designed to qualify for YouTube monetization.

Each scene is one AI key-art image, animated in code: rain, rain on glass, snow, fire, steam, candles, neon, passing cars, water, a sleeping pet, seeded events with synced sound. Everything that moves is deterministic from a scene config + seed.

> **Status:** six videos are live on [Sweater Weather Productivity](https://www.youtube.com/@SweaterWeatherProductivity). Live status: [docs/STATUS.md](docs/STATUS.md).

## Videos made with it

<table>
  <tr>
    <td width="50%"><a href="https://www.youtube.com/watch?v=wBFn90W5qh4"><img src="https://img.youtube.com/vi/wBFn90W5qh4/maxresdefault.jpg" alt="welcome home, critter. PNW friends in the rain, 4k, 10hrs" width="100%"></a></td>
    <td width="50%"><a href="https://www.youtube.com/watch?v=T8eYj7_AWBU"><img src="https://img.youtube.com/vi/T8eYj7_AWBU/maxresdefault.jpg" alt="stressed? come relax in the blossom veranda" width="100%"></a></td>
  </tr>
  <tr>
    <td valign="top"><a href="https://www.youtube.com/watch?v=wBFn90W5qh4">welcome home, critter. PNW friends in the rain</a><br>The channel's own critters in an ink-and-gouache look. Breathing, blinks, the fire, the soup's steam, the leaves in the wind and the rain are all animated in code.</td>
    <td valign="top"><a href="https://www.youtube.com/watch?v=T8eYj7_AWBU">stressed? come relax in the blossom veranda</a><br>Minecraft style, with Mojang's calm music. Rain on the pond, drips off the eaves, falling petals, fish, birds on the bridge, a gecko on the ledge, the tea's steam and a sleeping dog that breathes.</td>
  </tr>
</table>

## The idea

Videos like [Rainy Apartment (10 Hours)](https://www.youtube.com/watch?v=eFVPmqgZAi4) pull big audiences, but under the hood they're a locked camera on a cozy scene, a few short seamless loops (rain, a spinning fan, a ticking clock), occasional state changes (the dog lies down), and rare surprises (lightning). That structure is a natural fit for code. Get the formula right on one great video, then make many *different* scenes like fall evening, cloudy jungle day, snowy cabin, …

## Goals

1. **Video #1**: one excellent, original 4K / 30 fps / 10-hour rainy-evening scene (Treetop, published 2026-10-16): smooth seamless motion, rare events, event-synced ambience audio.
2. **A formula, not a one-off**: scene configs and a reusable layer and event library, so new scenes are fast to make and genuinely different (YouTube's inauthentic-content policy).
3. **Safe to monetize**: original or CC0 art and sound, and a license ledger for every external file. Minecraft and other franchise looks are allowed as a secondary part of a title, never logos or brand text ([AGENTS.md](AGENTS.md)).
4. **The whole package**: music, titles, thumbnails and the upload folder come out of the pipeline; the upload itself stays with Truman.

Full spec, acceptance criteria, and roadmap: [docs/GOALS.md](docs/GOALS.md).

## Start here (desktop)

1. In **native Windows** (not WSL — [why](docs/DECISIONS.md)), clone to a short path outside OneDrive-synced folders, e.g. `gh repo clone TrumanBrown/cozy-vibe-vids-public C:\dev\cozy-vibe-vids`, then open that folder **directly** in VS Code (not via Remote - WSL). Renders need a few hundred GB free; if that drive is tight, the agent puts `out/` on a bigger one. Machine setup: [docs/SETUP.md](docs/SETUP.md).
2. Open Chat, pick the **Video Studio** agent and say what you want, e.g. "generate me a new youtube video sample for pixel 8 bit style", or run **`/new-sample pixel 8 bit style`**. The agent runs `tools/autopilot.py` ([new-video skill](.agents/skills/new-video/SKILL.md#autopilot-the-default-user-2026-10-21)), fixes whatever its review gates find, and stops once: with a 5 minute sample with music for your OK.
3. After your OK it builds the 10 hour video and the upload folder. After you publish, **`/record-published <link>`** records what you changed so the next package matches. The original phase plan is in [docs/GOALS.md](docs/GOALS.md#roadmap--checkpoints).

## Repo map

| Path | What |
|---|---|
| [AGENTS.md](AGENTS.md) | Always-on rules for any AI agent working here |
| [.github/prompts/](.github/prompts/) | Slash commands: `/new-sample <idea>`, `/finish-video <scene>`, `/record-published <link>` |
| [.github/agents/media-outreach.agent.md](.github/agents/media-outreach.agent.md) | Media and outreach agent: plans launches and drafts posts. Drafts only; Truman posts |
| [.github/agents/video-studio.agent.md](.github/agents/video-studio.agent.md) | Video Studio agent: makes a sample from one line with tools/autopilot.py, fixes what the review gates find, one stop for your OK; the standing rules (nothing frozen, a painted pet only breathes, look before you show) |
| [marketing/](marketing/) | Campaign log and drafts for promotion (private notes: not in the public copy) |
| [docs/GOALS.md](docs/GOALS.md) | Vision, video #1 spec, acceptance criteria, roadmap |
| [docs/REFERENCE.md](docs/REFERENCE.md) | What we like about the reference video — and what we must not copy |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log (the *why*; private notes, a stub in the public copy); ADRs in [docs/decisions/](docs/decisions/) |
| [docs/research-phase0.md](docs/research-phase0.md) | Tools/sources found, used, and rejected |
| [docs/research-aesthetics.md](docs/research-aesthetics.md) | Which ambience aesthetics succeed on YouTube, and a ranked shortlist to test |
| [config/aesthetics.json](config/aesthetics.json) | Aesthetic catalog: style prompts, settings, motions, sound beds per look |
| [config/defaults.json](config/defaults.json) | Truman's settled defaults (event rates, loop period, music settings, sample length, budget) applied to every new scene |
| [config/local_vision.json](config/local_vision.json) | The local vision model (Qwen3.5-9B through llama.cpp on the GPU) that does the rain check's first passes for free before Azure's final look; setup in [docs/SETUP.md section 7](docs/SETUP.md#7-local-vision-model-saves-azure-credit) |
| [docs/research-agent-architecture.md](docs/research-agent-architecture.md) | How the agent setup is built (autopilot, gates, critic, lessons) and the sources behind it |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the code is built today: stack, what each folder and script is for, how data flows from one line to the upload folder, and the top technical debt |
| [.agents/skills/new-video/SKILL.md](.agents/skills/new-video/SKILL.md) | How a new video gets made (`tools/new_video.py`): brief, key art, automatic analysis, cleaning painted transients, the critter and the fire from clips, sample; the standing quality bar (a painted pet only breathes) |
| [spikes/](spikes/) | Phase 0 renderer spikes (three.js + Electron, Godot) on one shared benchmark scene |
| [docs/STATUS.md](docs/STATUS.md) | Current phase, done, next (private notes, a stub in the public copy) |
| [TASKS.md](TASKS.md) | The refactoring plan from the 2026-10-26 code review, in order, with what each task changed and how it was proven |
| [tests/](tests/) | The free offline safety net: `.venv\Scripts\python -m unittest discover -s tests` before and after any code change (tools, timelines, sound, the JS and Python formulas, types, a bug-finding lint); `COZY_SLOW=1` adds the stills of every scene |
| [tools/cozy/](tools/cozy/) | Shared code for the tools: paths and config, ffmpeg, model revisions, code hashes for caches, and the plate, audio and publishing steps the big tools are split into |
| [docs/asset-ledger.csv](docs/asset-ledger.csv) | License record for every external asset |

## Setup & commands

**Current pipeline** (one line → `tools/autopilot.py` → a reviewed 5 minute sample → `tools/finish_video.py` → the 10 h video and the upload folder): full machine setup in [docs/SETUP.md](docs/SETUP.md); the everyday commands are in [AGENTS.md](AGENTS.md#commands) and every command with its flags in [the new-video skill's commands reference](.agents/skills/new-video/references/commands.md) (`tools/keyart.py`, `tools/plate_prep.py`, `node src/cli.mjs still|preview|timeline|render`, `tools/loop_master.py`, `tools/audio.py`, `tools/music.py`, `tools/mc_music.py`, `tools/rain_qa.py`).

**Saving Azure credit with a local model** (since 2026-10-22): the rain check, which spent the most Azure credit, does its first passes on a vision model running on this PC's GPU (Qwen3.5-9B through llama.cpp), for free. Azure only checks what the local model flags, and it has the final look at every tile, so a pass is always Azure's. Everything else stays on Azure. How it works, the setup commands and how to turn it off: [docs/SETUP.md, section 7](docs/SETUP.md#7-local-vision-model-saves-azure-credit). Settings: [config/local_vision.json](config/local_vision.json).

**Your own recordings** (since 2026-10-22, the aquarium): put the clip in `scenes/<scene>/` with a `footage.json`, and `tools/footage_loop.py` loops it to 10 hours: from the usable part (footage.json `in`) it picks the stretch (20 minutes, or shorter when the usable part is) whose end dissolves into its start with the fewest fish ghosts, opens on the busiest moment, encodes once in 4K and repeats it without re-encoding, then adds water (`tools/water_bed.py`: made in code, or Minecraft's own flowing water) and the music planned over the whole video. To change the colors, `tools/color_edit.py <scene>` opens an editor in the browser with iPhone's sliders (Exposure, Highlights, Shadows, Contrast, Warmth and the rest) on a 4K frame of any moment; Save look stores the look in `footage.json`, and the next render of the loop uses it.

**One command rebuilds a whole video** from the scene config + seed: `node src/cli.mjs render scenes/treetop-plate --duration 10h` (segmented and resumable: re-run the same command after a crash). Output: `out/<scene>/render/<tag>/master.mp4`, plus the timeline, audio masters, thumbnails, `credits.txt` and a QA report. When a video is ready, `tools/upload_package.py assets/publish/<scene>.json` puts everything YouTube needs in one folder, `upload/<video>/`: the video, the suggested thumbnail and all alternatives, title, description, tags, credits, and a README with the upload steps.

Desktop (native Windows 11, RTX 4070 SUPER). Versions verified 2026-10-15.

```powershell
winget install --id OpenJS.NodeJS.LTS -e      # Node 24.20.0
winget install --id Gyan.FFmpeg -e            # ffmpeg 9.0.2 full build (NVENC h264/hevc/av1)
winget install --id GodotEngine.GodotEngine -e  # Godot 4.7.2 — only for the Godot spike
# Python 3.12.7 runs the tools: docs/SETUP.md makes its venv from requirements.lock.txt
```

Open a new terminal after installing so `node` and `ffmpeg` are on `PATH`. Godot gets no `PATH` alias; the spike finds it in the winget folder or via `GODOT=<path to Godot_v4.x_console.exe>`.

**Phase 0 spikes** (history: they chose the renderer that is now `src/`, [ADR 0001](docs/decisions/0001-tech-stack.md)):

```powershell
cd spikes/three; npm install; cd ../..        # three r186, Electron 44, Playwright (ws/headless comparison)
node spikes/shared/gen-textures.mjs            # original 16x16 textures (seeded)
node spikes/shared/gen-scene.mjs               # shared benchmark scene JSON (seeded)
node spikes/three/validate.mjs                 # 10 s 4K render + determinism/random-access/seam report -> out/phase0/three
node spikes/godot/validate.mjs                 # same for Godot -> out/phase0/godot (add --sdfgi to test GI)
```

If Electron's binary is missing after `npm install` (postinstall skipped), run `node spikes/three/node_modules/electron/install.js`.

## License

MIT, see [LICENSE](LICENSE). The vendored agent skills and the third-party assets keep their own licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
