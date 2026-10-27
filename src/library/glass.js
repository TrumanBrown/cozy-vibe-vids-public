// Rain on window glass: beads stuck to the pane and drops that slide down it in stop-and-go runs, leaving a
// wet trail with a few residue beads and wiping the beads in their path. Each drop is a small lens: it shows
// an inverted, minified view of the scene behind it (bright lights outside sparkle in it), with a dark rim
// (total internal reflection) and a highlight from the room light. Pure function of the loop phase with
// integer cycle counts (seamless); masked by the plate's glass regions (regions.png). Drawn after the
// outdoor rain, so the drops sit in front of it.
//
// opts: { plate, regions: ['window'] or 'kind:glass', size: px scale (1 = drops up to ~8 px at 4K; scale
// with how close the pane is), density: beads (0..1.5), trickles: sliding drops per lane-cycle (0..1),
// spec: highlight color, light: highlight direction [x, y] (image coords, y down), blur: 0..1 defocus of the
// view through the glass, fog: 0..1 condensation (wiped clear by trails), fogColor }
import * as THREE from 'three';
import { flashAt, trackAt } from './timeline.js';
import { plateTexture, plateRegions, pickRegions, PREMUL, GLSL_COMMON, bboxQuad } from './overlay.js';

const vert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const frag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tPlate, tBlur, tRegion, tSel;
uniform float uPhase, uFlash, uBlur, uFog, uDens, uSize, uTrickle, uRainK;
uniform vec3 uFogCol, uSpecCol;
uniform vec2 uLightDir;
uniform vec4 uBox;          // glass bbox, px (x0, y0, x1, y1), image coords y down
varying vec2 vUv;
const vec2 RES = vec2(3840.0, 2160.0);

// tSel: 256 x 1, red 1 for every selected region id (views.png / regions.png ids are 8-bit)
bool isGlass(int id) { return id > 0 && id < 256 && texelFetch(tSel, ivec2(id, 0), 0).r > 0.5; }

// Static bead of grid layer L (cell S px, cyc lifecycles per loop): x coverage, yz shape coords, w radius px.
vec4 bead(vec2 p, float S, int L, float dens, int cyc, float keep) {
  vec2 q = p / S;
  ivec2 c = ivec2(floor(q));
  vec2 f = q - vec2(c) - 0.5;
  float u = uPhase * float(cyc) + hash3(c, L, 5u);
  int k = int(floor(u)) % cyc;
  float age = fract(u);
  ivec2 ck = c + ivec2(k * 7907, k * 6151);
  if (hash3(ck, L, 1u) > dens) return vec4(0.0);
  vec2 o = (vec2(hash3(ck, L, 2u), hash3(ck, L, 3u)) - 0.5) * 0.42;
  float r = 0.1 + 0.2 * pow(hash3(ck, L, 4u), 2.0);
  r *= mix(0.85, 1.12, age);                          // beads grow as more rain lands on them
  vec2 d = (f - o) / r;
  d.y *= d.y > 0.0 ? 0.86 : 1.12;                      // gravity: fuller at the bottom (y down)
  float life = smoothstep(0.0, 0.015, age) * (1.0 - smoothstep(0.85, 0.97, age));
  float rpx = r * S;
  float cov = (1.0 - smoothstep(1.0 - 1.4 / rpx, 1.0, length(d))) * life * keep;
  return vec4(cov, d, rpx);
}

float pathX(float xc, float y, float hA, float hB) {
  return xc + 5.0 * uSize * sin(y / (38.0 * uSize) + hA * TAU) + 2.5 * uSize * sin(y / (11.0 * uSize) + hB * TAU);
}

// Sliding drops in lanes (each lane: a few cycles per loop; a cycle may hold one run).
void trickles(vec2 p, inout vec4 drop, inout float wipe, inout float wet) {
  float Wl = 64.0 * uSize;
  int li = int(floor(p.x / Wl));
  for (int k = -1; k <= 1; k++) {
    int lane = li + k;
    ivec2 lc = ivec2(lane, 977);
    int cyc = 3 + int(hash2(lc, 21u) * 4.0);
    float u = uPhase * float(cyc) + hash2(lc, 22u);
    int kc = int(floor(u)) % cyc;
    float fu = fract(u);
    ivec2 cc = ivec2(lane, kc);
    if (hash2(cc, 23u) > uTrickle * clamp(uRainK, 0.3, 1.6)) continue;
    float st = 0.04 + 0.3 * hash2(cc, 27u);
    if (fu < st) continue;
    float xc = (float(lane) + 0.25 + 0.5 * hash2(cc, 24u)) * Wl;
    float y0 = mix(uBox.y, mix(uBox.y, uBox.w, 0.6), hash2(cc, 25u));
    float len = (uBox.w - y0) * mix(0.3, 1.0, hash2(cc, 26u));
    float du = 0.22 + 0.35 * hash2(cc, 28u);
    float m2 = 2.0 + floor(hash2(cc, 29u) * 3.0);
    float uu = clamp((fu - st) / du, 0.0, 1.0);
    float F = uu - 0.85 / (TAU * m2) * sin(TAU * m2 * uu);      // stop-and-go (monotone)
    float yh = y0 + len * F;
    float hA = hash2(cc, 30u), hB = hash2(cc, 31u);
    float rh = (4.5 + 3.5 * hash2(cc, 32u)) * uSize;
    float fade = 1.0 - smoothstep(0.78, 0.97, fu);              // the trail dries and fills with new beads
    if (p.y > y0 - rh && p.y < yh) {
      float px = pathX(xc, p.y, hA, hB);
      float dx = abs(p.x - px);
      wet = max(wet, (1.0 - smoothstep(0.25 * rh, 0.5 * rh, dx)) * fade * step(y0, p.y));
      wipe = max(wipe, (1.0 - smoothstep(1.4 * rh, 2.2 * rh, dx)) * fade);
      float sy = 15.0 * uSize;
      int bi = int(floor(p.y / sy));
      ivec2 bk = ivec2(bi, lane * 131 + kc);
      float hb = hash2(bk, 33u);
      if (hb < 0.5 && (float(bi) + 0.5) * sy > y0) {
        vec2 bc = vec2(pathX(xc, (float(bi) + 0.5) * sy, hA, hB) + (hb - 0.25) * 3.0 * uSize, (float(bi) + 0.5) * sy);
        float rb = (1.1 + 1.7 * hash2(bk, 34u)) * uSize;
        vec2 db = (p - bc) / rb;
        float cov = (1.0 - smoothstep(1.0 - 1.4 / rb, 1.0, length(db))) * fade;
        if (cov > drop.x) drop = vec4(cov, db, rb);
      }
    }
    vec2 hc = vec2(pathX(xc, yh, hA, hB), yh);
    vec2 d = (p - hc) / vec2(rh, rh * 1.3);
    d.y *= d.y > 0.0 ? 0.85 : 1.25;                              // round front, tapered back
    float cov = (1.0 - smoothstep(1.0 - 1.4 / rh, 1.0, length(d))) * fade;
    if (cov > drop.x) drop = vec4(cov, d, rh);
  }
}

void main() {
  vec2 uv = vUv;
  vec2 p = vec2(uv.x, 1.0 - uv.y) * RES;
  ivec2 tp = ivec2(clamp(uv, 0.0, 0.9999) * vec2(textureSize(tRegion, 0)));
  vec3 rr = texelFetch(tRegion, tp, 0).rgb;
  int id = int(rr.r * 255.0 + 0.5);
  if (!isGlass(id)) discard;
  float w = rr.g;
  vec4 drop = vec4(0.0);
  float wipe = 0.0, wet = 0.0;
  trickles(p, drop, wipe, wet);
  float keep = 1.0 - wipe;
  float dens = uDens * clamp(0.6 + 0.4 * uRainK, 0.4, 1.4);
  vec4 b0 = bead(p, 26.0 * uSize, 0, 0.55 * dens, 3, keep);
  vec4 b1 = bead(p, 17.0 * uSize, 1, 0.5 * dens, 4, keep);
  vec4 b2 = bead(p, 11.0 * uSize, 2, 0.45 * dens, 5, keep);
  if (b0.x > drop.x) drop = b0;
  if (b1.x > drop.x) drop = b1;
  if (b2.x > drop.x) drop = b2;
  float fog = uFog * (1.0 - wet);
  float baseA = max(uBlur, fog * 0.6);
  vec3 col = texture2D(tBlur, uv).rgb * (1.0 + uFlash * 0.5);
  col = mix(col, uFogCol, fog * 0.45);
  float a = baseA;
  if (drop.x > 0.002) {
    vec2 d = drop.yz;
    float l = min(length(d), 1.0);
    // Lens: an inverted, minified view from a few drop-radii around (image y down -> uv y up).
    vec2 off = -d * drop.w * 3.2 / RES * vec2(1.0, -1.0);
    vec3 refr = texture2D(tPlate, uv + off).rgb * (1.0 + uFlash * 0.9);
    refr = mix(refr, texture2D(tBlur, uv + off * 1.6).rgb, 0.35);
    refr *= mix(1.08, 0.42, smoothstep(0.5, 1.0, l));            // dark rim
    vec2 hl = d - uLightDir * 0.42;
    refr += uSpecCol * (exp(-dot(hl, hl) / 0.025) * 0.8 + 0.12 * smoothstep(0.6, 0.95, dot(d, -uLightDir)));
    col = mix(col, refr, drop.x);
    a = mix(a, 1.0, drop.x);
  }
  a *= w;
  if (a < 0.002) discard;
  gl_FragColor = vec4(col * a, a);
}`;

export async function glassLayer(ctx, opts) {
  const meta = await plateRegions(opts.plate);
  // every selected pane (the shader once took 4 ids, and the pixel greenhouse's 28 panes got beads on 4 of them only:
  // dark marks on the right-hand glass that appeared nowhere else, 2026-10-21)
  const regs = pickRegions(meta, opts.regions ?? 'kind:glass');
  if (!regs.length) return null;
  const [tPlate, tBlur, tViews, tRegions] = await Promise.all([
    plateTexture(opts.plate, 'plate.png', { srgb: true }), plateTexture(opts.plate, 'blur.png', { srgb: true }),
    // views.png (plate_prep, 2026-10-16): the glass with whatever stands in front of it cut out, and with what is
    // seen through it not cutting holes in it; plates made before it fall back to regions.png
    plateTexture(opts.plate, 'views.png', { nearest: true, optional: true }), plateTexture(opts.plate, 'regions.png', { nearest: true }),
  ]);
  const tRegion = (tViews.image?.width ?? 1) > 1 ? tViews : tRegions;
  const box = regs.reduce((b, g) => [Math.min(b[0], g.bbox[0]), Math.min(b[1], g.bbox[1]), Math.max(b[2], g.bbox[2]), Math.max(b[3], g.bbox[3])], [1, 1, 0, 0]);
  const sel = new Uint8Array(256 * 4);
  for (const g of regs) if (g.id > 0 && g.id < 256) sel[g.id * 4] = 255;
  const tSel = new THREE.DataTexture(sel, 256, 1, THREE.RGBAFormat);
  tSel.minFilter = tSel.magFilter = THREE.NearestFilter;
  tSel.needsUpdate = true;
  const spec = new THREE.Color(opts.spec ?? '#ffe2b8');
  const fogC = new THREE.Color(opts.fogColor ?? '#9aa3ad');
  const ld = opts.light ?? [-0.55, -0.65];
  const n = Math.hypot(ld[0], ld[1]) || 1;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      tPlate: { value: tPlate }, tBlur: { value: tBlur }, tRegion: { value: tRegion }, tSel: { value: tSel },
      uPhase: { value: 0 }, uFlash: { value: 0 },
      uBlur: { value: opts.blur ?? 0 }, uFog: { value: opts.fog ?? 0 }, uDens: { value: opts.density ?? 1 },
      uSize: { value: opts.size ?? 1 }, uTrickle: { value: opts.trickles ?? 0.55 }, uRainK: { value: 1 },
      uFogCol: { value: new THREE.Vector3(fogC.r, fogC.g, fogC.b) }, uSpecCol: { value: new THREE.Vector3(spec.r, spec.g, spec.b).multiplyScalar(opts.specGain ?? 0.6) },
      uLightDir: { value: new THREE.Vector2(ld[0] / n, ld[1] / n) },
      uBox: { value: new THREE.Vector4(box[0] * 3840, box[1] * 2160, box[2] * 3840, box[3] * 2160) },
    },
  });
  const mesh = new THREE.Mesh(bboxQuad(box, 0.005), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 30;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const L = ctx.loopSeconds;
  ctx.animate((t) => {
    const u = mat.uniforms;
    u.uPhase.value = (t % L) / L;
    u.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
    u.uRainK.value = trackAt(ctx.timeline?.track, 'rain', t);
  });
  return mesh;
}
