// A drink or soup inside a vessel the key art painted empty (user 2026-10-19: the tea cup should hold a little
// tea). The liquid's level is an ellipse the size of the rim's opening (plate_prep fits it to the rim:
// regions.json `opening`) a little smaller for a cup that narrows downward, and `depth` px lower on screen; what
// shows is where it lies inside the opening (the near wall hides the rest), so a cup a little under full shows a
// lens of tea under a sliver of the back wall. Seen at a low angle a liquid is mostly what it reflects: the warm
// light and the street behind the cup (the plate's blur above the rim, mirrored and squashed), over the dark
// body of the drink (the cup's own wall seen through it, tinted). A soft highlight of the light above, a thin
// bright meniscus where it meets the back wall, and a slow shimmer (draughts, the steam) keep it alive. Whole
// cycles per loop; the edges are as soft as the plate is there (defocus.png).
//
// opts: { plate, regions: [names] | 'kind:steam', horizon (0.45: eye-level row, 0..1), per: { <region>: { depth:
//   level below the rim (fraction of the opening's half height b, 0.55), shrink (0.96), color: linear tint of the
//   drink in the vessel's light ([0.62, 0.42, 0.12], tea), body (0.55), reflect (0.28: grazing water), meniscus
//   (0.8), sheen (0.3: the light across the far half) } }, renderOrder (6) }
import * as THREE from 'three';
import { plateTexture, plateRegions, pickRegions, imagePixels, PREMUL, GLSL_COMMON } from './overlay.js';

const W = 3840, H = 2160;

const vert = /* glsl */ `
uniform vec4 uBox;   // x0, y0, x1, y1 (px, y down)
varying vec2 vPx;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = vec2(mix(uBox.x, uBox.z, q.x), mix(uBox.w, uBox.y, q.y));
  vUv = vec2(vPx.x / ${W}.0, 1.0 - vPx.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tPlate, tBlur;
uniform vec4 uOpen;       // rim opening: center x, y, half width a, half height b (px)
uniform vec4 uLiq;        // level: drop below the rim (px), shrink, edge softness (px), horizon row (px)
uniform vec3 uTint;
uniform vec3 uLit;        // the light on the vessel (its lit rim)
uniform vec4 uLook;       // body, reflect, meniscus, sheen
uniform float uPhase, uLoop;
varying vec2 vPx;
varying vec2 vUv;
// signed distance (px, about) outside an ellipse
float ell(vec2 p, vec2 c, vec2 r) {
  vec2 q = (p - c) / r;
  return (length(q) - 1.0) * min(r.x, r.y);
}
void main() {
  vec2 c = uOpen.xy, r = uOpen.zw;
  vec2 cl = c + vec2(0.0, uLiq.x), rl = r * uLiq.y;
  float soft = uLiq.z;
  float inRim = 1.0 - smoothstep(-soft, soft, ell(vPx, c, r - 1.5));
  float dl = ell(vPx, cl, rl);
  float inLiq = 1.0 - smoothstep(-soft, soft, dl);
  float a = inRim * inLiq;
  if (a < 0.003) discard;
  // slow shimmer: a few whole cycles per loop
  float ph = uPhase * TAU;
  vec2 q = (vPx - cl) / rl;
  float n = pfbm(vec2(q.x * 3.0 + 0.6 * sin(ph * 2.0), q.y * 1.5 + 0.4 * cos(ph * 3.0)) + 4.0, vec2(64.0));
  float wob = (n - 0.5) * 2.0;
  // the drink's body: the vessel's light through the drink off its glaze, over the wall seen through it
  vec3 wall = texture2D(tPlate, vUv).rgb;
  float front = clamp((q.y + 1.0) * 0.5, 0.0, 1.0);
  vec3 body = uTint * uLit * uLook.x * (0.6 + 0.4 * front) + wall * 0.25;
  // a level surface mirrors what is as far above the horizon as it is below it (a low view: the street and the
  // neon behind and above the vessel), softened
  vec2 pr = vec2(vPx.x + wob * 4.0, 2.0 * uLiq.w - vPx.y);
  vec3 refl = texture2D(tBlur, vec2(pr.x / ${W}.0, 1.0 - pr.y / ${H}.0)).rgb;
  float fres = uLook.y * (0.6 + 0.4 * (1.0 - front)) * (0.9 + 0.1 * wob);
  vec3 col = mix(body, refl, fres);
  // the meniscus: a thin bright line where it meets the back wall
  float men = exp(-pow(dl / (0.8 + soft * 0.4), 2.0)) * smoothstep(0.2, -0.4, q.y) * inRim;
  col += uLit * uLook.z * men * (0.85 + 0.15 * wob);
  // a soft sheen of the stall's light across the far half (grazing reflection), drifting with the shimmer
  float sheen = exp(-pow((q.y + 0.35 + 0.05 * wob) / 0.22, 2.0)) * smoothstep(1.0, 0.4, abs(q.x - 0.1 * sin(ph)));
  col += uLit * uLook.w * sheen * (0.8 + 0.2 * wob);
  gl_FragColor = vec4(col * a, a);
}`;

export async function liquidLayer(ctx, opts) {
  const meta = await plateRegions(opts.plate);
  const items = [];
  for (const g of pickRegions(meta, opts.regions ?? [])) {
    if (!g.opening) { console.warn(`liquid: ${g.name} has no measured opening (plate_prep fits one to steam regions)`); continue; }
    const [cx, cy, a, b] = g.opening;
    items.push({ name: g.name, cx: cx * W, cy: cy * H, a: a * W, b: b * H, ...(opts.per?.[g.name] ?? {}) });
  }
  if (!items.length) return null;
  const [tPlate, tBlur, dmap, blur] = await Promise.all([plateTexture(opts.plate, 'plate.png', { srgb: true }),
    plateTexture(opts.plate, 'blur.png', { srgb: true }), imagePixels(`/out/plates/${opts.plate}/defocus.png`),
    imagePixels(`/out/plates/${opts.plate}/blur.png`)]);
  const L = ctx.loopSeconds;
  const horizon = (opts.horizon ?? 0.45) * H;
  const lin = (v) => Math.pow(v / 255, 2.2);
  const mats = [];
  for (const it of items) {
    // as soft as the plate is at the vessel (defocus.png: sigma * 20)
    let sig = 0;
    if (dmap) {
      const i = Math.min(dmap.width - 1, Math.floor((it.cx / W) * dmap.width)), j = Math.min(dmap.height - 1, Math.floor((it.cy / H) * dmap.height));
      sig = dmap.data[(j * dmap.width + i) * 4] / 20;
    }
    // the light on the vessel: the brighter half of its front rim
    const lit = [0, 0, 0];
    if (blur) {
      const px = [];
      for (let k = -8; k <= 8; k++) {
        const x = it.cx + (k / 8) * 0.8 * it.a, y = it.cy + it.b * Math.sqrt(Math.max(0, 1 - ((k / 8) * 0.8) ** 2)) + 3;
        const i = Math.min(blur.width - 1, Math.round((x / W) * blur.width)), j = Math.min(blur.height - 1, Math.round((y / H) * blur.height));
        const q = (j * blur.width + i) * 4;
        px.push([lin(blur.data[q]), lin(blur.data[q + 1]), lin(blur.data[q + 2])]);
      }
      px.sort((u, v) => v[0] + v[1] + v[2] - (u[0] + u[1] + u[2]));
      const top = px.slice(0, Math.ceil(px.length / 2));
      for (const p of top) for (let c = 0; c < 3; c++) lit[c] += p[c] / top.length;
    }
    const drop = (it.depth ?? 0.55) * it.b, shrink = it.shrink ?? 0.96;
    const tint = it.color ?? [0.62, 0.42, 0.12];
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag, ...PREMUL,
      uniforms: {
        tPlate: { value: tPlate }, tBlur: { value: tBlur },
        uBox: { value: new THREE.Vector4(it.cx - it.a - 8, it.cy - it.b - 8, it.cx + it.a + 8, it.cy + it.b + 8) },
        uOpen: { value: new THREE.Vector4(it.cx, it.cy, it.a, it.b) },
        uLiq: { value: new THREE.Vector4(drop, shrink, Math.max(0.8, Math.min(4, sig)), horizon) },
        uTint: { value: new THREE.Vector3(...tint) }, uLit: { value: new THREE.Vector3(...lit) },
        uLook: { value: new THREE.Vector4(it.body ?? 0.55, it.reflect ?? 0.28, it.meniscus ?? 0.8, it.sheen ?? 0.3) },
        uPhase: { value: 0 }, uLoop: { value: L },
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
    mats.push(mat);
    console.log(`liquid: ${it.name} level ${drop.toFixed(1)} px below the rim (${(2 * it.a).toFixed(0)} x ${(2 * it.b).toFixed(0)} px opening), edge ${sig.toFixed(1)} px`);
  }
  // one shimmer cycle every ~20 s, whole cycles per loop
  const per = L / Math.max(1, Math.round(L / 20));
  ctx.animate((t) => { for (const m of mats) m.uniforms.uPhase.value = (t % per) / per; });
  return mats;
}
