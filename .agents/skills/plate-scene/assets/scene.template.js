// TEMPLATE: a plate scene (plate-scene skill). Copy to scenes/<scene>/scene.js, then replace every <PLACEHOLDER>
// and re-measure or re-tune every value marked MEASURE or TUNE. Derived from scenes/treetop-plate/scene.js (Treetop;
// its rain, runoff and lightning were approved by the user on 2026-10-15). The numbers left in place are Treetop's,
// as working examples; the event rates are Treetop's timeline v5 (2026-10-16: far more often, alive but calm
// enough to study to).
//
// Flow: AI key art (keyart-pipeline skill) -> tools/plate_prep.py -> out/plates/<plate>/ (hand masks in
// assets/keyart/<plate>.masks.json) -> this module (src/library/plate.js, rain.js, leaves.js, boat.js) -> seeded
// timeline (src/library/timeline/ buildTimeline reads `events`) -> tools/audio.py (reads the timeline JSON from
// `node src/cli.mjs timeline`, which also carries `weather` and `audio` below) -> `node src/cli.mjs render`.
//
// Coordinates are normalized plate coords: x, y in 0..1, y down. Sizes "in px" mean 3840x2160 plate px.
// Keep fps and loopSeconds as plain numeric literals inside the default export: tools/rain_qa.py reads them with
// a regex (so never write those two keys followed by a number in a comment above them), and the integer-cycle
// rates inside plate.js and rain.js (sway, ripples, flicker, breathing, runoff surges) were tuned for a 120 s loop.
//
// QA params (ctx.params, from --params k=v,...): debug=rain (coverage only, for rain_qa --leak), only=runoff|falling,
// rain=off (rain_qa --profile), events=off (handled by the engine: no timeline; rain_qa --seam), rain.<opt>=<v>.
import { plateLayer } from '../../src/library/plate.js';
import { rainLayer } from '../../src/library/rain.js';
import { leavesLayer } from '../../src/library/leaves.js';
import { boatLayer } from '../../src/library/boat.js';
import { fishLayer } from '../../src/library/fish.js';
import { heronLayer } from '../../src/library/heron.js';

const PLATE = '<plate>';   // out/plates/<plate>/ from `tools/plate_prep.py <image> --name <plate>`

// Wind (m/s), one object shared by falling rain, runoff, leaves (events.leaves.wind + leavesLayer) and the audio
// (gust whoosh, rain swells, creaks via the timeline JSON). mean: steady drift (+ = to the right); gust: gust
// amplitude; gustCycles: gusts per loop (integer; 5 per 120 s = one gust every 24 s); fronts: gust fronts across
// the frame width (gusts sweep sideways); turb: per-drop turbulence (falling rain only). TUNE.
const wind = { mean: 0.05, gust: 0.5, gustCycles: 5, fronts: 0.6, turb: 0.75 };

// Roof runoff and drips (rain.js runoffParams; tools/audio.py hears every source with rate >= 10 as a stream and
// syncs its splashes to the same flow). MEASURE each lip on out/plates/<plate>/edges_preview.png and a gridded crop
// (plate-scene skill): streams must fall through open sky columns, never behind vines, posts or a lantern.
// ORDER MATTERS: each source's flow pattern is seeded by its index, so append new sources at the end.
//   x, y        lip position (y < 0 = a roof edge just above the frame)
//   z           lip distance from the camera (m, default 3.2): sets bead size and fall speed in px
//   d           bead diameter (mm, default 4)
//   rate        bead releases per second at full flow (rounded to whole beads per loop): >= 10 = a stream,
//               ~0.5-2.5 = a drip (default 20)
//   flow        mean flow 0..1 (0.8); burst: surge amplitude (0.2); burstCycles: slow swells per loop (integer, 3)
//   neck        unbroken column under a visible lip (m, default 0 = none)
//   spread      sideways scatter (m per m fallen, 0.02)
//   gain        opacity (1); warm: lantern light it catches (1.5); bright: brightness (1)
//   wobble      sway of the release point (m; default 0.006 for streams, 0 for drips)
const runoff = [
  // A strong pour from a roof edge just above the frame (open sky column down to the railing). MEASURE
  { x: 0.312, y: -0.03, z: 3.4, d: 5.0, rate: 46, flow: 0.65, burst: 0.3, burstCycles: 3, spread: 0.012, warm: 0.6, bright: 1.5 },
  // A visible lip with a short unbroken neck, lit by a nearby lantern. MEASURE
  { x: 0.571, y: 0.026, z: 3.3, d: 4.6, rate: 36, flow: 0.62, burst: 0.3, burstCycles: 5, neck: 0.05, spread: 0.015, warm: 2.0, bright: 1.3 },
  // Slow drips from vine ends and roof lips. MEASURE
  { x: 0.548, y: 0.036, z: 3.3, d: 4.0, rate: 2.2, flow: 0.8, burst: 0.2, warm: 1.5 },
  { x: 0.276, y: 0.29, z: 3.0, d: 4.2, rate: 1.1, flow: 0.9, burst: 0.1, warm: 0.8 },
];

// Lantern boat route (boat.js). Delete it, events.boat and the boatLayer call if the scene has no calm open water
// seen from above. Shared by the renderer and the audio profile in the timeline JSON.
//   camera  the pinhole that matches the plate: focalPx is shared with rain and leaves (2700 px = ~70 deg
//           horizontal FOV at 3840 px); horizon = image row (0..1) of the water's horizon; height = camera height
//           above the water (m). MEASURE both so shore blocks come out ~1 m: scripts/lake_camera.mjs fit.
//   path    screen points ON THE WATER, far end first. The far end must sit in mist (haze hides the boat) and
//           the near end behind solid foreground (outdoor mask 0), so the boat never pops. Check the result with
//           `node .agents/skills/plate-scene/scripts/lake_camera.mjs route scenes/<scene>`.
//   fade    [m faded in from the far end, m faded out at the near end] along the route.
const boatRoute = {
  camera: { focalPx: 2700, horizon: 0.453, height: 16 },
  path: [[0.468, 0.523], [0.457, 0.537], [0.443, 0.553], [0.424, 0.570], [0.400, 0.585], [0.372, 0.598],
    [0.348, 0.611], [0.328, 0.627], [0.315, 0.648], [0.308, 0.675], [0.304, 0.690], [0.302, 0.703]],
  fade: [30, 6],
};

export default {
  name: '<scene>',                 // the folder name under scenes/; outputs go to out/<scene>/
  title: '<Title (setting, weather)>',   // copied into the timeline JSON
  plate: PLATE,                    // engine and CLI read out/plates/<plate>/plate.json (switchable light groups)
  seed: 1,                         // TUNE: pick after reviewing `node src/cli.mjs timeline` (event spread, a rich test hour)
  fps: 30,
  loopSeconds: 120,                // base loop of every periodic motion (integer cycles per loop)
  duration: 36000,                 // 10 h. The timeline always spans the whole video; --duration overrides it.
  events: {
    // Lightning: strike clusters (passing storm cells) at perHour strikes (the count is calibrated per seed, so
    // 10 h at 6/h = 60 strikes); each strike is 1-3 strokes merged into one soft swell; thunder follows at
    // distance / 343 m/s. Delete for a scene without storms.
    //   cluster [min, max] strikes per cluster; withinCluster [s, s] between strikes of a cluster (>= 50 s keeps the
    //   WCAG flash check easy); minGap s after a cluster; maxGap cap on quiet spells (s); startAfter / endBefore s
    //   from the start / end of the video; delay [s, s] thunder delay (2-6 s = 690-2060 m); brightness: flash power.
    lightning: { perHour: 6, cluster: [1, 4], withinCluster: [50, 180], minGap: 90, maxGap: 1800, startAfter: 150, endBefore: 45, delay: [2, 6] },
    // Distant lightning (ambient): soft glows in the cloud bank behind the far terrain, a deep rumble delay [s, s]
    // later, quieter than the rain; with the storm strikes ~30 flashes/h (user 2026-10-16: lightning every ~2 min,
    // but not loud). power [ , ] flash strength (storm ~0.5-1.1); x / y glow center range (image coords) over
    // sky behind the far terrain (MEASURE with the sky mask); clear = s kept away from storm strikes.
    farflash: { perHour: 24, minGap: 35, startAfter: 60, delay: [3, 5], power: [0.45, 0.85], x: [0.2, 0.62], y: [0.12, 0.25], clear: 20 },
    // Slow weather drift, sampled every dt s and read by rain.js, plate.js, leaves and the audio: rain (drop rate),
    // streams (runoff, lagging the rain by streamLag s) and wind (gust strength). rainAmp / windAmp scale the noise;
    // stormRain / stormWind add a swell (relative to the mean) within stormHalfWidth s of each strike.
    weather: { dt: 5, rainAmp: 1.3, windAmp: 1, stormRain: 0.2, stormWind: 0.32, stormHalfWidth: 420, streamLag: 90 },
    // Falling leaves (leaves.js): a Poisson stream, thicker in gusts. depth [m, m] from the camera; size [m, m];
    // x [0..1, 0..1] spawn columns (under the canopy); palette [first, last] indices into plate.json
    // foliage_palette (6 colors, dark -> bright); wind = the wind above plus the loop length. Optional: focalPx
    // (2700), height (2160), startAfter (5 s). Delete for a scene without falling leaves.
    leaves: { perMinute: 4.8, gustBoost: 1.2, depth: [2.4, 7], size: [0.07, 0.12], x: [0.03, 0.83], palette: [2, 5], wind: { ...wind, loop: 120 } },
    // Night lights: switchable windows (plate.json light_groups of kind 'window', not reflective) go dark one by one
    // between offFrom and offTo (s from the start); stayOn = share that stays lit; revisit = share that comes back on
    // for a few minutes. Delete if the plate has no distant windows.
    lights: { offFrom: 19800, offTo: 35400, stayOn: 0.25, revisit: 0.15 },
    // People in the distant houses (per hour): someone walks past a window (pass), a lamp dims (dim), a room goes
    // dark for 2-7 min (away); minGap s between changes; minSize px: smaller windows can't show a change.
    windows: { pass: 4, dim: 2, away: 1.5, minGap: 45, minSize: 10 },
    // Rare (spotlight, one at a time): a lantern (light group of kind 'lantern') gutters with 2-3 soft dips over
    // dur s. Optional keys for every rare type: startAfter (default 300 s), oversample (8) and cooldown (lantern
    // 1200 s, boat 1800 s, heron 2700 s by default); see rareEvents() in src/library/timeline/spotlight.js.
    lantern: { perHour: 1.5, dur: [2.5, 4], cooldown: 900 },
    // Pet micro-motions per hour (plate.js warps; needs pet + petRig below): ear flicks, tail-tip twitches, sighs;
    // thunderEar = chance the ears flick right after near thunder; minGap = s between motions. Delete without a pet.
    pet: { ear: 18, tail: 11, sigh: 7, thunderEar: 0.75, minGap: 12 },
    // Rare: the lantern boat along boatRoute; dur [s, s] per trip, so speed = route length / dur.
    boat: { perHour: 4, dur: [110, 150], startAfter: 300, cooldown: 480, route: boatRoute },
    // Rare: a bird crossing over the water (heron.js; lake camera): distance [m, m] from the camera, speed [m/s, m/s];
    // screenY [row, row] (0..1, y down) = the band it crosses, so it flies in front of bright sky or mist (a dark bird
    // over a dark forest is invisible; MEASURE: sky mask + luminance along the band); camera = the lake camera
    // (or altitude [m, m] instead of screenY + camera). glide [0, 0] = always flapping (glides looked fake).
    heron: { perHour: 3, startAfter: 600, cooldown: 600, distance: [60, 78], screenY: [0.13, 0.18], camera: boatRoute.camera, sink: [-1, 1], glide: [0, 0], speed: [8, 10.5], focalPx: 2700 },
    // Ambient (frequent, may overlap spotlight events): a fish rises (rings, splash, jump share) on open water.
    // zones = [x0, y0, x1, y1, weight] boxes on open water only (MEASURE on a gridded crop; never on reflections of
    // solid things or near the shore). Dropped while a boat is out.
    fish: { perHour: 20, minGap: 60, jump: 0.7, zones: [[0.30, 0.597, 0.38, 0.624, 1.4], [0.38, 0.556, 0.50, 0.592, 2]] },
    // Ambient: a gust flurry: amp [m/s] raised-cosine gust over dur [s] (rain slants, vines lean, leaves burst
    // loose, wind/rustle/creak in the audio); prevailing = sign of 80 % of the gusts.
    flurry: { perHour: 3, minGap: 420, dur: [5, 8], amp: [1.0, 2.0], leaves: [4, 9], prevailing: 1 },
    // Spotlight spacing: rareGap = s kept clear before and after every rare event (default 120); strikeBusy = [s
    // before the flash, s after the thunder] kept clear of spotlight events (default [45, 45]). Shorter values let
    // 4 boats + 3 herons + lanterns per hour fit between the storm strikes.
    rareGap: 45,
    strikeBusy: [30, 30],
  },
  // Shared with tools/audio.py through the timeline JSON.
  weather: { wind, runoff },
  // Ambience mix: deep-merged over DEFAULTS in tools/cozy/audio/ambience.py. lufs = bed loudness target. Optional overrides, e.g.
  // levels_db: { roof: -9 }, rates: { drips: 0.5 }, events: { creak_db: -13 }, music: { lufs: -16.5 }.
  audio: { lufs: -20 },
  // Plate scenes draw full-screen and screen-box quads, but the engine still needs a camera.
  camera: { pos: [0, 0, 1], target: [0, 0, 0], fov: 50 },
  background: '#000000',
  msaa: 0,
  ssaa: 1,
  // Post: no tone mapping (the plate is finished art), a light bloom that must be off for debug=rain (leak QA).
  post: (p) => ({
    toneMapping: 'none',
    exposure: 1.0,
    ao: { enabled: false },
    bloom: { enabled: p.debug !== 'rain', strength: 0.18, radius: 0.5, threshold: 0.92 },
    grade: { lift: [0, 0, 0], gamma: [1, 1, 1], gain: [1, 1, 1], saturation: 1.0, contrast: 1.0 },
    vignette: 0.0,
  }),
  async build(ctx) {
    const qa = ctx.params?.debug === 'rain';
    const only = ctx.params?.only;   // QA: 'runoff' hides falling rain, 'falling' hides runoff
    // Plate shader: mist, water ripples and rain rings, foliage sway, light flicker, pet breathing and rig,
    // switchable lights (night windows, lantern dips) and lightning light.
    await plateLayer(ctx, {
      plate: PLATE,
      // Breathing ellipse (MEASURE on a gridded crop): center cx, cy; radii rx, ry; base = row of the pet's bottom
      // (the breath stretches upward from it). Omit pet and petRig (and events.pet) if there is no pet.
      pet: { cx: 0.802, cy: 0.668, rx: 0.055, ry: 0.042, base: 0.7 },
      // Rig (MEASURE): each ear rotates about `pivot` inside an ellipse at `center` with `radius` [rx, ry], by up
      // to ~`angle` rad per flick; the tail tip lifts by `lift` along base -> tip within `halfWidth` (y).
      petRig: {
        earA: { pivot: [0.7655, 0.6635], center: [0.7635, 0.6575], radius: [0.0058, 0.0105], angle: 0.22 },
        earB: { pivot: [0.774, 0.658], center: [0.774, 0.651], radius: [0.0055, 0.0085], angle: 0.16 },
        tail: { base: [0.836, 0.6925], tip: [0.794, 0.6915], halfWidth: 0.0075, lift: 0.0026 },
      },
      mist: 0.22,                  // drifting mist over far terrain (0 = none). TUNE
      // Calm water through the lake camera: ripples drifting downstream (flow = [upstream, downstream] image points on
      // the water), sway = [horizontal, vertical] reflection sway in px at 4K, rough = gust patch strength (px).
      // Omit for no lake camera (falls back to the screen-space `ripple` shimmer). TUNE with stills 0.5 s apart.
      water: { camera: boatRoute.camera, flow: [boatRoute.path[0], boatRoute.path[boatRoute.path.length - 1]], sway: [9, 18], rough: 18 },
      // Defaults, set only to change them: sway 0.0008, ripple 0.0007, flicker 0.12, waterfall 0.22 (streak
      // strength on flow.png, from the masks json 'waterfall' polygons), mistColor '#2a3044',
      // lightning: { color: '#b9c8ff', sky: 2.2, land: 0.9, roomNear: 0.45, roomAmbient: 0.08, farColor: '#c9c4f2' }.
      debug: qa ? 'black' : undefined,
    });
    if (ctx.params?.rain === 'off') return;   // QA: plate animation only (the rain's contribution = the difference)
    // Tuning without code edits: --params rain.alphaRef=0.3,rain.depth=2.4:30 (top-level rainLayer options; a:b = range).
    const num = (v) => (v.includes(':') ? v.split(':').map(Number) : Number(v));
    const tune = Object.fromEntries(Object.entries(ctx.params ?? {}).filter(([k]) => k.startsWith('rain.')).map(([k, v]) => [k.slice(5), num(v)]));
    // Rain and runoff (every option: plate-weather skill). These are Treetop's approved v3.1 values. TUNE per plate.
    await rainLayer(ctx, {
      plate: PLATE,
      debug: qa,
      count: only === 'runoff' ? 1 : 13000,   // visible drops at nominal intensity
      depth: [2.4, 30],          // m: from just beyond the roof edge out into the valley
      depthPower: 1.45,          // depth pdf ~ z^-1.45: mostly near rain plus a slow far layer
      dropRange: [0.5, 3.6],     // mm
      dropLambda: 2.4,           // 1/mm (exponential size distribution)
      focalPx: 2700,             // same focal length as the leaves and the boat camera
      shutter: 1 / 110,          // streak length = screen speed x shutter
      alphaRef: 0.45,            // opacity of a 2 mm drop at 7 m
      farBoost: 0.3,             // keeps a visible slow far layer
      maxAlpha: 0.9,
      minWidth: 3.4,             // px at 4K: lens-blur floor
      focus: 12, coc: 13,        // defocus px = coc * |1/z - 1/focus|
      skyGain: 2.2, envMix: 0.85, warm: '#ffb26a', warmGain: 0.45, warmNear: 3,   // drops lit by env.png + lantern glints
      wind,
      clumps: { amount: 1.0, strength: 0.55, cycles: 13, across: 3, drift: 1 },
      runoff: only === 'falling' ? [] : runoff,
      runoffGain: 6,
      runoffLook: { minWidth: 4.5, warmGain: 1.2, envMix: 0 },   // pins the runoff look: falling-rain tuning can't change it
      ...tune,
    });
    // Falling leaves from the timeline (same wind and focal length as the rain).
    if (!only) await leavesLayer(ctx, { plate: PLATE, wind, focalPx: 2700, shutter: 1 / 110, ambient: 0.26, warm: 0.9, debug: qa });
    // Lantern boat (route above): returns null when the timeline has no boat events.
    if (!only) await boatLayer(ctx, { plate: PLATE, debug: qa, ...boatRoute });
    // Fish rises and the heron share the boat's lake camera (anything on or over the water uses one camera).
    if (!only) await fishLayer(ctx, { plate: PLATE, debug: qa, camera: boatRoute.camera });
    if (!only) await heronLayer(ctx, { plate: PLATE, debug: qa, camera: boatRoute.camera });
  },
};
