// A pet that really moves, from a free rigged 3D model (user 2026-10-21, after six rounds of sprite poses that each came
// out a somewhat different dog, asked for a fix at the root, such as an existing free model). One model is the same dog
// in every frame by construction. It replaces the painted pet: the plate shows the
// empty bed (pet_sprite.py's `empty` patch) and the painted pet never breathes under it (ctx.petHold).
//
// Rendered like cat3d.js, into its own texture every frame, but through the room's own camera in true perspective (a
// pinhole fitted to the painted floor, rendering only a window around the dog, one texel per screen pixel), lit by the
// plate's light where it stands, composited with a contact shadow and snapped to the art's grid by the engine's output
// pass. For pixel art: colors mapped onto a palette (the painted pet's own, so it has the picture's colors), fur shading
// fixed to the body, a dark edge one cell thick inside the silhouette and inner lines where a nearer part overlaps.
//
// opts: { plate, model (url of a .glb), empty: { url, x, y, w, h } (the empty bed patch, 4K px), colors: { <material>:
//   hex }, palette: [hex...], edge (hex), cell (px at 4K: the edge's thickness), inner: { color, depth } | false, fur:
//   { cells, amp }, aim, bones (breed changes on the rig, below), key: { dir, color, intensity }, fill, ambient
//   (hemisphere gain), shadow (0.4), occlude (true: hidden behind anything nearer than the floor where it stands),
//   floor: { row, height (its head-top px with its feet at that row), horizon (the floor's vanishing row), focal },
//   start (scene s the program starts), program: [{ do: 'idle', clip, dur, at: [x, y] (image coords of the floor point
//   under it, the first step), heading (deg: 0 faces the camera, 90 screen right, 180 away), speed, from } |
//   { do: 'turn', to (deg), dur } | { do: 'walk', path: [[x, y], ...], rate, radius }], turnRadius, lock, renderOrder }
// A walk's headings follow the path on the floor and its paws are pinned where they land (lock: false turns that off);
// a walk that leads off more than 40 deg from where the dog faces starts on an arc (radius, units); each step
// crossfades 0.3 s from the one before, and walks start and stop where the legs stand most like standing.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { plateTexture, imagePixels, boxMean, dirLight, PREMUL } from './overlay.js';

const W = 3840, H = 2160;

const quadVert = /* glsl */ `
uniform vec4 uBox;        // x, y (top left, px at 4K, y down), w, h
varying vec2 vT;          // 0..1 across the box, y down
varying vec2 vUv;         // plate uv (y up)
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
const OCCLUDE = /* glsl */ `
uniform float uOcclude;
float frontOf(vec2 uv) {
  if (uOcclude < 0.5) return 1.0;
  float d0 = texture2D(tDepth, uFootUv).r, d = texture2D(tDepth, uv).r;
  return 1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, d);
}`;
const dogFrag = /* glsl */ `
uniform sampler2D tDog, tDepth, tZ;
uniform vec2 uFootUv, uTexel;
uniform float uCell, uZEdge;
uniform vec3 uEdge, uInner;
uniform vec3 uPal[32];
uniform int uPalN;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
vec3 toS(vec3 c) { return pow(max(c, vec3(0.0)), vec3(1.0 / 2.2)); }
void main() {
  vec2 st = vec2(vT.x, 1.0 - vT.y);
  vec4 c = texture2D(tDog, st);
  if (c.a < 0.5) discard;
  float f = frontOf(vUv);
  if (f <= 0.0) discard;
  vec3 col = c.rgb / c.a;
  // the edge: within one cell of the outside; an inner line: within one cell of a nearer part (the head over the
  // chest, the near leg over the far one), as pixel art separates the parts (tZ: 1 - depth, nearer is larger)
  float edge = 0.0, inner = 0.0, z = texture2D(tZ, st).r;
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.785398;
    vec2 o = st + vec2(cos(a), sin(a)) * uCell * uTexel;
    float oa = texture2D(tDog, o).a;
    edge = max(edge, step(oa, 0.5));
    inner = max(inner, step(0.5, oa) * step(uZEdge, texture2D(tZ, o).r - z));
  }
  if (edge > 0.5) {
    col = uEdge;
  } else if (inner > 0.5 && uZEdge > 0.0) {
    col = uInner;
  } else if (uPalN > 0) {
    vec3 s = toS(col);
    float best = 1e9;
    vec3 pick = col;
    for (int i = 0; i < 32; i++) {
      if (i >= uPalN) break;
      vec3 d = toS(uPal[i]) - s;
      float e = dot(d, d * vec3(0.30, 0.59, 0.11));
      if (e < best) { best = e; pick = uPal[i]; }
    }
    col = pick;
  }
  gl_FragColor = vec4(col * f, f);
}`;
const shadowFrag = /* glsl */ `
uniform sampler2D tDepth;
uniform vec2 uFootUv;
uniform float uShadow;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
void main() {
  vec2 q = vT * 2.0 - 1.0;
  float r2 = dot(q, q);
  float k = exp(-r2 * 2.4) * (1.0 - smoothstep(0.8, 1.0, r2)) * uShadow * frontOf(vUv);
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;
const patchFrag = /* glsl */ `
uniform sampler2D tPatch;
varying vec2 vT;
void main() {
  vec4 c = texture2D(tPatch, vec2(vT.x, 1.0 - vT.y));
  if (c.a < 0.5) discard;
  gl_FragColor = vec4(c.rgb, 1.0);
}`;

const linHex = (h) => new THREE.Color(h);   // sRGB hex -> the working (linear) space

export async function dog3dLayer(ctx, opts) {
  const R = ctx.renderer;
  if (!R || !opts.program?.length) return null;
  const gltf = await new GLTFLoader().loadAsync(opts.model);
  const root = new THREE.Group();
  root.add(gltf.scene);
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    // fur: shades fixed to the body (the bind-pose position, so they move with it and never swim), about a pixel-art
    // cell each at the size it is drawn (opts.fur: { cells: noise cells over its height, amp })
    o.geometry.computeBoundingBox();
    const gb = o.geometry.boundingBox, gh = Math.max(gb.max.x - gb.min.x, gb.max.y - gb.min.y, gb.max.z - gb.min.z);
    const one = (m) => {
      const n = new THREE.MeshStandardMaterial({ color: opts.colors?.[m.name] ? linHex(opts.colors[m.name]) : m.color.clone(),
        roughness: 1, metalness: 0, flatShading: opts.flat ?? false });
      n.name = m.name;
      const fur = opts.fur;
      if (fur && !/eye|black/i.test(m.name)) {
        n.onBeforeCompile = (sh) => {
          sh.uniforms.uFurK = { value: (fur.cells ?? 60) / gh };
          sh.uniforms.uFurA = { value: fur.amp ?? 0.22 };
          sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vRest;')
            .replace('#include <begin_vertex>', '#include <begin_vertex>\nvRest = position;');
          sh.fragmentShader = sh.fragmentShader.replace('#include <common>', `#include <common>
varying vec3 vRest;
uniform float uFurK, uFurA;
float furHash(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
float furNoise(vec3 p) {
  vec3 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n = 0.0;
  for (int k = 0; k < 8; k++) {
    vec3 o = vec3(float(k & 1), float((k >> 1) & 1), float((k >> 2) & 1));
    vec3 w = mix(1.0 - f, f, o);
    n += furHash(i + o) * w.x * w.y * w.z;
  }
  return n;
}`).replace('#include <color_fragment>', `#include <color_fragment>
  // strands: stretched along the body's length, a fine grain over a coarse one
  vec3 q = vRest * uFurK * vec3(1.0, 1.0, 0.45);
  float fn = 0.6 * furNoise(q) + 0.4 * furHash(floor(q * 1.7));
  diffuseColor.rgb *= 1.0 + uFurA * (fn - 0.5) * 2.0;`);
        };
      }
      return n;
    };
    o.material = Array.isArray(o.material) ? o.material.map(one) : one(o.material);
  });
  // the clips are evaluated directly every frame (no AnimationMixer: its state carries from frame to frame, and a render
  // must give the same frame for the same time); two clips blend for a crossfade
  const clips = Object.fromEntries(gltf.animations.map((a) => [a.name, a]));
  const rest = [];
  gltf.scene.traverse((o) => rest.push({ o, p: o.position.clone(), q: o.quaternion.clone(), s: o.scale.clone() }));
  const restOf = new Map(rest.map((r) => [r.o, r]));
  const tracks = {};
  const trackOf = (name) => {
    if (tracks[name]) return tracks[name];
    if (!clips[name]) throw new Error(`dog3d: no clip ${name} (${Object.keys(clips).join(', ')})`);
    return (tracks[name] = clips[name].tracks.map((tr) => {
      const pb = THREE.PropertyBinding.parseTrackName(tr.name);
      const o = THREE.PropertyBinding.findNode(gltf.scene, pb.nodeName);
      return o && ['quaternion', 'position', 'scale'].includes(pb.propertyName) ? { o, prop: pb.propertyName, it: tr.createInterpolant() } : null;
    }).filter(Boolean));
  };
  let fixes = [], scales = [];
  const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), va = new THREE.Vector3(), vb = new THREE.Vector3();
  // list: [{ clip, time, w }] (one, or two with the second's weight w)
  const evalPose = (list, extras = true) => {
    for (const r of rest) { r.o.position.copy(r.p); r.o.quaternion.copy(r.q); r.o.scale.copy(r.s); }
    const touched = new Map();
    list.forEach((e, k) => {
      const d = clips[e.clip].duration, tt = ((e.time % d) + d) % d;
      for (const tr of trackOf(e.clip)) {
        const key = `${tr.o.id}:${tr.prop}`;
        let m = touched.get(key);
        if (!m) touched.set(key, (m = { o: tr.o, prop: tr.prop, v: [] }));
        m.v[k] = Array.from(tr.it.evaluate(tt));
      }
    });
    for (const m of touched.values()) {
      const r = restOf.get(m.o);
      const base = (m.prop === 'quaternion' ? r.q : m.prop === 'position' ? r.p : r.s).toArray();
      const a = m.v[0] ?? base;
      if (list.length < 2) { m.o[m.prop].fromArray(a); continue; }
      const b = m.v[1] ?? base, w = list[1].w;
      if (m.prop === 'quaternion') m.o.quaternion.copy(qa.fromArray(a).slerp(qb.fromArray(b), w));
      else m.o[m.prop].copy(va.fromArray(a).lerp(vb.fromArray(b), w));
    }
    if (!extras) return;
    for (const f of fixes) f.b.quaternion.premultiply(f.fix);
    for (const { b, s } of scales) b.scale.set(...s);
  };
  // which way the model faces (head minus tail, on the floor) and how tall it stands, in the first clip's first frame
  evalPose([{ clip: opts.program.find((s) => s.clip)?.clip ?? 'Idle', time: 0, w: 1 }], false);
  gltf.scene.updateMatrixWorld(true);
  // GLTFLoader drops the dots from node names (Ear1.L -> Ear1L)
  const obj = (n) => gltf.scene.getObjectByName(n) ?? gltf.scene.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(n));
  const bone = (n) => obj(n)?.getWorldPosition(new THREE.Vector3());
  const head = bone('Head_end') ?? bone('Head'), tail = bone('Tail1');
  const yaw0 = head && tail ? Math.atan2(head.x - tail.x, head.z - tail.z) : 0;   // its facing, from +z
  // breed changes on the rig (opts.aim: [{ chain: [bones root to tip], dir: [down, out, forward] or one per segment,
  // center (bone the "out" side is measured from, Head) }]: a Shiba's pricked ears made to hang and its curled tail to
  // hang behind, as a retriever's do; opts.bones: { <bone>: scale }). Each segment's turn is found once at the first
  // frame, segment by segment from the root, and applied on top of the clip every frame, so the clip's own motion stays
  const fwd = new THREE.Vector3(Math.sin(yaw0), 0, Math.cos(yaw0)), up = new THREE.Vector3(0, 1, 0);
  const side = new THREE.Vector3().crossVectors(fwd, up).normalize();
  for (const a of opts.aim ?? []) {
    const bones = a.chain.map(obj);
    if (bones.some((b) => !b)) { console.warn(`dog3d: aim ${a.chain.join(' > ')}: a bone is missing`); continue; }
    const c = bone(a.center ?? 'Head') ?? new THREE.Vector3();
    const s = Math.sign(bones[0].getWorldPosition(new THREE.Vector3()).sub(c).dot(side)) || 1;
    for (let i = 0; i < bones.length - 1; i++) {
      gltf.scene.updateMatrixWorld(true);
      const b = bones[i];
      const cur = bones[i + 1].getWorldPosition(new THREE.Vector3()).sub(b.getWorldPosition(new THREE.Vector3())).normalize();
      const d = Array.isArray(a.dir[0]) ? a.dir[Math.min(i, a.dir.length - 1)] : a.dir;
      const want = up.clone().multiplyScalar(-d[0]).addScaledVector(side, s * d[1]).addScaledVector(fwd, d[2]).normalize();
      const pq = b.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
      const fix = new THREE.Quaternion().setFromUnitVectors(cur.applyQuaternion(pq), want.applyQuaternion(pq));
      fixes.push({ b, fix });
      b.quaternion.premultiply(fix);
    }
  }
  if (ctx.params?.doglog) console.warn(`dog3d: ${fixes.length} bone turns, facing ${(yaw0 * 180 / Math.PI).toFixed(0)} deg`);
  scales = Object.entries(opts.bones ?? {}).map(([n, s]) => ({ b: obj(n), s: Array.isArray(s) ? s : [s, s, s] })).filter((x) => x.b);
  evalPose([{ clip: opts.program.find((s) => s.clip)?.clip ?? 'Idle', time: 0, w: 1 }], false);
  gltf.scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(gltf.scene, true);
  const unitH = box.max.y - Math.min(0, box.min.y);
  // the room's camera (opts.floor: { row, height: its head-top px with its feet at that row, horizon: the floor's
  // vanishing row, focal (px at 4K) }): a pinhole at the picture's middle, pitched down so the floor vanishes at the
  // horizon, standing as high (in the model's units) as makes the dog stand `height` px tall at `row`. The dog is
  // rendered through it in true perspective (a window of it around the dog), so it sits on the painted floor as the
  // floor recedes, is seen from the side it would be, and a paw pinned to the floor stays put on screen
  const F = opts.floor ?? {};
  const y0 = F.row ?? 1758, h0 = F.height ?? 470, yh = F.horizon ?? 131.6;
  const cx = W / 2, cy = H / 2, focal = F.focal ?? 3325;
  const theta = Math.atan((cy - yh) / focal), cT = Math.cos(theta), sT = Math.sin(theta);
  let Hc = 10;
  const hAt = (y) => h0 * Math.max(0.05, (y - yh) / (y0 - yh));
  // a floor row's distance into the room (D) and along the camera's axis (zc); screen <-> floor (X right, Z toward the
  // camera, units)
  const distOfRow = (y) => { const q = (Math.max(yh + 1, y) - cy) / focal; return (Hc * (cT - q * sT)) / (q * cT + sT); };
  const project = (X, Y, Z) => {
    const ry = Y - Hc, zc = -ry * sT - Z * cT, yc = ry * cT - Z * sT;
    return [cx + (focal * X) / zc, cy - (focal * yc) / zc];
  };
  const floorOf = ([x, y]) => { const D = distOfRow(y), zc = Hc * sT + D * cT; return [((x - cx) * zc) / focal, -D]; };
  const screenOf = ([X, Z]) => project(X, 0, Z);
  const ppuAt = (y) => focal / (Hc * sT + distOfRow(y) * cT);
  // the camera's height: the standing dog's head-top `height` px above its feet at `row`
  {
    let lo = 0.2, hi = 200;
    for (let k = 0; k < 60; k++) {
      Hc = Math.sqrt(lo * hi);
      const top = project(0, box.max.y, -distOfRow(y0))[1];
      if (y0 - top > h0) lo = Hc; else hi = Hc;
    }
  }
  // the walk's gait, from the clip: each paw's place under the body through the cycle and the part of it the paw is down
  // (lowest quarter of its lift); the walk moves as fast as the paws push back while down, and each paw is pinned to
  // the floor while down (two-bone IK on its leg): the clip's own paws don't move back evenly (the hind ones stroke
  // half again as far as the front ones), so no single speed alone keeps them from sliding
  const fwd0 = new THREE.Vector3(Math.sin(yaw0), 0, Math.cos(yaw0));
  const PAWS = ['FrontUpperLeg.L', 'FrontUpperLeg.R', 'BackUpperLeg.L', 'BackUpperLeg.R'];
  const gaitOf = (clip) => {
    const D = clips[clip].duration, N = 96, paws = [];
    for (const up of PAWS) {
      const bones = [obj(up), obj(up.replace('Upper', 'Lower')), obj(`${up.replace('Upper', 'Lower')}_end`)];
      if (bones.some((b) => !b)) continue;
      const tab = [];
      for (let i = 0; i <= N; i++) {
        evalPose([{ clip, time: (D * i) / N, w: 1 }]);
        gltf.scene.updateMatrixWorld(true);
        tab.push(bones[2].getWorldPosition(new THREE.Vector3()));
      }
      const ys = tab.map((p) => p.y), lo = Math.min(...ys), hi = Math.max(...ys), cut = lo + 0.25 * (hi - lo);
      // the longest run of samples below the cut, around the cycle
      let best = [0, 0];
      for (let s = 0; s < N; s++) {
        if (ys[s] > cut || ys[(s + N - 1) % N] <= cut) continue;
        let n = 0;
        while (n < N && ys[(s + n) % N] <= cut) n++;
        if (n > best[1]) best = [s, n];
      }
      const z = (i) => tab[i % N].dot(fwd0);
      const speed = best[1] ? (z(best[0]) - z(best[0] + best[1])) / ((best[1] / N) * D) : 0;
      paws.push({ name: up, bones, tab, c0: (best[0] / N) * D, len: (best[1] / N) * D, speed });
      if (ctx.params?.doglog === 'cycle') console.warn(`dog3d: cycle ${clip} ${up} d ${D.toFixed(4)} y ${ys.map((q) => q.toFixed(3)).join(' ')} | z ${tab.map((p) => p.dot(fwd0).toFixed(3)).join(' ')}`);
    }
    const sp = paws.map((p) => p.speed).filter((v) => v > 0);
    return { D, N, paws, stride: sp.length ? sp.reduce((a, b) => a + b, 0) / sp.length : 0.5 * unitH };
  };
  const tabAt = (g, p, time) => {
    const f = ((((time % g.D) + g.D) % g.D) / g.D) * g.N, i = Math.min(g.N - 1, Math.floor(f));
    return p.tab[i].clone().lerp(p.tab[i + 1], f - i);
  };
  const gaits = {};
  // the program: idle (a clip in place), turn (stepping in place to a heading), walk (along a path on the floor, a turn
  // in place first when the path leads off another way); a 0.3 s crossfade into each step from where the last ended
  const TAU = Math.PI * 2, rad = (d) => (d * Math.PI) / 180, smooth = (x) => { const u = Math.min(1, Math.max(0, x)); return u * u * (3 - 2 * u); };
  const wrap = (a) => ((((a + Math.PI) % TAU) + TAU) % TAU) - Math.PI;
  const pt = (p) => [p[0] * W, p[1] * H];
  const pathOf = (pts) => {
    // corners rounded (two Chaikin passes), then sampled with floor distance and heading
    let P = pts;
    for (let k = 0; k < 2; k++) {
      const Q = [P[0]];
      for (let i = 0; i < P.length - 1; i++) {
        const [a, b] = [P[i], P[i + 1]];
        Q.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]], [0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
      }
      Q.push(P[P.length - 1]);
      P = Q;
    }
    const S = [P[0]];
    for (let i = 1; i < P.length; i++) for (let j = 1; j <= 12; j++) S.push([P[i - 1][0] + ((P[i][0] - P[i - 1][0]) * j) / 12, P[i - 1][1] + ((P[i][1] - P[i - 1][1]) * j) / 12]);
    const FS = S.map(floorOf);
    const cum = [0], hd = [];
    for (let i = 1; i < S.length; i++) {
      const dX = FS[i][0] - FS[i - 1][0], dZ = FS[i][1] - FS[i - 1][1];
      cum.push(cum[i - 1] + Math.hypot(dX, dZ));
      hd.push(Math.atan2(dX, dZ));
    }
    hd.push(hd[hd.length - 1]);
    for (let i = 1; i < hd.length; i++) hd[i] = hd[i - 1] + wrap(hd[i] - hd[i - 1]);
    const len = cum[cum.length - 1];
    const lerp2 = (a, b, f) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    const at = (d) => {
      const dd = Math.min(len, Math.max(0, d));
      let i = cum.findIndex((c) => c >= dd);
      if (i <= 0) return { p: S[0], f: FS[0], h: hd[0] };
      const f = (dd - cum[i - 1]) / Math.max(1e-9, cum[i] - cum[i - 1]);
      return { p: lerp2(S[i - 1], S[i], f), f: lerp2(FS[i - 1], FS[i], f), h: hd[i - 1] + (hd[i] - hd[i - 1]) * f };
    };
    return { len, at };
  };
  const steps = [];
  let pos = null, heading = 0, t = 0, last = null;
  const turnStep = (h1, clip, rate, dur) => {
    const dh = wrap(h1 - heading);
    const T = dur ?? Math.max(0.6, (Math.abs(dh) / (Math.PI / 2)) * 0.9);
    steps.push({ kind: 'turn', clip, t0: t, dur: T, pos: [...pos], h0: heading, h1: heading + dh, rate, phase: last?.clip === clip ? last.time : 0 });
    heading += dh; t += T;
    last = { clip, time: steps[steps.length - 1].phase + T * rate };
  };
  // an arc on the floor (radius r units) from p0 facing h0, turning by dh (+ to its left): a dog turns round by walking a
  // tight curve, not by spinning on the spot (its paws would skate)
  const leftOf = (h) => [Math.cos(h), -Math.sin(h)];
  const arcPts = (p0, h0, dh, r, n = 8) => {
    const [X0, Z0] = floorOf(p0), sg = Math.sign(dh) || 1, L0 = leftOf(h0);
    const C = [X0 + sg * r * L0[0], Z0 + sg * r * L0[1]];
    return Array.from({ length: n }, (_, j) => { const L = leftOf(h0 + (dh * (j + 1)) / n); return screenOf([C[0] - sg * r * L[0], C[1] - sg * r * L[1]]); });
  };
  const dirTo = (a, b) => { const fa = floorOf(a), fb = floorOf(b); return Math.atan2(fb[0] - fa[0], fb[1] - fa[1]); };
  // the phase of the walk whose legs stand most like the standing clip's: walks start and stop there, so the crossfade
  // between walking and standing hardly moves a paw
  const squareOf = (g, clip) => {
    evalPose([{ clip, time: 0, w: 1 }]);
    gltf.scene.updateMatrixWorld(true);
    const at = g.paws.map((p) => p.bones[2].getWorldPosition(new THREE.Vector3()));
    let best = [0, Infinity];
    for (let i = 0; i < g.N; i++) {
      const e = g.paws.reduce((s, p, k) => s + p.tab[i].distanceToSquared(at[k]), 0);
      if (e < best[1]) best = [i, e];
    }
    return (best[0] / g.N) * g.D;
  };
  for (const [k, s] of opts.program.entries()) {
    if (s.at) pos = pt(s.at);
    if (s.do === 'idle') {
      if (s.heading != null) heading = rad(s.heading);
      const rate = s.speed ?? 1, clip = s.clip ?? 'Idle';
      steps.push({ kind: 'idle', clip, t0: t, dur: s.dur, pos: [...pos], h: heading, rate, phase: s.from ?? 0 });
      t += s.dur;
      last = { clip, time: (s.from ?? 0) + s.dur * rate };
    } else if (s.do === 'turn') {
      turnStep(rad(s.to), s.clip ?? 'Walk', s.rate ?? 0.55, s.dur);
    } else if (s.do === 'walk') {
      const clip = s.clip ?? 'Walk';
      const g = (gaits[clip] ??= gaitOf(clip));
      let pts = s.path.map(pt);
      const dh0 = wrap(dirTo(pos, pts[0]) - heading);
      if (Math.abs(dh0) > 0.7) {
        const r = s.radius ?? opts.turnRadius ?? 0.7;
        let arc = [], dh = dh0;
        for (let it = 0; it < 3; it++) {
          arc = arcPts(pos, heading, dh, r);
          const raw = dirTo(arc[arc.length - 1], pts[0]) - heading;
          dh = raw + TAU * Math.round((dh - raw) / TAU);
        }
        pts = [...arc, ...pts];
      }
      const P = pathOf([pos, ...pts]);
      const h = P.at(0).h;
      // the path's headings continue from where the dog faces now (whole turns); a small difference (under 40 deg, more
      // walks an arc) is taken up while it sets off
      const shift = Math.round((heading - h) / TAU) * TAU, off = heading - h - shift;
      const v = g.stride * (s.rate ?? 1), L = P.len, ta = Math.min(0.5, L / v / 3);
      const T = L / v + ta;
      // from standing it sets off at the walk's square phase; when it stops to stand, the clip runs a little faster or
      // slower over the walk (the pinned paws take it up) so it ends there too
      const sq = (g.square ??= squareOf(g, 'Idle'));
      const phase = last?.clip === clip ? last.time : sq;
      const nx = opts.program[k + 1];
      let stride = g.stride;
      if (nx && (nx.do === 'idle' || (nx.clip && nx.clip !== clip))) {
        const raw = sq - (phase + L / g.stride), dlt = raw - g.D * Math.round(raw / g.D);
        stride = L / (L / g.stride + dlt);
      }
      steps.push({ kind: 'walk', clip, t0: t, dur: T, P, v, ta, shift, off, stride, phase });
      t += T;
      pos = P.at(L).p;
      heading = P.at(L).h + shift;
      last = { clip, time: phase + L / stride };
    }
  }
  const end = t;
  // a walk's distance along its path at a time into it (speeding up and slowing down over ta), and back
  const distOf = (s, tau) => {
    const T = s.dur, ta = s.ta, v = s.v, L = s.P.len;
    return tau < ta ? (0.5 * v * tau * tau) / ta : tau > T - ta ? L - (0.5 * v * (T - tau) ** 2) / ta : v * (tau - ta / 2);
  };
  const tauOf = (s, d) => {
    const da = 0.5 * s.v * s.ta, L = s.P.len;
    return d < da ? Math.sqrt((2 * d * s.ta) / s.v) : d > L - da ? s.dur - Math.sqrt((2 * Math.max(0, L - d) * s.ta) / s.v) : d / s.v + s.ta / 2;
  };
  const stateOf = (s, tau) => {
    if (s.kind === 'idle') return { clip: s.clip, time: s.phase + tau * s.rate, pos: s.pos, fl: floorOf(s.pos), h: s.h };
    if (s.kind === 'turn') return { clip: s.clip, time: s.phase + tau * s.rate, pos: s.pos, fl: floorOf(s.pos), h: s.h0 + (s.h1 - s.h0) * smooth(tau / s.dur) };
    const d = distOf(s, tau), a = s.P.at(d);
    return { clip: s.clip, time: s.phase + d / s.stride, pos: a.p, fl: a.f, h: a.h + s.shift + s.off * (1 - smooth(tau / (2 * s.ta))) };
  };
  if (ctx.params?.doglog) {
    for (const [k, g] of Object.entries(gaits)) console.warn(`dog3d: ${k} cycle ${g.D.toFixed(3)} s, walks ${g.stride.toFixed(3)} u/s; paws down ${g.paws.map((p) => `${p.name} ${(p.len / g.D * 100).toFixed(0)}% at ${p.speed.toFixed(2)} u/s`).join(', ')}; unit height ${unitH.toFixed(3)}`);
    console.warn(`dog3d: ${steps.map((s) => `${s.kind}:${s.clip}@${s.t0.toFixed(1)}+${s.dur.toFixed(1)}${s.kind === 'walk' ? ` (to ${((s.P.at(s.P.len).h + s.shift) * 180 / Math.PI).toFixed(0)} deg)` : ''}`).join(' ')} (ends ${end.toFixed(1)} s after the start)`);
  }
  const scene3 = new THREE.Scene();
  scene3.add(root);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 1.6);
  scene3.add(hemi);
  dirLight(scene3, opts.key, { color: '#ffb066', intensity: 2.4, dir: [-0.5, 0.7, 0.4] });
  dirLight(scene3, opts.fill, { color: '#9fb8ff', intensity: 0.5, dir: [0.6, 0.5, -0.5] });
  const RT = opts.texture ?? 1024;
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  // its depth, for the inner lines (no MSAA: a blend of two parts' depths would draw lines between them)
  const zrt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType });
  const zMat = new THREE.MeshDepthMaterial({ depthPacking: THREE.BasicDepthPacking });
  const ZR = 8;   // the depth pass sees the dog's distance +- ZR units: its precision
  const cam = new THREE.PerspectiveCamera((2 * Math.atan(cy / focal) * 180) / Math.PI, W / H, 1, 100);
  cam.position.set(0, Hc, 0);
  cam.rotation.set(-theta, 0, 0);
  cam.updateMatrixWorld(true);
  if (ctx.params?.doglog) console.warn(`dog3d: camera ${Hc.toFixed(2)} units up, pitched ${(theta * 180 / Math.PI).toFixed(1)} deg; the mat ${distOfRow(y0).toFixed(1)} units in, ${ppuAt(y0).toFixed(1)} px per unit`);
  const tDepth = await plateTexture(opts.plate, 'depth8.png');
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  const occ = { uOcclude: { value: opts.occlude === false ? 0 : 1 } };
  const mk = (frag, extra) => new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: frag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4() }, tDepth: { value: tDepth }, uFootUv: { value: new THREE.Vector2() }, ...occ, ...extra },
  });
  const pal = (opts.palette ?? []).slice(0, 32).map(linHex);
  const mat = mk(dogFrag, {
    tDog: { value: rt.texture }, tZ: { value: zrt.texture }, uTexel: { value: new THREE.Vector2(1 / RT, 1 / RT) }, uCell: { value: opts.cell ?? 8.5 },
    uEdge: { value: linHex(opts.edge ?? '#2a1717') },
    // opts.inner: { color, depth (model units a nearer part must stand out by) } or false
    uInner: { value: linHex(opts.inner?.color ?? opts.edge ?? '#2a1717') },
    uZEdge: { value: opts.inner === false ? 0 : (opts.inner?.depth ?? 0.25) / (2 * ZR) },
    uPal: { value: [...pal, ...Array.from({ length: 32 - pal.length }, () => new THREE.Color())] }, uPalN: { value: pal.length },
  });
  const smat = mk(shadowFrag, { uShadow: { value: 0 } });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), smat);
  quad.renderOrder = opts.renderOrder ?? 8;
  shadow.renderOrder = (opts.renderOrder ?? 8) - 0.5;
  for (const m of [shadow, quad]) { m.frustumCulled = false; m.visible = false; m.userData.noAO = true; ctx.add(m); }
  // the empty bed in place of the painted pet, always; the painted pet holds still under it
  if (opts.empty) {
    const e = opts.empty;
    const tex = await new THREE.TextureLoader().loadAsync(e.url);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = tex.minFilter = THREE.NearestFilter;
    tex.generateMipmaps = false;
    const pm = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
      vertexShader: quadVert, fragmentShader: patchFrag, ...PREMUL,
      uniforms: { uBox: { value: new THREE.Vector4(e.x, e.y, e.w, e.h) }, tPatch: { value: tex } },
    }));
    pm.frustumCulled = false; pm.renderOrder = 0.5; pm.userData.noAO = true;
    ctx.add(pm);
    ctx.petHold = () => 1;
  }
  const start = opts.start ?? 0;
  const XF = 0.3, REL = 0.12;
  // whether each step starts with a crossfade from the one before (a different clip, or the same at another phase)
  steps.forEach((s, k) => {
    const pv = k > 0 ? stateOf(steps[k - 1], steps[k - 1].dur) : null;
    s.xf = !!pv && !(pv.clip === s.clip && Math.abs(s.phase - pv.time) < 1e-6);
  });
  // two-bone IK: turn the upper and lower leg so the paw reaches T, the knee kept in the leg's own plane and side. The
  // upper leg's thickness scale shears the lower leg's frame, so each turn is found in the parent's own (scaled) frame,
  // where it maps the direction exactly, and CCD passes close the rest (the lower leg's length shifts as it turns)
  const V = () => new THREE.Vector3();
  const _a = V(), _b = V(), _c = V(), _u = V(), _w = V(), _k = V(), _t = V(), _qa = new THREE.Quaternion(), _m3 = new THREE.Matrix3();
  const turnBone = (bone, from, to) => {
    _m3.setFromMatrix4(bone.parent.matrixWorld).invert();
    const f = from.clone().applyMatrix3(_m3).normalize(), g = to.clone().applyMatrix3(_m3).normalize();
    _qa.setFromUnitVectors(f, g);
    bone.quaternion.premultiply(_qa);
    bone.updateMatrixWorld(true);
  };
  const ik2 = ([A, B, C], T, n) => {
    for (let it = 0; it < 2; it++) {
      A.getWorldPosition(_a); B.getWorldPosition(_b); C.getWorldPosition(_c);
      const l1 = _a.distanceTo(_b), l2 = _b.distanceTo(_c);
      _u.subVectors(T, _a);
      const d = Math.min(l1 + l2 - 1e-4, Math.max(Math.abs(l1 - l2) + 1e-4, _u.length()));
      _u.normalize();
      _w.crossVectors(n, _u).normalize();
      if (_w.dot(_k.subVectors(_b, _a)) < 0) _w.negate();
      const ca = Math.min(1, Math.max(-1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))), sa = Math.sqrt(1 - ca * ca);
      _k.copy(_a).addScaledVector(_u, l1 * ca).addScaledVector(_w, l1 * sa);
      turnBone(A, _b.clone().sub(_a), _k.clone().sub(_a));
      B.getWorldPosition(_b); C.getWorldPosition(_c);
      _t.copy(_a).addScaledVector(_u, d);
      turnBone(B, _c.clone().sub(_b), _t.sub(_b));
    }
    for (let it = 0; it < 3; it++) {
      for (const bone of [B, A]) {
        bone.getWorldPosition(_b); C.getWorldPosition(_c);
        if (_c.distanceToSquared(T) < 1e-8) return;
        turnBone(bone, _c.clone().sub(_b), T.clone().sub(_b));
      }
    }
  };
  // each paw pinned where it touched down while it is down in a walk, found from the time alone (a still or a segment
  // gives the same frame): its touchdown is the start of its window in the clip's cycle, the dog's place and heading
  // then give the spot on the floor, and the spot is seen from where the dog is now; after it lifts, its pinned place
  // lets go into the clip's over REL; the pin lets go over the last 0.3 s of the walk, before the crossfade out
  const pinPaws = (st, tau, cur, rot) => {
    const g = gaits[st.clip];
    if (!g || opts.lock === false) return;
    const lock0 = st.xf ? XF : 0;
    if (tau < lock0) return;
    const lw = smooth((st.dur - tau) / 0.3);
    if (lw <= 0) return;
    root.updateMatrixWorld(true);
    const n = V().set(Math.cos(rot), 0, -Math.sin(rot));
    const dMin = distOf(st, lock0);
    for (const p of g.paws) {
      const u = (((cur.time - p.c0) % g.D) + g.D) % g.D;
      const w = (u < p.len ? 1 : u < p.len + REL ? 1 - smooth((u - p.len) / REL) : 0) * lw;
      if (w <= 0) continue;
      let ttd = cur.time - u, dtd = (ttd - st.phase) * st.stride;
      if (dtd < dMin) { dtd = dMin; ttd = st.phase + dMin / st.stride; }
      const sTd = stateOf(st, tauOf(st, dtd)), pl = tabAt(g, p, ttd), th = sTd.h - yaw0;
      // the spot on the floor (the room's frame, where the dog stands at its floor point)
      const T = V().set(sTd.fl[0] + pl.x * Math.cos(th) + pl.z * Math.sin(th), pl.y, sTd.fl[1] - pl.x * Math.sin(th) + pl.z * Math.cos(th));
      p.bones[2].getWorldPosition(_c);
      const goal = _c.lerp(T, w).clone();
      ik2(p.bones, goal, n);
      if (ctx.params?.pawlog === 'ik' && p.name === (ctx.params?.ikpaw ?? 'BackUpperLeg.L')) {
        const [A, B, C] = p.bones.map((b) => b.getWorldPosition(V()));
        console.warn(`dogik ${tau.toFixed(3)} w ${w.toFixed(2)} goal ${goal.toArray().map((q) => q.toFixed(3))} got ${C.toArray().map((q) => q.toFixed(3))} reach ${goal.distanceTo(A).toFixed(3)}/${(A.distanceTo(B) + B.distanceTo(C)).toFixed(3)}`);
      }
    }
  };
  const prevClear = new THREE.Color();
  ctx.animate((tl) => {
    const t = Math.min(end - 1e-3, Math.max(0, (ctx.realTime?.() ?? tl) - start));
    const i = Math.max(0, steps.findIndex((s) => t < s.t0 + s.dur));
    const st = steps[i], tau = t - st.t0;
    const cur = stateOf(st, tau);
    const list = [{ clip: cur.clip, time: cur.time, w: 1 }];
    // a crossfade from where the step before ended, unless it continues the same clip at the same phase
    if (st.xf && tau < XF) {
      list.unshift({ ...stateOf(steps[i - 1], steps[i - 1].dur), w: 1 });
      list[1].w = smooth(tau / XF);
    }
    evalPose(list);
    const [x, y] = cur.pos;
    root.position.set(cur.fl[0], 0, cur.fl[1]);
    root.rotation.y = cur.h - yaw0;
    if (st.kind === 'walk') pinPaws(st, tau, cur, root.rotation.y);
    const size = hAt(y), ppu = ppuAt(y);
    // the window of the room's view around the dog, one texel a pixel, its feet 80% of the way down
    const ox = Math.round(x - RT / 2), oy = Math.round(y - 0.8 * RT);
    const dist = Math.hypot(cur.fl[0], Hc, cur.fl[1]);
    cam.near = Math.max(0.05, dist - ZR);
    cam.far = dist + ZR;
    cam.setViewOffset(W, H, ox, oy, RT, RT);
    cam.updateProjectionMatrix();
    mat.uniforms.uZEdge.value = opts.inner === false ? 0 : ((opts.inner?.depth ?? 0.25) * cam.far * cam.near) / ((cam.far - cam.near) * dist * dist);
    hemi.color.setRGB(...avg(x - 0.5 * size, y - 1.6 * size, x + 0.5 * size, y - 0.6 * size));
    hemi.groundColor.setRGB(...avg(x - 0.6 * size, y - 0.1 * size, x + 0.6 * size, y + 0.15 * size));
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, cam);
    scene3.overrideMaterial = zMat;
    R.setRenderTarget(zrt);
    R.clear(true, true, true);
    R.render(scene3, cam);
    scene3.overrideMaterial = null;
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    mat.uniforms.uBox.value.set(ox, oy, RT, RT);
    const foot = [x / W, 1 - (y + 2) / H];
    mat.uniforms.uFootUv.value.set(...foot);
    smat.uniforms.uFootUv.value.set(...foot);
    // contact shadow: the body's footprint on the floor, flattened by how steeply the camera looks down there
    const dep = theta + Math.atan((y - cy) / focal);
    const hd = root.rotation.y + yaw0, sh = Math.abs(Math.sin(hd)), ch = Math.abs(Math.cos(hd));
    const L = (box.max.z - box.min.z) * 0.9 * ppu, Wd = (box.max.x - box.min.x) * 1.1 * ppu;
    const rx = (sh * L + ch * Wd) * 0.5, ry = (ch * L + sh * Wd) * 0.5 * Math.sin(dep) + 3;
    smat.uniforms.uBox.value.set(x - rx, y - ry, 2 * rx, 2 * ry);
    smat.uniforms.uShadow.value = opts.shadow ?? 0.4;
    quad.visible = shadow.visible = true;
    // QA (pawlog=1): each paw's place on screen (4K px) and height off the floor (units), to measure any slide
    if (ctx.params?.pawlog) {
      root.updateMatrixWorld(true);
      const v = new THREE.Vector3();
      const paws = ['FrontLowerLeg.L_end', 'FrontLowerLeg.R_end', 'BackLowerLeg.L_end', 'BackLowerLeg.R_end'].map((n) => {
        const b = obj(n);
        if (!b) return 'na';
        b.getWorldPosition(v);
        const h = v.y;
        v.project(cam);
        return `${(ox + ((v.x + 1) / 2) * RT).toFixed(1)},${(oy + ((1 - v.y) / 2) * RT).toFixed(1)},${h.toFixed(3)}`;
      });
      console.warn(`dogpaw ${t.toFixed(4)} ${i} ${st.kind} ${paws.join(' ')}`);
    }
  });
  return quad;
}
