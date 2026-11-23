// Waves breaking on the far rocks (scene.json layers: { type: 'surf' }). The plate's surf (plate.js, plate_fx.surf)
// brings the painted foam in with each wave of the timeline; on the tide pool that was all a wave did, and Truman saw no
// waves on the far rocks while the surf roared (2026-11-05). This layer draws what a wave does that the painting has no
// pixels for, with the same waves (timeline 'surf' events) on the same timing as the plate's foam and the sound
// (cozy/audio/ambience.py surf_env):
//   spray: thrown up off each rock the wave reaches: a plume of blobs flying up from behind the rock and falling back,
//          leaving a mist that drifts off with the wind and thins. A wave throws spray only off the rocks it is big
//          enough for (each spot's `min`), so the sets break on more of them.
//   wash:  the white water it runs in with, sliding shoreward between the rocks and breaking up into lace as it thins,
//          with the swell's darker face running in just ahead of it.
// Both are painted shapes, not particles: flat foam color with soft edges, billows that ride with the spray and the
// paper's grain fixed to the page. Hidden behind the rocks (the spray rises behind them), the characters and what they
// hold, and anything clearly nearer than the rock in the depth map.
// Inputs from plate_prep (cozy/plate/surf.py): surf.png (shoreward, along the shore), surf_fx.png (where the wash runs,
// rock, what stands in front), surf.json (the painted foam's color, the spray spots it found on the rocks' seaward edges).
//
// opts: { plate, spots (replace surf.json's: [{ x, y (frame fractions: the middle of a rock's seaward top edge), w, h
//   (px at 4K: the stretch the wave hits, the biggest wave's spray height), min (the smallest wave strength that throws
//   spray there) }]), addSpots (more, kept with surf.json's), spray (1: opacity), wash (0.8: how white the water running
//   in gets; 0 = none), swell (0.1: how much the swell's face darkens the water), haze (0.2: toward the air behind),
//   bright (1.25: the spray against the painted foam's mean color), fx (the plate's plate_fx.surf: its timing), wind
//   (the scene's mean wind: the mist's drift) }
import * as THREE from 'three';
import { plateTexture, fetchJson, imagePixels, PREMUL, bboxQuad, GLSL_COMMON } from './overlay.js';
import { SURF } from './plate.js';

const W = 3840, H = 2160;
export const LIFE = 6;   // s a plume lasts after the wave reaches its rock (its mist the longest)
const NB = 8;            // puffs a burst throws (each leaves a mist)
const MAXB = 48;

// A deterministic hash to [0, 1).
export function h01(a, b, c, d) {
  let x = Math.imul(a | 0, 0x9e3779b1) ^ Math.imul((b + 0x7f4a7c15) | 0, 0x85ebca6b) ^ Math.imul((c + 0x165667b1) | 0, 0xc2b2ae35) ^ Math.imul((d + 0x27d4eb2f) | 0, 0x2545f491);
  x ^= x >>> 15; x = Math.imul(x, 0x2c1b3c6d); x ^= x >>> 12; x = Math.imul(x, 0x297a2d39); x ^= x >>> 15;
  return (x >>> 0) / 4294967296;
}
const waveSeed = (e) => Math.round(e.t * 1000) | 0;

// When a wave reaches a point of the zone (s shoreward, along 0..1 left to right): the plate shader's timing (it breaks
// at the zone's far edge at e.t - fx.lead, crosses it in fx.travel s and peels along it in fx.peel s, in its own direction).
export function arrival(e, s, along, fx) {
  return e.t - (fx.lead ?? 0) + s * fx.travel + (e.peel > 0 ? along : 1 - along) * fx.peel;
}

// Shoreward (0 at the zone's far edge, 1 at its near edge) and along the shore (0 left, 1 right) at a px, from surf.json's
// edges: the same coordinates as surf.png's R and G (cozy/plate/surf.py shoreward), which the CPU can't read back (the
// map's alpha is the painted foam, and a canvas drops the color under zero alpha).
export function shoreAt(edges, x, y) {
  const i = Math.min(edges.top.length - 1, Math.max(0, Math.round(x / edges.step)));
  const s = (y - edges.top[i]) / Math.max(edges.bot[i] - edges.top[i], 1);
  const along = (x - edges.x0) / Math.max(edges.x1 - edges.x0, 1);
  return { s: Math.min(1, Math.max(0, s)), along: Math.min(1, Math.max(0, along)) };
}

// The spray a wave throws off a spot tau s after it reaches it: [[x, y, r, a, tx, ty, kind], ...] (px at 4K, y down),
// each a short streak from its tail (tx, ty) to its head (x, y), radius r. kind 0 is the spray's body: the crest heaped
// white against the rock's face as the wave hits, and a burst of puffs that leap up together from behind the rock, fan
// out and billow as they rise (one mass, not columns: jets drawn as long streaks read as white fingers, and Truman found
// them fake, 2026-11-05); each puff's tail is where it was a moment before, so a fast rise blurs as a shutter would.
// kind 1 is its mist: past the top each puff breaks up into a veil that hangs, drifts off with the wind and thins.
// spot: { x, y (px), w, h (px), min }; k: the spot's index; wind: px/s the mist drifts.
export function plume(spot, e, tau, k, wind = 8, out = []) {
  if (tau <= 0 || tau > LIFE || e.amp < spot.min) return out;
  const str = 0.3 + 0.7 * Math.min(1, (e.amp - spot.min) / Math.max(0.05, 0.95 - spot.min));
  const g = (9.8 * spot.h) / 3.2;   // px/s^2: the biggest wave's spray goes about 3 m up
  const sd = waveSeed(e);
  const cr = Math.min(1, tau / 0.12) * Math.exp(-Math.max(0, tau - 0.3) / 0.4);
  if (cr > 0.02) {
    const hy = spot.h * str * 0.16 * Math.min(1, tau / 0.3);
    out.push([spot.x + spot.w * 0.32, spot.y - hy, spot.w * 0.17 * (0.8 + 0.4 * str), 0.95 * cr, spot.x - spot.w * 0.32, spot.y - hy * 0.4, 0]);
  }
  for (let j = 0; j < NB; j++) {
    const R = (c) => h01(sd, k, j, c);
    // most of the burst near the middle of the face it hits
    const off = (R(1) - 0.5) * (0.45 + 0.55 * R(9));
    const t1 = tau - (0.22 * (0.5 + off * e.peel) + 0.1 * R(2));
    if (t1 <= 0) continue;
    const hj = spot.h * str * (0.35 + 0.65 * R(3));
    const v0 = Math.sqrt(2 * g * hj), tUp = v0 / g;
    const x0 = spot.x + off * spot.w * 0.9;
    const vx = ((off * 1.1 + (R(4) - 0.5) * 0.5) * spot.w * 0.45) / Math.max(tUp, 0.25) + wind * 0.3;
    const r0 = spot.w * (0.07 + 0.05 * R(5)) * (0.75 + 0.25 * str);
    // up as thrown water does, then the puff hangs: it sinks a little with drag and drifts off
    const pos = (u) => {
      if (u <= tUp) return [x0 + vx * u, spot.y - (v0 * u - 0.5 * g * u * u)];
      const s = u - tUp;
      return [x0 + vx * tUp + (vx * 0.35 + wind) * s, spot.y - hj + 0.12 * hj * (1 - Math.exp(-s / 0.8)) + 4 * s];
    };
    const [hx, hy] = pos(t1), [tx, ty] = pos(Math.max(0, t1 - 0.07));
    const grow = 1 + (1.3 * Math.min(t1, tUp)) / tUp + 0.6 * Math.max(0, t1 - tUp);
    const body = Math.min(1, t1 / 0.06) * (t1 < tUp ? 1 : Math.exp(-(t1 - tUp) / 0.45));
    if (body > 0.02) out.push([hx, hy, r0 * grow, body, tx, ty, 0]);
    const ms = t1 - 0.6 * tUp;
    if (ms > 0) {
      const a = 0.42 * str * Math.min(1, ms / 0.4) * Math.exp(-ms / 1.8);
      if (a > 0.01) out.push([hx + (R(7) - 0.5) * r0, hy + (R(8) - 0.5) * r0 * 0.6, r0 * grow * 1.35 + 14 * ms, a, hx - wind * 0.3 - 4, hy + 2, 1]);
    }
  }
  return out;
}

// The waves (sorted by t) a moment can still see: broken within `back` s before t (binary search).
function since(waves, t, back) {
  let lo = 0, hi = waves.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (waves[m].t < t - back) lo = m + 1; else hi = m; }
  const out = [];
  for (let i = lo; i < waves.length && waves[i].t <= t + 1; i++) out.push(waves[i]);
  return out;
}

const vert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const sprayFrag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tFx, tDepth, tBlur;
uniform vec4 uB[${2 * MAXB}];   // per streak: head x, y, radius, alpha; tail x, y, kind (0 spray, 1 mist)
uniform int uN;
uniform vec3 uFoam;
uniform vec4 uSpot;       // x, y (px: the rock's top edge), h (px), the rock's depth
uniform vec2 uOff;        // the billows ride up and drift with the spray
uniform float uHaze, uAlpha, uSpat;
varying vec2 vUv;
void main() {
  vec2 P = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
  vec4 fx = texture2D(tFx, vUv);
  float d = texture2D(tDepth, vUv).r;
  // behind the rock it is thrown up from, the characters and what they hold, and anything clearly nearer
  float vis = (1.0 - fx.g) * (1.0 - fx.b) * (1.0 - smoothstep(uSpot.w * 1.15 + 0.015, uSpot.w * 1.3 + 0.03, d));
  if (vis <= 0.0) discard;
  // billowing edges: the shapes are pushed about by a noise that rides with the spray, so the puffs merge into one
  // ragged mass rather than a row of round heads
  vec2 Q = (P - uOff) / 26.0;
  vec2 wv = vec2(pnoise(Q + vec2(3.1, 0.0), vec2(4096.0)), pnoise(Q + vec2(0.0, 7.7), vec2(4096.0))) - 0.5;
  vec2 Q2 = (P - uOff) / 8.0;
  vec2 wv2 = vec2(pnoise(Q2 + vec2(1.7, 5.3), vec2(4096.0)), pnoise(Q2 + vec2(9.2, 2.4), vec2(4096.0))) - 0.5;
  vec2 Pw = P + wv * 30.0 + wv2 * 9.0;
  float dense = 0.0, mist = 0.0;
  for (int i = 0; i < ${MAXB}; i++) {
    if (i >= uN) break;
    vec4 b = uB[2 * i], c = uB[2 * i + 1];
    vec2 ab = c.xy - b.xy, pa = Pw - b.xy;
    float h = clamp(dot(pa, ab) / max(dot(ab, ab), 1e-3), 0.0, 1.0);
    vec2 q = (pa - ab * h) / b.z;
    float f = max(0.0, 1.0 - dot(q, q));
    if (c.z < 0.5) dense += b.w * f * f; else mist += b.w * f;
  }
  if (dense + mist < 0.003) discard;
  float n = pfbm((P - uOff) / 11.0, vec2(4096.0));
  // while it leaps its edges streak along its flight like flung water; once it hangs they billow
  float ns = pfbm((P - uOff) / vec2(4.0, 14.0) + vec2(17.0, 0.0), vec2(4096.0));
  float ne = mix(n, ns, 0.7 * uSpat);
  float n2 = pnoise((P - uOff) / 3.5, vec2(4096.0));
  float grain = pnoise(P / 1.6, vec2(4096.0));
  float core = dense * (0.55 + 0.9 * ne);
  float body = smoothstep(0.1, 0.7, core);
  // drops flung off its edge while it leaps
  float fringe = smoothstep(0.02, 0.15, dense) * (1.0 - smoothstep(0.1, 0.4, core));
  float drops = step(0.8, n2) * fringe * uSpat;
  float veil = 0.5 * smoothstep(0.03, 0.8, mist * (0.5 + n));
  float a = max(max(0.9 * body * (0.78 + 0.22 * n2), 0.75 * drops), veil) * (0.85 + 0.15 * grain) * vis * uAlpha;
  // where it is thin the paper's tooth breaks it up, as a dry brush leaves white on rough paper
  float tooth = smoothstep(0.3, 0.7, pnoise(P / 2.6 + vec2(11.0, 3.0), vec2(4096.0)));
  a *= mix(1.0, tooth, (1.0 - body) * 0.75);
  if (a < 0.003) discard;
  // modeled like a painted billow: lit on top and where it is thick, a cooler shade underneath and in its folds,
  // hazed toward the air behind the higher it goes
  float up = clamp((uSpot.y - P.y) / max(uSpot.z, 1.0), 0.0, 1.0);
  float lit = clamp(0.35 + 0.5 * smoothstep(0.3, 1.2, core) + 0.3 * (n - 0.5) + 0.25 * up, 0.0, 1.0);
  vec3 base = uFoam * mix(vec3(0.78, 0.82, 0.88), vec3(1.06), lit);
  vec3 col = mix(base, texture2D(tBlur, vUv).rgb, clamp(uHaze + 0.3 * up, 0.0, 0.85));
  gl_FragColor = vec4(col * a, a);
}`;

const washFrag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tSurf, tFx, tBlur;
uniform vec4 uW[4];       // the newest waves: x s since it broke at the zone's far edge, y strength, z peel direction, w its own pattern
uniform vec4 uK;          // travel, peel, decay (s), run (px the white water slides shoreward)
uniform vec3 uFoam;
uniform float uWash, uSwell, uHaze;
varying vec2 vUv;
void main() {
  vec4 sf = texture2D(tSurf, vUv);
  vec4 fx = texture2D(tFx, vUv);
  if (sf.r < 0.004 || fx.r < 0.01) discard;
  vec2 P = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
  float s = (sf.r - 0.02) / 0.98;
  float lag = pnoise(P / vec2(107.0, 61.0), vec2(4096.0));
  // foam cells about 22 x 10 px (a scale that changed with the distance sheared the pattern into thin arcs)
  const vec2 sc = vec2(22.0, 10.0);
  // water just shoreward of a rock: the wave pours around and over it there, so the white water is thickest
  vec2 px = vec2(1.0 / ${W}.0, 1.0 / ${H}.0);
  float behind = max(max(texture2D(tFx, vUv + vec2(0.0, 14.0) * px).g, texture2D(tFx, vUv + vec2(0.0, 30.0) * px).g),
                     max(texture2D(tFx, vUv + vec2(-20.0, 22.0) * px).g, texture2D(tFx, vUv + vec2(20.0, 22.0) * px).g));
  float foam = 0.0, dark = 0.0;
  for (int i = 0; i < 4; i++) {
    vec4 w = uW[i];
    if (w.y <= 0.0) continue;
    float along = w.z > 0.0 ? sf.g : 1.0 - sf.g;
    float age = w.x - s * uK.x - along * uK.y - 0.7 * lag;
    dark = max(dark, w.y * exp(-(age + 0.45) * (age + 0.45) / 0.08));
    if (age <= 0.0) continue;
    vec2 q = vec2(P.x, P.y - uK.w * (1.0 - exp(-age / 1.1)));
    float nz = pfbm(q / sc + w.w, vec2(4096.0));
    float th = mix(0.3, 0.74, 1.0 - exp(-age / 1.8));
    float lace = mix(smoothstep(th, th + 0.15, nz), smoothstep(th - 0.22, th - 0.08, nz), behind);
    foam = max(foam, w.y * smoothstep(0.0, 0.25, age) * exp(-age / uK.z) * lace);
  }
  float m = fx.r * smoothstep(0.03, 0.2, s);
  float a = clamp(foam * uWash * 1.3, 0.0, 0.88) * m;
  float ad = clamp(dark * uSwell, 0.0, 0.3) * fx.r;
  vec3 c = mix(uFoam, texture2D(tBlur, vUv).rgb, uHaze);
  float at = a + ad * (1.0 - a);
  if (at < 0.003) discard;
  gl_FragColor = vec4(c * a, at);
}`;

export async function surfLayer(ctx, opts) {
  const waves = (ctx.timeline?.events ?? []).filter((e) => e.type === 'surf').sort((a, b) => a.t - b.t);
  if (!waves.length) return null;
  const fx = { ...SURF, ...(opts.fx ?? {}) };
  const meta = await fetchJson(`/out/plates/${opts.plate}/surf.json`, { hint: 'run tools/plate_prep.py with hand.json "surf" (cozy/plate/surf.py)' });
  const [tSurf, tFx, tDepth, tBlur] = await Promise.all([
    plateTexture(opts.plate, 'surf.png'), plateTexture(opts.plate, 'surf_fx.png'),
    plateTexture(opts.plate, 'depth8.png'), plateTexture(opts.plate, 'blur.png', { srgb: true }),
  ]);
  const dp = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
  const at = (img, x, y, c) => {
    const ix = Math.min(img.width - 1, Math.max(0, Math.round((x * img.width) / W))), iy = Math.min(img.height - 1, Math.max(0, Math.round((y * img.height) / H)));
    return img.data[(iy * img.width + ix) * 4 + c] / 255;
  };
  const lin = (v) => Math.pow(v, 2.2);
  const bright = opts.bright ?? 1.25;
  const foam = new THREE.Vector3(...meta.foam.map((v) => Math.min(1, lin(v) * bright)));
  // the scene's wind (the engine hands every layer its wind object; a number works too)
  const wm = Number(typeof opts.wind === 'object' ? opts.wind?.mean : opts.wind);
  const wind = 6 + 40 * (Number.isFinite(wm) ? wm : 0.1);
  const haze = opts.haze ?? 0.2;
  const spots = [...(opts.spots ?? meta.spots ?? []), ...(opts.addSpots ?? [])].map((q) => {
    const x = q.x * W, y = q.y * H;
    // its timing just seaward of the rock (where the wave hits it), its depth the rock's own
    const { s, along } = shoreAt(meta.edges, x, y - 6);
    const d0 = Math.max(...[-0.3, 0, 0.3].map((f) => at(dp, x + f * q.w, y + 8, 0)));
    return { x, y, w: q.w, h: q.h, min: q.min ?? 0.5, s, along, d0 };
  });
  const meshes = [];
  const sprayMats = spots.map((q) => {
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: sprayFrag, ...PREMUL,
      uniforms: {
        tFx: { value: tFx }, tDepth: { value: tDepth }, tBlur: { value: tBlur },
        uB: { value: Array.from({ length: 2 * MAXB }, () => new THREE.Vector4()) }, uN: { value: 0 },
        uFoam: { value: foam }, uSpot: { value: new THREE.Vector4(q.x, q.y, q.h, q.d0) }, uOff: { value: new THREE.Vector2() },
        uHaze: { value: haze }, uAlpha: { value: opts.spray ?? 1 }, uSpat: { value: 0 },
      },
    });
    const box = [(q.x - q.w * 0.95 - 30) / W, (q.y - q.h * 1.35 - 40) / H, (q.x + q.w * 0.95 + 30 + wind * LIFE) / W, (q.y + 16) / H];
    const mesh = new THREE.Mesh(bboxQuad(box), mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 5.6;
    mesh.userData.noAO = true;
    mesh.visible = false;
    ctx.add(mesh);
    meshes.push(mesh);
    return mat;
  });
  const washOn = (opts.wash ?? 0.8) > 0;
  const washMat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: washFrag, ...PREMUL,
    uniforms: {
      tSurf: { value: tSurf }, tFx: { value: tFx }, tBlur: { value: tBlur },
      uW: { value: Array.from({ length: 4 }, () => new THREE.Vector4()) },
      uK: { value: new THREE.Vector4(fx.travel, fx.peel, fx.decay, opts.run ?? 28) },
      uFoam: { value: foam }, uWash: { value: opts.wash ?? 0.8 }, uSwell: { value: opts.swell ?? 0.1 }, uHaze: { value: haze },
    },
  });
  const wash = new THREE.Mesh(bboxQuad(meta.bbox, 0.004), washMat);
  wash.frustumCulled = false;
  wash.renderOrder = (opts.renderOrder ?? 5.6) - 0.1;
  wash.userData.noAO = true;
  wash.visible = false;
  if (washOn) ctx.add(wash);
  const reach = fx.travel + fx.peel + 1;
  ctx.animate((t) => {
    const recent = since(waves, t + (fx.lead ?? 0), LIFE + reach);
    spots.forEach((q, k) => {
      const blobs = [];
      let last = -1, lastStr = 0;
      for (const e of recent) {
        const tau = t - arrival(e, q.s, q.along, fx);
        if (tau <= 0 || tau > LIFE || e.amp < q.min) continue;
        plume(q, e, tau, k, wind, blobs);
        last = tau;
        lastStr = 0.3 + 0.7 * Math.min(1, (e.amp - q.min) / Math.max(0.05, 0.95 - q.min));
      }
      const U = sprayMats[k].uniforms;
      const n = Math.min(MAXB, blobs.length);
      for (let i = 0; i < n; i++) {
        const [hx, hy, r, a, tx, ty, kind] = blobs[i];
        U.uB.value[2 * i].set(hx, hy, r, a);
        U.uB.value[2 * i + 1].set(tx, ty, kind, 0);
      }
      U.uN.value = n;
      // the billows ride up with the spray, then drift off with its mist
      if (last >= 0) U.uOff.value.set(wind * Math.max(0, last - 0.7), -q.h * lastStr * 0.6 * Math.min(1, last / 0.7));
      // drops fly off it while it leaps, not once it hangs
      U.uSpat.value = last >= 0 ? 1 - Math.min(1, Math.max(0, (last - 0.2) / 0.7)) : 0;
      meshes[k].visible = n > 0;
    });
    if (washOn) {
      // the four newest waves (the foam of any older one has faded to nothing by the time a fifth has come)
      const U = washMat.uniforms.uW.value;
      const lead = fx.lead ?? 0;
      const live = since(waves, t + lead, 40).slice(-4).reverse();
      for (let i = 0; i < 4; i++) {
        const e = live[i];
        if (e && t + lead - e.t < 40) U[i].set(t + lead - e.t, e.amp, e.peel, (h01(waveSeed(e), 7, 7, 7) * 997) % 97);
        else U[i].set(0, 0, 0, 0);
      }
      wash.visible = live.length > 0;
    }
  });
  return wash;
}
