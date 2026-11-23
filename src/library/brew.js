// Bubbles rising in a brewing stand's bottles (Truman 2026-11-22, the Enchanter's Tower: the brewing stand bubbling, a
// small mover he picked for the room). Small round bubbles rise through each bottle's potion from near its bottom,
// wobbling a little and growing a touch as they rise, and burst at the potion's surface with a tiny ring and a glint.
// Each is a clear sphere seen in the potion: a light rim where it catches the room's light (a dark rim vanished into the
// dark potion), the potion a little brighter through its middle, and a highlight on the side the light comes from. They
// are drawn bigger than life (6 to 10 px in a bottle 45 px wide: real ones would be a pixel and read as nothing). They
// never leave the bottle's body (an ellipse) and never rise above the potion. A pure function of time with whole cycles
// per loop: the 20 minute window joins.
//
// opts: { plate, bottles: [{ c: [x, y] (px at 4K: the body's middle), r: [rx, ry] (px), top (px: the potion's
//   surface), n (bubbles at a time, 5) }], size: [min, max] (px across, [6, 10]), speed (px/s, 18), light ([x, y]: the
//   direction the light comes from on screen, [0.6, -0.8]), renderOrder (9) }
import * as THREE from 'three';
import { plateTexture, instancedQuad, PREMUL } from './overlay.js';
import { mulberry32 } from '../engine/rng.js';

const W = 3840, H = 2160;

const vert = /* glsl */ `
attribute vec4 aB;      // the bottle: cx, cy, rx, ry (px)
attribute vec4 aP;      // top (px), period (s), phase (0..1), seed
attribute vec4 aQ;      // size (px), speed (px/s), wobble (px), wobble rate (Hz)
uniform float uTime, uLoop;
varying vec2 vQ;        // -1..1 across the quad
varying float vA, vPop, vR;
varying vec2 vUv, vC;
varying vec4 vB;
float h(float k, float s) { return fract(sin(k * 127.1 + s * 311.7) * 43758.5453); }
void main() {
  float per = aP.y, n = floor(uLoop / per + 0.5);
  float tt = uTime + aP.z * per;
  float k = mod(floor(tt / per), n);                  // which bubble of the slot (periodic in the loop)
  float tc = tt - floor(tt / per) * per;              // its time since it was born
  float sz = aQ.x * (0.8 + 0.4 * h(k, aP.w + 3.0));
  float bot = aB.y + 0.72 * aB.w;                     // born near the bottom of the round body
  float rise = max(0.3, (bot - aP.x - sz * 0.5) / aQ.y);
  float u = clamp(tc / rise, 0.0, 1.0);
  float y = bot - (bot - aP.x - sz * 0.5) * u;
  float half_w = aB.z * sqrt(max(0.0, 1.0 - pow((y - aB.y) / aB.w, 2.0)));
  float x0 = aB.x + aB.z * 0.55 * (2.0 * h(k, aP.w) - 1.0);
  float x = x0 + aQ.z * sin(6.2832 * aQ.w * tc + 6.2832 * h(k, aP.w + 7.0));
  x = clamp(x, aB.x - 0.8 * half_w, aB.x + 0.8 * half_w);
  float r = 0.5 * sz * (0.85 + 0.3 * u);
  float pop = clamp((tc - rise) / 0.16, 0.0, 1.0);    // bursting at the surface
  float alive = tc < rise + 0.16 ? 1.0 : 0.0;
  vA = alive * smoothstep(0.0, 0.25, tc);
  vPop = tc > rise ? pop : -1.0;
  vR = r;
  vec2 q = position.xy;
  float ext = r * (vPop >= 0.0 ? 2.4 : 1.6);
  vec2 p = vec2(x, y) + q * ext;
  vQ = q * ext / r;
  vC = vec2(x, y);
  vB = aB;
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vA > 0.0 ? vec4(vUv * 2.0 - 1.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tPlate;
uniform vec2 uLight;
varying vec2 vQ;
varying float vA, vPop, vR;
varying vec2 vUv, vC;
varying vec4 vB;
void main() {
  vec2 px = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
  vec2 e = (px - vB.xy) / vB.zw;
  if (dot(e, e) > 1.0) discard;                       // only inside the bottle's round body
  vec3 pot = texture2D(tPlate, vUv).rgb;
  float d = length(vQ);
  float aa = 1.2 / max(vR, 1.0);
  if (vPop >= 0.0) {
    // the burst: a thin ring spreading on the surface and a glint, gone in 0.16 s
    float rr = 1.0 + 1.3 * vPop;
    float ring = (1.0 - smoothstep(0.0, 0.22 + aa, abs(d - rr))) * (1.0 - vPop);
    float a = ring * 0.55 * vA;
    if (a < 0.003) discard;
    gl_FragColor = vec4(mix(pot, vec3(1.0, 0.97, 0.9), 0.6) * a, a);
    return;
  }
  if (d > 1.0 + aa) discard;
  // a bubble in a colored potion: a light rim where its surface catches the room's light, the potion a little brighter
  // through it, and a highlight on the side the light comes from (dark rims vanished into the dark potion)
  float inside = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, d);
  float rim = smoothstep(0.5, 0.92, d) * inside;
  float spec = exp(-dot(vQ - uLight * 0.4, vQ - uLight * 0.4) * 14.0);
  vec3 lit = vec3(1.0, 0.97, 0.9);
  vec3 col = mix(pot * 1.15, mix(pot, lit, 0.65), rim) + lit * spec;
  float a = vA * (0.15 * inside + 0.55 * rim + 0.75 * spec);
  if (a < 0.003) discard;
  gl_FragColor = vec4(col * a, a);
}`;

export async function brewLayer(ctx, opts) {
  const bottles = opts.bottles ?? [];
  if (!bottles.length) return null;
  const P = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const r = mulberry32(((ctx.seed ?? 1) * 4099 + 17) >>> 0);
  const rows = [];
  const [s0, s1] = opts.size ?? [6, 10];
  for (const b of bottles) {
    for (let i = 0; i < (b.n ?? 5); i++) {
      const size = s0 + (s1 - s0) * r(), speed = (opts.speed ?? 18) * (0.75 + 0.5 * r());
      const rise = (b.c[1] + 0.72 * b.r[1] - b.top) / speed;
      // a whole number of bubbles per loop, each slot resting a while after its bubble bursts
      const per = P / Math.max(1, Math.round(P / (rise + 0.6 + 2.2 * r())));
      rows.push([[b.c[0], b.c[1], b.r[0], b.r[1]], [b.top, per, r(), Math.floor(r() * 997)], [size, speed, 0.6 + 1.2 * r(), 0.8 + 1.2 * r()]]);
    }
  }
  const g = instancedQuad(rows.length);
  ['aB', 'aP', 'aQ'].forEach((name, k) => g.setAttribute(name, new THREE.InstancedBufferAttribute(new Float32Array(rows.flatMap((x) => x[k])), 4)));
  const tPlate = await plateTexture(opts.plate, 'plate.png', { srgb: true });
  const [lx, ly] = opts.light ?? [0.6, -0.8];
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: { uTime: { value: 0 }, uLoop: { value: P }, tPlate: { value: tPlate }, uLight: { value: new THREE.Vector2(lx, ly).normalize() } },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 9;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  ctx.animate((t) => { mat.uniforms.uTime.value = ((t % P) + P) % P; });
  return mesh;
}
