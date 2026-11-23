# Reference — "Rainy Apartment" (vibe only — never copy)

**Video:** [Rainy Apartment | Minecraft Music with Soft Rain for Sleeping & Studying (10 Hours)](https://www.youtube.com/watch?v=eFVPmqgZAi4&t=26480s) — Retrosteve. Frame captured at 7:21:20 / 10:00:00 (the link opens there).

The frame isn't in the repo: it's another creator's work, and the repo is going public (2026-10-26). It's kept on the desktop only, in `cache/reference/rainy-apartment-reference.png` (gitignored), like the other stills below.

> Internal style reference only. Never use this image as an asset, texture source, or generation input, and never publish it.

Agents can't watch YouTube, so this page describes the video. Motion notes come from the user, who watches it a lot.

## What it is

- A 3D scene — most likely built in Minecraft and rendered with a shader pack (perspective, bloom, soft shadows, warm bounce light).
- It uses Minecraft IP: the dog is the Minecraft wolf (cream body, red collar), the cardboard boxes have creeper faces, and the music is C418's Minecraft soundtrack.
- Static camera for all 10 hours.

## Composition

- Wide, locked-off shot from slightly above eye level, facing a wall of floor-to-ceiling windows; roughly one-point perspective.
- **Foreground:** bed with pillows (left); patterned rug with a sleeping dog (right).
- **Midground:** desk in front of the windows with an articulated desk lamp, very tall stacks of books, a small radio on a wooden nightstand, a desk chair with a blocky person seen from behind, cardboard boxes (right), potted plants, bedside lamp.
- **Background:** dense city skyline — tall towers with warm lit windows in vertical strips — with rain in front of it.
- **Upper frame:** ceiling fan; a row of hanging plants and flower baskets along the window line; an octagonal wooden pendulum wall clock on a pillar (left); small framed pictures (right wall).

## Light & rendering

- **Almost monochrome amber grade** — even the "cool" exterior is warm brown; there is barely any blue.
- Emissive sources (desk lamp, bedside lamp, lit book stacks, tower windows) bloom softly.
- Deep near-black-brown shadows, low overall key, soft shadows and ambient occlusion, light haze/rain fog on the skyline, mild darkening toward the edges.
- Rain is drawn as chunky diagonal pixel streaks, lit amber by the room light.

## Palette

Extracted from the frame (median cut; share of pixels):

| Hex | Role (approx.) | Share |
|---|---|---|
| `#150b02` | deepest shadow | 9% |
| `#1d1105` `#1f160c` `#281504` `#291d0f` | shadows, couch, floor edges | 29% |
| `#331c07` `#3c2811` `#411f03` `#4e2c05` `#4f391c` | low mids — skyline, floor | 35% |
| `#5f2f03` `#753c03` `#894b06` | burnt-orange mids — walls, ceiling | 22% |
| `#ce7c08` | amber highlight | 5% |
| `#f5a004` and brighter (sampled) | lit books, lamp cores | small |

Takeaway: keep this warmth, but consider a bit more color separation (e.g., a dusky blue-violet exterior) for depth — and so we don't look like a copy.

## Motion (from the user)

- Rain falls continuously; drops run down the glass now and then.
- The ceiling fan spins; the clock ticks.
- The dog sometimes sits for a while, sometimes lies down.
- Overall: short clips looped, with variations.

## Keep — the vibe

- Warm, low-key evening light against rain — the feeling of being safe indoors during a storm.
- A lived-in room: books, plants, lamps, a pet.
- Blocky voxel construction with pixel textures, but furniture that isn't literally Minecraft blocks.
- Locked camera, layered depth, small calm motions.

## Do-not-copy checklist

Run this for every scene and every new asset:

- [ ] Not this room's specific layout or prop arrangement (desk centered against the windows, bed left, rug + dog right, …).
- [ ] No Minecraft mobs or look-alikes — wolf (cream dog with red collar), creeper (incl. creeper-face prints), other mob skins — and no Steve/Alex-style player models (their proportions or skins). Creatures and characters are original designs.
- [ ] No Minecraft textures, block designs, GUI, fonts, logos, item sprites, or particles taken from the game.
- [ ] No Minecraft sound effects. Music only from the Mojang-owned allowlist ([config/minecraft_music.json](../config/minecraft_music.json)); never C418.
- [ ] No "Minecraft" or any other brand text in renders; no real brands/logos on props (books, radios, posters).

## Where we can beat it

- More variety over 10 hours (rare events, a painted pet's breathing and sighs, slow evolution) so it never feels looped. Pose changes only with a 3D or library pet (DECISIONS 2026-10-18).
- Thunder synced to lightning; layered ambience.
- Crisp 4K delivery and better color separation.
- A signature detail in every scene.

---

## Added references (2026-10-15, from the user) — vibe only, never copy

Both are 10-hour "Minecraft music + rain" videos, so the same IP caveats apply. Internal references only; never use them as assets or publish them.

### Autumn Treehouse — [video](https://www.youtube.com/watch?v=pTTNsgLJTiU) · frame: `cache/reference/autumn-treehouse-reference.png` (desktop only)

The user's favorite. What makes it work:
- **The outside is half the picture.** A huge open window shows a rich, layered exterior: two lantern-lit treehouses with glowing windows, a rope bridge between them, orange/red autumn canopies, darker trees behind, and a blue-violet storm sky with blocky clouds.
- **Strong warm/cool split:** amber interior vs. blue-violet rainy exterior, with orange foliage bridging the two.
- **Leaves come inside:** vines with autumn leaves frame the opening, and fallen leaves lie on the bed and floor.
- **Dense interior detail:** fireplace with a stone chimney, books, lanterns, a plaid quilt, a mug, and a blocky cat (read as cat-like, not a game mob).
- Fine detail: small leaf cubes, thin rain streaks, and small lights everywhere.

### Rainy Lakeside Porch — [video](https://www.youtube.com/watch?v=E00HNQDuEZk) · frame: `cache/reference/lakeside-porch-reference.png` (desktop only)

- Covered porch: fire pit, couch with cushions, wall lantern on a post, and a lit cabin window on the right.
- Exterior: a dark lake **reflecting** the lights of a lakeside village (cottages with warm windows, lamp posts), a pine-forested hillside behind with a few lit windows, and a misty grey sky.
- Overhanging pixel-leaf silhouettes frame the top corners.
- Do-not-copy: the dog is a Minecraft-wolf look-alike, so our pets stay original.

### Takeaways for our scenes
1. Give the exterior **40–50% of the frame**, built in 3–4 depth layers (near framing foliage → mid structures with lights → far forest → sky/clouds), each with its own lights.
2. **Many small light sources outside** (lanterns, windows, string lights), each with a small light pool.
3. **Fine-grained foliage** (leaf cubes ~1/4 to 1/2 block up close), saturated even at night.
4. **Bring the outside in:** vines, leaves, and rain spray on the threshold.


---

## Motion quality bar (user feedback 2026-10-15) — applies to ALL animations

The user rejected rain that moved like vectors and rain that came through the ceiling. Reference stills (desktop only, gitignored): `cache/reference/treehouse-rain-reference.png` and `cache/reference/lakeside-rain-reference.png`.

- **Physically motivated, not geometric.** Model the real thing (e.g., rain streak length = fall speed × shutter; near drops long and fast, far drops short and slow). Look up established techniques (papers, engine VFX tutorials) before inventing one.
- **Irregular and clumpy.** Real phenomena gather and thin: gust bands, curtains, bursts. Avoid uniform grids, equal spacing and constant density. Every element gets per-instance variety (size, speed, brightness, phase).
- **Depth.** Several layers at different distances with parallax; nearer = bigger, faster, brighter, sparser.
- **Light interaction.** Elements pick up the scene's light: rain glints warm near lanterns and cool against the sky; mist glows around lights.
- **Correct occlusion — never through solid geometry.** Weather only shows outdoors and behind/around foreground objects (roof, posts, railing). Use the plate's depth plus an explicit outdoor mask; verify with `tools/rain_qa.py --leak` (must be exactly zero outside the mask) and frame-difference images.
- **Calibrate against footage.** Measure reference clips with `tools/rain_analyze.py` and match the statistics (count, length, width, brightness, speed spread) within ~25% (`tools/rain_qa.py --calibrate`). Rain v3 numbers are in [DECISIONS.md](DECISIONS.md).
- **Water behaves like water.** Roof runoff is a chain of beads that accelerate and stretch as they fall (gravity + drag), pulsing with surges; not a solid line. Drips come from vine tips and roof lips at plausible places.
- **Verify like a viewer.** Watch the preview; check frame-diff images (what moves, what must not), 1:1 crops at 4K, and a side-by-side against the reference stills before presenting.
