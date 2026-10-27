// Ambient event: a small creature crawls along a surface of the plate (timeline event type 'critter'). A snail
// glides at a few px per second along its path (image coords), pausing now and then; its head end stretches
// and pulls back as it moves, its eye stalks sway, the shell rocks a hair; a soft contact shadow sits under it
// and a glossy trail stays behind it. The sprite (tools/critter.py: assets/keyart/<scene>/critter_<kind>.png,
// facing right) is lit like its surroundings (the defocused plate around it) and turned along the path.
// It comes out from behind something and goes out of sight behind something: occ.png (tools/plate_prep.py,
// from "critter_occ" in the masks json) holds what stands in front of it (sprite, trail and shadow all hide
// under it), and each path end is pushed out along the path until the whole creature is covered there, facing
// either way (an event may run the path in either direction); anything clearly nearer than the path's own surface
// in the depth map covers it too, and a creature outdoors (its path on lights.png G) hides behind everything indoors
// (the counter's edge, a cup, a stool: the mask is exact where the depth map is soft). An end that can't be covered within 3 body
// lengths is reported ("[page] critter: ...") and the creature fades over its last quarter body length there.
//
// opts: { plate, scene, creature ('snail'), track (0: which of the timeline's critter specs it plays, when
//   events.critter is a list), path: [[x, y], ...] (image coords, the line its foot touches),
//   size: body length px at 4K at the path start, sizeEnd: at the end (perspective) (= size), speed: body
//   lengths per second (0.025), trail (0.22; 0.12 when wet; 0 for anything but a snail or slug), trailLife (s the
//   trail takes to fade: 600; 30 when wet, the rain washes it), wet (it rains on it: autoscene sets it), shadow
//   (0.35), lift: light gain (1),
//   horizon (0.45: eye-level row, 0..1), focal (2700 px): the view angle onto the surface flattens the contact
//   shadow and the trail }
// Size: about twice life at its depth (tools/analyze_plate.py critter_size). On the ramen alley's steps an 8x snail
// (80 px) covered the step's riser behind it and read as floating in front of the step (user 2026-10-19).
import * as THREE from 'three';
import { plateTexture, PREMUL, imagePixels } from './overlay.js';

const W = 3840, H = 2160;

const spriteVert = /* glsl */ `
uniform vec4 uXf;      // anchor x, y (px, y down: the foot point under the shell's center), angle (rad), scale (screen px per sprite px)
uniform vec4 uBox;     // sprite bbox x0, y0, x1, y1 (sprite px) incl. a margin
uniform float uFlip;   // -1 = mirrored (moving left)
uniform vec2 uAnchor;  // anchor in sprite px
varying vec2 vS;       // sprite px (before the crawl warp)
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vec2 s = mix(uBox.xy, uBox.zw, vec2(q.x, 1.0 - q.y));
  vS = s;
  vec2 d = (s - uAnchor) * uXf.w;
  d.x *= uFlip;
  float c = cos(uXf.z), sn = sin(uXf.z);
  vec2 p = uXf.xy + vec2(c * d.x - sn * d.y, sn * d.x + c * d.y);
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const spriteFrag = /* glsl */ `
uniform sampler2D tSprite, tBlur, tLights, tDepth, tOcc;
uniform vec2 uSize;        // sprite texture size
uniform vec4 uBody;        // shell center x, front x, foot y, stretch (1 = rest)
uniform vec4 uEye;         // eye stalk pivot x, y (sprite px), angle (rad), reach (px)
uniform vec3 uTint;        // local light color / sprite mean (gain folded in)
uniform float uAlpha, uBob;
uniform float uFootD;      // the depth of the surface it crawls on (from the path, so it holds behind an occluder)
uniform float uOut;        // 1: it crawls outdoors, so everything indoors (lights.png G = 0) stands in front of it
uniform vec4 uXf;          // as in the vertex shader
uniform float uFlip;
uniform vec2 uAnchor;
uniform float uCell;       // pixel art: the grid cell (px at 4K; 0 = off)
varying vec2 vS;
varying vec2 vUv;
// sprite px under a screen point (px, y down): the vertex transform inverted
vec2 spriteAt(vec2 p) {
  vec2 d = p - uXf.xy;
  float c = cos(uXf.z), sn = sin(uXf.z);
  d = vec2(c * d.x + sn * d.y, -sn * d.x + c * d.y);
  d.x *= uFlip;
  return uAnchor + d / uXf.w;
}
float coverAt(vec2 p, float lod) {
  vec2 s = spriteAt(p);
  if (s.x < 0.0 || s.y < 0.0 || s.x > uSize.x || s.y > uSize.y) return 0.0;
  return textureLod(tSprite, vec2(s.x / uSize.x, 1.0 - s.y / uSize.y), lod).a;
}
void main() {
  // anything clearly nearer than the surface it crawls on hides it (plants, posts, the counter), and so do the
  // occluders it passes behind (occ.png: the pots at its path ends, whose depth is too close to its own)
  float d0 = uFootD, d = texture2D(tDepth, vUv).r;
  float front = (1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, d)) * (1.0 - texture2D(tOcc, vUv).r)
              * mix(1.0, texture2D(tLights, vUv).g, uOut);
  if (front <= 0.0) discard;
  vec2 s = vS;
  // head end stretches about the shell center (the foot slides out, then the shell follows)
  if (s.x > uBody.x) s.x = uBody.x + (s.x - uBody.x) / uBody.w;
  // eye stalks: rotate the upper front part about their base
  vec2 e = s - uEye.xy;
  float wgt = smoothstep(0.0, uEye.w, length(e)) * step(uEye.y - s.y, uEye.w * 1.5) * step(uEye.x - uEye.w * 0.6, s.x) * step(s.y, uEye.y + 4.0);
  float a = uEye.z * wgt;
  s = uEye.xy + vec2(cos(a) * e.x - sin(a) * e.y, sin(a) * e.x + cos(a) * e.y);
  if (s.x < uBody.x) s.y += uBob;
  vec4 c;
  if (uCell > 0.0) {
    // pixel art shows one pixel per grid cell: each cell takes the sprite's average over the cell, solid where the
    // sprite covers most of it, and a dark outline cell rings the silhouette, as pixel-art sprites are drawn. Soft
    // edges blended into the floor, and the greenhouse's beetle and shield bug read as smudges (2026-10-21)
    float lod = max(0.0, log2(uCell / uXf.w) - 0.5);
    vec2 P = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
    vec2 st = vec2(s.x / uSize.x, 1.0 - s.y / uSize.y);
    c = textureLod(tSprite, st, lod);
    if (c.a >= 0.45) {
      // the color from a sharper level (the middle of the cell, premultiplied on upload): a cell keeps one of the
      // sprite's own colors, as a hand-made sprite does, where the whole cell's average turned a glossy beetle gray
      vec4 k = textureLod(tSprite, st, max(0.0, lod - 1.5));
      c = vec4(k.a > 0.05 ? k.rgb / k.a : c.rgb / c.a, 1.0);
    } else {
      float n = max(max(coverAt(P + vec2(uCell, 0.0), lod), coverAt(P - vec2(uCell, 0.0), lod)),
                    max(coverAt(P + vec2(0.0, uCell), lod), coverAt(P - vec2(0.0, uCell), lod)));
      if (n < 0.45) discard;
      c = vec4(0.07, 0.05, 0.045, 0.9);
    }
  } else {
    c = texture2D(tSprite, vec2(s.x / uSize.x, 1.0 - s.y / uSize.y));   // sprite px are y down; the texture is flipped
  }
  float al = c.a * uAlpha * front;
  if (al < 0.003) discard;
  gl_FragColor = vec4(c.rgb * uTint * al, al);
}`;

const dotVert = /* glsl */ `
attribute vec4 aDot;   // x, y (px), radius px, alpha
varying vec2 vL;
varying float vA, vR;
varying vec2 vUv;
void main() {
  vec2 p = aDot.xy + position.xy * (aDot.z + 1.5);
  vL = position.xy * (aDot.z + 1.5) / max(aDot.z, 0.5);
  vA = aDot.w;
  vR = max(aDot.z, 0.5);
  vUv = vec2(p.x / ${W}.0, 1.0 - p.y / ${H}.0);
  gl_Position = vA > 0.0 ? vec4(vUv * 2.0 - 1.0, 0.0, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;
// Both lie on the surface: seen at a low angle they are flattened by 1 / sin(view angle) (uSquash), but never
// thinner than ~0.7 px on screen (thinner, they break up into dots between pixel rows).
const NEARER = /* glsl */ `
uniform sampler2D tDepth, tLights;
uniform float uFootD, uOut;
// 1 where nothing clearly nearer than the surface stands in front (the same test as the sprite's)
float inFront(vec2 uv) {
  return (1.0 - smoothstep(uFootD * 1.06 + 0.01, uFootD * 1.12 + 0.02, texture2D(tDepth, uv).r)) * mix(1.0, texture2D(tLights, uv).g, uOut);
}`;
const dotFrag = /* glsl */ `
uniform sampler2D tBlur, tOcc;
uniform float uSquash;
${NEARER}
varying vec2 vL;
varying float vA, vR;
varying vec2 vUv;
void main() {
  if (vA > 0.0) {
    // trail: a thin glossy film on the surface catching the light around it
    float ry = max(1.0 / uSquash, 0.7 / vR);
    vec2 l = vec2(vL.x, vL.y / ry);
    float k = exp(-dot(l, l) * 2.0) * vA * (1.0 - texture2D(tOcc, vUv).r) * inFront(vUv);
    if (k < 0.003) discard;
    vec3 L = texture2D(tBlur, vUv).rgb;
    gl_FragColor = vec4((L * 1.8 + 0.03) * k, k * 0.35);
  } else discard;
}`;
const shadowFrag = /* glsl */ `
uniform sampler2D tOcc;
uniform float uShadow, uSquash;
${NEARER}
varying vec2 vL;
varying float vA, vR;
varying vec2 vUv;
void main() {
  float ry = max(1.0 / uSquash, 0.7 / vR);
  vec2 l = vec2(vL.x, vL.y / ry);
  float k = exp(-dot(l, l) * 1.6) * uShadow * (1.0 - texture2D(tOcc, vUv).r) * inFront(vUv);
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;

function pathTools(path, size, sizeEnd) {
  const P = path.map(([x, y]) => [x * W, y * H]);
  const seg = [];
  let L = 0;
  for (let i = 1; i < P.length; i++) {
    const l = Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
    seg.push([L, l]);
    L += l;
  }
  const at = (u) => {
    const d = Math.min(Math.max(u, 0), 1) * L;
    let i = seg.findIndex(([s0, l]) => d <= s0 + l);
    if (i < 0) i = seg.length - 1;
    const [s0, l] = seg[i];
    const f = l > 0 ? (d - s0) / l : 0;
    const a = P[i], b = P[i + 1];
    return { x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f, ang: Math.atan2(b[1] - a[1], b[0] - a[0]), size: size + (sizeEnd - size) * (d / L) };
  };
  return { L, at };
}

// Sprite pose for travel direction th (rad, screen, y down). The sprite faces right: moving left-ish it is
// mirrored and turned by th - PI, so it stays upright whichever way it crawls.
export function critterFacing(th) {
  return Math.cos(th) >= 0 ? { flip: 1, ang: th } : { flip: -1, ang: th - Math.PI };
}

// Push each end of the path (px) out along it until the creature (its opaque sprite pixels `body`, posed by
// critterFacing) is hidden there facing either way: under occ (0..1 at a px) or off the frame. Up to 3 body
// lengths, plus a quarter body length so the fade at the ends happens out of sight. Returns the new path and
// the ends that could not be hidden.
export function hideEnds(path, body, anchor, len, sizes, occ, nearer = () => 0) {
  const hid = (x, y, e) => (x < 0 || y < 0 || x >= W || y >= H ? 1 : Math.max(occ(x, y), nearer(x, y, e)));
  const cover = (x, y, th, size, e) => {
    const { flip, ang } = critterFacing(th), k = size / len, c = Math.cos(ang), s = Math.sin(ang);
    let h = 0;
    for (const [px, py] of body) {
      const dx = (px - anchor[0]) * k * flip, dy = (py - anchor[1]) * k;
      h += hid(x + c * dx - s * dy, y + s * dx + c * dy, e);
    }
    return h / Math.max(1, body.length);
  };
  const out = path.map((q) => q.slice());
  const open = [];
  for (const end of [0, 1]) {
    const n = out.length;
    const b = end ? out[n - 1] : out[0], a = end ? out[n - 2] : out[1];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, ux = (b[0] - a[0]) / l, uy = (b[1] - a[1]) / l;
    const size = sizes[end], th = Math.atan2(uy, ux);
    let got = -1;
    for (let k = 0; k <= 60 && got < 0; k++) {
      const d = k * 0.05 * size, x = b[0] + ux * d, y = b[1] + uy * d;
      if (Math.min(cover(x, y, th, size, end), cover(x, y, th + Math.PI, size, end)) >= 0.99) got = d;
    }
    if (got < 0) { open.push(end ? 'end' : 'start'); continue; }
    const d = got + 0.25 * size, q = [b[0] + ux * d, b[1] + uy * d];
    if (end) out.push(q); else out.unshift(q);
  }
  return { path: out, open };
}

// Progress (0..1 of the path, in the event's direction) at tau seconds, with pauses (fractions of the time).
export function critterProgress(ev, tau) {
  const T = ev.dur;
  const pauses = (ev.pauses ?? []).map((p) => [p * T, ev.pauseLen * T]);
  const move = T - pauses.reduce((s, [, l]) => s + l, 0);
  let tm = 0;
  for (const [p0, l] of pauses) {
    if (tau <= p0) break;
    tm -= Math.min(l, tau - p0);
  }
  tm += tau;
  const u = Math.min(Math.max(tm / move, 0), 1);
  // ease in and out of each pause (a slow start and stop) with a smooth global profile
  return u;
}

// Seconds into the event at which the creature reached progress u0 (0..1 along its way): the inverse of
// critterProgress (every pause that began before then adds its length). The trail's age at a point comes from it.
export function critterTimeAt(ev, u0) {
  const T = ev.dur;
  const pauses = (ev.pauses ?? []).map((p) => [p * T, ev.pauseLen * T]).sort((a, b) => a[0] - b[0]);
  const move = T - pauses.reduce((s, [, l]) => s + l, 0);
  let tau = Math.min(Math.max(u0, 0), 1) * move;
  for (const [p0, l] of pauses) if (p0 < tau) tau += l;
  return tau;
}

export async function critterLayer(ctx, opts) {
  const track = opts.track ?? 0;
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'critter' && (e.track ?? 0) === track);
  if (!evs.length || !opts.path?.length) return null;
  const kind = opts.creature ?? 'snail';
  // only a snail or slug glides on a foot that stretches, sways its eye stalks and leaves a film; a ladybug or a
  // beetle walks rigid and leaves nothing (the pixel greenhouse's ladybug, 2026-10-21)
  const slimy = kind === 'snail' || kind === 'slug';
  const base = `/assets/keyart/${opts.scene}/critter_${kind}`;
  const meta = await fetch(`${base}.json`).then((r) => r.json());
  const tSprite = await spriteTexture(`${base}.png`, opts);
  // with several critters each has its own occluders (occ_<track>.png, plate_prep render_occluders): another
  // track's cover (a planter a floor beetle goes behind) must not hide this one walking on it
  const own = await imagePixels(`/out/plates/${opts.plate}/occ_${track}.png`);
  const occFile = own ? `occ_${track}.png` : 'occ.png';
  const [tBlur, tLights, tDepth, tOcc] = await Promise.all([plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'lights.png'),
    plateTexture(opts.plate, 'depth8.png'), plateTexture(opts.plate, occFile, { optional: true })]);
  const [bx0, , bx1] = meta.bbox;
  const len = bx1 - bx0;
  const shellC = (meta.shell_x[0] + meta.shell_x[1]) / 2;
  const anchor = [shellC, meta.foot_y];
  // the path ends go out of sight behind the occluders (or off the frame)
  const sizes = [opts.size ?? 70, opts.sizeEnd ?? opts.size ?? 70];
  const body = spriteBody(await imagePixels(`${base}.png`), meta.bbox);
  const occ = own ?? await imagePixels(`/out/plates/${opts.plate}/occ.png`);
  // the same nearer-than-its-surface test as the sprite shader, against the depth at each path end
  const dep = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
  // outdoors (lights.png G): a creature on the street is behind everything inside the shop (counter, cups, stools)
  const lit = await imagePixels(`/out/plates/${opts.plate}/lights.png`);
  const { occAt, depAt, outAt } = plateSamplers(occ, dep, lit);
  const P0 = opts.path.map(([x, y]) => [x * W, y * H]);
  // the surface under a vertex: the farthest depth within ~8 px (the depth map is soft at an occluder's edge)
  const surfD = (x, y) => Math.min(...[-8, 0, 8].flatMap((dx) => [-6, 2, 8].map((dy) => depAt(x + dx, y + dy))));
  const footD = [surfD(...P0[0]), surfD(...P0[P0.length - 1])];
  const outdoor = opts.outdoor ?? (P0.reduce((a, [x, y]) => a + outAt(x, y + 2), 0) / P0.length > 0.5);
  const nearer = (x, y, e) => {
    const d0 = footD[e], d = depAt(x, y);
    const dz = Math.min(1, Math.max(0, (d - (d0 * 1.06 + 0.01)) / (d0 * 0.06 + 0.01)));
    return outdoor ? Math.max(dz, 1 - outAt(x, y)) : dz;
  };
  const hidden = hideEnds(P0, body, anchor, len, sizes, occAt, nearer);
  for (const e of hidden.open) {
    console.warn(`critter: the path ${e} is in plain sight (nothing in occ.png covers the ${kind} there within 3 body lengths): `
      + 'add what it should hide behind to "critter_occ" in the masks json or move that end; it fades in view there');
  }
  const P = pathTools(hidden.path.map(([x, y]) => [x / W, y / H]), sizes[0], sizes[1]);
  const footDAt = footDepthAlong(P0, hidden.path, surfD);
  const tex = { tSprite, tBlur, tLights, tDepth, tOcc };
  const mat = spriteMaterial(tex, meta, anchor, opts);
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.frustumCulled = false;
  quad.renderOrder = opts.renderOrder ?? 7;
  const { trail, shadow, aDot, aSh } = trailAndShadow(tex, opts);
  for (const m of [shadow, trail, quad]) { m.userData.noAO = true; m.visible = false; ctx.add(m); }
  const lightAt = await plateLight(opts.plate);
  ctx.animate(critterFrame({ evs, P, mat, quad, trail, shadow, aDot, aSh, meta, slimy, footDAt, outdoor, lightAt, opts }));
  return quad;
}

async function spriteTexture(url, opts) {
  const tSprite = await new THREE.TextureLoader().loadAsync(url);
  tSprite.colorSpace = THREE.SRGBColorSpace;
  tSprite.generateMipmaps = true;
  tSprite.minFilter = THREE.LinearMipmapLinearFilter;
  tSprite.magFilter = THREE.LinearFilter;
  tSprite.anisotropy = 4;
  // pixel art averages the sprite over each grid cell: premultiplied, so the mip levels average color by coverage
  if (opts.pixelGrid?.cell) tSprite.premultiplyAlpha = true;
  return tSprite;
}

// The sprite's opaque points on a 33 x 17 grid over its bbox: what hideEnds must see covered at a path end.
function spriteBody(spr, [bx0, by0, bx1, by1]) {
  const body = [];
  for (let j = 0; j <= 16; j++) {
    for (let i = 0; i <= 32; i++) {
      const x = Math.round(bx0 + (bx1 - bx0) * i / 32), y = Math.round(by0 + (by1 - by0) * j / 16);
      if (x < spr.width && y < spr.height && spr.data[(y * spr.width + x) * 4 + 3] > 128) body.push([x, y]);
    }
  }
  return body;
}

// The plate's occluders, depth and outdoor mask at a 4K pixel (each 0..1; occ.png missing: 0, lights.png missing: 1).
function plateSamplers(occ, dep, lit) {
  const occAt = (x, y) => {
    if (!occ) return 0;
    const ix = Math.min(occ.width - 1, Math.round(x * occ.width / W)), iy = Math.min(occ.height - 1, Math.round(y * occ.height / H));
    return occ.data[(iy * occ.width + ix) * 4] / 255;
  };
  const depAt = (x, y) => {
    if (!dep) return 0;
    const ix = Math.min(dep.width - 1, Math.max(0, Math.round(x * dep.width / W))), iy = Math.min(dep.height - 1, Math.max(0, Math.round(y * dep.height / H)));
    return dep.data[(iy * dep.width + ix) * 4] / 255;
  };
  const outAt = (x, y) => {
    if (!lit) return 1;
    const ix = Math.min(lit.width - 1, Math.max(0, Math.round(x * lit.width / W))), iy = Math.min(lit.height - 1, Math.max(0, Math.round(y * lit.height / H)));
    return lit.data[(iy * lit.width + ix) * 4 + 1] / 255;
  };
  return { occAt, depAt, outAt };
}

// The surface's depth along the path (u 0..1): sampled under the given vertices (on the visible surface), held over
// the extensions behind the occluders, so whatever covers the creature there stays in front of it.
function footDepthAlong(P0, hiddenPath, surfD) {
  const vD = P0.map(([x, y]) => surfD(x, y));
  const hv = hiddenPath.map((q) => { const i = P0.findIndex((o) => o[0] === q[0] && o[1] === q[1]); return i; });
  const vDep = hv.map((i, k) => (i >= 0 ? vD[i] : k === 0 ? vD[0] : vD[vD.length - 1]));
  const cum = [0];
  for (let k = 1; k < hiddenPath.length; k++) cum.push(cum[k - 1] + Math.hypot(hiddenPath[k][0] - hiddenPath[k - 1][0], hiddenPath[k][1] - hiddenPath[k - 1][1]));
  return (u) => {
    const d = Math.min(Math.max(u, 0), 1) * cum[cum.length - 1];
    let k = cum.findIndex((c) => c >= d);
    if (k <= 0) return vDep[0];
    const f = (d - cum[k - 1]) / Math.max(1e-6, cum[k] - cum[k - 1]);
    return vDep[k - 1] + (vDep[k] - vDep[k - 1]) * f;
  };
}

function spriteMaterial({ tSprite, tBlur, tLights, tDepth, tOcc }, meta, anchor, opts) {
  const [bx0, by0, bx1, by1] = meta.bbox;
  const len = bx1 - bx0;
  const shellC = anchor[0];
  return new THREE.ShaderMaterial({
    vertexShader: spriteVert, fragmentShader: spriteFrag, ...PREMUL,
    uniforms: {
      tSprite: { value: tSprite }, tBlur: { value: tBlur }, tLights: { value: tLights }, tDepth: { value: tDepth }, tOcc: { value: tOcc }, uFootD: { value: 0 }, uOut: { value: 0 },
      uXf: { value: new THREE.Vector4() }, uBox: { value: new THREE.Vector4(bx0 - 8, by0 - 8, bx1 + 8, by1 + 8) }, uFlip: { value: 1 },
      uAnchor: { value: new THREE.Vector2(...anchor) }, uSize: { value: new THREE.Vector2(...meta.size) },
      uBody: { value: new THREE.Vector4(shellC, bx1, meta.foot_y, 1) },
      uEye: { value: new THREE.Vector4(bx1 - 0.16 * len, by0 + 0.38 * (by1 - by0), 0, 0.22 * len) },
      uTint: { value: new THREE.Vector3(1, 1, 1) }, uAlpha: { value: 0 }, uBob: { value: 0 },
      uCell: { value: opts.pixelGrid?.cell ?? 0 },
    },
  });
}

// The trail dots and the contact shadow, one instanced mesh each.
const ND = 400;
function trailAndShadow({ tBlur, tLights, tDepth, tOcc }, opts) {
  const dg = new THREE.InstancedBufferGeometry();
  dg.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  dg.setIndex([0, 1, 2, 0, 2, 3]);
  dg.instanceCount = ND;
  const aDot = new THREE.InstancedBufferAttribute(new Float32Array(ND * 4), 4);
  aDot.setUsage(THREE.DynamicDrawUsage);
  dg.setAttribute('aDot', aDot);
  const trail = new THREE.Mesh(dg, new THREE.ShaderMaterial({ vertexShader: dotVert, fragmentShader: dotFrag, ...PREMUL, uniforms: { tBlur: { value: tBlur }, tOcc: { value: tOcc }, uSquash: { value: 3 }, tDepth: { value: tDepth }, tLights: { value: tLights }, uFootD: { value: 0 }, uOut: { value: 0 } } }));
  trail.frustumCulled = false;
  trail.renderOrder = (opts.renderOrder ?? 7) - 0.5;
  const sg = new THREE.InstancedBufferGeometry();
  sg.setAttribute('position', dg.getAttribute('position'));
  sg.setIndex([0, 1, 2, 0, 2, 3]);
  sg.instanceCount = 1;
  const aSh = new THREE.InstancedBufferAttribute(new Float32Array(4), 4);
  aSh.setUsage(THREE.DynamicDrawUsage);
  sg.setAttribute('aDot', aSh);
  const shadow = new THREE.Mesh(sg, new THREE.ShaderMaterial({
    vertexShader: dotVert.replace('gl_Position = vA > 0.0 ?', 'gl_Position = vA != 0.0 ?'), fragmentShader: shadowFrag, ...PREMUL,
    uniforms: { uShadow: { value: opts.shadow ?? 0.35 }, uSquash: { value: 3 }, tOcc: { value: tOcc }, tDepth: { value: tDepth }, tLights: { value: tLights }, uFootD: { value: 0 }, uOut: { value: 0 } },
  }));
  shadow.frustumCulled = false;
  shadow.renderOrder = (opts.renderOrder ?? 7) - 0.6;
  return { trail, shadow, aDot, aSh };
}

// Local light at the creature: the blurred plate around it (read once per frame from a small canvas copy).
async function plateLight(plate) {
  const blurImg = await new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.src = `/out/plates/${plate}/blur.png`; });
  const cv = document.createElement('canvas');
  cv.width = blurImg.width; cv.height = blurImg.height;
  const c2 = cv.getContext('2d', { willReadFrequently: true });
  c2.drawImage(blurImg, 0, 0);
  return (x, y, r) => {
    const sx = blurImg.width / W, k = Math.max(1, Math.round(r * sx));
    const d = c2.getImageData(Math.max(0, Math.round(x * sx - k)), Math.max(0, Math.round(y * sx - k)), 2 * k, 2 * k).data;
    let s = [0, 0, 0], n = 0;
    for (let i = 0; i < d.length; i += 4) { s[0] += d[i]; s[1] += d[i + 1]; s[2] += d[i + 2]; n++; }
    return s.map((v) => Math.pow(v / n / 255, 2.2));
  };
}

// One frame: where the creature is along its path, how it moves and is lit, its contact shadow and its trail.
function critterFrame({ evs, P, mat, quad, trail, shadow, aDot, aSh, meta, slimy, footDAt, outdoor, lightAt, opts }) {
  const [bx0, by0, bx1, by1] = meta.bbox;
  const len = bx1 - bx0;
  const FADE = 90;   // the trail dries over this long after the creature has gone
  const horizon = (opts.horizon ?? 0.45) * H, focal = opts.focal ?? 2700;
  const trailAmt = opts.trail ?? (slimy ? (opts.wet ? 0.12 : 0.22) : 0), trailLife = opts.trailLife ?? (opts.wet ? 30 : 600);
  return (t) => {
    const ev = evs.find((e) => t >= e.t && t <= e.t + e.dur + FADE);
    for (const m of [shadow, trail, quad]) m.visible = !!ev;
    if (!ev) return;
    const tau = Math.min(t - ev.t, ev.dur);
    const dry = Math.max(0, 1 - Math.max(0, t - ev.t - ev.dur) / FADE);
    const u0 = critterProgress(ev, tau);
    const fwd = ev.to >= ev.from;
    const u = ev.from + (ev.to - ev.from) * u0;
    const p = P.at(u);
    // facing: along the path in the direction of travel, upright either way
    const { flip, ang } = critterFacing(fwd ? p.ang : p.ang + Math.PI);
    const scale = p.size / len;
    // crawl cycle: the head end reaches out and draws back (~4 s), the eye stalks sway (~6 s), a slight bob
    const cyc = 2 * Math.PI * tau / 4.2, eye = 2 * Math.PI * tau / 6.3;
    const moving = slimy && u0 > 0 && u0 < 1 ? 1 : 0;
    const m = mat.uniforms;
    m.uXf.value.set(p.x, p.y, ang, scale);
    if (m.uCell.value > 0) {
      const mg = 8 + 1.5 * m.uCell.value / Math.max(scale, 1e-3);   // room for the outline cell around the silhouette
      m.uBox.value.set(bx0 - mg, by0 - mg, bx1 + mg, by1 + mg);
    }
    const fd = footDAt(u);
    for (const U of [m, trail.material.uniforms, shadow.material.uniforms]) { U.uFootD.value = fd; U.uOut.value = outdoor ? 1 : 0; }
    m.uFlip.value = flip;
    m.uBody.value.w = 1 + moving * 0.06 * Math.sin(cyc);
    m.uEye.value.z = slimy ? 0.12 * Math.sin(eye) + 0.05 * Math.sin(2.3 * eye + 1.1) : 0;
    m.uBob.value = slimy ? 0.6 * Math.sin(cyc + 1.0) / Math.max(scale, 0.05) * 0.02 : 0;
    // fades over the last quarter body length at each end (out of sight there: hideEnds)
    const edge = Math.min(u * P.L, (1 - u) * P.L) / (0.25 * p.size);
    m.uAlpha.value = Math.min(1, Math.max(0, edge)) * (t - ev.t <= ev.dur ? 1 : 0);
    const L = lightAt(p.x, p.y - p.size * 0.3, p.size * 0.6);
    const lum = 0.2126 * L[0] + 0.7152 * L[1] + 0.0722 * L[2];
    const gain = Math.min(1.5, Math.max(0.25, (lum * 1.6 + 0.02) / meta.lum)) * (opts.lift ?? meta.lift ?? 1);
    const chroma = L.map((v) => (v + 0.004) / (lum + 0.004));
    m.uTint.value.set(...chroma.map((c) => gain * (0.55 + 0.45 * c)));
    // contact shadow under the foot, the trail behind, both lying on the surface: seen from sinE above it
    const sinE = Math.min(0.8, Math.max(0.06, (p.y - horizon) / focal)), squash = Math.min(12, 1 / sinE);
    shadow.material.uniforms.uSquash.value = squash;
    trail.material.uniforms.uSquash.value = squash;
    aSh.array.set([p.x, p.y + 0.5, p.size * 0.45, -1], 0);
    aSh.needsUpdate = true;
    shadow.material.uniforms.uShadow.value = (opts.shadow ?? 0.35) * Math.min(1, Math.max(0, edge)) * (t - ev.t <= ev.dur ? 1 : 0);
    // The film it leaves is glossiest fresh and fades as it dries, or within half a minute in the rain (on wet
    // stone a slime trail barely shows): each point's age is the time since the creature passed it.
    const span = Math.abs(u - ev.from);
    const n = Math.min(ND, Math.ceil(span * P.L / 3));
    const now = t - ev.t, dirU = ev.to - ev.from;
    for (let i = 0; i < ND; i++) {
      if (i >= n) { aDot.array[i * 4 + 3] = 0; continue; }
      const uu = fwd ? u - (i + 1) * 3 / P.L : u + (i + 1) * 3 / P.L;
      const age = Math.max(0, now - critterTimeAt(ev, (uu - ev.from) / dirU));
      const a = trailAmt * dry * Math.exp(-age / trailLife) * Math.min(1, (i + 1) / 6);
      if (a < 0.002) { aDot.array[i * 4 + 3] = 0; continue; }
      const q = P.at(uu);
      aDot.array.set([q.x, q.y + 0.5, Math.max(0.8, q.size * 0.035), a], i * 4);
    }
    aDot.needsUpdate = true;
  };
}
