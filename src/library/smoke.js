// Chimney smoke for plate scenes: a plume rising from a chimney or stove pipe in the plate, bending over in the
// breeze, widening and thinning as it drifts off. It is a train of soft puffs released every 0.2 s from the
// chimney top, each following the same physics as a pure function of time: a buoyant rise that slows over a few
// seconds, picked up by the scene's wind and gust flurries (the exact drift integrals the rain and leaves use),
// a slow meander of the release (the plume snakes as the draft wavers), and turbulent spreading. Each puff
// carries its own billowy texture, so the plume tears into wisps as it grows. It is lit by the light around it
// (the blurred plate: warm in front of a lit window, bluish against the night sky, brighter in a lightning flash),
// sits at the chimney's depth (anything nearer in depth8.png covers it: poles, eaves, lanterns), and thin dark
// things crossing in front (power lines, branches: much darker than their surroundings) stay crisp over it.
//
// opts: { plate, sources: [{ x, y (the chimney top's center, image coords 0..1), w: chimney width (m, 0.5), ppm:
//   px per m at the chimney (default from its disparity: 1990 x disp, the ramen alley's pole calibration), rise
//   (m/s, 1.0), drift: breeze carrying it (m/s, +right, 0.5), spread (m/s, 0.06), life (s, 10: fading beyond its
//   dilution), opacity (0.7), density: optical depth at the chimney top (1.8) }], wind (scene wind), renderOrder (6) }
// Each puff's amount is the plume's optical depth there times its spacing over its width, so the sum along the
// plume is independent of the release rate; the depth falls as 1/width (the smoke dilutes as it spreads).
import * as THREE from 'three';
import { flashAt, trackAt, windAt, windDrift, flurryDrift, flurryWind } from './timeline.js';
import { plateTexture, imagePixels, PREMUL, GLSL_COMMON } from './overlay.js';

const W = 3840, H = 2160;
const N = 160;         // puff slots per plume
const DT = 0.1;        // seconds between puffs
const TMAX = 16;       // a puff's life (it has thinned to nothing by then)

const vert = /* glsl */ `
uniform vec4 uBox;     // x0, y0, x1, y1 px (y down)
varying vec2 vPx, vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vec2 p = mix(uBox.xy, uBox.zw, vec2(q.x, 1.0 - q.y));
  vPx = p;
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tBlur, tPlate, tDepth, tLights;
uniform vec4 uP[${N}];     // puff center x, y (px), sigma (px), amount
uniform vec4 uQ[${N}];     // noise angle, seed, stretch along the drift, unused
uniform int uN;
uniform float uD0, uOpacity, uFlash;
varying vec2 vPx, vUv;
void main() {
  float dens = 0.0;
  for (int i = 0; i < ${N}; i++) {
    if (i >= uN) break;
    vec4 P = uP[i];
    vec2 d = vPx - P.xy;
    float s = P.z;
    float r2 = dot(d, d) / (s * s);
    if (r2 > 9.0) continue;
    vec4 Q = uQ[i];
    float c = cos(Q.x), sn = sin(Q.x);
    vec2 l = vec2(c * d.x + sn * d.y, -sn * d.x + c * d.y) / s;
    // billows: a lumpy texture riding on the puff (its own pattern, turning slowly as it grows)
    float n = pfbm(l * 1.3 + vec2(Q.y * 37.0, Q.y * 71.0), vec2(64.0));
    dens += P.w * exp(-0.5 * r2) * (0.35 + 1.3 * smoothstep(0.25, 0.8, n));
  }
  if (dens < 0.002) discard;
  float a = (1.0 - exp(-dens)) * uOpacity;
  // what stands in front: nearer surfaces, and the indoors (the shop: lights.png G = 0)
  float dz = texture2D(tDepth, vUv).r;
  a *= 1.0 - smoothstep(uD0 * 1.06 + 0.01, uD0 * 1.12 + 0.02, dz);
  a *= texture2D(tLights, vUv).g;
  // thin dark things in front (wires, twigs): much darker than the light around them
  vec3 bg = texture2D(tBlur, vUv).rgb, pl = texture2D(tPlate, vUv).rgb;
  float Lb = dot(bg, vec3(0.2126, 0.7152, 0.0722)), Lp = dot(pl, vec3(0.2126, 0.7152, 0.0722));
  a *= 1.0 - smoothstep(0.45, 0.7, 1.0 - Lp / max(Lb, 1e-4));
  if (a < 0.002) discard;
  // lit by the light around it, a little greyer than what is behind it
  vec3 col = mix(vec3(Lb), bg, 0.5) * 1.7 + 0.012;
  col *= 1.0 + 0.6 * uFlash;
  gl_FragColor = vec4(col * a, a);
}`;

// smooth seeded wobble of time t (-1..1): three incommensurate sines
const wob = (t, s) => 0.5 * Math.sin(2 * Math.PI * t / 7.3 + s) + 0.3 * Math.sin(2 * Math.PI * t / 13.1 + 2.1 * s) + 0.2 * Math.sin(2 * Math.PI * t / 29.7 + 3.7 * s);
const hash = (k, s) => { let x = Math.imul((k | 0) ^ Math.imul(s | 0, 0x9e3779b1), 0x85ebca6b); x ^= x >>> 13; x = Math.imul(x, 0xc2b2ae35); x ^= x >>> 16; return (x >>> 0) / 4294967296; };

export async function smokeLayer(ctx, opts) {
  const srcs = opts.sources ?? [];
  if (!srcs.length) return null;
  const [tBlur, tPlate, tDepth, tLights] = await Promise.all([plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'plate.png', { srgb: true }),
    plateTexture(opts.plate, 'depth8.png'), plateTexture(opts.plate, 'lights.png')]);
  const dep = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
  const d8 = (x, y) => (dep ? dep.data[(Math.min(dep.height - 1, Math.round(y * (dep.height - 1))) * dep.width + Math.min(dep.width - 1, Math.round(x * (dep.width - 1)))) * 4] / 255 : 0.1);
  const wv = opts.wind ?? {};
  const w = { mean: wv.mean ?? 0, gust: wv.gust ?? 0, gustCycles: Math.max(1, Math.round(wv.gustCycles ?? 5)), fronts: wv.fronts ?? 0.6, loop: ctx.loopSeconds };
  const tl = ctx.timeline;
  const plumes = srcs.map((s, si) => {
    // the chimney's own depth, just under its top (its body)
    const D0 = d8(s.x, s.y + 6 / H);
    const ppm = s.ppm ?? 1990 * D0 * D0;
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag, ...PREMUL,
      uniforms: {
        tBlur: { value: tBlur }, tPlate: { value: tPlate }, tDepth: { value: tDepth }, tLights: { value: tLights },
        uP: { value: Array.from({ length: N }, () => new THREE.Vector4()) }, uQ: { value: Array.from({ length: N }, () => new THREE.Vector4()) },
        uN: { value: 0 }, uD0: { value: D0 }, uOpacity: { value: s.opacity ?? opts.opacity ?? 0.7 }, uFlash: { value: 0 }, uBox: { value: new THREE.Vector4() },
      },
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 6;
    mesh.userData.noAO = true;
    ctx.add(mesh);
    return {
      mesh, mat, ppm, x0: s.x * W, y0: s.y * H, seed: 977 * (si + 1) + 13, sig0: 0.45 * (s.w ?? 0.5), rise: s.rise ?? 1.0, drift: s.drift ?? 0.5,
      spread: s.spread ?? 0.06, life: s.life ?? 10, density: s.density ?? 1.8,
    };
  });
  ctx.animate((t) => {
    const fl = flashAt(tl, t).flash;
    for (const P of plumes) {
      const { mat, ppm } = P, U = mat.uniforms;
      const kHi = Math.floor(t / DT), kLo = Math.max(0, kHi - N + 1);
      const tauR = 2.5, tauU = 1.5;
      const pts = [];
      for (let k = kHi; k >= kLo; k--) {
        const te = k * DT, tau = t - te;
        if (tau < 0 || tau > TMAX) continue;
        const gk = trackAt(tl?.track, 'wind', te);
        // horizontal: the breeze plus the scene's wind and gusts, picked up over ~1.5 s after it leaves the chimney
        const u0 = P.drift + windAt(w, te, P.x0 / W, gk) + flurryWind(tl, te);
        const X = P.drift * tau + windDrift(w, te, t, P.x0 / W, gk) + flurryDrift(tl, te, t) - u0 * tauU * (1 - Math.exp(-tau / tauU));
        // vertical: buoyancy carries it up fast at first; a stronger breeze bends it over
        const flat = 1 / (1 + 0.6 * Math.abs(u0));
        const Y = flat * P.rise * tauR * (1 - Math.exp(-tau / tauR)) + 0.1 * tau;
        // the release wavers (the plume snakes) and each puff is knocked about by eddies its own size
        const sig = P.sig0 + P.spread * tau;
        const mx = tau * 0.08 * wob(te, P.seed), my = tau * 0.05 * wob(te + 50, P.seed + 1);
        const jx = sig * 0.35 * (hash(k, P.seed) - 0.5), jy = sig * 0.35 * (hash(k, P.seed + 7) - 0.5);
        pts.push({ k, tau, x: P.x0 + (X + mx + jx) * ppm, y: P.y0 - (Y + my + jy) * ppm - 0.3 * P.sig0 * ppm, sig });
      }
      let n = 0, bx0 = 1e9, by0 = 1e9, bx1 = -1e9, by1 = -1e9;
      for (let i = 0; i < pts.length && n < N; i++) {
        const q = pts[i], spx = q.sig * ppm;
        // spacing to its neighbours along the plume (px)
        const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
        const gap = Math.max(0.5, 0.5 * (Math.hypot(q.x - a.x, q.y - a.y) + Math.hypot(q.x - b.x, q.y - b.y)));
        // the burn varies over minutes and puff to puff; the smoke dilutes as it spreads and fades with age
        const burn = 0.8 + 0.2 * wob(q.k * DT / 9, P.seed + 3);
        const rho = P.density * burn * (0.7 + 0.6 * hash(q.k, P.seed + 11)) * Math.min(1, q.tau / 0.25) * (P.sig0 / q.sig) * Math.exp(-q.tau / P.life);
        const amt = rho * Math.min(gap, 2 * spx) / (spx * 2.5066);
        if (rho < 0.01) continue;
        U.uP.value[n].set(q.x, q.y, spx, amt);
        U.uQ.value[n].set(6.2832 * hash(q.k, P.seed + 5) + 0.15 * q.tau, hash(q.k, P.seed + 9), 1, 0);
        bx0 = Math.min(bx0, q.x - 3 * spx); bx1 = Math.max(bx1, q.x + 3 * spx); by0 = Math.min(by0, q.y - 3 * spx); by1 = Math.max(by1, q.y + 3 * spx);
        n++;
      }
      U.uN.value = n;
      U.uFlash.value = fl;
      U.uBox.value.set(Math.max(0, bx0), Math.max(0, by0), Math.min(W, bx1), Math.min(H, by1));
      P.mesh.visible = n > 0;
    }
  });
  return plumes.map((p) => p.mesh);
}
