// Steam off a hot spring's whole pool (Truman 2026-11-12, the Yuzu Spring: steam rising off the water nonstop is the
// video's signature motion). tools/pool_steam.py simulates the steam once, in meters, over a strip of hot water that
// wraps across, and saves it as a looping flipbook (out/plates/<plate>/poolsteam/p_*.jpg, poolsteam.json). Here one
// pass lays it over the pool as a stack of slices standing on the water, from the far waterline to the near one, and
// composites them far to near at every pixel: each slice is one row of the water on a ground plane seen from the
// camera (poolsteam.json sheets: its row, distance and px per meter), so far steam is small and fine and near steam
// large and soft, as it is from the rim of a pool. Drawn as separate quads, ten sheets showed as ten horizontal bands
// and their boxes cut straight edges into the steam; thirty slices blended in one pass read as one body of steam.
// Each slice reads the strip at its own place across it, mirrored every other one, at one of three times, so no two
// show the same steam at once. A slice's steam rises only over water (rows.png, spreading as it rises) and hides
// behind whatever stands in front of it (front.png: a character or a floating fruit by where it meets the water,
// anything else by its depth). Lit like steam at night: by the lantern by its distance in 3D (the far steam beside it
// glows, the near steam stays dim and never veils a face), faintly by the snow light elsewhere, and grained like white
// pencil on the black paper (fixed hatching and the paper's tooth), so it reads as drawn, never as an airbrushed glow.
// Gust flurries lean it.
//
// opts: { plate, opacity (0.14 per slice), density (1.6), floor (0.04: density under it shows nothing), cap (0.4),
//   near (2.0: a slice is (z / z_far)^near as strong), reach (560 px: no slice rises higher on screen), onset (10 px),
//   lamp: { x, y (its center on screen, 0..1), z (m), r (m: where its light has fallen to half, 1.1), gain (2.2) },
//   warm ('#ffc58a'), cool ('#a9b8dc'), ambient (0.06), grain (0.45), spread (0.25), lean (0.5), drafts (true) }
import * as THREE from 'three';
import { flurryEnv } from './timeline.js';
import { fetchJson, plateTexture, frameCache, PREMUL, GLSL_COMMON } from './overlay.js';

const W = 3840, H = 2160;
const FRONT_SCALE = 20;           // tools/pool_steam.py FRONT_SCALE
const NMAX = 40;

const vert = /* glsl */ `
uniform vec4 uBox;       // x0, y0, x1, y1 (px at 4K, y down)
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
uniform sampler2D tA0, tB0, tA1, tB1, tA2, tB2, tRows, tFront;
uniform vec3 uMix;
uniform float uScale, uK, uOpacity, uCap, uN, uGust, uLean, uAmb, uGrain, uSpread, uOnset, uFloor;
uniform vec4 uS[${NMAX}];   // row px, px per meter, offset m, mirror (1 or -1)
uniform vec4 uT[${NMAX}];   // z (m), time slot (0..2), weight, reach px
uniform vec4 uStrip;        // strip width m, water row (texels from the top), rows, m per texel
uniform vec4 uLamp;         // x, y (m, y = height above the water), z (m), half-light radius (m)
uniform vec2 uCam;          // focal px, gain of the lamp
uniform vec3 uWarm, uCool;
varying vec2 vPx;
varying vec2 vUv;
float dens(int slot, vec2 t) {
  float v;
  if (slot == 0) v = mix(texture2D(tA0, t).r, texture2D(tB0, t).r, uMix.x);
  else if (slot == 1) v = mix(texture2D(tA1, t).r, texture2D(tB1, t).r, uMix.y);
  else v = mix(texture2D(tA2, t).r, texture2D(tB2, t).r, uMix.z);
  return pow(v, 2.2) * uScale;
}
float rowsAt(float x, float k) { return texture2D(tRows, vec2(clamp(x, 0.0, ${W}.0) / ${W}.0, (k + 0.5) / uN)).r; }
// white pencil on black paper: the pencil skips over the paper's tooth (fixed on the paper), in soft clumps; a hatching
// read as rain falling through the steam (2026-11-12)
float grain(vec2 p) {
  float tooth = pnoise(p / 1.6, vec2(4096.0));
  float clump = pnoise(p / 9.0 + 17.0, vec2(4096.0));
  return clamp(0.35 + 1.1 * smoothstep(0.2, 0.7, tooth) * (0.6 + 0.6 * clump), 0.0, 1.35);
}
void main() {
  float F = texture2D(tFront, vUv).r * 255.0 / ${FRONT_SCALE}.0;
  vec3 C = vec3(0.0);
  float A = 0.0;
  for (int i = 0; i < ${NMAX}; i++) {
    if (float(i) >= uN) break;
    vec4 s = uS[i], q = uT[i];
    float hpx = s.x - vPx.y;
    if (hpx < 0.0 || hpx > q.w) continue;
    float vis = 1.0 - clamp(F - float(i), 0.0, 1.0);
    if (vis <= 0.0) continue;
    float sp = 4.0 + uSpread * hpx;
    float wat = 0.4 * rowsAt(vPx.x, float(i)) + 0.3 * (rowsAt(vPx.x - sp, float(i)) + rowsAt(vPx.x + sp, float(i)));
    if (wat <= 0.002) continue;
    float h = hpx / s.y;
    float row = uStrip.y - h / uStrip.w;
    if (row < 0.5) continue;
    float lean = uLean * uGust * h * h;
    float sx = (vPx.x - ${W / 2}.0) / s.y * s.w + s.z + lean;
    float d = dens(int(q.y + 0.5), vec2(sx / uStrip.x, (row + 0.5) / uStrip.z));
    float win = smoothstep(0.0, uOnset, hpx) * (1.0 - smoothstep(0.6 * q.w, q.w, hpx));
    // the thin haze between the plumes stays clear, so the steam rises in wisps, never as a fog over the whole pool
    float a = (1.0 - exp(-uK * max(d - uFloor, 0.0))) * uOpacity * q.z * wat * vis * win;
    if (a < 0.0005) continue;
    // the lantern's light at this bit of steam, by its distance in 3D, and the snow's cool light
    vec3 P = vec3((vPx.x - ${W / 2}.0) / uCam.x * q.x, h, q.x);
    vec3 dl = P - uLamp.xyz;
    float lit = uCam.y * uLamp.w * uLamp.w / (uLamp.w * uLamp.w + dot(dl, dl));
    vec3 col = uWarm * lit + uCool * uAmb;
    C = C * (1.0 - a) + col * a;
    A = A * (1.0 - a) + a;
  }
  if (A < 0.002) discard;
  float g = mix(1.0, grain(vPx), uGrain);
  float k = min(1.0, uCap / max(A * g, 1e-4));
  gl_FragColor = vec4(C * g * k, A * g * k);
}`;

export async function poolSteamLayer(ctx, opts) {
  const dir = `/out/plates/${opts.plate}/poolsteam`;
  const meta = await fetchJson(`${dir}/poolsteam.json`, { hint: 'run tools/pool_steam.py <scene> (new_video.py life does)' });
  const sheets = meta.sheets ?? [];
  if (!sheets.length) throw new Error(`${dir}/poolsteam.json has no sheets: run tools/pool_steam.py <scene>`);
  if (sheets.length > NMAX) throw new Error(`${dir}/poolsteam.json has ${sheets.length} sheets, at most ${NMAX}`);
  const [tRows, tFront] = await Promise.all([plateTexture(opts.plate, 'poolsteam/rows.png'), plateTexture(opts.plate, 'poolsteam/front.png')]);
  const mkTex = () => {
    const t = new THREE.Texture();
    t.flipY = false;
    t.generateMipmaps = false;
    t.minFilter = t.magFilter = THREE.LinearFilter;
    t.wrapS = THREE.RepeatWrapping;           // the strip wraps across
    t.wrapT = THREE.ClampToEdgeWrapping;
    return t;
  };
  const toffs = [...new Set(sheets.map((s) => s.toff ?? 0))].slice(0, 3);
  while (toffs.length < 3) toffs.push(toffs[0]);
  const pairs = toffs.map(() => [mkTex(), mkTex()]);
  const warm = new THREE.Color(opts.warm ?? '#ffc58a'), cool = new THREE.Color(opts.cool ?? '#a9b8dc');
  const zFar = sheets[0].z, reachMax = opts.reach ?? 560;
  const cam = meta.camera ?? {};
  const f = cam.focal ?? 2700, hc = cam.camHeight ?? 0.4, yh = (cam.horizon ?? 0.47) * H;
  // the lamp in 3D from where it hangs on screen and how far it is
  const lp = opts.lamp ?? {};
  const lz = lp.z ?? zFar + 0.8, lx = ((lp.x ?? 0.5) * W - W / 2) / f * lz, ly = hc + (yh - (lp.y ?? 0.3) * H) * lz / f;
  const uS = [], uT = [];
  sheets.forEach((s, k) => {
    uS.push(new THREE.Vector4(s.y * H, s.ppm, s.offset, s.mirror ? -1 : 1));
    // a slice stands for the water between it and the next: its depth grows as z^2 (rows evenly spaced on screen), so
    // a near slice holds far less steam along the line of sight than a far one seen at a grazing angle
    uT.push(new THREE.Vector4(s.z, toffs.indexOf(s.toff ?? 0), Math.pow(s.z / zFar, opts.near ?? 2.0),
      Math.min(reachMax, (meta.cfg?.fade_to ?? 0.75) * s.ppm)));
  });
  while (uS.length < NMAX) { uS.push(new THREE.Vector4(-1e6, 1, 0, 1)); uT.push(new THREE.Vector4(1, 0, 0, 0)); }
  const top = Math.max(0, Math.min(...sheets.map((s, k) => s.y * H - uT[k].w)));
  const bottom = Math.min(H, Math.max(...sheets.map((s) => s.y * H)) + 2);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      tA0: { value: pairs[0][0] }, tB0: { value: pairs[0][1] }, tA1: { value: pairs[1][0] }, tB1: { value: pairs[1][1] },
      tA2: { value: pairs[2][0] }, tB2: { value: pairs[2][1] }, tRows: { value: tRows }, tFront: { value: tFront },
      uMix: { value: new THREE.Vector3() }, uScale: { value: meta.scale ?? 1.6 }, uK: { value: opts.density ?? 1.6 },
      uOpacity: { value: opts.opacity ?? 0.14 }, uCap: { value: opts.cap ?? 0.4 }, uN: { value: sheets.length },
      uFloor: { value: opts.floor ?? 0.04 },
      uGust: { value: 0 }, uLean: { value: opts.lean ?? 0.5 }, uAmb: { value: opts.ambient ?? 0.06 },
      uGrain: { value: opts.grain ?? 0.45 }, uSpread: { value: opts.spread ?? 0.25 }, uOnset: { value: opts.onset ?? 10 },
      uS: { value: uS }, uT: { value: uT },
      uStrip: { value: new THREE.Vector4(meta.world[0], meta.water_row, meta.size[1], meta.cell) },
      uLamp: { value: new THREE.Vector4(lx, ly, lz, lp.r ?? 1.1) }, uCam: { value: new THREE.Vector2(f, lp.gain ?? 2.2) },
      uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b) }, uCool: { value: new THREE.Vector3(cool.r, cool.g, cool.b) },
      uBox: { value: new THREE.Vector4(0, top, W, bottom) },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 40;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  console.log(`poolsteam: ${sheets.length} slices (${sheets[0].z.toFixed(2)} to ${sheets.at(-1).z.toFixed(2)} m), ${meta.frames} frames at ${meta.fps} fps, `
    + `the lamp at ${lx.toFixed(2)}, ${ly.toFixed(2)}, ${lz.toFixed(2)} m`);

  const frame = frameCache(8 * toffs.length);
  const url = (i) => `${dir}/p_${String(i).padStart(4, '0')}.jpg`;
  const at = (t) => {
    const fr = (((t * meta.fps) % meta.frames) + meta.frames) % meta.frames;
    const i0 = Math.floor(fr);
    return [i0, (i0 + 1) % meta.frames, fr - i0];
  };
  let cur = null;
  ctx.prefetch(async (t) => {
    const loaded = await Promise.all(toffs.map(async (o) => {
      const [i0, i1, w] = at(t + o);
      return { bm: await Promise.all([frame(url(i0)), frame(url(i1))]), w };
    }));
    cur = { t, loaded };
  });
  const shown = pairs.map(() => [null, null]);
  ctx.animate((t) => {
    if (!cur || Math.abs(cur.t - t) > 1e-6) { mesh.visible = false; return; }
    mesh.visible = true;
    cur.loaded.forEach((L, j) => {
      pairs[j].forEach((tx, i) => {
        if (shown[j][i] !== L.bm[i]) { tx.image = L.bm[i]; tx.needsUpdate = true; shown[j][i] = L.bm[i]; }
      });
    });
    mat.uniforms.uMix.value.set(cur.loaded[0].w, cur.loaded[1].w, cur.loaded[2].w);
    mat.uniforms.uGust.value = opts.drafts === false ? 0 : flurryEnv(ctx.timeline, t);
  });
  return mesh;
}
