// Ambient event: small birds crossing the sky (timeline event type 'birds': a flock of 1-7, see timeline.js).
// Each bird is a side-view silhouette (body, head, tail, swept wings) flapping at its own rate (3-7 Hz) with
// short glides, flying a straight, slightly climbing or sinking line with a little bob per wingbeat. Sizes
// are wingspans in px at 4K. Dark against the sky, hazed toward the air behind it by distance, hidden behind
// anything clearly nearer (plate depth) and outside the outdoor mask. 4 sub-samples per pixel (no shimmer).
// Depth (user 2026-10-19: birds vanished behind the poles): with dispPerPx each bird's plate disparity follows its
// size (a nearer bird looks bigger), so it is hidden crisply by exactly what is nearer than it: a 36 px bird
// passes in front of a far pole and into the alley's buildings where they come nearer than it. Calibrate it on
// the plate: a bird of wingspan s px is 2700 * 0.25 / s m away; a pole of known width gives the disparity of a
// known distance (ramen: a 25 px pole, ~0.3 m, at disparity 0.042 -> 0.002 per px).
//
// opts: { plate, dispPerPx (disparity per px of wingspan; else every bird at `disp`), dispMin (0: a floor, e.g.
//   in front of a far pole in the middle of the sky: birds there must not blink out in open air), dispMax (0.3),
//   disp: the birds' plate disparity without dispPerPx (0.03), haze (0.35), max (16) }
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { plateTexture } from './overlay.js';

const vert = /* glsl */ `
attribute vec4 aB;     // center x, y (px, y down), wingspan (px), wing tip height (fraction of the half span, signed)
attribute vec4 aB2;    // direction (+1 = right), visibility, bob (px), the bird's own plate disparity (0 = uDisp)
uniform vec2 uRes;
uniform float uCell;   // pixel art: the grid cell (px at 4K; 0 = off): the quad grows a cell so every touched cell is drawn
varying vec2 vP;       // bird frame: x forward, y up, in wingspans
varying vec4 vB, vB2;
varying vec2 vUv;
void main() {
  if (aB2.y <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  float s = aB.z;
  vec2 q = position.xy;
  vec2 px = aB.xy + q * (vec2(0.75, 0.75) * s + uCell) + vec2(0.0, aB2.z);
  vP = vec2(q.x * 0.75 * aB2.x, -q.y * 0.75);
  vB = aB; vB2 = aB2;
  vUv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

// Silhouette distance functions shared with perch.js (birds sitting on wires): bird() is the flying side view in
// wingspans, x forward, y up.
export const BIRD_SDF = /* glsl */ `
float ell(vec2 p, vec2 c, vec2 r) { return (length((p - c) / r) - 1.0) * min(r.x, r.y); }
float seg(vec2 p, vec2 a, vec2 b, float r) { vec2 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0); return length(pa - ba * h) - r; }
// Swept wing seen from the side: root chord at the shoulder, a narrower tip at height tip (wingspans).
float wing(vec2 p, float tip) {
  float y0 = 0.01, lo = min(y0, tip), hi = max(y0, tip);
  float v = clamp((p.y - y0) / (abs(tip - y0) < 1e-3 ? 1e-3 : tip - y0), 0.0, 1.0);
  float xl = mix(-0.11, -0.16, v), xr = mix(0.09, -0.03, v * v);
  return max(max(xl - p.x, p.x - xr), max(lo - p.y, p.y - hi));
}
float bird(vec2 p, float tip, float px) {
  float d = ell(p, vec2(0.0, 0.0), vec2(0.17, 0.045));
  d = min(d, ell(p, vec2(0.15, 0.02), vec2(0.05, 0.04)));
  d = min(d, seg(p, vec2(0.19, 0.022), vec2(0.235, 0.012), 0.008));
  d = min(d, ell(p, vec2(-0.2, -0.004), vec2(0.08, 0.022)));
  d = min(d, wing(p, tip));
  d = min(d, wing(p - vec2(0.015, 0.0), tip * 0.82));
  return smoothstep(0.6 * px, -0.6 * px, d);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights, tDepth, tBlur, tEnv, tMask;
uniform vec2 uRes, uOrigin;
uniform float uDisp, uHaze, uFlash, uCell;
varying vec2 vP;
varying vec4 vB, vB2;
varying vec2 vUv;
${BIRD_SDF}
void main() {
  float outdoor = texture2D(tLights, vUv).g;
  if (outdoor < 0.004) discard;
  // seen against the sky, or in front of far scenery; anything clearly nearer (buildings, poles) hides them
  float dp = texture2D(tDepth, vUv).r; dp *= dp;
  float sky = texture2D(tMask, vUv).r;
  // a bird with its own disparity (from its size) is hidden crisply by what is nearer than it; else the old
  // scene-wide soft threshold
  float front = vB2.w > 0.0 ? max(sky, 1.0 - smoothstep(vB2.w * 1.06 + 0.002, vB2.w * 1.14 + 0.004, dp))
                            : max(sky, 1.0 - smoothstep(uDisp * 1.2, uDisp * 1.6, dp));
  if (front <= 0.0) discard;
  float s = vB.z, px = 1.0 / s;
  float tip = vB.w * 0.5;
  float cov = 0.0;
  if (uCell > 0.0) {
    // pixel art shows each cell's center pixel: that pixel draws its whole cell's share of the bird, and a cell a fifth
    // covered or more is bird, crisp as a sprite (thin wings vanished between the centers, 2026-10-21)
    vec2 p = vec2(vUv.x * uRes.x, (1.0 - vUv.y) * uRes.y);
    vec2 c0 = uOrigin + floor((p - uOrigin) / uCell) * uCell;
    for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) {
      vec2 sp = c0 + (vec2(float(i), float(j)) + 0.5) * uCell * 0.25;
      cov += bird(vec2((sp.x - vB.x) / s * vB2.x, -(sp.y - vB.y - vB2.z) / s), tip, 0.25 * px);
    }
    cov = step(0.2, cov / 16.0);
  } else {
    for (int i = 0; i < 4; i++) {
      vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
      if (i == 1 || i == 3) o = o.yx;
      cov += bird(vP + o * px * vec2(vB2.x, -1.0), tip, px);
    }
    cov *= 0.25;
  }
  cov *= front * outdoor * vB2.y;
  if (cov <= 0.002) discard;
  vec3 env = texture2D(tEnv, vUv).rgb;
  vec3 air = texture2D(tBlur, vUv).rgb;
  vec3 b = vec3(0.05, 0.05, 0.06) * (env * 2.0 + vec3(0.02)) * (1.0 + 0.8 * uFlash);
  vec3 col = mix(b, air, uHaze);
  gl_FragColor = vec4(col * cov, cov);
}`;

// Bird state at time t inside its flock event: center (px), wingspan, wing tip height, bob, visibility. `scale` grows
// the birds and the flock's spacing together (pixel art: a bird under ~6 cells is a speck on the grid).
export function birdPose(ev, m, t, scale = 1) {
  const tau = t - ev.t, u = tau / ev.dur;
  const W = 3840, H = 2160;
  const x = (ev.dir > 0 ? ev.x0 * W - m.dx * scale : ev.x1 * W + m.dx * scale) + ev.dir * ev.speed * tau;
  const y = (ev.y + ev.climb * u) * H + (m.dy + m.wave * Math.sin(2 * Math.PI * (tau / m.waveT + m.phase))) * scale;
  // flap with short glides (wings held up a little); each bird its own rate and phase
  const g = Math.sin(2 * Math.PI * (tau / m.glideT + m.phase * 1.7));
  const glide = Math.min(Math.max((g - 0.55) / 0.3, 0), 1);
  const ph = 2 * Math.PI * (m.hz * tau + m.phase);
  const tip = (1 - glide) * (0.15 + 0.85 * Math.sin(ph)) + glide * 0.18;
  const bob = -(1 - glide) * 0.06 * m.span * scale * Math.sin(ph);
  const vis = Math.min(1, tau / 0.6, (ev.dur - tau) / 0.6);
  return { x, y, span: m.span * scale, tip, bob, vis: Math.max(0, vis) };
}

export async function birdsLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'birds');
  if (!evs.length) return null;
  const [tLights, tDepth8, tBlur, tEnv, tMask, tFine] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'depth8.png'),
    plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'env.png', { srgb: true }), plateTexture(opts.plate, 'masks.png'),
    plateTexture(opts.plate, 'depth_fine.png', { optional: true }),
  ]);
  // depth_fine (plate_prep): the depth model's halo around poles and wires put back to the sky's depth
  const tDepth = opts.dispPerPx && tFine.image?.width > 1 ? tFine : tDepth8;
  const dispOf = (span) => (opts.dispPerPx ? Math.min(opts.dispMax ?? 0.3, Math.max(opts.dispMin ?? 0, span * opts.dispPerPx)) : 0);
  const MAX = opts.max ?? 16;
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = MAX;
  const aB = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
  const aB2 = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
  aB.setUsage(THREE.DynamicDrawUsage);
  aB2.setUsage(THREE.DynamicDrawUsage);
  g.setAttribute('aB', aB);
  g.setAttribute('aB2', aB2);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    side: THREE.DoubleSide,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tDepth: { value: tDepth }, tBlur: { value: tBlur }, tEnv: { value: tEnv }, tMask: { value: tMask },
      uRes: { value: new THREE.Vector2(3840, 2160) }, uDisp: { value: opts.disp ?? 0.03 }, uHaze: { value: opts.haze ?? 0.35 }, uFlash: { value: 0 },
      uCell: { value: opts.pixelGrid?.cell ?? 0 }, uOrigin: { value: new THREE.Vector2(...(opts.pixelGrid?.origin ?? [0, 0])) },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 6;   // on the plate, under the rain
  mesh.userData.noAO = true;
  ctx.add(mesh);
  ctx.animate((t) => {
    let k = 0;
    for (const ev of evs) {
      if (t < ev.t || t > ev.t + ev.dur) continue;
      // opts.minSpan (pixel looks): the flock's smallest bird is drawn at least that wide, the rest and their spacing alike
      const sc = opts.minSpan ? Math.max(1, opts.minSpan / Math.min(...ev.members.map((m) => m.span))) : 1;
      for (const m of ev.members) {
        if (k >= MAX) break;
        const p = birdPose(ev, m, t, sc);
        aB.array.set([p.x, p.y, p.span, p.tip], k * 4);
        aB2.array.set([ev.dir, p.vis, p.bob, dispOf(p.span)], k * 4);
        k++;
      }
    }
    for (let i = k; i < MAX; i++) aB2.array[i * 4 + 1] = 0;
    aB.needsUpdate = aB2.needsUpdate = true;
    mesh.visible = k > 0;
    mat.uniforms.uFlash.value = flashAt(ctx.timeline, t).flash;
  });
  return mesh;
}
