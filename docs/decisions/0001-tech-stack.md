# ADR 0001 — Tech stack: renderer, capture, encode, assembly

- **Status:** **Accepted** 2026-10-15 at CP1: the user approved the agent's recommendations. Master codec: HEVC via NVENC (H.264 stays available as a flag).
- **Deciders:** user (approval), agent (recommendation)

## Context

We need to turn *scene config + seed* into a 10-hour, 3840×2160, 30 fps SDR video with a blocky voxel look (warm practical lights, bloom, soft shadows, AO, haze), deterministically, on a native-Windows desktop with an RTX 4070 SUPER. Requirements and constraints are in [GOALS.md](../GOALS.md); the "pure frame function" (`frame = render(scene, seed, timeline, frameIndex)`) is the architectural core.

## Environment (measured 2026-10-15)

| | |
|---|---|
| OS | Windows 11 Pro 10.0.26200 |
| CPU / RAM | AMD Ryzen 7 7700X (8C/16T) / 31 GB |
| GPU | RTX 4070 SUPER 12 GB, driver 617.42 |
| Disk | C: ~1 TB free (only drive) |
| Tools | Node 24.20.0, Python 3.12.7, ffmpeg 9.0.2 (gyan.dev full, NVENC h264/hevc/av1), Godot 4.7.2, Electron 44.7.2, three r186, Playwright 1.64.1 |
| NVENC 4K30 test encode | hevc 108 fps, av1 108 fps, h264 72 fps (synthetic source; the encoder is not the bottleneck) |

## Options evaluated

Same benchmark scene in both engines, built from one shared seeded JSON and original 16×16 textures (`spikes/shared/`): a corner of a room built from pixel-textured blocks, 1,400 chunky rain streaks past a window with drops on its glass, a glowing lamp with bloom, a turning ceiling fan, and a box-shaped stand-in pet that blends between lying and sitting. Every motion is periodic in a 10 s loop.

1. **three.js (WebGL2) in headless Chromium via Playwright** — frames leave the page over a WebSocket.
2. **three.js in Electron (hidden window)** — same page and code; the renderer process has Node, so frames go straight into ffmpeg's stdin.
3. **Godot 4.7 Forward+ (Vulkan)** — scene built from the same JSON in GDScript, with frame-index time. The viewport is read back after each draw (the same capture Movie Maker does internally) and piped to ffmpeg via `OS.execute_with_pipe`. Movie Maker's own writers were rejected: AVI/MJPEG has a 4 GB cap, PNG is too slow, OGV is editor-only, and there's no ffmpeg pipe.

Remotion was not spiked: its fast shared-memory capture excludes Windows (it falls back to screenshots), so it can't beat option 2 here. (Its license is free for individuals.)

## Results (4K, 300 frames = 10 s)

| | three + headless Chrome | **three + Electron** | Godot 4.7 |
|---|---|---|---|
| GPU actually used | ✅ ANGLE D3D11 on RTX 4070 SUPER | ✅ same | ✅ Vulkan on RTX 4070 SUPER |
| Render only (all effects) | ~60–75 fps (13–16 ms) | same | ~234 fps |
| Render + readback + **NVENC encode**, sustained | **~13 fps** (WebSocket out of the sandbox: ~72 ms per 12 MB frame) | **~45–54 fps** | ~37 fps (CPU readback + CPU RGB→YUV) |
| Determinism (same frames twice) | — | 299–300 of 300 bit-identical; a rare 1-pixel ±1 LSB GPU rounding tie (1 px of 8.3 M, luma only) | 300/300 bit-identical |
| Random access (cold start at frame 150 vs sequential) | — | 30/30 identical | 30/30 identical |
| Loop wrap (frames 300–309 = 0–9) | — | 10/10 | 10/10 |
| Seam step MSE ÷ normal step MSE | — | 0.96 | 0.96 |
| With real-time GI (Godot SDFGI) | n/a | n/a | ❌ 0/300 identical across runs, random access broken, seam ratio 1.28 (GI converges over time) |
| Encoded size, HEVC NVENC CQ19 | — | ~10 Mbps → **~42 GB / 10 h** | ~38 GB / 10 h |
| Unattended | headless | hidden window | needs a real window (`--headless` disables rendering) |
| Authoring | JS, same language as all tooling; browser preview | same | GDScript (a type-inference parse error silently leaves an idle window); Godot editor available for inspection |

Sample frames: `out/phase0/compare_three_vs_godot.png`, `out/phase0/contact_three.png`, `out/phase0/contact_godot.png`. The look is effectively a tie at spike level: both produce the warm voxel room with bloom, AO, and soft shadows, and the differences are lighting tuning.

Projected time per 10 h video (1,080,000 frames):

| Strategy | three + Electron (45–54 fps) | Godot (37 fps; ~45 with GPU YUV) |
|---|---|---|
| **B. Full timeline**, rendered in resumable segments | **~5.5–6.7 h** (overnight) | ~6.7–8 h |
| **A. Clip graph** (e.g., 60 s base loop + ~40 variant/transition clips of ~10 s ≈ 14k frames, then `ffmpeg` concat with stream copy) | ~5 min render + ~10 min stitch | similar |

## Decision (recommended)

1. **Renderer: three.js (r186, WebGL2) inside Electron**, in a hidden window, with Node integration available only to our own local page. three's addons supply GTAO, UnrealBloom, AgX tone mapping, and fog.
2. **Capture: GPU-side output pipeline** — tone-mapped float buffer → vignette → BT.709 limited-range **YUV 4:2:0 packing in a shader, with TPDF dither before 8-bit quantization** (anti-banding) → async PBO readback (12.4 MB/frame) → ffmpeg stdin.
3. **Encode: HEVC via NVENC** (`-preset p5 -tune hq -rc vbr -cq ~19`, BT.709 tags, `hvc1`). YouTube accepts HEVC. At ~40 GB per 10 h there's room to raise quality. A 10-bit master is a later A/B test (P010 packing uses the same shader trick).
4. **Assembly: B (full timeline) as the default.** Render in resumable segments (e.g., 5 min each, so a crash or Windows Update restart loses at most one segment), then concatenate with stream copy. This keeps independent element timelines and slow evolution cheap, and fits overnight. Clip-graph tricks (A) stay available for fast previews.
5. **Determinism rules** learned in the spike, enforced in the engine:
   - Seed `Math.random` (three's GTAO builds its noise texture with it).
   - Give transparent/instanced objects an explicit `renderOrder`, and turn off frustum culling for animated `InstancedMesh`es. three lazily computes their bounds on the first rendered frame, which otherwise makes output depend on the start frame.
   - No temporal effects (TAA, accumulated GI) unless they are a pure function of the frame index.
   - QA compares hashes and, on mismatch, falls back to a tolerance check (≤ 1 LSB on ≤ 0.001% of pixels), so a sporadic GPU rounding tie isn't reported as a failure.

### Why not Godot

Its raw render speed and built-in lighting are excellent, but its best look feature (SDFGI) is temporal and breaks determinism, seams, and random access. Without it, the look is on par with three. It also needs a visible window, can't pipe frames out of Movie Maker, and splits the codebase across GDScript and Node. **It stays the fallback** if three can't reach the look we want; the spike in `spikes/godot/` makes that cheap to re-evaluate.

## Proposed repo layout & CLI (built in Phase 2)

```text
package.json            # one Node project at the root (three, electron); npm scripts below
src/
  render/               # Electron main, render page, GPU YUV pass, ffmpeg sink, segment manager
  engine/               # scene → three.js: voxel/box meshing, materials, lights, post, determinism guards
  library/              # reusable props, creatures, effects (rain, drops, fan, fire…), texture generators
  timeline/             # seeded scheduler → timeline.json (states, rare events, cooldowns)
  audio/                # ambience bed, event-synced SFX, music slot, loudness (ffmpeg ebur128)
  qa/                   # seam, determinism, loudness, size checks → QA report
scenes/<name>/scene.mjs # scene config (layout, palette, lights, weather, creature, events, audio) + default seed
spikes/                 # Phase 0 spikes, kept for reference (three + Godot)
out/<scene>/            # gitignored: stills, previews, segments, masters, reports
```

| Command | Does |
|---|---|
| `npm run still -- scenes/<name> --frame 1234` | One 4K PNG |
| `npm run contact -- scenes/<name>` | Contact sheet across the loop/timeline |
| `npm run preview -- scenes/<name> --seconds 10` | Short clip |
| `npm run render -- scenes/<name> --duration 10h --seed 42` | Segmented, resumable, background-friendly render with progress/ETA → master + timeline + stems |
| `npm run qa -- out/<name>` | Seam/determinism/loudness/size report |

## Consequences

- One language (JS/Node) for scenes, renderer, scheduler, audio tooling, and QA; scenes are previewable live in a browser.
- Bounce light must be authored, not simulated: hemisphere/fill lights, shadow intensity, per-vertex voxel AO, emissive "bounce cards", and optionally code-baked lightmaps. This is the main art risk and gets attention in Phase 1.
- The Electron renderer runs with Node integration and loads only our local server; never point it at remote content.
- `electron.exe` is a GUI-subsystem binary. Always launch it from Node (`spawn`/`spawnSync`) so callers wait for it and capture its output.
- Godot stays installed but unused unless we revisit this ADR.
