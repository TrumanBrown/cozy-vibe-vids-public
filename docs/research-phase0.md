# Phase 0 research — found / will use / rejected

_2026-10-15. Licenses checked at the source on that date; re-check before relying on them._

## Will use

| What | Why |
|---|---|
| **three.js r186** (MIT) — core + addons: `GTAOPass`, `UnrealBloomPass`, `OutputPass`, AgX tone mapping, `FogExp2`, `VOXLoader` (if we ever import `.vox`) | Maintained, everything we need in one dependency; see [ADR 0001](decisions/0001-tech-stack.md) |
| **Electron 44** (MIT) | Same Chromium/WebGL on the real GPU, with Node in the renderer → frames go straight into ffmpeg (~4× faster than headless Chrome) |
| **ffmpeg 9 (gyan.dev full build)** with NVENC | HEVC/AV1/H.264 hardware encode at 4K well above 30 fps |
| **Own GPU YUV/dither pass** | No library does "float → BT.709 YUV420 + TPDF dither → raw bytes" for us; it's ~60 lines of GLSL |
| **Own greedy/box meshing** | No maintained JS greedy-mesher package; the algorithm is ~100 lines (references: `mikolalysenko/greedy-mesher`, `maxogden/voxel`, MIT) |
| **CC0 sound sources:** Freesound (filter `license:"Creative Commons 0"` only), Kenney.nl | Rain, thunder, fire, room tone — verify and ledger each file |
| **CC0 texture/model sources (only if needed):** ambientCG, Poly Haven, Kenney | Our textures are code-generated; these are fallbacks |

## Maybe later

| What | Note |
|---|---|
| pmndrs `postprocessing` (Zlib) | Merged effect chains if the three addons get slow or limiting |
| N8AO | Nicer AO; license metadata is inconsistent (CC0 repo vs ISC package) — confirm first |
| OpenGameArt | Mixed licenses; CC0 filter `field_art_licenses_tid[]=4`, verify per asset |
| Godot 4.7 + `Coding-Solo/godot-mcp` | Only if we revisit the renderer decision |
| 10-bit HEVC master | A/B for banding after YouTube's re-encode |

## Rejected

| What | Why |
|---|---|
| Headless Chrome + Playwright capture | Works on the GPU, but frames can't leave the sandbox faster than ~13 fps at 4K |
| `page.screenshot()` / CDP screencast | Slowest path; PNG/JPEG encode per frame |
| WebCodecs in-page encode | Reported ~25 fps at 4K; less control over quality than ffmpeg's NVENC |
| Remotion | Its fast capture path excludes Windows; we don't need its React timeline |
| Godot Movie Maker | No headless rendering, AVI 4 GB cap, no ffmpeg pipe; SDFGI breaks determinism (see ADR) |
| Sonniss GDC bundle | Custom royalty-free license, **not CC0** |
| BigSoundBank | Custom "free" license, **not CC0** |
| Any Minecraft/Mojang assets, C418/Lena Raine music | IP — see [REFERENCE.md](REFERENCE.md#do-not-copy-checklist) |

## Facts to remember

- **YouTube upload limit:** 256 GB or 12 h, whichever is less; uploads over 15 min need a **phone-verified account** ([source](https://support.google.com/youtube/answer/71673)). HEVC uploads are accepted.
- Agent skills / MCPs: nothing useful found for three.js or ffmpeg beyond what's above; Remotion's official agent skills only matter if we use Remotion.
