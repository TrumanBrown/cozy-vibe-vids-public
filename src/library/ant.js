// Ambient event: an ant walks across a table or counter (timeline event type 'ant'; suggested by the user on
// 2026-10-18). A small 3D model built in code (never generated): glossy head, thorax,
// petiole and gaster, six legs in an alternating tripod gait, elbowed antennae that sweep and tap while it stops
// to feel about. It is rendered every frame from the camera's actual angle onto the surface (a level surface at
// row y is seen from asin((y - horizon) / focal) above it), so on a counter seen at a low angle it is the thin
// dark sliver with leg ticks a real ant is. It walks in short bursts with a slight weave, stops now and then, is
// lit by the plate around it, casts a soft contact shadow, and shows only where the plate is the surface itself
// (a plane fitted to the plate's depth along its paths): it comes out from behind the bowl or cup and goes out
// of sight behind them. At the surface's far edge it walks over the corner and down the far side, hidden by a
// depth-only block for the surface (the edge is the outdoor mask's crisp line for an indoor counter: the depth
// map's soft edge made it sink into the ramen counter, 2026-10-19). Where the plate is out of focus (a near counter) the ant
// is blurred by as much (plate_prep defocus.png), so it never looks pasted onto a soft foreground.
//
// opts: { plate, paths: [[[x, y], ...], ...] (image coords; start and end out of sight), size: body length px at
//   4K (34), horizon (0.45: eye-level row, 0..1), focal (2700 px), color ('#1b110b'), shadow (0.4),
//   defocus (1: how much of the plate's blur to match; false = none), renderOrder (7) }.
//   Timeline `ant`: { perHour, dur: [s, s], paths (how many), startAfter, first }.
import * as THREE from 'three';
import { plateTexture, PREMUL, imagePixels } from './overlay.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;

function pathTools(pts) {
  const P = pts.map(([x, y]) => [x * W, y * H]);
  const seg = [];
  let L = 0;
  for (let i = 1; i < P.length; i++) { const l = Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]); seg.push([L, l]); L += l; }
  const at = (d) => {
    d = Math.min(Math.max(d, 0), L);
    let i = seg.findIndex(([s0, l]) => d <= s0 + l);
    if (i < 0) i = seg.length - 1;
    const [s0, l] = seg[i], f = l > 0 ? (d - s0) / l : 0, a = P[i], b = P[i + 1];
    return { x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f, dx: b[0] - a[0], dy: b[1] - a[1] };
  };
  return { L, at };
}

// Distance along the path at tau: bursts of walking (speed swinging +-35% at 0.7 Hz) with stops [[fraction of
// dur, seconds]] in between, scaled to cover the whole path in the event's time. moving: 1 walking, 0 stopped.
function walked(ev, tau, L) {
  const stopT = ev.stops.reduce((s, [, l]) => s + l, 0);
  const T = Math.max(ev.dur - stopT, 1), A = 0.35 / (TAU * 0.7);
  const mod = (tm) => tm + A * (1 - Math.cos(TAU * 0.7 * tm));
  let tm = tau, moving = 1;
  for (const [f, l] of ev.stops) {
    const t0 = f * ev.dur;
    if (tau <= t0) continue;
    tm -= Math.min(l, tau - t0);
    if (tau < t0 + l) moving = Math.min(moving, 1 - Math.min(1, Math.min(tau - t0, t0 + l - tau) / 0.25));
  }
  tm = Math.max(0, Math.min(T, tm));
  return { d: (L * mod(tm)) / mod(T), moving, tm };
}

// The surface the paths run on, as a plane in disparity: d = a + b*y + c*x (px at 4K), fitted robustly to the
// plate's depth along the paths (depth8 holds sqrt(disparity)); points on nearer things or beyond the edge are
// trimmed away as outliers.
function fitPlane(img, paths) {
  if (!img) return [0, 0, 0];
  const pts = [];
  for (const P of paths) {
    for (let d = 0; d <= P.L; d += 4) {
      const p = P.at(d);
      for (const [ox, oy] of [[0, 0], [0, -24], [0, 24], [-24, 0], [24, 0]]) {
        const x = Math.round(((p.x + ox) * img.width) / W), y = Math.round(((p.y + oy) * img.height) / H);
        if (x < 0 || y < 0 || x >= img.width || y >= img.height) continue;
        const s = img.data[(y * img.width + x) * 4] / 255;
        pts.push([p.x + ox, p.y + oy, s * s]);
      }
    }
  }
  let keep = pts, coef = [0, 0, 0];
  for (let it = 0; it < 5 && keep.length >= 3; it++) {
    const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], R = [0, 0, 0];
    for (const [x, y, d] of keep) {
      const v = [1, y, x];
      for (let i = 0; i < 3; i++) { R[i] += v[i] * d; for (let j = 0; j < 3; j++) S[i][j] += v[i] * v[j]; }
    }
    coef = solve3(S, R);
    const res = keep.map(([x, y, d]) => Math.abs(d - (coef[0] + coef[1] * y + coef[2] * x))).sort((a, b) => a - b);
    const lim = Math.max(res[Math.floor(res.length * 0.6)] * 2, 0.01);
    keep = keep.filter(([x, y, d]) => Math.abs(d - (coef[0] + coef[1] * y + coef[2] * x)) <= lim);
  }
  return coef;
}

// How soft the plate is on that surface, as a function of its depth: defocus.png's estimates at every point
// where the plate shows the plane (within 4%), in 6 bins by disparity, a line through the bins' medians.
// Taken from depth rather than read at the ant's spot, so a soft painted light patch or a sharp reflection in
// the varnish doesn't blur and sharpen the ant as it walks over them.
function surfaceBlur(depth, dmap, plane, horizon) {
  if (!dmap || !depth) return null;
  const s = [];
  for (let y = Math.ceil(horizon); y < H; y += 16) {
    for (let x = 0; x < W; x += 16) {
      const dp = plane[0] + plane[1] * y + plane[2] * x;
      if (dp <= 0.02) continue;
      const u = Math.min(depth.width - 1, Math.round((x * depth.width) / W)), v = Math.min(depth.height - 1, Math.round((y * depth.height) / H));
      const q = depth.data[(v * depth.width + u) * 4] / 255;
      if (Math.abs(q * q - dp) > 0.04 * dp) continue;
      const i = Math.min(dmap.width - 1, Math.floor((x / W) * dmap.width)), j = Math.min(dmap.height - 1, Math.floor((y / H) * dmap.height));
      s.push([dp, dmap.data[(j * dmap.width + i) * 4] / 20]);
    }
  }
  if (s.length < 60) return null;
  s.sort((a, b) => a[0] - b[0]);
  const nb = 6, med = (a) => a.slice().sort((p, q) => p - q)[Math.floor(a.length / 2)];
  const bins = Array.from({ length: nb }, (_, k) => s.slice(Math.floor((k * s.length) / nb), Math.floor(((k + 1) * s.length) / nb)))
    .map((b) => [med(b.map((v) => v[0])), med(b.map((v) => v[1]))]);
  const mx = bins.reduce((a, b) => a + b[0], 0) / nb, my = bins.reduce((a, b) => a + b[1], 0) / nb;
  const sxx = bins.reduce((a, b) => a + (b[0] - mx) ** 2, 0), sxy = bins.reduce((a, b) => a + (b[0] - mx) * (b[1] - my), 0);
  const k = sxx > 1e-9 ? sxy / sxx : 0;
  const lo = Math.min(...bins.map((b) => b[1])), hi = Math.max(...bins.map((b) => b[1]));
  const at = (x, y) => Math.min(hi, Math.max(lo, my + k * (plane[0] + plane[1] * y + plane[2] * x - mx)));
  return { at, bins, n: s.length };
}

function solve3(A, b) {
  const M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < 3; c++) {
    let p = c;
    for (let r = c + 1; r < 3; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    if (Math.abs(M[c][c]) < 1e-12) return [0, 0, 0];
    for (let r = 0; r < 3; r++) {
      if (r === c) continue;
      const f = M[r][c] / M[c][c];
      for (let k = c; k < 4; k++) M[r][k] -= f * M[c][k];
    }
  }
  return [M[0][3] / M[0][0], M[1][3] / M[1][1], M[2][3] / M[2][2]];
}

// The model, in body lengths, facing +z, standing on y = 0.
function buildAnt(color) {
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.3, metalness: 0.05 });
  const root = new THREE.Group();
  const blob = (r, p) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14), mat);
    m.scale.set(...r);
    m.position.set(...p);
    root.add(m);
  };
  blob([0.125, 0.1, 0.19], [0, 0.13, -0.29]);    // gaster
  blob([0.035, 0.04, 0.05], [0, 0.12, -0.08]);    // petiole
  blob([0.06, 0.065, 0.13], [0, 0.125, 0.06]);    // thorax
  blob([0.075, 0.068, 0.085], [0, 0.135, 0.27]);  // head
  const limbGeo = new THREE.CylinderGeometry(1, 1, 1, 6);
  const limb = (r) => { const m = new THREE.Mesh(limbGeo, mat); m.userData.r = r; root.add(m); return m; };
  const legs = [];
  for (let i = 0; i < 3; i++) for (const side of [1, -1]) legs.push({ i, side, upper: limb(0.013), lower: limb(0.01) });
  const ants = [1, -1].map((side) => ({ side, a: limb(0.008), b: limb(0.007) }));
  return { root, legs, ants };
}

const UP = new THREE.Vector3(0, 1, 0);
function place(m, a, b) {
  const d = new THREE.Vector3().subVectors(b, a), len = d.length();
  m.position.copy(a).addScaledVector(d, 0.5);
  m.quaternion.setFromUnitVectors(UP, d.normalize());
  m.scale.set(m.userData.r, len, m.userData.r);
}

const HIPZ = [0.14, 0.07, 0.0], FOOTZ = [0.36, 0.05, -0.27], FOOTX = [0.25, 0.3, 0.28];
function pose(ant, gait, moving, antPh, tap) {
  const v = (x, y, z) => new THREE.Vector3(x, y, z);
  for (const L of ant.legs) {
    const grp = (L.i + (L.side > 0 ? 0 : 1)) % 2;      // tripods: L1 R2 L3 | R1 L2 R3
    const ph = TAU * (gait + 0.5 * grp);
    const fz = FOOTZ[L.i] + 0.07 * Math.sin(ph) * moving, lift = 0.045 * Math.max(0, Math.cos(ph)) * moving;
    const hip = v(L.side * 0.045, 0.11, HIPZ[L.i]);
    const foot = v(L.side * FOOTX[L.i], 0.006 + lift, fz);
    const knee = v(L.side * (0.6 * FOOTX[L.i]), 0.2 + 0.4 * lift, (HIPZ[L.i] + fz) / 2 + (L.i === 0 ? 0.05 : L.i === 2 ? -0.05 : 0));
    place(L.upper, hip, knee);
    place(L.lower, knee, foot);
  }
  for (const A of ant.ants) {
    const sw = 0.35 * Math.sin(antPh + A.side * 1.1) + 0.3 * tap * Math.sin(4 * antPh + A.side);
    const base = v(A.side * 0.03, 0.17, 0.33);
    const elbow = v(A.side * 0.07, 0.25, 0.4);
    const tip = v(A.side * (0.07 + 0.11 * Math.sin(0.6 + sw)), 0.2 - 0.12 * tap * Math.max(0, Math.sin(3 * antPh + A.side)), 0.4 + 0.14 * Math.cos(0.6 + sw));
    place(A.a, base, elbow);
    place(A.b, elbow, tip);
  }
}

const quadVert = /* glsl */ `
uniform vec4 uBox;        // x, y (top left, px at 4K, y down), w, h
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
const SURFACE = /* glsl */ `
uniform sampler2D tDepth, tLights;
uniform vec4 uPlane;
uniform float uBeyond;    // 1: hide it beyond the surface's far edge here (0 while it crosses an edge: the occluder does it)
uniform float uIndoor;    // 1: the surface is indoors, so beyond its edge = outdoors (lights.png G, snapped to the image)
// 1 where the plate shows the surface itself: not something nearer (bowl, cup), not beyond its far edge. The depth
// map is soft at an edge, so for an indoor surface "beyond" is the outdoor mask (crisp); fading by depth there made
// the ramen ant go see-through on the counter before it reached the edge (2026-10-19)
float onSurface(vec2 uv) {
  vec2 px = vec2(uv.x * ${W}.0, (1.0 - uv.y) * ${H}.0);
  float dp = uPlane.x + uPlane.y * px.y + uPlane.z * px.x;
  float s = texture2D(tDepth, uv).r, d = s * s;
  float far = uIndoor > 0.5 ? 1.0 - texture2D(tLights, uv).g : smoothstep(dp * 0.78, dp * 0.86, d);
  return (1.0 - smoothstep(dp * 1.06 + 0.01, dp * 1.12 + 0.02, d)) * mix(1.0, far, uBeyond);
}`;
const antFrag = /* glsl */ `
uniform sampler2D tAnt;
uniform float uAlpha;
varying vec2 vT;
varying vec2 vUv;
${SURFACE}
void main() {
  vec4 c = texture2D(tAnt, vec2(vT.x, 1.0 - vT.y));
  float k = uAlpha * onSurface(vUv);
  if (c.a * k < 0.003) discard;
  gl_FragColor = c * k;
}`;
const shadowFrag = /* glsl */ `
uniform float uShadow;
varying vec2 vT;
varying vec2 vUv;
${SURFACE}
void main() {
  vec2 q = vT * 2.0 - 1.0;
  float k = exp(-dot(q, q) * 2.6) * (1.0 - smoothstep(0.8, 1.0, dot(q, q))) * uShadow * onSurface(vUv);
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;
// One pass of a separable Gaussian over the ant's render (premultiplied, linear): blurs it like the plate is
// blurred where it walks, so it isn't sharp on an out-of-focus foreground.
const blurFrag = /* glsl */ `
uniform sampler2D tSrc;
uniform vec2 uStep;
uniform float uSigma;
varying vec2 vUv;
void main() {
  vec4 s = vec4(0.0);
  float wsum = 0.0;
  for (int i = -20; i <= 20; i++) {
    float x = float(i);
    if (abs(x) > 3.0 * uSigma + 1.0) continue;
    float w = exp(-x * x / (2.0 * uSigma * uSigma));
    s += texture2D(tSrc, vUv + uStep * x) * w;
    wsum += w;
  }
  gl_FragColor = s / wsum;
}`;
const blurVert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

// Where a path leaves the surface over its far edge (instead of going behind something nearer): walking from the
// path's middle toward `end` (0 start, 1 end), the first point beyond the surface (`beyond(x, y)`). Returns
// { d: path distance of the crossing, A: [x, y] (px), e: the edge line's screen direction, o: the path's screen
// direction outward there } or null. The edge line is fitted to the boundary in the columns around the crossing.
function findEdge(P, end, beyond) {
  const step = 2, mid = P.L / 2;
  let prev = null;
  for (let k = 0; k * step <= P.L / 2; k++) {
    const d = end ? mid + k * step : mid - k * step;
    const p = P.at(d);
    if (beyond(p.x, p.y)) {
      if (!prev) return null;
      const A = [(prev.x + p.x) / 2, (prev.y + p.y) / 2];
      const o = [p.x - prev.x, p.y - prev.y], on = Math.hypot(...o) || 1;
      // which way across the edge is beyond, up or down the screen (a far edge: up); then in each column near the
      // crossing, the first row beyond it, searching from the inside
      const up = beyond(A[0], A[1] - 24) && !beyond(A[0], A[1] + 24), down = !up && beyond(A[0], A[1] + 24) && !beyond(A[0], A[1] - 24);
      const sy = up ? -1 : down ? 1 : Math.sign(o[1]) || -1, pts = [];
      for (let x = A[0] - 48; x <= A[0] + 48; x += 6) {
        if (beyond(x, A[1] - sy * 40)) continue;
        for (let k = 0; k <= 80; k++) {
          const y = A[1] - sy * 40 + sy * k;
          if (beyond(x, y)) { pts.push([x, y]); break; }
        }
      }
      let m = 0;
      if (pts.length >= 5) {
        const mx = pts.reduce((s, q) => s + q[0], 0) / pts.length, my = pts.reduce((s, q) => s + q[1], 0) / pts.length;
        const sxx = pts.reduce((s, q) => s + (q[0] - mx) ** 2, 0), sxy = pts.reduce((s, q) => s + (q[0] - mx) * (q[1] - my), 0);
        m = Math.max(-1.5, Math.min(1.5, sxx > 0 ? sxy / sxx : 0));
      }
      const en = Math.hypot(1, m);
      return { d: end ? d - step / 2 : d + step / 2, A, e: [1 / en, m / en], o: [o[0] / on, o[1] / on] };
    }
    prev = p;
  }
  return null;
}

export async function antLayer(ctx, opts) {
  const R = ctx.renderer;
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'ant');
  if (!R || !evs.length || !opts.paths?.length) return null;
  const paths = opts.paths.map(pathTools);
  const tDepth = await plateTexture(opts.plate, 'depth8.png');
  const tLights = await plateTexture(opts.plate, 'lights.png');
  const depth = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
  const plane = fitPlane(depth, paths);
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const size = opts.size ?? 34, horizon = (opts.horizon ?? 0.45) * H, focal = opts.focal ?? 2700;
  // How soft the plate is where the ant walks (plate_prep defocus.png, fitted along the surface's depth), less
  // what the ant's own antialiased render already has.
  const dmap = opts.defocus === false ? null : await imagePixels(`/out/plates/${opts.plate}/defocus.png`);
  const blurAt = plateBlur(depth, dmap, plane, horizon, opts);
  let bmax = 0;
  for (const P of paths) for (let d = 0; d <= P.L; d += 8) { const p = P.at(d); bmax = Math.max(bmax, blurAt(p.x, p.y)); }
  const { indoor, edges } = farEdges(paths, depth, plane, await imagePixels(`/out/plates/${opts.plate}/lights.png`));
  const view = antView(opts, size, bmax);
  const avg = plateAverage(blur);
  const slots = antSlots(ctx, opts, view.RT, { tDepth, tLights, plane, indoor });
  const lagsFor = fileLags(paths, slots.length, size);
  const end = (ev) => ev.t + ev.dur + lagsFor(ev).at(-1);
  const drawOne = antDrawer({ ...view, R, paths, edges, avg, blurAt, size, horizon, focal, opts });
  ctx.animate((t) => {
    for (const S of slots) S.quad.visible = S.shadow.visible = false;
    const ev = evs.find((e) => t >= e.t && t <= end(e));
    if (!ev) return;
    const lags = lagsFor(ev);
    lags.forEach((lag, k) => {
      const tau = t - ev.t - lag;
      if (tau < 0 || tau > ev.dur) return;
      // each ant its own gait phase, weave and a little size difference (workers of one nest vary)
      const seed = (ev.seed + 7919 * k) >>> 0;
      drawOne(slots[k], ev, tau, seed, k ? 0.9 + 0.08 * ((seed >>> 8) % 5) / 4 : 1, k);
    });
  });
  return slots[0].quad;
}

// The plate's blur (px) at a point of the ant's surface, less what its own antialiased render already has.
function plateBlur(depth, dmap, plane, horizon, opts) {
  const surf = surfaceBlur(depth, dmap, plane, horizon);
  if (surf) console.log(`ant: plate blur on its surface by disparity ${surf.bins.map(([d, s]) => `${d.toFixed(2)}:${s.toFixed(1)}px`).join(' ')} (${surf.n} points)`);
  return (x, y) => {
    if (!surf) return 0;
    const s = surf.at(x, y);
    return Math.min(6, Math.sqrt(Math.max(0, s * s - 0.6 * 0.6)) * (opts.defocus ?? 1));
  };
}

// Over the far edge: the surface is indoors (a counter in a stall) when most of the paths are, and then beyond it is
// the outdoor mask; outdoors (a table on a terrace) it is where the depth falls well behind the surface's plane.
// -> { indoor, edges: per path [its start's edge, its end's edge] (findEdge; null where it doesn't go over one) }
function farEdges(paths, depth, plane, lit) {
  const G = (x, y) => {
    if (!lit) return 0;
    const i = Math.min(lit.width - 1, Math.max(0, Math.round((x * lit.width) / W))), j = Math.min(lit.height - 1, Math.max(0, Math.round((y * lit.height) / H)));
    return lit.data[(j * lit.width + i) * 4 + 1] / 255;
  };
  let gi = 0, gn = 0;
  for (const P of paths) for (let d = 0.25 * P.L; d <= 0.75 * P.L; d += 8) { const p = P.at(d); gi += G(p.x, p.y); gn++; }
  const indoor = gn > 0 && gi / gn < 0.5;
  const dAt = (x, y) => {
    const i = Math.min(depth.width - 1, Math.max(0, Math.round((x * depth.width) / W))), j = Math.min(depth.height - 1, Math.max(0, Math.round((y * depth.height) / H)));
    const s = depth.data[(j * depth.width + i) * 4] / 255;
    return s * s;
  };
  const beyond = (x, y) => (indoor ? G(x, y) > 0.5 : !!depth && dAt(x, y) < 0.8 * (plane[0] + plane[1] * y + plane[2] * x));
  const edges = paths.map((P) => [findEdge(P, 0, beyond), findEdge(P, 1, beyond)]);
  edges.forEach((E, i) => E.forEach((e, k) => e && console.log(`ant: path ${i} ${k ? 'end' : 'start'} goes over the edge at (${(e.A[0] / W).toFixed(4)}, ${(e.A[1] / H).toFixed(4)}), edge slope ${(e.e[1] / e.e[0]).toFixed(2)}`)));
  return { indoor, edges };
}

// The ant's own little 3D scene, its lights and the camera that looks down onto it, the size of the render target it
// is drawn into (RT px square), and the separable blur pass that softens it like the surface.
function antView(opts, size, bmax) {
  const ant = buildAnt(opts.color ?? '#1b110b');
  const scene3 = new THREE.Scene();
  scene3.add(ant.root);
  ant.root.rotation.order = 'YXZ';      // heading about the vertical, then the pitch over an edge in its own frame
  // The surface's body as a depth-only block: crossing the far edge the ant tips head first over it and goes down the
  // far side, out of sight behind the edge (what is below the surface and behind the block is hidden)
  const occluder = new THREE.Mesh(new THREE.BoxGeometry(20, 20, 20), new THREE.MeshBasicMaterial({ colorWrite: false }));
  occluder.renderOrder = -1;
  occluder.visible = false;
  scene3.add(occluder);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x303030, 1.5);
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-30, 60, -80);    // the lit street and lamps beyond the counter: rim light on its back
  scene3.add(hemi, key);
  const RT = Math.ceil((2.4 * size + 6 * bmax) / 4) * 4;
  const bmat = new THREE.ShaderMaterial({
    vertexShader: blurVert, fragmentShader: blurFrag, depthTest: false, depthWrite: false,
    uniforms: { tSrc: { value: null }, uStep: { value: new THREE.Vector2() }, uSigma: { value: 1 } },
  });
  const bscene = new THREE.Scene();
  const bquad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), bmat);
  bquad.frustumCulled = false;
  bscene.add(bquad);
  const bcam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const cam = new THREE.OrthographicCamera(-1.2, 1.2, 1.2, -1.2, 0.1, 100);
  return { ant, scene3, occluder, hemi, key, RT, bmat, bscene, bcam, cam };
}

// The plate's mean linear color over a box (5 x 5 samples of the blurred plate): the light around the ant.
function plateAverage(blur) {
  const lin = (v) => Math.pow(v / 255, 2.2);
  return (x0, y0, x1, y1) => {
    const s = [0, 0, 0];
    let n = 0;
    for (let j = 0; j < 5; j++) {
      for (let i = 0; i < 5; i++) {
        const x = Math.round(((x0 + ((x1 - x0) * (i + 0.5)) / 5) * blur.width) / W), y = Math.round(((y0 + ((y1 - y0) * (j + 0.5)) / 5) * blur.height) / H);
        if (x < 0 || y < 0 || x >= blur.width || y >= blur.height) continue;
        const q = (y * blur.width + x) * 4;
        s[0] += lin(blur.data[q]); s[1] += lin(blur.data[q + 1]); s[2] += lin(blur.data[q + 2]); n++;
      }
    }
    return n ? s.map((v) => v / n) : [0.05, 0.05, 0.05];
  };
}

// One render target set, quad and shadow per ant that can be out at once (a file of up to 3, timeline `n`)
function antSlots(ctx, opts, RT, { tDepth, tLights, plane, indoor }) {
  const mk = (frag, extra) => new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      uBox: { value: new THREE.Vector4() }, tDepth: { value: tDepth }, uPlane: { value: new THREE.Vector4(...plane, 0) },
      tLights: { value: tLights }, uBeyond: { value: 1 }, uIndoor: { value: indoor ? 1 : 0 }, ...extra,
    },
  });
  return [0, 1, 2].map(() => {
    const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
    const rtH = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType });
    const rtV = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType });
    const mat = mk(antFrag, { tAnt: { value: rt.texture }, uAlpha: { value: 0 } });
    const smat = mk(shadowFrag, { uShadow: { value: 0 } });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), smat);
    quad.renderOrder = opts.renderOrder ?? 7;
    shadow.renderOrder = (opts.renderOrder ?? 7) - 0.5;
    for (const m of [shadow, quad]) { m.frustumCulled = false; m.visible = false; m.userData.noAO = true; ctx.add(m); }
    return { rt, rtH, rtV, mat, smat, quad, shadow };
  });
}

// A file of ants (user 2026-10-19, round 3: more often, or more ants): the others follow the first along
// its trail a fixed time behind, so they pause where it paused, as ants on a scent trail do. The delay is the
// smallest that keeps each at least ~1.9 body lengths behind the one ahead over the whole walk (stops included),
// plus a little of its own; worked out once per event from the walk itself, so nothing can overlap.
function fileLags(paths, nSlots, size) {
  const lagCache = new Map();
  return (ev) => {
    if (lagCache.has(ev)) return lagCache.get(ev);
    const P = paths[ev.path % paths.length];
    const n = Math.max(1, Math.min(nSlots, ev.n ?? 1));
    const lags = [0];
    if (n > 1) {
      const dt = 0.05, N = Math.ceil(ev.dur / dt);
      const D = Array.from({ length: N + 1 }, (_, i) => walked(ev, i * dt, P.L).d);
      let lag = 1.5;
      for (; lag < 15; lag += 0.1) {
        const k = Math.round(lag / dt);
        let mn = Infinity;
        for (let i = k; i <= N; i++) mn = Math.min(mn, D[i] - D[i - k]);
        if (mn >= 1.9 * size) break;
      }
      for (let i = 1; i < n; i++) lags.push(lags[i - 1] + lag + 0.6 * (((ev.seed >>> (4 * i)) & 15) / 15));
    }
    lagCache.set(ev, lags);
    return lags;
  };
}

// One ant of a file into its slot: where it is along its path and how it is turned, over a far edge, lit like the
// plate around it, rendered and softened like the surface, with its contact shadow.
function antDrawer({ R, paths, edges, ant, scene3, occluder, hemi, key, RT, bmat, bscene, bcam, cam, avg, blurAt, size, horizon, focal, opts }) {
  const prevClear = new THREE.Color();
  // one ant of a file: its slot, the event, its own time since it set off, its seed and size
  return (S, ev, tau, seed, scale, k) => {
    const { rt, rtH, rtV, mat, smat, quad, shadow } = S;
    quad.visible = shadow.visible = true;
    const P = paths[ev.path % paths.length];
    const w = walked(ev, tau, P.L);
    const p = P.at(ev.fwd ? w.d : P.L - w.d);
    const sgn = ev.fwd ? 1 : -1;
    // the view down onto the surface at this row, and the heading on the surface
    const sinE = Math.min(0.95, Math.max(0.08, (p.y - horizon) / focal)), cosE = Math.sqrt(1 - sinE * sinE);
    const sx = sgn * p.dx, sy = sgn * p.dy, n = Math.hypot(sx, sy) || 1;
    const weave = 0.14 * Math.sin(TAU * 1.3 * w.tm + (seed % 97)) * w.moving;   // ants never walk a ruler line
    let heading = Math.atan2(sx / n, sy / n / sinE) + weave, tip = 0;
    pose(ant, w.d / (0.42 * size * scale) + (k ? (seed % 13) / 13 : 0), w.moving, tau * (w.moving > 0.5 ? 5.5 : 3.2) + (k ? seed % 7 : 0), 1 - w.moving);
    ant.root.scale.setScalar(scale);
    const unit = RT / 2.4;
    let delta = -9;
    ant.root.position.set(0, 0, 0);
    occluder.visible = false;
    // the edge of the half of the path it is on (an edge line, extended, can pass under the other end of the path)
    const E = edges[ev.path % paths.length][(ev.fwd ? w.d : P.L - w.d) < P.L / 2 ? 0 : 1];
    if (E) ({ delta, heading, tip } = overEdge(E, p, sx, sy, n, sinE, unit, scale, heading, ant, occluder));
    ant.root.rotation.set(tip, heading, 0, 'YXZ');
    const edgeMode = delta > -1;
    mat.uniforms.uBeyond.value = edgeMode ? 0 : 1;
    cam.position.set(0, 0.1 + sinE * 20, cosE * 20);
    cam.lookAt(0, 0.1, 0);
    const env = avg(p.x - 2 * size, p.y - 1.5 * size, p.x + 2 * size, p.y + 0.5 * size);
    hemi.color.setRGB(...env.map((v) => v * 1.4));
    hemi.groundColor.setRGB(...avg(p.x - size, p.y, p.x + size, p.y + size).map((v) => v * 0.8));
    key.color.setRGB(...avg(p.x - 3 * size, p.y - 6 * size, p.x + 3 * size, p.y - 2 * size).map((v) => Math.min(1, v * 3)));
    const bl = blurAt(p.x, p.y);
    renderAnt({ R, rt, rtH, rtV, mat, scene3, cam, bmat, bscene, bcam, RT, prevClear }, bl);
    // the view centre (0, 0.1, 0) sits 0.1*cosE units above the ground point on screen
    const cy = p.y - 0.1 * cosE * unit;
    mat.uniforms.uBox.value.set(p.x - RT / 2, cy - RT / 2, RT, RT);
    const fade = Math.min(1, tau / 0.15, (ev.dur - tau) / 0.15);
    mat.uniforms.uAlpha.value = fade;
    // the contact shadow stays on the surface: it thins out as the ant goes over the edge
    const onTop = edgeMode ? 1 - Math.min(1, Math.max(0, (delta + 0.36) / 0.5)) : 1;
    const rx = 0.42 * size * scale + bl, ry = 0.42 * size * scale * sinE + 2 + bl;
    smat.uniforms.uBox.value.set(p.x - rx, p.y - ry, 2 * rx, 2 * ry);
    smat.uniforms.uShadow.value = (opts.shadow ?? 0.4) * fade * onTop;
  };
}

// Over a far edge (delta: how far past the edge line the ant is, in units on the surface; the view stays on the ant,
// x right, z toward the viewer): it turns to go straight over, walks over the corner and down the far side, and a
// depth-only block for the surface's body hides what is below and behind the edge. More than a unit before the edge
// nothing changes: -> { delta: -9, heading, tip: 0 }.
function overEdge(E, p, sx, sy, n, sinE, unit, scale, heading, ant, occluder) {
  let delta = -9, tip = 0;
  const ax = (E.A[0] - p.x) / unit, az = (E.A[1] - p.y) / (sinE * unit);
  const ex = E.e[0], ez = E.e[1] / sinE, el = Math.hypot(ex, ez);
  let nx = -ez / el, nz = ex / el;
  if (nx * E.o[0] + nz * (E.o[1] / sinE) < 0) { nx = -nx; nz = -nz; }
  const dl = -(ax * nx + az * nz);
  if (dl > -1) {
    delta = dl;
    // It walks over the corner with its back feet on the top and its front feet down the far side (coming in,
    // the other way round): the body lies on the chord between them, so nothing sticks up above the edge.
    const out = (sx / n) * nx + (sy / n / sinE) * nz >= 0 ? 1 : -1;
    const ft = (out > 0 ? 0.27 : 0.36) * scale, fu = (out > 0 ? 0.36 : 0.27) * scale;    // root to the feet on the top, on the far side
    let along = dl, y = 0, th = 0;
    if (dl >= ft) { along = 0; y = -dl; th = Math.PI / 2; }
    else if (dl > -fu) { along = ((dl - ft) * fu) / (ft + fu); y = (-(dl + fu) * ft) / (ft + fu); th = Math.atan2(dl + fu, ft - dl); }
    tip = out * th;
    ant.root.position.set((along - dl) * nx, y, (along - dl) * nz);
    // it turns to go straight over in the last body length before the edge
    const s = Math.min(1, Math.max(0, (dl + 1) / (1 - fu))), k = s * s * (3 - 2 * s);
    const hn = Math.atan2(out * nx, out * nz);
    heading += k * (((hn - heading + 3 * Math.PI) % TAU) - Math.PI);
    occluder.rotation.y = Math.atan2(nx, nz);
    occluder.position.set(ax - 10 * nx, -10.005, az - 10 * nz);
    occluder.visible = true;
  }
  return { delta, heading, tip };
}

// The ant into its render target, blurred like the surface when it is soft there (bl px), and the renderer put back.
function renderAnt({ R, rt, rtH, rtV, mat, scene3, cam, bmat, bscene, bcam, RT, prevClear }, bl) {
  const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
  R.getClearColor(prevClear);
  R.setRenderTarget(rt);
  R.setClearColor(0x000000, 0);
  R.clear(true, true, true);
  R.autoClear = false;
  R.render(scene3, cam);
  if (bl > 0.3) {
    bmat.uniforms.uSigma.value = bl;
    bmat.uniforms.tSrc.value = rt.texture;
    bmat.uniforms.uStep.value.set(1 / RT, 0);
    R.setRenderTarget(rtH);
    R.render(bscene, bcam);
    bmat.uniforms.tSrc.value = rtH.texture;
    bmat.uniforms.uStep.value.set(0, 1 / RT);
    R.setRenderTarget(rtV);
    R.render(bscene, bcam);
  }
  mat.uniforms.tAnt.value = bl > 0.3 ? rtV.texture : rt.texture;
  R.autoClear = prevAuto;
  R.setRenderTarget(prevRT);
  R.setClearColor(prevClear, prevA);
}
