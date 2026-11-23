// A waterwheel turning the whole video (Truman 2026-11-08: the Skyrim mill's waterwheel turning nonstop).
// tools/wheel_layer.py takes the painted wheel apart (tools/cozy/plate/wheel.py: the front rim's ellipse, the hub where
// the painted spokes meet, the projective map of the wheel's disk, the depth to the back rim, three small textures
// that repeat as it turns) and repaints the wall behind it on the plate; this layer draws it turned:
//   front face   the rim (rim.png, periodic along it) over 8 spokes evenly spaced, each the painted spoke
//                straightened (spoke.png), in the wheel's own frame: the inverse of the projective map gives the
//                disk's angle, the turn is subtracted, so it turns as a wheel in perspective does
//   band         the paddles between the rims on the side the wheel shows (band.png, one paddle period): a point
//                there is a rim point plus s times the depth, found by the quadratic, its wheel angle turned likewise
//   back face    the front's rim and spokes moved by the depth and darkened, seen through the gaps
// The trestle, the hub cap (occ.png R) and the water (G) stay painted in front; under the waterline the wheel shows
// mirrored, rippled and fading with depth (its reflection; the trestle's stays painted on the plate). Whole turns per
// loop with a speed that swells a few percent over half a minute (seamless): a slow, steady mill.
//
// opts: { plate, turn (s per turn, wheel.json turn_s), vary (0.03), reflect (0.32: how much the water mirrors),
//   ripple (px, 2.2), water (false, or water coming off the paddles: true or { radius (m, 2.4: the wheel's own, for its
//   scale), drain (deg of rise a paddle sheds water over, 55), drops (per paddle pass, 120), splash (drops thrown up
//   where a paddle goes in and comes out, 20), stream (s a drop stays a thread back to the paddle, 0.12), color (glint,
//   [0.7, 0.78, 0.86]), alpha (0.7), width (px, 1.8) }), renderOrder (4.5) }
//
// Water off the paddles (opts.water; Truman's ideas round on the Sleeping Hound Inn, 2026-11-15: the wheel turned dry):
// a paddle coming up out of the river sheds the water it lifted from its outer edge, most of it in its first few
// degrees of rise, the rest dripping off over the next 55; each drop leaves with the paddle's own speed and a little
// outward push, falls under gravity at the wheel's scale (its radius in px over `radius` m) and is drawn as the streak
// a 1/60 s shutter sees, hidden behind the trestle (occ.png R); where it lands it makes a small flat ring on the water.
// A paddle going in throws up a few drops. Every drop is a pure function of the wheel's angle (its age is how far its
// paddle has turned since it shed it), and the angle has whole turns per loop: the drops repeat exactly every loop.
import * as THREE from 'three';
import { plateTexture, fetchJson, PREMUL, instancedQuad } from './overlay.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;

const vert = /* glsl */ `
uniform vec4 uBox;
varying vec2 vPx;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = uBox.xy + vec2(q.x, 1.0 - q.y) * uBox.zw;
  gl_Position = vec4(vPx.x / ${W}.0 * 2.0 - 1.0, 1.0 - vPx.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tRim;
uniform sampler2D tSpoke;
uniform sampler2D tBand;
uniform sampler2D tOcc;
uniform vec4 uBox;        // the layer's box (px): occ.png covers it
uniform vec2 uC;          // the front rim ellipse's center (px)
uniform vec4 uMi;         // inverse of the ellipse's 2x2 map, row major (image offset -> unit circle, y up)
uniform mat3 uKi;         // inverse of the disk's projective map (normalized ellipse -> the wheel's own disk)
uniform vec2 uD;          // depth: the back rim is the front's ellipse moved by this (px)
uniform vec4 uSpoke;      // first spoke's angle, spoke center across (local), half width, count
uniform vec2 uSpokeT;     // the spoke texture's run along the radius
uniform vec4 uRim;        // rim texture: rho from, rho to, angle start, angle period
uniform vec2 uBand;       // paddle period, phase (rad)
uniform float uPhi;       // the turn so far (rad, signed by its direction)
uniform float uBack;      // how dark the back face is
uniform vec4 uWater;      // waterline: x0, y0, x1, y1 (px)
uniform vec4 uRefl;       // reflection: depth (px), strength, ripple (px), ripple phase
varying vec2 vPx;
const float PI = 3.14159265359;

vec2 normd(vec2 p) {       // image px -> the ellipse's unit circle (y up)
  vec2 o = p - uC;
  return vec2(uMi.x * o.x + uMi.y * o.y, uMi.z * o.x + uMi.w * o.y);
}
vec2 disk(vec2 n) {        // the ellipse's normalized coords -> the wheel's own disk
  vec3 l = uKi * vec3(n, 1.0);
  return l.xy / l.z;
}
// premultiplied: the face at p (front when shift is 0, back when shift is the depth)
vec4 face(vec2 p) {
  vec2 l = disk(normd(p));
  float rho = length(l);
  if (rho > uRim.y) return vec4(0.0);
  float th = atan(l.y, l.x) - uPhi;
  vec4 acc = vec4(0.0);
  // the nearest spoke
  float step = 2.0 * PI / uSpoke.w;
  float k = floor((th - uSpoke.x) / step + 0.5);
  float a = th - (uSpoke.x + k * step);
  float t = rho * cos(a), w = rho * sin(a);
  float u = (w - (uSpoke.y - 1.6 * uSpoke.z)) / (3.2 * uSpoke.z);
  float v = (t - uSpokeT.x) / (uSpokeT.y - uSpokeT.x);
  if (u >= 0.0 && u < 1.0 && v >= 0.0 && v < 1.0 && t > 0.0) {
    vec4 s = texture2D(tSpoke, vec2(u, 1.0 - v));
    acc = vec4(s.rgb * s.a, s.a);
  }
  // the rim over it
  float rv = (rho - uRim.x) / (uRim.y - uRim.x);
  if (rv >= 0.0 && rv < 1.0) {
    float ru = mod(th - uRim.z, uRim.w) / uRim.w;
    vec4 r = texture2D(tRim, vec2(ru, 1.0 - rv));
    acc = vec4(r.rgb * r.a, r.a) + acc * (1.0 - r.a);
  }
  return acc;
}
// premultiplied: the paddle band at p, on the side the wheel shows
vec4 band(vec2 p) {
  vec2 e = vec2(uMi.x * uD.x + uMi.y * uD.y, uMi.z * uD.x + uMi.w * uD.y);
  vec2 wv = normd(p);
  float A = dot(e, e), B = -2.0 * dot(wv, e), C = dot(wv, wv) - 1.0;
  float disc = B * B - 4.0 * A * C;
  if (disc < 0.0) return vec4(0.0);
  float sq = sqrt(disc);
  for (int i = 0; i < 2; i++) {
    float s = (-B + (i == 0 ? -sq : sq)) / (2.0 * A);
    if (s < 0.0 || s > 1.0) continue;
    vec2 q = wv - s * e;
    if (dot(q, e) <= 0.0) continue;
    vec2 l = disk(q);
    float psi = atan(l.y, l.x) - uPhi;
    float u = mod(psi - uBand.y + 0.5 * uBand.x, uBand.x) / uBand.x;
    vec4 b = texture2D(tBand, vec2(u, 1.0 - s));
    return vec4(b.rgb * b.a, b.a);
  }
  return vec4(0.0);
}
vec4 wheelAt(vec2 p) {
  vec4 acc = face(p);
  vec4 b = band(p);
  acc += (1.0 - acc.a) * b;
  vec4 bk = face(p - uD);
  bk.rgb *= uBack;
  acc += (1.0 - acc.a) * bk;
  return acc;
}
vec4 occAt(vec2 p) {
  vec2 uv = (p - uBox.xy) / uBox.zw;
  return texture2D(tOcc, vec2(uv.x, 1.0 - uv.y));
}
void main() {
  float yw = mix(uWater.y, uWater.w, clamp((vPx.x - uWater.x) / max(uWater.z - uWater.x, 1.0), 0.0, 1.0));
  if (vPx.y < yw) {
    vec4 c = wheelAt(vPx);
    gl_FragColor = c * (1.0 - occAt(vPx).r);
    return;
  }
  // the reflection: mirrored about the waterline, rippled, fading with depth; the trestle's own stays painted
  float dd = vPx.y - yw;
  if (dd > uRefl.x || uRefl.y <= 0.0) discard;
  float r = uRefl.z * (0.6 + dd / uRefl.x);
  vec2 q = vec2(vPx.x + r * sin(vPx.y * 0.31 + uRefl.w) + 0.5 * r * sin(vPx.y * 0.77 - 1.7 * uRefl.w), yw - dd - 1.0);
  vec4 c = wheelAt(q) * (1.0 - occAt(q).r);
  float f = uRefl.y * (1.0 - dd / uRefl.x);
  gl_FragColor = c * f;
}`;

export async function wheelLayer(ctx, opts) {
  const plate = opts.plate;
  const g = await fetchJson(`/out/plates/${plate}/wheel/wheel.json`, { hint: 'run tools/wheel_layer.py with hand.json "wheel"' });
  const [tRim, tSpoke, tBand, tOcc] = await Promise.all(['rim', 'spoke', 'band', 'occ'].map((n) => plateTexture(plate, `wheel/${n}.png`, { srgb: n !== 'occ' })));
  for (const t of [tRim, tBand]) { t.wrapS = THREE.RepeatWrapping; t.needsUpdate = true; }
  const L = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const cyc = (hz) => Math.max(1, Math.round(hz * L));
  const o = { vary: 0.03, reflect: 0.32, ripple: 2.2, ...opts };
  const turnS = o.turn ?? g.turn_s ?? 16;
  const n = cyc(1 / turnS), k = cyc(1 / 37), nr = cyc(1 / 2.6);
  const [cx, cy, a, b, al] = g.rim;
  // the ellipse's 2x2 map (unit circle, y up -> image px, y down) and its inverse
  const ca = Math.cos(al), sa = Math.sin(al);
  const M = [a * ca, b * sa, a * sa, -b * ca];          // [[a ca, -b sa], [a sa, b ca]] @ diag(1, -1)
  const det = M[0] * M[3] - M[1] * M[2];
  const Mi = new THREE.Vector4(M[3] / det, -M[1] / det, -M[2] / det, M[0] / det);
  // the disk's projective map: a boost that keeps the unit circle and takes its center to the hub
  const [hx, hy] = g.hn;
  const r = Math.hypot(hx, hy), psi = Math.atan2(hy, hx), eta = Math.atanh(Math.min(r, 0.95));
  const R = (t) => new THREE.Matrix3().set(Math.cos(t), -Math.sin(t), 0, Math.sin(t), Math.cos(t), 0, 0, 0, 1);
  const B = new THREE.Matrix3().set(Math.cosh(eta), 0, Math.sinh(eta), 0, 1, 0, Math.sinh(eta), 0, Math.cosh(eta));
  const K = R(psi).multiply(B).multiply(R(-psi));
  const Ki = K.clone().invert();
  const wl = g.waterline ?? [[0, 1e6], [W, 1e6]];
  const box = g.box;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      tRim: { value: tRim }, tSpoke: { value: tSpoke }, tBand: { value: tBand }, tOcc: { value: tOcc },
      uBox: { value: new THREE.Vector4(box[0], box[1], box[2] - box[0], box[3] - box[1]) },
      uC: { value: new THREE.Vector2(cx, cy) }, uMi: { value: Mi }, uKi: { value: Ki }, uD: { value: new THREE.Vector2(...g.d) },
      uSpoke: { value: new THREE.Vector4(g.spoke0, g.spoke_c, g.spoke_h, g.spokes) }, uSpokeT: { value: new THREE.Vector2(...g.spoke_t) },
      uRim: { value: new THREE.Vector4(g.rim_tex_rho[0], g.rim_tex_rho[1], g.rim_start, g.rim_period) },
      uBand: { value: new THREE.Vector2(g.paddle_period, g.paddle_phase) },
      uPhi: { value: 0 }, uBack: { value: g.back_dark ?? 0.45 },
      uWater: { value: new THREE.Vector4(wl[0][0], wl[0][1], wl[wl.length - 1][0], wl[wl.length - 1][1]) },
      uRefl: { value: new THREE.Vector4(g.reflect ?? 0, o.reflect, o.ripple, 0) },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = o.renderOrder ?? 4.5;      // on the plate and its river, under the fire, the critters and the birds
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const dir = g.dir ?? 1;
  const ph = TAU * ((ctx.seed * 0.6180339887) % 1);
  // the turn so far at t (rad, signed by the direction) and its rate (rad/s): whole turns per loop, the speed swelling
  // +-vary over ~37 s (a periodic term: the seam is exact)
  const phiAt = (tt) => dir * (TAU * n * tt / L + ((o.vary * n) / k) * Math.sin(TAU * k * tt / L + ph));
  const omegaAt = (tt) => dir * (TAU * n / L) * (1 + o.vary * Math.cos(TAU * k * tt / L + ph));
  const water = o.water ? await wheelWater(ctx, g, { M, K, cx, cy, box, plate }, o.water === true ? {} : o.water, n, phiAt, omegaAt, L, tOcc) : null;
  ctx.animate((t) => {
    const tt = ((t % L) + L) % L;
    mat.uniforms.uPhi.value = phiAt(tt);
    mat.uniforms.uRefl.value.w = TAU * nr * tt / L;
    if (water) water(tt);
  });
  return mat;
}

const dropVert = /* glsl */ `
attribute vec4 aSeg;      // the streak's tail and head (px)
attribute vec2 aWA;       // width (px), alpha
varying vec2 vQ;
varying float vA, vLen, vHw;
varying vec2 vPx;
void main() {
  vec2 a = aSeg.xy, b = aSeg.zw;
  vec2 d = b - a;
  float len = max(length(d), 0.001);
  vec2 dir = d / len, nrm = vec2(-dir.y, dir.x);
  float hw = 0.5 * aWA.x + 1.0;
  vec2 q = position.xy;
  // the quad runs from half a width behind the tail to half a width past the head (round ends)
  vec2 p = mix(a - dir * hw, b + dir * hw, q.y * 0.5 + 0.5) + nrm * q.x * hw;
  vQ = vec2(q.x * hw / max(0.5 * aWA.x, 0.5), (q.y * 0.5 + 0.5) * (len + 2.0 * hw) - hw);
  vA = aWA.y;
  vLen = len;
  vHw = hw;
  vPx = p;
  gl_Position = aWA.y > 0.0 ? vec4(p.x / 3840.0 * 2.0 - 1.0, 1.0 - p.y / 2160.0 * 2.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;
// water is lit like what is around it: the plate behind it, brightened (it catches the moonlight and the sky), toward a
// pale glint color; flat pale dashes read as confetti on the dark wheel (first try)
const dropFrag = /* glsl */ `
uniform sampler2D tOcc, tBlur;
uniform vec4 uBox;
uniform vec3 uColor;
varying vec2 vQ;
varying float vA, vLen, vHw;
varying vec2 vPx;
void main() {
  float across = exp(-vQ.x * vQ.x * 3.0);
  float ends = smoothstep(-vHw, vHw * 0.3, vQ.y) * (1.0 - smoothstep(vLen - vHw * 0.3, vLen + vHw, vQ.y));
  float a = vA * across * ends;
  vec2 uv = (vPx - uBox.xy) / uBox.zw;
  if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) a *= 1.0 - texture2D(tOcc, vec2(uv.x, 1.0 - uv.y)).r;
  if (a < 0.003) discard;
  vec3 bg = texture2D(tBlur, vec2(vPx.x / 3840.0, 1.0 - vPx.y / 2160.0)).rgb;
  vec3 c = mix(bg * 2.2, uColor, 0.4);
  gl_FragColor = vec4(c * a, a);
}`;
const ringVert = /* glsl */ `
attribute vec4 aRing;     // center (px), radius (px), alpha
varying vec2 vD;
varying float vR, vA;
varying vec2 vPx;
void main() {
  float r = aRing.z + 2.0;
  vec2 p = aRing.xy + position.xy * vec2(r, r * 0.22);
  vD = position.xy * r;
  vR = aRing.z;
  vA = aRing.w;
  vPx = p;
  gl_Position = aRing.w > 0.0 ? vec4(p.x / 3840.0 * 2.0 - 1.0, 1.0 - p.y / 2160.0 * 2.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;
const ringFrag = /* glsl */ `
uniform sampler2D tOcc;
uniform vec4 uBox;
uniform vec3 uColor;
varying vec2 vD;
varying float vR, vA;
varying vec2 vPx;
void main() {
  float d = length(vD) - vR;
  float a = vA * exp(-d * d / 0.7);
  vec2 uv = (vPx - uBox.xy) / uBox.zw;
  if (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) a *= 1.0 - texture2D(tOcc, vec2(uv.x, 1.0 - uv.y)).r;
  if (a < 0.003) discard;
  gl_FragColor = vec4(uColor * a, a);
}`;

// A small, fast hash of integers to 0..1 (deterministic: no Math.random)
function hash3(a, b, c) {
  let h = Math.imul(a + 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x7f4a7c15, 0xc2b2ae35) ^ Math.imul(c + 0x165667b1, 0x27d4eb2f);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}

// The water off the paddles (see the header): returns (tt) => update for the loop time tt.
async function wheelWater(ctx, g, { M, K, cx, cy, box, plate }, w, turns, phiAt, omegaAt, L, tOcc) {
  const radiusM = w.radius ?? 2.4, ppm = g.rim[3] / radiusM, grav = 9.81 * ppm;
  const drainA = ((w.drain ?? 55) * Math.PI) / 180, J = w.drops ?? 120, S = w.splash ?? 20;
  const P = g.paddles ?? 23, per = g.paddle_period ?? TAU / P, ph0 = g.paddle_phase ?? 0, dir = g.dir ?? 1;
  const wl = g.waterline ?? [[0, 1e6], [W, 1e6]];
  const yw = (x) => wl[0][1] + (wl[wl.length - 1][1] - wl[0][1]) * Math.min(1, Math.max(0, (x - wl[0][0]) / Math.max(wl[wl.length - 1][0] - wl[0][0], 1)));
  // the wheel's own disk (angle th, radius 1, depth s 0..1 from the front rim to the back) -> image px
  const fwd = (th, s) => {
    const v = new THREE.Vector3(Math.cos(th), Math.sin(th), 1).applyMatrix3(K);
    const nx = v.x / v.z, ny = v.y / v.z;
    return [cx + M[0] * nx + M[1] * ny + s * g.d[0], cy + M[2] * nx + M[3] * ny + s * g.d[1]];
  };
  // where the rim's middle crosses the waterline going in and coming out (the paddles turn dir: counterclockwise as seen
  // for dir 1, so they go in on the side the river comes from)
  const cross = (a0, a1) => {
    let best = a0, bd = Infinity;
    for (let i = 0; i <= 720; i++) {
      const th = a0 + ((a1 - a0) * i) / 720, p = fwd(th, 0.5), d = Math.abs(p[1] - yw(p[0]));
      if (d < bd) { bd = d; best = th; }
    }
    return best;
  };
  const bottom = 1.5 * Math.PI;
  const out = dir > 0 ? cross(bottom, bottom + 0.5 * Math.PI) : cross(bottom - 0.5 * Math.PI, bottom);
  const inn = dir > 0 ? cross(bottom - 0.5 * Math.PI, bottom) : cross(bottom, bottom + 0.5 * Math.PI);
  const hub = fwd(0, 0.5).map((v, i) => (v + fwd(Math.PI, 0.5)[i]) / 2);
  const N = P * (J + S);
  const sg = instancedQuad(N), rg = instancedQuad(N);
  const aSeg = new THREE.InstancedBufferAttribute(new Float32Array(N * 4), 4), aWA = new THREE.InstancedBufferAttribute(new Float32Array(N * 2), 2);
  const aRing = new THREE.InstancedBufferAttribute(new Float32Array(N * 4), 4);
  sg.setAttribute('aSeg', aSeg);
  sg.setAttribute('aWA', aWA);
  rg.setAttribute('aRing', aRing);
  const col = new THREE.Vector3(...(w.color ?? [0.7, 0.78, 0.86]));
  const tBlur = await plateTexture(plate, 'blur.png', { srgb: true });
  const boxV = new THREE.Vector4(box[0], box[1], box[2] - box[0], box[3] - box[1]);
  const mk = (vs, fs) => new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, ...PREMUL,
    uniforms: { tOcc: { value: tOcc }, tBlur: { value: tBlur }, uBox: { value: boxV }, uColor: { value: col } } });
  const streaks = new THREE.Mesh(sg, mk(dropVert, dropFrag)), rings = new THREE.Mesh(rg, mk(ringVert, ringFrag));
  for (const m of [streaks, rings]) { m.frustumCulled = false; m.userData.noAO = true; m.renderOrder = 4.6; ctx.add(m); }
  const alpha = w.alpha ?? 0.7, width = w.width ?? 1.8, shutter = 1 / 60, ringLife = 0.25, streamT = w.stream ?? 0.12;
  // one drop: left from p0 with velocity v0 (px/s) tau s ago -> its streak and its ring on the water once it lands
  const put = (i, p0, v0, tau, a, wd) => {
    const at = (s) => [p0[0] + v0[0] * s, p0[1] + v0[1] * s + 0.5 * grav * s * s];
    const yl = yw(p0[0]);
    // when it reaches the water: p0.y + vy s + g s^2 / 2 = yl
    const disc = v0[1] * v0[1] + 2 * grav * Math.max(0, yl - p0[1]);
    const land = (-v0[1] + Math.sqrt(disc)) / grav;
    if (tau < land) {
      // fresh off the paddle it is still a thread of water back to the edge; after streamT s it is a drop, drawn as the
      // streak a 1/60 s shutter sees
      const h = at(tau), tl = at(tau < streamT ? 0 : Math.max(0, tau - shutter));
      aSeg.array.set([tl[0], tl[1], h[0], Math.min(h[1], yl)], i * 4);
      aWA.array.set([wd, a * Math.min(1, tau / 0.04)], i * 2);
      aRing.array.set([0, 0, 0, 0], i * 4);
    } else {
      aWA.array.set([0, 0], i * 2);
      const age = tau - land;
      if (age < ringLife) {
        const x = at(land)[0];
        // a faint, small, flat ring: crisp bright ones in a row along the waterline read as drawn circles (first try)
        aRing.array.set([x, yw(x), 1.2 + 4.5 * Math.pow(age / ringLife, 0.6), 0.16 * a * (1 - age / ringLife) ** 2], i * 4);
      } else aRing.array.set([0, 0, 0, 0], i * 4);
    }
  };
  return (tt) => {
    const phi = phiAt(tt), om = Math.max(1e-4, Math.abs(omegaAt(tt)));
    let i = 0;
    for (let p = 0; p < P; p++) {
      const thP = ph0 + p * per + phi;        // this paddle's angle now (unwrapped)
      // water shed as it comes up: slot j left when the paddle passed out + its share of the drain arc
      for (let j = 0; j < J; j++, i++) {
        const thE = out + dir * drainA * Math.pow((j + 0.5) / J, 1.25);
        const turned = dir * (thP - thE);
        const m = Math.floor(turned / TAU);
        const ang = turned - m * TAU, tau = ang / om;
        const rnd = (c) => hash3(p, j, (((m % turns) + turns) % turns) * 8 + c);
        if (tau > 1.6 || rnd(0) > Math.exp((-1.3 * j) / J) * 0.9) { aWA.array.set([0, 0], i * 2); aRing.array.set([0, 0, 0, 0], i * 4); continue; }
        const s = rnd(1), th = thE + dir * (rnd(2) - 0.5) * (drainA / J);
        const p0 = fwd(th, s), p1 = fwd(th + dir * 0.01, s);
        const rad = [p0[0] - hub[0], p0[1] - hub[1]], rl = Math.hypot(rad[0], rad[1]) || 1;
        const push = (0.15 + 0.25 * rnd(3)) * ppm;
        const v0 = [((p1[0] - p0[0]) / 0.01) * om + (rad[0] / rl) * push + (rnd(4) - 0.5) * 0.2 * ppm,
          ((p1[1] - p0[1]) / 0.01) * om + (rad[1] / rl) * push + (rnd(5) - 0.5) * 0.2 * ppm];
        put(i, p0, v0, tau, alpha * (0.55 + 0.45 * rnd(6)), width * (0.75 + 0.5 * rnd(7)));
      }
      // drops thrown up as it goes in (slapping the water) and as it comes out (the water it lifts spilling off its face):
      // the churn where the wheel meets the river
      for (let j = 0; j < S; j++, i++) {
        const at0 = j % 2 ? out : inn;
        const turned = dir * (thP - at0);
        const m = Math.floor(turned / TAU), tau = (turned - m * TAU) / om;
        const rnd = (c) => hash3(p + 101, j, (((m % turns) + turns) % turns) * 8 + c);
        if (tau > 1.2 || rnd(0) > 0.75) { aWA.array.set([0, 0], i * 2); aRing.array.set([0, 0, 0, 0], i * 4); continue; }
        const p0 = fwd(at0 + dir * (rnd(6) - 0.5) * 0.12, rnd(1));
        p0[1] = yw(p0[0]) - 1;
        const v0 = [(rnd(2) - 0.5) * 0.9 * ppm, -(0.4 + 1.0 * rnd(3)) * ppm];
        put(i, p0, v0, tau, alpha * 0.8 * (0.5 + 0.5 * rnd(4)), width * (0.7 + 0.4 * rnd(5)));
      }
    }
    aSeg.needsUpdate = aWA.needsUpdate = aRing.needsUpdate = true;
  };
}
