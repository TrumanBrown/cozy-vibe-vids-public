---
name: keyart-pipeline
description: 'Generate and prepare AI key art for a cozy-vibe-vids scene. Use when: making a new scene image, regenerating key art, calling Azure gpt-image models, writing scenes/<scene>/keyart.json prompts, choosing animatable props for the image (steaming mug, fireplace or campfire, clock, candle, wind chime), upscaling a key-art image to a 4K plate, estimating depth, editing motion/outdoor masks, placing rain runoff sources, or running rain leak/seam QA.'
argument-hint: 'scene name (e.g. treetop) and what to change'
---

# Key-art pipeline (Azure gpt-image → 4K plate → animation)

## When to use
- A scene needs new or revised key art (the hero still the video is built on).
- Turning a key-art image into an animatable plate (upscale, depth, masks).
- For a whole new video, `tools/new_video.py` (new-video skill) builds the prompt from [config/aesthetics.json](../../../config/aesthetics.json) and a brief, generates candidates, scores them, preps the plate and analyzes it. The rules below still apply to its prompts.

## Art direction (read first)

Truman's bar since 2026-10-25: key art must look like an illustrator spent days on it, never like AI slop (L135). [references/art-direction.md](references/art-direction.md) has his references analyzed and measured, what made the rejected bus stop read as AI, how to write a prompt that moves the image model off its stock look, the approved styles (`ink-gouache`, `brushwork-night`), the channel's own cast ([config/cast.json](../../../config/cast.json): Pacific Northwest creatures with a silly, animatable touch) and the test rounds.

## Prerequisites
- `az login` into the subscription in [config/azure.json](../../../config/azure.json). Auth is keyless (Entra ID); there are no API keys.
- Python venv with [requirements.txt](../../../requirements.txt) (see [docs/SETUP.md](../../../docs/SETUP.md)).
- If the resource group was deleted: `.venv\Scripts\python tools\azure_provision.py` (idempotent).

## Procedure
1. **Write prompts** in `scenes/<scene>/keyart.json`: 16:9 (`2560x1440`), locked-off eye-level camera, explicit foreground/midground/background, the light sources, and "no people, no text, no user interface". Leave clear areas for animated layers (sky, water, foliage edges, lanterns, a pet). **Ask for 1–2 extra animatable props** besides the pet (user, 2026-10-16); see [Animatable props](#animatable-props).
2. **Generate:** `.venv\Scripts\python tools\keyart.py scenes\<scene>\keyart.json --only <id>`. The default deployment is `gpt-image-2-5-sunburst` (~30 s each); it keeps its own polished house style whatever the prompt says about the medium. `gpt-image-2` (~85 s, about $0.29 an image, ~4× the tokens) follows a hand-made medium (ink, gouache, paper grain): a look's `keyart_model` picks it (the hand-made looks do, 2026-10-25), or pass `--model gpt-image-2`. Outputs plus prompt sidecars go to `assets/keyart/<scene>/`.
3. **Review** each candidate yourself (view it) and pick the hero. When he asks for changes to a candidate he likes (a character moved, a light farther away, a subject a touch more distinct), revise it before the plate: `tools/keyart_revise.py <scene> --src <png> --tag <name> [--lift "x,y"] [--edit "<polygon>" --keep "x,y" --prompt "..."] [--dry]` (masked edits with the look's model, composited back only inside the mask; `--lift` raises a subject's value and contrast in code). Move a subject in two edits: paint it out, then paint it in with a mask over the new spot only (lessons L139).
4. **Prepare the plate:** `.venv\Scripts\python tools\plate_prep.py <hero.png> --name <plate> --sr-from 0`. Use `--sr-from 0` for gpt-image output (≥2560 px, so Lanczos is best). For small inputs, omit it to use tiled Swin2SR. This writes `out/plates/<plate>/`: `plate_raw.png` (4K upscale), `plate.png` (painted-in rain streaks removed: static streaks look frozen under animated rain), `depth.png`/`depth8.png` (Depth Anything V2 at 1036 px with a flip pass), `masks.png` (R sky, G water, B foliage), `lights.png` (R lights, G **outdoors**, B light glow), `plate.json` (env colors, drip/stream candidates), `preview_masks.png` and `edges_preview.png`. Re-run with `--masks-only` (reuse depth) or `--redepth` (reuse the upscale).
5. **Outdoors mask (where weather exists):** it is `disparity < outdoor_disp`, edge-snapped with a guided filter. Pick `outdoor_disp` from the disparity histogram so every porch object (roof, posts, railing, pets, vines) is above it; Treetop uses 0.105. Then clip it with an `only_outdoor` rectangle around the opening. **Never hand-paint outdoors over solid objects:** that caused rain on the cat and ceiling. Other polygons go in `assets/keyart/<plate>.masks.json` (normalized x,y with y down; keys `only_<ch>`, `<ch>`, `not_<ch>` for channels sky, water, foliage, lights, outdoor; `not_derain` protects waterfalls and similar from de-rain; `qa_regions` holds boxes that must stay dry). Check `preview_masks.png`.
6. **Scene module:** `scenes/<scene>/scene.js` calls `plateLayer(ctx, { plate, pet: {cx, cy, rx, ry, base}, mist, ... })` from `src/library/plate.js` and `rainLayer(ctx, { plate, count, depth, runoff: [...] })` from `src/library/rain.js`. Find the pet's coordinates by cropping the plate. Put roof streams in open columns under a roof edge (see `edges_preview.png`), and drips at vine ends.
7. **Verify:** `.venv\Scripts\python tools\rain_qa.py scenes/<scene> --plate <plate> --leak --seam` (zero rain outside outdoors and in `qa_regions`; loop end identical to frame 0; deterministic). Leak QA can't see rain that is *missing*: also check the outdoor mask at 1:1 over every see-through gap (railings, fences, window bars). Depth fills thin near gaps with near depth; add `outdoor` polygons (plate-scene checklist "See-through gaps"). Add `--calibrate docs/reference/treehouse-rain-stats.json` (or stats from other footage via `tools/rain_analyze.py`) to compare streak statistics with reference footage. Then run `node src/cli.mjs preview scenes/<scene> --seconds 10` and watch it.

## Animatable props

User guidance (2026-10-16): every key art gets **a prop or two the code can animate**, besides the pet. Treetop has only the cat. Pick props that suit the setting, place them on the near interior (dry, well lit, unoccluded, in focus), and describe them in the prompt so they come out clean and separable.

| Prop | Prompt wording | Animation (pure function of time, integer cycles per loop) | Notes |
|---|---|---|---|
| Steaming mug on a small table | "a steaming mug of cocoa on a low wooden table near the camera, Minecraft-style blocky mug, dark background behind the mug" | a faint haze from the whole surface of the drink (the simulated plume, scaled to the mug: tools/steam_sim.py), rising and fading within about a mug width, lit by the room; never a few separate wisps | keep a dark, plain area above the mug for the steam to read against, and the rim visible so plate_prep can fit the opening |
| Fireplace or campfire | "a stone fireplace with a crackling fire, flames clearly visible" (blocky Minecraft fire, or a real-looking fire for other styles) | flame sprites or noise-driven flame shader, embers rising, warm flicker lighting the room (reuse the lights mask); crackle and pop audio grains | the strongest anchor for a cozy video; flicker must stay soft (WCAG) |
| Clock | "a wall clock with a visible face and hands" (or a Minecraft clock item on the wall) | hands that turn (second hand ticking or smooth), optional pendulum swing; a tick in the audio | the minute hand can show real elapsed time across the 10 h (GOALS slow evolution) |
| Candle or oil lamp | "a lit candle on the windowsill" | flame sway and flicker, a wax glint | small; pair it with a bigger prop |
| Hanging plant or wind chime | "a hanging plant / wind chime by the open window" | sway with the scene's wind and gusts (the same wind object as the rain and leaves) | wind chimes add a gentle audio event |
| Book with turning pages, curtain | "an open book on the table", "a light curtain at the window" | a page turns now and then; a curtain billows in gusts | both are rare events, not loops |

Mention the props in the scene's DECISIONS entry and give each one an event or loop in the timeline (ambient-events skill). The plate-scene skill's "what to vary per scene" table counts them as a scene's signature motion.

## Rules
- Log every key-art image used in a video in [docs/asset-ledger.csv](../../../docs/asset-ledger.csv) (model, date, sidecar path).
- Keep generation counts small (a few candidates per scene); it costs Azure credits.
- Never commit API keys; none are needed. Never touch Azure resources outside `rg-cozyvibevids-img`.
