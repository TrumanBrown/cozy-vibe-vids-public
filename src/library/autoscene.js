// Data-driven plate scene: scenes/<scene>/scene.json -> a scene module (the same shape as a hand-written
// scene.js such as scenes/treetop-plate/scene.js). New videos need no JavaScript: tools/analyze_plate.py
// writes scene.json and a three-line scene.js that calls autoScene().
//
// scene.json keys:
//   name, title, aesthetic, plate, seed, fps (30), loopSeconds (120), duration (36000)
//   render: { pixel: { cell, origin: [x, y] } | "plate" (pixel art: px at 4K, or plate.json's grid), animFps: 12 } (optional;
//           pixel art lifts outdoor sways, bobs, ripples and the pet's breathing to about a cell, or they vanish on the grid)
//   post: { bloom, grade, vignette, exposure, toneMapping }                              (engine DEFAULT_POST keys)
//   plate_fx: plateLayer options (mist, mistColor, flicker, sway, ripple, waterfall, lightning, pet, petRig, water)
//   regions: { <region name>: { sway, bob, pendulum, spin, flow, flicker, twinkle, shimmer, breathe, river } } overrides; every
//            region of the plate (regions.json) also gets the defaults of its kind (REGION_FX below).
//            spin: { hz (turns/s), vary (speed swing), dir (1 | -1), pivot } turns a wheel about its hub (kind wheel)
//            river: { dir, amp (ripple shimmer px), glint, period (s), speed (surface drift px/s), cycle (s), texture (0 = no drift) }
//   layers: [{ type: rain | glass | steam | liquid | particles | traffic | leaves | petals | smoke | boat | fish | heron | drips | birds | perch | moth | critter | ant | pet | fire | blink, ...options }]
//   wind: { mean, gust, gustCycles, fronts, turb }, runoff: [...]   (shared by rain, snow, leaves and the audio)
//   events: timeline spec (src/library/timeline.js), audio: tools/audio.py overrides incl. "bed"
import { plateLayer } from './plate.js';
import { rainLayer } from './rain.js';
import { glassLayer } from './glass.js';
import { steamLayer } from './steam.js';
import { particleLayer } from './particles.js';
import { trafficLayer } from './traffic.js';
import { plateRegions } from './overlay.js';

// Plate effects by region kind (overridden per region name in scene.json "regions"; null = none).
// Amplitudes in px at 4K, rates in Hz (rounded to whole cycles per loop).
export const REGION_FX = {
  // Painted flames are removed from the key art (tools/plate_clean.py) and fire.js draws live ones; the region
  // keeps the light: the fire's flicker and the glow it throws on the room.
  fire: { flicker: { style: 'fire', amp: 0.1, spill: 0.1, sigma: 0.16 } },
  water: { river: { amp: 12, glint: 0.6, period: 30, speed: 40 } },   // period: s per ripple pattern length; speed: surface drift px/s (far)
  candle: { flicker: { style: 'candle', amp: 0.12, spill: 0.04, sigma: 0.04 } },
  bob: { bob: { amp: 5, hz: 0.1, x: 0.3 }, flicker: { style: 'candle', amp: 0.1 } },
  lantern: { pendulum: { amp: 1.0, hz: 0.28 }, flicker: { style: 'candle', amp: 0.08, spill: 0.04, sigma: 0.06 } },
  pendulum: { pendulum: { amp: 1.5, hz: 0.32 } },
  chime: { pendulum: { amp: 3, hz: 0.45 } },
  // a windmill's or windpump's wheel, a waterwheel, a fan: turning about its hub (the region's center)
  wheel: { spin: { hz: 0.3, vary: 0.25 } },
  // a small painted flame (a lantern's, an oil lamp's) traced on its own (hand.json, "on_top"): pinned at its base, the
  // tip wavers and stretches as a flame does, and its light flickers; on the pixel grid the tip moves about a cell
  flame: { flicker: { style: 'candle', amp: 0.12, spill: 0.05, sigma: 0.06 }, sway: { amp: 10, hz: 1.4, gust: 0 }, breathe: { amp: 0.12, hz: 2.1 } },
  lamp: { flicker: { style: 'lamp', amp: 0.02 } },
  neon: { flicker: { style: 'neon', amp: 0.03 } },
  string: { twinkle: { amp: 0.35, grid: 110, hz: 0.18, threshold: 0.5 } },
  twinkle: { twinkle: { amp: 0.3, grid: 90, hz: 0.15, threshold: 0.45 } },
  stars: { twinkle: { amp: 0.5, grid: 160, hz: 0.25, threshold: 0.35 } },
  sway: { sway: { amp: 3, hz: 0.1, gust: 1 } },
  // Outdoor cloth (a noren, an awning's side cloth): 3 px at the hem read as painted, 5 px reads as heavy wet cloth
  // stirring; drops and runoff along a hem move with it (overlay.js hangingFrom).
  curtain: { sway: { amp: 5, hz: 0.09, gust: 1.6 } },
  plant: { sway: { amp: 2, hz: 0.12, gust: 1 } },
  flow: { flow: { dir: [0.01, 0], period: 40, vary: 0.5 } },
  clouds: { flow: { dir: [0.012, 0], period: 45, vary: 0.5 } },
  fog: { flow: { dir: [0.015, 0.002], period: 30, vary: 0.6 } },
  smoke: { flow: { dir: [0.004, -0.03], period: 6, vary: 0.7 }, shimmer: { amp: 1.5, scale: 90, hz: 1 } },
  haze: { shimmer: { amp: 1.6, scale: 110, hz: 0.8 } },
  screen: { flicker: { style: 'screen', amp: 0.03 } },
};

function deepMerge(a, b) {
  const out = { ...(a ?? {}) };
  for (const [k, v] of Object.entries(b ?? {})) out[k] = v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' ? deepMerge(out[k], v) : v;
  return out;
}

// The layer types of scene.json "layers": the function that draws each one (rain to traffic are imported above, the
// rest load from `module` only when a scene uses them), and what it gets besides the layer's own options:
// extra(spec, pf) with pf the plate layer's options (its horizon); the layer's own keys win. types.json lists the same
// types for the tools (tests/test_types.py).
export const LAYERS = {
  rain: { fn: rainLayer, extra: (spec) => ({ runoff: spec.runoff ?? [] }) },
  glass: { fn: glassLayer },
  steam: { fn: steamLayer },
  particles: { fn: particleLayer },
  traffic: { fn: trafficLayer },
  leaves: { module: './leaves.js', name: 'leavesLayer' },
  petals: { module: './petals.js', name: 'petalsLayer', extra: (spec, pf) => ({ horizon: pf.horizon }) },
  smoke: { module: './smoke.js', name: 'smokeLayer' },
  moth: { module: './moth.js', name: 'mothLayer' },
  boat: { module: './boat.js', name: 'boatLayer', extra: (spec) => spec.events?.boat?.route ?? {} },
  fish: { module: './fish.js', name: 'fishLayer' },
  heron: { module: './heron.js', name: 'heronLayer' },
  drips: { module: './drips.js', name: 'dripsLayer', extra: (spec, pf) => ({ horizon: pf.horizon }) },
  birds: { module: './birds.js', name: 'birdsLayer' },
  perch: { module: './perch.js', name: 'perchLayer' },
  critter: {
    module: './critters.js', name: 'critterLayer',
    extra: (spec, pf) => ({ scene: spec.name, horizon: pf.horizon, wet: (spec.layers ?? []).some((x) => x.type === 'rain' && x.enabled !== false) }),
  },
  ant: { module: './ant.js', name: 'antLayer' },
  liquid: { module: './liquid.js', name: 'liquidLayer', extra: (spec, pf) => ({ horizon: pf.horizon }) },
  pet: { module: './pet.js', name: 'petLayer' },
  fire: { module: './fire.js', name: 'fireLayer' },
  blink: { module: './blink.js', name: 'blinkLayer' },
};

// The pixel-art grid cell (px at 4K) of a scene rendered on its art's grid (render.pixel), else 0.
function pixelCell(meta, px) {
  return pixelGrid(meta, px)?.cell ?? 0;
}

// The pixel-art grid { cell, origin } (px at 4K) of a scene rendered on its art's grid, else null. meta: the plate's
// plate.json (ctx.plateMeta, read by the engine, which fails the render when it is missing).
function pixelGrid(meta, px) {
  if (!px) return null;
  if (typeof px === 'object' && px.cell) return { cell: px.cell, origin: px.origin ?? [0, 0] };
  return meta?.pixel?.cell ? { cell: meta.pixel.cell, origin: meta.pixel.origin ?? [0, 0] } : null;
}

export function autoScene(spec) {
  const plate = spec.plate ?? spec.name;
  const wind = spec.wind ?? { mean: 0.2, gust: 0.5, gustCycles: 5, fronts: 0.6, turb: 0.5 };
  return {
    name: spec.name,
    title: spec.title,
    aesthetic: spec.aesthetic,
    plate,
    seed: spec.seed ?? 1,
    fps: spec.fps ?? 30,
    loopSeconds: spec.loopSeconds ?? 120,
    duration: spec.duration ?? 36000,
    animFps: spec.render?.animFps,
    pixel: spec.render?.pixel,
    // petals drift and are shaken loose with the scene's own wind (timeline.js petalSchedule)
    events: spec.events?.petals && !spec.events.petals.wind ? { ...spec.events, petals: { ...spec.events.petals, wind: { ...wind, loop: spec.loopSeconds ?? 120 } } } : spec.events ?? {},
    weather: { wind, runoff: spec.runoff ?? [] },
    audio: { lufs: -20, ...(spec.audio ?? {}) },
    camera: { pos: [0, 0, 1], target: [0, 0, 0], fov: 50 },
    background: '#000000',
    msaa: 0,
    post: (p) => deepMerge({
      exposure: 1.0,
      toneMapping: 'none',
      ao: { enabled: false },
      bloom: { enabled: p.debug !== 'rain', strength: 0.18, radius: 0.5, threshold: 0.92 },
      grade: { lift: [0, 0, 0], gamma: [1, 1, 1], gain: [1, 1, 1], saturation: 1.0, contrast: 1.0 },
      vignette: 0.0,
    }, spec.post ?? {}),
    async build(ctx) {
      const qa = ctx.params?.debug === 'rain';
      const only = ctx.params?.only;     // QA: run one layer type alone, e.g. only=glass
      const meta = await plateRegions(plate);
      const fx = {};
      for (const g of meta) {
        let d = REGION_FX[g.kind];
        // a lantern standing on a table or a bench (kind lamp, the model's name says lantern) burns a flame: the lamp
        // kind's 2% flicker read as a still flame in the pixel greenhouse (2026-10-21); no swing, it isn't hanging
        if (g.kind === 'lamp' && /lantern|oil|kerosene/i.test(g.name)) d = { flicker: { style: 'candle', amp: 0.1, spill: 0.05, sigma: 0.06 } };
        // Indoors (no wind): plants and curtains only breathe with the room's air, no gusts.
        if (d?.sway && (g.kind === 'plant' || g.kind === 'curtain') && g.outdoor === false) d = { sway: { ...d.sway, amp: 0.8, gust: 0 } };
        // Water flows the way the analysis saw it go on screen (y down) = across / away on the ground plane.
        if (g.kind === 'water') {
          const f = g.flow ?? [1, 0];
          d = Math.hypot(f[0], f[1]) > 0.05 ? { river: { ...d.river, dir: [f[0], -f[1]] } } : { river: { ...d.river, dir: [1, 0], period: 120, amp: 5, texture: 0 } };   // still water: ripples only, no drift
        }
        const o = spec.regions?.[g.name];
        if (o === null) continue;
        if (d || o) fx[g.name] = deepMerge(d ?? {}, o ?? {});
      }
      const pf = { ...(spec.plate_fx ?? {}) };
      if (ctx.params?.ground === 'off') delete pf.ground;          // QA switches
      if (ctx.params?.river === 'off') for (const k of Object.keys(fx)) if (fx[k].river) delete fx[k].river;
      // Pixel art: the frame is snapped to the art's grid, so motion under one cell vanishes. Outdoor sways, bobs
      // and water ripples reach ~1.2 cells (indoor plants and cloth stay still, as in a real closed room).
      const cell = pixelCell(ctx.plateMeta, spec.render?.pixel);
      if (cell) {
        const k = 1.2 * cell;
        for (const f of Object.values(fx)) {
          if (f.sway && (f.sway.gust ?? 1) > 0) f.sway = { ...f.sway, amp: Math.max(f.sway.amp ?? 4, k) };
          if (f.bob) f.bob = { ...f.bob, amp: Math.max(f.bob.amp ?? 3, k) };
          if (f.river) f.river = { ...f.river, amp: Math.max(f.river.amp ?? 5, k) };
        }
      }
      if (!pf.pet) {
        const pet = meta.find((g) => g.kind === 'pet');
        if (pet) {
          const [x0, y0, x1, y1] = pet.bbox;
          // Breathing stretch scaled to the pet's size on screen: a big foreground pet moves less per pixel of
          // fur (Treetop's approved 0.035 is for a ~180 px tall cat).
          const hpx = (y1 - y0) * 2160;
          pf.pet = { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, rx: (x1 - x0) * 0.46, ry: (y1 - y0) * 0.52, base: y1, amp: 0.035 * Math.min(1, Math.max(0.3, 200 / hpx)) };
          const pm = ctx.plateMeta?.pet_map;
          if (pm) {
            // pet.png: only the torso rises, over a background that never moves; in pixel art the back's top rises
            // about a cell, less vanishes on the grid (user 2026-10-21: the greenhouse dog's ellipse, sized past the
            // outline for pixel art, pushed up the shelf corner behind it and moved its eyes)
            pf.pet.map = true;
            if (cell) pf.pet.amp = (1.05 * cell) / hpx;
            // several characters (the channel's cast, 2026-10-25): each one's height above its own base and its own
            // amplitude are baked into pet.png (plate_prep pet_map_multi); each breathes at its own rate and phase
            if (pm.multi) Object.assign(pf.pet, { multi: true, amp: pm.amp_ref, hmax: pm.hmax });
          } else if (cell) {
            // Pixel art has no fur texture to move: the back itself must rise about a cell, so the warp's ellipse
            // reaches past the outline (it fades out toward its rim) and the stretch is sized to the cell.
            Object.assign(pf.pet, { rx: pf.pet.rx * 1.3, ry: pf.pet.ry * 1.3, amp: Math.max(pf.pet.amp, 1.2 * cell / (0.62 * hpx)) });
          }
        }
      }
      await plateLayer(ctx, { plate, mist: 0, ripple: 0, sway: 0, flicker: 0.03, ...pf, regions: ctx.params?.regions === 'off' ? {} : fx, debug: qa ? 'black' : undefined });
      if (ctx.params?.layers === 'off') return;
      for (const L of spec.layers ?? []) {
        if (L.enabled === false || (only && L.type !== only)) continue;
        const o = { plate, debug: qa, wind: L.wind ?? wind, ...L };
        // Pixel art: small life drawn near life size is a 2-cell speck on the grid (the greenhouse's ladybug and snail,
        // 2026-10-21); as pixel games draw them, a critter is at least ~6.5 cells long and a moth ~4 cells across
        if (cell && L.type === 'critter') {
          const s0 = o.size ?? 70, s1 = o.sizeEnd ?? s0, k = Math.max(1, (6.5 * cell) / Math.min(s0, s1));
          Object.assign(o, { size: s0 * k, sizeEnd: s1 * k, pixelGrid: pixelGrid(ctx.plateMeta, spec.render?.pixel) });
        }
        if (cell && L.type === 'moth') Object.assign(o, { size: Math.max(o.size ?? 11, 4 * cell), silhouette: o.silhouette ?? true, pixelGrid: pixelGrid(ctx.plateMeta, spec.render?.pixel) });
        // a flying bird keeps its flapping shape from ~6 cells across, and a rain streak shows only where it covers a cell's
        // center: thinner streaks came out as a few scattered specks on the greenhouse's dawn sky (2026-10-21)
        if (cell && L.type === 'birds') Object.assign(o, { minSpan: Math.max(o.minSpan ?? 0, 6 * cell), pixelGrid: pixelGrid(ctx.plateMeta, spec.render?.pixel) });
        if (cell && L.type === 'rain') o.minWidth = Math.max(o.minWidth ?? 1.6, cell);
        const R = Object.hasOwn(LAYERS, L.type) ? LAYERS[L.type] : null;
        if (!R) throw new Error(`autoScene: unknown layer type ${L.type}`);
        const draw = R.fn ?? (await import(R.module))[R.name];
        await draw(ctx, R.extra ? { ...R.extra(spec, pf), ...o } : o);
      }
      // the intro title over everything, from tools/intro_title.py (scene.json `intro`)
      if (spec.intro && !only) await (await import('./title.js')).titleLayer(ctx, { plate });
    },
  };
}
