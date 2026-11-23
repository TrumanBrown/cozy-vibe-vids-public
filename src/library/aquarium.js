// A glass tank built into the wall, alive (Truman 2026-11-22, the Enchanter's Tower: an aquarium with blocky tropical
// fish, an axolotl, kelp and bubbles, one of the movers he picked for the room).
//
// The tank is the painted one. Its front glass is a quad on the plate (tank.quad: the near end's top, the far end's top,
// the far end's bottom, the near end's bottom, px at 4K); its inside reaches back into the wall, which faces the room's
// middle, so going deeper into it is going left across the view (tank.depth: the tank's depth in blocks; tank.height: its
// height). Tank coordinates: u along it from the near end to the far one, v up from the bottom of the glass, w from the
// front glass to the back. A point maps to the screen through the quad's homography (u, v) and a shift to the left for w,
// and whatever is in the tank is sized by the quad's height there (px per block).
//
// In it: blocky tropical fish of our own (boxes in code, two body shapes, two-color patterns), each on its own slow
// closed path (whole cycles per loop), heading along its way and turning where it reverses, its tail beating harder the
// faster it swims; an axolotl that rests on the sand breathing, its gills stirring, and now and then swims a slow lap and
// settles somewhere else; a stream of bubbles from the sand, wobbling up and bursting at the surface; light from the
// surface rippling over the sand and the plants. Fish deeper than the plants go behind them (the painting's plants, coral
// and sand, found by color: whatever isn't the water's blue), nearer ones swim in front; everything stays behind the
// front glass's bright edges and behind what stands in front of the tank (tank.front: region names, e.g. the brewing
// stand); each fish is tinted toward the water's own color the deeper it swims. Lit by a near-white lamp over the water
// and the room's light through the glass.
//
// opts: { plate, tank: { quad, height (blocks, 3), depth (blocks, 1.2), length (blocks, 3), floor: [[u, v], ...] (the
//   sand's top along it), surface (v, 0.9), front: [region names] }, fish: n (5), axolotl: { spots: [[u, w] or [u, w, v],
//   ...], scale } | false, bubbles: { at: [u, w], rate (per s, 2.5), size: [px, px] } | false, caustics (0.07), ambient
//   (1.2), key (1.8), fill (0.6), focal (px, 1600), horizon (px, 1060), renderOrder (7) }
import * as THREE from 'three';
import { plateTexture, plateRegions, imagePixels, boxMean, instancedQuad, GLSL_COMMON, PREMUL, ADDITIVE } from './overlay.js';
import { boxMaterials, hash3 } from './boxart.js';
import { mulberry32 } from '../engine/rng.js';
import { smooth } from './util.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;

// ------------------------------------------------------------------ the tank's geometry
// The projective map of the unit square onto the quad: (u, v) = (0, 0) near bottom, (1, 0) far bottom, (1, 1) far top,
// (0, 1) near top. Returns the 3 x 3 matrix (row-major) and the map.
export function tankMap(tank) {
  const [nt, ft, fb, nb] = tank.quad;
  const [x0, y0] = nb, [x1, y1] = fb, [x2, y2] = ft, [x3, y3] = nt;
  const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (dx3 * dy2 - dx2 * dy3) / den, h = (dx1 * dy3 - dx3 * dy1) / den;
  const M = [x1 - x0 + g * x1, x3 - x0 + h * x3, x0, y1 - y0 + g * y1, y3 - y0 + h * y3, y0, g, h, 1];
  const F = (u, v) => {
    const z = M[6] * u + M[7] * v + 1;
    return [(M[0] * u + M[1] * v + M[2]) / z, (M[3] * u + M[4] * v + M[5]) / z];
  };
  const Ht = tank.height ?? 3, Dt = tank.depth ?? 1.2;
  const tall = (u) => { const a = F(u, 0), b = F(u, 1); return Math.hypot(b[0] - a[0], b[1] - a[1]); };
  const ppb = (u) => tall(u) / Ht;                         // px per block at u
  const at = (u, v, w) => { const p = F(u, v); return [p[0] - w * Dt * ppb(u), p[1], ppb(u)]; };
  const fl = tank.floor ?? [[0, 0.1], [1, 0.1]];
  const floor = (u) => {
    for (let i = 1; i < fl.length; i++) if (u <= fl[i][0]) return fl[i - 1][1] + (fl[i][1] - fl[i - 1][1]) * (u - fl[i - 1][0]) / Math.max(1e-6, fl[i][0] - fl[i - 1][0]);
    return fl[fl.length - 1][1];
  };
  return { M, F, at, ppb, floor, Ht, Dt, Lt: tank.length ?? 3 };
}

// ------------------------------------------------------------------ the fish
const FISH = [
  { body: '#f07c22', band: '#f6f2ea', fin: '#ea6a1c', edge: '#2a1f1c', shape: 'slim', pattern: 'bands' },
  { body: '#2f62d6', band: '#141b38', fin: '#f2c232', edge: '#141b38', shape: 'tall', pattern: 'stripe' },
  { body: '#f3d53c', band: '#fbf2c4', fin: '#efbf22', edge: '#8a6a1a', shape: 'tall', pattern: 'belly' },
  { body: '#d23a35', band: '#f3efe8', fin: '#cf3732', edge: '#3a1a1a', shape: 'slim', pattern: 'bands' },
  { body: '#3fb9a6', band: '#d4ea74', fin: '#2f9e8d', edge: '#1d4f47', shape: 'slim', pattern: 'spots' },
  { body: '#a868d8', band: '#f4a6cf', fin: '#9455c4', edge: '#3d2457', shape: 'tall', pattern: 'belly' },
];

// a fish 16 units a block, nose toward +z: a body, a tail fin on a joint, a dorsal fin, two small side fins, eyes
function buildFish(pal, id) {
  const slim = pal.shape === 'slim';
  const [bw, bh, bl] = slim ? [1.4, 2.6, 5.4] : [1.2, 3.8, 4.4];
  const T = 2;
  const paint = (p, f) => {
    const z = p[2], y = p[1];
    // eyes on the sides, near the nose and high
    if ((f === 0 || f === 1) && z > bl / 2 - 1.2 && z < bl / 2 - 0.5 && y > bh * 0.05 && y < bh * 0.05 + 0.7) return '#121212';
    if (f === 4) return pal.edge;                                   // the snout
    if (pal.pattern === 'bands' && ((z > 0.9 && z < 1.6) || (z > -1.4 && z < -0.8))) return pal.band;
    if (pal.pattern === 'stripe' && y > -0.2 && y < 0.7 && z < bl / 2 - 1.3) return pal.band;
    if (pal.pattern === 'belly' && y < -bh * 0.18) return pal.band;
    if (pal.pattern === 'spots' && hash3(Math.floor(z * 2 + 20), Math.floor(y * 2 + 20), f) > 0.72) return pal.band;
    return pal.body;
  };
  const box = (size, fn, k) => new THREE.Mesh(new THREE.BoxGeometry(...size), boxMaterials(size, T, fn, id * 10 + k, { grain: 0.08, roughness: 0.55 }));
  const root = new THREE.Group();
  root.add(box([bw, bh, bl], paint, 1));
  const tail = new THREE.Group();
  tail.position.set(0, 0, -bl / 2);
  root.add(tail);
  const fin = box([0.3, slim ? 2.6 : 3.2, 1.7], (p) => (p[2] < -0.5 ? pal.edge : pal.fin), 2);
  fin.position.set(0, 0, -0.85);
  tail.add(fin);
  const dorsal = box([0.3, slim ? 1.0 : 1.4, bl * 0.55], () => pal.fin, 3);
  dorsal.position.set(0, bh / 2 + (slim ? 0.45 : 0.6), -0.2);
  root.add(dorsal);
  if (!slim) {
    const ventral = box([0.3, 1.1, bl * 0.4], () => pal.fin, 4);
    ventral.position.set(0, -bh / 2 - 0.5, -0.3);
    root.add(ventral);
  }
  const pecs = [1, -1].map((s) => {
    const g = new THREE.Group();
    g.position.set(s * bw / 2, -bh * 0.15, bl * 0.15);
    const m = box([0.2, 0.7, 1.0], () => pal.fin, 5);
    m.position.set(s * 0.1, 0, -0.5);
    g.add(m);
    root.add(g);
    return g;
  });
  return { root, tail, pecs, len: bl + 1.7 };
}

// The axolotl, 16 units a block, nose toward +z: a pink body, a wide head with three frilly gills a side, four short legs,
// a long flat tail fin in two joints.
const AXO = { body: '#f3b2c4', spot: '#e595ad', belly: '#f9d0db', gill: '#cf4d74', gillTip: '#e8789a', eye: '#161616', mouth: '#b7607a' };
function buildAxolotl() {
  const T = 2;
  const box = (size, fn, k) => new THREE.Mesh(new THREE.BoxGeometry(...size), boxMaterials(size, T, fn, 300 + k, { grain: 0.07, roughness: 0.6 }));
  const skin = (p, f) => (f === 3 ? AXO.belly : hash3(Math.floor(p[0] * 2 + 30), Math.floor(p[2] * 2 + 30), f) > 0.86 ? AXO.spot : AXO.body);
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  body.add(box([6, 3.6, 9], skin, 1));
  const head = new THREE.Group();
  head.position.set(0, 0.4, 4.5);
  body.add(head);
  const hd = box([7, 4.2, 4.6], (p, f) => {
    if ((f === 0 || f === 1) && p[2] > 0.6 && p[2] < 1.6 && p[1] > 0.2 && p[1] < 1.1) return AXO.eye;
    if (f === 4 && p[1] < -0.6 && p[1] > -1.1 && Math.abs(p[0]) < 2.4) return AXO.mouth;
    return skin(p, f);
  }, 2);
  hd.position.set(0, 0, 2.3);
  head.add(hd);
  const gills = [];
  for (const s of [1, -1]) {
    for (let k = 0; k < 3; k++) {
      const g = new THREE.Group();
      g.position.set(s * 3.4, 1.0 + 0.9 * k - 0.6, 1.6 - 0.3 * k);
      g.rotation.z = -s * (0.5 + 0.35 * k);
      const stalk = box([0.6, 3.0, 0.6], (p) => (p[1] > 0.6 ? AXO.gillTip : AXO.gill), 3 + k);
      stalk.position.set(0, 1.5, 0);
      g.add(stalk);
      for (let j = 0; j < 3; j++) {
        const fr = box([0.4, 0.5, 1.2], () => AXO.gillTip, 6 + j);
        fr.position.set(0, 0.6 + 0.9 * j, -0.6);
        g.add(fr);
      }
      head.add(g);
      gills.push({ g, s, k, base: g.rotation.z });
    }
  }
  const legs = [[1, 3], [-1, 3], [1, -3], [-1, -3]].map(([s, z], i) => {
    const g = new THREE.Group();
    g.position.set(s * 3, -1.2, z);
    const m = box([1.4, 3.2, 1.4], skin, 10 + i);
    m.position.set(s * 0.4, -1.4, 0);
    g.add(m);
    body.add(g);
    return { g, s, front: z > 0 };
  });
  const tail1 = new THREE.Group();
  tail1.position.set(0, 0.2, -4.5);
  body.add(tail1);
  const t1 = box([1.2, 4.6, 6], (p) => (Math.abs(p[1]) > 1.4 ? AXO.spot : AXO.body), 20);
  t1.position.set(0, 0, -3);
  tail1.add(t1);
  const tail2 = new THREE.Group();
  tail2.position.set(0, 0, -6);
  tail1.add(tail2);
  const t2 = box([0.8, 3.6, 5], (p) => (Math.abs(p[1]) > 1.0 ? AXO.spot : AXO.body), 21);
  t2.position.set(0, 0, -2.5);
  tail2.add(t2);
  return { root, body, head, gills, legs, tail1, tail2, len: 24 };
}

// ------------------------------------------------------------------ where they are
// A fish's state at loop time t: tank position (u, v, w), its heading in the world (unit vector: x right, y up, z toward
// the camera) and its speed (blocks/s). It swims slow laps of the tank: along it and back on an ellipse that runs from
// the front glass to the back round the turns (u and w on one whole-cycle sine a quarter turn apart, so it never stops
// and its heading turns smoothly round the ends; a fish going back and forth along a line flipped about at each end),
// rising and sinking on its own slower beat. All whole cycles a loop.
export function fishAt(f, t, map) {
  const pos = (tt) => {
    const ph = f.wu * tt + f.pu;
    const u = f.u0 + f.au * Math.sin(ph);
    const w = f.w0 + f.dir * f.aw * Math.cos(ph);
    const v = f.v0 + f.av * Math.sin(f.wv * tt + f.pv);
    return [u, Math.max(map.floor(u) + f.clear, Math.min(f.top, v)), w];
  };
  const a = pos(t - 0.05), b = pos(t + 0.05);
  // tank axes in the world: u away from the camera (-z), v up, w into the wall (-x)
  const hz = -(b[0] - a[0]) * map.Lt, hy = (b[1] - a[1]) * map.Ht, hx = -(b[2] - a[2]) * map.Dt;
  const n = Math.hypot(hx, hy, hz) || 1;
  const y = Math.max(-0.5, Math.min(0.5, hy / n)), k = Math.sqrt(1 - y * y), hn = Math.hypot(hx, hz) || 1;
  const [u, v, w] = pos(t);
  return { u, v, w, head: [(hx / hn) * k, y, (hz / hn) * k], speed: n / 0.1 };
}

// The axolotl's day over a loop: rests at a spot, then a slow swim to the next, and so on, from the seed. spots: [[u, w]
// or [u, w, v]] (v: its middle's height there, measured on the painting; else the floor's plus a little). Returns (t) =>
// { u, v, w, head, swim (0..1), speed, look }.
export function axolotlPlan(spots, P, map, seed = 1) {
  const r = mulberry32((seed * 6007 + 3) >>> 0);
  const legs = [];
  let t = 0, i = 0;
  const restV = (s) => s[2] ?? map.floor(s[0]) + 0.05;
  // whole rounds of the spots, so the last swim ends where the first rest is (never a swim from a spot back to itself)
  while (t < P || i % spots.length) {
    const rest = 70 + 70 * r();
    const swim = 16 + 10 * r();
    const a = spots[i % spots.length], b = spots[(i + 1) % spots.length];
    legs.push({ t0: t, t1: t + rest, a, b, s1: t + rest + swim, rise: 0.42 + 0.2 * r(), side: (r() - 0.5) * 0.24 });
    t += rest + swim;
    i++;
  }
  // stretch to fill the loop exactly: the last swim ends where the first rest begins
  const k = P / t;
  for (const L of legs) { L.t0 *= k; L.t1 *= k; L.s1 *= k; }
  const at = (L, s) => {
    // a cubic Bezier from a's spot to b's: steadily along the way between them (a third of it at each control point,
    // so it never doubles back and its heading never flips), up into the middle of the tank and bowed a little toward
    // the glass or away from it
    const p0 = [L.a[0], restV(L.a), L.a[1]], p3 = [L.b[0], restV(L.b), L.b[1]];
    const lerp = (j, f) => p0[j] + (p3[j] - p0[j]) * f;
    const p1 = [lerp(0, 1 / 3), Math.max(L.rise, p0[1]), lerp(2, 1 / 3) + L.side];
    const p2 = [lerp(0, 2 / 3), Math.max(L.rise, p3[1]), lerp(2, 2 / 3) + L.side];
    const q = 1 - s;
    return [0, 1, 2].map((j) => q * q * q * p0[j] + 3 * q * q * s * p1[j] + 3 * q * s * s * p2[j] + s * s * s * p3[j]);
  };
  const heading = (L, s) => {
    const a = at(L, Math.max(0, s - 0.01)), b = at(L, Math.min(1, s + 0.01));
    const hz = -(b[0] - a[0]) * map.Lt, hy = (b[1] - a[1]) * map.Ht, hx = -(b[2] - a[2]) * map.Dt;
    const n = Math.hypot(hx, hy, hz) || 1;
    return [hx / n, Math.max(-0.6, Math.min(0.6, hy / n)), hz / n];
  };
  // level, along the floor: the way it faces while it rests
  const flat = (h) => { const n = Math.hypot(h[0], h[2]) || 1; return [h[0] / n, 0, h[2] / n]; };
  const turn = (a, b, k) => {
    const ya = Math.atan2(a[0], a[2]);
    let d = Math.atan2(b[0], b[2]) - ya;
    d = ((d + Math.PI) % TAU + TAU) % TAU - Math.PI;
    const y = ya + d * k;
    return [Math.sin(y), 0, Math.cos(y)];
  };
  return (tt) => {
    const L = legs.find((x) => tt >= x.t0 && tt < x.s1) ?? legs[legs.length - 1];
    if (tt < L.t1) {
      // resting where the last swim set it down, facing the way it came in; over the rest's last 4 s it turns, unhurried,
      // the way it will set off (a turn of the head alone would leave it swimming off sideways); its head turns now and
      // then while it rests
      const prev = legs[(legs.indexOf(L) - 1 + legs.length) % legs.length];
      const head = turn(flat(heading(prev, 1)), flat(heading(L, 0)), smooth((tt - (L.t1 - 4)) / 4));
      const look = 0.25 * Math.sin((TAU * (tt - L.t0)) / 23) * smooth((tt - L.t0) / 6) * (1 - smooth((tt - (L.t1 - 6)) / 2));
      return { u: L.a[0], v: restV(L.a), w: L.a[1], head, swim: 0, speed: 0, look };
    }
    const s = smooth((tt - L.t1) / (L.s1 - L.t1));
    const p = at(L, s);
    const ds = 0.01;
    const q0 = at(L, Math.max(0, s - ds)), q1 = at(L, Math.min(1, s + ds));
    const speed = Math.hypot((q1[0] - q0[0]) * map.Lt, (q1[1] - q0[1]) * map.Ht, (q1[2] - q0[2]) * map.Dt) / (2 * ds) / (L.s1 - L.t1);
    const sw = smooth((tt - L.t1) / 2) * (1 - smooth((tt - L.s1 + 2) / 2));
    // nose up or down only while it is well under way: level where it sets off and where it settles
    const h = heading(L, s), f = flat(h);
    const hy = h[1] * sw, k = Math.sqrt(1 - hy * hy);
    return { u: p[0], v: p[1], w: p[2], head: [f[0] * k, hy, f[2] * k], swim: sw, speed, look: 0 };
  };
}

// The fish's swims from the layer's seed: each a sum of whole-cycle sines in the tank's u, v and w (fishAt), its palette
// and its length in blocks. The same draws the layer makes (tests/test_enchanter.py checks them).
export function fishSwims(n, P, seed, top) {
  const rng = mulberry32((seed * 1913 + 29) >>> 0);
  const cyc = (per) => (TAU * Math.max(1, Math.round(P / per))) / P;
  return Array.from({ length: n }, (_, i) => {
    const len = 0.9 + 0.25 * rng();
    // kept clear of the sand (at most 0.26 + 0.08 high) and of the surface (top - 0.08), so the height never clamps: a
    // clamped height follows the sand's steps, and the fish pitched half a radian in one frame
    const f = {
      u0: 0.5 + 0.08 * (rng() - 0.5), au: 0.3 + 0.12 * rng(), wu: cyc(32 + 22 * rng()), pu: TAU * rng(),
      v0: 0.47 + 0.19 * rng(), av: 0.05 + 0.06 * rng(), wv: cyc(17 + 14 * rng()), pv: TAU * rng(),
      w0: 0.3 + 0.3 * rng(), aw: 0.12 + 0.12 * rng(), dir: rng() < 0.5 ? 1 : -1,
      clear: 0.08, top: top - 0.08, beat: cyc(1 / (1.4 + 0.8 * rng())),
    };
    return { f, pal: i % FISH.length, len };
  });
}

// ------------------------------------------------------------------ shaders
const quadVert = /* glsl */ `
uniform vec4 uBox;
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
// the tank's masks over its box: R plants, coral and sand (not water), G the front glass's bright edges, B what stands in
// front of the tank, A inside the glass
const MASKS = /* glsl */ `
uniform sampler2D tMask, tBlur;
uniform vec4 uMaskBox;     // x0, y0, w, h (px)
vec4 maskAt(vec2 uv) {
  vec2 px = vec2(uv.x * ${W}.0, (1.0 - uv.y) * ${H}.0);
  vec2 m = (px - uMaskBox.xy) / uMaskBox.zw;
  if (any(lessThan(m, vec2(0.0))) || any(greaterThan(m, vec2(1.0)))) return vec4(0.0, 0.0, 1.0, 0.0);
  return texture2D(tMask, m);     // a DataTexture: its first row (the box's top) is at v = 0
}`;
const fishFrag = /* glsl */ `
uniform sampler2D tFish;
uniform float uBehind, uTint;
varying vec2 vT;
varying vec2 vUv;
${MASKS}
void main() {
  vec4 c = texture2D(tFish, vec2(vT.x, 1.0 - vT.y));
  if (c.a < 0.002) discard;
  vec4 m = maskAt(vUv);
  float k = m.a * (1.0 - m.b) * (1.0 - 0.85 * m.g) * (1.0 - uBehind * m.r);
  if (k <= 0.002) discard;
  vec3 water = texture2D(tBlur, vUv).rgb;
  gl_FragColor = vec4(mix(c.rgb, water * c.a, uTint), c.a) * k;
}`;

const bubbleVert = /* glsl */ `
attribute vec4 aP;      // period (s), phase (0..1), size (px), seed
uniform float uTime, uLoop;
uniform mat3 uM;        // the tank's homography (unit square -> px)
uniform vec4 uEmit;     // u, w, the floor's v there, the surface's v
uniform vec2 uShift;    // px to the left per unit of w at the emitter's u, px per block there
varying vec2 vQ;
varying float vA, vPop, vR;
varying vec2 vUv;
float h(float k, float s) { return fract(sin(k * 78.233 + s * 12.9898) * 43758.5453); }
vec2 F(vec2 uv) { vec3 p = uM * vec3(uv, 1.0); return p.xy / p.z; }
void main() {
  float per = aP.x, n = floor(uLoop / per + 0.5);
  float tt = uTime + aP.y * per;
  float k = mod(floor(tt / per), n);
  float tc = tt - floor(tt / per) * per;
  float speed = 0.32 * (0.85 + 0.3 * h(k, aP.w));       // blocks/s
  float rise = (uEmit.w - uEmit.z) * 3.0 / speed;          // the tank is 3 blocks tall
  float s = tc / rise;
  vPop = s > 1.0 ? clamp((tc - rise) / 0.18, 0.0, 1.0) : -1.0;
  vA = (s < 1.0 || vPop < 1.0) ? smoothstep(0.0, 0.05, s) : 0.0;
  float v = mix(uEmit.z, uEmit.w, min(s, 1.0));
  float w = uEmit.y + 0.04 * sin(6.2832 * h(k, aP.w + 1.0) + tc * 2.1);
  vec2 c = F(vec2(uEmit.x + 0.012 * sin(tc * (5.0 + 3.0 * h(k, aP.w + 2.0)) + 6.2832 * h(k, aP.w + 3.0)), v)) - vec2(w * uShift.x, 0.0);
  float r = 0.5 * aP.z * (0.8 + 0.5 * h(k, aP.w + 4.0)) * (1.0 + 0.25 * min(s, 1.0)) * uShift.y / 300.0;
  vR = r;
  float ext = r * (vPop >= 0.0 ? 2.4 : 1.5);
  vec2 p = c + position.xy * ext;
  vQ = position.xy * ext / r;
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vA > 0.0 ? vec4(vUv * 2.0 - 1.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;
const bubbleFrag = /* glsl */ `
varying vec2 vQ;
varying float vA, vPop, vR;
varying vec2 vUv;
${MASKS}
void main() {
  vec4 m = maskAt(vUv);
  float k = m.a * (1.0 - m.b) * (1.0 - 0.7 * m.g);
  vec3 water = texture2D(tBlur, vUv).rgb;
  float d = length(vQ);
  float aa = 1.2 / max(vR, 1.0);
  if (vPop >= 0.0) {
    float ring = (1.0 - smoothstep(0.0, 0.2 + aa, abs(d - 1.0 - 1.2 * vPop))) * (1.0 - vPop);
    float a = ring * 0.5 * vA * k;
    if (a < 0.003) discard;
    gl_FragColor = vec4(mix(water, vec3(1.0), 0.6) * a, a);
    return;
  }
  if (d > 1.0 + aa) discard;
  float inside = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, d);
  float rim = smoothstep(0.6, 0.97, d) * inside;
  float spec = exp(-dot(vQ - vec2(-0.35, -0.4), vQ - vec2(-0.35, -0.4)) * 16.0);
  vec3 col = mix(water * 1.3 + 0.04, mix(water, vec3(0.9, 0.97, 1.0), 0.55), rim) + vec3(1.0) * spec * 0.8;
  float a = vA * k * (0.12 * inside + 0.55 * rim + 0.7 * spec);
  if (a < 0.003) discard;
  gl_FragColor = vec4(col * a, a);
}`;

// light from the rippling surface over the sand and the plants: two drifting ridge patterns multiplied, brightest where
// they cross, moving a whole number of tiles a loop
const causticFrag = /* glsl */ `
uniform float uPhase, uAmt;
uniform sampler2D tPlate;
varying vec2 vT;
varying vec2 vUv;
${GLSL_COMMON}
${MASKS}
float ridge(vec2 p, vec2 per) { return 1.0 - abs(2.0 * pnoise(p, per) - 1.0); }
void main() {
  vec4 m = maskAt(vUv);
  float k = m.a * (1.0 - m.b) * (1.0 - m.g);
  if (k <= 0.01) discard;
  vec2 px = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
  vec2 p = px / 95.0;
  vec2 per = vec2(64.0);
  float a = ridge(p + vec2(uPhase * 64.0, uPhase * 32.0), per);
  float b = ridge(p * 1.37 + vec2(-uPhase * 64.0, uPhase * 64.0), per * 1.0);
  float c = pow(a * b, 5.0);
  // brightest on what the light falls on (the plants, the sand), lighter in the open water
  float amt = uAmt * k * (0.35 + 0.65 * m.r);
  vec3 col = texture2D(tPlate, vUv).rgb;
  vec3 add = col * c * amt * 2.2 + vec3(0.6, 0.85, 1.0) * c * amt * 0.25;
  gl_FragColor = vec4(add, 0.0);
}`;

// ------------------------------------------------------------------ the layer
async function tankMasks(plate, quad, frontIds, pad = 8) {
  const xs = quad.map((p) => p[0]), ys = quad.map((p) => p[1]);
  const bx0 = Math.max(0, Math.floor(Math.min(...xs) - pad)), by0 = Math.max(0, Math.floor(Math.min(...ys) - pad));
  const bx1 = Math.min(W, Math.ceil(Math.max(...xs) + pad)), by1 = Math.min(H, Math.ceil(Math.max(...ys) + pad));
  const S = 2;                                             // half resolution
  const mw = Math.ceil((bx1 - bx0) / S), mh = Math.ceil((by1 - by0) / S);
  const img = await imagePixels(`/out/plates/${plate}/plate.png`);
  const reg = frontIds.length ? await imagePixels(`/out/plates/${plate}/regions.png`) : null;
  const L = new Float32Array(mw * mh);
  const out = new Uint8Array(mw * mh * 4);
  const inside = (x, y) => {
    let s = 0;
    for (let i = 0; i < 4; i++) {
      const [ax, ay] = quad[i], [bx, by] = quad[(i + 1) % 4];
      const c = (bx - ax) * (y - ay) - (by - ay) * (x - ax);
      if (c !== 0) { if (s === 0) s = Math.sign(c); else if (Math.sign(c) !== s) return false; }
    }
    return true;
  };
  for (let j = 0; j < mh; j++) {
    for (let i = 0; i < mw; i++) {
      const x = bx0 + i * S + S / 2, y = by0 + j * S + S / 2;
      const q = (Math.min(H - 1, Math.round(y)) * img.width + Math.min(W - 1, Math.round(x))) * 4;
      const r = img.data[q] / 255, g = img.data[q + 1] / 255, b = img.data[q + 2] / 255;
      L[j * mw + i] = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      // the water is blue: blue well over red and at least as much as green; plants, coral and sand aren't
      const water = Math.min(1, Math.max(0, (b - Math.max(1.6 * r, 0.95 * g) + 0.02) / 0.1));
      const o = (j * mw + i) * 4;
      out[o] = Math.round(255 * (1 - water));
      out[o + 3] = inside(x, y) ? 255 : 0;
      if (reg) {
        const rx = Math.min(reg.width - 1, Math.round((x * reg.width) / W)), ry = Math.min(reg.height - 1, Math.round((y * reg.height) / H));
        if (frontIds.includes(reg.data[(ry * reg.width + rx) * 4])) out[o + 2] = 255;
      }
    }
  }
  // the glass's bright edges: brighter than their surroundings by a margin (a box mean 12 px across)
  const R = 6;
  const I = new Float64Array((mw + 1) * (mh + 1));
  for (let j = 0; j < mh; j++) for (let i = 0; i < mw; i++) I[(j + 1) * (mw + 1) + i + 1] = L[j * mw + i] + I[j * (mw + 1) + i + 1] + I[(j + 1) * (mw + 1) + i] - I[j * (mw + 1) + i];
  for (let j = 0; j < mh; j++) {
    for (let i = 0; i < mw; i++) {
      const a0 = Math.max(0, i - R), a1 = Math.min(mw, i + R + 1), b0 = Math.max(0, j - R), b1 = Math.min(mh, j + R + 1);
      const mean = (I[b1 * (mw + 1) + a1] - I[b0 * (mw + 1) + a1] - I[b1 * (mw + 1) + a0] + I[b0 * (mw + 1) + a0]) / ((a1 - a0) * (b1 - b0));
      const e = Math.min(1, Math.max(0, (L[j * mw + i] - mean - 0.07) / 0.1));
      out[(j * mw + i) * 4 + 1] = Math.round(255 * e);
    }
  }
  // what stands in front, grown by a pixel so no fish edge peeks past it
  const B = out.slice();
  for (let j = 1; j < mh - 1; j++) for (let i = 1; i < mw - 1; i++) {
    let m = 0;
    for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) m = Math.max(m, B[((j + dj) * mw + i + di) * 4 + 2]);
    out[(j * mw + i) * 4 + 2] = m;
  }
  const tex = new THREE.DataTexture(out, mw, mh, THREE.RGBAFormat);
  tex.flipY = false;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return { tex, box: [bx0, by0, mw * S, mh * S] };
}

export async function aquariumLayer(ctx, opts) {
  const R = ctx.renderer;
  const tank = opts.tank;
  if (!R || !tank?.quad) return null;
  const P = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const map = tankMap(tank);
  const meta = await plateRegions(opts.plate);
  const frontIds = meta.filter((g) => (tank.front ?? []).includes(g.name)).map((g) => g.id);
  const masks = await tankMasks(opts.plate, tank.quad, frontIds);
  const tBlur = await plateTexture(opts.plate, 'blur.png', { srgb: true });
  const tPlate = await plateTexture(opts.plate, 'plate.png', { srgb: true });
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  const maskUniforms = () => ({ tMask: { value: masks.tex }, tBlur: { value: tBlur }, uMaskBox: { value: new THREE.Vector4(...masks.box) } });
  const focal = opts.focal ?? 1600, cx = W / 2, cy = opts.horizon ?? 1060;
  const ro = opts.renderOrder ?? 7;
  const rng = mulberry32(((ctx.seed ?? 1) * 1913 + 31) >>> 0);     // the bubbles' draws (the fish's: fishSwims)
  const cyc = (per) => (TAU * Math.max(1, Math.round(P / per))) / P;
  // the light in the tank: a lamp over the water, near white, and the room's warm light through the front glass from the
  // window's side; the water's blue comes from the depth tint, never from the light on the fish (lit by the blue water
  // around them, the orange fish came out near black and the pink axolotl mauve)
  const bot = map.F(0.55, 0.15);
  const sandLight = avg(bot[0] - 160, bot[1] - 40, bot[0] + 160, bot[1] + 40);
  const makeScene = () => {
    const scene3 = new THREE.Scene();
    const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 1.2);
    hemi.color.setRGB(0.95, 1.0, 1.08);
    hemi.groundColor.setRGB(...sandLight.map((v) => Math.min(1, v * 2.5)));
    const key = new THREE.DirectionalLight('#fff6e8', opts.key ?? 1.8);
    key.position.set(0.45, 0.85, 0.35).multiplyScalar(100);
    const fill = new THREE.DirectionalLight('#dff0ff', opts.fill ?? 0.6);
    fill.position.set(0.6, 0.2, 1).multiplyScalar(100);
    scene3.add(hemi, key, fill);
    return scene3;
  };
  const prevClear = new THREE.Color();
  const renderInto = (rt, scene3, cam) => {
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, cam);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
  };
  // one creature: its own scene, target and quad; place(state) poses it, frames it and draws it
  const creature = (model, maxPx, unitsPerBlock = 16) => {
    const scene3 = makeScene();
    const holder = new THREE.Group();
    holder.add(model.root);
    scene3.add(holder);
    const RT = Math.min(512, Math.ceil(maxPx / 16) * 16);
    const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 400);
    const mat = new THREE.ShaderMaterial({ vertexShader: quadVert, fragmentShader: fishFrag, ...PREMUL,
      uniforms: { uBox: { value: new THREE.Vector4() }, tFish: { value: rt.texture }, uBehind: { value: 0 }, uTint: { value: 0 }, ...maskUniforms() } });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    quad.frustumCulled = false;
    quad.renderOrder = ro;
    quad.userData.noAO = true;
    ctx.add(quad);
    return (st, scale) => {
      const [px, py, ppb] = map.at(st.u, st.v, st.w);
      const ppu = (ppb / unitsPerBlock) * scale;
      const half = RT / 2 / ppu;
      Object.assign(cam, { left: -half, right: half, top: half, bottom: -half });
      cam.updateProjectionMatrix();
      // its heading: turned about the vertical toward its way, pitched up or down along it
      const [hx, hy, hz] = st.head;
      holder.rotation.set(-Math.asin(hy), Math.atan2(hx, hz), 0, 'YXZ');
      const n = new THREE.Vector3(cx - px, py - cy, focal).normalize();
      cam.position.copy(n).multiplyScalar(200);
      cam.up.set(0, 1, 0);
      cam.lookAt(0, 0, 0);
      renderInto(rt, scene3, cam);
      mat.uniforms.uBox.value.set(px - RT / 2, py - RT / 2, RT, RT);
      mat.uniforms.uBehind.value = smooth((st.w - 0.4) / 0.2);
      mat.uniforms.uTint.value = 0.06 + 0.3 * st.w;
      // nearer in the tank, drawn later: a fish passing in front of another covers it
      quad.renderOrder = ro + 0.2 * (1 - st.w);
      quad.visible = true;
    };
  };

  // the fish
  const nFish = opts.fish ?? 5;
  const top_v = tank.surface ?? 0.9;
  const fish = fishSwims(nFish, P, ctx.seed ?? 1, top_v).map(({ f, pal, len }, i) => {
    const model = buildFish(FISH[pal], i);
    const lenBlocks = (model.len / 16) * len;
    const draw = creature(model, (lenBlocks + 0.4) * map.ppb(0) * 1.15);
    return { f, model, draw, scale: len };
  });

  // the axolotl
  let axo = null;
  if (opts.axolotl !== false && opts.axolotl?.spots?.length) {
    const model = buildAxolotl();
    const scale = opts.axolotl.scale ?? 0.55;
    axo = { model, plan: axolotlPlan(opts.axolotl.spots, P, map, ctx.seed ?? 1), draw: creature(model, (model.len / 16) * scale * map.ppb(0) * 1.4 + 40), scale };
  }

  // bubbles
  let bmat = null;
  if (opts.bubbles !== false) {
    const B = opts.bubbles ?? {};
    const [eu, ew] = B.at ?? [0.6, 0.35];
    const rate = B.rate ?? 2.5, [s0, s1] = B.size ?? [7, 15];
    const N = Math.max(1, Math.round(rate * 4));
    const aP = new Float32Array(N * 4);
    for (let i = 0; i < N; i++) {
      const per = P / Math.max(1, Math.round(P / (3.2 + 1.6 * rng())));
      aP.set([per, rng(), s0 + (s1 - s0) * rng(), Math.floor(rng() * 997)], i * 4);
    }
    const g = instancedQuad(N);
    g.setAttribute('aP', new THREE.InstancedBufferAttribute(aP, 4));
    const M = map.M;
    bmat = new THREE.ShaderMaterial({ vertexShader: bubbleVert, fragmentShader: bubbleFrag, ...PREMUL,
      uniforms: {
        uTime: { value: 0 }, uLoop: { value: P }, uM: { value: new THREE.Matrix3().set(M[0], M[1], M[2], M[3], M[4], M[5], M[6], M[7], M[8]) },
        uEmit: { value: new THREE.Vector4(eu, ew, map.floor(eu), top_v) }, uShift: { value: new THREE.Vector2(map.Dt * map.ppb(eu), map.ppb(eu)) },
        ...maskUniforms(),
      } });
    const bm = new THREE.Mesh(g, bmat);
    bm.frustumCulled = false;
    bm.renderOrder = ro + 0.2 * (1 - ew);       // among the fish, by its depth in the tank
    bm.userData.noAO = true;
    ctx.add(bm);
  }

  // the surface's light rippling over what is in the tank
  let cmat = null;
  if ((opts.caustics ?? 0.07) > 0) {
    cmat = new THREE.ShaderMaterial({ vertexShader: quadVert, fragmentShader: causticFrag, ...ADDITIVE,
      uniforms: { uBox: { value: new THREE.Vector4(...masks.box) }, uPhase: { value: 0 }, uAmt: { value: opts.caustics ?? 0.07 }, tPlate: { value: tPlate }, ...maskUniforms() } });
    const cm = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), cmat);
    cm.frustumCulled = false;
    cm.renderOrder = ro - 0.5;
    cm.userData.noAO = true;
    ctx.add(cm);
  }

  ctx.animate((t) => {
    const tm = ((t % P) + P) % P;
    for (const F of fish) {
      const st = fishAt(F.f, tm, map);
      const m = F.model;
      const sp = Math.min(1, st.speed / 0.5);
      const beat = Math.sin(F.f.beat * tm);
      m.tail.rotation.y = (0.18 + 0.4 * sp) * beat;
      m.root.rotation.y = -0.06 * (0.3 + sp) * beat;
      m.pecs.forEach((g, k) => { g.rotation.y = (k ? -1 : 1) * (0.5 + 0.25 * Math.sin(F.f.beat * 0.7 * tm + k)); });
      F.draw(st, F.scale);
    }
    if (axo) {
      const st = axo.plan(tm);
      const m = axo.model;
      const sw = st.swim;
      // swimming: the tail sweeps in a wave, the legs fold back along the body; resting: legs out on the sand, the tail
      // curled a little, the gills stirring as it breathes
      const ph = cyc(1.6) * tm;
      m.tail1.rotation.y = sw * 0.35 * Math.sin(ph) + (1 - sw) * 0.18 * Math.sin(cyc(9.5) * tm);
      m.tail2.rotation.y = sw * 0.5 * Math.sin(ph - 1.1) + (1 - sw) * 0.25 * Math.sin(cyc(9.5) * tm - 0.8);
      m.body.rotation.y = -sw * 0.08 * Math.sin(ph + 0.6);
      m.head.rotation.y = st.look ?? 0;
      m.legs.forEach((L) => {
        L.g.rotation.x = sw * (L.front ? 1.1 : 1.3);
        L.g.rotation.z = (1 - sw) * L.s * 0.5;
      });
      const breathe = Math.sin(cyc(3.6) * tm);
      m.gills.forEach((G, i) => { G.g.rotation.z = G.base - G.s * (0.08 * breathe + 0.06 * Math.sin(cyc(1.3) * tm + i)); });
      m.body.scale.set(1 + 0.02 * breathe * (1 - sw), 1 + 0.03 * breathe * (1 - sw), 1);
      axo.draw(st, axo.scale);
    }
    if (bmat) bmat.uniforms.uTime.value = tm;
    if (cmat) cmat.uniforms.uPhase.value = tm / P;
  });
  return true;
}
