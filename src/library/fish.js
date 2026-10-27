// Ambient event: a fish rises on open water (timeline event type 'fish'). Expanding rings on the water,
// drawn as perspective ellipses through the plate-matched lake camera (boat.js lakeCamera): at these
// distances a ring is a thin, flat, widening ellipse, so ring lines are kept ~1 px thick in screen space
// (4 sub-samples: no shimmer). A splash crown and a few droplets go up at the start; on a "jump" the fish
// leaps out first (a small dark arc) and lands with a second, smaller splash. Rings stay on the water mask;
// everything is hidden behind the porch (outdoor mask). Pure function of the event and time.
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { lakeCamera } from './boat.js';
import { loadTex } from './overlay.js';

const vert = /* glsl */ `
uniform vec4 uBox;
uniform vec2 uRes;
varying vec2 vPx;
void main() {
  vec2 p = position.xy * 0.5 + 0.5;
  vPx = mix(uBox.xy, uBox.zw, vec2(p.x, 1.0 - p.y));
  gl_Position = vec4(vPx.x / uRes.x * 2.0 - 1.0, 1.0 - vPx.y / uRes.y * 2.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
precision highp float;
uniform sampler2D tLights, tMask, tEnv;
uniform vec2 uRes;
uniform vec2 uC;          // splash center (px, y down)
uniform float uPpm;       // px per m at the splash
uniform float uSin;       // sine of the view angle down onto the water (ellipse flattening)
uniform float uTau;       // s since the event started
uniform float uSize, uJump, uDirX, uFlash, uDebug, uSeed;
varying vec2 vPx;
const float G = 9.81;
float h11(float n) { return fract(sin(n * 127.1 + uSeed * 0.013) * 43758.5453); }

// One ring: an ellipse of radius R (m) around the splash, ~1.5 px line. Returns line intensity at offset d (px).
float ring(vec2 d, float R) {
  float a = max(R * uPpm, 0.5), b = max(R * uPpm * uSin, 0.5);
  vec2 e = d / vec2(a, b);
  float rho = length(e);
  vec2 g = vec2(e.x / a, e.y / b) / max(rho, 1e-4);          // gradient of rho (per px)
  float dpx = abs(rho - 1.0) / max(length(g), 1e-4);
  return smoothstep(1.5, 0.0, dpx);
}
// Inside the newest ring the mirror-flat surface is broken up: it scatters a little more sky light.
float disc(vec2 d, float R) {
  float a = max(R * uPpm, 0.5), b = max(R * uPpm * uSin, 0.5);
  return 1.0 - smoothstep(0.6, 1.0, length(d / vec2(a, b)));
}

void main() {
  vec2 uv = vec2(vPx.x / uRes.x, 1.0 - vPx.y / uRes.y);
  float outdoor = texture2D(tLights, uv).g;
  if (outdoor < 0.004) discard;
  float water = texture2D(tMask, uv).g;
  vec3 env = texture2D(tEnv, uv).rgb;
  vec3 sky = env * 2.6 + vec3(0.012, 0.016, 0.03);
  vec3 add = vec3(0.0);
  float dark = 0.0;
  // A jump: the fish is out of the water for 0.45 s, then the rings start where it lands.
  float tl = uJump > 0.5 ? 0.45 : 0.0;
  float t1 = uTau - tl;                         // time since the (main) entry
  vec2 land = uC + vec2(uDirX * 0.35 * uPpm * uSize, 0.0);
  vec2 rc = uJump > 0.5 ? land : uC;
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    vec2 d = vPx + o - rc;
    // Rings: 3 crests spreading at ~0.3 m/s, fading with time and spreading.
    if (t1 > 0.0) {
      for (int k = 0; k < 3; k++) {
        float tk = t1 - 0.22 * float(k);
        if (tk <= 0.0) continue;
        float R = (0.1 + 0.3 * tk) * uSize;
        float A = (1.0 - 0.28 * float(k)) * exp(-tk / 2.4) / sqrt(1.0 + R / 0.35);
        add += 0.55 * sky * A * ring(d, R) * water;
        dark += 0.2 * A * ring(d, R - 0.05 * uSize) * water;    // trough just inside the crest
        if (k == 0) add += 0.07 * sky * A * disc(d, R) * water;
      }
    }
    // A jump: smaller rings where the fish left the water, and the fish itself in the air.
    if (uJump > 0.5 && uTau > 0.0) {
      vec2 d0 = vPx + o - uC;
      for (int k = 0; k < 2; k++) {
        float tk = uTau - 0.22 * float(k);
        if (tk <= 0.0) continue;
        float R = (0.06 + 0.3 * tk) * uSize * 0.7;
        float A = 0.6 * (1.0 - 0.3 * float(k)) * exp(-tk / 2.0) / sqrt(1.0 + R / 0.35);
        add += 0.55 * sky * A * ring(d0, R) * water;
      }
      // The fish: a slender dark arc on a parabola (0.35 m forward, 0.35 m high) for 0.45 s.
      float u = uTau / 0.45;
      if (u > 0.0 && u < 1.0) {
        vec2 fp = uC + vec2(uDirX * 0.35 * uPpm * uSize * u, -0.35 * uPpm * uSize * 4.0 * u * (1.0 - u));
        vec2 vel = vec2(uDirX * 0.35 * uSize, -0.35 * uSize * 4.0 * (1.0 - 2.0 * u));
        vec2 ax = normalize(vel);
        vec2 q = vPx + o - fp;
        vec2 ql = vec2(dot(q, ax), dot(q, vec2(-ax.y, ax.x)));
        vec2 semi = vec2(max(0.17 * uPpm * uSize, 2.2), max(0.035 * uPpm * uSize, 0.75));   // px, never sub-pixel
        float body = smoothstep(1.0, 0.75, length(ql / semi));
        dark += 0.9 * body;
        add += 0.06 * sky * body;                  // a wet glint along its back
      }
    }
    // Splash crown + droplets at the (main) entry: bright, up to ~0.3 m, gone after ~0.7 s.
    if (t1 > 0.0 && t1 < 0.8) {
      vec2 d = vPx + o - rc;
      float hC = 0.28 * uSize * uPpm * sin(3.14159 * min(t1 / 0.32, 1.0)) * step(t1, 0.32);
      float crown = exp(-pow(d.x / max(0.12 * uSize * uPpm, 0.9), 2.0)) * smoothstep(0.0, -1.0, d.y) * smoothstep(-hC - 1.0, -hC + 0.5, d.y);
      add += 0.35 * sky * crown * smoothstep(0.32, 0.1, t1);
      for (int k = 0; k < 7; k++) {
        float fk = float(k);
        float vx = (h11(fk * 3.1) - 0.5) * 1.2 * uSize, vy = (1.4 + 1.8 * h11(fk * 5.7)) * sqrt(uSize);
        float y = vy * t1 - 0.5 * G * t1 * t1;
        if (y < 0.0) continue;
        vec2 p = rc + vec2(vx * t1, -y) * uPpm;
        float r = max(0.012 * uPpm, 0.7);
        add += 0.5 * sky * exp(-dot(vPx + o - p, vPx + o - p) / (r * r));
      }
    }
  }
  add *= 0.25; dark *= 0.25;
  add *= (1.0 + 0.8 * uFlash);
  dark = clamp(dark, 0.0, 0.9);
  vec4 outc = vec4(add, dark) * outdoor;
  if (uDebug > 0.5) { float c = max(dark, dot(add, vec3(1.0))); gl_FragColor = vec4(c, c, c, 1.0); return; }
  gl_FragColor = outc;
}`;

// opts: { plate, camera: {focalPx, horizon, height} (the boat route's lake camera), debug }
export async function fishLayer(ctx, opts) {
  const fish = (ctx.timeline?.events ?? []).filter((e) => e.type === 'fish');
  if (!fish.length) return null;
  const W = 3840, H = 2160;
  const cam = lakeCamera({ ...opts.camera, W, H });
  const dir = `/out/plates/${opts.plate}`;
  const [tLights, tMask, tEnv] = await Promise.all([loadTex(`${dir}/lights.png`), loadTex(`${dir}/masks.png`), loadTex(`${dir}/env.png`, { srgb: true })]);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
    blendDst: opts.debug ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tMask: { value: tMask }, tEnv: { value: tEnv }, uRes: { value: new THREE.Vector2(W, H) },
      uBox: { value: new THREE.Vector4() }, uC: { value: new THREE.Vector2() }, uPpm: { value: 20 }, uSin: { value: 0.1 },
      uTau: { value: 0 }, uSize: { value: 1 }, uJump: { value: 0 }, uDirX: { value: 1 }, uFlash: { value: 0 },
      uDebug: { value: opts.debug ? 1 : 0 }, uSeed: { value: 0 },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 4;          // on the plate, under the boat, rain and leaves
  mesh.visible = false;
  ctx.add(mesh);
  ctx.animate((t) => {
    let ev = null;
    for (const e of fish) { if (e.t > t) break; if (t <= e.t + e.dur) ev = e; }
    mesh.visible = !!ev;
    if (!ev) return;
    const m = mat.uniforms;
    const P = cam.toWater(ev.x, ev.y);
    const dist = Math.hypot(P[0] - cam.C[0], cam.C[1], P[2] - cam.C[2]);
    const ppm = cam.pxPerM(dist);
    const cx = ev.x * W, cy = ev.y * H;
    const R = (0.1 + 0.3 * ev.dur) * ev.size * ppm + 4;
    m.uC.value.set(cx, cy);
    m.uPpm.value = ppm;
    m.uSin.value = cam.C[1] / dist;
    m.uTau.value = t - ev.t;
    m.uSize.value = ev.size;
    m.uJump.value = ev.jump;
    m.uDirX.value = ev.seed % 2 ? 1 : -1;
    m.uSeed.value = ev.seed % 9973;
    m.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
    const up = 0.5 * ev.size * ppm + 6;
    m.uBox.value.set(Math.max(0, cx - R - 0.4 * ppm), Math.max(0, cy - Math.max(R * m.uSin.value, up) - 4), Math.min(W, cx + R + 0.4 * ppm), Math.min(H, cy + R * m.uSin.value + 6));
  });
  return mesh;
}
