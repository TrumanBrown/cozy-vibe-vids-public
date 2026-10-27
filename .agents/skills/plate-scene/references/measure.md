# Measuring a plate

Everything below uses normalized plate coords (x, y in 0..1, y down): 0.01 in x = 38.4 px and 0.01 in y = 21.6 px at 4K. The whole 4K plate is downscaled when you view it, so read coordinates only from gridded crops. Write measurement images to `out/<scene>/measure/` (gitignored) and view them yourself. Checks that render (stills, `rain_qa.py`) need the scene module: create `scenes/<scene>/scene.js` from the template early with rough values and refine it as you measure.

```powershell
$m = '.agents\skills\plate-scene\scripts\plate_measure.py'                 # Python: .venv\Scripts\python $m <cmd> ...
$lc = '.agents/skills/plate-scene/scripts/lake_camera.mjs'                 # Node:   node $lc <cmd> ...
```

| Command | Use |
|---|---|
| `plate_measure.py grid <image> --box x0,y0,x1,y1 [--step 0.01] [--zoom 2] --out <png>` | labeled coordinate grid on a crop (nearest-neighbour zoom, so block edges stay sharp); prints one grid step in 4K px |
| `plate_measure.py disp <plate> [--box ...] [--thr 0.105 --out <png>]` | disparity histogram and percentiles, percentiles inside every `qa_regions` box, optional outdoors preview |
| `plate_measure.py rows <plate> [--box ...] [--step 0.01]` | median water-mask disparity per row band; flags drops and jumps |
| `plate_measure.py cands <plate>` | runoff candidates, light groups and foliage palette from `plate.json`, normalized |
| `plate_measure.py diff <a.png> <b.png> --out <png> [--gain 8] [--box ...]` | what changed between two stills, with the largest changed regions |
| `lake_camera.mjs fit --rows y:px y:px ...` | camera height and horizon from shore-block widths |
| `lake_camera.mjs pts --horizon h --height m --pts x,y x,y ...` | water-plane positions, distances, px per meter |
| `lake_camera.mjs route scenes/<scene> [--dur s]` | the scene's boat route: length, scale, fades, haze and speed along a trip |

`lake_camera.mjs` imports `src/library/boat.js`, so its numbers are exactly what the renderer and the audio profile use.

## 1. outdoor_disp and the opening

1. `plate_measure.py disp <plate> --box <opening>` with a box around the opening. The far world piles up at low disparity; porch geometry sits higher.
2. Put rough `qa_regions` boxes on every solid thing near the opening (pet, ceiling, hanging lanterns, posts, deck, interior wall) and run `disp` again: it prints p0.5/p1/p5/p50 inside each box.
3. Choose `outdoor_disp` below the lowest p0.5 of the solid boxes and above most of the far world. Treetop: solids ≥ 0.151, chosen 0.105. Preview it: `disp <plate> --thr 0.105 --out out\<scene>\measure\thr.png` (raw threshold, magenta = outdoors).
4. Write `outdoor_disp`, `only_outdoor` (box around the opening) and `qa_regions` into `assets/keyart/<plate>.masks.json`, run `tools/plate_prep.py <hero.png> --name <plate> --masks-only`, check `preview_masks.png`, then `rain_qa.py scenes/<scene> --plate <plate> --leak` must print exactly 0 outside the mask and in every region.
5. A solid object with a far-looking disparity (thin vines, glass, a dark post): cut it out with `not_outdoor` and give it a `qa_regions` box. Never paint `outdoor` polygons over solid objects; that is how rain once fell on the cat and through the ceiling. Trace the object's own outline, not a box around it: a box around the ramen stool swallowed the wet street between its legs (2026-10-19); `tools/weather_audit.py` reports such dry pockets.

## 2. Water polygons

1. Grid the water at step 0.005 (`grid ... --step 0.005 --zoom 3`, several crops along the shore) and trace the shoreline as `[x, y]` vertices. Water seen through gaps in a railing is its own polygon. Leave islands, stones and shore foliage outside.
2. `--masks-only`, then check `preview_masks.png` (cyan).
3. `plate_measure.py rows <plate> --box <water area>`: on one flat water surface, disparity rises smoothly with y. A drop or a jump points at shore, an island, a reflection the depth model read as an object, or a second stretch of water (Treetop's rail-gap water shows as a drop at y 0.655, which is expected).
4. Once the scene renders, look at what moves: `node src/cli.mjs still scenes/<scene> --frames 0,15 --params rain=off --out out\<scene>\measure --name wd`, then `plate_measure.py diff out\<scene>\measure\wd_4k_f000000.png out\<scene>\measure\wd_4k_f000015.png --out out\<scene>\measure\diff.png --box <water area>`. Ripples must stay on the water (foliage sway and mist also move; shore stones must not).
5. Changing the water mask re-derives the light groups: re-check `lights_preview.png` (windows whose reflection falls on the water are never switched off).

## 3. Runoff lips and drips

1. `plate_measure.py cands <plate>` lists `tip` (lowest points of hanging leaves and vines: drip spots), `eave` (flat edges: streams) and `top` (columns open to the frame top: a roof edge just above the frame, so use y < 0, e.g. -0.02). `edges_preview.png` shows them on the plate.
2. A stream needs an open sky column from the lip down to the bottom of the opening. Check with a tall crop: `grid ... --box <x-0.02>,0,<x+0.02>,0.9`. Treetop's pours are at x 0.252 and 0.312 (roof edge above the frame) and one visible lip at (0.571, 0.026) between two vines.
3. Drips go at vine ends: the `tip` y is the outdoors' top edge, so read the real vine end off a crop.
4. Check placement alone: `node src/cli.mjs still scenes/<scene> --frames 0,900 --params only=runoff,debug=rain` (white coverage of the runoff only, plate black). Then watch a 10 s preview.
5. `z` (m) only sets bead size and fall speed in px: keep the lips at Treetop-like 2.3–3.4 m and judge the look against footage.

## 4. Pet ellipse and rig

1. `grid out\plates\<plate>\plate.png --box <pet box> --step 0.005 --zoom 3`.
2. `pet: { cx, cy, rx, ry, base }`: body center, radii (the breath fades out between 0.55 and 1.0 of them) and `base` = the row of the pet's bottom (the stretch is anchored there).
3. Each ear: `pivot` at the ear's base, `center` in the middle of the ear, `radius` [rx, ry] about half the ear's size (the warp fades between 0.75 and 1.25 radius), `angle` 0.15–0.25 rad (a flick peaks at up to ~1.25× angle).
4. Tail: `base` and `tip` along the visible tail end (the lift grows from 25 % to 100 % of the way), `halfWidth` ≈ half the tail's thickness, `lift` ≈ 0.002–0.003 (4–6 px at 4K).
5. Verify: list motions with `node -e "const tl=require('./out/<scene>/timeline.json'); console.log(tl.pet.slice(0,8).map(e=>e.type+' t='+e.t+' frame='+Math.round(e.t*30)).join('\n'))"`, render stills at the frame before and ~3 frames into an ear flick (peak 0.08–0.14 s) or ~7 frames into a tail twitch, and `diff` them: only the ear or tail may change. Fur must stay intact (no smearing at the warp edge).

## 5. Lake camera and boat route

Only for calm water seen from above whose far end disappears into mist. The boat is drawn through a pinhole camera that must match the plate: shared `focalPx` 2700 (as rain and leaves), plus `horizon` and `height`.

1. Find voxel blocks at the water level at two or more rows far apart (shore stones, dock planks, reeds). On fine crops (`--step 0.0025 --zoom 4`) measure the width in 4K px of one block face that faces the camera. Use widths, not heights: horizontal size on the water plane is exactly `focalPx / depth` px per meter.
2. `node $lc fit --rows 0.56:14.4 0.64:25.2` (row y : block px) prints `camera: { focalPx, horizon, height }`. The model is width = cos(pitch) × (row px − horizon px) / height, so the horizon is where block widths shrink to zero.
3. Sanity-check: the horizon row should sit at or just above the farthest visible water, and the height should be plausible for the viewpoint (Treetop: horizon 0.453, height 16 m). `node $lc pts --horizon 0.453 --height 16 --pts 0.30,0.70 0.31,0.70` must put two points one block apart about 1 m apart.
4. Trace `path` points on the water, far end first: start inside the mist and end where solid foreground (outdoor mask 0) hides the water. Depth from `depth.png` is too coarse to hide the boat behind foliage, so don't end a route behind trees.
5. `node $lc route scenes/<scene>`: Treetop's route is ~208 m; the 4.5 m boat is ~40 px long in the mist and ~150 px at the near end; trips run 1.1–1.8 m/s; the hull haze (a smoothstep over 95–260 m camera depth by default) keeps the far part of each trip a lantern glow in the mist. Every point must be below the horizon.
6. Watch it: `node src/cli.mjs preview scenes/<scene> --event boat:0 --seconds 160 --audio off --out out\<scene>\boat0.mp4`, plus stills at a few frames of the trip and a `--params debug=rain` still (the boat must vanish behind the railing, not draw over it).

## 6. Light groups and leaves

- `plate_measure.py cands <plate>` lists the light groups. Lantern events need at least one `lantern` group (bright warm compact cores on near geometry, not outdoors); night lights need non-reflective `window` groups. Plate.js only switches ids 1–63.
- Leaves take colors from `foliage_palette` (6 k-means colors of the near foliage, dark to bright): `events.leaves.palette: [first, last]` picks the range (Treetop [2, 5]). The palette comes from the foliage mask, so green or sparse foliage needs `foliage` polygons first.
- `events.leaves.x`: the columns under the canopy that overhangs the opening (Treetop 0.03–0.83).
