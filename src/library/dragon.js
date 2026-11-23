// A dragon far off, gliding across the sky now and then (timeline event 'dragon'; Truman's ideas round on the Sleeping
// Hound Inn, 2026-11-15: in Skyrim dragons fly over at random, and it is the one thing that says Skyrim most). Silent.
//
// Its silhouette is built in code every frame, never generated: a 3D pose projected as seen from a little below (the
// camera looks up at it, `view` degrees under its wing plane), so the near wing hangs under the body and the far one
// shows above it; bat wings (an arm to the wrist, fingers fanning to the tip, the membrane's trailing edge scalloped
// between the finger tips) with a dihedral that beats in short bouts of slow, heavy flaps (0.38-0.5 Hz, the wings half
// folded on the upstroke) between long glides on raised wings; the body rising a little on each downstroke; an S-curved
// neck with a horned head; a long tail swaying in a slow wave that runs down it. Drawn dark against the sky, hazed by
// its distance toward the air behind it like the birds (birds.js), hidden behind anything nearer than it (the plate's
// depth, outdoors only), at the far ends of its way behind the porch's posts or off the frame.
//
// opts: { plate, disp (its plate disparity: hidden by what is nearer, 0.02), haze (0.35), view (deg, 22), dark (0.05),
//   renderOrder (6) }. Timeline `dragon`: { perHour, minGap, startAfter, first, dur: [s, s], span: [px, px],
//   band: [x0, y0, x1, y1] (where its way runs), from: [x, x] (the far ends, image x) }.
import * as THREE from 'three';
import { plateTexture } from './overlay.js';
import { mulberry32 } from '../engine/rng.js';
import { smooth } from './util.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;
const NCAP = 20, NPOLY = 12;

const vert = /* glsl */ `
uniform vec4 uQuad;      // x0, y0, x1, y1 (px)
varying vec2 vPx;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = mix(uQuad.xy, uQuad.zw, vec2(q.x, 1.0 - q.y));
  gl_Position = vec4(vPx.x / ${W}.0 * 2.0 - 1.0, 1.0 - vPx.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights, tDepth, tBlur, tEnv, tMask;
uniform vec4 uCap[${NCAP}];          // capsules: a (px), b (px)
uniform float uCapR[${NCAP}];        // their radii (px)
uniform vec2 uNear[${NPOLY}], uFar[${NPOLY}];   // the wings' outlines (px)
uniform float uVis, uDisp, uHaze, uDark;
varying vec2 vPx;
float seg(vec2 p, vec2 a, vec2 b, float r) { vec2 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0); return length(pa - ba * h) - r; }
// signed distance to a closed polygon (negative inside), by its edges and the crossing count
float poly(vec2 p, vec2 v[${NPOLY}]) {
  float d = dot(p - v[0], p - v[0]);
  float s = 1.0;
  for (int i = 0, j = ${NPOLY - 1}; i < ${NPOLY}; j = i, i++) {
    vec2 e = v[j] - v[i], w = p - v[i];
    vec2 b = w - e * clamp(dot(w, e) / max(dot(e, e), 1e-6), 0.0, 1.0);
    d = min(d, dot(b, b));
    bvec3 c = bvec3(p.y >= v[i].y, p.y < v[j].y, e.x * w.y > e.y * w.x);
    if (all(c) || all(not(c))) s = -s;
  }
  return s * sqrt(d);
}
float shape(vec2 p) {
  float d = min(poly(p, uNear), poly(p, uFar));
  for (int i = 0; i < ${NCAP}; i++) if (uCapR[i] > 0.0) d = min(d, seg(p, uCap[i].xy, uCap[i].zw, uCapR[i]));
  return d;
}
void main() {
  vec2 uv = vec2(vPx.x / ${W}.0, 1.0 - vPx.y / ${H}.0);
  float outdoor = texture2D(tLights, uv).g;
  if (outdoor < 0.004) discard;
  float dp = texture2D(tDepth, uv).r; dp *= dp;
  float sky = texture2D(tMask, uv).r;
  float front = max(sky, 1.0 - smoothstep(uDisp * 1.06 + 0.002, uDisp * 1.14 + 0.004, dp));
  if (front <= 0.0) discard;
  // 4 sub-samples per pixel: no shimmer on the thin horns and finger tips
  float cov = 0.0;
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    cov += smoothstep(0.5, -0.5, shape(vPx + o));
  }
  cov *= 0.25 * front * outdoor * uVis;
  if (cov <= 0.002) discard;
  vec3 env = texture2D(tEnv, uv).rgb;
  vec3 air = texture2D(tBlur, uv).rgb;
  vec3 col = mix(vec3(uDark) * (env * 2.0 + vec3(0.02)), air, uHaze);
  gl_FragColor = vec4(col * cov, cov);
}`;

// The flight plan of one pass: glides with bouts of 2-3 slow beats between them. Returns (tau) => { flap 0..1 (how
// much it is flapping), ph (the beat's phase, rad) }.
export function dragonWings(ev) {
  const r = mulberry32((ev.seed ?? 1) >>> 0);
  const bouts = [];
  let t = 0.5 + 2.5 * r();
  while (t < ev.dur) {
    const hz = 0.38 + 0.12 * r(), beats = 2 + Math.floor(2 * r());
    bouts.push([t, t + beats / hz, hz]);
    t += beats / hz + 5 + 6 * r();
  }
  return (tau) => {
    for (const [a, b, hz] of bouts) {
      if (tau < a - 0.6 || tau > b + 0.6) continue;
      const k = smooth((tau - (a - 0.6)) / 0.6) * (1 - smooth((tau - b) / 0.6));
      return { flap: k, ph: TAU * hz * (tau - a) };
    }
    return { flap: 0, ph: 0 };
  };
}

// Where it is tau s into its pass: center (px), its heading (+1 right), the size (wingspan px) and how much shows.
export function dragonAt(ev, tau) {
  const u = Math.min(1, Math.max(0, tau / ev.dur));
  const x = (ev.x0 + (ev.x1 - ev.x0) * u) * W;
  const y = (ev.y0 + (ev.y1 - ev.y0) * u - (ev.arc ?? 0) * 4 * u * (1 - u)) * H;
  return { x, y, dir: ev.x1 >= ev.x0 ? 1 : -1, span: ev.span, vis: Math.min(1, tau / 0.8, (ev.dur - tau) / 0.8) };
}

// The silhouette's parts in px for one frame: capsules [ax, ay, bx, by, r] and the two wings' outlines.
export function dragonShape(ev, tau, view = 22) {
  const { x, y, dir, span: S } = dragonAt(ev, tau);
  const { flap, ph } = dragonWings(ev)(tau);
  const ce = Math.cos((view * Math.PI) / 180), se = Math.sin((view * Math.PI) / 180);
  const beat = Math.sin(ph);
  // the wings' dihedral: raised a little in a glide, swinging +-38 deg in a beat; half folded going up
  const dih = ((8 + 2 * Math.sin(TAU * tau / 7.3)) * (1 - flap) + (6 + 38 * beat) * flap) * Math.PI / 180;
  const fold = 1 - 0.22 * flap * Math.max(0, Math.cos(ph));
  const bob = -0.025 * flap * Math.cos(ph);     // up a little on each downstroke
  // a point of the dragon (x forward, h up, z toward its far side; wingspans) -> image px
  const P = (bx, h, z) => [x + dir * bx * S, y - ((h + bob) * ce + z * se) * S];
  const caps = [];
  const cap = (a, b, r) => caps.push([...P(...a), ...P(...b), r * S]);
  // body and chest: a heavy beast, not a bird (stick-thin, it read as a pterosaur: first try)
  cap([-0.15, 0, 0], [0.1, 0.008, 0], 0.045);
  cap([0.0, 0.006, 0], [0.12, 0.016, 0], 0.055);
  // the neck's S-curve and the head, bobbing a little with the beat
  const nb = 0.008 * flap * Math.sin(ph - 0.8);
  cap([0.11, 0.016, 0], [0.19, 0.038 + nb, 0], 0.032);
  cap([0.19, 0.038 + nb, 0], [0.25, 0.05 + nb, 0], 0.023);
  cap([0.25, 0.05 + nb, 0], [0.29, 0.054 + nb, 0], 0.019);
  cap([0.29, 0.056 + nb, 0], [0.34, 0.05 + nb, 0], 0.019);
  cap([0.34, 0.05 + nb, 0], [0.375, 0.042 + nb, 0], 0.011);
  cap([0.3, 0.068 + nb, 0], [0.255, 0.1 + nb, 0], 0.006);       // horns, swept back
  cap([0.31, 0.066 + nb, 0.01], [0.27, 0.095 + nb, 0.01], 0.0055);
  // legs tucked under
  cap([-0.06, -0.03, 0], [-0.13, -0.05, 0], 0.017);
  cap([0.06, -0.025, 0], [0.1, -0.042, 0], 0.012);
  // the tail: a slow wave runs down it
  let prev = [-0.14, 0, 0];
  for (let i = 1; i <= 7; i++) {
    const k = i / 7, tx = -0.14 - 0.43 * k;
    const ty = -0.02 * k + 0.03 * k * Math.sin(TAU * (tau / 3.4 - 0.9 * k)) + 0.01 * flap * Math.sin(ph - 2 * k);
    const pt = [tx, ty, 0];
    cap(prev, pt, 0.038 * (1 - 0.84 * k));
    prev = pt;
  }
  cap(prev, [prev[0] - 0.04, prev[1] - 0.005, 0], 0.014);         // the spade at its end
  while (caps.length < NCAP) caps.push([0, 0, 0, 0, 0]);
  // a wing in its own plane (u along the span, 0 shoulder .. 1 tip; v along the body, + forward), then turned up by the
  // dihedral and seen from below: the leading edge to the wrist and the finger tips, the scalloped trailing edge back
  const L = 0.5 * fold;
  const outline = [[0, 0.05], [0.25, 0.075], [0.47, 0.085], [0.74, 0.03], [1, -0.05], [0.88, -0.11], [0.78, -0.2], [0.64, -0.17],
    [0.52, -0.27], [0.36, -0.2], [0.2, -0.24], [0, -0.13]];
  const wing = (side) => outline.map(([u, v]) => {
    const r = u * L, vv = v * (0.85 + 0.15 * fold);
    // the membrane's far part lags the arm a little in a beat (it bends): its tip goes higher on the upstroke
    const d = dih + 0.12 * flap * Math.sin(ph - 0.6) * u * u;
    return P(0.04 + vv - 0.04 * u, 0.012 + r * Math.sin(d), side * r * Math.cos(d));
  });
  return { caps, near: wing(-1), far: wing(1), x, y, S };
}

export async function dragonLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'dragon');
  if (!evs.length) return null;
  const [tLights, tDepth, tBlur, tEnv, tMask] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'depth8.png'),
    plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'env.png', { srgb: true }), plateTexture(opts.plate, 'masks.png'),
  ]);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tDepth: { value: tDepth }, tBlur: { value: tBlur }, tEnv: { value: tEnv }, tMask: { value: tMask },
      uCap: { value: Array.from({ length: NCAP }, () => new THREE.Vector4()) }, uCapR: { value: new Array(NCAP).fill(0) },
      uNear: { value: Array.from({ length: NPOLY }, () => new THREE.Vector2()) }, uFar: { value: Array.from({ length: NPOLY }, () => new THREE.Vector2()) },
      uQuad: { value: new THREE.Vector4() }, uVis: { value: 0 }, uDisp: { value: opts.disp ?? 0.02 }, uHaze: { value: opts.haze ?? 0.35 },
      uDark: { value: opts.dark ?? 0.05 },
    },
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 6;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  ctx.animate((t) => {
    const ev = evs.find((e) => t >= e.t && t <= e.t + e.dur);
    mesh.visible = !!ev;
    if (!ev) return;
    const tau = t - ev.t;
    const s = dragonShape(ev, tau, opts.view ?? 22);
    const u = mat.uniforms;
    s.caps.forEach((c, i) => { u.uCap.value[i].set(c[0], c[1], c[2], c[3]); u.uCapR.value[i] = c[4]; });
    s.near.forEach((p, i) => u.uNear.value[i].set(p[0], p[1]));
    s.far.forEach((p, i) => u.uFar.value[i].set(p[0], p[1]));
    u.uQuad.value.set(s.x - 0.75 * s.S, s.y - 0.6 * s.S, s.x + 0.75 * s.S, s.y + 0.6 * s.S);
    u.uVis.value = dragonAt(ev, tau).vis;
  });
  return mesh;
}
