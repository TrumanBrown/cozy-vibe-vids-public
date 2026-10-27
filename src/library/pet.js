// The pet's behaviors (timeline event type 'petact'): short clips of the pet generated from the plate itself
// (tools/pet_clips.py: a local image-to-video model on a crop around the pet, matted and color-matched to the
// plate) played as a motion graph. Every act starts at the plate's own pose: it plays a clip forward to a rest
// frame (head up and looking around; sitting up), holds there breathing, and plays the same frames backward to
// the plate's pose again, so every join is exact. Clip frames are blended (24 -> 30 fps) and crossfade in and
// out over 0.3 s. Drawn over the rain (the pet is nearer than any of it); loaded per frame (ctx.prefetch).
//
// RETIRED (user 2026-10-18, docs/DECISIONS.md): generated clips of a painted pet look eerie and obviously AI.
// A painted pet only breathes (plate.js); a pet that moves must be a 3D model or library asset animated in code.
// Kept only until the ramen alley's acts are removed; a scene that uses this layer gets a warning.
//
// out/plates/<plate>/pet/pet.json: { fps, clips: { <clip>: { frames, box: [x, y, w, h] px at 4K, dir,
//   hold_bbox: [x0, y0, x1, y1] px (the pet at its rest frame) } }, acts: [{ name, clip, to: rest frame,
//   hold: [s0, s1], weight }] }
import * as THREE from 'three';
import { PREMUL } from './overlay.js';

const vert = /* glsl */ `
uniform vec4 uBox;        // x, y, w, h (px at 4K)
varying vec2 vT;          // texture coords in the clip frame (0..1, y down)
varying vec2 vPx;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vPx = uBox.xy + vT * uBox.zw;
  vec2 uv = vec2(vPx.x / 3840.0, 1.0 - vPx.y / 2160.0);
  gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tA, tB;
uniform float uMix, uAlpha;
uniform vec4 uBox;
uniform vec4 uBreath;     // pet ellipse center x, y (px), radius x, y (px)
uniform vec2 uBreathK;    // base row (px), stretch amount now
varying vec2 vT;
varying vec2 vPx;
void main() {
  vec2 t = vT;
  if (uBreathK.y != 0.0) {
    vec2 d = (vPx - uBreath.xy) / uBreath.zw;
    float m = 1.0 - smoothstep(0.55, 1.0, length(d));
    float dy = (vPx.y - uBreathK.x) * uBreathK.y * m;     // stretch upward from the base
    t.y -= dy / uBox.w;
  }
  vec4 a = texture2D(tA, t), b = texture2D(tB, t);
  vec4 c = mix(a, b, uMix);
  float al = c.a * uAlpha;
  if (al < 0.002) discard;
  gl_FragColor = vec4(c.rgb * al, al);
}`;

export async function petLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'petact');
  const base = `/out/plates/${opts.plate}/pet`;
  const meta = await fetch(`${base}/pet.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!meta || !evs.length) return null;
  console.warn('pet: this scene plays generated clips of its painted pet, retired 2026-10-18 (docs/DECISIONS.md): a painted pet '
    + 'only breathes. Remove the pet layer and events.petAct from scene.json when its renders are next changed.');
  const fps = meta.fps ?? 24;
  const acts = Object.fromEntries((meta.acts ?? []).map((a) => [a.name, a]));
  const mkTex = () => {
    const t = new THREE.Texture();
    t.colorSpace = THREE.SRGBColorSpace;
    t.flipY = false;
    t.premultiplyAlpha = false;
    t.generateMipmaps = false;
    t.minFilter = t.magFilter = THREE.LinearFilter;
    return t;
  };
  // One texture pair per clip: clips differ in size, and three.js allocates a texture's storage once (at its
  // first image's size), so reusing one texture for a bigger clip leaves the old frame stretched over the box.
  const texOf = new Map();
  const texFor = (clip) => {
    if (!texOf.has(clip)) texOf.set(clip, { a: mkTex(), b: mkTex(), shownA: null, shownB: null });
    return texOf.get(clip);
  };
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      tA: { value: null }, tB: { value: null }, uMix: { value: 0 }, uAlpha: { value: 0 }, uBox: { value: new THREE.Vector4() },
      uBreath: { value: new THREE.Vector4(0, 0, 1, 1) }, uBreathK: { value: new THREE.Vector2() },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 30;
  mesh.userData.noAO = true;
  mesh.visible = false;
  ctx.add(mesh);

  // What an act shows at tau seconds: clip frame index (float) and crossfade weight.
  const state = (t) => {
    const ev = evs.find((e) => t >= e.t && t < e.t + e.dur);
    if (!ev) return null;
    const act = acts[ev.act];
    const clip = act && meta.clips[act.clip];
    if (!clip) return null;
    const Tin = act.to / fps, tau = t - ev.t;
    let idx, hold = false;
    if (tau < Tin) idx = tau * fps;
    else if (tau < Tin + ev.hold) {
      // held at the rest pose; with `idle` frames it drifts slowly into the near-still frames just after it and
      // back (small head and ear movements), always leaving and returning at the rest frame
      hold = true;
      const th = tau - Tin, k = Math.min(act.idle ?? 0, clip.frames - 1 - act.to);
      const per = act.idlePeriod ?? 7;
      idx = act.to + (k > 0 ? k * 0.5 * (1 - Math.cos(2 * Math.PI * th / per)) * Math.min(1, th / 2, (ev.hold - th) / 2) : 0);
    } else idx = Math.max(0, act.to - (tau - Tin - ev.hold) * fps);
    const fade = Math.min(1, tau / 0.3, (ev.dur - tau) / 0.3);
    return { ev, act, clip, idx, hold, fade: Math.max(0, fade), tau, Tin };
  };
  const cache = new Map();
  const order = [];
  const url = (clip, i) => `${base}/${clip.dir ?? ''}/a_${String(i).padStart(4, '0')}.png`.replace('//a_', '/a_');
  const load = async (clip, i) => {
    const key = url(clip, i);
    if (cache.has(key)) return cache.get(key);
    const p = fetch(key).then((r) => { if (!r.ok) throw new Error(`${key}: HTTP ${r.status}`); return r.blob(); }).then((b) => createImageBitmap(b, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' }));
    cache.set(key, p);
    order.push(key);
    while (order.length > 24) {
      const k = order.shift();
      const old = cache.get(k);
      cache.delete(k);
      old?.then((bm) => bm.close?.());
    }
    return p;
  };
  let cur = null;
  ctx.prefetch(async (t) => {
    const s = state(t);
    if (!s) { cur = null; return; }
    const i0 = Math.floor(s.idx), i1 = Math.min(i0 + 1, s.clip.frames - 1);
    const [a, b] = await Promise.all([load(s.clip, i0), load(s.clip, i1)]);
    cur = { s, a, b, i0, mix: s.idx - i0 };
  });
  ctx.animate((t) => {
    const s = cur && Math.abs(cur.s.ev.t + cur.s.tau - t) < 1e-6 ? cur : null;
    mesh.visible = !!s;
    if (!s) return;
    const tx = texFor(s.s.act.clip);
    if (tx.shownA !== s.a) { tx.a.image = s.a; tx.a.needsUpdate = true; tx.shownA = s.a; }
    if (tx.shownB !== s.b) { tx.b.image = s.b; tx.b.needsUpdate = true; tx.shownB = s.b; }
    const u = mat.uniforms;
    u.tA.value = tx.a;
    u.tB.value = tx.b;
    u.uBox.value.set(...s.s.clip.box);
    u.uMix.value = s.mix;
    u.uAlpha.value = s.s.fade;
    // breathing while it rests at the hold frame (eases in and out with the hold)
    const hb = s.s.clip.hold_bbox;
    if (s.s.hold && hb) {
      const th = s.s.tau - s.s.Tin;
      const env = Math.min(1, th / 1.0, (s.s.ev.hold - th) / 1.0);
      const hpx = hb[3] - hb[1];
      const amp = 0.03 * Math.min(1, Math.max(0.3, 200 / hpx));
      u.uBreath.value.set((hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2, (hb[2] - hb[0]) * 0.5, (hb[3] - hb[1]) * 0.55);
      u.uBreathK.value.set(hb[3], amp * Math.max(0, env) * (0.5 + 0.5 * Math.sin(2 * Math.PI * th / 3.4)));
    } else u.uBreathK.value.set(0, 0);
  });
  return mesh;
}
