// The northern lights rippling (Truman 2026-11-08: the Skyrim mill, the aurora as one of the things that move the
// whole video). tools/cozy/plate/aurora.py lifts the painted aurora's light off the plate's sky (signed: aurora.png
// what lies above the smooth base, aurora_neg.png the paint darker than it), so the plate keeps a smooth night sky with
// its stars and this layer adds the light back, moving:
//   folds   the curtain's shape sways sideways in slow waves that travel along it, the hem more than the top, so the
//           drapery seems to fold and unfold (the painted rays bend with it)
//   rays    fine vertical striations drift along the curtain and brighten and fade, a little
//   waves   brightness runs along the arc in long waves (activity moving across the sky), and the whole display
//           breathes over minutes
//   surges  a few times a loop a brightening sweeps across the sky over half a minute, the rays livelier while it
//           passes (seeded, inside the loop: never on a beat)
// and the river's painted reflection of it brightens and dims with the light above it (a multiply over the water's
// mirror share, aurorafx.png G; the water's own paint and ripples stay the plate's). Averaged over time the light is
// the painting's. Everything is a pure function of time with whole cycles per loop (seamless), slow and soft: no flash,
// no flicker faster than about one swell a second (viewer comfort).
//
// opts: { plate, fold (px at 4K, 16), rays (0.14), waves (0.16), breathe (0.12), surges (per hour, 18), surge (0.4),
//   reflect (1: how much the water follows), renderOrder (0.2) }
import * as THREE from 'three';
import { plateTexture, fetchJson, ADDITIVE, GLSL_COMMON } from './overlay.js';
import { hashString, mulberry32 } from '../engine/rng.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;

const vert = /* glsl */ `
uniform vec4 uBox;        // the quad: x, y (top left, px at 4K, y down), w, h
varying vec2 vPx;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = uBox.xy + vec2(q.x, 1.0 - q.y) * uBox.zw;
  gl_Position = vec4(vPx.x / ${W}.0 * 2.0 - 1.0, 1.0 - vPx.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;

// the shared motion: fold displacement and the brightness factor at a point, from this frame's phases
const MOTION = /* glsl */ `
uniform vec4 uFold;       // amplitudes (px): wave 1, wave 2, the hem's lift; 1/height of the aurora box
uniform vec4 uFoldPh;     // phases of fold waves 1, 2, 3 (rad)
uniform vec4 uWave;       // brightness: wave 1 amp, wave 2 amp, breathing (already a factor), ray amp
uniform vec4 uWavePh;     // phases of brightness waves 1, 2 (rad); the rays' drift (px); unused
uniform vec2 uRayT;       // the rays' flicker: time in noise cells, cells per loop (whole: seamless)
uniform vec4 uSurge[2];   // active surges: center x (px), half width (px), amount (0..), unused
uniform vec2 uTop;        // the aurora box's top and bottom rows (px)
float hem(float y) { return clamp((y - uTop.x) / max(uTop.y - uTop.x, 1.0), 0.0, 1.0); }
vec2 foldOffset(vec2 px) {
  float h = hem(px.y);
  float a = 0.35 + 0.65 * h;                     // the hem sways most, the top of the rays least
  float dx = a * (uFold.x * sin(px.x * 0.00698 + uFoldPh.x + 1.9 * h) + uFold.y * sin(px.x * 0.0151 - uFoldPh.y + 2.7 * h));
  float dy = uFold.z * h * h * sin(px.x * 0.0042 + uFoldPh.z);
  return vec2(dx, dy);
}
float surgeAt(float x) {
  float s = 0.0;
  for (int i = 0; i < 2; i++) {
    vec4 S = uSurge[i];
    if (S.z <= 0.0) continue;
    float d = (x - S.x) / max(S.y, 1.0);
    s += S.z * exp(-d * d);
  }
  return s;
}
float brightness(float x) {
  float w = 1.0 + uWave.x * sin(x * 0.00185 - uWavePh.x) + uWave.y * sin(x * 0.0043 + uWavePh.y);
  return w * uWave.z * (1.0 + surgeAt(x));
}
float rays(vec2 px, float surge) {
  // fine vertical striations 8 px wide, drifting along the curtain: the pattern repeats every 4096 px (512 cells) and
  // drifts two repeats a loop; it flickers through uRayT.y cells of time a loop (both whole: seamless)
  float r = pfbm(vec2((px.x + uWavePh.z) / 8.0, uRayT.x), vec2(512.0, uRayT.y));
  float slow = pnoise(vec2(px.x / 140.0, px.y / 420.0 + uRayT.x / 20.0), vec2(64.0, uRayT.y / 20.0));
  return 1.0 + uWave.w * (1.0 + 1.5 * surge) * (r - 0.5) * 2.0 * (0.55 + 0.9 * slow);
}
`;

const fragSky = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tPos;
uniform sampler2D tNeg;
uniform sampler2D tFx;
uniform vec2 uGain;       // 1/gain of the light, 1/gain of the dark paint
${MOTION}
varying vec2 vPx;
void main() {
  vec2 uv = vec2(vPx.x / ${W}.0, 1.0 - vPx.y / ${H}.0);
  float air = texture2D(tFx, uv).r;
  if (air < 0.003) discard;
  vec2 src = vPx - foldOffset(vPx);
  vec2 suv = vec2(src.x / ${W}.0, 1.0 - src.y / ${H}.0);
  vec3 pos = texture2D(tPos, suv).rgb * uGain.x;
  vec3 neg = texture2D(tNeg, suv).rgb * uGain.y;
  float s = surgeAt(vPx.x);
  float m = brightness(vPx.x) * rays(src, s);
  gl_FragColor = vec4((pos * m - neg) * air, 0.0);
}`;

// the river's painted reflection follows the light above it: a multiply of the water's color by 1 + share x (m - 1)
const fragWater = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tFx;
uniform float uReflect;
${MOTION}
varying vec2 vPx;
void main() {
  vec2 uv = vec2(vPx.x / ${W}.0, 1.0 - vPx.y / ${H}.0);
  float share = texture2D(tFx, uv).g * uReflect;
  if (share < 0.003) discard;
  float m = brightness(vPx.x);
  gl_FragColor = vec4(vec3(max(0.0, 1.0 + share * (m - 1.0))), 1.0);
}`;

const MULTIPLY = {
  transparent: true, depthTest: false, depthWrite: false, toneMapped: false, side: THREE.DoubleSide,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.DstColorFactor, blendDst: THREE.ZeroFactor,
  blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
};

const hash = (s) => hashString(s) / 4294967296;

// The surges of one loop: seeded start times spread over the loop with a minimum gap (never on a beat), each sweeping
// across the aurora's width one way or the other. Kept inside [0, L) with their whole length, so the loop's seam is
// never in one.
export function surgePlan(L, perHour, seed, x0, x1) {
  const n = Math.max(1, Math.round((perHour * L) / 3600));
  const r = mulberry32(Math.floor(seed * 1e9) ^ 0x5f3759df);
  const slot = L / n, out = [];
  for (let i = 0; i < n; i++) {
    const dur = 26 + 20 * r();
    const t0 = i * slot + 4 + (slot - dur - 8) * r();
    const dir = r() < 0.5 ? 1 : -1;
    out.push({ t0, dur, dir, amp: 0.65 + 0.35 * r(), xa: dir > 0 ? x0 - 300 : x1 + 300, xb: dir > 0 ? x1 + 300 : x0 - 300 });
  }
  return out;
}

export async function auroraLayer(ctx, opts) {
  const plate = opts.plate;
  const meta = await fetchJson(`/out/plates/${plate}/aurora.json`, { hint: 'run plate_prep with hand.json "aurora" (tools/cozy/plate/aurora.py)' });
  const [tPos, tNeg, tFx] = await Promise.all([
    plateTexture(plate, 'aurora.png', { srgb: true }), plateTexture(plate, 'aurora_neg.png', { srgb: true }), plateTexture(plate, 'aurorafx.png'),
  ]);
  const L = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const cyc = (hz) => Math.max(1, Math.round(hz * L));
  const o = { fold: 16, rays: 0.14, waves: 0.16, breathe: 0.12, surges: 18, surge: 0.4, reflect: 1, ...opts };
  const [bx0, by0, bx1, by1] = meta.box;
  const seed = hash(`aurora:${ctx.seed}`);
  const plan = surgePlan(L, o.surges, seed, bx0, bx1);
  const uniforms = {
    uFold: { value: new THREE.Vector4(o.fold, 0.55 * o.fold, 0.4 * o.fold, 0) }, uFoldPh: { value: new THREE.Vector4() },
    uWave: { value: new THREE.Vector4(o.waves, 0.55 * o.waves, 1, o.rays) }, uWavePh: { value: new THREE.Vector4() },
    uRayT: { value: new THREE.Vector2() },
    uSurge: { value: [new THREE.Vector4(), new THREE.Vector4()] }, uTop: { value: new THREE.Vector2(by0, by1) },
  };
  const margin = Math.ceil(1.6 * o.fold + 4);
  const sky = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: fragSky, ...ADDITIVE,
    uniforms: { ...uniforms, tPos: { value: tPos }, tNeg: { value: tNeg }, tFx: { value: tFx }, uGain: { value: new THREE.Vector2(1 / meta.gain, 1 / (meta.dark_gain ?? meta.gain)) },
      uBox: { value: new THREE.Vector4(bx0 - margin, by0 - margin, bx1 - bx0 + 2 * margin, by1 - by0 + 2 * margin) } },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), sky);
  mesh.frustumCulled = false;
  mesh.renderOrder = o.renderOrder ?? 0.2;     // on the plate's sky, behind everything else
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const mats = [sky];
  if (meta.reflect && o.reflect > 0) {
    const [rx0, ry0, rx1, ry1] = meta.reflect;
    const water = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: fragWater, ...MULTIPLY,
      uniforms: { ...uniforms, tFx: { value: tFx }, uReflect: { value: o.reflect }, uBox: { value: new THREE.Vector4(rx0, ry0, rx1 - rx0, ry1 - ry0) } },
    });
    const wm = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), water);
    wm.frustumCulled = false;
    wm.renderOrder = (o.renderOrder ?? 0.2) + 0.05;
    wm.userData.noAO = true;
    ctx.add(wm);
    mats.push(water);
  }
  // whole cycles per loop: the folds travel along the arc in about 40 s and 23 s, the hem lifts over 61 s, brightness
  // waves cross in 47 s and 29 s, the display breathes over about 5 minutes, the rays drift two pattern widths a loop
  // and flicker about once in 3 s
  const nF1 = cyc(1 / 40), nF2 = cyc(1 / 23), nF3 = cyc(1 / 61), nW1 = cyc(1 / 47), nW2 = cyc(1 / 29), nB = cyc(1 / 290), nB2 = cyc(1 / 131);
  const ph = [0, 1, 2, 3, 4, 5, 6].map((k) => TAU * hash(`aurora:${k}:${ctx.seed}`));
  // the rays flicker through one noise cell in about 3 s; 20 divides the cell count, for the slow variation's period
  const flick = Math.max(20, 20 * Math.round(L / 3 / 20));
  ctx.animate((t) => {
    const tt = ((t % L) + L) % L;
    const u = uniforms;
    u.uFoldPh.value.set(TAU * nF1 * tt / L + ph[0], TAU * nF2 * tt / L + ph[1], TAU * nF3 * tt / L + ph[2], 0);
    const breathe = 1 + o.breathe * (0.7 * Math.sin(TAU * nB * tt / L + ph[3]) + 0.3 * Math.sin(TAU * nB2 * tt / L + ph[4]));
    u.uWave.value.z = breathe;
    u.uWavePh.value.set(TAU * nW1 * tt / L + ph[5], TAU * nW2 * tt / L + ph[6], 2 * 4096 * tt / L, 0);
    u.uRayT.value.set((tt / L) * flick, flick);
    let k = 0;
    for (const s of plan) {
      if (k >= 2) break;
      const f = (tt - s.t0) / s.dur;
      if (f <= 0 || f >= 1) continue;
      const env = Math.sin(Math.PI * f) ** 2;        // swells in and out, no edges
      u.uSurge.value[k].set(s.xa + (s.xb - s.xa) * f, 700, o.surge * s.amp * env, 0);
      k++;
    }
    for (; k < 2; k++) u.uSurge.value[k].set(0, 1, 0, 0);
  });
  return mats[0];
}
