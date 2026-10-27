// Ambient event: small birds land on a power line or a pole's crossarm, sit a while and fly off (timeline event
// type 'perch'; user 2026-10-19: he liked the birds and wanted more). A bird flies in (flapping with short glides,
// braking with quick beats at the end, swooping up onto the perch from just below it), folds its wings and turns
// to sit across the wire: facing the camera, facing away, or side-on. While it sits it turns its head (the most
// common thing a perched bird does), flicks its tail, now and then fluffs up and shakes off the rain, preens or
// shuffles along the wire. To leave it turns, crouches, drops off the wire and flaps away. A near thunderclap
// flushes every bird on the wires at once (timeline.js). Silhouettes, lit and hazed like the flying birds
// (birds.js shares the flying shape), hidden behind anything clearly nearer. Everything is a pure function of time.
//
// opts: { plate, perches: [{ name, pts: [[x, y], ...] (image coords along the wire's centerline or the top edge of
//   a crossarm, left to right), slots: [x, ...] (image x of each place a bird can sit: clear of insulators, poles
//   and crossing wires), size: a perched bird's length px at 4K (18: bulbul-sized; 11 px read as dots), lift: px
//   above the line where its feet grip (0: on a wire's centerline the belly rests on the wire) }], disp: the perch's plate disparity (0.05: the pole
//   beside it must not hide it), haze (0.25), max (16) }
// Timeline `perch`: { perHour, slots: [count per perch], group: [1, 4], stay: [s, s], together (share of groups
//   leaving at once), atStart (birds already sitting at t = 0), startAfter, first, intro }
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { plateTexture, imagePixels } from './overlay.js';
import { BIRD_SDF } from './birds.js';
import { smooth, hash } from './util.js';

const W = 3840, H = 2160, TAU = 2 * Math.PI;
const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
const bump = (x) => (x > 0 && x < 1 ? Math.sin(Math.PI * x) : 0);

const vert = /* glsl */ `
attribute vec4 aP;     // x, y (px, y down: the feet on the perch, or the body center in flight), size px (length perched, wingspan flying), mode (0 perched, 1 flying)
attribute vec4 aQ;     // perched: sin(yaw) (+1 side-on facing right, 0 facing the camera or away), vis, head turn, tail flick | flying: dir, vis, wing tip, bob px
attribute vec4 aR;     // perched: fluff, crouch, wing flutter, shiver (lengths)
attribute vec4 aS;     // the bird's plate disparity (its perch's), 0, 0, 0
uniform vec2 uRes;
varying vec2 vP;       // bird frame, y up: perched in lengths (feet at 0), flying in wingspans (x forward)
varying vec4 vQ, vR;
varying float vMode, vSize, vDisp;
varying vec2 vUv;
void main() {
  if (aQ.y <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  float s = aP.z;
  vec2 q = position.xy;
  vec2 b, px;
  if (aP.w < 0.5) {
    b = mix(vec2(-0.8, -0.45), vec2(0.8, 1.0), q * 0.5 + 0.5);
    px = aP.xy + vec2(b.x + aR.w, -b.y) * s;
    vP = b;
  } else {
    b = q * 0.75;
    px = aP.xy + vec2(b.x, -b.y) * s + vec2(0.0, aQ.w);
    vP = vec2(b.x * aQ.x, b.y);
  }
  vQ = aQ; vR = aR; vMode = aP.w; vSize = s; vDisp = aS.x;
  vUv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights, tDepth, tBlur, tEnv, tMask;
uniform float uDisp, uHaze, uFlash;
varying vec2 vP;
varying vec4 vQ, vR;
varying float vMode, vSize, vDisp;
varying vec2 vUv;
${BIRD_SDF}
// A small songbird sitting on a wire (feet at the origin, y up, in body lengths). sphi = sin(yaw): side-on it is a
// longer body tilted head-up with the tail angled down behind; from the front or back an upright oval with the
// tail hanging below the wire. turn swings the head (the beak shows only side-on), flick lifts the tail.
float perched(vec2 p, float sphi, float turn, float flick, float fluff, float crouch, float flutter, float px) {
  float pr = abs(sphi), sg = sphi < 0.0 ? -1.0 : 1.0;
  float f = 1.0 + 0.14 * fluff;
  vec2 c = vec2(0.0, mix(0.19, 0.17, pr) - 0.05 * crouch);
  float th = sg * pr * (0.45 + 0.25 * crouch);
  vec2 q = p - c;
  q = vec2(cos(th) * q.x + sin(th) * q.y, -sin(th) * q.x + cos(th) * q.y);
  vec2 rad = vec2(mix(0.14, 0.27, pr), mix(0.21, 0.145, pr)) * f;
  float d = ell(q, vec2(0.0), rad);
  vec2 hc = c + vec2(sg * pr * 0.2 + 0.05 * turn, mix(0.24, 0.16, pr) - 0.04 * crouch);
  float hr = 0.11 * f;
  d = min(d, length(p - hc) - hr);
  float hs = clamp(sphi + turn, -1.0, 1.0);
  float bl = 0.09 * abs(hs);
  if (bl > 0.012) d = min(d, seg(p, hc + vec2(sign(hs) * hr * 0.7, -0.01), hc + vec2(sign(hs) * (hr + bl), -0.025), 0.02));
  vec2 tb = mix(c + vec2(0.0, -rad.y * 0.75), c + vec2(cos(th), sin(th)) * (-rad.x * 0.8), pr);
  vec2 td = normalize(mix(vec2(0.0, -1.0), normalize(vec2(-sg * 0.8, -0.6)), pr));
  float fa = -sg * flick * pr;
  td = vec2(cos(fa) * td.x - sin(fa) * td.y, sin(fa) * td.x + cos(fa) * td.y);
  float tl = mix(0.22, 0.3, pr) * (1.0 - 0.35 * flick * (1.0 - pr));
  d = min(d, seg(p, tb, tb + td * tl, mix(0.045, 0.035, pr)));
  d = min(d, seg(p, vec2(0.0, 0.0), vec2(0.0, c.y - rad.y * 0.6), 0.03));
  if (flutter > 0.01) {
    vec2 sh = c + vec2(0.0, 0.05);
    vec2 wp = sh + vec2(-sg * 0.12, 0.3) * flutter;
    d = min(d, min(seg(p, sh, mix(sh + vec2(0.32, 0.18) * flutter, wp, pr), 0.05), seg(p, sh, mix(sh + vec2(-0.32, 0.18) * flutter, wp, pr), 0.05)));
  }
  return smoothstep(0.6 * px, -0.6 * px, d);
}
void main() {
  float outdoor = texture2D(tLights, vUv).g;
  if (outdoor < 0.004) discard;
  float dp = texture2D(tDepth, vUv).r; dp *= dp;
  float sky = texture2D(tMask, vUv).r;
  // hidden crisply by what is nearer than its perch (the pole beside it is not: depth_fine has no halo)
  float dB = vDisp > 0.0 ? vDisp : uDisp;
  float front = max(sky, 1.0 - smoothstep(dB * 1.1 + 0.004, dB * 1.2 + 0.006, dp));
  if (front <= 0.0) discard;
  float px = 1.0 / vSize;
  float cov = 0.0;
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    if (vMode < 0.5) cov += perched(vP + o * px, vQ.x, vQ.z, vQ.w, vR.x, vR.y, vR.z, px);
    else cov += bird(vP + o * px * vec2(vQ.x, -1.0), vQ.z * 0.5, px);
  }
  cov *= 0.25 * front * outdoor * vQ.y;
  if (cov <= 0.002) discard;
  vec3 env = texture2D(tEnv, vUv).rgb;
  vec3 air = texture2D(tBlur, vUv).rgb;
  vec3 b = vec3(0.05, 0.05, 0.06) * (env * 2.0 + vec3(0.02)) * (1.0 + 0.8 * uFlash);
  gl_FragColor = vec4(mix(b, air, uHaze) * cov, cov);
}`;

function perchTools(P) {
  const pts = P.pts.map(([x, y]) => [x * W, y * H]).sort((a, b) => a[0] - b[0]);
  const yAt = (x) => {
    if (x <= pts[0][0]) return pts[0][1];
    for (let i = 1; i < pts.length; i++) {
      if (x <= pts[i][0]) { const f = (x - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]); return pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f; }
    }
    return pts[pts.length - 1][1];
  };
  return { yAt, slots: (P.slots ?? []).map((u) => u * W), size: P.size ?? 18, lift: P.lift ?? 0 };
}

// The perched pose's little life at tau seconds after touchdown: slots of 2.4 s, each holding at most one action.
function idle(m, tau, L) {
  const S = 2.4;
  const k = Math.floor(tau / S);
  let turn = 0, flick = 0, fluff = 0, crouch = 0, flutter = 0, shiver = 0, shift = 0;
  // head turns hold until the next one: find the latest two turn slots at or before now
  let cur = null, prev = null;
  for (let j = k; j >= Math.max(0, k - 40) && !prev; j--) {
    const r = hash(m.seed, j), st = j * S + hash(m.seed, j + 1000) * 1.4;
    if (r < 0.42 && st <= tau) {
      const tgt = (hash(m.seed, j + 2000) * 2 - 1) * 0.9;
      if (!cur) cur = { st, tgt }; else prev = { st, tgt };
    }
  }
  if (cur) turn = (prev?.tgt ?? 0) + (cur.tgt - (prev?.tgt ?? 0)) * smooth((tau - cur.st) / 0.12);
  // shuffles along the perch hold too: the offset of the latest shuffle
  let sh = null, shPrev = null;
  for (let j = k; j >= Math.max(0, k - 120) && !shPrev; j--) {
    const r = hash(m.seed, j), st = j * S + hash(m.seed, j + 1000) * 1.4;
    if (r >= 0.69 && r < 0.72 && st <= tau) {
      const off = (hash(m.seed, j + 3000) - 0.5) * 0.7 * L;
      if (!sh) sh = { st, off }; else shPrev = { st, off };
    }
  }
  if (sh) {
    const u = (tau - sh.st) / 0.3;
    shift = (shPrev?.off ?? 0) + (sh.off - (shPrev?.off ?? 0)) * smooth(u);
    flutter = Math.max(flutter, 0.5 * bump(u));
  }
  const r = hash(m.seed, k), st = k * S + hash(m.seed, k + 1000) * 1.4, u = tau - st;
  if (u >= 0) {
    if (r >= 0.42 && r < 0.58) flick = 0.45 * bump(u / 0.28);
    else if (r >= 0.58 && r < 0.64) {
      fluff = bump(u / 0.7);
      flutter = Math.max(flutter, 0.6 * bump(u / 0.35));
      shiver = 0.04 * Math.sin(TAU * 14 * u) * fluff;
    } else if (r >= 0.64 && r < 0.69) {
      const w = smooth(u / 0.25) * smooth((1.4 - u) / 0.25);
      turn = turn + (-Math.sign(m.face || 1) * 0.9 - turn) * w;
      crouch = 0.25 * w;
    }
  }
  return { turn, flick, fluff, crouch, flutter, shiver, shift };
}

// Flying in: from the start point to just below the perch, then a swoop up onto it; quick braking beats at the end.
function arrive(m, u, P, L) {
  const span = 2.1 * L;
  const cx = P.x, cy = P.y - 0.2 * L;
  const sx = cx + m.inDx, sy = cy + m.inDy, dip = 0.5 * L;
  const e = 1 - (1 - u) ** 1.7;
  const x = sx + (cx - sx) * e;
  const y = u < 0.85 ? sy + (cy + dip - sy) * smooth(u / 0.85) : cy + dip * (1 - smooth((u - 0.85) / 0.15));
  const T = m.inT, tau = u * T;
  const g = Math.sin(TAU * (tau / 2.6 + (m.seed % 97) / 97));
  const glide = u < 0.75 ? clamp01((g - 0.55) / 0.3) : 0;
  const brake = smooth((u - 0.8) / 0.15);
  const ph = TAU * (m.hz * (1 + 0.6 * brake) * tau + (m.seed % 89) / 89);
  const tip = (1 - glide) * (0.15 + (0.85 + 0.15 * brake) * Math.sin(ph)) + glide * 0.18;
  const bob = -(1 - glide) * 0.06 * span * Math.sin(ph);
  return { x, y, span, tip, bob, dir: Math.sign(cx - sx) || 1 };
}

// Leaving: a drop off the perch as the wings open, then a climbing, speeding flight out.
function depart(m, u, P, L) {
  const span = 2.1 * L;
  const cx = P.x, cy = P.y - 0.2 * L;
  const ex = cx + m.outDx, ey = cy + m.outDy;
  const T = m.outT, tau = u * T;
  const e = u ** 1.5;
  const x = cx + (ex - cx) * e;
  const y = cy + (ey - cy) * smooth(u) + 0.6 * L * bump(tau / 0.45);
  const ph = TAU * (m.hz * (1.35 - 0.35 * smooth(tau / 1.2)) * tau + (m.seed % 89) / 89 + 0.25);
  const tip = 0.15 + 0.85 * Math.sin(ph);
  const bob = -0.06 * span * Math.sin(ph);
  return { x, y, span, tip, bob, dir: Math.sign(m.outDx) || 1 };
}

// Instances (1, or 2 while the wings fold or open) for one bird at time t: [state, weight].
export function perchBird(ev, m, t, perches) {
  const P0 = perches[ev.perch];
  if (!P0) return [];
  const L = P0.size * (m.size ?? 1);
  const t0 = ev.t + m.land, tLand = t0 + m.inT, tLeave = ev.t + m.leave, tEnd = tLeave + m.outT;
  if (t < t0 || t > tEnd) return [];
  const sx = P0.slots[m.slot % P0.slots.length];
  const out = [];
  const flying = (s, vis) => out.push({ mode: 1, x: s.x, y: s.y, size: s.span, a: s.dir, vis, tip: s.tip, bob: s.bob });
  const perchedAt = (tau, vis) => {
    const id = idle(m, tau, L);
    const x = sx + id.shift;
    const P = { x, y: P0.yAt(x) - P0.lift };
    const dirIn = Math.sign(m.inDx) ? -Math.sign(m.inDx) : 1, dirOut = Math.sign(m.outDx) || 1;
    const stay = tLeave - tLand;
    let sphi = m.face + (dirIn - m.face) * (1 - smooth((tau - 0.2) / 0.4));
    sphi += (dirOut - sphi) * smooth((tau - (stay - 0.55)) / 0.3);
    const land = bump(tau / 0.35), leave = smooth((tau - (stay - 0.22)) / 0.2);
    out.push({
      mode: 0, x: P.x, y: P.y, size: L, a: sphi, vis, turn: id.turn * (1 - leave), flick: id.flick,
      fluff: id.fluff, crouch: Math.max(id.crouch, 0.6 * land, leave), flutter: Math.max(id.flutter, 0.8 * (1 - smooth(tau / 0.25))), shiver: id.shiver,
    });
    return P;
  };
  const Pslot = { x: sx, y: P0.yAt(sx) - P0.lift };
  const X = 0.06;   // wings fold / open over this long (two instances crossfading)
  if (t < tLand) {
    const u = (t - t0) / m.inT;
    flying(arrive(m, u, Pslot, L), Math.min(1, (t - t0) / 0.5) * (t > tLand - X ? (tLand - t) / X : 1));
    if (t > tLand - X) perchedAt(0, 1 - (tLand - t) / X);
  } else if (t < tLeave) {
    perchedAt(t - tLand, 1);
  } else {
    const P = { x: sx, y: Pslot.y };
    const u = (t - tLeave) / m.outT;
    if (t < tLeave + X) perchedAt(tLeave - tLand, 1 - (t - tLeave) / X);
    flying(depart(m, u, P, L), Math.min(1, (t - tLeave) / X, (tEnd - t) / 0.5));
  }
  return out;
}

export async function perchLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'perch');
  if (!evs.length || !opts.perches?.length) return null;
  const perches = opts.perches.map(perchTools);
  const [tLights, tDepth8, tBlur, tEnv, tMask, tFine] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'depth8.png'),
    plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'env.png', { srgb: true }), plateTexture(opts.plate, 'masks.png'),
    plateTexture(opts.plate, 'depth_fine.png', { optional: true }),
  ]);
  const tDepth = tFine.image?.width > 1 ? tFine : tDepth8;
  // each slot's disparity: the perch's own (the wire or crossarm under the bird), from the same depth map
  const dimg = await imagePixels(`/out/plates/${opts.plate}/${tFine.image?.width > 1 ? 'depth_fine.png' : 'depth8.png'}`);
  const dispAt = (x, y) => {
    if (!dimg) return opts.disp ?? 0.05;
    const vals = [];
    for (let j = -3; j <= 3; j++) {
      for (let i = -3; i <= 3; i++) {
        const u = Math.min(dimg.width - 1, Math.max(0, Math.round(((x + i) * dimg.width) / W))), v = Math.min(dimg.height - 1, Math.max(0, Math.round(((y + j) * dimg.height) / H)));
        const s = dimg.data[(v * dimg.width + u) * 4] / 255;
        vals.push(s * s);
      }
    }
    return Math.max(...vals);
  };
  for (const P of perches) P.slotDisp = P.slots.map((x) => dispAt(x, P.yAt(x)));
  const MAX = opts.max ?? 16;
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = MAX;
  const attr = (n) => { const a = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4); a.setUsage(THREE.DynamicDrawUsage); g.setAttribute(n, a); return a; };
  const aP = attr('aP'), aQ = attr('aQ'), aR = attr('aR'), aS = attr('aS');
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    side: THREE.DoubleSide,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tDepth: { value: tDepth }, tBlur: { value: tBlur }, tEnv: { value: tEnv }, tMask: { value: tMask },
      uRes: { value: new THREE.Vector2(W, H) }, uDisp: { value: opts.disp ?? 0.05 }, uHaze: { value: opts.haze ?? 0.25 }, uFlash: { value: 0 },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 6;   // on the plate, under the rain
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const longest = Math.max(...evs.map((e) => e.dur ?? 0), 0);
  ctx.animate((t) => {
    let k = 0;
    for (const ev of evs) {
      if (ev.t > t) break;
      if (t > ev.t + (ev.dur ?? longest)) continue;
      for (const m of ev.members) {
        const P0 = perches[ev.perch];
        const sd = P0 ? P0.slotDisp[m.slot % P0.slotDisp.length] : 0;
        for (const s of perchBird(ev, m, t, perches)) {
          if (k >= MAX || s.vis <= 0) continue;
          aS.array.set([sd, 0, 0, 0], k * 4);
          if (s.mode === 0) {
            aP.array.set([s.x, s.y, s.size, 0], k * 4);
            aQ.array.set([s.a, s.vis, s.turn, s.flick], k * 4);
            aR.array.set([s.fluff, s.crouch, s.flutter, s.shiver], k * 4);
          } else {
            aP.array.set([s.x, s.y, s.size, 1], k * 4);
            aQ.array.set([s.a, s.vis, s.tip, s.bob], k * 4);
            aR.array.set([0, 0, 0, 0], k * 4);
          }
          k++;
        }
      }
    }
    for (let i = k; i < MAX; i++) aQ.array[i * 4 + 1] = 0;
    aP.needsUpdate = aQ.needsUpdate = aR.needsUpdate = aS.needsUpdate = true;
    mesh.visible = k > 0;
    mat.uniforms.uFlash.value = flashAt(ctx.timeline, t).flash;
  });
  return mesh;
}
