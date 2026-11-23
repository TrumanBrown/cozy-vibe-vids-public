// A fish leaping out of a pool, for blocky looks (user 2026-10-27, the jungle temple: fish jumping, or another animal
// in the water): an original blocky salmon built from boxes in code, flying its leap's arc (timeline fish events with
// `lh`, `ld`, `hd`, `air`: the stream's `leap` spec) from where it breaks the surface to where it dives back in. Nose up
// as it leaves the water and down as it goes back in, along its path; its tail beats; only what is above the water
// shows (the rest is cut at the surface), so it slides out of the water and back into it. fish.js draws the rings and
// the splashes at both ends.
//
// Rendered like frog3d.js: into its own texture every frame from the lake camera's angle at the fish, one texel or
// more per screen pixel, and composited onto the plate, hidden behind anything clearly nearer than the water under it.
// Lit from the plate around it, the moon behind it as a rim light on its wet back.
//
// opts (the fish layer's): { plate, camera, palette ('salmon' | 'cod'), length (m, 0.7, times the event's size), key
//   { dir, color, intensity }, ambient, texels (per unit, 2.2), renderOrder (3.9: under the splashes) }
import * as THREE from 'three';
import { plateTexture, imagePixels, boxMean, dirLight, PREMUL } from './overlay.js';
import { boxMaterials, hash3 } from './boxart.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;
const PALETTES = {
  salmon: { back: '#74463a', side: '#c4654d', spot: '#8f4636', belly: '#efdcc2', fin: '#6f7c66', eye: '#101010', gill: '#9a3c31' },
  cod: { back: '#7d7253', side: '#b9ad84', spot: '#8f8461', belly: '#ece7d2', fin: '#8f7f5c', eye: '#101010', gill: '#6f6649' },
};

// the body, 10 units nose to tail-fin tip, nose toward +z
function buildFish(palette, texels) {
  const C = PALETTES[palette] ?? PALETTES.salmon;
  const body = (h) => (p, f) => {
    if (f === 3 || p[1] < -0.32 * h) return C.belly;
    if (f === 2 || p[1] > 0.3 * h) return C.back;
    return hash3(Math.floor(p[0] * 3 + 9), Math.floor(p[1] * 3 + 9), Math.floor(p[2] * 3 + 9)) > 0.8 ? C.spot : C.side;
  };
  const head = (p, f) => (f === 4 && p[1] < -0.2 ? C.gill : f === 5 ? C.gill : body(1.9)(p, f));
  const box = (size, paint, id, rough = 0.38) => new THREE.Mesh(new THREE.BoxGeometry(...size),
    boxMaterials(size, texels, paint, id, { grain: 0.12, roughness: rough }));
  const root = new THREE.Group();
  const front = box([1.6, 2.4, 3.4], body(2.4), 31);
  front.position.set(0, 0, 1.6);
  root.add(front);
  const hd = box([1.4, 1.9, 1.6], head, 32);
  hd.position.set(0, -0.08, 4.1);
  root.add(hd);
  for (const s of [1, -1]) {
    const e = box([0.2, 0.32, 0.32], () => C.eye, 33);
    e.position.set(s * 0.72, 0.28, 4.35);
    root.add(e);
    const pf = box([0.12, 0.5, 0.9], () => C.fin, 34, 0.6);
    pf.position.set(s * 0.86, -0.75, 2.6);
    pf.rotation.z = s * 0.5;
    root.add(pf);
  }
  const dorsal = box([0.22, 0.8, 1.5], () => C.fin, 35, 0.6);
  dorsal.position.set(0, 1.55, 1.4);
  root.add(dorsal);
  const back = new THREE.Group();          // the tail half beats about the joint
  back.position.set(0, 0, -0.1);
  root.add(back);
  const rear = box([1.3, 2.0, 2.9], body(2.0), 36);
  rear.position.set(0, 0, -1.45);
  back.add(rear);
  const fin = new THREE.Group();
  fin.position.set(0, 0, -2.9);
  back.add(fin);
  // a forked tail, wider than the body is tall: what makes the shape read as a fish at 60 px
  for (const s of [1, -1]) {
    const lobe = box([0.24, 1.7, 1.5], () => C.fin, 37, 0.6);
    lobe.position.set(0, s * 0.85, -0.85);
    lobe.rotation.x = s * 0.45;
    fin.add(lobe);
  }
  return { root, back, fin, mats: [] };
}

const quadVert = /* glsl */ `
uniform vec4 uBox;
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
const fishFrag = /* glsl */ `
uniform sampler2D tFish, tDepth;
uniform vec2 uFootUv;
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec4 c = texture2D(tFish, vec2(vT.x, 1.0 - vT.y));   // premultiplied over a clear target
  if (c.a < 0.002) discard;
  float d0 = texture2D(tDepth, uFootUv).r, d = texture2D(tDepth, vUv).r;
  float f = 1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, d);   // anything clearly nearer than the water hides it
  if (f <= 0.0) discard;
  gl_FragColor = vec4(c.rgb * f, c.a * f);
}`;

// The fish's state at tau s into its event: null outside the leap.
export function leapAt(ev, tau) {
  const u = tau / ev.air;
  if (!(u > 0 && u < 1)) return null;
  const vh = ev.ld / ev.air, vv = (4 * ev.lh * (1 - 2 * u)) / ev.air;
  return { u, h: 4 * ev.lh * u * (1 - u), s: ev.ld * u, pitch: Math.atan2(vv, vh), beat: Math.sin(TAU * 4.2 * tau + (ev.seed % 7)) };
}

export async function leapFishLayer(ctx, opts, cam, evs) {
  const R = ctx.renderer;
  evs = evs.filter((e) => e.jump && e.air);
  if (!R || !evs.length) return null;
  const fish = buildFish(opts.palette ?? 'salmon', opts.texels ?? 2.2);
  const scene3 = new THREE.Scene();
  scene3.add(fish.root);
  const water = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  fish.root.traverse((o) => { if (o.material) for (const m of [].concat(o.material)) m.clippingPlanes = [water]; });
  R.localClippingEnabled = true;
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 2.0);
  scene3.add(hemi);
  // the moon behind and above it: a rim on its wet back and its fins; the sky and the water's glitter light its side
  dirLight(scene3, opts.key, { color: '#c9d6ff', intensity: 2.6, dir: [0.3, 0.75, -0.6] });
  const fill = new THREE.DirectionalLight('#9fb4e8', opts.fill ?? 1.4);
  scene3.add(fill);
  const RT = 256;
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  const ocam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
  const tDepth = await plateTexture(opts.plate, 'depth8.png');
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  const mat = new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: fishFrag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4() }, tFish: { value: rt.texture }, tDepth: { value: tDepth }, uFootUv: { value: new THREE.Vector2() } },
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.renderOrder = opts.renderOrder ?? 3.9;
  quad.frustumCulled = false;
  quad.visible = false;
  quad.userData.noAO = true;
  ctx.add(quad);
  const prevClear = new THREE.Color();
  const v3 = (a) => new THREE.Vector3(...a);
  ctx.animate((t) => {
    let ev = null, st = null;
    for (const e of evs) {
      if (e.t > t) break;
      const s = leapAt(e, t - e.t);
      if (s) { ev = e; st = s; }
    }
    quad.visible = !!st;
    if (!st) return;
    const L = (opts.length ?? 0.7) * ev.size;
    const dir = [Math.cos(ev.hd), 0, Math.sin(ev.hd)];
    const P0 = cam.toWater(ev.x, ev.y);
    const Wp = [P0[0] + dir[0] * st.s, st.h, P0[2] + dir[2] * st.s];
    const [px, py, dep] = cam.project(Wp);
    const foot = cam.project([Wp[0], 0, Wp[2]]);
    const ppm = cam.F / dep;
    // the fish: yaw along its way, pitch along its arc, a little roll; the tail half beats
    fish.root.scale.setScalar(L / 10);
    fish.root.rotation.set(-st.pitch, Math.atan2(dir[0], dir[2]), 0.15 * st.beat, 'YXZ');
    fish.back.rotation.y = 0.32 * st.beat;
    fish.fin.rotation.y = 0.35 * Math.sin(TAU * 4.2 * (t - ev.t) - 0.9 + (ev.seed % 7));
    water.constant = st.h;            // the water's surface, st.h below the fish's middle
    // seen from the lake camera's side of it
    const toCam = v3(cam.C).sub(v3(Wp)).normalize();
    const hs = 0.62 * L + 0.08;
    Object.assign(ocam, { left: -hs, right: hs, top: hs, bottom: -hs });
    ocam.updateProjectionMatrix();
    ocam.position.copy(toCam.multiplyScalar(50));
    ocam.up.set(0, 1, 0);
    ocam.lookAt(0, 0, 0);
    fill.position.copy(ocam.position).add(new THREE.Vector3(0, 30, 0));
    // the light where it is: the plate behind it and the water under it (a dark night plate: lifted, it is the light
    // that falls on it from the whole sky, not the dark trees behind it)
    const bp = hs * ppm, lift = opts.skyGain ?? 3;
    hemi.color.setRGB(...avg(px - bp, py - 2 * bp, px + bp, py - bp).map((c) => c * lift));
    hemi.groundColor.setRGB(...avg(foot[0] - bp, foot[1] - 0.3 * bp, foot[0] + bp, foot[1] + 0.3 * bp).map((c) => c * lift));
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, ocam);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    const sz = 2 * hs * ppm;
    mat.uniforms.uBox.value.set(px - sz / 2, py - sz / 2, sz, sz);
    mat.uniforms.uFootUv.value.set(foot[0] / W, 1 - foot[1] / H);
  });
  return quad;
}
