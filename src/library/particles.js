// Particle layers for plate scenes, all pure functions of time (integer cycles per loop where they loop):
//   snow       falling flakes at depth (perspective size and speed), fluttering, carried by the wind and gust
//              flurries (same wind model as rain.js), lit by the sky and nearby warm light, outdoors only
//   dust       motes drifting slowly in a lit region, glinting as they turn
//   fireflies  slow wandering glows that blink on and off, in a region (gardens, fields at dusk)
//   embers     sparks rising from a fire region, cooling from orange to dark red; bursts at 'ember' events
//   stars      shooting stars at 'star' timeline events (a short soft streak across the sky)
//
// opts common: { plate, mode, regions (for dust/fireflies/embers: names or 'kind:<k>'), count, debug }
import * as THREE from 'three';
import { mulberry32 } from '../engine/rng.js';
import { flashAt, trackAt, flurryUniform } from './timeline.js';
import { plateTexture, plateRegions, pickRegions, instancedQuad, PREMUL, ADDITIVE, GLSL_COMMON } from './overlay.js';

const ADD = ADDITIVE;

// ------------------------------------------------------------------ snow
const snowVert = /* glsl */ `
${GLSL_COMMON}
attribute vec4 aF;        // z (m), diameter (mm), cycles per loop (integer), phase
attribute vec4 aG;        // flutter amplitude (m), flutter cycles per loop (integer), fall speed (m/s), spin
uniform float uPhase, uLoop, uF, uTime, uDensity, uMinW, uCoc, uFocus;
uniform vec4 uWind;       // mean, gust, gust cycles per loop, fronts
uniform vec3 uFlurry;
uniform sampler2D tLights, tEnv;
uniform vec3 uSky, uWarm;
uniform float uFlash;
varying vec2 vQ;
varying float vA;
varying vec3 vE;
varying vec2 vUv;
float windAt(float t, float xpx) {
  float th = TAU * (uWind.z * t / uLoop - uWind.w * xpx / 3840.0);
  return uWind.x + uWind.y * (0.75 * sin(th) + 0.25 * sin(2.0 * th + 1.3));
}
float flurryInt(float s) { float u = clamp(s, 0.0, uFlurry.y); return uFlurry.z * (0.5 * u - uFlurry.y / (2.0 * TAU) * sin(TAU * u / uFlurry.y)); }
void main() {
  float z = aF.x, D = aF.y, n = aF.z;
  float ppm = uF / z;
  float c = uPhase * n + aF.w;
  float k = mod(floor(c), n);
  float tau = fract(c) * uLoop / n;            // s since this flake entered above the frame
  float tNow = uPhase * uLoop, tEnt = tNow - tau;
  uint id = uint(gl_InstanceID);
  float rx = hash1(id * 7u + uint(k) * 131u), rk = hash1(id * 7u + uint(k) * 131u + 3u);
  if (rk > uDensity) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vA = 0.0; return; }
  float x0 = mix(-500.0, 4340.0, rx);
  // Drift: mean wind + gust fronts (exact integral) + flurries, then a flutter (integer cycles per loop).
  float m = uWind.z, xs = uWind.w * x0 / 3840.0;
  float th0 = TAU * (m * tEnt / uLoop - xs), th1 = TAU * (m * tNow / uLoop - xs);
  float K = uWind.y * uLoop / (TAU * m);
  float drift = uWind.x * tau - K * (0.75 * (cos(th1) - cos(th0)) + 0.125 * (cos(2.0 * th1 + 1.3) - cos(2.0 * th0 + 1.3)));
  drift += (flurryInt(uFlurry.x) - flurryInt(uFlurry.x - tau)) * 0.8;
  float fl = aG.x * sin(TAU * aG.y * tNow / uLoop + aF.w * 40.0);
  float fy = 0.35 * aG.x * sin(TAU * (2.0 * aG.y + 1.0) * tNow / uLoop + aF.w * 17.0);
  vec2 pos = vec2(x0 + (drift + fl) * ppm, -150.0 + (aG.z * tau + fy) * ppm);
  float wP = D * 0.001 * ppm;
  float wR = max(wP, uMinW) + uCoc * abs(1.0 / z - 1.0 / uFocus);
  // Out-of-focus near flakes spread into soft, faint discs (coverage ~ (sharp / blurred size)^2); each flake
  // catches the light a little differently.
  float a = min(clamp(wP * wP / (wR * wR), 0.0, 1.0), 0.55) * mix(0.5, 1.0, hash1(id * 13u + uint(k) * 7u + 5u));
  vec2 q = position.xy;
  vQ = q;
  vA = a;
  vec2 uvc = clamp(vec2(pos.x / 3840.0, 1.0 - pos.y / 2160.0), 0.0, 1.0);
  float glow = texture2D(tLights, uvc).b;
  vec3 env = texture2D(tEnv, uvc).rgb;
  vE = (uSky + env * 1.4 + uWarm * glow * exp(-max(z - 2.5, 0.0) / 4.0)) * (1.0 + 1.5 * uFlash);
  vec2 p = pos + q * (0.5 * wR + 1.0);
  vUv = vec2(p.x / 3840.0, 1.0 - p.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const snowFrag = /* glsl */ `
uniform sampler2D tLights;
uniform float uDebug;
varying vec2 vQ;
varying float vA;
varying vec3 vE;
varying vec2 vUv;
void main() {
  float r = length(vQ);
  float a = vA * (1.0 - smoothstep(0.55, 1.0, r)) * texture2D(tLights, vUv).g;
  if (a < 0.002) discard;
  gl_FragColor = uDebug > 0.5 ? vec4(a, a, a, 1.0) : vec4(vE * a, a);
}`;

async function snowLayer(ctx, opts) {
  const [tLights, tEnv, meta] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'env.png', { srgb: true }),
    fetch(`/out/plates/${opts.plate}/plate.json`).then((r) => r.json()),
  ]);
  const L = ctx.loopSeconds, F = opts.focalPx ?? 2700;
  const N = opts.count ?? 5000;
  const [zN, zF] = opts.depth ?? [1.5, 25];
  const r = mulberry32((ctx.seed ?? 1) * 4241 + 7);
  const aF = new Float32Array(N * 4), aG = new Float32Array(N * 4);
  for (let i = 0; i < N; i++) {
    const z = zN * Math.pow(zF / zN, Math.pow(r(), opts.depthBias ?? 1.3));
    const D = (opts.size ?? [3, 14])[0] + Math.pow(r(), 2) * ((opts.size ?? [3, 14])[1] - (opts.size ?? [3, 14])[0]);
    const v = (opts.fall ?? 1.0) * (0.75 + 0.5 * r());                  // m/s (snowflakes: ~0.5-1.5)
    const n = Math.max(1, Math.floor((L * v * F / z) / (2160 + 300)));
    aF.set([z, D, n, r()], i * 4);
    aG.set([(opts.flutter ?? 0.12) * (0.5 + r()), Math.max(1, Math.round(L * (0.25 + 0.6 * r()))), n * (2160 + 300) * z / (F * L), r()], i * 4);
  }
  const g = instancedQuad(N);
  g.setAttribute('aF', new THREE.InstancedBufferAttribute(aF, 4));
  g.setAttribute('aG', new THREE.InstancedBufferAttribute(aG, 4));
  const wind = opts.wind ?? {};
  const uWind = new THREE.Vector4(wind.mean ?? 0.4, wind.gust ?? 0.9, Math.max(1, Math.round(wind.gustCycles ?? 4)), wind.fronts ?? 0.6);
  const gust0 = uWind.y;
  const sky = new THREE.Vector3(...(meta.env_linear?.sky ?? [0.1, 0.12, 0.18])).multiplyScalar(opts.skyGain ?? 2.2);
  const warm = new THREE.Color(opts.warm ?? '#ffb26a');
  const mat = new THREE.ShaderMaterial({
    vertexShader: snowVert, fragmentShader: snowFrag, ...PREMUL,
    uniforms: {
      uPhase: { value: 0 }, uLoop: { value: L }, uF: { value: F }, uTime: { value: 0 }, uDensity: { value: 1 },
      uMinW: { value: opts.minWidth ?? 2.2 }, uCoc: { value: opts.coc ?? 34 }, uFocus: { value: opts.focus ?? 25 },
      uWind: { value: uWind }, uFlurry: { value: new THREE.Vector3(0, 1, 0) }, tLights: { value: tLights }, tEnv: { value: tEnv },
      uSky: { value: sky }, uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b).multiplyScalar(opts.warmGain ?? 0.6) },
      uFlash: { value: 0 }, uDebug: { value: opts.debug ? 1 : 0 },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 12;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  ctx.animate((t) => {
    const u = mat.uniforms;
    u.uPhase.value = (t % L) / L;
    u.uTime.value = t;
    u.uDensity.value = Math.min(1, (opts.density ?? 0.85) * trackAt(ctx.timeline?.track, 'rain', t));
    uWind.y = gust0 * trackAt(ctx.timeline?.track, 'wind', t);
    u.uFlurry.value.set(...flurryUniform(ctx.timeline, t));
    u.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
  });
  return mesh;
}

// ------------------------------------------------------------------ dust, fireflies, embers (screen space)
const spriteVert = /* glsl */ `
${GLSL_COMMON}
attribute vec4 aP;      // base x, y (px), seed, size px
attribute vec4 aQ;      // mode-specific
uniform float uPhase, uLoop, uMode, uRate;
uniform vec4 uBox;      // px x0 y0 x1 y1
uniform vec4 uBurst0, uBurst1;    // ember bursts: t since event, n, power, seed (t < 0 = none)
uniform sampler2D tBlur;
uniform vec3 uCol;
varying vec2 vQ;
varying float vA;
varying vec3 vC;
varying vec2 vUv;
varying float vStreak;
void main() {
  float t = uPhase * uLoop;
  vec2 pos = aP.xy;
  float a = 0.0, size = aP.w;
  vec3 col = uCol;
  vec2 vel = vec2(0.0);
  if (uMode < 0.5) {
    // Dust: slow wander (integer cycles) and slow settling that wraps inside the box (faded at the edges).
    float h = aP.z;
    pos.x += 26.0 * sin(TAU * aQ.x * uPhase + h * 30.0) + 11.0 * sin(TAU * (aQ.x * 3.0 + 1.0) * uPhase + h * 7.0);
    float H = uBox.w - uBox.y;
    float yy = fract((aP.y - uBox.y) / H + uPhase * aQ.y);
    pos.y = uBox.y + yy * H + 9.0 * sin(TAU * (aQ.x + 2.0) * uPhase + h * 3.0);
    float edge = smoothstep(0.0, 0.12, yy) * (1.0 - smoothstep(0.88, 1.0, yy));
    float glint = pow(0.5 + 0.5 * sin(TAU * aQ.z * uPhase + h * 50.0), 6.0);
    vec2 uvc = clamp(vec2(pos.x / 3840.0, 1.0 - pos.y / 2160.0), 0.0, 1.0);
    float L = dot(texture2D(tBlur, uvc).rgb, vec3(0.2126, 0.7152, 0.0722));
    a = edge * (0.25 + 0.75 * glint) * smoothstep(0.08, 0.5, L) * aQ.w;
    col = uCol * (0.6 + 1.6 * L);
  } else if (uMode < 1.5) {
    // Fireflies: wander (integer cycles) and blink (one pulse per blink cycle).
    float h = aP.z;
    pos.x += 120.0 * sin(TAU * aQ.x * uPhase + h * 20.0) + 45.0 * sin(TAU * (2.0 * aQ.x + 1.0) * uPhase + h * 9.0);
    pos.y += 60.0 * sin(TAU * (aQ.x + 1.0) * uPhase + h * 13.0) + 25.0 * sin(TAU * (3.0 * aQ.x + 2.0) * uPhase + h * 5.0);
    float b = fract(uPhase * aQ.y + h);
    a = smoothstep(0.0, 0.08, b) * (1.0 - smoothstep(0.12, aQ.z, b)) * aQ.w;
  } else {
    // Embers: steady trickle (slots with integer cycles) + bursts from 'ember' events.
    float h = aP.z;
    float age, life = aQ.y;
    vec2 v0;
    if (aQ.w > 0.5) {
      vec4 B = (gl_InstanceID % 2 == 0) ? uBurst0 : uBurst1;
      float j = floor(float(gl_InstanceID) / 2.0);
      if (B.x < 0.0 || j >= B.y) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vA = 0.0; return; }
      age = B.x - 0.4 * hash1(uint(j) * 13u + uint(B.w));
      h = hash1(uint(j) * 29u + uint(B.w) + 5u);
      pos.x = mix(uBox.x, uBox.z, 0.25 + 0.5 * h);
      pos.y = mix(uBox.y, uBox.w, 0.45);
      v0 = vec2((hash1(uint(j) * 31u + uint(B.w)) - 0.5) * 140.0, -(160.0 + 220.0 * hash1(uint(j) * 37u + uint(B.w)))) * B.z;
      life = 1.0 + 1.6 * hash1(uint(j) * 41u + uint(B.w));
    } else {
      float c = uPhase * aQ.x + h;
      float k = mod(floor(c), aQ.x);
      age = fract(c) * uLoop / aQ.x;
      float r1 = hash1(uint(gl_InstanceID) * 17u + uint(k) * 7u), r2 = hash1(uint(gl_InstanceID) * 19u + uint(k) * 11u);
      if (hash1(uint(gl_InstanceID) * 23u + uint(k)) > uRate) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vA = 0.0; return; }
      pos.x = mix(uBox.x, uBox.z, 0.2 + 0.6 * r1);
      pos.y = mix(uBox.y, uBox.w, 0.35 + 0.3 * r2);
      v0 = vec2((r2 - 0.5) * 60.0, -(70.0 + 120.0 * r1));
    }
    if (age < 0.0 || age > life) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vA = 0.0; return; }
    // Buoyant rise with drag (velocity decays over ~0.9 s), lateral flutter.
    float tc = 0.9;
    pos += v0 * tc * (1.0 - exp(-age / tc));
    pos.x += 10.0 * sin(age * 6.0 + h * 40.0);
    vel = v0 * exp(-age / tc);
    float cool = age / life;
    a = (1.0 - smoothstep(0.55, 1.0, cool)) * smoothstep(0.0, 0.05, age) * (0.6 + 0.4 * sin(age * 23.0 + h * 9.0));
    col = mix(vec3(1.0, 0.62, 0.22), vec3(0.75, 0.16, 0.04), cool) * 2.2;
  }
  // Motion streak along the velocity (embers), round sprite otherwise.
  float spd = length(vel);
  vec2 dir = spd > 1.0 ? vel / spd : vec2(0.0, 1.0);
  float L = spd / 60.0;   // 1/60 s exposure
  vec2 q = position.xy;
  vQ = q;
  vStreak = L / max(size, 1.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  vec2 p = pos + nrm * q.x * size + dir * q.y * (size + 0.5 * L);
  vA = a;
  vC = col;
  vUv = vec2(p.x / 3840.0, 1.0 - p.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const spriteFrag = /* glsl */ `
uniform sampler2D tRegion;
uniform float uMode, uHalo;
uniform ivec4 uIds;
varying vec2 vQ;
varying float vA;
varying vec3 vC;
varying vec2 vUv;
varying float vStreak;
void main() {
  float r = length(vQ);
  float core = 1.0 - smoothstep(0.25, 0.6, r);
  float halo = exp(-r * r * 6.0) * uHalo;
  float a = vA * (core + halo);
  if (uIds.x > 0) {
    int id = int(texelFetch(tRegion, ivec2(clamp(vUv, 0.0, 0.9999) * vec2(textureSize(tRegion, 0))), 0).r * 255.0 + 0.5);
    if (id != uIds.x && id != uIds.y && id != uIds.z && id != uIds.w) a = 0.0;
  }
  if (a < 0.002) discard;
  gl_FragColor = vec4(vC * a, a);
}`;

async function spriteLayer(ctx, opts, mode) {
  const meta = await plateRegions(opts.plate);
  const kinds = { dust: 'kind:dust', fireflies: 'kind:fireflies', embers: 'kind:fire' };
  const regs = pickRegions(meta, opts.regions ?? kinds[opts.mode]);
  const box = opts.box ?? (regs.length ? regs.reduce((b, g) => [Math.min(b[0], g.bbox[0]), Math.min(b[1], g.bbox[1]), Math.max(b[2], g.bbox[2]), Math.max(b[3], g.bbox[3])], [1, 1, 0, 0]) : null);
  if (!box) return null;
  const [tBlur, tRegion] = await Promise.all([plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'regions.png', { nearest: true, optional: true })]);
  const L = ctx.loopSeconds;
  const r = mulberry32((ctx.seed ?? 1) * 7717 + mode * 101 + 3);
  const N = opts.count ?? [140, 18, 70][mode];
  const nB = mode === 2 ? 64 : 0;
  const aP = new Float32Array((N + nB) * 4), aQ = new Float32Array((N + nB) * 4);
  const bx = box.map((v, i) => v * (i % 2 ? 2160 : 3840));
  for (let i = 0; i < N + nB; i++) {
    const x = bx[0] + r() * (bx[2] - bx[0]), y = bx[1] + r() * (bx[3] - bx[1]);
    if (mode === 0) {
      aP.set([x, y, r(), (opts.size ?? 1.6) * (0.7 + 0.8 * r())], i * 4);
      aQ.set([1 + Math.floor(r() * 3), Math.max(1, Math.round(L / (60 + 120 * r()))) * (r() < 0.5 ? 1 : 1), 1 + Math.floor(r() * 4), 0.5 + 0.5 * r()], i * 4);
    } else if (mode === 1) {
      aP.set([x, y, r(), (opts.size ?? 3.2) * (0.8 + 0.5 * r())], i * 4);
      aQ.set([1 + Math.floor(r() * 2), Math.max(1, Math.round(L / (3.5 + 3.5 * r()))), 0.25 + 0.2 * r(), 0.6 + 0.4 * r()], i * 4);
    } else {
      const burst = i >= N;
      aP.set([x, y, r(), (opts.size ?? 1.8) * (0.7 + 0.6 * r())], i * 4);
      aQ.set([Math.max(1, Math.round(L / (2.2 + 2.5 * r()))), 1.0 + 1.4 * r(), 0, burst ? 1 : 0], i * 4);
    }
  }
  const g = instancedQuad(N + nB);
  g.setAttribute('aP', new THREE.InstancedBufferAttribute(aP, 4));
  g.setAttribute('aQ', new THREE.InstancedBufferAttribute(aQ, 4));
  const col = new THREE.Color(opts.color ?? ['#fff1d6', '#d9ff7a', '#ff9a3c'][mode]);
  const ids = [0, 0, 0, 0];
  if (opts.clip !== false && mode !== 2) regs.slice(0, 4).forEach((gg, i) => { ids[i] = gg.id; });
  const mat = new THREE.ShaderMaterial({
    vertexShader: spriteVert, fragmentShader: spriteFrag, ...(mode === 0 ? PREMUL : ADD),
    uniforms: {
      uPhase: { value: 0 }, uLoop: { value: L }, uMode: { value: mode }, uRate: { value: opts.rate ?? 0.6 },
      uBox: { value: new THREE.Vector4(...bx) }, uBurst0: { value: new THREE.Vector4(-1, 0, 0, 0) }, uBurst1: { value: new THREE.Vector4(-1, 0, 0, 0) },
      tBlur: { value: tBlur }, tRegion: { value: tRegion }, uIds: { value: new THREE.Vector4(...ids) },
      uCol: { value: new THREE.Vector3(col.r, col.g, col.b).multiplyScalar(opts.gain ?? [0.9, 2.4, 1][mode]) },
      uHalo: { value: opts.halo ?? [0.15, 0.55, 0.35][mode] },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? [45, 14, 42][mode];
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const bursts = mode === 2 ? (ctx.timeline?.events ?? []).filter((e) => e.type === 'ember') : [];
  ctx.animate((t) => {
    const u = mat.uniforms;
    u.uPhase.value = (t % L) / L;
    if (mode === 2) {
      const act = bursts.filter((e) => t >= e.t && t < e.t + 3.2).slice(-2);
      [u.uBurst0, u.uBurst1].forEach((B, i) => {
        const e = act[i];
        B.value.set(e ? t - e.t : -1, e ? Math.min(32, e.n * 2) : 0, e ? e.power : 0, e ? e.seed % 100000 : 0);
      });
    }
  });
  return mesh;
}

// ------------------------------------------------------------------ shooting stars
const starVert = /* glsl */ `
uniform vec4 uSeg;     // x0 y0 x1 y1 (px) of the current meteor
uniform float uProg, uPow;
varying vec2 vQ;
varying float vA;
varying vec2 vUv;
void main() {
  vec2 a = uSeg.xy, b = uSeg.zw;
  vec2 head = mix(a, b, uProg);
  vec2 tail = mix(a, b, max(0.0, uProg - 0.35));
  vec2 dir = normalize(b - a), nrm = vec2(-dir.y, dir.x);
  vec2 q = position.xy;
  vec2 c = mix(tail, head, q.y * 0.5 + 0.5);
  vec2 p = c + nrm * q.x * 3.0;
  vQ = q;
  vA = uPow;
  vUv = vec2(p.x / 3840.0, 1.0 - p.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
const starFrag = /* glsl */ `
uniform sampler2D tMask;
varying vec2 vQ;
varying float vA;
varying vec2 vUv;
void main() {
  float along = vQ.y * 0.5 + 0.5;               // 0 tail .. 1 head
  float a = vA * pow(along, 2.2) * (1.0 - smoothstep(0.3, 1.0, abs(vQ.x))) * texture2D(tMask, vUv).r;
  if (a < 0.002) discard;
  gl_FragColor = vec4(vec3(0.85, 0.9, 1.0) * a * 1.6, a);
}`;

async function starLayer(ctx, opts) {
  const ev = (ctx.timeline?.events ?? []).filter((e) => e.type === 'star');
  if (!ev.length) return null;
  const tMask = await plateTexture(opts.plate, 'masks.png');
  const mat = new THREE.ShaderMaterial({
    vertexShader: starVert, fragmentShader: starFrag, ...ADD,
    uniforms: { uSeg: { value: new THREE.Vector4() }, uProg: { value: 0 }, uPow: { value: 0 }, tMask: { value: tMask } },
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 6;
  ctx.add(mesh);
  ctx.animate((t) => {
    const e = ev.find((x) => t >= x.t && t <= x.t + x.dur);
    mesh.visible = !!e;
    if (!e) return;
    const s = (t - e.t) / e.dur;
    mat.uniforms.uSeg.value.set(e.x0 * 3840, e.y0 * 2160, e.x1 * 3840, e.y1 * 2160);
    mat.uniforms.uProg.value = s;
    mat.uniforms.uPow.value = e.power * Math.sin(Math.PI * Math.min(1, s * 1.15)) * (opts.gain ?? 0.8);
  });
  return mesh;
}

export async function particleLayer(ctx, opts) {
  switch (opts.mode) {
    case 'snow': return snowLayer(ctx, opts);
    case 'dust': return spriteLayer(ctx, opts, 0);
    case 'fireflies': return spriteLayer(ctx, opts, 1);
    case 'embers': return spriteLayer(ctx, opts, 2);
    case 'stars': return starLayer(ctx, opts);
    default: throw new Error(`particleLayer: unknown mode ${opts.mode}`);
  }
}
