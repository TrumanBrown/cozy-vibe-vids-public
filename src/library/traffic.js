// Passing traffic seen through a window or down a street: cars (timeline 'car' events) and a distant train
// ('train' events, a chain of lit windows). Light-only, as at night in the rain: headlights and tail lights
// with a soft halo, a pool of light on the road ahead, and long reflections on the wet road below each light.
// Everything is clipped to the outdoors (lights.png G), so interior objects stay in front.
//
// opts: { plate,
//   path: [[x, y], ...] the road (image coords, y down) from its left/far end to its right/near end,
//   scale: car length in px at 4K at each path point (number or array), view: 'side' (street across the frame;
//   lights at the car's ends) | 'depth' (street toward the camera; a pair of lights side by side),
//   lanes: [dy, ...] px offsets per lane (scaled), reflect: wet-road reflection strength (0..1),
//   train: { path, scale, cars, windowColor } }
import * as THREE from 'three';
import { plateTexture, ADDITIVE } from './overlay.js';

const MAX = 96;

const vert = /* glsl */ `
attribute vec4 aS;     // center x, y (px), size x, size y (px)
attribute vec4 aC;     // color rgb (linear), intensity
attribute float aK;    // kind: 0 glow, 1 reflection streak, 2 pool, 3 window
varying vec2 vQ;
varying vec4 vC;
varying float vK;
varying vec2 vUv;
void main() {
  vec2 q = position.xy;
  vec2 p = aS.xy + q * aS.zw * (aK < 0.5 ? 3.0 : 1.0);
  vQ = q * (aK < 0.5 ? 3.0 : 1.0);
  vC = aC; vK = aK;
  vUv = vec2(p.x / 3840.0, 1.0 - p.y / 2160.0);
  gl_Position = aC.w > 0.0 ? vec4(vUv * 2.0 - 1.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights;
varying vec2 vQ;
varying vec4 vC;
varying float vK;
varying vec2 vUv;
void main() {
  float r2 = dot(vQ, vQ), a;
  if (vK < 0.5) a = exp(-r2 * 3.2) + 0.16 * exp(-r2 * 0.35);                         // light: core + halo
  else if (vK < 1.5) a = exp(-vQ.x * vQ.x * 5.0) * smoothstep(1.0, 0.0, abs(vQ.y)) * (0.6 + 0.4 * sin(vQ.y * 23.0 + vQ.x * 3.0)); // rippled streak
  else if (vK < 2.5) a = exp(-r2 * 2.0) * 0.5;                                        // pool on the road
  else a = (1.0 - smoothstep(0.75, 1.0, abs(vQ.x))) * (1.0 - smoothstep(0.7, 1.0, abs(vQ.y)));   // lit train window
  a *= vC.w * texture2D(tLights, vUv).g;
  if (a < 0.001) discard;
  gl_FragColor = vec4(vC.rgb * a, a);
}`;

function polyAt(path, s) {
  // point and tangent at arc fraction s (0..1) along a polyline
  const seg = [];
  let tot = 0;
  for (let i = 1; i < path.length; i++) { const l = Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]); seg.push(l); tot += l; }
  let d = Math.min(Math.max(s, 0), 1) * tot;
  for (let i = 0; i < seg.length; i++) {
    if (d <= seg[i] || i === seg.length - 1) {
      const u = seg[i] > 0 ? Math.min(d / seg[i], 1) : 0;
      const a = path[i], b = path[i + 1];
      return { p: [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u], t: [(b[0] - a[0]) / (seg[i] || 1), (b[1] - a[1]) / (seg[i] || 1)], i, u };
    }
    d -= seg[i];
  }
  return { p: path[path.length - 1], t: [1, 0], i: 0, u: 0 };
}
const scaleAt = (sc, i, u) => (Array.isArray(sc) ? sc[i] + ((sc[i + 1] ?? sc[i]) - sc[i]) * u : sc);

export async function trafficLayer(ctx, opts) {
  const tl = ctx.timeline;
  const cars = (tl?.events ?? []).filter((e) => e.type === 'car');
  const trains = (tl?.events ?? []).filter((e) => e.type === 'train');
  if (!(cars.length && opts.path) && !(trains.length && opts.train?.path)) return null;
  const tLights = await plateTexture(opts.plate, 'lights.png');
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = MAX;
  const aS = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
  const aC = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
  const aK = new THREE.InstancedBufferAttribute(new Float32Array(MAX), 1);
  for (const a of [aS, aC, aK]) a.setUsage(THREE.DynamicDrawUsage);
  g.setAttribute('aS', aS); g.setAttribute('aC', aC); g.setAttribute('aK', aK);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...ADDITIVE, uniforms: { tLights: { value: tLights } },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 8;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const head = new THREE.Color(opts.headColor ?? '#fff1d8'), tail = new THREE.Color(opts.tailColor ?? '#ff2a1a');
  const win = new THREE.Color(opts.train?.windowColor ?? '#ffd9a0');
  const gain = opts.gain ?? 1.6, refl = opts.reflect ?? 0.55;
  const lanes = opts.lanes ?? [0, -0.12];
  let n = 0;
  const put = (x, y, sx, sy, c, I, k) => {
    if (n >= MAX || I <= 0) return;
    aS.array.set([x, y, sx, sy], n * 4);
    aC.array.set([c.r, c.g, c.b, I], n * 4);
    aK.array[n] = k;
    n++;
  };
  ctx.animate((t) => {
    n = 0;
    for (const e of cars) {
      if (t < e.t || t > e.t + e.dur) continue;
      const s0 = (t - e.t) / e.dur;
      const s = e.dir > 0 ? s0 : 1 - s0;
      const fade = Math.min(1, s0 / 0.08, (1 - s0) / 0.08);
      const at = polyAt(opts.path, s);
      const len = scaleAt(opts.scale ?? 160, at.i, at.u) * (e.size ?? 1);
      const laneK = lanes[Math.min(lanes.length - 1, Math.floor((e.lane ?? 0) * lanes.length))];
      const [x, y] = [at.p[0] * 3840, at.p[1] * 2160 + laneK * len];
      const I = gain * fade;
      if ((opts.view ?? 'side') === 'side') {
        const fx = x + e.dir * 0.5 * len, bx = x - e.dir * 0.5 * len, r = 0.05 * len;
        put(fx, y, r, r, head, I, 0);                              // headlight
        put(bx, y + 0.02 * len, r * 0.7, r * 0.7, tail, I * 0.55, 0); // tail light
        put(fx + e.dir * 0.9 * len, y + 0.12 * len, 0.9 * len, 0.12 * len, head, I * 0.18, 2);  // light pool ahead
        put(fx, y + 0.45 * len, r * 0.8, 0.45 * len, head, I * refl * 0.35, 1);   // wet-road reflections
        put(bx, y + 0.4 * len, r * 0.6, 0.4 * len, tail, I * refl * 0.25, 1);
      } else {
        const toward = e.dir > 0;
        const c = toward ? head : tail, w = 0.22 * len, r = (toward ? 0.05 : 0.035) * len;
        for (const sx of [-1, 1]) {
          put(x + sx * w, y, r, r, c, I * (toward ? 1 : 0.6), 0);
          put(x + sx * w, y + 0.5 * len, r * 0.8, 0.5 * len, c, I * refl * 0.3, 1);
        }
        if (toward) put(x, y + 0.3 * len, 0.6 * len, 0.1 * len, head, I * 0.15, 2);
      }
    }
    for (const e of trains) {
      if (!opts.train || t < e.t || t > e.t + e.dur) continue;
      const T = opts.train;
      const s0 = (t - e.t) / e.dur;
      const nWin = (e.cars ?? 6) * (T.windows ?? 6);
      const span = 1.35;                                 // the whole train passes: head enters, tail leaves
      for (let k = 0; k < nWin; k++) {
        const along = s0 * span - (k / nWin) * 0.35;
        if (along < 0 || along > 1) continue;
        const s = e.dir > 0 ? along : 1 - along;
        const at = polyAt(T.path, s);
        const len = scaleAt(T.scale ?? 40, at.i, at.u);
        if (k % (T.windows ?? 6) === (T.windows ?? 6) - 1) continue;      // gap between cars
        const lit = ((k * 2654435761) >>> 0) % 100 < (e.lit ?? 0.8) * 100 ? 1 : 0.15;
        put(at.p[0] * 3840, at.p[1] * 2160, 0.32 * len, 0.22 * len, win, (T.gain ?? 1.2) * lit, 3);
      }
    }
    for (let i = n; i < MAX; i++) aC.array[i * 4 + 3] = 0;
    aS.needsUpdate = aC.needsUpdate = aK.needsUpdate = true;
  });
  return mesh;
}
