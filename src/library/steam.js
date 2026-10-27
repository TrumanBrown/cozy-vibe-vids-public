// Steam rising from cups, bowls, kettles and cauldrons, as real steam does: thin wisps rise from points on the
// hot surface (the vapor only shows a little above it, where it condenses), bend with kinks that form at the
// surface and are carried up with the steam, grow wider and fainter as they climb, come and go (each wisp
// is evaluated at the moment its steam left the surface, so gaps travel up), and higher up tear into puffs
// that drift apart and vanish within about one vessel width. Small-scale curls are a noise displacement
// carried upward; drafts and gust flurries lean the whole plume. Steam scatters the light around it, so it
// is bright against dark backgrounds and nearly invisible against bright ones (blur.png = local light).
// Every motion has whole cycles per loop (seamless). A window fades everything to zero inside the quad, so
// no edge can show. Sources come from regions of kind 'steam' (point = back rim center, width = rim width
// as a fraction of the frame width) or opts.sources.
//
// Wide vessels (a bowl, a pot, a cauldron: a measured opening over ~300 px at 4K) use the veil model instead (user
// 2026-10-19: the ramen bowl's 6 wisps read as 6 separate sources, and the right side of the bowl had none). Steam
// leaves the whole surface of the opening (plate_prep fits a level ellipse to the rim: regions.json `opening`, with
// `opening_fit` rim / hand / box; hand.json "openings" overrides): a thin haze hugs the surface, and up to 24
// tendrils (about one per 60 px of opening) are each born at a random spot of the surface every 3-7 s, emit for a
// while and let go. A tendril gathers from a patch, necks in, rises and slows as it mixes (age from height:
// -slow * ln(1 - h / (v * slow))), widens, and keeps the history of its wandering root as S-bends that grow with
// height; puffs and thin bright sheets are carried up in it. A shared turbulent flow (gradient noise, slower than
// the steam) bends everything, the draft leans and sways it, and higher up it breaks into patches. Lit by the
// vessel's own light plus what shines through from behind.
//
// Simulated plumes (user 2026-10-19, round 2: the veil was still too wispy; round 4: a cup's two wisps read as
// two separate sources): every vessel with a measured opening, cup or bowl, where tools/steam_sim.py has run for it
// (out/plates/<plate>/steam/<region>/steam.json and its frames) gets a 2D fluid simulation scaled to it, played as a
// looping flipbook (frames loaded per frame through ctx.prefetch, like fire.js): a soft haze over the whole surface
// that curls a little and is gone within about a vessel width. Shaded here: warm light from the plate (bright on the
// dark street), a self-shadow from the steam above, a lean in gusts, nothing below the near rim, nothing over what
// stands in front of the vessel (analyzed regions nearer than it, anything clearly nearer in depth than its near
// rim), and a drink's steam only from `onset_cm` above its surface (steam.json; soup fogs right at it). The wisps
// and the veil are the fallbacks where no plume exists. `sim: false` or `mode: 'wisps'` (on the layer or per region)
// keeps them.
//
// opts: { plate, regions: 'kind:steam' | [names], sources: [{x, y, width} | {opening: [cx, cy, a, b]}], height:
//   fade height in rim widths (default 3.2, capped at ~540 px so big near bowls stay small; veil: in opening
//   half-widths, 1.6, capped at ~800 px), opacity (0.55; veil 0.6), speed: rise speed in rim widths per
//   s (0.55 for wide bowls, 1.3 for cups; veil: half-widths per s, 1.1), wisps (3-7 by width), lean (-1..1: the draft),
//   drafts (gust flurries push the plume), warm: tint color, mode ('auto' | 'wisps' | 'veil'), veil only: tendrils
//   (8-24 by width), density (1.25), filaments (1.2), slow (2.2 s), simulated only: simOpacity (0.5; per region
//   `opacity`), simDensity (1.3), simCap (0.4), shadow (0.12), onset (cm, per region; default from steam.json), sim
//   (true), per: { <region>: overrides } }
import * as THREE from 'three';
import { flurryEnv } from './timeline.js';
import { fetchJson, plateTexture, plateRegions, pickRegions, imagePixels, instancedQuad, PREMUL, GLSL_COMMON } from './overlay.js';

const vert = /* glsl */ `
attribute vec4 aSrc;     // back rim center x, y (px, image coords y down), rim width px, seed (0..1)
attribute vec4 aLook;    // fade height (rim widths), opacity, rise speed (rim widths per s), wisps
attribute vec2 aQuad;    // quad half width, depth below the rim (rim widths)
varying vec2 vLoc;       // across (rim widths, 0 = center), up (rim widths above the back rim)
varying vec2 vQ;         // quad coords -1..1
varying vec4 vSrc;
varying vec4 vLook;
varying vec2 vUv;
void main() {
  float W = aSrc.z;
  vec2 q = position.xy;
  vec2 loc = vec2(q.x * aQuad.x, mix(-aQuad.y, aLook.x * 1.05, q.y * 0.5 + 0.5));
  vec2 p = vec2(aSrc.x + loc.x * W, aSrc.y - loc.y * W);
  vLoc = loc; vQ = q; vSrc = aSrc; vLook = aLook;
  vUv = vec2(p.x / 3840.0, 1.0 - p.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tBlur;
uniform float uPhase, uGust, uLean, uLoop;
uniform vec3 uWarm;
varying vec2 vLoc;
varying vec2 vQ;
varying vec4 vSrc;
varying vec4 vLook;
varying vec2 vUv;
// A kink travelling up with the steam: f cycles per rim width, rising at v rim widths per s, whole cycles per loop.
float wave(float h, float f, float v, float ph) {
  float C = max(1.0, floor(v * f * uLoop + 0.5));
  return sin(TAU * (C / (v * uLoop) * h - C * uPhase) + ph);
}
// Noise scrolled upward at speed v: a whole number of periods per loop.
float upNoise(vec2 p, float sc, float v, float per) {
  float n = max(1.0, floor(v * uLoop * sc / per + 0.5)) * per;
  return pfbm(vec2(p.x * sc, p.y * sc - uPhase * n), vec2(per));
}
void main() {
  float s = vLoc.x, h = vLoc.y;
  float Hm = vLook.x, v = vLook.z, seedf = vSrc.w;
  float win = smoothstep(1.0, 0.75, abs(vQ.x)) * smoothstep(1.0, 0.8, vQ.y);
  if (win <= 0.0) discard;
  float hp = max(h, 0.0);
  // laminar near the hot surface, curling higher up
  float tw = smoothstep(-0.1, 0.55, h);
  vec2 o = vec2(seedf * 13.0, seedf * 7.0);
  vec2 cw = vec2(upNoise(vec2(s, h) + o, 2.2, v, 8.0), upNoise(vec2(s, h) + o + vec2(3.7, 5.1), 2.2, v, 8.0)) - 0.5;
  vec2 cw2 = vec2(upNoise(vec2(s, h) + o + vec2(7.3, 1.1), 4.8, 0.8 * v, 16.0), upNoise(vec2(s, h) + o + vec2(2.9, 8.4), 4.8, 0.8 * v, 16.0)) - 0.5;
  // the draft: the whole plume leans and sways, harder in gust flurries
  float drift = uLean * (0.22 + 0.6 * uGust) * hp * hp + (0.01 + 0.05 * hp) * wave(h, 0.5, v, seedf * 6.0) * (0.6 + 1.2 * uGust);
  // curls grow with height: the warm column turns turbulent a few centimetres up
  float sx = s - drift + (0.30 * cw.x + 0.12 * cw2.x) * tw * (0.5 + 0.8 * hp);
  float hy = h + (0.12 * cw.y + 0.05 * cw2.y) * tw;
  int nW = int(vLook.w + 0.5);
  uint sd = uint(seedf * 9973.0) * 131u + 7u;
  float dens = 0.0;
  for (int k = 0; k < 8; k++) {
    if (k >= nW) break;
    uint kk = sd + uint(k) * 977u;
    float r1 = hash1(kk), r2 = hash1(kk + 1u), r3 = hash1(kk + 2u), r4 = hash1(kk + 3u), r5 = hash1(kk + 4u), r6 = hash1(kk + 5u);
    // where on the surface it rises (spread over the broth, below the back rim) and its height above that point
    float x0 = (float(k) + 0.5) / float(nW) * 0.8 - 0.4 + (r1 - 0.5) * 0.22;
    float u = hy + 0.04 + 0.14 * r2;
    if (u <= 0.0) continue;
    // the root wanders and the column keeps the history of it (a streakline): S-bends that grow as they rise
    float m = (0.012 + 0.16 * u) * wave(u, 1.6 + 1.2 * r3, v, TAU * r4) + (0.006 + 0.07 * u) * wave(u, 4.0 + 2.5 * r5, v, TAU * r6)
            + 0.05 * u * wave(u, 0.45 + 0.3 * r1, v, TAU * r2);
    float cx = x0 * (1.0 - 0.3 * smoothstep(0.0, 0.5, u)) + m;    // the warm column draws the wisps together a little
    float wid = 0.016 + 0.09 * u;
    float prof = exp(-pow((sx - cx) / wid, 2.0));
    if (prof < 0.002) continue;
    // it comes and goes (judged when its steam left the surface, so the gaps rise) and pulses along its length
    float pe = uPhase - u / (v * uLoop);
    float life = 0.18 + 0.82 * smoothstep(0.36, 0.85, 0.5 + 0.38 * sin(TAU * (floor(5.0 + 7.0 * r3) * pe + r1)) + 0.17 * sin(TAU * (floor(13.0 + 9.0 * r6) * pe + r2)));
    float puff = 0.6 + 0.4 * wave(u, 2.4 + r4, v, TAU * r5);
    dens += prof * life * puff * (0.02 / wid + 0.12) * smoothstep(0.0, 0.07, u);
  }
  // higher up the ribbons tear into puffs that drift apart
  float br = upNoise(vec2(sx + 2.0, hy * 0.7), 3.2, v, 8.0);
  dens *= mix(1.0, smoothstep(0.38, 0.72, br), smoothstep(0.08, 0.45, hy));
  // a thin warm haze hugging the broth, where the wisps are born
  dens += 0.07 * exp(-pow(s / 0.4, 2.0)) * smoothstep(-0.16, -0.04, h) * exp(-hp / 0.05) * (0.5 + 0.5 * br);
  float venv = exp(-1.4 * hp / Hm) * (1.0 - smoothstep(0.45 * Hm, Hm, hy));
  float a = clamp(dens * venv * win * vLook.y, 0.0, 0.75);
  if (a < 0.003) discard;
  vec3 bg = texture2D(tBlur, vUv).rgb;
  float L = dot(bg, vec3(0.2126, 0.7152, 0.0722));
  vec3 col = uWarm * (0.26 + 1.3 * L) + bg * 0.6;
  gl_FragColor = vec4(col * a, a);
}`;

// ---- the veil model (wide vessels) ----
const veilVert = /* glsl */ `
attribute vec4 aOpen;    // opening ellipse: center x, y (px, y down), half width a, half height b (px)
attribute vec4 aLook;    // height (units of a), opacity, rise speed (a per s), seed (0..1)
attribute vec2 aSpan;    // quad half width (units of a), lean margin
varying vec2 vPx;
varying vec2 vQ;
varying vec4 vOpen;
varying vec4 vLook;
varying vec2 vUv;
void main() {
  vec2 q = position.xy;
  float a = aOpen.z, b = aOpen.w;
  float x = aOpen.x + q.x * aSpan.x * a + aSpan.y * a * (q.y * 0.5 + 0.5);
  float y = mix(aOpen.y + b + 0.08 * a, aOpen.y - b - aLook.x * a, q.y * 0.5 + 0.5);
  vPx = vec2(x, y); vQ = q; vOpen = aOpen; vLook = aLook;
  vUv = vec2(x / 3840.0, 1.0 - y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const veilFrag = /* glsl */ `
${GLSL_COMMON}
uniform sampler2D tBlur;
uniform float uPhase, uGust, uLean, uLoop, uWispK, uDensK, uSlow;
uniform int uNT;
uniform vec3 uWarm;
varying vec2 vPx;
varying vec2 vQ;
varying vec4 vOpen;
varying vec4 vLook;
varying vec2 vUv;
vec2 grad2(ivec2 c, uint k) { float t = TAU * hash2(c, k); return vec2(cos(t), sin(t)); }
// Periodic gradient noise (smooth, no value-noise blocks), about -0.7..0.7.
float gnoise(vec2 p, vec2 per, uint k) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  vec2 i0 = mod(i, per), i1 = mod(i + 1.0, per);
  float n00 = dot(grad2(ivec2(i0), k), f), n10 = dot(grad2(ivec2(i1.x, i0.y), k), f - vec2(1.0, 0.0));
  float n01 = dot(grad2(ivec2(i0.x, i1.y), k), f - vec2(0.0, 1.0)), n11 = dot(grad2(ivec2(i1), k), f - vec2(1.0));
  return mix(mix(n00, n10, u.x), mix(n01, n11, u.x), u.y);
}
// Two octaves scrolled upward at v units per s, a whole number of periods per loop; about -1..1.
float flow(vec2 p, float sc, float v, float per, uint k) {
  float n = max(1.0, floor(v * uLoop * sc / per + 0.5)) * per;
  vec2 q = vec2(p.x * sc, p.y * sc - uPhase * n);
  return 1.25 * (gnoise(q, vec2(per), k) + 0.5 * gnoise(2.0 * q + 3.7, vec2(2.0 * per), k + 7u));
}
float wave(float pe, float c, float ph) { return sin(TAU * (c * pe + ph)); }
// Seconds since the steam at height h (units of a) left the surface: it rises at v and slows as it mixes.
float ageAt(float h, float v) { return -uSlow * log(max(1.0 - h / (v * uSlow), 0.03)); }
void main() {
  float a = vOpen.z, k = vOpen.w / vOpen.z;
  float s = (vPx.x - vOpen.x) / a;          // across the opening (1 = its edge)
  float y0 = (vOpen.y - vPx.y) / a;         // height above the opening's center row, units of a
  float Hm = vLook.x, v = vLook.z, sd = vLook.w;
  float win = smoothstep(1.0, 0.78, abs(vQ.x)) * smoothstep(1.0, 0.82, vQ.y);
  if (win <= 0.0) discard;
  uint ks = uint(sd * 9973.0) * 131u + 7u;
  float hp = max(y0 + k, 0.0);
  // the shared flow: big S-bends and smaller curls, rising slower than the steam, so its shapes deform
  float tw = smoothstep(-0.15, 0.5, y0);
  vec2 p0 = vec2(s, y0);
  vec2 W1 = vec2(flow(p0, 1.2, 0.5 * v, 6.0, ks), flow(p0, 1.2, 0.5 * v, 6.0, ks + 1u));
  vec2 W2 = vec2(flow(p0 + 0.25 * W1, 3.2, 0.8 * v, 12.0, ks + 2u), flow(p0 + 0.25 * W1, 3.2, 0.8 * v, 12.0, ks + 3u));
  float pe0 = uPhase - ageAt(max(y0, 0.0), v) / uLoop;
  // the draft leans the steam and sways it, harder in gust flurries (judged when the steam left the surface)
  float drift = uLean * (0.15 + 0.6 * uGust) * hp * hp
              + (0.02 + 0.07 * hp) * (0.6 * wave(pe0, 5.0, sd) + 0.4 * wave(pe0, 11.0, 3.1 * sd)) * (0.5 + 1.5 * uGust);
  vec2 q = vec2(s - drift, y0) + (vec2(0.14, 0.05) * W1 * (0.1 + hp) + vec2(0.05, 0.03) * W2 * (0.05 + hp)) * tw;
  // a thin haze over the whole surface, where the steam first condenses (5 depth rows of the opening)
  float haze = 0.0;
  for (int i = 0; i < 5; i++) {
    float wk = -0.8 + 0.4 * float(i);
    float hu = q.y + k * wk, ck = 0.88 * sqrt(1.0 - wk * wk);
    haze += smoothstep(-0.01, 0.06, hu) * exp(-max(hu, 0.0) / 0.13) * smoothstep(ck, 0.55 * ck, abs(q.x));
  }
  float dens = 0.045 * haze / 5.0 * (0.7 + 0.3 * W1.y);
  // tendrils: each slot is born at a random spot of the surface every 3-7 s, emits for a while and lets go
  float fil = 0.0;
  for (int j = 0; j < 32; j++) {
    if (j >= uNT) break;
    uint kj = ks + uint(j) * 7919u;
    float r1 = hash1(kj), r2 = hash1(kj + 1u), r3 = hash1(kj + 2u), r4 = hash1(kj + 3u);
    float C = max(1.0, floor(uLoop / (3.0 + 4.0 * r1) + 0.5));
    float n = mod(floor(pe0 * C + r2), C);
    uint kn = kj * 31u + uint(n) * 2654435761u;
    float rr = 0.86 * sqrt(hash1(kn)), th = TAU * hash1(kn + 1u);
    float s0 = rr * cos(th), w0 = rr * sin(th);
    float hu = q.y + k * w0;                 // above its own row of the surface
    if (hu < -0.03) continue;
    float hh = max(hu, 0.0);
    float age = ageAt(hh, v);
    float pe = uPhase - age / uLoop;
    float f = fract(pe * C + r2);
    float emit = smoothstep(0.1, 0.32, f) * smoothstep(0.88, 0.6, f) * (0.4 + 0.6 * hash1(kn + 2u));
    if (emit <= 0.0) continue;
    // the root wanders while it emits; the column keeps that history: S-bends that grow as they rise
    float cx = s0 + (0.012 + 0.11 * hh) * wave(pe, floor(19.0 + 17.0 * r3), r4)
                  + (0.006 + 0.045 * hh) * wave(pe, floor(53.0 + 31.0 * r4), r3);
    // it gathers from a patch of the surface, necks in as it speeds up, then widens as it mixes
    float wid = 0.05 + 0.07 * exp(-hh / 0.08) + 0.18 * hh;
    float d = (q.x - cx) / wid;
    float prof = exp(-d * d);
    if (prof < 0.004) continue;
    // invisible at the surface, condensing over the first few centimetres, thinning away higher up
    float onset = smoothstep(0.02, 0.3, hu);
    float fade = exp(-hh / 0.7) * smoothstep(Hm, 0.35 * Hm, hh);
    // the same steam spreads over a wider band as it rises
    float m = emit * prof * onset * fade * 0.075 / (wid + 0.05);
    // puffs and thin bright sheets carried up with the steam (functions of when it left the surface)
    float pf = gnoise(vec2(d * 0.7 + 7.0 * r1, pe * 240.0), vec2(64.0, 240.0), kj + 5u);
    float fl = gnoise(vec2(d * 1.7 + 3.0 * r3, pe * 90.0), vec2(64.0, 90.0), kj + 9u);
    float ridge = pow(max(1.0 - abs(fl) * 2.2, 0.0), 4.0);
    dens += m * (0.75 + 0.6 * pf);
    fil += m * ridge * smoothstep(0.04, 0.2, hu);
  }
  // higher up it breaks into patches that thin away
  float br = flow(p0 + 0.2 * W1, 2.0, 0.7 * v, 8.0, ks + 11u);
  float tear = mix(1.0, clamp(0.55 + 0.7 * br, 0.0, 1.0), smoothstep(0.3, 1.0, hp));
  float al = clamp((dens * uDensK + fil * uWispK) * tear * win * vLook.y, 0.0, 0.7);
  if (al < 0.002) discard;
  vec3 bg = texture2D(tBlur, vUv).rgb;
  float L = dot(bg, vec3(0.2126, 0.7152, 0.0722));
  // lit by the same key light as the vessel (it is near), plus what shines through from behind
  vec3 col = uWarm * (0.5 + 1.1 * L) + bg * 0.5;
  gl_FragColor = vec4(col * al, al);
}`;

// ---- simulated steam (tools/steam_sim.py): a looping flipbook of density over the vessel ----
const simVert = /* glsl */ `
uniform vec4 uBox;       // x0, y0, x1, y1 (px at 4K, y down)
varying vec2 vPx;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = vec2(mix(uBox.x, uBox.z, q.x), mix(uBox.w, uBox.y, q.y));
  vUv = vec2(vPx.x / 3840.0, 1.0 - vPx.y / 2160.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const simFrag = /* glsl */ `
uniform sampler2D tA, tB, tBlur, tOcc, tDepth;
uniform float uMix, uScale, uOpacity, uK, uShadow, uGust, uLean, uCap, uOnset, uD0;
uniform vec4 uBox, uOpen, uOccBox;
uniform vec2 uTexel;
uniform vec3 uWarm;
varying vec2 vPx;
varying vec2 vUv;
float dens(vec2 t) {
  float v = mix(texture2D(tA, t).r, texture2D(tB, t).r, uMix);
  return pow(v, 2.2) * uScale;
}
void main() {
  vec2 t = (vPx - uBox.xy) / (uBox.zw - uBox.xy);
  // gust flurries lean it, more the higher it is (sampled from where it came from)
  float h = clamp((uOpen.y - uOpen.w - vPx.y) / max(uOpen.y - uOpen.w - uBox.y, 1.0), 0.0, 1.0);
  t.x -= uLean * uGust * h * h * 0.12;
  float win = smoothstep(0.0, 0.07, t.x) * smoothstep(1.0, 0.93, t.x) * smoothstep(0.0, 0.12, t.y) * smoothstep(1.0, 0.98, t.y);
  // nothing below the near rim (the bowl's own wall)
  float s = (vPx.x - uOpen.x) / uOpen.z;
  float chord = uOpen.w * sqrt(max(0.0, 1.0 - s * s));
  float rimY = uOpen.y + chord;
  win *= smoothstep(rimY + 4.0, rimY - 4.0, vPx.y);
  // a drink's steam shows only uOnset px above its surface (soup fogs right at it: 0): of the surface under this
  // point (the opening's chord), only the part at least uOnset below has steam that shows yet (round 4: a fog film
  // over the tea hid it)
  if (uOnset > 0.0) win *= smoothstep(0.0, 1.0, (rimY - vPx.y - uOnset) / max(2.0 * chord, uOnset));
  // nothing over what stands in front of the vessel: analyzed regions nearer than it (round 4: the cup's steam over
  // the bowl's rim), and anything clearly nearer in depth than its near rim
  win *= 1.0 - texture2D(tOcc, (vPx - uOccBox.xy) / (uOccBox.zw - uOccBox.xy)).r;
  win *= 1.0 - smoothstep(uD0 * 1.06 + 0.01, uD0 * 1.12 + 0.02, texture2D(tDepth, vUv).r);
  if (win <= 0.0) discard;
  float d = dens(t);
  // lit from above (the stall's lamp): steam above this point shades it, so billows get bright tops and darker undersides
  float tau = 0.0;
  for (int i = 1; i <= 6; i++) tau += dens(t - vec2(0.0, float(i * i) * 2.0 * uTexel.y));
  float shade = exp(-uShadow * tau);
  float al = clamp((1.0 - exp(-uK * d)) * uOpacity * win, 0.0, uCap);
  if (al < 0.002) discard;
  vec3 bg = texture2D(tBlur, vUv).rgb;
  float L = dot(bg, vec3(0.2126, 0.7152, 0.0722));
  vec3 col = uWarm * (0.6 + 1.0 * L) * (0.6 + 0.4 * shade) + bg * 0.35;
  gl_FragColor = vec4(col * al, al);
}`;

async function simSteam(ctx, opts, s, meta, dir, tBlur, warm, mkMesh, occ) {
  const mkTex = () => {
    const t = new THREE.Texture();
    t.flipY = false;
    t.generateMipmaps = false;
    t.minFilter = t.magFilter = THREE.LinearFilter;
    return t;
  };
  const tA = mkTex(), tB = mkTex();
  const mat = new THREE.ShaderMaterial({
    vertexShader: simVert, fragmentShader: simFrag, ...PREMUL,
    uniforms: {
      tA: { value: tA }, tB: { value: tB }, tBlur: { value: tBlur },
      // its own look, not the layer's opacity (that is for the wisps and the veil); subtle (user 2026-10-19, round 3:
      // far too heavy, not subtle): a translucent veil, never more than `cap` opaque
      uMix: { value: 0 }, uScale: { value: meta.scale ?? 1 }, uOpacity: { value: s.opacity ?? opts.simOpacity ?? 0.5 },
      uK: { value: s.density ?? opts.simDensity ?? 1.3 }, uShadow: { value: s.shadow ?? opts.shadow ?? 0.12 },
      uCap: { value: s.cap ?? opts.simCap ?? 0.4 },
      // cm above the surface where the steam starts to show (steam_sim: a drink 1, soup 0), in px from the vessel's size
      uOnset: { value: (s.onset ?? meta.onset_cm ?? 0) * (2 * meta.opening[2]) / (meta.size_cm ?? 20) },
      tOcc: { value: occ.tOcc }, uOccBox: { value: new THREE.Vector4(...occ.box) }, tDepth: { value: occ.tDepth }, uD0: { value: occ.D0 },
      uGust: { value: 0 }, uLean: { value: opts.lean ?? 0 },
      uBox: { value: new THREE.Vector4(...meta.box) }, uOpen: { value: new THREE.Vector4(...meta.opening) },
      uTexel: { value: new THREE.Vector2(1 / meta.size[0], 1 / meta.size[1]) },
      uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b) },
    },
  });
  const mesh = mkMesh(mat);
  const cache = new Map(), order = [];
  const url = (i) => `${dir}/s_${String(i).padStart(4, '0')}.jpg`;
  const load = (i) => {
    const key = url(i);
    if (cache.has(key)) return cache.get(key);
    const p = fetch(key).then((r) => { if (!r.ok) throw new Error(`${key}: HTTP ${r.status}`); return r.blob(); }).then((b) => createImageBitmap(b, { colorSpaceConversion: 'none' }));
    cache.set(key, p);
    order.push(key);
    while (order.length > 24) {
      const old = order.shift();
      const q = cache.get(old);
      cache.delete(old);
      q?.then((bm) => bm.close?.());
    }
    return p;
  };
  // the flipbook repeats every meta.frames / meta.fps s (the scene's loop): frame f(t) = t * fps mod frames
  const at = (t) => {
    const f = (((t * meta.fps) % meta.frames) + meta.frames) % meta.frames;
    const i0 = Math.floor(f);
    return [i0, (i0 + 1) % meta.frames, f - i0];
  };
  let cur = null;
  ctx.prefetch(async (t) => {
    const [i0, i1, w] = at(t);
    const bm = await Promise.all([load(i0), load(i1)]);
    cur = { t, bm, w };
  });
  const shown = [null, null];
  return (t, gust) => {
    if (!cur || Math.abs(cur.t - t) > 1e-6) { mesh.visible = false; return; }
    mesh.visible = true;
    [tA, tB].forEach((tx, i) => { if (shown[i] !== cur.bm[i]) { tx.image = cur.bm[i]; tx.needsUpdate = true; shown[i] = cur.bm[i]; } });
    mat.uniforms.uMix.value = cur.w;
    mat.uniforms.uGust.value = gust;
  };
}

export async function steamLayer(ctx, opts) {
  const meta = await plateRegions(opts.plate);
  const all = (opts.sources ?? []).slice();
  for (const g of pickRegions(meta, opts.regions ?? 'kind:steam')) {
    const pt = g.point ?? [(g.bbox[0] + g.bbox[2]) / 2, g.bbox[1]];
    const w = g.width ?? (g.bbox[2] - g.bbox[0]) * 0.8;
    all.push({ name: g.name, id: g.id, disp: g.disp, x: pt[0], y: pt[1], width: w, opening: g.opening, openingFit: g.opening_fit, ...(opts.per?.[g.name] ?? {}) });
  }
  if (!all.length) return null;
  const tBlur = await plateTexture(opts.plate, 'blur.png', { srgb: true });
  const lean = opts.lean ?? 0;
  const warm = new THREE.Color(opts.warm ?? '#ffe9d2');
  const L = ctx.loopSeconds;
  const meshes = [];
  const add = (g, vs, fs, extra = {}) => {
    const mat = new THREE.ShaderMaterial({
      vertexShader: vs, fragmentShader: fs, ...PREMUL,
      uniforms: {
        tBlur: { value: tBlur }, uPhase: { value: 0 }, uGust: { value: 0 }, uLean: { value: lean }, uLoop: { value: L },
        uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b) }, ...extra,
      },
    });
    const mesh = new THREE.Mesh(g, mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 40;
    mesh.userData.noAO = true;
    ctx.add(mesh);
    meshes.push(mesh);
  };
  // Every vessel whose opening was measured (fitted to the rim or set by hand) steams from its whole surface, from the
  // plume tools/steam_sim.py simulated for it, cup or bowl (2026-10-19, round 2: the bowl's veil was still too
  // wispy; round 4: a cup's two wisps read as two separate sources); a missing plume fails the render. With the plume
  // turned off (per.<name>.sim false, or the layer's sim false): the procedural veil for a wide opening (over ~300 px; a
  // guess from a box that includes a mug's handle would turn a near cup into a bowl, so only a measured one), a few
  // wisps otherwise. `mode: 'wisps'` on a source keeps the wisps.
  const opening = (s) => s.opening ?? [s.x, s.y + 0.12 * s.width * 1.7778, 0.55 * s.width, 0.12 * s.width * 1.7778];
  const measured = (s) => !!s.opening && (s.openingFit === 'rim' || s.openingFit === 'hand' || (opts.sources ?? []).includes(s));
  const modeOf = (s) => s.mode ?? opts.mode ?? 'auto';
  const isVeil = (s) => modeOf(s) === 'veil' || (modeOf(s) === 'auto' && measured(s) && 2 * opening(s)[2] * 3840 > 300);
  const sims = [], simulated = new Set();
  // what stands in front of a vessel, built once per plume: a mask of the analyzed regions nearer than it over the
  // plume's box (regions.png ids), and its near rim's depth (its nearest part) for the depth test
  let idImg, depImg, tDepth;
  const inFront = async (s, sm) => {
    idImg ??= await imagePixels(`/out/plates/${opts.plate}/regions.png`);
    depImg ??= await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
    tDepth ??= await plateTexture(opts.plate, 'depth8.png');
    const [cx, cy, a, b] = sm.opening;
    let D0 = 1;
    if (depImg) {
      const { data, width, height } = depImg, v = [];
      const yy = Math.min(height - 1, Math.round(((cy + b + 6) * height) / 2160));
      for (let x = Math.round(((cx - 0.5 * a) * width) / 3840); x <= Math.round(((cx + 0.5 * a) * width) / 3840); x++) v.push(data[(yy * width + x) * 4] / 255);
      v.sort((p, q) => p - q);
      D0 = v[v.length >> 1] ?? 1;
    }
    const x0 = Math.floor(sm.box[0]), y0 = Math.floor(sm.box[1]), x1 = Math.ceil(sm.box[2]), y1 = Math.ceil(sm.box[3]);
    const w = x1 - x0, h = y1 - y0, m = new Uint8Array(w * h);
    const near = new Set(meta.filter((g) => g.id !== s.id && (g.disp ?? 0) > (s.disp ?? 1) * 1.06 + 0.01).map((g) => g.id));
    if (idImg && near.size) {
      const { data, width, height } = idImg;
      for (let y = 0; y < h; y++) {
        const yy = Math.min(height - 1, Math.round(((y0 + y) * height) / 2160));
        for (let x = 0; x < w; x++) {
          if (near.has(data[(yy * width + Math.min(width - 1, Math.round(((x0 + x) * width) / 3840))) * 4])) m[y * w + x] = 255;
        }
      }
    }
    const tOcc = new THREE.DataTexture(m, w, h, THREE.RedFormat, THREE.UnsignedByteType);
    tOcc.unpackAlignment = 1;
    tOcc.minFilter = tOcc.magFilter = THREE.LinearFilter;
    tOcc.needsUpdate = true;
    return { tOcc, box: [x0, y0, x1, y1], tDepth, D0 };
  };
  for (const s of all) {
    if (!s.name || !measured(s) || modeOf(s) === 'wisps' || s.sim === false || opts.sim === false) continue;
    const dir = `/out/plates/${opts.plate}/steam/${s.name}`;
    // a vessel with a measured opening steams from its simulation (lessons L25); wisps only when the scene says so
    const sm = await fetchJson(`${dir}/steam.json`, {
      hint: `run new_video.py life <scene> (tools/steam_sim.py), or set the steam layer's per.${s.name}.sim to false`,
    });
    const occ = await inFront(s, sm);
    sims.push(await simSteam(ctx, opts, s, sm, dir, tBlur, warm, (mat) => {
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
      mesh.frustumCulled = false;
      mesh.renderOrder = opts.renderOrder ?? 40;
      mesh.userData.noAO = true;
      ctx.add(mesh);
      return mesh;
    }, occ));
    simulated.add(s);
    console.log(`steam: ${s.name} uses the simulated plume (${sm.frames} frames at ${sm.fps} fps; near rim depth ${occ.D0.toFixed(3)})`);
  }
  const rest = all.filter((s) => !simulated.has(s));
  const veils = rest.filter(isVeil);
  const wisps = rest.filter((s) => !isVeil(s));
  if (veils.length) {
    const g = instancedQuad(veils.length);
    const aOpen = new Float32Array(veils.length * 4), aLook = new Float32Array(veils.length * 4), aSpan = new Float32Array(veils.length * 2);
    veils.forEach((s, i) => {
      const [cx, cy, a, b] = opening(s);
      const apx = a * 3840;
      // steam fades out within ~1.6 opening half-widths (a ramen bowl: ~18 cm), capped at ~800 px
      const H = s.height ?? Math.min(opts.height ?? 1.6, 800 / apx);
      aOpen.set([cx * 3840, cy * 2160, apx, b * 2160], i * 4);
      aLook.set([H, s.opacity ?? opts.opacity ?? 0.6, s.speed ?? opts.speed ?? 1.1, (i * 0.618 + 0.29) % 1], i * 4);
      const ln = s.lean ?? lean;
      aSpan.set([1.5 + Math.abs(ln) * 0.4 * H * H, 0], i * 2);
    });
    g.setAttribute('aOpen', new THREE.InstancedBufferAttribute(aOpen, 4));
    g.setAttribute('aLook', new THREE.InstancedBufferAttribute(aLook, 4));
    g.setAttribute('aSpan', new THREE.InstancedBufferAttribute(aSpan, 2));
    const apxMax = Math.max(...veils.map((s) => opening(s)[2] * 3840));
    add(g, veilVert, veilFrag, {
      uWispK: { value: opts.filaments ?? 1.2 }, uDensK: { value: opts.density ?? 1.25 }, uSlow: { value: opts.slow ?? 2.2 },
      // about one tendril slot per 60 px of opening (8..24)
      uNT: { value: opts.tendrils ?? Math.min(24, Math.max(8, Math.round((2 * apxMax) / 60))) },
    });
  }
  if (wisps.length) {
    const g = instancedQuad(wisps.length);
    const aSrc = new Float32Array(wisps.length * 4), aLook = new Float32Array(wisps.length * 4), aQuad = new Float32Array(wisps.length * 2);
    wisps.forEach((s, i) => {
      const wpx = Math.max(12, s.width * 3840);
      // real steam fades within about a vessel width or two: a big near bowl must not grow a fog bank (~540 px cap)
      const H = s.height ?? Math.min(opts.height ?? 3.2, Math.max(0.9, 540 / wpx));
      const nW = s.wisps ?? opts.wisps ?? Math.min(7, Math.max(3, Math.round(wpx / 110)));
      // ~12 cm/s: a wide (near) bowl is ~22 cm across, a cup ~9 cm
      const speed = s.speed ?? opts.speed ?? (wpx > 350 ? 0.55 : 1.3);
      aSrc.set([s.x * 3840, s.y * 2160, wpx, (i * 0.618 + 0.13) % 1], i * 4);
      aLook.set([H, s.opacity ?? opts.opacity ?? 0.55, speed, nW], i * 4);
      aQuad.set([0.72 + Math.abs(s.lean ?? lean) * 0.8 * H * H, 0.24], i * 2);
    });
    g.setAttribute('aSrc', new THREE.InstancedBufferAttribute(aSrc, 4));
    g.setAttribute('aLook', new THREE.InstancedBufferAttribute(aLook, 4));
    g.setAttribute('aQuad', new THREE.InstancedBufferAttribute(aQuad, 2));
    add(g, vert, frag);
  }
  ctx.animate((t) => {
    const gust = opts.drafts ? flurryEnv(ctx.timeline, t) : 0;
    for (const m of meshes) {
      m.material.uniforms.uPhase.value = (t % L) / L;
      m.material.uniforms.uGust.value = gust;
    }
    for (const f of sims) f(t, gust);
  });
  return meshes[0];
}
