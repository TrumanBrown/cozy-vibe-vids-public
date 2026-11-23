// Copies of helpers that src/ used to write more than once (TASKS.md T20), kept here as they were, compared with the
// one version src/ uses now over many inputs. Writes JSON to the file given as the first argument:
//   {"rng": {"<copy>": {"<seed class>": {"seeds": n, "differ": k, "example": ...}}}, "hash": {...}, "same": {...},
//    "shared": {"<helper>": {"inputs": n, "differ": k, "example": ...}}}
// Used by tests/test_js_helpers.py.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const R = await imp('src/engine/rng.js');
const out = { rng: {}, hash: {}, same: {} };

// ---- mulberry32, as each copy was before it pointed at engine/rng.js ----

// src/library/timeline.js: signed state and no `>>> 0` on the seed
function timelineMulberry32(a) {
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// src/library/fire.js, particles.js and rain.js (the same text in all three): unsigned state
function layerRng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// src/library/petsprite.js (`rand` in petSpriteLayer): unsigned state
const petspriteRand = (seed) => {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let q = Math.imul(s ^ (s >>> 15), 1 | s);
    q = (q + Math.imul(q ^ (q >>> 7), 61 | q)) ^ q;
    return ((q ^ (q >>> 14)) >>> 0) / 4294967296;
  };
};

// src/library/timeline.js
function timelineHashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// Test seeds, drawn from a fixed stream so every run checks the same ones.
const draw = R.mulberry32(20261026);
const many = (n, f) => Array.from({ length: n }, () => f(draw()));
const frac = () => 0.001 + 0.998 * draw();   // a fractional part that is never 0
const P32 = 2 ** 32, P52 = 2 ** 52, P53 = 2 ** 53;
// The timeline's call sites: every seed is `(Math.imul(seed, K) ^ hashStr(key)) >>> 0`, `ev.seed >>> 0` or
// `(f.seed ^ hashStr(key)) >>> 0`, so a uint32. These are the ones a scene seed of 1 to 300 gives.
const KEYS = ['lightning', 'pet', 'rare', 'rare-dir', 'perchStart', 'perchReturn', 'boat-ambient', 'nightlights', 'windows', 'leaves',
  'weather', 'fish', 'flurry', 'farflash', 'neon', 'gutter', 'car', 'ember', 'star', 'birds', 'critter', 'critter1', 'ant', 'perch', 'moth',
  'petact', 'petals-tree', 'petals-near', 'flurry-leaves', 'flurry-petals'];
const MULS = [2654435761, 668265263, 2246822519, 1597334677, 1103515245, 3266489917, 2654435789];
const callSites = [];
for (let seed = 1; seed <= 300; seed++) for (const k of MULS) for (const key of KEYS) callSites.push((Math.imul(seed, k) ^ timelineHashStr(key)) >>> 0);
callSites.push(...many(3000, (u) => Math.floor(u * 2147483647) >>> 0));   // event seeds (ev.seed >>> 0)
const SEEDS = {
  integer: [0, 1, 2, 7, 42, 12345, 2 ** 31 - 1, 2 ** 31, P32 - 1, ...Array.from({ length: 1000 }, (_, i) => i), ...many(3000, (u) => Math.floor(u * P32))],
  negative: [-1, -7, -12345, -(2 ** 31), -(2 ** 31) - 1, -(P32 - 1), -P32, -P52, ...Array.from({ length: 1000 }, (_, i) => -i - 1), ...many(3000, (u) => -Math.floor(u * P52))],
  huge: [P32, P32 + 1, 2 ** 40 + 123, P52, P52 - 1, ...many(3000, (u) => P32 + Math.floor(u * (P52 - P32)))],
  beyond_2_53: [P53 - 2, P53 + 2, 2 ** 60, 1e20, -(2 ** 60), ...many(1000, (u) => P53 - 2 ** 31 + Math.floor(u * 2 ** 32)), ...many(1000, (u) => P53 * (1 + 1000 * u))],
  fractional: [0.5, 1.25, 7.9, 12345.678, 2 ** 31 + 0.5, 1e10 + 0.25, ...many(3000, (u) => Math.floor(u * 1000) + frac()), ...many(3000, (u) => Math.floor(u * P32) + frac())],
  negative_fractional: [-0.5, -1.25, -7.9, -12345.678, -(2 ** 31) - 0.5, -1e10 - 0.25, ...many(3000, (u) => -Math.floor(u * 1000) - frac()),
    ...many(3000, (u) => -Math.floor(u * P32) - frac())],
  not_a_number: [NaN, undefined, null, Infinity, -Infinity],
  timeline_call_sites: callSites,
};

const DRAWS = 40;
const seq = (make, seed) => { const r = make(seed); return Array.from({ length: DRAWS }, () => r()); };
for (const [copy, make] of [['timeline', timelineMulberry32], ['fire_particles_rain', layerRng], ['petsprite', petspriteRand]]) {
  out.rng[copy] = {};
  for (const [cls, seeds] of Object.entries(SEEDS)) {
    let differ = 0, example = null;
    for (const s of seeds) {
      const a = seq(make, s), b = seq(R.mulberry32, s);
      if (a.some((v, i) => v !== b[i])) { differ++; example ??= { seed: String(s), copy: a.slice(0, 2), rng_js: b.slice(0, 2) }; }
    }
    out.rng[copy][cls] = { seeds: seeds.length, differ, example };
  }
}

// ---- hashStr (timeline) against rng.js hashString ----
const strings = ['', 'a', ...KEYS, 'treetop', 'ramen-alley', 'é', 'Ω', '\u{1F35C}', 'a\u0000b', 'x'.repeat(10000),
  ...many(2000, (u) => Array.from({ length: 1 + Math.floor(u * 40) }, () => String.fromCharCode(32 + Math.floor(draw() * 95))).join('')),
  ...many(500, (u) => Array.from({ length: 1 + Math.floor(u * 12) }, () => String.fromCharCode(Math.floor(draw() * 65536))).join(''))];
let hd = 0, hex = null;
for (const s of strings) if (timelineHashStr(s) !== R.hashString(s)) { hd++; hex ??= s; }
out.hash = { strings: strings.length, differ: hd, example: hex };

// ---- what src/ uses now ----
const T = await imp('src/library/timeline/random.js');
out.same.timeline_mulberry32_is_rng_js = T.mulberry32 === R.mulberry32;
out.same.timeline_hashStr_is_rng_js = T.hashStr === R.hashString;
const copies = [];
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));
for (const f of walk(path.join(root, 'src')).filter((f) => /\.m?js$/.test(f))) {
  const rel = path.relative(root, f).split(path.sep).join('/');
  if (rel !== 'src/engine/rng.js' && /0x6d2b79f5/i.test(fs.readFileSync(f, 'utf8'))) copies.push(rel);
}
out.same.mulberry32_written_outside_rng_js = copies;

// ---- helpers shared through src/library/util.js and overlay.js, each copy as it was ----

// smooth: timeline.js and title.js (the same text), perch.js (through its clamp01)
const smoothTimeline = (x) => { const s = Math.min(Math.max(x, 0), 1); return s * s * (3 - 2 * s); };
const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
const smoothPerch = (x) => { const s = clamp01(x); return s * s * (3 - 2 * s); };
// toLin: leaves.js, moth.js and petals.js (the same text)
const toLinCopy = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
// hash: blink.js adds b as it is, perch.js takes both inputs `| 0`
const hashBlink = (a, b) => {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
};
function hashPerch(a, b) {
  let h = Math.imul((a | 0) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul((b | 0) + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
// avg: cat3d.js and dog3d.js (the same code over the layer's blur, lin, W and H)
const avgCopy = (blur, W, H) => {
  const lin = (v) => Math.pow(v / 255, 2.2);
  return (x0, y0, x1, y1) => {
    const s = [0, 0, 0];
    let n = 0;
    for (let j = 0; j < 6; j++) {
      for (let i = 0; i < 6; i++) {
        const x = Math.round(((x0 + ((x1 - x0) * (i + 0.5)) / 6) * blur.width) / W), y = Math.round(((y0 + ((y1 - y0) * (j + 0.5)) / 6) * blur.height) / H);
        if (x < 0 || y < 0 || x >= blur.width || y >= blur.height) continue;
        const q = (y * blur.width + x) * 4;
        s[0] += lin(blur.data[q]); s[1] += lin(blur.data[q + 1]); s[2] += lin(blur.data[q + 2]); n++;
      }
    }
    return n ? s.map((v) => v / n) : [0.05, 0.05, 0.05];
  };
};
// pixelsOf: cat3d.js and dog3d.js (the same code)
async function pixelsOf(url) {
  const r = await fetch(url).catch(() => null);
  if (!r?.ok) return null;
  const bmp = await createImageBitmap(await r.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const c = new OffscreenCanvas(bmp.width, bmp.height);
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(bmp, 0, 0);
  return { data: g.getImageData(0, 0, bmp.width, bmp.height).data, width: bmp.width, height: bmp.height };
}

const THREE = await import('three');
// quad: particles.js quad(n) and steam.js quadGeo(n) (the same code); rain.js quad(), whose callers set instanceCount
function quadParticles(n) {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = n;
  return g;
}
function quadRain() {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  return g;
}
// dirLight: cat3d.js and dog3d.js (the same code over the layer's scene3)
const dirLightCopy = (scene3) => (o, def) => {
  const l = new THREE.DirectionalLight(o?.color ?? def.color, o?.intensity ?? def.intensity);
  l.position.set(...(o?.dir ?? def.dir).map((v) => v * 100));
  scene3.add(l);
  return l;
};
// loadTex: boat.js and heron.js (the same code), fish.js, leaves.js (no default for srgb) and rain.js (also clamps)
async function loadTexBoat(url, { srgb = false, mips = false } = {}) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = mips;
  t.minFilter = mips ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  return t;
}
async function loadTexFish(url, srgb = false) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = false;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  return t;
}
async function loadTexLeaves(url, srgb) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = false;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  return t;
}
async function loadTexRain(url, srgb = false) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = false;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

const U = await imp('src/library/util.js');
const OV = await imp('src/library/overlay.js');
const cmp = (pairs) => {
  let differ = 0, example = null;
  for (const [what, a, b] of pairs) {
    const x = JSON.stringify(a, (k, v) => (typeof v === 'number' && !Number.isFinite(v) ? String(v) : Object.is(v, -0) ? '-0' : v));
    const y = JSON.stringify(b, (k, v) => (typeof v === 'number' && !Number.isFinite(v) ? String(v) : Object.is(v, -0) ? '-0' : v));
    if (x !== y) { differ++; example ??= { what: String(what), copy: x.slice(0, 200), shared: y.slice(0, 200) }; }
  }
  return { inputs: pairs.length, differ, example };
};
out.shared = {};
const xs = [-Infinity, -1e9, -1, -0.5, -0, 0, 1e-12, 0.04045, 0.25, 0.5, 0.75, 1, 1.5, 1e9, Infinity, NaN, ...many(20000, (u) => -2 + 5 * u)];
out.shared.smooth_timeline_title = cmp(xs.map((x) => [x, smoothTimeline(x), U.smooth(x)]));
out.shared.smooth_perch = cmp(xs.map((x) => [x, smoothPerch(x), U.smooth(x)]));
out.shared.smooth_timeline_module = { same: (await imp('src/library/timeline/random.js')).smooth === U.smooth };
const cs = [-1, -0.5, -0, 0, 0.04, 0.04045, 0.0404500001, 0.05, 0.5, 1, 2, NaN, Infinity, ...many(20000, (u) => -0.5 + 2 * u), ...Array.from({ length: 256 }, (_, i) => i / 255)];
out.shared.toLin_leaves_moth_petals = cmp(cs.map((c) => [c, toLinCopy(c), U.toLin(c)]));
// hash inputs: a any number (a seed times a constant), b an integer: blink.js passes a character index and slot
// numbers, perch.js loop counters plus 1000, 2000 or 3000
const as = [0, 1, -1, 7 * 7919, 2 ** 31 - 1, -(2 ** 31), 2 ** 40 + 5, 1e15, 12.5, -12.5, -0.5, ...many(300, (u) => Math.floor(u * P32)), ...many(100, (u) => (u - 0.5) * 1e6)];
const bs = [0, 1, 2, 999, 1000, 3000, 3999, -1, -40, 2 ** 31 - 1, -(2 ** 31), ...many(300, (u) => Math.floor((u - 0.5) * 2e6))];
const pairs = as.flatMap((a) => bs.map((b) => [a, b]));
out.shared.hash_perch = cmp([...pairs, ...as.map((a) => [a, -0.5]), ...as.map((a) => [a, NaN])].map(([a, b]) => [`${a},${b}`, hashPerch(a, b), U.hash(a, b)]));
out.shared.hash_blink_integer_b = cmp(pairs.map(([a, b]) => [`${a},${b}`, hashBlink(a, b), U.hash(a, b)]));
out.shared.hash_blink_negative_fractional_b = cmp(as.flatMap((a) => [-0.5, -1.25, -999.5].map((b) => [`${a},${b}`, hashBlink(a, b), U.hash(a, b)])));
// avg over random images and boxes inside, across and outside the frame (px of a 3840 x 2160 frame)
const images = [[1, 1], [7, 5], [64, 36], [383, 216], [960, 540]].map(([w, h]) => ({ width: w, height: h, data: Uint8ClampedArray.from({ length: w * h * 4 }, () => Math.floor(draw() * 256)) }));
const boxes = [[0, 0, 3840, 2160], [100, 100, 100, 100], [3000, 2000, 100, 50], [-500, -300, 200, 100], [3800, 2100, 4400, 2500], [-900, -900, -100, -100],
  ...many(400, (u) => [u * 4400 - 300, draw() * 2600 - 200, draw() * 4400 - 300, draw() * 2600 - 200])];
out.shared.avg_cat3d_dog3d = cmp(images.flatMap((img) => { const a = avgCopy(img, 3840, 2160), b = OV.boxMean(img, 3840, 2160); return boxes.map((bx) => [`${img.width}x${img.height} ${bx}`, a(...bx), b(...bx)]); }));
out.shared.pixelsOf_is_imagePixels_text = pixelsOf.toString().replace('function pixelsOf', 'function imagePixels') === OV.imagePixels.toString();
const geo = (g) => ({
  type: g.type, attrs: Object.keys(g.attributes), pos: Array.from(g.attributes.position.array), itemSize: g.attributes.position.itemSize,
  normalized: g.attributes.position.normalized, usage: g.attributes.position.usage, index: Array.from(g.index.array), indexType: g.index.array.constructor.name,
  instanceCount: g.instanceCount, drawRange: g.drawRange, groups: g.groups, morph: Object.keys(g.morphAttributes),
});
const ns = [0, 1, 2, 7, 64, 1000, 30000, 123457];
out.shared.quad_particles_steam = cmp(ns.map((n) => [n, geo(quadParticles(n)), geo(OV.instancedQuad(n))]));
out.shared.quad_rain = cmp(ns.map((n) => { const g = quadRain(); g.instanceCount = n; return [n, geo(g), geo(OV.instancedQuad(n))]; }));
const light = (s, l) => ({ n: s.children.length, type: l.type, color: l.color.toArray(), intensity: l.intensity, pos: l.position.toArray(), target: l.target.position.toArray(),
  shadow: l.castShadow, parent: l.parent === s });
const defs = [{ color: '#ffb066', intensity: 2.4, dir: [-0.45, 0.75, -0.35] }, { color: '#ffc884', intensity: 0.8, dir: [0.6, 0.5, 0.4] },
  { color: '#ffb066', intensity: 2.4, dir: [-0.5, 0.7, 0.4] }, { color: '#9fb8ff', intensity: 0.5, dir: [0.6, 0.5, -0.5] }];
const os = [undefined, null, {}, { color: '#203040' }, { intensity: 3.3 }, { dir: [0.1, -0.2, 0.3] }, { color: 0x405060, intensity: 0, dir: [0, 0, 0] }];
out.shared.dirLight_cat3d_dog3d = cmp(defs.flatMap((def) => os.map((o) => {
  const s1 = new THREE.Scene(), s2 = new THREE.Scene();
  return [JSON.stringify(o), light(s1, dirLightCopy(s1)(o, def)), light(s2, OV.dirLight(s2, o, def))];
})));
// loadTex with the image load left out (a fresh Texture, as TextureLoader makes): the settings each layer gets
const loadAsync = THREE.TextureLoader.prototype.loadAsync;
THREE.TextureLoader.prototype.loadAsync = async () => new THREE.Texture();
const tex = (t) => ({
  colorSpace: t.colorSpace, generateMipmaps: t.generateMipmaps, minFilter: t.minFilter, magFilter: t.magFilter, wrapS: t.wrapS, wrapT: t.wrapT,
  flipY: t.flipY, premultiplyAlpha: t.premultiplyAlpha, anisotropy: t.anisotropy, format: t.format, type: t.type, mapping: t.mapping,
  unpackAlignment: t.unpackAlignment, version: t.version, offset: t.offset.toArray(), repeat: t.repeat.toArray(), rotation: t.rotation,
});
const texPairs = [];
for (const o of [undefined, {}, { srgb: true }, { mips: true }, { srgb: true, mips: true }]) texPairs.push([`boat ${JSON.stringify(o)}`, tex(await loadTexBoat('x', o)), tex(await OV.loadTex('x', o))]);
for (const [name, f] of [['fish', loadTexFish], ['leaves', loadTexLeaves], ['rain', loadTexRain]]) {
  for (const srgb of [false, true]) texPairs.push([`${name} ${srgb}`, tex(await f('x', srgb)), tex(await OV.loadTex('x', { srgb }))]);
  texPairs.push([`${name} default`, tex(await f('x')), tex(await OV.loadTex('x'))]);
}
THREE.TextureLoader.prototype.loadAsync = loadAsync;
out.shared.loadTex = cmp(texPairs);

fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
