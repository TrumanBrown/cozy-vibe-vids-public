// Shared helpers for plate overlay layers (glass, steam, particles, traffic): memoized plate textures and a plain
// texture loader, the region table, image pixels read on the CPU, quads, lights, and GLSL snippets (hashes and
// loop-periodic noise).
import * as THREE from 'three';

const cache = new Map();

// Memoized texture from out/plates/<plate>/<file> (one GPU copy shared by every layer).
export function plateTexture(plate, file, { srgb = false, nearest = false, optional = false } = {}) {
  const key = `${plate}/${file}/${srgb}/${nearest}`;
  if (!cache.has(key)) {
    cache.set(key, new THREE.TextureLoader().loadAsync(`/out/plates/${plate}/${file}`).then((t) => {
      t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.generateMipmaps = false;
      t.minFilter = t.magFilter = nearest ? THREE.NearestFilter : THREE.LinearFilter;
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      return t;
    }).catch((e) => {
      if (!optional) throw e;
      const t = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
      t.needsUpdate = true;
      return t;
    }));
  }
  return cache.get(key);
}

// A texture of the layer's own (plateTexture shares one copy): linear filtering, clamped at the edges, sRGB or raw
// data, mipmaps only with mips.
export async function loadTex(url, { srgb = false, mips = false } = {}) {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.generateMipmaps = mips;
  t.minFilter = mips ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

// regions.json of a plate ([] if the plate has no named regions, as a hand-measured plate like Treetop's), and lookups
// by name or kind. A regions.json that can't be read fails the render.
export async function plateRegions(plate) {
  const key = `${plate}/regions.json`;
  if (!cache.has(key)) cache.set(key, fetchJson(`/out/plates/${plate}/regions.json`, { optional: true }).then((j) => j ?? []));
  return cache.get(key);
}

// A JSON input of a layer, parsed; null when it is optional and missing. Anything else throws with the file's path and
// what makes it, so a missing input fails the render instead of drawing nothing (TASKS.md T6).
export async function fetchJson(url, { optional = false, hint = '' } = {}) {
  const r = await fetch(url);
  const file = url.replace(/^\//, '');
  if (r.status === 404 && optional) return null;
  if (!r.ok) throw new Error(`${file} is missing (HTTP ${r.status})${hint ? `: ${hint}` : ''}`);
  try {
    return await r.json();
  } catch (e) {
    throw new Error(`${file} isn't valid JSON (${e.message})`);
  }
}
export function pickRegions(meta, sel) {
  if (!sel) return [];
  const want = Array.isArray(sel) ? sel : [sel];
  return meta.filter((g) => want.includes(g.name) || want.includes(`kind:${g.kind}`));
}

// Exact pixels of an image (no color conversion, no premultiplication): { data (RGBA bytes), width, height },
// or null if it is missing. For id maps and masks read on the CPU.
export async function imagePixels(url) {
  const r = await fetch(url).catch(() => null);
  if (!r?.ok) return null;
  const bmp = await createImageBitmap(await r.blob(), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  const c = new OffscreenCanvas(bmp.width, bmp.height);
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(bmp, 0, 0);
  return { data: g.getImageData(0, 0, bmp.width, bmp.height).data, width: bmp.width, height: bmp.height };
}

// The mean linear color (gamma 2.2) of an image from imagePixels in a box: avg(x0, y0, x1, y1), px of a W x H frame,
// from 6 x 6 samples. Samples outside the image are left out, and with none inside it is [0.05, 0.05, 0.05].
export function boxMean(img, W, H) {
  const lin = (v) => Math.pow(v / 255, 2.2);
  return (x0, y0, x1, y1) => {
    const s = [0, 0, 0];
    let n = 0;
    for (let j = 0; j < 6; j++) {
      for (let i = 0; i < 6; i++) {
        const x = Math.round(((x0 + ((x1 - x0) * (i + 0.5)) / 6) * img.width) / W), y = Math.round(((y0 + ((y1 - y0) * (j + 0.5)) / 6) * img.height) / H);
        if (x < 0 || y < 0 || x >= img.width || y >= img.height) continue;
        const q = (y * img.width + x) * 4;
        s[0] += lin(img.data[q]); s[1] += lin(img.data[q + 1]); s[2] += lin(img.data[q + 2]); n++;
      }
    }
    return n ? s.map((v) => v / n) : [0.05, 0.05, 0.05];
  };
}

// Points (px at 4K, y down) hanging from a moving region (a swaying cloth or plant, a swinging lantern: the
// region just above the point, within 12 px): [{ i, id, x, y, ax, w }]. Each frame they move by
// ctx.regionMotion.offsetPx(id, x, y, ax, w), the plate's own warp there.
export async function hangingFrom(ctx, plate, pts) {
  const rm = ctx.regionMotion;
  if (!rm || !pts.length) return [];
  const img = await imagePixels(`/out/plates/${plate}/regions.png`);
  if (!img) return [];
  const { data, width, height } = img;
  const out = [];
  pts.forEach(([x, y], i) => {
    for (const dy of [2, 4, 7, 12]) {
      const xx = Math.round(x * width / 3840), yy = Math.round((y - dy) * height / 2160);
      if (xx < 0 || yy < 0 || xx >= width || yy >= height) continue;
      const k = (yy * width + xx) * 4;
      if (!data[k]) continue;
      if (rm.moves(data[k])) out.push({ i, id: data[k], x: Math.round(x), y: Math.round(y - dy), ax: data[k + 2] / 255, w: data[k + 1] / 255 });
      break;
    }
  });
  return out;
}

// Additive-over blending for premultiplied colors (same as rain.js). DoubleSide: screen-space quads built in
// y-down pixel coordinates flip the winding (leaves.js has the same note), which would cull them.
export const PREMUL = {
  transparent: true, depthTest: false, depthWrite: false, toneMapped: false, side: THREE.DoubleSide,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
  blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
};

// Pure additive blending of premultiplied color (dst += src.rgb); three's AdditiveBlending would scale by src alpha.
export const ADDITIVE = {
  transparent: true, depthTest: false, depthWrite: false, toneMapped: false, side: THREE.DoubleSide,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor,
  blendSrcAlpha: THREE.ZeroFactor, blendDstAlpha: THREE.OneFactor,
};

export const GLSL_COMMON = /* glsl */ `
const float TAU = 6.28318530718;
uint pcg(uint v) { uint s = v * 747796405u + 2891336453u; uint w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u; return (w >> 22u) ^ w; }
float hash1(uint a) { return float(pcg(a)) * (1.0 / 4294967296.0); }
float hash2(ivec2 c, uint k) { return hash1(uint(c.x) * 1597334677u ^ uint(c.y) * 3812015801u ^ k * 2654435761u); }
float hash3(ivec2 c, int l, uint k) { return hash2(c + ivec2(l * 7919, l * 104729), k); }
// Value noise, periodic with period per (cells) in both axes.
float pnoise(vec2 p, vec2 per) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  vec2 i0 = mod(i, per), i1 = mod(i + 1.0, per);
  float a = hash2(ivec2(i0), 11u), b = hash2(ivec2(i1.x, i0.y), 11u), c = hash2(ivec2(i0.x, i1.y), 11u), d = hash2(ivec2(i1), 11u);
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float pfbm(vec2 p, vec2 per) {
  float s = 0.0, a = 0.5;
  for (int k = 0; k < 4; k++) { s += a * pnoise(p, per); p *= 2.0; per *= 2.0; a *= 0.5; }
  return s / 0.9375;
}
int regionAt(sampler2D tRegion, vec2 uv) { return int(texelFetch(tRegion, ivec2(clamp(uv, 0.0, 0.9999) * vec2(textureSize(tRegion, 0))), 0).r * 255.0 + 0.5); }
`;

export function fullQuad() {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  return g;
}

// The same quad drawn n times (instanced particles, drops, wisps).
export function instancedQuad(n) {
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = n;
  return g;
}

// A directional light added to scene: o ({ color, intensity, dir }) over the defaults def, 100 units out along dir.
export function dirLight(scene, o, def) {
  const l = new THREE.DirectionalLight(o?.color ?? def.color, o?.intensity ?? def.intensity);
  l.position.set(...(o?.dir ?? def.dir).map((v) => v * 100));
  scene.add(l);
  return l;
}

// A screen-space quad covering bbox [x0, y0, x1, y1] (image coords, y down) plus a margin (fraction).
export function bboxQuad(b, margin = 0) {
  const x0 = Math.max(0, b[0] - margin), x1 = Math.min(1, b[2] + margin), y0 = Math.max(0, b[1] - margin), y1 = Math.min(1, b[3] + margin);
  const X = (x) => x * 2 - 1, Y = (y) => 1 - y * 2;
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([X(x0), Y(y1), 0, X(x1), Y(y1), 0, X(x1), Y(y0), 0, X(x0), Y(y0), 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  return g;
}

export const cyclesPerLoop = (hz, L) => Math.max(1, Math.round(hz * L));

// The timeline's slow weather track (timeline.js weatherTrack) as a 1D half-float texture: R rain, G streams,
// B wind (1 = nominal); null without a track. Shaders read it with WEATHER_GLSL (same as rain.js).
const weatherTex = new WeakMap();
export function weatherTexture(ctx) {
  const track = ctx.timeline?.track;
  if (!track?.rain?.length) return { tex: null, n: 0, dt: 5 };
  if (!weatherTex.has(track)) {
    const n = track.rain.length;
    const d = new Uint16Array(n * 4);
    for (let i = 0; i < n; i++) {
      d[i * 4] = THREE.DataUtils.toHalfFloat(track.rain[i]);
      d[i * 4 + 1] = THREE.DataUtils.toHalfFloat(track.streams[i]);
      d[i * 4 + 2] = THREE.DataUtils.toHalfFloat(track.wind[i]);
      d[i * 4 + 3] = THREE.DataUtils.toHalfFloat(1);
    }
    const tex = new THREE.DataTexture(d, n, 1, THREE.RGBAFormat, THREE.HalfFloatType);
    tex.minFilter = tex.magFilter = THREE.LinearFilter;
    tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
    tex.needsUpdate = true;
    weatherTex.set(track, { tex, n, dt: track.dt ?? 5 });
  }
  return weatherTex.get(track);
}
export function weatherUniforms(ctx) {
  const w = weatherTexture(ctx);
  return { tWeather: { value: w.tex }, uWeatherN: { value: w.n }, uWeatherDt: { value: w.dt }, uTime: { value: 0 } };
}
export const WEATHER_GLSL = /* glsl */ `
uniform sampler2D tWeather;
uniform float uWeatherN, uWeatherDt, uTime;
vec4 weather(float t) {
  if (uWeatherN < 2.0) return vec4(1.0);
  return texture2D(tWeather, vec2((clamp(t / uWeatherDt, 0.0, uWeatherN - 1.0) + 0.5) / uWeatherN, 0.5));
}`;
