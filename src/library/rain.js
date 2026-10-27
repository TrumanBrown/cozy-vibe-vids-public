// Physically based rain for plate scenes (decision record: docs/DECISIONS.md, 2026-10-15 "Rain v3").
//
// Falling rain (instanced streaks). Each drop has a depth z (m) and a diameter D (mm, truncated
// exponential, Marshall-Palmer shape). It falls at terminal velocity V(D) (Atlas et al. 1973), so on
// screen it moves V*F/z px/s; its streak is the distance moved while the shutter is open (motion blur);
// its width is D*F/z (with a lens-blur floor and defocus for near drops); its per-pixel opacity is the
// fraction of the exposure the drop covers a pixel (Garg & Nayar 2007), times an artistic gain. Streaks
// are composited "over" toward the drop's own radiance (sky light, plus warm lantern light for near
// drops) instead of additive white, so they read correctly on dark trees and bright sky. Wind = mean +
// gust fronts sweeping across the frame + per-drop turbulence; slant follows from the velocity ratio,
// so small, slow drops lean more. Density comes in clumps that are fixed to the drops (they fall with
// the rain) and drift with the wind.
//
// Runoff (instanced beads). Water pouring off roof edges and dripping from vine tips: beads released at
// a flow-modulated rate fall from rest under gravity with drag (h = Vt^2/g ln cosh(g t/Vt)). The same
// motion-blur rule makes a stream look continuous near the lip and break into accelerating, stretching
// beads lower down, as real runoff does.
//
// Everything is masked by the plate's outdoor mask (lights.png G, built from depth by plate_prep.py):
// rain only exists behind the opening, never on the roof, pets, railing or interior. All motion is
// periodic in the scene loop (integer cycles per loop), so loops are seamless and frames deterministic.
import * as THREE from 'three';
import { mulberry32 } from '../engine/rng.js';
import { flashAt, trackAt, flurryUniform } from './timeline.js';
import { hangingFrom, instancedQuad, loadTex } from './overlay.js';

const G = 9.81;
export const vTerm = (D) => Math.max(0.6, 9.65 - 10.3 * Math.exp(-0.6 * D)); // D in mm -> m/s

const shared = /* glsl */ `
const float TAU = 6.28318530718;
const float G = 9.81;
uint pcg(uint v) { uint s = v * 747796405u + 2891336453u; uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u; return (w >> 22u) ^ w; }
float rnd(uint a, uint b) { return float(pcg(a ^ pcg(b + 0x9e3779b9u))) * (1.0 / 4294967296.0); }
varying vec4 vDim;   // half motion length, disc radius (px)
varying vec2 vLoc;   // streak-local px: x across, y along
varying float vA;
varying vec3 vE;
varying vec2 vUv;
`;

const vertCommon = /* glsl */ `
${shared}
uniform float uPhase, uLoop, uF, uShutter, uMinW;
uniform vec2 uRes;
uniform vec4 uWind;   // mean (m/s), gust (m/s), gust cycles per loop (integer >= 1), gust fronts across the frame
uniform sampler2D tLights, tEnv, tWeather;
uniform vec3 uSky, uWarm;
uniform float uEnvGain, uEnvMix, uFlash, uMinContrast;
uniform float uTime, uWeatherN, uWeatherDt;   // absolute time (s); weather track (timeline.js) samples / spacing
// Slow weather at absolute time t: r = rain intensity, g = stream flow, b = wind gustiness (1 = nominal).
vec4 weather(float t) {
  if (uWeatherN < 2.0) return vec4(1.0);
  return texture2D(tWeather, vec2((clamp(t / uWeatherDt, 0.0, uWeatherN - 1.0) + 0.5) / uWeatherN, 0.5));
}
float vTerm(float D) { return max(0.6, 9.65 - 10.3 * exp(-0.6 * D)); }
float windAt(float t, float xpx) {
  float th = TAU * (uWind.z * t / uLoop - uWind.w * xpx / uRes.x);
  return uWind.x + uWind.y * (0.75 * sin(th) + 0.25 * sin(2.0 * th + 1.3));
}
// Gust flurry (timeline.js flurryUniform): x = seconds since it started, y = duration, z = amplitude (m/s).
// Raised-cosine gust and its exact integral (same formulas as flurryWind/flurryInt); zero when no flurry.
uniform vec3 uFlurry;
float flurryW(float s) { return (s > 0.0 && s < uFlurry.y) ? uFlurry.z * 0.5 * (1.0 - cos(TAU * s / uFlurry.y)) : 0.0; }
float flurryInt(float s) { float u = clamp(s, 0.0, uFlurry.y); return uFlurry.z * (0.5 * u - uFlurry.y / (2.0 * TAU) * sin(TAU * u / uFlurry.y)); }
// Motion-blurred streak quad. ctr: streak center (px, y down); vel: px/s; wR: rendered width (px).
void emit(vec2 ctr, vec2 vel, float wR, float a, vec3 E) {
  float spd = max(length(vel), 1e-3);
  vec2 dir = vel / spd, nrm = vec2(-dir.y, dir.x);
  float L = spd * uShutter;
  float rr = 0.5 * wR + 0.5;                 // disc radius incl. half a pixel of AA
  float hl = 0.5 * L + rr + 1.0, hw = rr + 1.0;
  vec2 q = position.xy;
  vec2 p = ctr + nrm * (q.x * hw) + dir * (q.y * hl);
  vLoc = vec2(q.x * hw, q.y * hl);
  vDim = vec4(0.5 * L, rr, 0.0, 0.0);
  vA = a;
  vE = E;
  vUv = vec2(p.x / uRes.x, 1.0 - p.y / uRes.y);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}
void hide() { vA = 0.0; vDim = vec4(0.0); vLoc = vec2(0.0); vE = vec3(0.0); vUv = vec2(0.0); gl_Position = vec4(2.0, 2.0, 2.0, 1.0); }
// Drop radiance: a drop refracts a wide view of its surroundings (Garg & Nayar), so it takes the
// sky's light mixed with the local outdoor environment (env.png: dim and warm in front of the
// forest, bright and cool against the misty sky), plus specular glints of nearby lanterns.
// uMinContrast: the least a drop stands above the environment behind it (linear). Physically a drop in front of a
// dark forest at night is almost as dark as the forest; the Burdock Shelter's rain vanished there (2026-10-25, L152).
vec3 radiance(vec2 px, float warmK) {
  vec2 uv = clamp(vec2(px.x / uRes.x, 1.0 - px.y / uRes.y), 0.0, 1.0);
  float glow = texture2D(tLights, uv).b;
  vec3 envL = texture2D(tEnv, uv).rgb;
  vec3 env = mix(uSky, envL * uEnvGain, uEnvMix);
  vec3 E = env + uWarm * glow * warmK;
  if (uMinContrast > 0.0) E = max(E, envL + uMinContrast);
  return E * (1.0 + uFlash);   // lightning lights every drop
}
`;

const rainVert = /* glsl */ `
${vertCommon}
attribute vec4 aDrop;   // z (m), D (mm), cycles per loop (integer), phase offset
uniform float uMarginX, uMarginY, uGain, uMaxA, uFocusZ, uCoc, uTurb, uWarmNear, uGlint, uFarBoost;
uniform vec4 uDens;     // keep fraction, clump strength, clump cycles per loop (integer), clumps across (integer)
uniform float uDrift;   // clump drift per loop in cells (a multiple of the clumps across: seamless)
float vnoise(vec2 p, vec2 per) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  vec2 i0 = mod(i, per), i1 = mod(i + 1.0, per);
  float a = rnd(uint(i0.x) + 7919u * uint(i0.y), 11u), b = rnd(uint(i1.x) + 7919u * uint(i0.y), 11u);
  float c = rnd(uint(i0.x) + 7919u * uint(i1.y), 11u), d = rnd(uint(i1.x) + 7919u * uint(i1.y), 11u);
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
void main() {
  float z = aDrop.x, D = aDrop.y, n = aDrop.z;
  float ppm = uF / z;
  float vy = vTerm(D) * ppm;
  float c = uPhase * n + aDrop.w;
  float k = mod(floor(c), n);
  float tau = fract(c) * uLoop / n;          // seconds since this drop entered above the frame
  float tNow = uPhase * uLoop, tEnt = tNow - tau;
  uint id = uint(gl_InstanceID) * 4u, kk = uint(k);
  float rx = rnd(id, kk), rt = rnd(id + 1u, kk), rk = rnd(id + 2u, kk), rg = rnd(id + 3u, kk);
  float x0 = mix(-uMarginX, uRes.x + uMarginX, rx);
  // Clumps: a density pattern evaluated where/when the drop entered, so it falls with the rain.
  vec2 np = vec2(rx * uDens.w + uDrift * tEnt / uLoop, uDens.z * tEnt / uLoop);
  float cl = 0.65 * vnoise(np, vec2(uDens.w, uDens.z)) + 0.35 * vnoise(np * 2.0 + 17.0, vec2(uDens.w, uDens.z) * 2.0);
  float dens = uDens.x * weather(uTime - tau).r * (1.0 - uDens.y * (1.0 - smoothstep(0.32, 0.68, cl)));
  if (rk >= dens) { hide(); return; }
  // Horizontal drift: exact integral of the wind since entry (periodic), plus turbulence.
  float m = uWind.z, xs = uWind.w * x0 / uRes.x;
  float th0 = TAU * (m * tEnt / uLoop - xs), th1 = TAU * (m * tNow / uLoop - xs);
  float K = uWind.y * uLoop / (TAU * m);
  float turb = (rt - 0.5) * 2.0 * uTurb;
  float drift = (uWind.x + turb) * tau - K * (0.75 * (cos(th1) - cos(th0)) + 0.125 * (cos(2.0 * th1 + 1.3) - cos(2.0 * th0 + 1.3)));
  drift += flurryInt(uFlurry.x) - flurryInt(uFlurry.x - tau);
  vec2 pos = vec2(x0 + drift * ppm, -uMarginY + vy * tau);
  vec2 vel = vec2((windAt(tNow, x0) + flurryW(uFlurry.x) + turb) * ppm, vy);
  float wP = D * 0.001 * ppm;
  float wR = max(wP, uMinW) + uCoc * abs(1.0 / z - 1.0 / uFocusZ);
  float L = length(vel) * uShutter;
  // farBoost > 0 lifts distant drops above their physical per-drop opacity (artistic: keeps a visible
  // slow far layer, like camera rain against a dark valley); 7 m is the reference depth.
  float a = min(uGain * wP * wP / ((L + wP) * wR) * pow(z / 7.0, uFarBoost) * mix(1.0 - uGlint, 1.0 + uGlint, rg), uMaxA);
  vec2 ctr = pos - vel * (0.5 * uShutter);
  emit(ctr, vel, wR, a, radiance(ctr, exp(-max(z - 3.0, 0.0) / uWarmNear)));
}`;

// Runoff flow (0.04..1) of a stream at loop time t: slow swells (the stream's cyc per loop), ~3 s surges and irregular
// 2-3 Hz packets, with phases from the stream's seed. One set of constants for the shader's flowAt (FLOW_GLSL, built
// from them) and flowAt in JS below, which tools/audio.py's flow() follows (tests/test_parity.py holds them together).
const FLOW = {
  swell: { w: 0.5, w2: 0.3, ph2: 2.1 },   // sin(th) and its second harmonic, th = TAU * cyc * t / L + seed phase
  surge: { w: 0.35, cyc: 37, k: 3 },      // weight, cycles per loop, seed phase multiplier
  packets: [{ w: 0.5, cyc: 263, k: 5 }, { w: 0.5, cyc: 389, k: 7 }],
  pk: 0.22, min: 0.04, max: 1,
};
const glf = (v) => (Number.isInteger(v) ? v.toFixed(1) : String(v));   // a GLSL float literal
const { swell: SW, surge: SU, packets: [P1, P2] } = FLOW;
const FLOW_GLSL = /* glsl */ `float flowAt(float t, float base, float amp, float cyc, float sd) {
  // Slow swells (cyc per loop), ~3 s surges (${SU.cyc} per loop) and irregular 2-3 Hz packets (${P1.cyc} + ${P2.cyc} per
  // loop): runoff pulses as water collects on the roof and lets go.
  float th = TAU * cyc * t / uLoop + sd;
  float s = ${glf(SW.w)} * sin(th) + ${glf(SW.w2)} * sin(2.0 * th + ${glf(SW.ph2)} + sd) + ${glf(SU.w)} * sin(TAU * ${glf(SU.cyc)} * t / uLoop + ${glf(SU.k)} * sd);
  float pk = ${glf(P1.w)} * sin(TAU * ${glf(P1.cyc)} * t / uLoop + ${glf(P1.k)} * sd) + ${glf(P2.w)} * sin(TAU * ${glf(P2.cyc)} * t / uLoop + ${glf(P2.k)} * sd);
  return clamp(base + amp * s + ${glf(FLOW.pk)} * pk, ${glf(FLOW.min)}, ${glf(FLOW.max)});
}`;
const TAU = 2 * Math.PI;

// The shader's flowAt in JS: t in s within the loop (L), base flow, burst amplitude, burst cycles per loop and the seed
// phase of a stream (runoffParams: flow, burst, burstCycles, seedf), before the weather track's stream strength.
export function flowAt(t, base, amp, cyc, sd, L) {
  const th = TAU * cyc * t / L + sd;
  const s = SW.w * Math.sin(th) + SW.w2 * Math.sin(2 * th + SW.ph2 + sd) + SU.w * Math.sin(TAU * SU.cyc * t / L + SU.k * sd);
  const pk = P1.w * Math.sin(TAU * P1.cyc * t / L + P1.k * sd) + P2.w * Math.sin(TAU * P2.cyc * t / L + P2.k * sd);
  return Math.min(Math.max(base + amp * s + FLOW.pk * pk, FLOW.min), FLOW.max);
}

const runoffVert = /* glsl */ `
${vertCommon}
attribute vec4 aS0;   // lip x (px), lip y (px), depth z (m), bead diameter D (mm)
attribute vec4 aS1;   // release rate (Hz, integer per loop), base flow (0..1), flow burst amplitude, burst cycles per loop
attribute vec4 aS2;   // slot (-1 = neck), neck length (m), lateral spread (m per m fallen), seed
attribute vec4 aS3;   // opacity gain, warm-light gain, sway (m), brightness
attribute vec2 aMove; // where the lip is carried this frame by a moving region it pours off (a swaying cloth), px
uniform float uGainR, uMaxAR;
${FLOW_GLSL}
float logcosh(float x) { return x + log(1.0 + exp(-2.0 * x)) - 0.69314718; }
// Sinuous sway of the release point (2.3 + 3.7 Hz, integer cycles per loop); it travels down the stream.
float swayAt(float t, float amp, float sd) {
  return amp * (0.6 * sin(TAU * 277.0 * t / uLoop + sd) + 0.4 * sin(TAU * 443.0 * t / uLoop + 1.0 + sd));
}
void main() {
  vec2 lip = aS0.xy + aMove;
  float z = aS0.z, D0 = aS0.w, f0 = aS1.x;
  float ppm = uF / z;
  float tNow = uPhase * uLoop;
  float slot = aS2.x;
  uint sd = uint(aS2.w);
  float seedf = aS2.w * 0.618;
  float gainS = uGainR * aS3.x, warmS = aS3.y;
  if (slot < 0.0) {
    // Neck: the unbroken column just below a visible lip (Plateau-Rayleigh breakup length ~ flow).
    float fl = clamp(flowAt(tNow, aS1.y, aS1.z, aS1.w, seedf) * weather(uTime).g, 0.04, 1.0);
    float len = aS2.y * fl;
    float wob = swayAt(tNow, aS3.z, seedf) * ppm;
    float wR = max(D0 * 0.001 * ppm * mix(0.55, 0.9, fl), uMinW);
    vec2 ctr = vec2(lip.x + wob, lip.y + 0.5 * len * ppm);
    emit(ctr, vec2(0.0, len * ppm / uShutter), wR, min(gainS * 0.09 * fl, uMaxAR), radiance(ctr, warmS) * aS3.w);
    return;
  }
  float N = f0 * uLoop;                      // beads per loop (integer)
  float kc = floor(f0 * tNow) - slot;        // bead index; negative = released in the previous loop
  float k = mod(kc, N);
  uint kk = uint(k) * 5u;
  float tRel = (kc + 0.85 * rnd(sd, kk)) / f0;
  float age = tNow - tRel;
  if (age < 0.0) { hide(); return; }
  float fl = clamp(flowAt(tRel, aS1.y, aS1.z, aS1.w, seedf) * weather(uTime - age).g, 0.04, 1.0);
  if (rnd(sd, kk + 1u) > fl) { hide(); return; }
  float D = D0 * mix(0.45, 1.35, rnd(sd, kk + 2u)) * mix(0.7, 1.15, fl);
  float Vt = vTerm(D), tr = Vt / G;
  float h = Vt * tr * logcosh(age / tr);     // fall distance (m), drag-limited
  float v = Vt * tanh(age / tr);
  float uw = windAt(tRel, lip.x) + flurryW(uFlurry.x - age);   // wind at release pushes the bead sideways (relaxes with tr)
  float ex = exp(-age / tr);
  // Sinuous sway of the release point travels down the stream.
  float sway = swayAt(tRel, aS3.z, seedf);
  float dx = uw * (age - tr * (1.0 - ex)) + sway + (rnd(sd, kk + 3u) - 0.5) * aS2.z * h;
  vec2 pos = vec2(lip.x + dx * ppm, lip.y + h * ppm);
  vec2 vel = vec2(uw * (1.0 - ex) * ppm, v * ppm);
  float wP = D * 0.001 * ppm;
  float wR = max(wP, uMinW);
  float L = length(vel) * uShutter;
  float a = min(gainS * wP / (L + wP) * (wP / wR) * mix(0.75, 1.25, rnd(sd, kk + 4u)), uMaxAR);
  vec2 ctr = pos - vel * (0.5 * uShutter);
  if (ctr.y - 0.5 * L > uRes.y + 4.0) { hide(); return; }
  float glint = 1.0 + 1.2 * pow(rnd(sd, kk + 6u), 6.0);   // occasional bead catching a highlight
  emit(ctr, vel, wR, a, radiance(ctr, warmS) * glint * aS3.w);
}`;

const frag = /* glsl */ `
${shared}
uniform sampler2D tLights;
uniform float uDebug;
void main() {
  // Exposure coverage of a disc (radius rr) swept along the streak: elliptical cross-section, ends that
  // taper over one drop diameter (normalized so a long streak's center is 1).
  float hL = vDim.x, rr = vDim.y;
  float c = sqrt(max(rr * rr - vLoc.x * vLoc.x, 0.0));
  float ov = clamp(min(vLoc.y + c, hL) - max(vLoc.y - c, -hL), 0.0, 2.0 * c);
  float a = vA * ov / max(min(2.0 * rr, 2.0 * hL), 1e-3);
  a *= texture2D(tLights, vUv).g;
  if (a < 0.0015) discard;
  gl_FragColor = uDebug > 0.5 ? vec4(a, a, a, 1.0) : vec4(vE * a, a);
}`;

const lin = (c) => new THREE.Color(c); // THREE.Color from hex is linear-sRGB in r152+ color management

// opts: see scenes/treetop-plate/scene.js for a commented example. Sizes are in 3840x2160 plate px.
export async function rainLayer(ctx, opts) {
  const dir = `/out/plates/${opts.plate}`;
  const [tLights, tEnv, meta] = await Promise.all([loadTex(`${dir}/lights.png`), loadTex(`${dir}/env.png`, { srgb: true }), fetch(`${dir}/plate.json`).then((r) => r.json())]);
  const W = 3840, H = 2160, Lp = ctx.loopSeconds;
  const F = opts.focalPx ?? 2700, shutter = opts.shutter ?? 1 / 60;
  const env = meta.env_linear?.sky ?? [0.08, 0.1, 0.2];
  const sky = new THREE.Vector3(...env).multiplyScalar(opts.skyGain ?? 2.0);
  const warm = lin(opts.warm ?? '#ffb26a');
  const wind = opts.wind ?? {};
  const uWind = new THREE.Vector4(wind.mean ?? 0.3, wind.gust ?? 0.8, Math.max(1, Math.round(wind.gustCycles ?? 5)), wind.fronts ?? 0.6);
  const gust0 = uWind.y;
  // Slow weather track (timeline.js weatherTrack) as a 1D texture: R rain, G streams, B wind.
  const track = ctx.timeline?.track;
  let tWeather = null, nW = 0;
  if (track?.rain?.length) {
    nW = track.rain.length;
    const d = new Uint16Array(nW * 4);
    for (let i = 0; i < nW; i++) {
      d[i * 4] = THREE.DataUtils.toHalfFloat(track.rain[i]);
      d[i * 4 + 1] = THREE.DataUtils.toHalfFloat(track.streams[i]);
      d[i * 4 + 2] = THREE.DataUtils.toHalfFloat(track.wind[i]);
      d[i * 4 + 3] = THREE.DataUtils.toHalfFloat(1);
    }
    tWeather = new THREE.DataTexture(d, nW, 1, THREE.RGBAFormat, THREE.HalfFloatType);
    tWeather.minFilter = tWeather.magFilter = THREE.LinearFilter;
    tWeather.wrapS = tWeather.wrapT = THREE.ClampToEdgeWrapping;
    tWeather.needsUpdate = true;
  }
  const common = {
    uPhase: { value: 0 }, uLoop: { value: Lp }, uF: { value: F }, uShutter: { value: shutter }, uMinW: { value: opts.minWidth ?? 1.6 },
    uRes: { value: new THREE.Vector2(W, H) }, uWind: { value: uWind }, tLights: { value: tLights }, tEnv: { value: tEnv },
    uSky: { value: sky }, uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b).multiplyScalar(opts.warmGain ?? 1.0) },
    uEnvGain: { value: opts.skyGain ?? 2.0 }, uEnvMix: { value: opts.envMix ?? 0 }, uMinContrast: { value: opts.minContrast ?? 0 },
    uFlash: { value: 0 },
    uTime: { value: 0 }, tWeather: { value: tWeather }, uWeatherN: { value: nW }, uWeatherDt: { value: track?.dt ?? 5 },
    uFlurry: { value: new THREE.Vector3(0, 1, 0) },
    uDebug: { value: opts.debug ? 1 : 0 },
  };
  const blend = {
    transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
  };
  if (opts.debug) Object.assign(blend, { blendDst: THREE.OneFactor, blendDstAlpha: THREE.OneFactor });
  const meshes = [];
  const r = mulberry32((ctx.seed ?? 1) * 7919 + 17);

  // Falling rain. `count` drops are visible at nominal intensity; the pool has headroom for heavier
  // spells of the weather track (keep fraction = count/pool * intensity, decided per drop at entry).
  const N0 = opts.count ?? 30000;
  const head = tWeather ? Math.max(1, ...track.rain) : 1;
  const N = Math.ceil(N0 * head);
  const [zN, zF] = opts.depth ?? [3, 30];
  const kz = opts.depthPower ?? 1;  // depth pdf ~ z^-k: 1 = log-uniform, >1 = more near drops
  const sampleZ = (u) => (Math.abs(kz - 1) < 1e-6 ? zN * Math.pow(zF / zN, u)
    : Math.pow(Math.pow(zN, 1 - kz) + u * (Math.pow(zF, 1 - kz) - Math.pow(zN, 1 - kz)), 1 / (1 - kz)));
  const [dMin, dMax] = opts.dropRange ?? [0.5, 4.5];
  const lam = opts.dropLambda ?? 2.0;
  const mX = opts.marginX ?? 700, mY = opts.marginY ?? 240;
  const aDrop = new Float32Array(N * 4);
  for (let i = 0; i < N; i++) {
    const z = sampleZ(r());
    const D = dMin - Math.log(1 - r() * (1 - Math.exp(-lam * (dMax - dMin)))) / lam;
    const vy = vTerm(D) * (F / z);
    const n = Math.max(1, Math.floor((Lp * vy) / (H + 2 * mY)));
    aDrop.set([z, D, n, r()], i * 4);
  }
  // Opacity gain: `alphaRef` is the opacity of a 2 mm drop at 7 m; others scale physically from it.
  const focus = opts.focus ?? 12, coc = opts.coc ?? 8, minW = opts.minWidth ?? 1.6;
  const physRef = (() => {
    const z = 7, D = 2, ppm = F / z, wP = D * 1e-3 * ppm, wR = Math.max(wP, minW) + coc * Math.abs(1 / z - 1 / focus);
    return (wP * wP) / ((vTerm(D) * ppm * shutter + wP) * wR);
  })();
  const dens = opts.clumps ?? {};
  const across = Math.max(1, Math.round(dens.across ?? 3));
  const rg = instancedQuad(N);
  rg.setAttribute('aDrop', new THREE.InstancedBufferAttribute(aDrop, 4));
  const rainMat = new THREE.ShaderMaterial({
    vertexShader: rainVert, fragmentShader: frag, ...blend,
    uniforms: {
      ...common,
      uMarginX: { value: mX }, uMarginY: { value: mY }, uGain: { value: (opts.alphaRef ?? 0.2) / physRef }, uMaxA: { value: opts.maxAlpha ?? 0.6 },
      uFocusZ: { value: focus }, uCoc: { value: coc }, uTurb: { value: wind.turb ?? 0.35 }, uWarmNear: { value: opts.warmNear ?? 5 },
      uGlint: { value: opts.glint ?? 0.35 }, uFarBoost: { value: opts.farBoost ?? 0 },
      uDens: { value: new THREE.Vector4((dens.amount ?? 1) * N0 / N, dens.strength ?? 0.5, Math.max(1, Math.round(dens.cycles ?? 11)), across) },
      uDrift: { value: Math.round(dens.drift ?? 1) * across },  // drift: whole frame-widths per loop
    },
  });
  const rain = new THREE.Mesh(rg, rainMat);
  meshes.push(rain);

  // Runoff: roof streams and vine drips.
  const src = runoffParams(opts.runoff ?? [], Lp);
  let hang = [], aMove = null;
  const rowsOf = [];
  if (src.length) {
    const rows = [];
    src.forEach((s, si) => {
      const ppm = F / s.z;
      const y0 = s.y * H, hMax = (H + 300 - y0) / ppm;
      const Vt = vTerm(s.d * 0.4), tr = Vt / G;
      const ageMax = tr * Math.acosh(Math.exp(hMax / (Vt * tr)));
      const J = Math.ceil(ageMax * s.f0) + 2;
      const base = [s.x * W, y0, s.z, s.d, s.f0, s.flow, s.burst, s.burstCycles];
      const look = [s.gain, s.warm, s.wobble, s.bright];
      rowsOf[si] = [];
      if (s.neck > 0 && y0 > 0) { rowsOf[si].push(rows.length); rows.push([...base, -1, s.neck, s.spread, s.seed, ...look]); }
      for (let j = 0; j < J; j++) { rowsOf[si].push(rows.length); rows.push([...base, j, s.neck, s.spread, s.seed, ...look]); }
    });
    const M = rows.length;
    const g = instancedQuad(M);
    for (let a = 0; a < 4; a++) {
      const arr = new Float32Array(M * 4);
      rows.forEach((row, i) => arr.set(row.slice(a * 4, a * 4 + 4), i * 4));
      g.setAttribute(`aS${a}`, new THREE.InstancedBufferAttribute(arr, 4));
    }
    // A stream pouring off a swaying cloth moves with its hem (the stream's beads ride along; the hem moves a
    // few px over the second they take to fall).
    hang = await hangingFrom(ctx, opts.plate, src.map((s) => [s.x * W, s.y * H]));
    aMove = new THREE.InstancedBufferAttribute(new Float32Array(M * 2), 2);
    aMove.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('aMove', aMove);
    // Runoff has its own look (falling-rain tuning must not change the streams): width floor,
    // lantern-glint gain and environment mix default to the falling rain's but can be pinned.
    const rl = opts.runoffLook ?? {};
    const mat = new THREE.ShaderMaterial({
      vertexShader: runoffVert, fragmentShader: frag, ...blend,
      uniforms: {
        ...common, uGainR: { value: opts.runoffGain ?? 6 }, uMaxAR: { value: opts.runoffMaxAlpha ?? 0.85 },
        uMinW: { value: rl.minWidth ?? opts.minWidth ?? 1.6 },
        uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b).multiplyScalar(rl.warmGain ?? opts.warmGain ?? 1.0) },
        uEnvMix: { value: rl.envMix ?? opts.envMix ?? 0 },
      },
    });
    meshes.push(new THREE.Mesh(g, mat));
  }

  meshes.forEach((m, i) => {
    m.frustumCulled = false;
    m.renderOrder = 10 + i;
    m.userData.noAO = true;
    ctx.add(m);
  });
  ctx.animate((t) => {
    const ph = (t % Lp) / Lp;
    for (const m of meshes) m.material.uniforms.uPhase.value = ph;
    common.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash * (opts.flashGain ?? 2.5);
    common.uTime.value = t;
    uWind.y = gust0 * trackAt(track, 'wind', t);
    common.uFlurry.value.set(...flurryUniform(ctx.timeline, t));
    if (hang.length) {
      for (const h of hang) {
        const [dx, dy] = ctx.regionMotion.offsetPx(h.id, h.x, h.y, h.ax, h.w);
        for (const r of rowsOf[h.i]) aMove.array.set([dx, dy], 2 * r);
      }
      aMove.needsUpdate = true;
    }
  });
  return meshes;
}

// Normalized runoff source parameters: the one definition used by the shader (above) and by the audio
// (tools/audio.py reads them from the timeline JSON), so streams sound like they look.
// flow(t) = clamp(flow + burst*s(t) + 0.22*pk(t), 0.04, 1) with phases from `seedf` (flowAt, in JS above and in GLSL).
export function runoffParams(runoff, loopSeconds) {
  return runoff.map((s, si) => {
    const seed = 101 + si * 977;
    return {
      x: s.x, y: s.y, z: s.z ?? 3.2, d: s.d ?? 4, rate: s.rate ?? 20,
      f0: Math.max(1, Math.round((s.rate ?? 20) * loopSeconds)) / loopSeconds,
      flow: s.flow ?? 0.8, burst: s.burst ?? 0.2, burstCycles: Math.max(1, Math.round(s.burstCycles ?? 3)),
      neck: s.neck ?? 0, spread: s.spread ?? 0.02, seed, seedf: seed * 0.618,
      gain: s.gain ?? 1, warm: s.warm ?? 1.5, wobble: s.wobble ?? ((s.rate ?? 20) >= 10 ? 0.006 : 0.0), bright: s.bright ?? 1,
    };
  });
}
