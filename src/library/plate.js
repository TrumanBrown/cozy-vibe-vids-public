// Plate animation: one full-screen shader over an AI key-art plate (out/plates/<name>/ from
// tools/plate_prep.py). All motion is a pure function of phase = (t mod L) / L with integer cycle
// counts, so frames are deterministic and the loop is seamless.
//
// Layers: foliage sway, water ripples + rain rings, drifting mist over far terrain, lantern flicker,
// a breathing pet region, and lightning light from the event timeline (timeline.js). Falling rain and
// roof runoff are separate instanced layers (rain.js).
import * as THREE from 'three';
import { flashAt, trackAt, lightLevels, petState, flurryEnv, flurryWind, flurryUniform, regionDip } from './timeline.js';
import { lakeCamera } from './boat.js';
import { plateFrag, plateVert } from './plate.glsl.js';

async function load(url, srgb) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = false;
  t.minFilter = THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}
// Optional per-plate map (e.g. flow.png only exists for plates with waterfalls): black 1x1 if missing (or no url).
async function loadOptional(url) {
  try {
    if (!url) throw new Error('no map');
    return await load(url, false);
  } catch {
    const t = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
    t.needsUpdate = true;
    return t;
  }
}

const TAU_JS = Math.PI * 2;
function hashName(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return ((h >>> 0) % 100000) / 100000;
}

// The surf's defaults (scene.json plate_fx.surf overrides; the surf layer, surf.js, times its spray and wash with the
// same): rest (the painted foam's level between waves), travel (s a wave takes to cross the zone shoreward), peel (s it
// takes to peel along it), decay (s the foam fades over), push (px it rides shoreward), swell (the brightness of the
// band running in ahead of it), peak (the foam's level as it breaks), lead (s the picture runs ahead of the waves' sound).
export const SURF = { rest: 0.5, travel: 2.6, peel: 1.6, decay: 3.2, push: 10, swell: 0.035, peak: 1.15, lead: 1.0 };

// The surf's waves at t (timeline 'surf' events, sorted by t): the n newest that have broken by t + 2 s (the swell's
// band runs in just ahead of a wave), newest first, as the shader's rows: x s since it broke at the zone's far edge
// (negative just before), y strength, z peel direction (+1 left to right); a row with no wave has no strength. lead: s the
// picture runs ahead of the event's time: a wave's sound (cozy/audio/ambience.py) roars from its event's time, and the
// first rocks lie a second into the zone, so the tide pool's spray came a second after the roar (2026-11-05).
export function surfWaves(waves, t, n = 4, out = Array.from({ length: n }, () => new THREE.Vector4()), lead = 0) {
  let lo = 0, hi = waves.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (waves[m].t <= t + lead + 2) lo = m + 1; else hi = m; }
  for (let i = 0; i < n; i++) {
    const e = waves[lo - 1 - i];
    if (e && t + lead - e.t < 45) out[i].set(t + lead - e.t, e.amp, e.peel, 0);
    else out[i].set(0, 0, 0, 0);
  }
  return out;
}

// The moon's way across the sky (opts.moon): a smooth curve through `path` (image coords) walked at an even pace over
// `travel` s of every `period` s (the timeline's loop: whole crossings per loop, so the 10 h stays seamless), out of
// sight the rest (both ends lie behind something: it rises and sets). At t = 0 it is where it was painted (moon.json),
// so the video opens on the key art's own sky. Returns (t) => { x, y (image coords), vis 0..1 }.
export function moonPath(opts, meta, period) {
  const P = opts.path;
  const cr = (p0, p1, p2, p3, u) => {
    const u2 = u * u, u3 = u2 * u;
    return [0, 1].map((k) => 0.5 * (2 * p1[k] + (-p0[k] + p2[k]) * u + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * u2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * u3));
  };
  const pts = [];
  for (let i = 0; i < P.length - 1; i++) {
    for (let j = 0; j < 40; j++) pts.push(cr(P[Math.max(0, i - 1)], P[i], P[i + 1], P[Math.min(P.length - 1, i + 2)], j / 40));
  }
  pts.push(P[P.length - 1]);
  const len = [0];
  for (let i = 1; i < pts.length; i++) len.push(len[i - 1] + Math.hypot((pts[i][0] - pts[i - 1][0]) * 16 / 9, pts[i][1] - pts[i - 1][1]));
  const total = len[len.length - 1];
  const at = (u) => {
    const s = Math.min(Math.max(u, 0), 1) * total;
    let i = 1;
    while (i < len.length - 1 && len[i] < s) i++;
    const f = (s - len[i - 1]) / Math.max(len[i] - len[i - 1], 1e-9);
    return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f];
  };
  // where along the way the painted moon is
  const c = [meta.center[0] / 3840, meta.center[1] / 2160];
  let best = 0, bd = Infinity;
  for (let i = 0; i < pts.length; i++) {
    const dd = Math.hypot((pts[i][0] - c[0]) * 16 / 9, pts[i][1] - c[1]);
    if (dd < bd) { bd = dd; best = len[i] / total; }
  }
  const travel = opts.travel ?? 0.83 * period;
  const t0 = best * travel;
  return (t) => {
    const s = ((((t + t0) % period) + period) % period);
    if (s >= travel) return { x: P[P.length - 1][0], y: P[P.length - 1][1], vis: 0 };
    const u = s / travel, [x, y] = at(u);
    const vis = Math.min(1, u / 0.04, (1 - u) / 0.04);
    return { x, y, vis };
  };
}

// Light signals by style (1 = as painted), sums of integer-cycle sines (seamless). Fire: lively, several
// rates; candle: slow sway with a little quick flutter; neon and lamps: nearly steady (their events dip them).
const FLICKER = {
  fire: [[1.1, 0.45], [2.3, 0.3], [4.7, 0.2], [7.9, 0.12], [11.3, 0.08]],
  candle: [[0.7, 0.6], [1.9, 0.3], [5.3, 0.15]],
  neon: [[0.2, 0.3]],
  lamp: [[0.05, 0.1]],
  screen: [[0.1, 0.3], [0.37, 0.2]],
};

// Normalized flicker signal (-1..1) of a named region at time t: the signal its light follows in the plate
// (makeRegionState below), so fire.js can make the flames rise and fall with the light they throw.
export function flickerSignal(name, seed, style, t, L, speed = 1) {
  const comps = FLICKER[style] ?? FLICKER.fire;
  const ph = TAU_JS * hashName(`${name}:${seed}`);
  const tt = t % L;
  let s = 0, n = 0;
  comps.forEach(([hz, a], i) => { s += a * Math.sin(TAU_JS * Math.max(1, Math.round(hz * speed * L)) * tt / L + ph * (i + 1)); n += a; });
  return s / n;
}

// Region effects (opts.regions: { <region name>: { sway, bob, pendulum, spin, flow, flicker, twinkle, shimmer,
// breathe, river } }) -> per-frame state rows in tReg (64 ids x 9 rows, RGBA float). Frequencies (hz) are rounded
// to whole cycles per loop; amplitudes are px at 4K unless noted. spin: { hz (turns/s, 0.3), vary (0.25), dir (1 or
// -1), pivot } turns the region about its hub (a windmill's wheel). See docs in autoscene.js.
function makeRegionState(ctx, meta, cfg, mistDry = false) {
  const L = ctx.loopSeconds;
  const cyc = (hz) => Math.max(1, Math.round(hz * L));
  const byName = Object.fromEntries(meta.map((g) => [g.name, g]));
  const data = new Float32Array(64 * 9 * 4);
  const tex = new THREE.DataTexture(data, 64, 9, THREE.RGBAFormat, THREE.FloatType);
  tex.minFilter = tex.magFilter = THREE.NearestFilter;
  tex.needsUpdate = true;
  const set = (row, id, v) => data.set(v, (row * 64 + id) * 4);
  const items = [];
  for (const [name, fx] of Object.entries(cfg ?? {})) {
    const g = byName[name];
    if (!g || !fx) continue;
    const ph = TAU_JS * hashName(`${name}:${ctx.seed}`);
    const it = { g, fx, ph, flags: 0 };
    if (fx.sway) it.flags |= 1;
    if (fx.bob) it.flags |= 2;
    if (fx.pendulum || fx.spin) it.flags |= 4;
    if (fx.flow) it.flags |= 8;
    if (fx.flicker) it.flags |= 16;
    if (fx.twinkle) it.flags |= 32;
    if (fx.shimmer) it.flags |= 64;
    if (fx.breathe) it.flags |= 128;
    if (fx.river) it.flags |= 256;
    if (mistDry && g.dry) it.flags |= 512;
    // a pendulum swings about the top of its box, a wheel spins about its hub (the box's center)
    const pv = fx.spin ? (fx.spin.pivot ?? g.pivot ?? g.center ?? [(g.bbox[0] + g.bbox[2]) / 2, (g.bbox[1] + g.bbox[3]) / 2])
      : (fx.pendulum?.pivot ?? g.pivot ?? [(g.bbox[0] + g.bbox[2]) / 2, g.bbox[1]]);
    set(2, g.id, [pv[0], 1 - pv[1], 0, fx.flow?.vary ?? 0.5]);
    const fd = fx.flow?.dir ?? [0, 0];
    set(3, g.id, [fd[0], -fd[1], (fx.shimmer?.amp ?? 0) / 3840, 0]);
    set(5, g.id, [fx.breathe?.amp ?? 0, 1 - g.bbox[3], 0, 0]);
    set(6, g.id, [fx.shimmer?.scale ?? 140, 0, 0, 0]);
    if (fx.river) {
      const d = fx.river.dir ?? [1, 0], n = Math.hypot(d[0], d[1]) || 1;
      set(7, g.id, [d[0] / n, d[1] / n, fx.river.amp ?? 5, fx.river.glint ?? 0.6]);
    }
    items.push(it);
  }
  // characters and what they hold (regions.json `dry`, cut out of the outdoors to keep the weather off them): with
  // plate_fx.mistDry, flag 512 tells the shader the part of their traced outline that runs out into the view behind
  // isn't indoors (opt-in: the approved scenes keep their pictures)
  const dry = mistDry ? meta.filter((g) => g.dry && g.id < 64) : [];
  for (const g of dry) if (!items.some((it) => it.g.id === g.id)) set(0, g.id, [512, 0, 0, 1]);
  const spill = Array.from({ length: 8 }, () => new THREE.Vector4());
  let spillN = 0;
  const row = (r, id) => data.subarray((r * 64 + id) * 4, (r * 64 + id) * 4 + 4);
  return {
    tex, spill, get spillN() { return spillN; }, active: items.length > 0 || dry.length > 0,
    // Does region `id` move the plate (sway, bob or pendulum)?
    moves: (id) => items.some((it) => it.g.id === id && (it.flags & 7) !== 0),
    // Where this frame's warp moves the content at image point (x, y: px at 4K, y down) of region `id`, given
    // the region's axis coordinate and weight there (regions.png B, G): [dx, dy] px, y down. The shader's sway,
    // bob and pendulum (first-order inverse of the sample offset), so drops hanging from a swaying hem or a
    // swinging lantern move with it.
    offsetPx(id, x, y, ax, w) {
      const a = row(0, id), b = row(1, id), p = row(2, id);
      const fl = Math.round(a[0]);
      const u = x / 3840, v = 1 - y / 2160;
      let ox = 0, oy = 0;
      if (fl & 1) {
        const sw = Math.sin(a[2] + v * 9 + u * 5) * 0.7 + 0.3 * Math.sin(2 * a[2] + 1.3 + v * 23);
        ox -= w * a[1] * Math.pow(ax, 1.5) * sw * a[3];
      }
      if (fl & 2) { ox -= w * b[0]; oy -= w * b[1]; }
      if (fl & 4) {
        const asp = 1.7778, dx = (u - p[0]) * asp, dy = v - p[1], c = Math.cos(-b[2]), s = Math.sin(-b[2]);
        ox += w * ((c * dx - s * dy) / asp + p[0] - u);
        oy += w * (s * dx + c * dy + p[1] - v);
      }
      return [-ox * 3840, oy * 2160];
    },
    update(tAbs, gust, dipOf) {
      spillN = 0;
      const t = tAbs % L;          // every region motion is L-periodic: wrap so the loop seam is exact
      for (const { g, fx, ph, flags } of items) {
        const id = g.id;
        const sw = fx.sway, bb = fx.bob, pd = fx.pendulum, fl = fx.flow, fk = fx.flicker, tw = fx.twinkle, sh = fx.shimmer, br = fx.breathe;
        const swayPh = sw ? TAU_JS * cyc(sw.hz ?? 0.12) * t / L + ph : 0;
        set(0, id, [flags, sw ? (sw.amp ?? 4) / 3840 : 0, swayPh, 1 + (sw?.gust ?? 1) * 1.2 * gust]);
        let tx = 0, ty = 0, ang = 0, level = 1;
        if (bb) {
          const c = cyc(bb.hz ?? 0.18), s = Math.sin(TAU_JS * c * t / L + ph);
          ty = ((bb.amp ?? 3) / 2160) * s;
          tx = ((bb.amp ?? 3) / 3840) * (bb.x ?? 0.25) * Math.sin(TAU_JS * (c + 1) * t / L + 1.7 * ph);
        }
        if (pd) {
          const c = cyc(pd.hz ?? 0.35);
          ang = ((pd.amp ?? 1.5) * Math.PI / 180) * (Math.sin(TAU_JS * c * t / L + ph) * 0.8 + 0.2 * Math.sin(TAU_JS * (2 * c + 1) * t / L + 2 * ph)) * (1 + (pd.gust ?? 1) * 1.5 * gust);
        }
        if (fx.spin) {
          // whole turns per loop, the speed swinging +-vary over ~20 s (a periodic term, so the loop seam is exact)
          const sp = fx.spin, n = cyc(sp.hz ?? 0.3), k = cyc(1 / 20);
          ang = (sp.dir ?? 1) * (TAU_JS * n * t / L + ((sp.vary ?? 0.25) * n / k) * Math.sin(TAU_JS * k * t / L + ph));
        }
        if (fk) {
          const comps = FLICKER[fk.style ?? 'fire'] ?? FLICKER.fire;
          let s = 0, n = 0;
          comps.forEach(([hz, a], i) => { s += a * Math.sin(TAU_JS * cyc(hz * (fk.speed ?? 1)) * t / L + ph * (i + 1)); n += a; });
          level = 1 + (fk.amp ?? 0.08) * (s / n);
          if (dipOf) level *= 1 - dipOf(g.name, tAbs);
          if ((fk.spill ?? 0) > 0 && spillN < 8) {
            const c = g.center;
            spill[spillN++].set(c[0], 1 - c[1], fk.sigma ?? 0.08, fk.spill * (level - 1) / Math.max(fk.amp ?? 0.08, 1e-3));
          }
        }
        set(1, id, [tx, ty, ang, level]);
        if (fl) {
          const c = Math.max(1, Math.round(L / (fl.period ?? 30)));
          data[(2 * 64 + id) * 4 + 2] = (c * t / L) % 1;
          // slow sideways sway of the flow (flames leaning in a draft): 7 s swell x 4 s travel, whole cycles
          const w = (fl.wobble ?? 0) * (0.6 + 0.4 * Math.sin(TAU_JS * cyc(1 / 7) * t / L + ph));
          data[(6 * 64 + id) * 4 + 1] = w;
          data[(6 * 64 + id) * 4 + 2] = TAU_JS * cyc(1 / 4) * t / L + 2 * ph;
        }
        if (tw) set(4, id, [tw.amp ?? 0.25, tw.grid ?? 80, cyc(tw.hz ?? 0.25) * t / L, tw.threshold ?? 0.45]);
        if (fx.river) {
          data[(2 * 64 + id) * 4 + 2] = (Math.max(1, Math.round(L / (fx.river.period ?? 10))) * t / L) % 1;
          // surface texture drift: a ~2 s crossfade cycle (whole cycles per loop) and the px it travels per cycle
          const n = Math.max(1, Math.round(L / (fx.river.cycle ?? 2)));
          set(8, id, [(n * t / L) % 1, (fx.river.speed ?? 40) * L / n, fx.river.texture ?? 1, 0]);
        }
        if (sh) data[(3 * 64 + id) * 4 + 3] = 2 * Math.max(1, Math.round((sh.hz ?? 1.5) * L / 2)) * t / L;
        if (br) data[(5 * 64 + id) * 4 + 2] = 0.5 + 0.5 * Math.sin(TAU_JS * cyc(br.hz ?? 0.28) * t / L + ph);
      }
      tex.needsUpdate = true;
    },
  };
}

// opts: { plate: 'treetop_rainy', pet: {cx, cy, rx, ry, base} in image coords (0..1, y down),
//         lightning: { color, sky, land, roomNear, roomAmbient }, ...tuning }
export async function plateLayer(ctx, opts) {
  const dir = `/out/plates/${opts.plate}`;
  const [tPlate, tDepth, tMask, tLights, tFlash, tPlateOff, tLightId, tLightW, tFlow, tBlur] = await Promise.all([
    load(`${dir}/plate.png`, true), load(`${dir}/depth8.png`, false), load(`${dir}/masks.png`, false), load(`${dir}/lights.png`, false),
    load(`${dir}/flash.png`, false), load(`${dir}/plate_off.png`, true), load(`${dir}/lightid.png`, false), load(`${dir}/lightw.png`, false),
    loadOptional(`${dir}/flow.png`), loadOptional(`${dir}/blur.png`),
  ]);
  tBlur.colorSpace = THREE.SRGBColorSpace;
  for (const t of [tLightId, tLightW]) t.minFilter = t.magFilter = THREE.NearestFilter;
  // Named regions (optional): id map + per-frame state.
  let regMeta = [], tRegion = null;
  try {
    regMeta = await fetch(`${dir}/regions.json`).then((r) => (r.ok ? r.json() : []));
    if (regMeta.length) {
      tRegion = await load(`${dir}/regions.png`, false);
      tRegion.minFilter = tRegion.magFilter = THREE.NearestFilter;
    }
  } catch { regMeta = []; }
  const regs = makeRegionState(ctx, regMeta, opts.regions, !!opts.mistDry);
  // Reflections of the regions' lights on the wet ground (optional; black = none).
  const tRefl = await loadOptional(`${dir}/refl.png`);
  tRefl.minFilter = tRefl.magFilter = THREE.NearestFilter;
  // A moon crossing the sky (opts.moon, scene.json plate_fx.moon): plate_prep lifted the painted one and its glitter
  // on the water off the plate (hand.json "moon"; cozy/plate/moon.py writes moon.json, moon.png and moonfx.png: red
  // where it and its glow show, the open sky snapped to the treetops' own edges; green its glitter's luminance)
  let moonAt = null, moonMeta = null, tMoon = await loadOptional(null), tMoonFx = tMoon;
  const halo = Array.from({ length: 24 }, () => new THREE.Vector3());
  let haloStep = 8;
  if (opts.moon) {
    moonMeta = await fetch(`${dir}/moon.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (!moonMeta) throw new Error(`plate ${opts.plate}: plate_fx.moon without moon.json (give hand.json "moon", then run plate_prep)`);
    tMoon = await load(`${dir}/moon.png`, true);
    tMoonFx = await load(`${dir}/moonfx.png`, false);
    moonAt = moonPath(opts.moon, moonMeta, opts.moon.period ?? ctx.timeline?.loop?.period ?? 1200);
    const D = moonMeta.halo.d, C = moonMeta.halo.rgb;
    haloStep = D[D.length - 1] / 23;
    halo.forEach((v, i) => {
      const d = i * haloStep;
      let j = 1;
      while (j < D.length - 1 && D[j] < d) j++;
      const f = Math.min(1, Math.max(0, (d - D[j - 1]) / Math.max(D[j] - D[j - 1], 1e-6)));
      v.set(...[0, 1, 2].map((c) => C[j - 1][c] + (C[j][c] - C[j - 1][c]) * f));
    });
  }
  // Other layers attach things to moving regions (drops along a swaying hem, runoff off a cloth): they read
  // where the warp moves the plate there each frame (this layer's animate runs first).
  ctx.regionMotion = regs.active ? regs : null;
  // Surf on a painted sea (opts.surf, scene.json plate_fx.surf): hand.json "surf" made plate_prep write surf.png
  // (cozy/plate/surf.py), bound where a waterfall's flow.png goes (the shader has no texture unit left); the waves are
  // the timeline's 'surf' events (scene.json events.surf)
  const sf = opts.surf ? { ...SURF, ...opts.surf } : null;
  let tFlowMap = tFlow;
  if (sf) {
    if (tFlow.image?.width > 1) throw new Error(`plate ${opts.plate}: plate_fx.surf on a plate with waterfalls (flow.png): they share a texture unit`);
    // how far the foam may come from at each pixel (surf_room.png), where the moon's map goes: unused without a moon
    if (opts.moon) throw new Error(`plate ${opts.plate}: plate_fx.surf and plate_fx.moon together: surf_room.png goes where moonfx.png goes`);
    try {
      tFlowMap = await load(`${dir}/surf.png`, false);
      tMoonFx = await load(`${dir}/surf_room.png`, false);
    } catch {
      throw new Error(`plate ${opts.plate}: plate_fx.surf without surf.png and surf_room.png (give hand.json "surf", then run plate_prep)`);
    }
  }
  const surfEvents = (ctx.timeline?.events ?? []).filter((e) => e.type === 'surf');
  if (sf && !surfEvents.length) console.warn('plate: plate_fx.surf but no surf waves in the timeline (scene.json events.surf)');
  const p = opts.pet ?? { cx: -1, cy: -1, rx: 0.01, ry: 0.01, base: 0 };
  // pet.png (plate_prep pet_map): the torso breathes over a still background; without it, the older soft ellipse
  const tPet = await loadOptional(p.map ? `${dir}/pet.png` : null);
  const lg = opts.lightning ?? {};
  const mat = new THREE.ShaderMaterial({
    vertexShader: plateVert,
    fragmentShader: plateFrag,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
    uniforms: {
      tPlate: { value: tPlate }, tDepth: { value: tDepth }, tMask: { value: tMask }, tLights: { value: tLights }, tFlash: { value: tFlash }, tBlur: { value: tBlur },
      tPlateOff: { value: tPlateOff }, tLightId: { value: tLightId }, tLightW: { value: tLightW }, uLevel: { value: new Float32Array(64).fill(1) },
      phase: { value: 0 },
      pet: { value: new THREE.Vector4(p.cx, 1 - p.cy, p.rx, p.ry) }, petBase: { value: 1 - p.base }, petAmp: { value: p.amp ?? 0.035 },
      tPet: { value: tPet }, uPetMap: { value: p.map ? 1 : 0 }, uPetMulti: { value: p.map && p.multi ? 1 : 0 }, petHMax: { value: p.hmax ?? 0.25 },
      mistAmt: { value: opts.mist ?? 0.22 }, swayAmt: { value: opts.sway ?? 0.0008 },
      rippleAmt: { value: opts.ripple ?? 0.0007 }, flickerAmt: { value: opts.flicker ?? 0.12 },
      rippleXY: { value: new THREE.Vector2(...(opts.rippleXY ?? [0.15, 1])) }, ringAmt: { value: new THREE.Vector2(...(opts.rings ?? [0.05, 0])) },
      mistCol: { value: new THREE.Color(opts.mistColor ?? '#2a3044') },
      black: { value: opts.debug === 'black' ? 1 : 0 },
      flash: { value: 0 }, flashUv: { value: new THREE.Vector2(0.5, 0.9) },
      flashCol: { value: new THREE.Color(lg.color ?? '#b9c8ff') },
      flashAmt: { value: new THREE.Vector4(lg.sky ?? 2.2, lg.land ?? 0.9, lg.roomNear ?? 0.45, lg.roomAmbient ?? 0.08) },
      farFlash: { value: 0 }, farUv: { value: new THREE.Vector2(0.5, 0.8) }, farCol: { value: new THREE.Color(lg.farColor ?? '#c9c4f2') },
      rainK: { value: 1 },
      earAP: { value: new THREE.Vector4() }, earBP: { value: new THREE.Vector4() },
      earAR: { value: new THREE.Vector4() }, earBR: { value: new THREE.Vector4() },
      tailP: { value: new THREE.Vector4() }, tailR: { value: new THREE.Vector2() }, breathK: { value: 1 },
      flurry: { value: new THREE.Vector2() },
      tFlow: { value: tFlowMap }, flowAmt: { value: opts.waterfall ?? 0.22 },
      waterCam: { value: new THREE.Vector4() }, waterFlow: { value: new THREE.Vector4() }, waterGust: { value: new THREE.Vector4() },
      waterRough: { value: 0 },
      tRegion: { value: tRegion ?? tFlow }, tReg: { value: regs.tex }, uRegions: { value: regs.active && tRegion ? 1 : 0 },
      tRefl: { value: tRefl },
      uSpill: { value: regs.spill }, uSpillN: { value: 0 },
      gRain: { value: new THREE.Vector4(opts.ground ? 1 : 0, opts.ground?.horizon ?? opts.horizon ?? 0.45, opts.ground?.focal ?? 2700, opts.ground?.growth ?? 0.16) },
      gRing: { value: new THREE.Vector4(opts.ground?.refract ?? 8, opts.ground?.highlight ?? 0.7, opts.ground?.cells ?? 24, opts.ground?.density ?? 0.85) },
      gWet: { value: 0 }, uLoopS: { value: ctx.loopSeconds },
      tMoon: { value: tMoon }, tMoonFx: { value: tMoonFx }, uMoon: { value: new THREE.Vector4() }, uMoonK: { value: new THREE.Vector4() },
      uGlitC: { value: new THREE.Vector3(...(moonMeta?.glitter?.rgb ?? [1, 1, 1])) },
      uHalo: { value: halo }, uMoonHS: { value: haloStep },
      uMoonSpr: { value: moonMeta ? (moonMeta.sprite[2] - moonMeta.sprite[0]) / 2 : 64 },
      uMoonCloud: { value: opts.moon?.clouds === false ? 0 : 1 },
      uSurfOn: { value: sf ? 1 : 0 },
      uSurfW: { value: Array.from({ length: 4 }, () => new THREE.Vector4()) },
      uSurfK: { value: new THREE.Vector4(sf?.rest ?? 0, sf?.travel ?? 1, sf?.peel ?? 0, sf?.decay ?? 1) },
      uSurfD: { value: new THREE.Vector4(sf?.push ?? 0, sf?.swell ?? 0, sf?.peak ?? 1, 0) },
      dbgMode: { value: { water: 1, off: 2, raw: 3, black: 4 }[ctx.params?.plate] ?? 0 },
    },
  });
  // Water ripples in world space through the lake camera (opts.water = { camera, flow: [[x, y] upstream,
  // [x, y] downstream] (image points on the river), sway: [horizontal, vertical] px at 4K, rough: px in gusts }).
  const wv = opts.water;
  if (wv?.camera) {
    const cam = lakeCamera(wv.camera);
    const [a, b] = (wv.flow ?? [[0.5, 0.55], [0.5, 0.7]]).map(([x, y]) => cam.toWater(x, y));
    const dx = b[0] - a[0], dz = b[2] - a[2], n = Math.hypot(dx, dz) || 1;
    const [sh, sv] = wv.sway ?? [2, 4];
    mat.uniforms.waterCam.value.set(cam.F, wv.camera.horizon ?? 0.453, wv.camera.height ?? 16, 1);
    mat.uniforms.waterFlow.value.set(dx / n, dz / n, sh, sv);
    mat.uniforms.waterRough.value = wv.rough ?? 6;
  }
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const L = ctx.loopSeconds;
  // Pet rig (image coords, y down -> uv y up): ears rotate about their base, tail tip lifts.
  const rig = opts.petRig ?? null;
  const U = (p) => [p[0], 1 - p[1]];
  // While a behavior clip plays over the pet (pet.js, 'petact' events), the plate's own pet holds still, so
  // nothing of it can peek out around the clip; breathing fades out before the act and back in after it.
  const acts = (ctx.timeline?.events ?? []).filter((e) => e.type === 'petact');
  const actQuiet = (t) => {
    let k = 1;
    for (const e of acts) {
      if (t < e.t - 0.8 || t > e.t + e.dur + 0.8) continue;
      const u = t < e.t ? (e.t - t) / 0.8 : t > e.t + e.dur ? (t - e.t - e.dur) / 0.8 : 0;
      k = Math.min(k, u * u * (3 - 2 * u));
    }
    return k;
  };
  if (rig?.earA) mat.uniforms.earAP.value.set(...U(rig.earA.pivot), ...U(rig.earA.center)), mat.uniforms.earAR.value.set(...rig.earA.radius, 0, 0);
  if (rig?.earB) mat.uniforms.earBP.value.set(...U(rig.earB.pivot), ...U(rig.earB.center)), mat.uniforms.earBR.value.set(...rig.earB.radius, 0, 0);
  if (rig?.tail) mat.uniforms.tailP.value.set(...U(rig.tail.base), ...U(rig.tail.tip)), mat.uniforms.tailR.value.set(rig.tail.halfWidth, 0);
  ctx.animate((t) => {
    const u = mat.uniforms;
    u.phase.value = (t % L) / L;
    const f = flashAt(ctx.timeline, t);
    u.flash.value = opts.debug === 'black' ? 0 : f.flash;
    u.flashUv.value.set(f.x, 1 - f.y);
    u.farFlash.value = opts.debug === 'black' ? 0 : f.far;
    u.farUv.value.set(f.fx, 1 - f.fy);
    u.rainK.value = trackAt(ctx.timeline?.track, 'rain', t);
    if (opts.ground) u.gWet.value = Math.min(1, (opts.ground.density ?? 0.85) * u.rainK.value);
    if (ctx.timeline) u.uLevel.value = lightLevels(ctx.timeline, t, 64);
    const fe = flurryEnv(ctx.timeline, t), fw = flurryWind(ctx.timeline, t);
    u.flurry.value.set(fe, Math.sign(fw) * fe);
    if (regs.active) {
      regs.update(t, fe, (name, tt) => regionDip(ctx.timeline, name, tt));
      u.uSpillN.value = opts.debug === 'black' ? 0 : regs.spillN;
    }
    if (wv?.camera) {
      // Gust patch: sweeps 70 m across the river downwind over the gust, strongest at its peak.
      const [s0, dur, amp] = flurryUniform(ctx.timeline, t);
      const on = amp !== 0 && s0 >= 0 && s0 <= dur;
      const sgn = Math.sign(amp) || 1;
      u.waterGust.value.set(on ? sgn * (-35 + (70 * s0) / dur) : 0, on ? fe : 0, sgn, on ? s0 : 0);
    }
    if (rig) {
      const s = petState(ctx.timeline, t);
      u.earAR.value.z = rig.earA ? -s.earA * rig.earA.angle : 0;
      u.earBR.value.z = rig.earB ? -s.earB * rig.earB.angle : 0;
      u.tailR.value.y = rig.tail ? s.tail * rig.tail.lift : 0;
      u.breathK.value = s.breath;
    } else if (ctx.timeline?.pet?.length && !(p.map && p.multi)) {
      // sighs (one pet); several characters never sigh all at once, which reads as staged: they just breathe
      u.breathK.value = petState(ctx.timeline, t).breath;
    }
    if (acts.length) u.breathK.value *= actQuiet(t);
    if (moonAt) {
      const m = moonAt(t);
      u.uMoon.value.set(m.x, 1 - m.y, moonMeta.half[0], moonMeta.half[1]);
      u.uMoonK.value.set(opts.debug === 'black' ? 0 : m.vis, opts.moon.halo ?? 1, moonMeta.glitter ? (opts.moon.glitter ?? 1) * m.vis : 0,
        m.x - moonMeta.center[0] / 3840);
    }
    if (sf) surfWaves(surfEvents, t, 4, u.uSurfW.value, sf.lead ?? 0);
    // a layer showing the pet in another pose over it (petsprite.js) holds the painted pet still: its breath lifted the
    // painted back above the empty mat drawn over it (round 6, an orange line behind the dog lying back down).
    // petHold: 0..1, eased in before it wakes and out after it falls asleep, so the breath never stops with a jump
    if (ctx.petHold) u.breathK.value *= 1 - ctx.petHold(t);
  });
  return mesh;
}
