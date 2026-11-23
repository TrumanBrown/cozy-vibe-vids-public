// Animated effects. Everything is a pure function of t and periodic in loopSeconds (integer cycle
// counts), so any frame renders identically and loops are seamless.
import * as THREE from 'three';
import { T } from './props.js';
import { getTexture } from '../engine/textures.js';

const TAU = Math.PI * 2;
const fract = (v) => v - Math.floor(v);
const smooth = (v) => v * v * (3 - 2 * v);

// Sum of sines with integer cycles per loop: deterministic, periodic, organic flicker around 1.
export function flicker(rng, loopSeconds, { amount = 0.12, hz = [1.5, 7], terms = 5 } = {}) {
  const parts = Array.from({ length: terms }, () => ({
    n: Math.max(1, Math.round(rng.range(hz[0], hz[1]) * loopSeconds)), ph: rng.range(0, TAU), a: rng.range(0.4, 1),
  }));
  const norm = parts.reduce((s, p) => s + p.a, 0);
  return (t) => 1 + (amount * parts.reduce((s, p) => s + p.a * Math.sin((TAU * p.n * t) / loopSeconds + p.ph), 0)) / norm;
}

function instanced(geo, mat, count, { order = 10 } = {}) {
  const m = new THREE.InstancedMesh(geo, mat, count);
  m.frustumCulled = false; // bounds are lazily computed on first render -> would depend on start frame
  m.renderOrder = order;
  m.userData.noAO = true;
  m.castShadow = false;
  m.receiveShadow = false;
  return m;
}

// Falling rain streaks inside an axis-aligned volume.
export function rain(ctx, { min, max, count = 1500, color = '#c9b9a8', opacity = 0.35, len = [0.25, 0.5], speed = 14, tilt = 0.12, width = T, rng, order = 5, fog = true }) {
  const L = ctx.loopSeconds;
  const H = max[1] - min[1];
  const mesh = instanced(new THREE.BoxGeometry(width, 1, width), new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, fog }), count, { order });
  const drops = Array.from({ length: count }, () => ({
    x: rng.range(min[0], max[0]), z: rng.range(min[2], max[2]), ph: rng.next(),
    cyc: Math.max(1, Math.round((speed * rng.range(0.85, 1.15) * L) / H)), len: rng.range(len[0], len[1]),
  }));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), tilt), v = new THREE.Vector3(), s = new THREE.Vector3();
  const drift = Math.tan(tilt);
  ctx.animate((t) => {
    drops.forEach((d, i) => {
      const k = fract(d.ph + (d.cyc * t) / L);
      const y = max[1] - k * H;
      v.set(d.x - (max[1] - y) * drift, y, d.z);
      mesh.setMatrixAt(i, m4.compose(v, q, s.set(1, d.len, 1)));
    });
    mesh.instanceMatrix.needsUpdate = true;
  });
  return ctx.add(mesh);
}

// Water on a window: static beads plus drops that slide down now and then, leaving a short trail.
// The glass lies in the local XY plane (z = 0) of `frame` (a THREE.Object3D placed by the caller).
export function glassDrops(ctx, { x0, x1, y0, y1, beads = 90, sliders = 10, rng, color = '#b8bfd8', parent, opacity = 0.42 }) {
  const L = ctx.loopSeconds;
  const mat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity, roughness: 0.05, metalness: 0.2, depthWrite: false });
  const geo = new THREE.BoxGeometry(1, 1, T / 2);
  const bead = instanced(geo, mat, beads, { order: 12 });
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3();
  for (let i = 0; i < beads; i++) {
    const sz = (rng.chance(0.2) ? 1.2 : 0.7) * T;
    bead.setMatrixAt(i, m4.compose(v.set(rng.range(x0, x1), rng.range(y0, y1), 0), q, s.set(sz, sz * rng.pick([1, 1, 1.5]), 1)));
  }
  const slide = instanced(geo, mat, sliders * 2, { order: 13 });
  const ds = Array.from({ length: sliders }, () => ({ x: rng.range(x0 + 0.05, x1 - 0.05), ph: rng.next(), cyc: rng.int(1, 3), active: rng.range(0.25, 0.45) }));
  const hide = new THREE.Matrix4().makeScale(0, 0, 0);
  ctx.animate((t) => {
    ds.forEach((d, i) => {
      const k = fract(d.ph + (d.cyc * t) / L);
      if (k > d.active) { slide.setMatrixAt(2 * i, hide); slide.setMatrixAt(2 * i + 1, hide); return; }
      const p = smooth(k / d.active);
      const y = y1 - 0.05 - p * (y1 - y0 - 0.1);
      slide.setMatrixAt(2 * i, m4.compose(v.set(d.x, y, 0.002), q, s.set(2 * T, 2.5 * T, 1)));
      const trail = Math.min(0.5, (y1 - 0.05 - y));
      slide.setMatrixAt(2 * i + 1, m4.compose(v.set(d.x, y + trail / 2 + T, 0.001), q, s.set(T * 0.6, Math.max(T, trail), 1)));
    });
    slide.instanceMatrix.needsUpdate = true;
  });
  (parent ?? ctx.scene).add(bead, slide);
  return { bead, slide };
}

// Voxel fire: rising cubes that shrink and cool from white-yellow to deep red. HDR instance colors bloom.
export function fire(ctx, { pos, w = 0.8, d = 0.35, h = 0.75, count = 70, rng, size = [0.1, 0.2], speed = 0.9 }) {
  const L = ctx.loopSeconds;
  const mat = new THREE.MeshBasicMaterial({ color: '#ffffff', fog: false });
  const mesh = instanced(new THREE.BoxGeometry(1, 1, 1), mat, count, { order: 1 });
  mesh.userData.noAO = true;
  const ps = Array.from({ length: count }, () => {
    const cx = rng.range(-1, 1), cz = rng.range(-1, 1);
    return {
      x: cx * w / 2 * (1 - Math.abs(cz) * 0.3), z: cz * d / 2, ph: rng.next(),
      cyc: Math.max(1, Math.round((speed * rng.range(0.8, 1.25) * L) / h)), s: rng.range(size[0], size[1]) * (1.2 - Math.abs(cx) * 0.5),
      hm: (1 - Math.abs(cx) * 0.55) * rng.range(0.7, 1.1), wob: rng.range(0, TAU), wf: rng.int(2, 5),
    };
  });
  const hot = new THREE.Color(1.35, 0.62, 0.1), mid = new THREE.Color(1.0, 0.26, 0.02), cool = new THREE.Color(0.42, 0.05, 0.01);
  const c = new THREE.Color(), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3();
  ctx.animate((t) => {
    ps.forEach((p, i) => {
      const k = fract(p.ph + (p.cyc * t) / L);
      const y = pos[1] + k * h * p.hm;
      const wob = Math.sin(TAU * (p.wf * (p.cyc * t) / L) + p.wob) * 0.04 * k;
      v.set(pos[0] + p.x * (1 - 0.6 * k) + wob, y, pos[2] + p.z * (1 - 0.5 * k));
      const sc = p.s * Math.pow(1 - k, 0.8) + 0.01;
      mesh.setMatrixAt(i, m4.compose(v, q, s.set(sc, sc * 1.3, sc)));
      if (k < 0.45) c.copy(hot).lerp(mid, k / 0.45); else c.copy(mid).lerp(cool, (k - 0.45) / 0.55);
      mesh.setColorAt(i, c);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.instanceColor.needsUpdate = true;
  });
  mesh.setColorAt(0, hot);
  return ctx.add(mesh);
}

// Rising steam wisps (additive, fading toward the top).
export function steam(ctx, { pos, count = 10, h = 0.6, rng, color = [0.5, 0.48, 0.45] }) {
  const L = ctx.loopSeconds;
  const mesh = instanced(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }), count, { order: 20 });
  const ps = Array.from({ length: count }, () => ({ ph: rng.next(), cyc: Math.max(1, Math.round((0.18 * L) / h * rng.range(0.8, 1.2))), dx: rng.range(-1, 1), wf: rng.int(1, 3), w: rng.range(0, TAU) }));
  const c = new THREE.Color(), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3();
  ctx.animate((t) => {
    ps.forEach((p, i) => {
      const k = fract(p.ph + (p.cyc * t) / L);
      v.set(pos[0] + p.dx * 0.03 + Math.sin(TAU * p.wf * k + p.w) * 0.05 * k, pos[1] + k * h, pos[2] + Math.cos(TAU * p.wf * k + p.w) * 0.03 * k);
      const sc = T * (1 + k * 2);
      mesh.setMatrixAt(i, m4.compose(v, q, s.set(sc, sc, sc)));
      const a = Math.sin(Math.PI * k) * (1 - k);
      mesh.setColorAt(i, c.setRGB(color[0] * a, color[1] * a, color[2] * a));
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.instanceColor.needsUpdate = true;
  });
  mesh.setColorAt(0, c.setRGB(0, 0, 0));
  return ctx.add(mesh);
}

// Vertical haze card: color fades from `opacity` at the bottom to 0 at the top (adds depth to exteriors).
export function hazeCard(ctx, { center, w, h, color = '#3a2a3a', opacity = 0.5, rotY = 0, order = 3, fog = true, top = 0 }) {
  const geo = new THREE.PlaneGeometry(w, h, 1, 8);
  const cols = [];
  const pos = geo.attributes.position;
  const cc = new THREE.Color(color);
  for (let i = 0; i < pos.count; i++) {
    const k = (pos.getY(i) + h / 2) / h;
    cols.push(cc.r, cc.g, cc.b, opacity * (1 - k) + top * k);
  }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 4));
  const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, fog }));
  m.position.set(...center);
  m.rotation.y = rotY;
  m.renderOrder = order;
  m.userData.noAO = true;
  return ctx.add(m);
}

// Gradient sky backdrop (unlit, no fog).
export function sky(ctx, { center, w, h, top = '#141026', bottom = '#3a2a30', rotY = 0 }) {
  const geo = new THREE.PlaneGeometry(w, h, 1, 16);
  const a = new THREE.Color(bottom), b = new THREE.Color(top), c = new THREE.Color();
  const cols = [];
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) { const k = (pos.getY(i) + h / 2) / h; c.copy(a).lerp(b, Math.pow(k, 0.7)); cols.push(c.r, c.g, c.b); }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
  const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, fog: false, depthWrite: false }));
  m.position.set(...center);
  m.rotation.y = rotY;
  m.renderOrder = -1;
  m.userData.noAO = true;
  return ctx.add(m);
}

// Window glass pane (slightly tinted, transparent).
export function glass(ctx, { x0, x1, y0, y1, z, tint = '#40384e', opacity = 0.14, rotY = 0, parent }) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, y1 - y0), new THREE.MeshStandardMaterial({ color: tint, transparent: true, opacity, roughness: 0.35, envMapIntensity: 0.15, depthWrite: false }));
  m.position.set((x0 + x1) / 2, (y0 + y1) / 2, z);
  m.rotation.y = rotY;
  m.renderOrder = 11;
  m.userData.noAO = true;
  (parent ?? ctx.scene).add(m);
  return m;
}

// Lake: planar reflection with periodic ripple distortion (stretches lights into vertical streaks),
// rain-ring sparkles, depth darkening and exponential fog. Everything periodic in loopSeconds.
export async function lake(ctx, { x0, x1, z0, z1, y, color = '#1a2430', reflect = 0.75, ripple = 0.012, rings = true, fog, resolution = [1920, 1080] }) {
  const { Reflector } = await import('three/addons/objects/Reflector.js');
  const L = ctx.loopSeconds;
  const shader = {
    name: 'LakeShader',
    uniforms: {
      color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null },
      phase: { value: 0 }, deep: { value: new THREE.Color(color) }, reflect: { value: reflect }, ripple: { value: ripple },
      rings: { value: rings ? 1 : 0 }, fogColor: { value: new THREE.Color(fog?.color ?? '#000000') }, fogDensity: { value: fog?.density ?? 0 },
    },
    vertexShader: /* glsl */ `
      uniform mat4 textureMatrix;
      varying vec4 vUv;
      varying vec3 vWorld;
      varying float vDepth;
      void main() {
        vUv = textureMatrix * vec4(position, 1.0);
        vec4 w = modelMatrix * vec4(position, 1.0);
        vWorld = w.xyz;
        vec4 mv = viewMatrix * w;
        vDepth = -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D tDiffuse;
      uniform float phase;
      uniform vec3 deep;
      uniform float reflect;
      uniform float ripple;
      uniform float rings;
      uniform vec3 fogColor;
      uniform float fogDensity;
      varying vec4 vUv;
      varying vec3 vWorld;
      varying float vDepth;
      const float TAU = 6.28318530718;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      void main() {
        vec2 p = vWorld.xz;
        float a = phase * TAU;
        // Integer temporal frequencies => periodic in the loop.
        float w = sin(p.y * 2.3 + p.x * 0.4 + a * 7.0) * 0.5 + sin(p.y * 4.1 - p.x * 0.9 - a * 11.0) * 0.3 + sin(p.y * 7.7 + p.x * 1.7 + a * 17.0) * 0.2;
        float wx = sin(p.x * 3.1 + p.y * 0.7 - a * 9.0) * 0.5 + sin(p.x * 6.3 - p.y * 1.3 + a * 13.0) * 0.5;
        vec2 d = vec2(wx * 0.25, w) * ripple;
        float ring = 0.0;
        if (rings > 0.5) {
          vec2 cell = floor(p * 0.9);
          vec2 f = fract(p * 0.9) - 0.5;
          float h = hash(cell);
          float k = fract(h * 7.0 + phase * floor(3.0 + h * 5.0));
          vec2 o = vec2(hash(cell + 3.1), hash(cell + 7.7)) - 0.5;
          float r = length(f - o * 0.5);
          ring = smoothstep(0.03, 0.0, abs(r - k * 0.45)) * (1.0 - k) * step(0.55, hash(cell + 1.9));
          d += (f - o * 0.5) * ring * 0.02;
        }
        vec4 uv = vUv;
        uv.xy += d * uv.w;
        vec3 refl = texture2DProj(tDiffuse, uv).rgb;
        vec3 c = deep + refl * reflect + ring * 0.05;
        float fog = 1.0 - exp(-fogDensity * fogDensity * vDepth * vDepth);
        gl_FragColor = vec4(mix(c, fogColor, fog), 1.0);
      }`,
  };
  const geo = new THREE.PlaneGeometry(x1 - x0, Math.abs(z1 - z0));
  const water = new Reflector(geo, { shader, textureWidth: resolution[0], textureHeight: resolution[1], clipBias: 0.003, multisample: 4 });
  water.rotation.x = -Math.PI / 2;
  water.position.set((x0 + x1) / 2, y, (z0 + z1) / 2);
  water.userData.noAO = true;
  water.renderOrder = -0.5;
  ctx.animate((t) => { water.material.uniforms.phase.value = (t % L) / L; });
  return ctx.add(water);
}

// Leaves drifting down with a slow tumble. Each leaf falls once per cycle during `active` of it, then hides.
export function fallingLeaves(ctx, { min, max, count = 6, rng, palette, active = 0.25, size = 0.32, order = 14 }) {
  const L = ctx.loopSeconds;
  const pal = palette ?? ['#d8641e', '#e8a030', '#b8401a'];
  const sprites = [0, 1, 2].map((i) => {
    const tex = getTexture({ name: 'leafCard', shape: 'maple', seed: i }, ctx.seed);
    return new THREE.MeshStandardMaterial({ map: tex.map, color: pal[i % pal.length], alphaTest: 0.5, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 0.7, emissive: pal[i % pal.length], emissiveIntensity: 0.12 });
  });
  const leaves = [];
  for (let i = 0; i < count; i++) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), sprites[i % 3]);
    m.renderOrder = order;
    m.userData.noAO = true;
    m.castShadow = false;
    ctx.add(m);
    leaves.push({ m, x: rng.range(min[0], max[0]), z: rng.range(min[2], max[2]), ph: rng.next(), cyc: rng.int(1, 2), sway: rng.range(0.3, 0.8), spin: rng.int(1, 3), w: rng.range(0, Math.PI * 2) });
  }
  ctx.animate((t) => {
    for (const l of leaves) {
      const k = fract(l.ph + (l.cyc * t) / L);
      if (k > active) { l.m.visible = false; continue; }
      const u = k / active;
      l.m.visible = true;
      const a = TAU * l.spin * u + l.w;
      l.m.position.set(l.x + Math.sin(a) * l.sway, max[1] - u * (max[1] - min[1]), l.z + Math.cos(a * 0.7) * l.sway * 0.5 + u * 0.8);
      l.m.rotation.set(Math.PI / 2 + Math.sin(a) * 0.7, a * 0.3, Math.cos(a) * 0.5);
    }
  });
  return leaves;
}

// Fallen leaves scattered flat on a surface (static).
export function scatterLeaves(ctx, { min, max, y, count = 20, rng, palette, size = 0.3, avoid = () => false }) {
  const pal = palette ?? ['#d8641e', '#e8a030', '#b8401a', '#c87a28'];
  const mats = [0, 1, 2, 3].map((i) => {
    const tex = getTexture({ name: 'leafCard', shape: 'maple', seed: i % 3 }, ctx.seed);
    return new THREE.MeshStandardMaterial({ map: tex.map, color: pal[i % pal.length], alphaTest: 0.5, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 0.75, emissive: pal[i % pal.length], emissiveIntensity: 0.08 });
  });
  for (let i = 0; i < count; i++) {
    const x = rng.range(min[0], max[0]), z = rng.range(min[1], max[1]);
    if (avoid(x, z)) continue;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mats[i % 4]);
    m.position.set(x, y + 0.004 + i * 0.0003, z);
    m.rotation.set(-Math.PI / 2, 0, rng.range(0, TAU));
    m.receiveShadow = true;
    ctx.add(m);
  }
}
