// Treetop (rainy dusk), plate-based: AI key art (gpt-image-2.5-sunburst via tools/keyart.py,
// prompt in scenes/treetop/keyart.json) prepared by tools/plate_prep.py into out/plates/treetop_rainy,
// animated in code: src/library/plate.js (mist, ripples, sway, flicker, breathing cat, waterfalls, window
// lights, lightning light) and src/library/rain.js (physically based rain + roof runoff/drips); falling
// leaves, a lantern boat, fish rising and a heron are their own layers. Loop: 120 s. Events come from the
// seeded timeline (src/library/timeline.js); audio from tools/audio.py (same timeline/weather).
// QA params: debug=rain (rain coverage only), only=runoff|falling, rain=off, events=off, rain.<opt>=<v>.
import { plateLayer } from '../../src/library/plate.js';
import { rainLayer } from '../../src/library/rain.js';
import { leavesLayer } from '../../src/library/leaves.js';
import { boatLayer } from '../../src/library/boat.js';
import { fishLayer } from '../../src/library/fish.js';
import { heronLayer } from '../../src/library/heron.js';

// Wind (m/s): mean + gusts with `gustCycles` per loop, sweeping across the frame (`fronts`), plus
// per-drop turbulence. The audio follows the same gusts (rain swells, wind whoosh).
const wind = { mean: 0.05, gust: 0.5, gustCycles: 5, fronts: 0.6, turb: 0.75 };

// Runoff sources in plate coords (x, y: 0..1, y down; y < 0 = lip above the frame). Positions come from
// out/plates/treetop_rainy/plate.json + edges_preview.png (open columns under the roof edge, vine ends).
// z: lip distance (m); d: bead diameter (mm); rate: bead releases/s at full flow; flow/burst: mean flow
// and surges; neck: unbroken column below a visible lip (m); warm: how much lantern light it catches.
const runoff = [
  // Roof edge just above the frame: a strong pour and a lighter one (open sky columns down to the railing).
  // Rates are chosen so 1/60 s bead streaks leave gaps (a chain of dashes); surges close them up.
  { x: 0.312, y: -0.03, z: 3.4, d: 5.0, rate: 46, flow: 0.65, burst: 0.3, burstCycles: 3, spread: 0.012, warm: 0.6, bright: 1.5 },
  { x: 0.252, y: -0.02, z: 3.4, d: 4.2, rate: 30, flow: 0.5, burst: 0.35, burstCycles: 4, spread: 0.018, warm: 0.6, bright: 1.2 },
  // Visible porch-roof lip between two vines, left of the hanging lantern (neck shows; lantern-lit).
  { x: 0.571, y: 0.026, z: 3.3, d: 4.6, rate: 36, flow: 0.62, burst: 0.3, burstCycles: 5, neck: 0.05, spread: 0.015, warm: 2.0, bright: 1.3 },
  // Sparse drips along the same lip.
  { x: 0.548, y: 0.036, z: 3.3, d: 4.0, rate: 2.2, flow: 0.8, burst: 0.2, warm: 1.5 },
  { x: 0.589, y: 0.03, z: 3.3, d: 4.0, rate: 1.6, flow: 0.8, burst: 0.2, warm: 1.8 },
  // Slow drips from vine ends.
  { x: 0.276, y: 0.29, z: 3.0, d: 4.2, rate: 1.1, flow: 0.9, burst: 0.1, warm: 0.8 },
  { x: 0.595, y: 0.305, z: 3.0, d: 4.2, rate: 0.7, flow: 0.9, burst: 0.1, warm: 1.2 },
  { x: 0.745, y: 0.32, z: 2.9, d: 4.4, rate: 1.4, flow: 0.9, burst: 0.1, warm: 2.5 },
  { x: 0.793, y: 0.295, z: 2.8, d: 4.0, rate: 0.8, flow: 0.9, burst: 0.1, warm: 2.5 },
  { x: 0.055, y: 0.44, z: 2.3, d: 4.4, rate: 0.6, flow: 0.9, burst: 0.1, warm: 3.0 },
  { x: 0.418, y: 0.12, z: 3.2, d: 4.0, rate: 0.9, flow: 0.9, burst: 0.1, warm: 0.6 },
  { x: 0.555, y: 0.095, z: 3.2, d: 4.0, rate: 0.5, flow: 0.9, burst: 0.1, warm: 0.6 },
];

// Lantern boat route (shared by the renderer and the audio profile in the timeline JSON): screen points on
// the water, far end first: out of the far mist, down the river, across the near basin and away behind the
// porch railing. Camera: same focal length as rain/leaves; height/horizon calibrated so shore blocks are
// ~1 m. Fades (m of route): out of the mist / once hidden behind the railing.
const boatRoute = {
  camera: { focalPx: 2700, horizon: 0.453, height: 16 },
  path: [[0.468, 0.523], [0.457, 0.537], [0.443, 0.553], [0.424, 0.570], [0.400, 0.585], [0.372, 0.598],
    [0.348, 0.611], [0.328, 0.627], [0.315, 0.648], [0.308, 0.675], [0.304, 0.690], [0.302, 0.703]],
  fade: [30, 6],
};

export default {
  name: 'treetop-plate',
  title: 'Autumn Treetop (rainy dusk)',
  plate: 'treetop_rainy',    // out/plates/<plate>/ (switchable lights for the timeline come from its plate.json)
  seed: 11,
  fps: 30,
  loopSeconds: 120,
  duration: 36000,           // 10 h: the event timeline always spans the whole video
  // Events. User 2026-10-15: more often and more animated, still realistic and calming; 2026-10-16: far more
  // often, alive but calm enough to study to. Something happens about every 30-40 s
  // on average, mostly small; the spotlight events (boat, heron, lantern) stay one at a time.
  events: {
    // Storm strikes overhead (~6/h in passing cells): flash lights the valley and porch, thunder 2-6 s later.
    lightning: { perHour: 6, cluster: [1, 4], withinCluster: [50, 180], minGap: 90, maxGap: 1800, startAfter: 150, endBefore: 45, delay: [2, 6] },
    // Distant lightning (~24/h, so ~30 flashes/h in all): glows in the cloud bank behind the mountains, a soft
    // low rumble 3-5 s later, quieter than the rain (user 2026-10-16: quiet, there to keep it dynamic; the rumble
    // should come sooner than the realistic 8-20 s: about 4 s).
    farflash: { perHour: 24, minGap: 35, startAfter: 60, delay: [3, 5], power: [0.45, 0.85], x: [0.2, 0.62], y: [0.12, 0.25], clear: 20 },
    weather: { dt: 5, rainAmp: 1.3, windAmp: 1, stormRain: 0.2, stormWind: 0.32, stormHalfWidth: 420, streamLag: 90 },
    // Falling leaves (continuous, seeded): ~5/min, more in gusts; from the canopy above the porch.
    leaves: { perMinute: 4.8, gustBoost: 1.2, depth: [2.4, 7], size: [0.07, 0.12], x: [0.03, 0.83], palette: [2, 5], wind: { ...wind, loop: 120 } },
    // Slow evolution: distant windows go dark one by one late at night (from 5.5 h); a few stay on, a few
    // come back on for a while.
    lights: { offFrom: 19800, offTo: 35400, stayOn: 0.25, revisit: 0.15 },
    // People in the distant houses (per hour): someone walks past a window, a lamp dims, a room goes dark
    // for a few minutes.
    windows: { pass: 4, dim: 2, away: 1.5, minGap: 45, minSize: 10 },
    // Spotlight: a porch lantern gutters (2-3 soft dips over ~3 s), ~1.5/h.
    lantern: { perHour: 1.5, dur: [2.5, 4], cooldown: 900 },
    // Cat micro-motions (per hour); the cat's ears also flick right after most near thunder.
    pet: { ear: 18, tail: 11, sigh: 7, thunderEar: 0.75, minGap: 12 },
    // Spotlight: a small covered lantern boat comes down the river out of the mist and passes under the
    // porch, or heads back up into the mist (~4/h; ~200 m route, 1.3-1.8 m/s).
    boat: { perHour: 4, dur: [110, 150], startAfter: 300, cooldown: 480, route: boatRoute },
    // Spotlight: a grey heron crosses the valley along the river (~3/h), 60-78 m out at 60-80 px wingspan (4K),
    // its height chosen so it crosses the bright band of misty sky (13-18% down the frame). Over the dark far
    // forest or the dark peak a dark bird disappears; sink (m over the crossing) stays small for that reason.
    // Always flapping (user 2026-10-16: glides looked like a sprite sliding along a straight line).
    heron: { perHour: 3, startAfter: 600, cooldown: 600, distance: [60, 78], screenY: [0.13, 0.18], camera: boatRoute.camera, sink: [-1, 1], glide: [0, 0], speed: [8, 10.5], focalPx: 2700 },
    // Ambient: a fish rises (splash + rings, most of them jump) somewhere on open water, ~20/h. Zones: screen
    // rects on the river [x0, y0, x1, y1, weight]: near basin, main channel, right bank, far reach, water seen
    // through the rail.
    fish: {
      perHour: 20, minGap: 60, jump: 0.7,
      zones: [[0.30, 0.597, 0.38, 0.624, 1.4], [0.38, 0.556, 0.50, 0.592, 2], [0.50, 0.566, 0.555, 0.584, 0.7],
        [0.425, 0.529, 0.47, 0.547, 0.6], [0.36, 0.69, 0.51, 0.75, 0.8]],
    },
    // Ambient: a gust flurry (~3/h): rain leans, vines sway harder, a handful of leaves blow off.
    flurry: { perHour: 3, minGap: 420, dur: [5, 8], amp: [1.0, 2.0], leaves: [4, 9], prevailing: 1 },
    // Spotlight spacing: s kept clear around every spotlight event, and around each storm strike (from
    // before the flash until after its thunder).
    rareGap: 45,
    strikeBusy: [30, 30],
  },
  // Shared with tools/audio.py through the timeline JSON (node src/cli.mjs timeline).
  weather: { wind, runoff },
  // Ambience mix (tools/audio.py): layer levels in dB relative to the rain wash; loudness target.
  audio: { lufs: -20 },
  camera: { pos: [0, 0, 1], target: [0, 0, 0], fov: 50 },
  background: '#000000',
  msaa: 0,
  ssaa: 1,
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
    const only = ctx.params?.only; // QA: 'runoff' hides falling rain, 'falling' hides runoff
    await plateLayer(ctx, {
      plate: 'treetop_rainy',
      pet: { cx: 0.802, cy: 0.668, rx: 0.055, ry: 0.042, base: 0.7 },
      // Cat rig in image coords (from out/plates/treetop_rainy/cat_head.png / cat_body.png grids).
      petRig: {
        earA: { pivot: [0.7655, 0.6635], center: [0.7635, 0.6575], radius: [0.0058, 0.0105], angle: 0.22 },
        earB: { pivot: [0.774, 0.658], center: [0.774, 0.651], radius: [0.0055, 0.0085], angle: 0.16 },
        tail: { base: [0.836, 0.6925], tip: [0.794, 0.6915], halfWidth: 0.0075, lift: 0.0026 },
      },
      mist: 0.22,
      // Calm river ripples drifting downstream (along the boat route, upstream end first); a rougher
      // patch crosses the water in gust flurries.
      water: { camera: boatRoute.camera, flow: [boatRoute.path[0], boatRoute.path[boatRoute.path.length - 1]], sway: [9, 18], rough: 18 },
      debug: qa ? 'black' : undefined,
    });
    if (ctx.params?.rain === 'off') return; // QA: plate animation only (rain contribution = diff)
    // Tuning/QA overrides: --params rain.alphaRef=0.2,rain.depth=2.4:30 (top-level rainLayer options; a:b = range).
    const num = (v) => (v.includes(':') ? v.split(':').map(Number) : Number(v));
    const tune = Object.fromEntries(Object.entries(ctx.params ?? {}).filter(([k]) => k.startsWith('rain.')).map(([k, v]) => [k.slice(5), num(v)]));
    await rainLayer(ctx, {
      plate: 'treetop_rainy',
      debug: qa,
      count: only === 'runoff' ? 1 : 13000,
      depth: [2.4, 30],        // m: from just beyond the roof edge out into the valley
      depthPower: 1.45,        // depth pdf ~ z^-1.45: mostly near rain plus a slow far layer
      dropRange: [0.5, 3.6],   // mm
      dropLambda: 2.4,         // 1/mm (exponential size distribution; user 2026-10-15: background rain finer)
      focalPx: 2700,           // ~70 deg horizontal FOV at 3840 px
      shutter: 1 / 110,        // ~100 deg shutter at 30 fps (reference footage: ~1/120 s)
      alphaRef: 0.45,          // opacity of a 2 mm drop at 7 m (dimmer env lighting below compensates)
      farBoost: 0.3,           // keep a visible slow far layer (speed variety, as in the reference)
      maxAlpha: 0.9,
      minWidth: 3.4,           // px at 4K: lens blur floor (opacity scales down to keep energy)
      focus: 12, coc: 13,      // defocus px = coc*|1/z - 1/focus|: near drops wider + fainter
      // Drop light: sky light mixed with the local environment (env.png), so rain in front of the dark
      // forest stays subtle and rain against the misty sky reads; small lantern glints only.
      skyGain: 2.2, envMix: 0.85, warm: '#ffb26a', warmGain: 0.45, warmNear: 3,
      wind,
      clumps: { amount: 1.0, strength: 0.55, cycles: 13, across: 3, drift: 1 },
      runoff: only === 'falling' ? [] : runoff,
      runoffGain: 6,
      runoffLook: { minWidth: 4.5, warmGain: 1.2, envMix: 0 },  // approved by the user 2026-10-15: keep
      ...tune,
    });
    if (!only) await leavesLayer(ctx, { plate: 'treetop_rainy', wind, focalPx: 2700, shutter: 1 / 110, ambient: 0.26, warm: 0.9, debug: qa });
    // Lantern boat (route above): a ray-marched voxel skiff with reflection, wake and lantern glitter.
    if (!only) await boatLayer(ctx, { plate: 'treetop_rainy', debug: qa, ...boatRoute });
    // Fish rising (rings on the water) and a heron crossing the valley, through the same lake camera.
    if (!only) await fishLayer(ctx, { plate: 'treetop_rainy', debug: qa, camera: boatRoute.camera });
    if (!only) await heronLayer(ctx, { plate: 'treetop_rainy', debug: qa, camera: boatRoute.camera });
  },
};
