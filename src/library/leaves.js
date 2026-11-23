// Falling autumn leaves for plate scenes, driven by the event timeline (timeline.js leafSchedule): each
// leaf's flight is a pure function of time. It falls at a leaf's terminal speed (~1 m/s), sways like a
// pendulum with a little lift at the ends of each swing, tilts with the swing, tumbles (flutterers) or
// glides, and drifts with the same wind as the rain (exact drift integral). Leaves are pixel-art shapes
// in the key art's voxel style, colored from the plate's own foliage palette (plate.json), lit by the
// local environment and lantern glow, motion-blurred over the shutter, and masked to the outdoors.
import * as THREE from 'three';
import { flashAt, trackAt, windDrift, flurryDrift } from './timeline.js';
import { loadTex } from './overlay.js';
import { toLin } from './util.js';

// 9x9 shapes, tip at the top: '#' leaf, '+' vein, 's' stem, '.' empty.
const SHAPES = [
  ['....#....', '..#.#.#..', '#.##+##.#', '##.#+#.##', '.###+###.', '..##+##..', '...#+#...', '....s....', '....s....'],
  ['...#.#...', '..##.##..', '.###+###.', '####+####', '.###+###.', '..##+##..', '...###...', '....s....', '....s....'],
  ['....#....', '...###...', '..##+##..', '.###+###.', '.###+###.', '..##+##..', '...#+#...', '....#....', '....s....'],
];
const CELL = 11; // 9 + 1 texel transparent border each side

function atlas() {
  const w = CELL * SHAPES.length, h = CELL;
  const d = new Uint8Array(w * h * 4);
  SHAPES.forEach((rows, k) => rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === '.') return;
    const i = ((y + 1) * w + k * CELL + x + 1) * 4;
    d[i] = 255; d[i + 1] = ch === '+' ? 255 : 0; d[i + 2] = ch === 's' ? 255 : 0; d[i + 3] = 255;
  })));
  const t = new THREE.DataTexture(d, w, h, THREE.RGBAFormat, THREE.UnsignedByteType);
  t.colorSpace = THREE.NoColorSpace;
  t.minFilter = t.magFilter = THREE.LinearFilter;
  t.generateMipmaps = false;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.flipY = false;
  t.unpackAlignment = 1;
  t.needsUpdate = true;
  return t;
}

// Pixel-art albedo shader of a leaf's 9x9 shape in its own frame. Motion blur: 4 samples across the shutter.
const vert = /* glsl */ `
attribute vec4 aA, aB;   // state at shutter open / close: center x, y (px, y down), angle, flip (cos)
attribute vec4 aC;       // size (px), shape, depth z (m), seed
attribute vec4 aD;       // linear albedo rgb, active (1) / unused slot (0)
uniform vec2 uRes;
varying vec2 vPx, vUv;
varying vec4 vA, vB, vC;
varying vec3 vCol;
void main() {
  vA = aA; vB = aB; vC = aC; vCol = aD.rgb;
  vec2 c = 0.5 * (aA.xy + aB.xy);
  float hs = (0.75 * aC.x + 0.5 * length(aB.xy - aA.xy) + 2.0) * step(0.5, aD.w);   // unused slot: zero-size quad
  vec2 p = c + position.xy * hs;
  vPx = p;
  vUv = vec2(p.x / uRes.x, 1.0 - p.y / uRes.y);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLeaf, tLights, tEnv;
uniform vec3 uWarm;
uniform float uAmb, uWarmK, uEnvRef, uFlash, uDebug;
varying vec2 vPx, vUv;
varying vec4 vA, vB, vC;
varying vec3 vCol;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main() {
  if (uDebug > 1.5) { gl_FragColor = vec4(1.0, 0.0, 1.0, 1.0); return; }   // QA: show the quad
  float cov = 0.0;
  vec3 col = vec3(0.0);
  for (int i = 0; i < 4; i++) {           // 4 samples across the shutter (motion blur)
    float l = (float(i) + 0.5) / 4.0;
    vec2 c = mix(vA.xy, vB.xy, l);
    float ang = mix(vA.z, vB.z, l), fl = mix(vA.w, vB.w, l);
    vec2 d = vPx - c;
    float cs = cos(ang), sn = sin(ang);
    vec2 q = vec2(cs * d.x + sn * d.y, -sn * d.x + cs * d.y) / vC.x;
    float af = max(abs(fl), 0.06);
    q.x /= af;
    vec2 uv = (q + 0.5) * 9.0;            // shape texel coords (texel k spans [k, k+1])
    // Pixel-art AA: sample texel centers, blending only within 1 screen pixel of each texel seam.
    vec2 fw = 9.0 / (vec2(vC.x * af, vC.x));   // texels per screen pixel
    vec2 seam = floor(uv + 0.5);
    vec2 tc = seam + clamp((uv - seam) / fw, -0.5, 0.5);
    tc = clamp(tc, vec2(-0.5), vec2(9.5));
    vec4 s = texture2D(tLeaf, (vec2(vC.y * 11.0 + 1.0, 1.0) + tc) / vec2(33.0, 11.0));
    float a = s.r * smoothstep(0.03, 0.12, abs(fl));     // edge-on leaves thin out
    vec3 base = vCol * (0.9 + 0.2 * hash(floor(uv) + vC.w));
    base = mix(base, base * 0.7, s.g);                     // vein
    base = mix(base, vec3(0.09, 0.045, 0.02), s.b);        // stem
    if (fl < 0.0) base *= vec3(0.78, 0.8, 0.85);           // underside: duller
    base *= 0.55 + 0.45 * abs(fl);                         // tilt shading as it turns
    cov += a * 0.25;
    col += base * a * 0.25;
  }
  if (cov < 0.002) discard;
  vec3 albedo = col / cov;                                 // coverage-weighted mean color
  vec4 lt = texture2D(tLights, vUv);
  cov *= lt.g;                                             // outdoors only (behind the opening)
  if (cov < 0.002) discard;
  if (uDebug > 0.5) { gl_FragColor = vec4(cov, cov, cov, 1.0); return; }
  vec3 env = texture2D(tEnv, vUv).rgb;
  float light = uAmb * dot(env, vec3(0.2126, 0.7152, 0.0722)) / uEnvRef + uWarmK * lt.b;
  vec3 rgb = albedo * light * (1.0 + 0.6 * uFlash);
  rgb = mix(rgb, env, clamp((vC.z - 2.0) * 0.06, 0.0, 0.35));   // distance haze toward the local air
  gl_FragColor = vec4(rgb * cov, cov);
}`;

// opts: { plate, wind: {mean, gust, gustCycles, fronts}, focalPx, shutter, ambient, warm, debug }
export async function leavesLayer(ctx, opts) {
  const leaves = ctx.timeline?.leaves ?? [];
  if (ctx.params?.leafdebug) console.warn(`leavesLayer: ${leaves.length} leaves in timeline`);
  if (!leaves.length) return null;
  const dir = `/out/plates/${opts.plate}`;
  const [tLights, tEnv, meta] = await Promise.all([loadTex(`${dir}/lights.png`), loadTex(`${dir}/env.png`, { srgb: true }), fetch(`${dir}/plate.json`).then((r) => r.json())]);
  const W = 3840, H = 2160, F = opts.focalPx ?? 2700, shutter = opts.shutter ?? 1 / 110;
  const pal = (meta.foliage_palette ?? [[200, 100, 30, 1]]).map((c) => c.slice(0, 3).map((v) => toLin(v / 255)));
  const envRef = (() => { const e = meta.env_linear?.outdoor ?? [0.07, 0.06, 0.1]; return 0.2126 * e[0] + 0.7152 * e[1] + 0.0722 * e[2]; })();
  const wv = opts.wind ?? {};
  const w = { mean: wv.mean ?? 0, gust: wv.gust ?? 0, gustCycles: Math.max(1, Math.round(wv.gustCycles ?? 5)), fronts: wv.fronts ?? 0.6, loop: ctx.loopSeconds };
  const MAX = 24;
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  const attr = {};
  for (const k of ['aA', 'aB', 'aC', 'aD']) {
    attr[k] = new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4);
    attr[k].setUsage(THREE.DynamicDrawUsage);
    g.setAttribute(k, attr[k]);
  }
  g.instanceCount = MAX;   // fixed pool; unused slots are culled in the vertex shader (aD.w = 0)
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    side: THREE.DoubleSide,   // screen-space quads with y down flip the winding
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
    blendDst: opts.debug ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLeaf: { value: atlas() }, tLights: { value: tLights }, tEnv: { value: tEnv }, uRes: { value: new THREE.Vector2(W, H) },
      uWarm: { value: new THREE.Color('#ffb26a') }, uAmb: { value: opts.ambient ?? 0.45 }, uWarmK: { value: opts.warm ?? 0.9 },
      uEnvRef: { value: envRef }, uFlash: { value: 0 }, uDebug: { value: ctx.params?.leafdebug === 'quad' ? 2 : opts.debug ? 1 : 0 },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 20;
  mesh.userData.noAO = true;
  ctx.add(mesh);

  const maxDur = Math.max(...leaves.map((l) => l.dur));
  const state = (L, time, gustK) => {
    const age = time - L.t, ppm = F / L.z;
    const ph = 2 * Math.PI * L.f * age + L.ph;
    const xm = L.A * Math.sin(ph) + windDrift(w, L.t, time, L.x, gustK) + flurryDrift(ctx.timeline, L.t, time);
    const ym = L.vt * age + 0.05 * Math.cos(2 * ph);
    const ang = L.th0 + L.B * Math.cos(ph) + L.spin * age;
    const fl = L.fm ? Math.cos(2 * Math.PI * L.fl * age + 1.7 * L.ph) : Math.cos(0.5 * Math.sin(ph));
    return [L.x * W + xm * ppm, -(L.s * ppm) - 20 + ym * ppm, ang, fl];
  };
  ctx.animate((t) => {
    let lo = 0, hi = leaves.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (leaves[m].t < t - maxDur) lo = m + 1; else hi = m; }
    const gustK = trackAt(ctx.timeline?.track, 'wind', t);
    let n = 0;
    for (let i = lo; i < leaves.length && leaves[i].t <= t + shutter && n < MAX; i++) {
      const L = leaves[i];
      if (t - shutter > L.t + L.dur) continue;
      const a = state(L, t - shutter / 2, gustK), b = state(L, t + shutter / 2, gustK);
      const sizePx = L.s * F / L.z;
      const c = pal[Math.min(L.c, pal.length - 1)];
      const red = L.red;
      attr.aA.array.set(a, n * 4);
      attr.aB.array.set(b, n * 4);
      attr.aC.array.set([sizePx, L.shape, L.z, (i * 7.31) % 97], n * 4);
      attr.aD.array.set([c[0], c[1] * (1 - 0.5 * red), c[2] * (1 - 0.5 * red), 1], n * 4);
      n++;
    }
    if (ctx.params?.leafdebug) console.warn(`leaves t=${t.toFixed(2)} active=${n}` + (n ? ` first=${Array.from(attr.aA.array.slice(0, 4)).map((v) => v.toFixed(1))} size=${attr.aC.array[0].toFixed(1)}` : ''));
    for (let k = n; k < MAX; k++) attr.aD.array[k * 4 + 3] = 0;
    for (const k in attr) attr[k].needsUpdate = true;
    mat.uniforms.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
  });
  return mesh;
}
