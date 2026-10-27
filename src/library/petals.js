// Cherry petals for plate scenes, driven by the event timeline (timeline.js petalSchedule): specks drifting down
// from a blossoming tree in the plate, and now and then a petal blown past near the opening that lands on the
// wet street and lies there a while before the rain dulls it. Gust flurries shake a burst of both loose. Each
// petal's flight is a pure function of time: it falls at a petal's terminal speed (~0.7 m/s), sways and tilts
// with the swing, tumbles (its width flips as it turns), and drifts with the scene's wind and gust flurries
// (exact drift integrals, the same as the rain's). It is lit by the light around it (env.png, plus lantern glow)
// and motion-blurred over the shutter. Tree petals hide behind anything nearer than the tree (depth8.png); all
// petals sit behind everything indoors (lights.png G = 0: the counter, the noren, the lanterns).
//
// opts: { plate, tree: region name (its depth: default the first region named like 'cherry'/'blossom'), focal (2700),
//   horizon (0.45), camH (1.1 m: the street lies this far below the eye, where near petals land), color ('#f7cbd6'),
//   grow: { tree: 3.2, near: 1.5 } (size over life: a tree petal is ~1.5 px at 25 m, too small to read in the video at
//   2x; the ramen alley's are ~5 px), shutter (1/60), ambient (0.55),
//   warm (0.8) }
import * as THREE from 'three';
import { flashAt, trackAt, windDrift, flurryDrift } from './timeline.js';
import { plateTexture, plateRegions, imagePixels } from './overlay.js';
import { toLin } from './util.js';

const W = 3840, H = 2160;

const vert = /* glsl */ `
attribute vec4 aA, aB;   // state at shutter open / close: center x, y (px, y down), angle, flip (cos of the tumble)
attribute vec4 aC;       // size (px), depth8 of the petal (0: no depth test), lying: 0 in flight, else 1 / sin(view angle) (flat), seed
attribute vec4 aD;       // linear albedo rgb, alpha (0: unused slot)
varying vec2 vPx, vUv;
varying vec4 vA, vB, vC, vD;
void main() {
  vA = aA; vB = aB; vC = aC; vD = aD;
  vec2 c = 0.5 * (aA.xy + aB.xy);
  float hs = (0.7 * aC.x + 0.5 * length(aB.xy - aA.xy) + 2.0) * step(0.001, aD.w);
  vec2 p = c + position.xy * hs;
  vPx = p;
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights, tEnv, tDepth;
uniform vec3 uWarm;
uniform float uAmb, uWarmK, uEnvRef, uFlash;
varying vec2 vPx, vUv;
varying vec4 vA, vB, vC, vD;
uniform float uDbg;
void main() {
  if (uDbg > 0.5) { gl_FragColor = vec4(1.0, 0.0, 1.0, 1.0); return; }   // QA: show the quads
  float cov = 0.0, sh = 0.0;
  float aa = 1.0 / max(vC.x, 0.5);         // one screen px in petal units
  for (int i = 0; i < 4; i++) {            // 4 samples across the shutter (motion blur)
    float l = (float(i) + 0.5) / 4.0;
    vec2 c = mix(vA.xy, vB.xy, l);
    float ang = mix(vA.z, vB.z, l), fl = mix(vA.w, vB.w, l);
    vec2 d = vPx - c;
    float cs = cos(ang), sn = sin(ang);
    vec2 q = vec2(cs * d.x + sn * d.y, -sn * d.x + cs * d.y) / vC.x;
    // lying on the ground: seen at a low angle, flattened by 1 / sin of the view angle
    q.y *= max(vC.z, 1.0);
    float af = max(abs(fl), 0.12);
    q.x /= af;
    // a cherry petal: an oval with a notch at its tip (tip toward +y)
    float e = length(vec2(q.x / 0.34, q.y / 0.5));
    float k = 1.0 - smoothstep(1.0 - aa * 2.5, 1.0 + aa * 2.5, e);
    float notch = length(q - vec2(0.0, 0.52)) / 0.12;
    k *= smoothstep(1.0 - aa * 6.0, 1.0 + aa * 6.0, notch);
    k *= smoothstep(0.04, 0.14, abs(fl)) * 0.85 + 0.15;    // edge-on it thins out
    cov += k * 0.25;
    sh += k * 0.25 * (0.82 + 0.18 * smoothstep(-0.5, 0.4, q.y)) * (0.6 + 0.4 * abs(fl));   // deeper pink at the base, tilt shading
  }
  if (cov < 0.002) discard;
  float shade = sh / cov;
  vec4 lt = texture2D(tLights, vUv);
  cov *= lt.g;                             // outdoors only
  if (vC.y > 0.0) cov *= 1.0 - smoothstep(vC.y * 1.06 + 0.01, vC.y * 1.12 + 0.02, texture2D(tDepth, vUv).r);
  cov *= vD.w;
  if (cov < 0.002) discard;
  vec3 env = texture2D(tEnv, vUv).rgb;
  vec3 light = uAmb * env / uEnvRef + uWarmK * lt.b * uWarm;
  vec3 rgb = vD.rgb * shade * light * (1.0 + 0.6 * uFlash);
  rgb *= mix(1.0, 0.7, clamp(vC.z, 0.0, 1.0));   // wet on the ground: darker
  gl_FragColor = vec4(rgb * cov, cov);
}`;

export async function petalsLayer(ctx, opts) {
  const petals = ctx.timeline?.petals ?? [];
  if (!petals.length) return null;
  const meta = await plateRegions(opts.plate);
  const regs = meta.regions ?? meta ?? [];
  const treeReg = (Array.isArray(regs) ? regs : []).find((r) => (opts.tree ? r.name === opts.tree : /cherry|blossom|sakura/.test(r.name)));
  const [tLights, tEnv, tDepth] = await Promise.all([plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'env.png', { srgb: true }), plateTexture(opts.plate, 'depth8.png')]);
  const pj = await fetch(`/out/plates/${opts.plate}/plate.json`).then((r) => r.json());
  const envRef = (() => { const e = pj.env_linear?.outdoor ?? [0.07, 0.06, 0.1]; return 0.2126 * e[0] + 0.7152 * e[1] + 0.0722 * e[2]; })();
  // the tree's depth (depth8) and distance: ppm from the region's disparity (the birds' calibration: ~1990 px per
  // m per unit of disparity), so a 1.4 cm petal at ~25 m is ~1.5 px before `grow`
  let treeD = 0, treePpm = 100;
  if (treeReg) {
    const dep = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
    const [x0, y0, x1, y1] = treeReg.bbox;
    const vals = [];
    for (let j = 0; j <= 12; j++) for (let i = 0; i <= 12; i++) {
      const ix = Math.round((x0 + (x1 - x0) * i / 12) * (dep.width - 1)), iy = Math.round((y0 + (y1 - y0) * j / 12) * (dep.height - 1));
      vals.push(dep.data[(iy * dep.width + ix) * 4] / 255);
    }
    vals.sort((a, b) => a - b);
    treeD = vals[Math.floor(vals.length / 2)];
    treePpm = opts.treePpm ?? (treeReg.disp ? 1990 * treeReg.disp : 100);
  }
  const F = opts.focal ?? 2700, horizon = (opts.horizon ?? 0.45) * H, camH = opts.camH ?? 1.1, shutter = opts.shutter ?? 1 / 60;
  const grow = { tree: 3.2, near: 1.5, ...(opts.grow ?? {}) };
  const base = new THREE.Color(opts.color ?? '#f7cbd6');
  const alb = [toLin(base.r), toLin(base.g), toLin(base.b)].map((v) => Math.min(1, v));
  // (THREE.Color stores linear values already when ColorManagement is on; guard against double conversion)
  const albedo = THREE.ColorManagement?.enabled ? [base.r, base.g, base.b] : alb;
  const wv = opts.wind ?? {};
  const w = { mean: wv.mean ?? 0, gust: wv.gust ?? 0, gustCycles: Math.max(1, Math.round(wv.gustCycles ?? 5)), fronts: wv.fronts ?? 0.6, loop: ctx.loopSeconds };
  const MAX = 96;
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const attr = {};
  for (const k of ['aA', 'aB', 'aC', 'aD']) {
    attr[k] = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
    attr[k].setUsage(THREE.DynamicDrawUsage);
    g.setAttribute(k, attr[k]);
  }
  g.instanceCount = MAX;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false, side: THREE.DoubleSide,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tEnv: { value: tEnv }, tDepth: { value: tDepth }, uWarm: { value: new THREE.Color('#ffb070') },
      uAmb: { value: opts.ambient ?? 0.55 }, uWarmK: { value: opts.warm ?? 0.8 }, uEnvRef: { value: envRef }, uFlash: { value: 0 }, uDbg: { value: ctx.params?.petaldebug === 'quad' ? 1 : 0 },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 21;
  mesh.userData.noAO = true;
  ctx.add(mesh);

  const tl = ctx.timeline;
  // a near petal lands where the street at its distance is (the ground plane camH below the eye)
  const groundY = (z) => horizon + F * camH / z;
  const flight = (P, age, gustK) => {
    const ph = 2 * Math.PI * P.f * age + P.ph;
    const drift = P.A * Math.sin(ph) + (P.vx ?? 0) * age + windDrift(w, P.t, P.t + age, P.x, gustK) + flurryDrift(tl, P.t, P.t + age);
    const ang = P.th0 + P.B * Math.cos(ph) + P.spin * age;
    const fl = Math.cos(2 * Math.PI * P.fl * age + 1.7 * P.ph);
    return { drift, fall: P.vt * age + 0.04 * Math.cos(2 * ph), ang, fl };
  };
  // each petal drifts with the gust strength of its own moment (a pure function of the petal: deterministic
  // wherever a render segment starts, and the same in flight and where it lands)
  const gustOf = (P) => trackAt(tl?.track, 'wind', P.t);
  const nearInfo = new Map();
  const landing = (P) => {
    let v = nearInfo.get(P);
    if (v) return v;
    const gustK = gustOf(P);
    const ppm = F / P.z, size = P.s * ppm * grow.near;
    const yg = groundY(P.z), y0 = -size - 10;
    // first time its fall reaches the ground row (the bob is small: solve on the mean fall, then refine)
    let a = Math.max(0, (yg - y0) / (P.vt * ppm));
    for (let i = 0; i < 3; i++) { const f = flight(P, a, gustK); a += (yg - (y0 + f.fall * ppm)) / (P.vt * ppm); }
    v = { ppm, size, yg, y0, aLand: a, sq: Math.min(8, F / Math.max(1, yg - horizon)) };
    nearInfo.set(P, v);
    return v;
  };
  const state = (P, time) => {
    const age = time - P.t, gustK = gustOf(P);
    if (P.k === 0) {
      const ppm = treePpm, f = flight(P, age, gustK);
      // most land out of sight (behind the nearer street); any still in the air at the end of its life fades out
      return { x: P.x * W + f.drift * ppm, y: P.y * H + f.fall * ppm, ang: f.ang, fl: f.fl, lie: 0, size: P.s * ppm * grow.tree, a: Math.min(1, age / 0.4, (P.dur - age) / 1.0) };
    }
    const L = landing(P);
    if (age < L.aLand) {
      const f = flight(P, age, gustK);
      return { x: P.x * W + f.drift * L.ppm, y: L.y0 + f.fall * L.ppm, ang: f.ang, fl: f.fl, lie: 0, size: L.size, a: 1 };
    }
    // lying where it landed, flat, until the rain dulls it
    const f = flight(P, L.aLand, gustK);
    const tl2 = age - L.aLand;
    const lie = Math.min(1, tl2 / 0.15);
    return { x: P.x * W + f.drift * L.ppm, y: L.yg, ang: f.ang, fl: 1, lie: 1 + lie * (L.sq - 1), size: L.size, a: 1 - Math.min(1, Math.max(0, (tl2 - 0.5 * P.stay) / (0.5 * P.stay))) };
  };
  const life = (P) => (P.k === 0 ? P.dur : (landing(P).aLand + P.stay));
  const maxDur = Math.max(...petals.map((P) => (P.k === 0 ? P.dur : P.stay + 20)));
  ctx.animate((t) => {
    let lo = 0, hi = petals.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (petals[m].t < t - maxDur) lo = m + 1; else hi = m; }
    let n = 0;
    for (let i = lo; i < petals.length && petals[i].t <= t + shutter && n < MAX; i++) {
      const P = petals[i];
      if (t - shutter > P.t + life(P) || t + shutter / 2 < P.t) continue;
      const a = state(P, Math.max(P.t, t - shutter / 2)), b = state(P, t + shutter / 2);
      if (b.x < -60 || b.x > W + 60 || b.y > H + 60) continue;
      const tone = 0.88 + 0.24 * P.c;
      attr.aA.array.set([a.x, a.y, a.ang, a.fl], n * 4);
      attr.aB.array.set([b.x, b.y, b.ang, b.fl], n * 4);
      attr.aC.array.set([Math.max(1.2, b.size), P.k === 0 ? treeD : 0, b.lie, (i * 7.31) % 97], n * 4);
      attr.aD.array.set([albedo[0] * tone, albedo[1] * tone, albedo[2] * (0.95 + 0.1 * P.c), Math.max(0, b.a)], n * 4);
      n++;
    }
    if (ctx.params?.petaldebug === 'log') console.warn(`petals t=${t.toFixed(2)}: ${n} in flight or lying`);
    for (let i = n; i < MAX; i++) attr.aD.array[i * 4 + 3] = 0;
    for (const k of Object.keys(attr)) attr[k].needsUpdate = true;
    mat.uniforms.uFlash.value = flashAt(tl, t).flash;
  });
  return mesh;
}
