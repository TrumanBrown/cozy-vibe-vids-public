// Live flames on a fire's log bed (fireplace, stove, campfire, brazier). The key art's painted flames are removed
// first (tools/plate_clean.py: the logs glowing with embers remain), so nothing ghosts or doubles.
//
// Clip mode (the default; a fire layer without fire/fire.json fails the render): tools/fire_clips.py animated the key
// art's own painted fire with a local video model, color-matched the clips to the plate and found, for every
// frame, the frames of any clip that look like what would come next. The fire plays as a seeded walk through
// those clips: runs of 1.2 to 3 s, each joined to the next by a 0.5 s crossfade between two near-identical
// frames, so it never visibly loops or cuts. The walk is periodic over `period` s (a whole number of loops,
// ~1 h) and a pure function of time (random access, deterministic). The frames are drawn over the plate through
// the feathered fire mask, brightened and dimmed a little with the fire's flicker signal (the light it throws on
// the room, plate.js), and loaded per frame (ctx.prefetch).
//
// Procedural mode (opts.mode = 'procedural', and any fire the clips don't cover): flames are a handful of tongues rooted along the bed: each is a teardrop that narrows to its tip, sways more
// the higher it reaches, and grows and shrinks at its own rates (integer cycles per loop). Upward-scrolling
// noise warps them sideways and breaks their tips into licks that tear off and fade. Color follows the
// temperature (dense, low flame is near white-yellow; thin, high flame is orange to deep red), added on top of
// the plate (fire emits light). The whole fire breathes with the same flicker signal as the light it throws on
// the room (plate.js flickerSignal of the region), so flames and room light rise and fall together. Pixel-art
// scenes quantize the colors (opts.steps) and the engine snaps everything to the pixel grid at 12 fps.
//
// opts: { plate, regions: 'kind:fire', mode: 'clips' | 'procedural', period (s, clip walk), level (clip
//   brightness, 1), per: { <region>: { base: [x0, x1, y] (image coords), height: px at 4K } },
//   tongues (7), intensity (1.15), steps (0 smooth | 4-6 for pixel art), sway (0.16), seed }
import * as THREE from 'three';
import { mulberry32 } from '../engine/rng.js';
import { fetchJson, plateRegions, pickRegions, plateTexture, GLSL_COMMON, PREMUL } from './overlay.js';
import { flickerSignal } from './plate.js';

const NT = 9;

const clipVert = /* glsl */ `
uniform vec4 uBox;        // x, y, w, h (px at 4K)
varying vec2 vT;          // coords in the clip frame (0..1, y down)
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  gl_Position = vec4(vec2(px.x / 3840.0, 1.0 - px.y / 2160.0) * 2.0 - 1.0, 0.0, 1.0);
}`;

const clipFrag = /* glsl */ `
uniform sampler2D tA0, tA1, tB0, tB1, tAlpha;
uniform vec3 uMix;        // blend A0->A1, B0->B1, A->B (crossfade)
uniform float uLevel;
varying vec2 vT;
void main() {
  float al = texture2D(tAlpha, vT).r;
  if (al < 0.002) discard;
  vec3 a = mix(texture2D(tA0, vT).rgb, texture2D(tA1, vT).rgb, uMix.x);
  vec3 c = a;
  if (uMix.z > 0.0) c = mix(a, mix(texture2D(tB0, vT).rgb, texture2D(tB1, vT).rgb, uMix.y), uMix.z);
  gl_FragColor = vec4(c * uLevel * al, al);
}`;

const vert = /* glsl */ `
uniform vec4 uBed;       // bed x0, x1 (px), base y (px, y down), flame height (px)
varying vec2 vP;         // x: -1..1 across the bed, y: 0 at the base, 1 at the nominal flame top
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;                 // 0..1, y up
  vec2 P = vec2(mix(-1.35, 1.35, q.x), mix(-0.25, 1.7, q.y));
  float cx = 0.5 * (uBed.x + uBed.y), hw = 0.5 * (uBed.y - uBed.x);
  vec2 px = vec2(cx + P.x * hw, uBed.z - P.y * uBed.w);
  vP = P;
  vUv = vec2(px.x / 3840.0, 1.0 - px.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tPlate;
uniform vec4 uT[${NT}];      // per tongue: x on the bed (-1..1), half width, height (x flame height), seed
uniform vec4 uTh[${NT}];     // per tongue now: height factor, sway phase, sway amount, lean
uniform int uN;
uniform float uPhase, uLevel, uAspect;   // loop phase; flicker level (~1); bed half width / flame height
uniform vec4 uLook;          // intensity, steps, glow, seed
varying vec2 vP;
varying vec2 vUv;

vec3 ramp(float T) {
  vec3 c = mix(vec3(0.0), vec3(0.5, 0.06, 0.01), smoothstep(0.02, 0.25, T));
  c = mix(c, vec3(0.98, 0.32, 0.04), smoothstep(0.2, 0.5, T));
  c = mix(c, vec3(1.0, 0.62, 0.16), smoothstep(0.45, 0.75, T));
  c = mix(c, vec3(1.0, 0.85, 0.55), smoothstep(0.75, 1.0, T));
  return c;
}

void main() {
  vec2 p = vP;
  float seed = uLook.w;
  // rising turbulence (periodic: whole periods scrolled per loop): big slow licks and fast fine tearing
  float n1 = pfbm(vec2(p.x * 2.2 * uAspect + seed, p.y * 1.4 - uPhase * 384.0), vec2(16.0, 8.0));
  float n2 = pfbm(vec2(p.x * 5.0 * uAspect + 3.7 * seed, p.y * 3.0 - uPhase * 768.0), vec2(32.0, 16.0));
  // the flames waver more the higher they reach
  vec2 q = vec2(p.x + (n1 - 0.5) * 0.55 * smoothstep(0.0, 1.0, p.y) / max(uAspect, 0.3), p.y);
  // local flame height across the bed: the tongues (each growing, shrinking and swaying on its own)
  float hx = 0.0;
  for (int k = 0; k < ${NT}; k++) {
    if (k >= uN) break;
    vec4 T = uT[k], S = uTh[k];
    float h = T.z * S.x;
    float u = clamp(q.y / max(h, 1e-3), 0.0, 1.3);
    float sway = S.z * pow(u, 1.35) * sin(S.y + u * 2.4) + S.w * u * u;
    hx = max(hx, h * exp(-pow((q.x - T.x - sway) / (T.y * 1.4), 2.0)));
  }
  float side = smoothstep(1.25, 0.8, abs(q.x));
  float rel = q.y / max(hx, 0.05);                  // 0 at the base, 1 at the local flame top
  float e = clamp(1.0 - rel, 0.0, 1.0) * side;
  // licks: the noise cuts the flame body into tongues and tears off the tips, more strongly higher up
  float lick = 0.6 * n2 + 0.4 * n1;
  float d = clamp(e * 1.7 - (1.0 - lick) * (0.3 + 0.75 * smoothstep(0.05, 0.9, rel)), 0.0, 1.0);
  d = d * d * (3.0 - 2.0 * d);
  // the flames come up from between the logs, a little below the glowing bed line
  d *= smoothstep(-0.14, 0.03, q.y + 0.1 * (n2 - 0.5));
  if (d < 0.003) discard;
  float temp = clamp(d * (1.3 - 0.6 * clamp(rel, 0.0, 1.4)), 0.0, 1.0) * mix(0.92, 1.08, clamp((uLevel - 0.9) * 5.0, 0.0, 1.0));
  if (uLook.y > 0.5) temp = floor(temp * uLook.y + 0.5) / uLook.y;
  // dark foreground metal (grate bars, andirons) in the lower part stays in front of the flames
  vec3 bg = texture2D(tPlate, vUv).rgb;
  float lumB = dot(bg, vec3(0.2126, 0.7152, 0.0722));
  float occl = mix(1.0, smoothstep(0.02, 0.12, lumB), 1.0 - smoothstep(0.2, 0.45, p.y));
  vec3 col = ramp(temp) * (0.35 + 0.65 * d) * d * occl * uLook.x * uLevel;
  // a faint warm glow in the air around the flames
  vec2 gp = p * vec2(0.8, 1.2) - vec2(0.0, 0.45);
  col += vec3(1.0, 0.45, 0.12) * exp(-dot(gp, gp) * 1.4) * uLook.z * uLevel;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 0.0);
}`;

// Screen blending (dst + src - dst*src): flames add light without clipping the painted fire glow to white.
const SCREEN = {
  transparent: true, depthTest: false, depthWrite: false, toneMapped: false, side: THREE.DoubleSide,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneMinusDstColorFactor, blendDst: THREE.OneFactor,
  blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
};

// The clip walk: runs [T (source frames from the period start), clip index, first frame], periodic in `total`.
function clipWalk(meta, total, seed) {
  const r = mulberry32(seed);
  const names = meta.names, fps = meta.fps ?? 24, half = Math.floor((meta.xfade ?? 6) / 2);
  const [rmin, rmax] = (meta.run ?? [1.2, 3]).map((s) => Math.round(s * fps));
  const runs = [];
  let ci = 0;
  let f = meta.clips[names[0]].lo + half + Math.floor(r() * 12);
  let T = 0;
  while (T < total) {
    const c = meta.clips[names[ci]];
    const maxN = c.hi - half - 1 - f;   // the last row of jumps; the crossfade after it still has frames
    const n = Math.max(1, Math.min(maxN, rmin + Math.floor(r() * (rmax - rmin + 1))));
    runs.push([T, ci, f]);
    T += n;
    const row = meta.next[names[ci]][f + n - (c.lo + half)] ?? [];
    if (!row.length) { ci = 0; f = runs[0][2]; continue; }
    // the cheapest jumps are likeliest (cost 1 = as different as one frame step)
    const b = row[0][2];
    const w = row.map(([, , cost]) => Math.exp(-(cost - b) / 0.6));
    let u = r() * w.reduce((s, x) => s + x, 0), k = 0;
    while (k < row.length - 1 && (u -= w[k]) > 0) k++;
    ci = row[k][0];
    f = row[k][1] - 1;
  }
  return runs;
}

async function fireClipsLayer(ctx, opts, meta, g) {
  const base = `/out/plates/${opts.plate}/fire`;
  const fps = meta.fps ?? 24, half = Math.floor((meta.xfade ?? 6) / 2);
  const L = ctx.loopSeconds;
  const period = opts.period ?? L * Math.max(1, Math.round(3600 / L));
  const total = Math.round(period * fps);
  const runs = clipWalk(meta, total, (opts.seed ?? ctx.seed ?? 7) * 7919 + 101);
  const names = meta.names;
  // frame shown by run k at source time s (frames from the period start), clamped to the clip
  const runAt = (k, s) => {
    const n = runs.length, kk = ((k % n) + n) % n, wrap = Math.floor(k / n) * total;
    const [T, ci, f] = runs[kk];
    const c = meta.clips[names[ci]];
    return { ci, idx: Math.min(c.hi, Math.max(0, f + (s - T - wrap))) };
  };
  const state = (t) => {
    const s = ((t * fps) % total + total) % total;
    let lo = 0, hi = runs.length - 1;
    while (lo < hi) { const m = (lo + hi + 1) >> 1; if (runs[m][0] <= s) lo = m; else hi = m - 1; }
    const k = lo;
    const a = runAt(k, s);
    const tNext = k + 1 < runs.length ? runs[k + 1][0] : total;
    // crossfades are centered on the run boundaries (half the crossfade on each side)
    if (s > tNext - half) return { a, b: runAt(k + 1, s), w: (s - (tNext - half)) / (2 * half) };
    if (s < runs[k][0] + half) {
      const w = (s - (runs[k][0] - half)) / (2 * half);
      return { a: runAt(k - 1, s), b: a, w };
    }
    return { a, b: null, w: 0 };
  };
  const mkTex = () => {
    const t = new THREE.Texture();
    t.colorSpace = THREE.SRGBColorSpace;
    t.flipY = false;
    t.generateMipmaps = false;
    t.minFilter = t.magFilter = THREE.LinearFilter;
    return t;
  };
  const tex = [mkTex(), mkTex(), mkTex(), mkTex()];
  const tAlpha = await plateTexture(opts.plate, `fire/${meta.alpha ?? 'alpha.png'}`);
  tAlpha.flipY = false;
  tAlpha.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({
    vertexShader: clipVert, fragmentShader: clipFrag, ...PREMUL,
    uniforms: {
      tA0: { value: tex[0] }, tA1: { value: tex[1] }, tB0: { value: tex[2] }, tB1: { value: tex[3] }, tAlpha: { value: tAlpha },
      uMix: { value: new THREE.Vector3() }, uLevel: { value: 1 }, uBox: { value: new THREE.Vector4(...meta.box) },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 5;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const cache = new Map(), order = [];
  const url = (ci, i) => `${base}/${meta.clips[names[ci]].dir}/c_${String(i).padStart(4, '0')}.jpg`;
  const load = (ci, i) => {
    const key = url(ci, i);
    if (cache.has(key)) return cache.get(key);
    const p = fetch(key).then((r) => { if (!r.ok) throw new Error(`${key}: HTTP ${r.status}`); return r.blob(); }).then((b) => createImageBitmap(b, { colorSpaceConversion: 'none' }));
    cache.set(key, p);
    order.push(key);
    while (order.length > 40) {
      const old = order.shift();
      const q = cache.get(old);
      cache.delete(old);
      q?.then((bm) => bm.close?.());
    }
    return p;
  };
  let cur = null;
  ctx.prefetch(async (t) => {
    const st = state(t);
    const pair = (x) => {
      const i0 = Math.floor(x.idx), i1 = Math.min(i0 + 1, meta.clips[names[x.ci]].hi);
      return [load(x.ci, i0), load(x.ci, i1), x.idx - i0];
    };
    const A = pair(st.a), B = st.b ? pair(st.b) : null;
    const bm = await Promise.all([A[0], A[1], ...(B ? [B[0], B[1]] : [])]);
    cur = { t, bm, fa: A[2], fb: B ? B[2] : 0, w: st.b ? st.w : 0 };
  });
  const shown = [null, null, null, null];
  const fk = opts.flicker ?? { style: 'fire' };
  ctx.animate((t) => {
    if (!cur || Math.abs(cur.t - t) > 1e-6) { mesh.visible = false; return; }
    mesh.visible = true;
    cur.bm.forEach((b, i) => {
      if (shown[i] !== b) { tex[i].image = b; tex[i].needsUpdate = true; shown[i] = b; }
    });
    const s = flickerSignal(g.name, ctx.seed, fk.style ?? 'fire', t, L, fk.speed ?? 1);
    mat.uniforms.uMix.value.set(cur.fa, cur.fb, cur.bm.length > 2 ? cur.w : 0);
    mat.uniforms.uLevel.value = (opts.level ?? 1) * (1 + 0.06 * s);
  });
  return mesh;
}

export async function fireLayer(ctx, opts) {
  const meta = await plateRegions(opts.plate);
  let fires = pickRegions(meta, opts.regions ?? 'kind:fire');
  if (!fires.length) return [];
  const meshes = [];
  if (opts.mode !== 'procedural') {
    // clips of the key art's own fire (lessons L09); code-drawn flames only when the scene asks for them
    const fm = await fetchJson(`/out/plates/${opts.plate}/fire/fire.json`, {
      hint: 'make the clips (tools/fire_clips.py <scene> auto, or new_video.py life), or set the fire layer\'s mode to "procedural"',
    });
    const g = fm && fires.find((x) => x.name === fm.region);
    if (g) {
      meshes.push(await fireClipsLayer(ctx, opts, fm, g));
      fires = fires.filter((x) => x !== g);
    }
  }
  if (!fires.length) return meshes;
  const L = ctx.loopSeconds;
  const cyc = (hz) => Math.max(1, Math.round(hz * L));
  const tPlate = await plateTexture(opts.plate, 'plate.png', { srgb: true });
  fires.forEach((g, fi) => {
    const per = opts.per?.[g.name] ?? {};
    const [x0, y0, x1, y1] = g.bbox;
    const w = (x1 - x0) * 3840, h = (y1 - y0) * 2160;
    // the flames stand on the glowing ember bed plate_prep measured in the cleaned plate (regions.json "bed");
    // without it, on the lower part of the analyzed fire region (the painted flames grown upward)
    const base = per.base ?? g.bed ?? [x0 + 0.12 * (x1 - x0), x1 - 0.12 * (x1 - x0), y1 - 0.14 * (y1 - y0)];
    const flameH = per.height ?? 0.55 * h;
    const bed = new THREE.Vector4(base[0] * 3840, base[1] * 3840, base[2] * 2160, flameH);
    const r = mulberry32((opts.seed ?? 7) * 7919 + fi * 104729 + 13);
    const n = Math.min(NT, opts.tongues ?? 7);
    const T = Array.from({ length: NT }, () => new THREE.Vector4());
    const Th = Array.from({ length: NT }, () => new THREE.Vector4());
    const motion = [];
    for (let k = 0; k < n; k++) {
      const xk = n === 1 ? 0 : -0.78 + 1.56 * (k + 0.5 * (r() - 0.5)) / (n - 1);
      const tall = 1 - 0.38 * Math.abs(xk);
      T[k].set(xk, 0.16 + 0.16 * r(), (0.55 + 0.45 * r()) * tall, r());
      motion.push({ a: [cyc(1.6 + 2.4 * r()), cyc(3.5 + 4.5 * r()), cyc(0.25 + 0.4 * r())], ph: [r() * 6.283, r() * 6.283, r() * 6.283], sw: cyc(0.7 + 0.9 * r()), swPh: r() * 6.283 });
    }
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag, ...SCREEN,
      uniforms: {
        tPlate: { value: tPlate },
        uBed: { value: bed }, uT: { value: T }, uTh: { value: Th }, uN: { value: n }, uPhase: { value: 0 }, uLevel: { value: 1 },
        uAspect: { value: (0.5 * (bed.y - bed.x)) / flameH },
        uLook: { value: new THREE.Vector4(opts.intensity ?? 0.95, opts.steps ?? 0, opts.glow ?? 0.04, (fi + 1) * 3.17) },
      },
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 5;   // on the plate, under rain, steam and the pet
    mesh.userData.noAO = true;
    ctx.add(mesh);
    meshes.push(mesh);
    const fk = opts.flicker ?? { style: 'fire' };
    ctx.animate((t) => {
      const ph = (t % L) / L;
      const s = flickerSignal(g.name, ctx.seed, fk.style ?? 'fire', t, L, fk.speed ?? 1);
      const level = 1 + 0.12 * s;
      mat.uniforms.uPhase.value = ph;
      mat.uniforms.uLevel.value = level;
      const sway = opts.sway ?? 0.16;
      motion.forEach((m, k) => {
        const hf = 0.84 + 0.11 * Math.sin(2 * Math.PI * m.a[0] * ph + m.ph[0]) + 0.06 * Math.sin(2 * Math.PI * m.a[1] * ph + m.ph[1])
          + 0.05 * Math.sin(2 * Math.PI * m.a[2] * ph + m.ph[2]) + 0.06 * s;
        Th[k].set(hf, 2 * Math.PI * m.sw * ph + m.swPh, sway, 0.05 * Math.sin(2 * Math.PI * m.a[2] * ph + 2 * m.ph[2]));
      });
    });
  });
  return meshes;
}
