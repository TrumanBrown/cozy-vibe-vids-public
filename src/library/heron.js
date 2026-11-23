// Spotlight event: a grey heron crosses the valley (timeline event type 'heron'). A side-view silhouette
// (retracted S-neck, dagger bill, trailing legs, broad wings flapping ~2 Hz with short glides) flown on a
// straight, slightly rising or sinking line through the plate-matched lake camera (boat.js lakeCamera),
// so its size and speed follow from its distance (160-280 m: ~20 px long at 4K). 4 sub-samples per pixel
// (no shimmer). Hazed toward the blurred plate (airlight, opaque: nothing shows through it), hidden behind
// the porch (outdoor mask) and behind clearly nearer scenery (plate depth). Pure function of the event.
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
uniform sampler2D tLights, tDepth, tPlate, tEnv;
uniform vec2 uRes;
uniform vec2 uC;          // body center (px, y down)
uniform float uPpm, uDir; // px per m; +1 flying right
uniform float uWingN, uWingF, uBob;   // near/far wing tip heights above the shoulder (m); body bob (m)
uniform float uHaze, uAirLod, uDisp, uFlash, uVis, uDebug;
varying vec2 vPx;

float ell(vec2 p, vec2 c, vec2 r) { return length((p - c) / r) - 1.0; }          // < 0 inside (approx, in radii)
float seg(vec2 p, vec2 a, vec2 b, float r) {                                      // capsule distance (m)
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h) - r;
}
// Wing seen from the side: from the shoulder (root chord) to the tip height (narrower tip chord, swept
// back). Box-like signed distance (m): < 0 inside.
float wing(vec2 p, float tip) {
  float y0 = 0.03, lo = min(y0, tip), hi = max(y0, tip);
  float v = clamp((p.y - y0) / (abs(tip - y0) < 1e-3 ? 1e-3 : tip - y0), 0.0, 1.0);
  float xl = mix(-0.22, -0.30, v), xr = mix(0.17, -0.02, v * v);
  return max(max(xl - p.x, p.x - xr), max(lo - p.y, p.y - hi));
}
float heron(vec2 p) {                                                             // coverage 0..1 (soft edge ~1 px)
  float px = 1.0 / uPpm;
  float d = 1e3;
  d = min(d, ell(p, vec2(0.0, 0.0), vec2(0.36, 0.085)) * 0.085);                // body
  d = min(d, ell(p, vec2(0.30, -0.035), vec2(0.13, 0.085)) * 0.085);            // tucked neck bulge
  d = min(d, ell(p, vec2(0.42, 0.055), vec2(0.085, 0.055)) * 0.055);            // head
  d = min(d, seg(p, vec2(0.47, 0.06), vec2(0.73, 0.035), 0.012));               // bill
  d = min(d, seg(p, vec2(-0.30, -0.02), vec2(-0.86, -0.07), 0.016));            // trailing legs
  d = min(d, seg(p, vec2(-0.84, -0.07), vec2(-0.90, -0.075), 0.022));           // feet
  float cov = smoothstep(0.6 * px, -0.6 * px, d);
  float w = min(wing(p, uWingN), wing(p, uWingF));
  cov = max(cov, smoothstep(0.6 * px, -0.6 * px, w));
  return cov;
}

void main() {
  vec2 uv = vec2(vPx.x / uRes.x, 1.0 - vPx.y / uRes.y);
  float outdoor = texture2D(tLights, uv).g;
  if (outdoor < 0.004) discard;
  // Nearer scenery (clearly larger plate disparity than the bird's) hides it.
  float dp = texture2D(tDepth, uv).r; dp *= dp;
  float front = 1.0 - smoothstep(uDisp * 1.35, uDisp * 1.8, dp);
  float cov = 0.0;
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    vec2 d = (vPx + o - uC) / uPpm;                  // m, y down
    vec2 p = vec2(d.x * uDir, -d.y - uBob);          // body frame: x forward, y up
    cov += heron(p);
  }
  cov *= 0.25 * front * outdoor * uVis;
  if (cov <= 0.0) discard;
  vec3 env = texture2D(tEnv, uv).rgb;
  vec3 bird = vec3(0.10, 0.10, 0.11) * (env * 2.2 + vec3(0.01)) * (1.0 + 0.8 * uFlash);
  vec3 air = textureLod(tPlate, uv, uAirLod).rgb;
  vec3 col = mix(bird, air, uHaze);
  if (uDebug > 0.5) { gl_FragColor = vec4(vec3(cov), 1.0); return; }
  gl_FragColor = vec4(col * cov, cov);
}`;

// Heron position (world, m) at time t: x across, altitude, distance in front of the camera. The flight line
// isn't ruler-straight: a gentle rise and fall (~5 s) and a small surge in speed, as a flapping bird has.
export function heronPose(ev, t) {
  const u = Math.min(Math.max((t - ev.t) / ev.dur, 0), 1);
  const half = ev.dur * ev.speed / 2, tau = u * ev.dur, ph = 2 * Math.PI * ev.phase;
  const surge = 0.6 * Math.sin(2 * Math.PI * tau / 3.7 + ph) * Math.sin(Math.PI * u);
  const lift = (0.45 * Math.sin(2 * Math.PI * tau / 5.3 + 2 * ph) + 0.2 * Math.sin(2 * Math.PI * tau / 2.9 + 3 * ph)) * Math.sin(Math.PI * u);
  return { u, x: ev.dir * (-half + 2 * half * u + surge), y: ev.alt + ev.sink * (u - 0.5) + lift, z: -ev.dist };
}

// opts: { plate, camera: {focalPx, horizon, height}, dispScale (plate disparity x distance, m), haze (m), debug }
export async function heronLayer(ctx, opts) {
  const herons = (ctx.timeline?.events ?? []).filter((e) => e.type === 'heron');
  if (!herons.length) return null;
  const W = 3840, H = 2160;
  const cam = lakeCamera({ ...opts.camera, W, H });
  const dir = `/out/plates/${opts.plate}`;
  const [tLights, tDepth, tPlate, tEnv] = await Promise.all([loadTex(`${dir}/lights.png`), loadTex(`${dir}/depth8.png`),
    loadTex(`${dir}/plate.png`, { srgb: true, mips: true }), loadTex(`${dir}/env.png`, { srgb: true })]);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
    blendDst: opts.debug ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tDepth: { value: tDepth }, tPlate: { value: tPlate }, tEnv: { value: tEnv },
      uRes: { value: new THREE.Vector2(W, H) }, uBox: { value: new THREE.Vector4() }, uC: { value: new THREE.Vector2() },
      uPpm: { value: 10 }, uDir: { value: 1 }, uWingN: { value: 0.5 }, uWingF: { value: 0.5 }, uBob: { value: 0 },
      uHaze: { value: 0.3 }, uAirLod: { value: 4 }, uDisp: { value: 0.03 }, uFlash: { value: 0 }, uVis: { value: 1 },
      uDebug: { value: opts.debug ? 1 : 0 },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 6;          // on the plate, under rain and leaves
  mesh.visible = false;
  ctx.add(mesh);
  const K = opts.dispScale ?? 5.5, hazeM = opts.haze ?? 650;
  ctx.animate((t) => {
    let ev = null;
    for (const e of herons) if (t >= e.t && t <= e.t + e.dur) { ev = e; break; }
    mesh.visible = !!ev;
    if (!ev) return;
    const m = mat.uniforms, tau = t - ev.t;
    const p = heronPose(ev, t);
    const q = cam.project([p.x, p.y, p.z]);
    const ppm = cam.pxPerM(q[2]);
    // Wingbeat: deep and slow, each beat a little different (amplitude and pace wander), with glides (wings
    // held slightly bowed) a share of the time when the event has a glide share > 0.
    const ph = 2 * Math.PI * (ev.flapHz * tau + 0.05 * Math.sin(2 * Math.PI * tau / 3.1 + 7 * ev.phase) + ev.phase);
    const gl = Math.sin(2 * Math.PI * (tau / 9 + ev.phase));
    const glide = ev.glide > 0 ? Math.min(Math.max((gl - (1 - 2 * ev.glide)) / 0.35, 0), 1) : 0;
    const depth = 0.62 * (0.88 + 0.12 * Math.sin(2 * Math.PI * tau / 2.3 + 5 * ev.phase));
    const ang = (1 - glide) * (0.12 + depth * Math.sin(ph)) + glide * -0.07;
    const half = 0.88, elev = Math.atan2(p.y - cam.C[1], -p.z);
    m.uWingN.value = 0.03 + half * (Math.sin(ang) + Math.cos(ang) * Math.sin(elev));
    m.uWingF.value = 0.03 + half * (Math.sin(ang) - Math.cos(ang) * Math.sin(elev));
    m.uBob.value = -0.035 * (1 - glide) * Math.sin(ph);
    m.uC.value.set(q[0], q[1]);
    m.uPpm.value = ppm;
    m.uDir.value = ev.dir;
    m.uHaze.value = 1 - Math.exp(-q[2] / hazeM);
    m.uAirLod.value = Math.min(Math.max(Math.log2(ppm * 2), 3), 7);
    m.uDisp.value = K / q[2];
    m.uVis.value = Math.min(1, tau / 1.5, (ev.dur - tau) / 1.5);
    m.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
    const ex = 1.0 * ppm + 4, ey = 1.1 * ppm + 4;
    m.uBox.value.set(Math.max(0, q[0] - ex), Math.max(0, q[1] - ey), Math.min(W, q[0] + ex), Math.min(H, q[1] + ey));
  });
  return mesh;
}
