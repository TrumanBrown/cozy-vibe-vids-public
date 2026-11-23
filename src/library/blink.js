// Blinks for the channel's awake cast (Truman 2026-10-25: the characters may be awake doing something quiet, "with
// breathing and blinks drawn in code"; nothing generated). tools/cast_eyes.py paints each eye closed, with skin
// cloned from beside it and a thin lid line, into out/plates/<plate>/eyes_closed.png, and eyes_id.png says which
// character each patch belongs to; this layer fades a character's patches in for a blink now and then. Each
// character keeps its own seeded rhythm (a blink every 2.5 to 7 s, now and then two in a row), laid out in slots that
// divide the loop period exactly, so the 20 minute window repeats without a cut blink at the join. The heads are the
// pet regions' still parts (they never move with the breathing), so the patches stay on the eyes.
import * as THREE from 'three';
import { fetchJson, plateTexture, PREMUL } from './overlay.js';
import { hash } from './util.js';

const vert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const frag = /* glsl */ `
uniform sampler2D tClosed;
uniform sampler2D tId;
uniform float uK[8];
varying vec2 vUv;
void main() {
  vec4 c = texture2D(tClosed, vUv);
  if (c.a < 0.002) discard;
  int k = int(floor(texture2D(tId, vUv).r * 8.0 + 0.5)) - 1;
  float b = 0.0;
  for (int i = 0; i < 8; i++) if (i == k) b = uK[i];
  float a = c.a * b;
  if (a < 0.002) discard;
  gl_FragColor = vec4(c.rgb * a, a);
}`;

// one blink's lid: down in 0.07 s, held 0.05 s, up in 0.11 s
const lid = (u) => (u < 0 || u > 0.23 ? 0 : u < 0.07 ? u / 0.07 : u < 0.12 ? 1 : 1 - (u - 0.12) / 0.11);

export async function blinkLayer(ctx, opts) {
  // the layer is in scene.json only when the cast has eyes to blink (autopilot's setup adds it after cast_eyes.py)
  const meta = await fetchJson(`/out/plates/${opts.plate}/eyes.json`, { hint: 'run tools/cast_eyes.py <scene>, or take the blink layer out of scene.json' });
  const pets = (meta.pets ?? []).filter((p) => p.eyes?.length);
  if (!pets.length) {
    console.log('blink: eyes.json lists no open eyes (tools/cast_eyes.py found none); no blinks');
    return null;
  }
  const [tClosed, tId] = await Promise.all([plateTexture(opts.plate, 'eyes_closed.png', { srgb: true }), plateTexture(opts.plate, 'eyes_id.png', { nearest: true })]);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: { tClosed: { value: tClosed }, tId: { value: tId }, uK: { value: new Array(8).fill(0) } },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 1;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const period = opts.period ?? ctx.timeline?.loop?.period ?? ctx.loopSeconds ?? 120;
  const [lo, hi] = opts.every ?? [2.5, 7];
  const seed = (opts.seed ?? 7) * 7919;
  // each character's slots: the period divided into whole slots of about the mean gap; one blink per slot at a
  // seeded time, sometimes a second right after, sometimes none
  const rhythm = pets.map((p) => {
    const n = Math.max(1, Math.round(period / ((lo + hi) / 2) * (0.9 + 0.2 * hash(seed, p.index))));
    return { index: p.index, n, slot: period / n };
  });
  console.log(`blink: ${pets.length} characters, ${pets.reduce((s, p) => s + p.eyes.length, 0)} eyes, a blink every ~${((lo + hi) / 2).toFixed(1)} s each`);
  ctx.animate((t) => {
    const k = mat.uniforms.uK.value;
    k.fill(0);
    const tt = ((t % period) + period) % period;
    let any = false;
    for (const r of rhythm) {
      const j = Math.floor(tt / r.slot);
      let v = 0;
      for (const jj of [j - 1, j]) {
        const s = ((jj % r.n) + r.n) % r.n;
        const base = jj * r.slot;
        if (hash(seed + r.index * 131, s * 2 + 1) < 0.1) continue;          // a slot without a blink
        const at = base + 0.15 * r.slot + 0.6 * r.slot * hash(seed + r.index * 131, s * 2);
        v = Math.max(v, lid(tt - at));
        if (hash(seed + r.index * 977, s) < 0.15) v = Math.max(v, lid(tt - at - 0.32));   // now and then twice
      }
      if (r.index < 8) k[r.index] = v;
      any = any || v > 0;
    }
    mesh.visible = any;
  });
  return mesh;
}
