// A happy ghast far off, drifting past the window now and then (timeline event 'ghast'; Truman 2026-11-22, the
// Enchanter's Tower: one of the movers he picked for the room). Silent.
//
// An original blocky ghast built from boxes in code (boxart.js), never generated: a white cube 16 units across with a
// smiling face, faint pink gills on its sides and nine short tentacles in a 3 x 3 grid under it, each swinging on its
// own phase with its tip lagging its root. It drifts like a balloon: slow, bobbing, leaning a little into its way, its
// tentacles trailing; about halfway across it slows, turns to look in at the tower, hovers a few seconds and turns back
// on its way. Rendered every frame into its own texture from the camera's side of it and composited onto the plate:
// the low sun behind it puts a warm rim on its edges toward the sun, the sky lights its top, the lake bounces warm light
// up under it, and the side it shows the tower is in its own shade, lit by the evening sky behind the camera. Hazed a
// little toward the air behind it; drawn only out in the open view and in front of what is farther (the plate's depth),
// so it comes and goes behind the window's walls.
//
// opts: { plate, sun: [x, y] (px at 4K, where the sunlight comes from: [2195, 785]), horizon (px, eye level: 900),
//   focal (px, 1600), disp (its plate disparity: hidden by what is nearer, 0.02), haze (0.15), ambient (hemisphere,
//   1.0), skyBox ([x0, y0, x1, y1] px: the open sky that lights its top), skyGain (0.8), bounce ([x0, y0, x1, y1] px:
//   the lake that lights it from below), key { color, intensity }, fill { color, intensity }, rim { color, strength }
//   (the sun through its edges that face it: '#ffc27a', 0.9), renderOrder (6) }.
//   Timeline `ghast`: { perHour, minGap, startAfter, first, dur: [s, s], span: [px, px] (the body's width), rows:
//   [y0, y1], from: [x0, x1] (the far ends, out of sight), hold: [s, s] }.
import * as THREE from 'three';
import { plateTexture, imagePixels, boxMean, PREMUL } from './overlay.js';
import { boxMaterials } from './boxart.js';
import { smooth } from './util.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;
const C = {
  body: '#f4f2ed', under: '#d6d1c9', eye: '#1d1f2b', glint: '#5d6274', cheek: '#f1b4c3', mouth: '#3b2c33',
  gill: '#eec1cc', tent: '#ebe8e2', tip: '#d4cfc7',
};
// the tentacles' roots (units, under the body) and lengths: short and stubby, a little uneven
const ROOTS = [[-5, -5], [0, -5], [5, -5], [-5, 0], [0, 0], [5, 0], [-5, 5], [0, 5], [5, 5]];
const LENS = [[4, 3], [5, 3], [4, 2], [5, 3], [6, 3], [4, 3], [4, 2], [5, 3], [4, 3]];

// the face on the front (+z): dark eyes with a soft glint inside their top corner (a white one notched the eye's outline
// and the eyes read as slanted), pink cheeks and a small smile, on a 16 x 16 grid (column, row from the top left)
function face(c, r) {
  const eye = (c0) => c >= c0 && c <= c0 + 1 && r >= 6 && r <= 8;
  if (eye(4) || eye(10)) return (c === 4 || c === 10) && r === 6 ? C.glint : C.eye;
  if (r === 10 && (c === 3 || c === 4 || c === 11 || c === 12)) return C.cheek;
  if ((r === 10 && (c === 6 || c === 9)) || (r === 11 && (c === 7 || c === 8))) return C.mouth;
  return null;
}

function buildGhast() {
  const T = 1;                    // texels per unit: 16 per side, like a mob's own texture
  const paint = (p, f) => {
    if (f === 3) return C.under;
    if (f === 4) return face(Math.floor(p[0] + 8), Math.floor(8 - p[1])) ?? C.body;
    // gills: three faint pink stripes on each side, toward the front and low
    if ((f === 0 || f === 1) && p[1] < -0.5 && p[1] > -5.5 && [2.5, 4.5, 6.5].some((z) => Math.abs(p[2] - z) < 0.5)) return C.gill;
    return C.body;
  };
  const root = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(16, 16, 16), boxMaterials([16, 16, 16], T, paint, 71, { grain: 0.07, roughness: 0.95 }));
  root.add(body);
  const tents = ROOTS.map(([x, z], i) => {
    const [l1, l2] = LENS[i];
    const g1 = new THREE.Group();
    g1.position.set(x, -8, z);
    const m1 = new THREE.Mesh(new THREE.BoxGeometry(2, l1, 2), boxMaterials([2, l1, 2], T, () => C.tent, 72 + i, { grain: 0.08 }));
    m1.position.y = -l1 / 2;
    g1.add(m1);
    const g2 = new THREE.Group();
    g2.position.y = -l1;
    const m2 = new THREE.Mesh(new THREE.BoxGeometry(2, l2, 2), boxMaterials([2, l2, 2], T, () => C.tip, 90 + i, { grain: 0.08 }));
    m2.position.y = -l2 / 2;
    g2.add(m2);
    g1.add(g2);
    root.add(g1);
    return { g1, g2, ph: 0.9 * i + (i % 3) * 0.4 };
  });
  return { root, tents };
}

// Where it is tau s into its pass: { x, y (px, the body's center), yaw (0 = facing the tower, + turned toward screen
// right), speed (px/s), look (0..1: turned to look in) }. It slows into its hover about halfway (`at` of its way), holds
// for `hold` s, and speeds up again; 1.5 times its mean speed at both ends, where the walls hide it.
export function ghastAt(ev, tau) {
  const D = ev.dur, hold = ev.hold ?? 0, sp = ev.at ?? 0.5;
  const T = Math.max(1, D - hold), T1 = T * sp, T2 = T - T1;
  const f = (x) => 1.5 * x - 0.5 * x * x * x;
  let s, v;
  if (tau < T1) {
    const x = Math.max(0, tau / T1);
    s = sp * f(x);
    v = (sp * 1.5 * (1 - x * x)) / T1;
  } else if (tau < T1 + hold) {
    s = sp;
    v = 0;
  } else {
    const x = Math.min(1, (tau - T1 - hold) / T2);
    s = sp + (1 - sp) * (1 - f(1 - x));
    v = ((1 - sp) * 1.5 * (1 - (1 - x) * (1 - x))) / T2;
  }
  const dir = ev.x1 >= ev.x0 ? 1 : -1;
  const u = (ev.span ?? 110) / 16;
  const ph = ((ev.seed ?? 1) % 997) / 997 * TAU;
  const bob = u * (0.7 * Math.sin((TAU * tau) / 4.8 + ph) + 0.5 * Math.sin((TAU * tau) / 13.1 + 2 * ph));
  const x = (ev.x0 + (ev.x1 - ev.x0) * s) * W;
  const y = (ev.y0 + (ev.y1 - ev.y0) * s - (ev.arc ?? 0) * 4 * s * (1 - s)) * H + bob;
  // turned a little toward the tower on its way, so its face half shows; fully toward it while it hovers
  const look = smooth((tau - (T1 - 3.2)) / 3.2) * (1 - smooth((tau - (T1 + hold - 0.6)) / 3.4));
  const yaw = dir * (Math.PI / 2 - 0.55) * (1 - look);
  return { x, y, yaw, dir, speed: v * Math.abs(ev.x1 - ev.x0) * W, look, s, vis: Math.min(1, tau / 1.2, (D - tau) / 1.2) };
}

// The pose of its parts tau s into its pass: the body's lean and roll (rad) and each tentacle's swing at its root and its
// tip (rad about x and z). Pure, for the tests.
export function ghastPose(ev, tau, st = ghastAt(ev, tau)) {
  const trail = Math.min(1, st.speed / 30);          // the tentacles trail behind it when it moves
  const lean = 0.05 * trail;
  const tents = ROOTS.map((_, i) => {
    const ph = 0.9 * i + (i % 3) * 0.4;
    const a = 0.2 * Math.sin(TAU * 0.46 * tau + ph) + 0.28 * trail;
    const b = 0.12 * Math.sin(TAU * 0.31 * tau + 1.7 * ph);
    return { x1: a, z1: b, x2: 0.7 * (0.2 * Math.sin(TAU * 0.46 * tau + ph - 0.9) + 0.2 * trail), z2: 0.6 * b };
  });
  return { lean, tents };
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
const ghastFrag = /* glsl */ `
uniform sampler2D tGhast, tLights, tDepth, tBlur, tMask;
uniform float uDisp, uHaze, uVis, uTexel;
uniform vec2 uSunDir;      // toward the sun on screen (px axes, y down), unit
uniform vec3 uRim;         // the sun's rim light on the edges that face it
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec2 st = vec2(vT.x, 1.0 - vT.y);
  vec4 c = texture2D(tGhast, st);   // premultiplied over a clear target
  if (c.a < 0.002) discard;
  float outdoor = texture2D(tLights, vUv).g;
  float dp = texture2D(tDepth, vUv).r; dp *= dp;
  float sky = texture2D(tMask, vUv).r;
  float front = max(sky, 1.0 - smoothstep(uDisp * 1.06 + 0.002, uDisp * 1.14 + 0.004, dp));
  float k = outdoor * front * uVis;
  if (k <= 0.002) discard;
  // backlit: where the body ends toward the sun, the low sun shines through its pale edge
  vec2 d = vec2(uSunDir.x, -uSunDir.y) * uTexel;
  float a1 = texture2D(tGhast, st + d * 2.0).a, a2 = texture2D(tGhast, st + d * 5.0).a;
  float rim = c.a * (1.0 - 0.5 * (a1 + a2));
  vec3 lit = c.rgb + uRim * rim;
  vec3 air = texture2D(tBlur, vUv).rgb;
  gl_FragColor = vec4(mix(lit, air * c.a, uHaze), c.a) * k;
}`;

export async function ghastLayer(ctx, opts) {
  const R = ctx.renderer;
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'ghast');
  if (!R || !evs.length) return null;
  const model = buildGhast();
  const scene3 = new THREE.Scene();
  scene3.add(model.root);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 1.0);
  scene3.add(hemi);
  const key = new THREE.DirectionalLight(opts.key?.color ?? '#ffc48a', opts.key?.intensity ?? 3.2);
  const fill = new THREE.DirectionalLight(opts.fill?.color ?? '#aab2e2', opts.fill?.intensity ?? 0.55);
  scene3.add(key, fill);
  const focal = opts.focal ?? 1600, cx = W / 2, cy = opts.horizon ?? 900;
  const [sunX, sunY] = opts.sun ?? [2195, 785];
  key.position.set(sunX - cx, cy - sunY, -focal).normalize().multiplyScalar(100);
  fill.position.set(0.15, 0.45, 1).normalize().multiplyScalar(100);
  // one texel per screen pixel at its biggest: 30 units across, centered 3 units under the body's center (the body turned
  // reaches 11.3 units out, the longest tentacle 17 down)
  const CY = -3;
  const maxSpan = Math.max(...evs.map((e) => e.span ?? 110));
  const RT = Math.min(512, Math.ceil((30 * maxSpan) / 16 / 16) * 16);
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 400);
  const [tLights, tDepth, tBlur, tMask] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'depth8.png'),
    plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'masks.png'),
  ]);
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  // the open sky above lights its top, the lake under it its underside
  const sky = avg(...(opts.skyBox ?? [1650, 150, 2350, 450])).map((v) => v * (opts.skyGain ?? 0.8));
  const lake = avg(...(opts.bounce ?? [1500, 1100, 2500, 1330]));
  const mat = new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: ghastFrag, ...PREMUL,
    uniforms: {
      uBox: { value: new THREE.Vector4() }, tGhast: { value: rt.texture }, tLights: { value: tLights }, tDepth: { value: tDepth },
      tBlur: { value: tBlur }, tMask: { value: tMask }, uDisp: { value: opts.disp ?? 0.02 }, uHaze: { value: opts.haze ?? 0.15 },
      uVis: { value: 0 }, uTexel: { value: 1 / RT }, uSunDir: { value: new THREE.Vector2(0, 1) },
      uRim: { value: new THREE.Color(opts.rim?.color ?? '#ffc27a').multiplyScalar(opts.rim?.strength ?? 0.9) },
    },
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.frustumCulled = false;
  quad.visible = false;
  quad.renderOrder = opts.renderOrder ?? 6;
  quad.userData.noAO = true;
  ctx.add(quad);
  const prevClear = new THREE.Color();
  ctx.animate((t) => {
    const ev = evs.find((e) => t >= e.t && t <= e.t + e.dur);
    quad.visible = !!ev;
    if (!ev) return;
    const tau = t - ev.t;
    const st = ghastAt(ev, tau);
    const pose = ghastPose(ev, tau, st);
    // leaning forward along its own heading as it moves (about its own x axis, after the yaw); the tentacles swing back
    model.root.rotation.set(pose.lean, st.yaw, 0, 'YXZ');
    model.tents.forEach((tn, i) => {
      const p = pose.tents[i];
      tn.g1.rotation.set(p.x1, 0, p.z1);
      tn.g2.rotation.set(p.x2, 0, p.z2);
    });
    const ppu = (ev.span ?? 110) / 16, half = RT / 2 / ppu;
    Object.assign(cam, { left: -half, right: half, top: half, bottom: -half });
    cam.updateProjectionMatrix();
    // seen from the camera: the ray to it, a little from below while it is above eye level
    const n = new THREE.Vector3(cx - st.x, st.y - cy, focal).normalize();
    cam.position.set(0, CY, 0).addScaledVector(n, 200);
    cam.up.set(0, 1, 0);
    cam.lookAt(0, CY, 0);
    hemi.color.setRGB(...sky);
    hemi.groundColor.setRGB(...lake);
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, cam);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    // the box's center is the view's center, CY units under the body's center (foreshortened by the upward look)
    const below = -CY * ppu * Math.sqrt(1 - n.y * n.y);
    mat.uniforms.uBox.value.set(st.x - RT / 2, st.y + below - RT / 2, RT, RT);
    mat.uniforms.uVis.value = st.vis;
    mat.uniforms.uSunDir.value.set(sunX - st.x, sunY - st.y).normalize();
  });
  return quad;
}
