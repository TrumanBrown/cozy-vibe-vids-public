// The layer that puts a blocky creature built in code onto the plate (frog3d.js, rabbit3d.js): every frame the
// creature is posed from its timeline event, rendered into its own texture (an orthographic view from the scene
// camera's angle down at the floor where it is, one texel per screen pixel) and composited onto the plate, hidden
// behind anything clearly nearer than the floor under it (plate depth), with a soft contact shadow that stays on the
// floor while it is in the air. It is lit like the plate around it: a hemisphere light from the defocused plate above
// it and the floor around it, and a key light as bright as the floor there is lit.
//
// On a glossy floor (opts.reflect > 0: the share of light the floor mirrors) it also shows in the floor: the scene seen
// from the camera mirrored below the floor, flipped, blurred and fading with the distance below its feet, as the
// painted floor's own reflections of the fire and the windows do.
//
// C, the creature: { type (its timeline events' type), BL (its body length in units: the floor's `size` px),
//   build () -> { root, ... }, at (event, tau) -> its state { x, y, h, arc, ... } or null, apply (model, state),
//   span (units across the offscreen view, 26), cy (units: the view's center above the floor, 4), maxRT (the view's
//   largest size in texels, 1024), above ([x0, y0, x1, y1]
//   in body lengths from its floor point, image axes: where the plate's light above it is read), ground (the same, for
//   the floor's), footprint (state) -> [length, width] in units (the shadow's) }
// opts: { plate, floor: scene.json events.<type> (horizon, size, focal), key: { dir, color, intensity }, fill, ambient
//   (hemisphere gain, 2.2), ambientSat (that light's saturation, 1 = the plate's own colors), ambientKnee (linear
//   luminance: brighter plate light grows only with its square root; off), keyRef (0.06 linear), keyMax (the most the
//   key grows with the floor's light, 1.6), shoulder ([knee, ceiling] in linear luminance: highlights roll off above the
//   knee; off by default), shadow (0.45), reflect (0), reflectFade (body lengths, 0.6),
//   renderOrder (8) }
import * as THREE from 'three';
import { plateTexture, imagePixels, boxMean, dirLight, PREMUL } from './overlay.js';
import { floorScale } from './timeline/frog.js';

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
// anything clearly nearer than the floor under the creature hides it
const OCCLUDE = /* glsl */ `
float frontOf(vec2 uv) {
  float d0 = texture2D(tDepth, uFootUv).r, d = texture2D(tDepth, uv).r;
  return 1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, d);
}`;
// a painting's highlights roll off: above the knee (linear luminance) the creature's light eases toward the ceiling,
// at its own hue, so it never glows (plate scenes bloom above 0.92) or clips where the plate is brightest. 0: off
const SHOULDER = /* glsl */ `
uniform vec2 uShoulder;
vec3 shoulder(vec4 c) {   // premultiplied in and out
  float L = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)) / max(c.a, 1e-4);
  if (uShoulder.x <= 0.0 || L <= uShoulder.x) return c.rgb;
  float k = uShoulder.x, m = uShoulder.y;
  return c.rgb * (k + (m - k) * (1.0 - exp(-(L - k) / (m - k)))) / L;
}`;
const bodyFrag = /* glsl */ `
uniform sampler2D tFrog, tDepth;
uniform vec2 uFootUv;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
${SHOULDER}
void main() {
  vec4 c = texture2D(tFrog, vec2(vT.x, 1.0 - vT.y));   // premultiplied over a clear target
  if (c.a < 0.002) discard;
  float f = frontOf(vUv);
  if (f <= 0.0) discard;
  gl_FragColor = vec4(shoulder(c) * f, c.a * f);
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
  float k = exp(-r2 * 2.2) * (1.0 - smoothstep(0.8, 1.0, r2)) * uShadow * frontOf(vUv);
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;
// the mirrored view: flipped (it was rendered from below the floor), only below the feet, blurred and fading with the
// distance below them (a waxed plank floor is a soft mirror)
const reflectFrag = /* glsl */ `
uniform sampler2D tRefl, tDepth;
uniform vec2 uFootUv;
uniform float uReflect, uFootT, uFade, uTexel;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
${SHOULDER}
void main() {
  float below = vT.y - uFootT;                       // 0..1 of the box below the feet
  if (below < 0.0) discard;
  float r = (1.5 + 60.0 * below) * uTexel;           // the blur grows away from the feet
  vec4 c = vec4(0.0);
  for (int i = -2; i <= 2; i++) for (int j = -2; j <= 2; j++)
    c += texture2D(tRefl, vec2(vT.x + float(i) * r, vT.y + float(j) * r * 1.6)) / 25.0;
  float k = uReflect * exp(-below / uFade) * frontOf(vUv);
  if (c.a * k < 0.002) discard;
  gl_FragColor = vec4(shoulder(c), c.a) * k;
}`;

export async function creatureLayer(ctx, opts, C) {
  const R = ctx.renderer;
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === C.type && e.hops?.length);
  if (!R || !evs.length) return null;
  const Fl = opts.floor ?? {};
  const BL = C.BL;
  const model = C.build();
  const scene3 = new THREE.Scene();
  scene3.add(model.root);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 2.2);
  scene3.add(hemi);
  const key = dirLight(scene3, opts.key, { color: '#ffb066', intensity: 2.2, dir: [0.15, 0.8, -0.55] });
  dirLight(scene3, opts.fill, { color: '#9db4ff', intensity: 0.5, dir: [0.75, 0.45, 0.3] });
  const keyI = key.intensity;
  // offscreen target: one texel per screen pixel at the largest size it reaches (off the frame's bottom), `span` units
  // across
  const span = C.span ?? 26, CY = C.cy ?? 4;
  const maxPpu = floorScale(Fl, 1.12).s / BL;
  const RT = Math.min(C.maxRT ?? 1024, Math.ceil((span * maxPpu) / 16) * 16);
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  const reflect = opts.reflect ?? 0;
  const rtR = reflect > 0 ? new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 }) : null;
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 1000);
  const tDepth = await plateTexture(opts.plate, 'depth8.png');
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  const shoulderOpt = opts.shoulder ?? [0, 1];
  const mk = (frag, extra) => new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: frag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4() }, tDepth: { value: tDepth }, uFootUv: { value: new THREE.Vector2() },
      uShoulder: { value: new THREE.Vector2(...shoulderOpt) }, ...extra },
  });
  const mat = mk(bodyFrag, { tFrog: { value: rt.texture } });
  const smat = mk(shadowFrag, { uShadow: { value: 0 } });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), smat);
  const ro = opts.renderOrder ?? 8;
  quad.renderOrder = ro;
  shadow.renderOrder = ro - 0.5;
  const meshes = [shadow, quad];
  let rmat = null, refl = null;
  if (rtR) {
    rmat = mk(reflectFrag, { tRefl: { value: rtR.texture }, uReflect: { value: reflect }, uFootT: { value: 0.5 },
      uFade: { value: 0.2 }, uTexel: { value: 1 / RT } });
    refl = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), rmat);
    refl.renderOrder = ro - 0.75;
    meshes.unshift(refl);
  }
  for (const m of meshes) { m.frustumCulled = false; m.visible = false; m.userData.noAO = true; ctx.add(m); }
  const prevClear = new THREE.Color();
  const draw = (target) => {
    R.setRenderTarget(target);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.render(scene3, cam);
  };
  const [ax0, ay0, ax1, ay1] = C.above ?? [-0.8, -1.2, 0.8, -0.4];
  const [gx0, gy0, gx1, gy1] = C.ground ?? [-0.7, -0.15, 0.7, 0.2];
  const sat = opts.ambientSat ?? 1, knee = opts.ambientKnee ?? 0;
  // ambientKnee (linear luminance): brighter plate light than this only grows with the square root of its brightness. The
  // spruce cabin's rabbit, as white as the wolf in the room's middle, glowed in the fire's pool of light in front of the
  // hearth, where the painting keeps its white wolf a warm gray
  const toward = (c) => {
    const l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    const g = knee > 0 && l > knee ? Math.sqrt(knee / l) : 1;
    if (sat === 1 && g === 1) return c;
    return c.map((v) => (l + (v - l) * sat) * g);
  };
  ctx.animate((t) => {
    let st = null;
    for (const e of evs) {
      if (t < e.t) break;
      if (t <= e.t + e.dur) { st = C.at(e, t - e.t); break; }
    }
    for (const m of meshes) m.visible = !!st;
    if (!st) return;
    C.apply(model, st);
    model.root.rotation.y = st.h;
    const { s, el } = floorScale(Fl, st.y);
    const ppu = s / BL, half = RT / 2 / ppu;
    Object.assign(cam, { left: -half, right: half, top: half, bottom: -half });
    cam.updateProjectionMatrix();
    const px = st.x * W, py = st.y * H, bpx = s;
    // the light where it is: the defocused plate above it and on the floor around it; the key light as bright as the
    // floor there is lit (a frog in the lantern's pool of light, or in the shade beside the ocelot). ambientSat pulls
    // that light toward gray at the same brightness: the spruce cabin's orange planks and logs turned its white rabbit
    // tan-brown beside the painting's own white wolf
    hemi.color.setRGB(...toward(avg(px + ax0 * bpx, py + ay0 * bpx, px + ax1 * bpx, py + ay1 * bpx)));
    const gnd = avg(px + gx0 * bpx, py + gy0 * bpx, px + gx1 * bpx, py + gy1 * bpx);
    hemi.groundColor.setRGB(...toward(gnd));
    const lum = 0.2126 * gnd[0] + 0.7152 * gnd[1] + 0.0722 * gnd[2];
    key.intensity = keyI * Math.min(opts.keyMax ?? 1.6, Math.max(0.35, lum / (opts.keyRef ?? 0.06)));
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.autoClear = false;
    if (rtR) {
      // the floor as a mirror: the camera mirrored below it, looking up at the mirrored view center (flipped back when
      // it is drawn)
      cam.position.set(0, -(CY + Math.sin(el) * 300), Math.cos(el) * 300);
      cam.lookAt(0, -CY, 0);
      draw(rtR);
    }
    cam.position.set(0, CY + Math.sin(el) * 300, Math.cos(el) * 300);
    cam.lookAt(0, CY, 0);
    draw(rt);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    // the floor point is CY*cos(el) units below the view's center
    const ay = RT / 2 + CY * Math.cos(el) * ppu;
    mat.uniforms.uBox.value.set(px - RT / 2, py - ay, RT, RT);
    const foot = [st.x, 1 - (py + 2) / H];
    mat.uniforms.uFootUv.value.set(...foot);
    smat.uniforms.uFootUv.value.set(...foot);
    if (rmat) {
      // the mirrored view, sampled flipped: its floor point is on the same row as the creature's, so the same box; a
      // height h above the floor shows h cos(el) below the feet in the mirror
      rmat.uniforms.uBox.value.set(px - RT / 2, py - ay, RT, RT);
      rmat.uniforms.uFootUv.value.set(...foot);
      rmat.uniforms.uFootT.value = ay / RT;
      rmat.uniforms.uFade.value = ((opts.reflectFade ?? 0.6) * s * Math.cos(el)) / RT + 1e-3;
    }
    // contact shadow: its footprint on the floor, fainter and smaller while it is in the air
    const sh = Math.abs(Math.sin(st.h)), ch = Math.abs(Math.cos(st.h)), up = Math.min(1, st.arc / (0.6 * BL));
    const [L, Wd] = C.footprint(st);
    const rx = (sh * L + ch * Wd) * 0.5 * ppu * (1 - 0.25 * up), ry = ((ch * L + sh * Wd) * 0.5 * ppu * Math.sin(el) + 3) * (1 - 0.25 * up);
    smat.uniforms.uBox.value.set(px - rx, py - ry, 2 * rx, 2 * ry);
    smat.uniforms.uShadow.value = (opts.shadow ?? 0.45) * (1 - 0.6 * up);
  });
  return quad;
}
