// Water pouring from a spout or falling over a drop (2026-11-12: the Yuzu Spring's bamboo spout poured frozen through
// sample v2, a miss Truman shouldn't have had to point out). tools/pour_map.py measures each pour once
// (out/plates/<plate>/pour/pour.json and its mask): the stream's center and half width on every row from the brink to the
// foot, the time the water takes to reach each row, its light and dark colors, where it meets the water and how flat
// rings lie there. Key art draws no moving water (Truman, after sample v3: animating over a painted stream looked wrong and
// parts of it never moved): a dry spout's pour is drawn whole here. The water runs along the bottom of the tube, its
// surface seen through the opening; at the end it pours over the whole stretch of rim under that surface as a tongue, which
// pulls into a round stream within about a pipe radius (a free overfall from a part-full pipe; started at one point of
// the rim, it looked like it came out of one spot, Truman 2026-11-15). A fall painted into older key art is measured from
// its trace, and only its paint is moved. Drawn over the plate:
//  - streaks rush down the stream at the water's own speed: value noise in (travel time, across the stream) moves one
//    second of travel per second, so it leaves the brink at a crawl and is a blur of streaks at the foot, where the water
//    falls eight times as fast; averaged over a camera's shutter (1/60 s), calmer near the brink (glassy) and broken lower
//    down, bright where light catches the water and darker between, grained like white pencil on the paper's tooth;
//  - where it meets the water: foam boiling, a choppy patch of short glinting wavelets, short-lived rings at uneven beats,
//    each wobbly, broken into arcs and centered where the stream happened to land (perfect circles every time looked
//    fake, Truman 2026-11-15), and now and then a drop flung up and falling back.
// The plate's own waterfall shimmer (plate_fx.waterfall) is for far falls; a scene with a pour sets it to 0.
// Everything repeats in whole cycles per loop (6 s of streaks, the rings' beat, the chop, a drop every 0.125 s, the boil).
//
// opts: { plate, spout (its name) with lip, lands, angle, depth, contract, axis (pour_map: a dry spout), or fall (0: a
//   traced fall), body (0.22: how much of the clear stream shows where no light catches it), streak (1.1: strength of the
//   light), spec (-0.45: where its specular line runs across it, toward the light), tube (false: no water drawn in the
//   tube), shade (0.55: of the dark between, on a painted fall),
//   contrast (2.2), cell ([0.07, 0.018]: s of travel per noise cell along, long streaks and fine shimmer), across ([4, 9]:
//   cells across the stream), shutter (1/60), grain (0.5), rings: { every (0.3 s: a beat, 30% of beats skipped), life
//   (0.8 s, each 0.55 to 1.45 of it), speed (0.13 m/s), strength (0.75) } | false,
//   chop: { radius (0.05 m), strength (0.6), rate (9 changes a second) } | false,
//   foam: { radius (0.03 m), strength (0.8), boil (10 a second), crown (0.015 m) } | false,
//   drops: { every (0.125 s), life (0.3 s), strength (0.8), size (2.2 px) } | false, renderOrder (6) }
import * as THREE from 'three';
import { fetchJson, plateTexture, PREMUL, GLSL_COMMON } from './overlay.js';

const W = 3840, H = 2160;

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
uniform sampler2D tMask, tRows, tWater;
uniform vec4 uMaskBox;     // the mask image's box (px at 4K)
uniform vec2 uRows;        // the first row (px), the number of rows
uniform float uT, uL;      // s into the loop, the loop (s)
uniform float uTravel, uShut, uStreak, uShade, uContrast, uGrain, uBody, uBodyA;
uniform vec2 uCell, uAcross;   // s of travel per noise cell along, cells across: the long streaks, the fine shimmer
uniform vec3 uLight, uDark;
uniform vec4 uFoot;        // x, y (px), px per meter there, ring aspect (minor / major)
uniform vec4 uRing;        // every (s), life (s), speed (m/s), strength
uniform vec4 uFoam;        // radius (m), strength, boil (a second), crown (m)
uniform vec4 uDrop;        // every (s), life (s), strength, size (px)
uniform vec4 uMouth;       // the spout's opening: center x, y (px), on (0/1), the water's half width across at the lip (share)
uniform vec4 uMouthInv;    // px from its center -> its own coordinates (the inverse of [A B], row by row)
uniform vec2 uMouthD;      // the lip's direction in those coordinates (its lowest point)
uniform vec2 uTube;        // the water's speed in the tube (m/s), unused
uniform vec4 uTop;         // the water's surface at the brink: its middle x, y (px), half the chord (px), its level (unit disk)
uniform vec4 uAxis;        // toward the tube's far end on screen (unit), how far in its surface shows (px), unused
uniform vec2 uSheet;       // the drop (px) over which the tongue closes by 1/e, unused
uniform vec4 uChop;        // the choppy patch: radius (m), strength, changes a second, unused
uniform float uSpec;       // where the specular line runs across the stream (-1 left .. 1 right: toward the light)
varying vec2 vPx;
varying vec2 vUv;

// the stream on a row: center x, half width (px), travel time from the lip (s)
vec4 rowAt(float y) {
  float r = clamp(y - uRows.x, 0.0, uRows.y - 1.0);
  int i = int(floor(r));
  int j = min(i + 1, int(uRows.y) - 1);
  return mix(texelFetch(tRows, ivec2(i, 0), 0), texelFetch(tRows, ivec2(j, 0), 0), r - float(i));
}
// white pencil on black paper: it skips over the paper's tooth, in soft clumps (as poolsteam.js)
float grain(vec2 p) {
  float tooth = pnoise(p / 1.6, vec2(4096.0));
  float clump = pnoise(p / 9.0 + 17.0, vec2(4096.0));
  return clamp(0.35 + 1.1 * smoothstep(0.2, 0.7, tooth) * (0.6 + 0.6 * clump), 0.0, 1.35);
}
// streaks at travel time tau (s from the lip) and across u (-1..1): the pattern moves one second of travel a second,
// averaged over the shutter; periodic over uTravel s of travel (whole cycles per loop). Two scales: long streaks that
// move under half their length a frame, so the eye follows them down the stream, and a fine shimmer that changes every
// frame. One scale of 6 ms cells moved 5.6 cells a frame: every frame was new and the stream flickered in place.
float streaks(float tau, float u) {
  float pc = floor(uTravel / uCell.x + 0.5), pf = floor(uTravel / uCell.y + 0.5);
  float c = 0.0, f = 0.0;
  for (int k = 0; k < 6; k++) {
    float dt = tau - uT + uShut * float(k) / 5.0;
    c += pnoise(vec2(dt / uCell.x, u * uAcross.x + 31.0), vec2(pc, 4096.0));
    f += pnoise(vec2(dt / uCell.y + 5.0, u * uAcross.y + 7.0), vec2(pf, 4096.0));
  }
  return clamp(0.5 + ((0.6 * c + 0.4 * f) / 6.0 - 0.5) * uContrast, 0.0, 1.0);
}
vec4 over(vec4 top, vec4 under) { return top + under * (1.0 - top.a); }

void main() {
  float gr = mix(1.0, grain(vPx), uGrain);
  vec2 d = vPx - uFoot.xy;
  vec4 C = vec4(0.0);
  float wat = smoothstep(0.2, 0.6, texture2D(tWater, vUv).g);

  // where the stream meets the water: a steady stream churns the surface into an uneven patch of broken wavelets that die
  // out within a few cm; clean rings come from single drops. So: short-lived rings at uneven intervals (some skipped),
  // each centered where the stream happened to land, wobbly and broken into arcs, different in width and life, and a
  // choppy glinting patch around the impact (Truman 2026-11-15: perfect circles every time looked fake)
  vec2 gp0 = vec2(d.x, d.y / max(uFoot.w, 0.05));          // on the water plane, px of the scale at the foot
  if (uRing.w > 0.0 && wat > 0.0) {
    float n = floor(uL / uRing.x + 0.5);
    float i1 = floor(uT / uRing.x);
    float lit = 0.0, sh = 0.0;
    for (int k = 0; k < 8; k++) {
      if (float(k - 1) * uRing.x > 1.6 * uRing.y) break;
      float i = i1 - float(k);
      uint id = uint(mod(i, n));
      if (hash1(id * 7u + 5u) < 0.3) continue;                    // not every beat
      float life = uRing.y * (0.55 + 0.9 * hash1(id * 7u + 6u));
      float age = uT - (i + 0.8 * hash1(id * 7u + 1u)) * uRing.x;
      if (age < 0.0 || age > life) continue;
      vec2 off = (vec2(hash1(id * 7u + 3u), hash1(id * 7u + 4u)) - 0.5) * 0.02 * uFoot.z;
      vec2 gp = gp0 - off;
      float rr = length(gp);
      vec2 cs = gp / max(rr, 1e-3);
      float seed = hash1(id * 7u + 8u) * 97.0;
      float wob = 1.0 + 0.3 * (pnoise(cs * 1.3 + vec2(seed, 5.0), vec2(4096.0)) - 0.5);
      float arcs = smoothstep(0.32, 0.62, pnoise(cs * 2.1 + vec2(11.0, seed), vec2(4096.0)));
      float r = (0.008 + uRing.z * (0.7 + 0.6 * hash1(id * 7u + 9u)) * age) * uFoot.z * wob;
      float w = (1.6 + 0.05 * r) * (0.75 + 0.6 * hash1(id * 7u + 2u));
      float f = 1.0 - age / life;
      float amp = f * f * (0.3 + 0.7 * hash1(id * 7u + 2u)) * inversesqrt(1.0 + r / 20.0) * mix(0.15, 1.0, arcs);
      lit += amp * exp(-pow((rr - r) / w, 2.0));
      sh += amp * exp(-pow((rr - r + 1.8 * w) / w, 2.0));
    }
    float a = clamp(lit * uRing.w * gr, 0.0, 0.6) * wat;
    float b = clamp(sh * uRing.w * 0.45, 0.0, 0.3) * wat * (1.0 - a);
    C = vec4(uLight * a + uDark * b, a + b);
  }
  // the chop: short wavelets around the impact, glinting where their crests catch the light, changing fast
  if (uChop.y > 0.0 && wat > 0.0) {
    float rr = length(gp0);
    float ce = exp(-pow(rr / (uChop.x * uFoot.z), 2.0));
    if (ce > 0.02) {
      float nb = floor(uL * uChop.z + 0.5);
      float b = uT * uChop.z, k0 = floor(b);
      uint i0 = uint(mod(k0, nb)), i1 = uint(mod(k0 + 1.0, nb));
      vec2 o0 = vec2(hash1(i0 * 5u + 1u), hash1(i0 * 5u + 2u)) * 512.0;
      vec2 o1 = vec2(hash1(i1 * 5u + 1u), hash1(i1 * 5u + 2u)) * 512.0;
      vec2 q = gp0 / (0.007 * uFoot.z);
      q = vec2(q.x, q.y * 1.8);                                    // wavelets longer across than toward us
      float c0 = pnoise(q + o0, vec2(4096.0)), c1 = pnoise(q + o1, vec2(4096.0));
      float crest = smoothstep(0.6, 0.82, mix(c0, c1, smoothstep(0.0, 1.0, b - k0)));
      float a = clamp(crest * ce * uChop.y * mix(1.0, gr, 0.5), 0.0, 0.5) * wat;
      C = over(vec4(uLight * a, a), C);
    }
  }

  // foam boiling where it lands, a little crown of it above the water: soft round clumps the size of bubbles, a few px
  // across (a 2.6 px noise with a hard threshold drew blocky specks, Truman 2026-11-12: the edges looked sharp)
  if (uFoam.y > 0.0) {
    float rx = uFoam.x * uFoot.z, ry = rx * max(uFoot.w, 0.2) + uFoam.w * uFoot.z;
    float e = 1.0 - smoothstep(0.3, 1.0, length(vec2(d.x / rx, (d.y + 0.5 * uFoam.w * uFoot.z) / ry)));
    if (e > 0.0) {
      float nb = floor(uL * uFoam.z + 0.5);
      float b = uT * uFoam.z, k0 = floor(b);
      uint i0 = uint(mod(k0, nb)), i1 = uint(mod(k0 + 1.0, nb));
      vec2 o0 = vec2(hash1(i0 * 3u + 1u), hash1(i0 * 3u + 2u)) * 512.0;
      vec2 o1 = vec2(hash1(i1 * 3u + 1u), hash1(i1 * 3u + 2u)) * 512.0;
      float sc = max(3.0, 0.004 * uFoot.z);
      vec2 q = mat2(0.866, 0.5, -0.5, 0.866) * vPx;            // turned off the grid, so the clumps don't line up square
      float f0 = 0.65 * pnoise(q / sc + o0, vec2(4096.0)) + 0.35 * pnoise(q / (2.2 * sc) + o0.yx, vec2(4096.0));
      float f1 = 0.65 * pnoise(q / sc + o1, vec2(4096.0)) + 0.35 * pnoise(q / (2.2 * sc) + o1.yx, vec2(4096.0));
      float nf = mix(f0, f1, smoothstep(0.0, 1.0, b - k0));
      float a = clamp(smoothstep(0.4, 0.75, nf) * e * uFoam.y * mix(1.0, gr, 0.5), 0.0, 0.75);
      C = over(vec4(uLight * a, a), C);
    }
  }

  // the stream
  vec2 mUv = (vPx - uMaskBox.xy) / (uMaskBox.zw - uMaskBox.xy);
  if (uBody > 0.5) {
    // the water in the tube, seen through its opening (Truman 2026-11-12: show it running in the tube): its level surface
    // runs from the brink (the chord across the opening at the water's level, uTop) back along the tube (uAxis), as wide
    // as that chord, and fades into the dark a little way in (the lantern's light reaches only the first bit). Its
    // streaks come toward the brink at the water's speed in the tube, the same pattern that then pours over the rim.
    if (uMouth.z > 0.5) {
      vec2 rel = vPx - uMouth.xy;
      vec2 pq = vec2(uMouthInv.x * rel.x + uMouthInv.y * rel.y, uMouthInv.z * rel.x + uMouthInv.w * rel.y);
      float inside = smoothstep(1.0, 0.9, length(pq));
      vec2 q = vPx - uTop.xy;
      float lam = q.y / min(uAxis.y, -0.05);                     // px back along the tube from the brink (it rises)
      float mu = q.x - lam * uAxis.x;                            // px across, level
      float half_ = uTop.z * (1.0 - 0.25 * clamp(lam / uAxis.z, 0.0, 1.0));
      float band = smoothstep(half_ + 2.5, half_ - 2.5, abs(mu)) * smoothstep(-2.0, 1.5, lam) * smoothstep(uAxis.z, 0.3 * uAxis.z, lam) * inside;
      if (band > 0.0) {
        float n = streaks(-lam / uFoot.z / uTube.x, clamp(mu / max(half_, 1.0), -1.0, 1.0));
        float near = exp(-max(lam, 0.0) / (0.35 * uAxis.z));
        float lit = smoothstep(0.45, 0.9, mix(0.5, n, 0.7)) * near;
        float a = clamp((0.1 + 0.5 * uStreak * lit + 0.2 * near) * near * gr, 0.0, 0.65) * band;
        vec3 c = mix(uDark, uLight, clamp(0.2 + 0.8 * lit, 0.0, 1.0));
        C = over(vec4(c * a, a), C);
      }
    }
    if (vPx.y < uRows.x - 3.0 || vPx.y > uRows.x + uRows.y) {
      // above the brink or below the foot: no stream
    } else {
    // nothing is painted under it (a dry spout): the whole stream is drawn here. At the brink it is a tongue as wide as
    // the water in the tube, falling in front of the rim, thin and clear in the middle with thicker edges catching the
    // light, bending over the brink in a smooth glassy band; within about a pipe radius it pulls into a round stream that
    // thins as it speeds up, a specular line down its side toward the light, streaks running down at the water's speed
    // and swellings riding down it that grow as it falls. Its edges are soft, a few px wide like a pencil's: a 1 px edge
    // with a bright line along it looked cut out (Truman 2026-11-12)
    vec4 R = rowAt(vPx.y);
    float dy = vPx.y - uRows.x;
    float sheet = exp(-max(dy, 0.0) / uSheet.x);                 // 1 at the brink, 0 once it is round
    float g = clamp(dy / max(uRows.y - 1.0, 1.0), 0.0, 1.0);
    float pc = floor(uTravel / uCell.x + 0.5);
    float swell = mix(0.03, 0.14, smoothstep(0.0, 0.35, g)) * (1.0 - sheet);
    float hw = R.y * (1.0 - swell + 2.0 * swell * pnoise(vec2((R.z - uT) / uCell.x, 101.0), vec2(pc, 4096.0)));
    float dx = vPx.x - R.x;
    float soft = clamp(0.2 * hw, 1.8, 4.5);
    float edge = smoothstep(-soft, soft, hw - abs(dx)) * smoothstep(-3.0, 2.0, dy);
    if (edge > 0.0) {
      float u = clamp(dx / max(hw, 0.75), -1.0, 1.0);
      // the streaks a little blurred across (two px either side), so no streak is a hard 1 px line on a thin stream
      float du = 2.0 / max(hw, 0.75);
      float n = 0.5 * streaks(R.z, u) + 0.25 * (streaks(R.z, u - du) + streaks(R.z, u + du));
      float lit = smoothstep(0.48, 0.85, n) * mix(0.75, 1.0, smoothstep(0.0, 0.3, g));
      float rim = smoothstep(0.35, 0.8, abs(u)) * (1.0 - smoothstep(0.82, 1.0, abs(u)));
      float spec = exp(-pow((u - uSpec) / 0.22, 2.0)) * (1.0 - 0.7 * sheet) * (0.55 + 0.45 * n);
      float roll = exp(-pow(dy / 5.0, 2.0)) * (1.0 - 0.5 * abs(u)) * (0.6 + 0.4 * n);
      float body = uBodyA * mix(1.0, 0.45 + 0.75 * u * u, sheet);  // the tongue is thin in the middle
      float a = clamp((body + mix(0.15, 0.35, sheet) * rim + 0.6 * uStreak * lit + 0.3 * spec + 0.2 * roll) * gr, 0.0, 0.9) * edge;
      vec3 c = mix(uDark, uLight, clamp(0.45 + 0.55 * max(max(lit, 0.6 * rim), max(spec, roll)), 0.0, 1.0));
      C = over(vec4(c * a, a), C);
    }
    }
  } else if (mUv.x >= 0.0 && mUv.y >= 0.0 && mUv.x <= 1.0 && mUv.y <= 1.0) {
    float m = texture2D(tMask, vec2(mUv.x, 1.0 - mUv.y)).r;
    if (m > 0.01) {
      vec4 R = rowAt(vPx.y);
      float u = clamp((vPx.x - R.x) / max(R.y, 1.0), -1.3, 1.3);
      float g = clamp((vPx.y - uRows.x) / max(uRows.y - 1.0, 1.0), 0.0, 1.0);
      float n = streaks(R.z, u);
      // glassy where it leaves the lip, broken lower down
      float amp = mix(0.45, 1.0, smoothstep(0.0, 0.45, g));
      float a = clamp(smoothstep(0.5, 0.82, n) * amp * uStreak * gr, 0.0, 0.85) * m;
      float b = clamp(smoothstep(0.46, 0.14, n) * amp * uShade, 0.0, 0.6) * m * (1.0 - a);
      C = over(vec4(uLight * a + uDark * b, a + b), C);
    }
  }

  // now and then a drop flung up from the splash, falling back
  if (uDrop.z > 0.0) {
    float n = floor(uL / uDrop.x + 0.5);
    float j1 = floor(uT / uDrop.x);
    float acc = 0.0;
    for (int k = 0; k < 6; k++) {
      if (float(k - 1) * uDrop.x > uDrop.y) break;
      float j = j1 - float(k);
      uint id = uint(mod(j, n));
      float age = uT - (j + hash1(id * 13u + 1u)) * uDrop.x;
      if (age < 0.0 || age > uDrop.y) continue;
      float vx = (hash1(id * 13u + 2u) - 0.5) * 0.6, vy = 0.3 + 0.5 * hash1(id * 13u + 3u);
      vec2 p0 = uFoot.xy + vec2((hash1(id * 13u + 4u) - 0.5) * uFoam.x * uFoot.z, -2.0);
      vec2 pos = p0 + vec2(vx * age, -vy * age + 4.905 * age * age) * uFoot.z;
      if (pos.y > uFoot.y + 1.0) continue;
      vec2 vel = vec2(vx, 9.81 * age - vy) * uFoot.z;
      vec2 a0 = pos - vel * uShut, ab = pos - a0;
      float h = clamp(dot(vPx - a0, ab) / max(dot(ab, ab), 1e-3), 0.0, 1.0);
      acc += exp(-pow(length(vPx - a0 - ab * h) / (uDrop.w * 1.3), 2.0)) * (1.0 - 0.5 * age / uDrop.y);
    }
    float a = clamp(acc * uDrop.z * mix(1.0, gr, 0.5), 0.0, 0.7);
    C = over(vec4(uLight * a, a), C);
  }
  if (C.a < 0.002) discard;
  gl_FragColor = C;
}`;

export async function pourLayer(ctx, opts) {
  const dir = `/out/plates/${opts.plate}/pour`;
  const meta = await fetchJson(`${dir}/pour.json`, { hint: 'run tools/pour_map.py <scene> (new_video.py life does)' });
  const want = opts.lip ? `spout:${opts.spout ?? 'spout'}` : `fall:${opts.fall ?? 0}`;
  const fall = (meta.falls ?? []).find((f) => (f.key ?? `fall:${f.fall}`) === want);
  if (!fall) throw new Error(`${dir}/pour.json has no ${want}: run tools/pour_map.py <scene>`);
  const body = fall.painted === false;
  const [tMask, tWater] = await Promise.all([plateTexture(opts.plate, `pour/${fall.mask}`), plateTexture(opts.plate, 'masks.png')]);
  const n = fall.rows.length;
  const data = new Float32Array(n * 4);
  fall.rows.forEach(([y, cx, hw, tau], i) => data.set([cx, hw, tau, y], i * 4));
  const tRows = new THREE.DataTexture(data, n, 1, THREE.RGBAFormat, THREE.FloatType);
  tRows.minFilter = tRows.magFilter = THREE.NearestFilter;
  tRows.generateMipmaps = false;
  tRows.needsUpdate = true;
  // whole cycles per loop
  const L = ctx.loopSeconds;
  const per = (s) => L / Math.max(1, Math.round(L / s));
  const travel = per(6);
  const cellOf = (s) => travel / Math.max(1, Math.round(travel / s));
  const [cellC, cellF] = opts.cell ?? [0.07, 0.018];
  const [acrossC, acrossF] = opts.across ?? [4, 9];
  const R = opts.rings === false ? null : { every: 0.3, life: 0.8, speed: 0.13, strength: 0.75, ...(opts.rings ?? {}) };
  const F = opts.foam === false ? null : { radius: 0.03, strength: 0.8, boil: 10, crown: 0.015, ...(opts.foam ?? {}) };
  const D = opts.drops === false ? null : { every: 0.125, life: 0.3, strength: 0.8, size: 2.2, ...(opts.drops ?? {}) };
  const K = opts.chop === false ? null : { radius: 0.05, strength: 0.6, rate: 9, ...(opts.chop ?? {}) };
  const col = (c) => { const k = new THREE.Color().setRGB(c[0], c[1], c[2], THREE.SRGBColorSpace); return new THREE.Vector3(k.r, k.g, k.b); };
  const [fx, fy] = fall.foot, ppm = fall.ppm, asp = fall.aspect;
  // the spout's opening (pour_map mouth): the water seen running in the tube, toward the brink
  const mo = body && opts.tube !== false && fall.mouth?.top ? fall.mouth : null;
  // the quad: the stream's box and the splash around its foot (the widest ring, the highest drop), and the opening
  const ringR = R ? (0.01 + R.speed * 1.3 * R.life * 1.45) * ppm * 1.2 + 6 : 0;
  const up = Math.max(ringR * asp, D ? (0.8 * 0.8) / (2 * 9.81) * ppm + 8 : 0, F ? (F.crown + F.radius * asp) * ppm + 6 : 0);
  let box = [Math.max(0, Math.min(fall.box[0], fx - ringR)), Math.max(0, Math.min(fall.box[1], fy - up)),
    Math.min(W, Math.max(fall.box[2], fx + ringR)), Math.min(H, Math.max(fall.box[3], fy + ringR * asp + 6))];
  if (mo) {
    const rx = Math.abs(mo.A[0]) + Math.abs(mo.B[0]) + 8, ry = Math.abs(mo.A[1]) + Math.abs(mo.B[1]) + 8;
    box = [Math.max(0, Math.min(box[0], mo.c[0] - rx)), Math.max(0, Math.min(box[1], mo.c[1] - ry)),
      Math.min(W, Math.max(box[2], mo.c[0] + rx)), Math.min(H, Math.max(box[3], mo.c[1] + ry))];
  }
  // how far into the tube its water's surface shows: about the opening's radius
  const reach = mo ? 1.2 * Math.hypot(mo.low[0] - mo.c[0], mo.low[1] - mo.c[1]) : 1;
  const sheet = mo ? Math.max(2, (mo.contract ?? 0.35) * (mo.radius ?? 0.04) * ppm) : 2;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      tMask: { value: tMask }, tRows: { value: tRows }, tWater: { value: tWater },
      uBox: { value: new THREE.Vector4(...box) }, uMaskBox: { value: new THREE.Vector4(...fall.box) },
      uRows: { value: new THREE.Vector2(fall.rows[0][0], n) },
      uT: { value: 0 }, uL: { value: L }, uTravel: { value: travel },
      uCell: { value: new THREE.Vector2(cellOf(cellC), cellOf(cellF)) }, uAcross: { value: new THREE.Vector2(acrossC, acrossF) },
      uShut: { value: opts.shutter ?? 1 / 60 },
      uStreak: { value: opts.streak ?? 1.1 }, uShade: { value: opts.shade ?? 0.55 }, uContrast: { value: opts.contrast ?? 2.2 },
      uGrain: { value: opts.grain ?? 0.5 }, uLight: { value: col(fall.light) }, uDark: { value: col(fall.dark) },
      uBody: { value: body ? 1 : 0 }, uBodyA: { value: opts.body ?? 0.22 },
      uFoot: { value: new THREE.Vector4(fx, fy, ppm, asp) },
      uRing: { value: R ? new THREE.Vector4(per(R.every), R.life, R.speed, R.strength) : new THREE.Vector4(1, 1, 0, 0) },
      uFoam: { value: F ? new THREE.Vector4(F.radius, F.strength, Math.max(1, Math.round(L * F.boil)) / L, F.crown) : new THREE.Vector4(0.03, 0, 1, 0) },
      uDrop: { value: D ? new THREE.Vector4(per(D.every), D.life, D.strength, D.size) : new THREE.Vector4(1, 1, 0, 1) },
      uMouth: { value: mo ? new THREE.Vector4(mo.c[0], mo.c[1], 1, 0) : new THREE.Vector4(0, 0, 0, 0) },
      uMouthInv: { value: mo ? new THREE.Vector4(...mo.inv) : new THREE.Vector4(1, 0, 0, 1) },
      uMouthD: { value: mo ? new THREE.Vector2(...mo.d) : new THREE.Vector2(0, 1) },
      uTube: { value: new THREE.Vector2(Math.max(0.1, fall.v0 ?? 0.3), 0) },
      uTop: { value: mo ? new THREE.Vector4(mo.top[0], mo.top[1], mo.half, mo.sc) : new THREE.Vector4(0, 0, 0, 1) },
      uAxis: { value: mo ? new THREE.Vector4(mo.axis[0], mo.axis[1], reach, 0) : new THREE.Vector4(0, -1, 1, 0) },
      uSheet: { value: new THREE.Vector2(sheet, 0) },
      uChop: { value: K ? new THREE.Vector4(K.radius, K.strength, Math.max(1, Math.round(L * K.rate)) / L, 0) : new THREE.Vector4(0.05, 0, 1, 0) },
      uSpec: { value: opts.spec ?? -0.45 },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 6;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  console.log(`pour ${want}${body ? ' (drawn whole)' : ''}${mo ? ', from the tube' : ''}: ${(fall.fall_m * 100).toFixed(0)} cm fall at ${fall.z.toFixed(2)} m, `
    + `${Math.round(fall.tau * 1000)} ms from the lip, ${fall.v_foot.toFixed(2)} m/s at the foot (${Math.round(fall.v_foot * ppm)} px/s)`);
  ctx.animate((t) => { mat.uniforms.uT.value = ((t % L) + L) % L; });
  return mesh;
}
