# Setup and reproduction guide

How to get a new machine (native Windows; WSL works for everything except GPU rendering) to the point where it can render this project. Agents: read this, then [STATUS.md](STATUS.md).

## 1. Tools

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e        # Node 24.x
winget install --id Python.Python.3.12 -e
winget install --id Gyan.FFmpeg -e              # ffmpeg with NVENC
winget install --id Microsoft.AzureCLI -e       # for AI key-art generation
# Godot is only needed for the Phase 0 spike: winget install --id GodotEngine.GodotEngine -e
```

Open a new terminal afterwards so the new `PATH` takes effect.

## 2. Repo + dependencies

```powershell
git clone https://github.com/TrumanBrown/cozy-vibe-vids-public C:\dev\cozy-vibe-vids
cd C:\dev\cozy-vibe-vids
npm install                                     # three + electron (renderer), versions pinned in package.json
python -m venv .venv                            # Python 3.12
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cu128
git config core.hooksPath .githooks             # every commit is checked for keys, user folders and private terms
git config user.name "Truman Brown"; git config user.email trumanbrown@users.noreply.github.com
```

Then put the private terms, one per line, in `.git/info/private-terms`: the Azure sign-in email, the subscription and tenant IDs (`az account show`) and the work email. The file stays inside `.git`, so it is never committed; `tools/secret_scan.py` refuses a commit that adds one of them or this PC's user folder, and `tools/go_public.py` uses the same list to clean the public copy (security review 2026-10-26).

`requirements.lock.txt` holds the exact versions the desktop runs (torch with CUDA 12.8 comes from PyTorch's index). numpy makes the ambience and torch runs the plate models, so a different version can change the sound or the plate of a rebuilt video: upgrade on purpose, then record the goldens again (`tests/test_goldens.py`). `requirements.txt` is the short list of what the tools import. `requirements-dev.txt` adds ruff for `tests/test_lint.py`, which looks only for undefined or unused names and bare `except:` (`ruff.toml`) and never reformats: `.venv\Scripts\python -m pip install -r requirements-dev.txt`.

Local models (SDXL, Depth Anything V2, Swin2SR, SAM 2.1 for `tools/analyze_plate.py`) download on first use into `cache/hf` (gitignored, about 46 GB with Wan 2.2), each at the revision pinned in `tools/cozy/models.py`. SAM 2.1 (`facebook/sam2.1-hiera-large`, Apache-2.0) is ~900 MB and not gated. Fire clips (`tools/fire_clips.py`, through the loader in `tools/cozy/wan.py`) use **Wan 2.2 TI2V-5B** (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`, Apache-2.0, ~34 GB download, needs `ftfy`): fp8 weight storage on the GPU, the text encoder on the CPU (~20 GB RAM), ~9 min per 97-frame clip on an RTX 4070 SUPER. Keep the GPU free while it runs: when VRAM overflows, Windows spills into shared memory and it slows 2-5x. (It no longer animates pets: DECISIONS 2026-10-18.)

## 3. Azure image generation (key art)

All Azure resources live in **one dedicated resource group**, so nothing else in the tenant is touched:

| | |
|---|---|
| Subscription | your own Azure subscription (its name and IDs: `az account show`; they stay out of the repo) |
| Resource group | `rg-cozyvibevids-img` (eastus2), tags `project=cozy-vibe-vids` |
| Account | `cvvimg-<suffix>` (kind AIServices, **API keys disabled**: Entra ID only) |
| Deployments | `gpt-image-2-5-sunburst` (default), `gpt-image-2` (GlobalStandard, capacity 1): key art. `gpt-6-sol` (GlobalStandard, 100K TPM): vision analysis, briefs and QA (`tools/azure_ai.py`) |
| Auth | your `az login` identity holds **Cognitive Services OpenAI User** on the account; no secrets anywhere |

```powershell
az login                                         # same tenant/subscription
.venv\Scripts\python tools\azure_provision.py    # idempotent: verifies/creates RG, account, deployments, role
.venv\Scripts\python tools\keyart.py scenes\treetop\keyart.json --only rainy_dusk
```

Non-secret settings (endpoint, deployment names, API version) live in `config/azure.json` (committed). To remove everything: `python tools/azure_provision.py --teardown`.

**Costs:** pay per token. A 2560x1440 `high` Sunburst image used ~1.8k-3.7k output image tokens (~$0.07-0.15) and gpt-image-2 ~7.4k; a gpt-6-sol image analysis is ~$0.02-0.06. Every call is logged with an estimate in `out/azure_usage.jsonl`: `.venv\Scripts\python tools\azure_ai.py spend [--since <date>]` (prices in `config/azure.json`; real charges are in the portal). Generate a few candidates per scene, not hundreds. No Azure call goes out once the day's logged estimate reaches `daily_cap_usd` in `config/azure.json` ($40, over twice the busiest day so far); `COZY_DAILY_CAP_USD` changes it for one run, 0 turns it off.

## 4. Pipeline (current direction, see DECISIONS.md)

**New videos in any aesthetic** go through `tools/new_video.py` (the `new-video` skill): a brief from `config/aesthetics.json`, key art, the plate, then `tools/analyze_plate.py` (vision model + SAM 2) writes the regions, masks and `scenes/<scene>/scene.json`, which `src/library/autoscene.js` turns into the animated scene. `clean` removes painted steam, flames and hanging drops from the key art with an Azure image edit (`tools/plate_clean.py`, ~$0.06 per edit window) and `life` makes the critter sprite and the fire's clips (a painted pet only breathes: no pet clips). The steps below are the parts it runs; Treetop is the hand-measured example.

1. **Key art:** `tools/keyart.py` + `scenes/<scene>/keyart.json`. Images and prompt sidecars go to `assets/keyart/<scene>/`.
2. **Plate:** `tools/plate_prep.py <image> --name <plate>` crops to 16:9 and upscales to 3840x2160 (Lanczos for gpt-image output; tiled Swin2SR for small inputs). It estimates depth (Depth Anything V2 Small at 1036 px) and builds motion masks; outdoors comes from depth. Painted-in rain streaks are removed. Hand overrides are in `assets/keyart/<plate>.masks.json`: masks, `waterfall` polygons (→ `flow.png`) and the `window_disp` band for switchable windows. It also writes the switchable-light maps (`lightid.png` + `lightw.png`: the 4 strongest lights per pixel and their shares, plus `plate_off.png`). Output goes to `out/plates/<plate>/`; re-run with `--masks-only` after editing the masks json.
3. **Animate + render:** `node src/cli.mjs still|preview scenes/<scene>` (three.js in Electron).
   - `src/library/plate.js` adds mist, calm water ripples (world space through the lake camera), sway, flicker, waterfalls, the pet's micro-motions, switchable lights, and lightning light (storm strikes plus distant flashes in the cloud bank).
   - `src/library/rain.js` adds physically based rain plus roof runoff, only outdoors.
   - `leaves.js` drops falling leaves, `boat.js` sails the ray-marched lantern boat, `fish.js` draws fish rises and `heron.js` a heron crossing the valley.
   - Events come from the seeded timeline (`src/library/timeline.js`).
   - New scene: start from the `plate-scene` skill and its template (`.agents/skills/plate-scene/assets/scene.template.js`).
4. **Audio:** `tools/audio.py` synthesizes the ambience (rain, runoff, drips, wind), thunder (storm strikes and soft distant rumbles) and event sounds (boat, lantern, fish, gust flurries, creaks) from `out/<scene>/timeline.json`. It needs only numpy and ffmpeg (no samples), and `preview` muxes it automatically.
   - **Optional music:** tracks live in folders under `music/` (gitignored), one style per folder, each with a `<file>.json` sidecar (title, artist, source, license); each look draws from its own folders (`music_dirs` in config/aesthetics.json, or scene.json `audio.music.dirs`). `tools/music_fetch.py` gets candidates with their licenses checked, `tools/music_screen.py` has an audio model listen to them (Azure `gpt-audio-1-5`), `tools/music_samples.py` makes clips to choose from. `tools/music.py` and `audio.py --music` turn the chosen tracks into a second, music mix.
     - **Minecraft music** (DECISIONS 2026-10-16) comes from the machine's own Minecraft: Java Edition install: `.venv\Scripts\python tools\mc_music.py check`, then `import`. It copies only the allowlist in `config/minecraft_music.json`. From WSL, pass `--minecraft /mnt/c/Users/<you>/AppData/Roaming/.minecraft`.
5. **Master render:** `node src/cli.mjs render scenes/<scene> [--duration 10h]`, or a test window such as `--from 8h --length 1h`.
   - **The 10 h upload from a test hour** (user decision 2026-10-16, the default now): render one approved hour, then `.venv\Scripts\python tools\loop_master.py out\<scene>\render\<tag> --times 10`. It stream-copies the hour's segments 10 times and rebuilds the audio joins seamlessly, in ~15 min with no rendering; output `out/<scene>/render/10h_loop_<tag>/master.mp4` (~110 GB) with its own `qa.md`. With tracks in `music/` it also writes `master_music.mp4` (another ~110 GB), whose playlist is planned over the whole 10 h. Re-running keeps an up-to-date `master.mp4`. Keep the hour's `seg/` folder until the loops are built.
     - **Sound first:** judge levels and the opening on `--preview 7m-11m "--ambience-db=0,-2,-3.5"` clips (a few minutes) before building.
     - **Opening:** `--offset 5m` starts the video on the busy part of the hour.
     - Afterwards re-run `tools/upload_package.py`, since the package's hard link keeps pointing at the old file.
   - **Resumable:** it renders 5 min segments; re-run the same command after a crash or restart to resume.
   - **Output:** `out/<scene>/render/<tag>/` holds `master.mp4`, audio masters, timeline, thumbnails, `credits.txt` and `qa.md`.
   - **Disk:** HEVC at CQ 19 runs ~20–25 Mbit/s for this scene, about 10–11 GB per hour. A 10 h master needs ~110 GB, plus ~100 GB of segments kept for resume and re-mux (delete `seg/` once the upload is verified), so keep ~250 GB free. `--cq 21`–`23` makes it smaller.
   - **Time:** ~3–4 h for 10 h on an RTX 4070 SUPER, video at ~100 fps when the CPU isn't busy with audio jobs.
6. **QA:**
   - `tools/rain_qa.py scenes/<scene> --plate <plate> --leak --seam --flash [--calibrate <stats.json>]` and `tools/audio.py ... --report` (loudness, true peak, thunder over bed, event sounds under the bed).
   - The master render writes its own QA report: frames, frame-exact segment joins, determinism, loudness and A/V sync.
   - Reference footage stats come from `tools/rain_analyze.py <frames_dir> <out_dir>` (frames extracted with ffmpeg as `f_%04d.png`).
7. **Local vision model:** the rain check's first passes run on the GPU for free and Azure has the final look. What it is, setup and use: [section 7](#7-local-vision-model-saves-azure-credit).

## 5. Agent skills

Third-party skills are installed with the open skills CLI (`npx skills`), and the lock file restores them. This repo's own skills (`new-video`, `keyart-pipeline`, `plate-scene`, `plate-weather`, `ambient-events`, `ambience-audio`, `master-render`, `marketing-outreach`) are committed in `.agents/skills/`, so a clone has them already.

```powershell
npx skills experimental_install                  # restores from skills-lock.json
```

See [AGENTS.md](../AGENTS.md#skills) for which skills are installed and why. For a new video, start with `new-video`.

Truman's writing skills (`truman-voice`, `humanizer`) and rules live at user level, not in the repo. On a new machine, install them from his voice pack by following its `START-HERE.md` (into `~/.copilot/skills/` and `~/.copilot/copilot-instructions.md`). Every title, description and channel text is written with them.

## 6. Gotchas

- Launch Electron via `node src/cli.mjs …` only (GUI-subsystem binary).
- Long renders: keep the machine awake and plugged in. Electron blocks app suspension while it renders, but a Windows Update restart can still interrupt; just re-run the same `render` command.
- PowerShell: pass negative-number flags as `--target=-4,1,-40`.
- Windows PowerShell 5 corrupts UTF-8 (em dashes) when piping text into Node/Python. Use script files or `[IO.File]::WriteAllText`.
- `StableDiffusionXLInpaintPipeline.from_pipe(...)` must get `torch_dtype=torch.float16`, or VRAM doubles to 13 GB and everything crawls.
- New Azure deployments can return `DeploymentNotFound` for a few minutes; `keyart.py` retries.

## 7. Local vision model (saves Azure credit)

Since 2026-10-22 the rain check does its first passes on a vision model running on this PC's GPU, for free, and Azure only has the final word (Truman's call: the local model for first passes to save cost, Azure for the final check). On the Minecraft tea house the rain check's repeated rounds cost $4.59 of the sample's $6.01 in Azure; those rounds now run locally.

**How it works.** `tools/outdoor_check.py --repair` (autopilot's checks stage runs it):

1. The local model (Qwen3.5-9B through llama.cpp) looks at every tile of the picture where rain is drawn.
2. A tile it flags goes to Azure, and only what Azure confirms gets cut. A local false alarm would otherwise cut real rain, and no later check looks where rain is missing.
3. When the local model finds nothing more, Azure looks at every tile once (the final pass). Tiles Azure already answered as they look now cost nothing. From there the run is Azure's alone.
4. A pass is always Azure's. The log says `first passes on the local model (qwen3.5-9b)` at the start and `~$x.xx of Azure this run` at the end.

What it saves: the Azure asks in the repair rounds. A scene that is clean on the first look costs the same as before, since Azure still looks at each tile once (about $0.40). Everything else stays on Azure: the critic, the scene analysis, the feature check, the clean scan and the static check (about $0.70 a video together), and review.py's own run of the rain check, which comes from its cache. The local model caught 8 of the 16 indoor things Azure caught on the labeled test cases, so it never decides anything alone.

**Setup** (once per machine, about 7 GB, all in `cache/`, which git ignores). From the repo root:

```powershell
# llama.cpp (MIT), build b11827, CUDA 13.4: the server that runs the model on the GPU
New-Item -ItemType Directory -Force cache\llama.cpp\_zip | Out-Null
gh release download b11827 --repo ggml-org/llama.cpp --pattern "llama-b11827-bin-win-cuda-13.4-x64.zip" --pattern "cudart-llama-bin-win-cuda-13.4-x64.zip" --dir cache\llama.cpp\_zip
Get-FileHash cache\llama.cpp\_zip\*.zip       # must match GitHub's digests, below, before you unpack
Expand-Archive cache\llama.cpp\_zip\llama-b11827-bin-win-cuda-13.4-x64.zip cache\llama.cpp\b11827 -Force
Expand-Archive cache\llama.cpp\_zip\cudart-llama-bin-win-cuda-13.4-x64.zip cache\llama.cpp\b11827 -Force
Remove-Item cache\llama.cpp\_zip -Recurse      # llama-server.exe is now in cache\llama.cpp\b11827

# Qwen3.5-9B (Apache-2.0), 4-bit, and its vision projector (unsloth's GGUF of Qwen's model)
New-Item -ItemType Directory -Force cache\llm\qwen3.5-9b | Out-Null
curl.exe -L --fail -o cache\llm\qwen3.5-9b\Qwen3.5-9B-Q4_K_M.gguf https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf
curl.exe -L --fail -o cache\llm\qwen3.5-9b\mmproj-F16.gguf https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/mmproj-F16.gguf
Get-FileHash cache\llm\qwen3.5-9b\*.gguf
```

The zips' hashes must be GitHub's digests for the release: `5D54C5FA2F26D9C80FA7439692E5929E8F7F1E7B2D00E3D6AB5A919154C768FA` (llama-b11827-bin-win-cuda-13.4-x64.zip) and `738F8C251AC22B70C3AE6F83A10CF222725DF0395246A2CF58F32BDB85FBE668` (cudart-llama-bin-win-cuda-13.4-x64.zip). The model's must be `03B74727A860A56338E042C4420BB3F04B2FEC5734175F4CB9FA853DAF52B7E8` (Qwen3.5-9B-Q4_K_M.gguf, 5.68 GB) and `F70DC3509053962B0D0D3EE8A7EACEBF5D60AA560CAD78254AE8698516AE029F` (mmproj-F16.gguf, 0.92 GB); the server won't start on other files (`sha256` in config/local_vision.json, Hugging Face's own hashes). Only for comparisons, the older Qwen3-VL 8B goes in `cache\llm\qwen3-vl-8b` from Qwen/Qwen3-VL-8B-Instruct-GGUF (`Qwen3VL-8B-Instruct-Q4_K_M.gguf`, `mmproj-Qwen3VL-8B-Instruct-F16.gguf`).

The server listens on 127.0.0.1 only, takes requests with its key only (`out\local_vision\server.key`, made on first use, never committed) and answers browsers from localhost pages only, so a website open while a check runs can't use the model (security review 2026-10-26).

**Check it works** (with nothing else on the GPU):

```powershell
.venv\Scripts\python tools\local_vision.py ask out\plates\<plate>\outdoor_check\tile_00_tint.jpg "What lies under the magenta?"
.venv\Scripts\python tools\local_vision.py status
```

`ask` starts the server (it loads in about 5 s and holds about 8.5 GB of the card's 12), answers and stops it again. `status` says whether a server is running and which checks use it.

**Day to day** there is nothing to do. The rain check starts the server when it needs it, stops it while SAM traces a cut (both need the GPU) and stops it at the end. Keep renders off the GPU while autopilot's checks stage runs. To run one check on Azure alone: `outdoor_check.py <scene> --repair --first-pass off`. To turn the first passes off everywhere: take `"outdoor_check"` out of `first_pass` in [config/local_vision.json](../config/local_vision.json). Without the files above (the laptop, a fresh clone) the check runs on Azure and says so.

**Trying another model:** add it to `models` in config/local_vision.json, then `.venv\Scripts\python tools\local_vision.py --model <name> compare`. That runs the rain check's own prompt on 43 cases with known answers, at no Azure cost, and writes `out/local_vision/compare_<name>.md`. On 2026-10-22: Qwen3.5-9B caught 8 of 16 indoor things and was right on 24 of 27 outside ones, at 6.7 s an ask; Qwen3-VL 8B caught 1 of 16; Qwen3.5-9B with thinking took 72 s an ask; Azure takes 24 s and about $0.028 an ask. Make a model `active` only after it measures at least as well.

**WSL (laptop):** use the Linux CUDA build of the same llama.cpp release and set `server.exe` in config/local_vision.json to its `llama-server`.
