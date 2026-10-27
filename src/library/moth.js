// A moth visiting a lamp (timeline event type 'moth'): it comes in out of the dark, circles the light in erratic
// loops (a wavering orbit with sudden small darts, as moths do at a light), lands on the lit pane now and then and
// sits there a few seconds as a dark silhouette with its wings folded, and flies off. Its flight is a pure function
// of time (event constants from the timeline). It is small (about twice life, ~9 px across at the ramen alley's
// lamp) with fast wingbeats blurred over the shutter. Lighting: the side facing the lamp is lit by it (the lamp's
// own glow color, falling off with distance), so it is a bright fleck beside or behind the light and a dark shape
// with a glowing fringe in front of it. It hides behind the lamp's body when it passes behind it (the lamp's
// region), behind anything nearer in depth (posts, poles) and behind everything indoors (lights.png G = 0), unless the
// lamp itself hangs under a roof on our side (`covered`: a porch lantern, where the indoors mask covers the whole porch
// and hid the moth everywhere, 2026-10-21).
// Landings happen only while it is in front of the lamp, so it never flies through the lamp body.
//
// opts: { plate, lamp: region name (its bbox gives the light's center and size), center: [x, y] (image coords:
//   the light's center; default the bbox's center), unit: px of the lamp's half width (default: a third of the
//   bbox width), size: wingspan px (9), pane: [u0, v0, u1, v1] the face it lands on (lamp units, default
//   [-0.65, -0.7, 0.65, 0.6]), front: the face's distance in front of the center (lamp units, 1.05), unitM: m per
//   lamp unit (0.33: for the depth test), shutter (1/60), covered (false), color: [r, g, b] linear glow color (default:
//   the blurred plate at the center), silhouette (false: with the light behind it the moth is a dark shape with a glowing
//   fringe; pixel looks set it, where its lit side read as a gray patch over a white-hot flame), detail (false: the
//   soft blob that suits a moth a few px across; true: wing shapes, antennae, a darker body, shaded wings and soft
//   edges, for a moth 40 px or more across, best with a shutter near 1/200 so each frame catches the wings in about one
//   pose: the Burdock Shelter's 48 px blob read as a light overlay, 2026-10-25) }
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { plateTexture, plateRegions, imagePixels, PREMUL } from './overlay.js';
import { toLin } from './util.js';

const W = 3840, H = 2160;
const S = 6;    // samples across the shutter

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
uniform sampler2D tDepth, tLights, tRegion;
uniform vec4 uM[${S}];     // per shutter sample: x, y (px), heading (rad), wing opening (0 folded .. 1 spread)
uniform vec4 uLook;        // wingspan px, depth8 of the moth, behind the lamp (1/0), lamp region id
uniform float uCovered;    // 1: the lamp hangs under a roof on our side (a porch): the indoors mask doesn't hide the moth
uniform vec3 uCol;         // lit color (linear, premultiplied later)
uniform vec3 uRim;         // back-lit fringe color
uniform float uCell;       // pixel art: the grid cell (px at 4K; 0 = off)
uniform vec2 uOrigin;      // the grid's origin (px)
uniform float uDetail;     // 1: the detailed silhouette (mothDetail); 0: the soft blob of the first moths
varying vec2 vPx, vUv;
// signed distance to a convex polygon given counterclockwise (+ outside): the largest of its edges' distances
float sdTri(vec2 p, vec2 a, vec2 b, vec2 c) {
  vec2 e0 = b - a, e1 = c - b, e2 = a - c;
  return max(max(dot(normalize(vec2(e0.y, -e0.x)), p - a), dot(normalize(vec2(e1.y, -e1.x)), p - b)), dot(normalize(vec2(e2.y, -e2.x)), p - c));
}
float sdQuad(vec2 p, vec2 a, vec2 b, vec2 c, vec2 d) {
  vec2 e0 = b - a, e1 = c - b, e2 = d - c, e3 = a - d;
  return max(max(dot(normalize(vec2(e0.y, -e0.x)), p - a), dot(normalize(vec2(e1.y, -e1.x)), p - b)),
             max(dot(normalize(vec2(e2.y, -e2.x)), p - c), dot(normalize(vec2(e3.y, -e3.x)), p - d)));
}
float sdSeg(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a, ba = b - a;
  return length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0));
}
// A moth that reads as one at 40-60 px (the Burdock Shelter's 48 px moth by a paper lantern was a soft tan disk, read
// as a light overlay, 2026-10-25): seen from above along its heading (x along the body, y across, wingspan 1),
// forewings are broad triangles swept back, hindwings smaller rounded lobes behind them, the fuzzy body darker than the
// wings, two antennae; soft edges over about a pixel and a half. The wings are shaded like a painted moth's: darker near
// the fur and along the outer margin, with a fine grain that moves with it (flat beige with crisp edges read as a cutout
// on the gouache). w: the wing opening (0.25..1 in flight), + 2 when it sits: then the wings fold into a tent over its
// back. Returns coverage, the fringe band, the body's share and the brightness of what covers the pixel.
vec4 mothDetail(vec2 l, float w, float px) {
  bool sit = w > 1.5;
  float o = sit ? w - 2.0 : w;
  float aa = 1.4 * px;
  vec2 m = vec2(l.x, abs(l.y));
  float db = min((length(vec2(l.x / 0.16, l.y / 0.05)) - 1.0) * 0.05, length(l - vec2(0.175, 0.0)) - 0.035);
  float body = 1.0 - smoothstep(-aa, aa, db);
  float ant = (1.0 - smoothstep(-aa, aa, sdSeg(m, vec2(0.185, 0.012), vec2(0.30, 0.085)) - 0.55 * px)) * 0.8;
  float dw, reach;
  if (sit) {
    float sp = 0.16 + 0.22 * o;
    dw = sdTri(l, vec2(0.15, 0.0), vec2(-0.25, sp), vec2(-0.25, -sp));
    reach = sp;
  } else {
    float k = max(o, 0.18);
    float f = sdQuad(m, vec2(0.10, 0.02), vec2(0.03, 0.02 + 0.48 * k), vec2(-0.15, 0.02 + 0.38 * k), vec2(-0.04, 0.02));
    vec2 hc = vec2(-0.11, 0.02 + 0.17 * k), hr = vec2(0.11, 0.03 + 0.14 * k);
    dw = min(f, (length((m - hc) / hr) - 1.0) * min(hr.x, hr.y));
    reach = 0.5 * k;
  }
  float wing = 1.0 - smoothstep(-aa, aa, dw);
  float cov = max(max(body, wing * 0.96), ant);
  float rim = wing * (1.0 - smoothstep(0.0, 2.0 * px, -dw));
  float u = clamp(m.y / max(reach, 1e-3), 0.0, 1.0);
  float grain = fract(sin(dot(floor(l / (2.0 * px)), vec2(12.9898, 78.233))) * 43758.5453);
  float shadeW = (0.78 + 0.27 * smoothstep(0.05, 0.45, u)) * (1.0 - 0.28 * smoothstep(0.7, 0.98, u)) * (0.92 + 0.16 * grain);
  float bodyShare = cov > 0.0 ? clamp(max(body, ant) * (1.0 - wing * 0.35) / cov, 0.0, 1.0) : 0.0;
  return vec4(cov, rim, bodyShare, mix(shadeW, 0.45, bodyShare));
}
// coverage and back-lit fringe of the moth at P (px), over the shutter, and (w) its brightness weighted by coverage:
// the soft moth's is its coverage (brightness 1), the detailed moth's is shaded
vec4 mothCov(vec2 P) {
  float span = uLook.x;
  float cov = 0.0, rim = 0.0, lum = 0.0;
  for (int i = 0; i < ${S}; i++) {
    vec4 M = uM[i];
    vec2 d = P - M.xy;
    float c = cos(M.z), s = sin(M.z);
    vec2 l = vec2(c * d.x + s * d.y, -s * d.x + c * d.y) / span;     // x along the body, y across
    if (uDetail > 0.5) {
      vec4 k4 = mothDetail(l, M.w, 1.0 / span);
      cov += k4.x / float(${S});
      rim += k4.y / float(${S});
      lum += k4.x * k4.w / float(${S});
      continue;
    }
    // body: a short fuzzy cigar
    float body = 1.0 - smoothstep(0.8, 1.25, length(vec2(l.x / 0.3, l.y / 0.11)));
    // wings: spread, two broad lobes on either side; folded, a delta over the body
    float o = M.w;
    vec2 wl = vec2(l.x + 0.04, abs(l.y) - 0.24 * o);
    float wing = 1.0 - smoothstep(0.75, 1.3, length(vec2(wl.x / (0.26 + 0.06 * (1.0 - o)), wl.y / (0.08 + 0.2 * o))));
    float k = max(body, wing * (0.55 + 0.35 * (1.0 - o)));
    cov += k / float(${S});
    rim += wing * (1.0 - wing) * 4.0 / float(${S});
    lum += k / float(${S});
  }
  return vec4(cov, rim, 0.0, lum);
}
void main() {
  vec4 cr;
  if (uCell > 0.0) {
    // pixel art shows each cell's center pixel: it draws its whole cell's share of the moth, crisp as a sprite (soft
    // partial cells read as gray patches over the pixel greenhouse's lantern, 2026-10-21)
    vec2 c0 = uOrigin + floor((vPx - uOrigin) / uCell) * uCell;
    vec2 acc = vec2(0.0);
    for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) acc += mothCov(c0 + (vec2(float(i), float(j)) + 0.5) * uCell * 0.25).xy;
    acc /= 16.0;
    float on = step(0.22, acc.x);
    cr = vec4(on, on * (1.0 - step(0.55, acc.x)) * min(acc.y * 2.0, 1.0), 0.0, on);
  } else {
    cr = mothCov(vPx);
  }
  float cov = cr.x, rim = cr.y;
  if (cov < 0.003) discard;
  // hidden behind the lamp body, nearer things, and the indoors
  int id = int(texelFetch(tRegion, ivec2(clamp(vUv, 0.0, 0.9999) * vec2(textureSize(tRegion, 0))), 0).r * 255.0 + 0.5);
  float vis = (uLook.z > 0.5 && id == int(uLook.w)) ? 0.0 : 1.0;
  vis *= 1.0 - smoothstep(uLook.y * 1.03 + 0.006, uLook.y * 1.08 + 0.015, texture2D(tDepth, vUv).r);
  // on its lamp's own pane in front of it the indoors test doesn't apply: a lantern a character holds is cut from the
  // outdoors (dry), and the Burdock Shelter's moth vanished whenever it landed on it (2026-10-25)
  float own = (uLook.z < 0.5 && id == int(uLook.w)) ? 1.0 : 0.0;
  vis *= max(max(texture2D(tLights, vUv).g, uCovered), own);
  float a = min(cov, 1.0) * vis;
  if (a < 0.003) discard;
  // brightness: 1 for the soft moth, shaded for the detailed one (its fur darker, its wings darker at the margin)
  vec3 col = uCol * a * (cr.w / max(cov, 1e-3)) + uRim * min(rim, 1.0) * vis * 0.6;
  gl_FragColor = vec4(col, a);
}`;

const ss = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

// The moth's position (lamp units: x right, y up, z away from the camera; 0 = the light's center) at tau s into
// its visit, and whether it is sitting (wings folded).
export function mothAt(ev, tau, front = 1.05) {
  const [a, b, c, d, e, f] = ev.ph;
  // the orbit: a wavering horizontal loop around the light, bobbing up and down, with small darts
  const orbit = (u) => {
    const th = ev.th0 + ev.w * u + 0.9 * Math.sin(0.41 * u + a) + 0.45 * Math.sin(1.37 * u + b);
    const R = ev.R0 * (1 + 0.28 * Math.sin(0.57 * u + c) + 0.16 * Math.sin(1.9 * u + d));
    const dart = 0.12 * Math.sin(7.3 * u + e) + 0.07 * Math.sin(11.9 * u + f);
    return [R * Math.cos(th) + dart, 0.55 * Math.sin(0.83 * u + e) + 0.3 * Math.sin(2.1 * u + a) + dart, R * Math.sin(th) + 0.6 * dart];
  };
  let p = orbit(tau);
  // in out of the dark and away again (eased over ~3.5 s)
  const k0 = 1 - ss(0, 3.5, tau), k1 = ss(ev.dur - 3.5, ev.dur, tau);
  const mix = (q, r, k) => q.map((v, i) => v + (r[i] - v) * k);
  if (k0 > 0) p = mix(p, ev.from, k0);
  if (k1 > 0) p = mix(p, ev.to, k1);
  let sit = 0;
  for (const L of ev.landsFit ?? []) {
    const [t0, t1, u, v] = L;
    if (tau < t0 - 0.6 || tau > t1 + 0.6) continue;
    const kin = ss(t0 - 0.6, t0, tau) * (1 - ss(t1, t1 + 0.6, tau));
    p = mix(p, [u, v, -front], kin);
    if (tau >= t0 && tau <= t1) sit = 1;
  }
  return { p, sit };
}

// Landing times nudged so the moth is in front of the lamp (z < -0.6) when it lands and takes off: from there
// it reaches the pane without crossing the lamp. Landings that can't be placed are dropped.
function fitLandings(ev, front) {
  const out = [];
  const zAt = (t) => mothAt({ ...ev, landsFit: [] }, t, front).p[2];
  for (const [t, d, u, v] of ev.lands ?? []) {
    let t0 = null;
    for (let k = 0; k < 120; k++) { const tt = t + k * 0.1; if (tt > ev.dur - 6) break; if (zAt(tt) < -0.6) { t0 = tt; break; } }
    if (t0 == null) continue;
    let t1 = null;
    for (let k = 0; k < 160; k++) { const tt = t0 + d + k * 0.1; if (tt > ev.dur - 4) break; if (zAt(tt) < -0.6) { t1 = tt; break; } }
    if (t1 == null) continue;
    if (out.length && t0 < out[out.length - 1][1] + 2) continue;
    out.push([t0, t1, u, v]);
  }
  return out;
}

export async function mothLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'moth');
  if (!evs.length) return null;
  const meta = await plateRegions(opts.plate);
  const lamp = meta.find((g) => g.name === opts.lamp) ?? meta.find((g) => g.kind === 'lamp');
  if (!lamp) { console.warn('moth: no lamp region'); return null; }
  const [bx0, by0, bx1, by1] = lamp.bbox;
  const cx = (opts.center?.[0] ?? (bx0 + bx1) / 2) * W, cy = (opts.center?.[1] ?? (by0 + by1) / 2) * H;
  const unit = opts.unit ?? ((bx1 - bx0) * W) / 3;
  const span = opts.size ?? 9, front = opts.front ?? 1.05, unitM = opts.unitM ?? 0.33, shutter = opts.shutter ?? 1 / 60;
  const [tDepth, tLights, tRegion] = await Promise.all([plateTexture(opts.plate, 'depth8.png'), plateTexture(opts.plate, 'lights.png'),
    plateTexture(opts.plate, 'regions.png', { nearest: true })]);
  // the lamp's light: its color from the blurred plate at its center, its reach from lights.png B
  const [blur, lit] = await Promise.all([imagePixels(`/out/plates/${opts.plate}/blur.png`), imagePixels(`/out/plates/${opts.plate}/lights.png`)]);
  const px = (img, x, y, ch) => { const ix = Math.min(img.width - 1, Math.max(0, Math.round(x * img.width / W))), iy = Math.min(img.height - 1, Math.max(0, Math.round(y * img.height / H))); return img.data[(iy * img.width + ix) * 4 + ch]; };
  const lampRGB = [0, 1, 2].map((ch) => toLin(px(blur, cx, cy, ch) / 255));
  const lmax = Math.max(...lampRGB, 1e-4);
  // the light's color: given (`color`, linear rgb of its glow: a white-hot center pixel would light the moth grey,
  // which read as a blue dot on the farm porch's warm siding, 2026-10-21), else the blurred plate at its center
  const lampCol = opts.color ? opts.color.map((v) => v / Math.max(...opts.color, 1e-4)) : lampRGB.map((v) => v / lmax);
  const dep = await imagePixels(`/out/plates/${opts.plate}/depth8.png`);
  const d8Lamp = px(dep, cx, cy, 0) / 255;
  const dispLamp = d8Lamp * d8Lamp, Zlamp = 2700 / Math.max(1990 * dispLamp, 1);
  for (const ev of evs) ev.landsFit = fitLandings(ev, front);
  // up to two moths at the lamp at once (visits can overlap)
  const meshes = [0, 1].map(() => {
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag, ...PREMUL,
      uniforms: {
        tDepth: { value: tDepth }, tLights: { value: tLights }, tRegion: { value: tRegion },
        uM: { value: Array.from({ length: S }, () => new THREE.Vector4()) }, uLook: { value: new THREE.Vector4() },
        uCol: { value: new THREE.Vector3() }, uRim: { value: new THREE.Vector3() }, uBox: { value: new THREE.Vector4() },
        uCovered: { value: opts.covered ? 1 : 0 }, uDetail: { value: opts.detail ? 1 : 0 },
        uCell: { value: opts.pixelGrid?.cell ?? 0 }, uOrigin: { value: new THREE.Vector2(...(opts.pixelGrid?.origin ?? [0, 0])) },
      },
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 22;
    mesh.userData.noAO = true;
    mesh.visible = false;
    ctx.add(mesh);
    return mesh;
  });
  const tl = ctx.timeline;
  const draw = (mesh, ev, t) => {
    const U = mesh.material.uniforms;
    let bx = [1e9, 1e9, -1e9, -1e9], zc = 0, pc = null, sitc = 0;
    for (let i = 0; i < S; i++) {
      const tau = t - ev.t + ((i + 0.5) / S - 0.5) * shutter;
      const { p, sit } = mothAt(ev, tau, front);
      const k = Zlamp / (Zlamp + p[2] * unitM);
      const x = cx + p[0] * unit * k, y = cy - p[1] * unit * k;
      // heading: along its motion on screen (sitting: head up)
      const q = mothAt(ev, tau + 0.05, front).p;
      const hx = (q[0] - p[0]), hy = -(q[1] - p[1]);
      const head = sit ? -Math.PI / 2 : Math.atan2(hy, hx);
      // wingbeats ~30-45 Hz: within one exposure the wings sweep their whole stroke (open = |cos|); folded when sitting,
      // with a short shiver now and then
      const shiver = sit ? Math.max(0, Math.sin(2 * Math.PI * tau / 3.1 + ev.ph[0])) ** 12 : 0;
      const open = sit ? 0.15 + 0.5 * shiver * Math.abs(Math.cos(2 * Math.PI * ev.hz * tau)) : 0.25 + 0.75 * Math.abs(Math.cos(2 * Math.PI * ev.hz * tau));
      // the detailed moth folds its wings into a tent when it sits: it is told so by + 2
      U.uM.value[i].set(x, y, head, opts.detail && sit ? open + 2 : open);
      bx = [Math.min(bx[0], x), Math.min(bx[1], y), Math.max(bx[2], x), Math.max(bx[3], y)];
      if (i === S >> 1) { zc = p[2]; pc = p; sitc = sit; }
    }
    const m = span * 1.2 + 2 + (opts.pixelGrid?.cell ?? 0);
    U.uBox.value.set(bx[0] - m, bx[1] - m, bx[2] + m, bx[3] + m);
    const dispM = dispLamp * Zlamp / (Zlamp + zc * unitM);
    U.uLook.value.set(span, Math.sqrt(Math.max(dispM, 0)), zc > 0 ? 1 : 0, lamp.id);
    // light: falls off with distance from the light (lamp units), the lit side faces the camera when it is beside or behind it
    const r = Math.hypot(pc[0], pc[1], pc[2]);
    const I = 3.0 / (1 + Math.pow(r / 1.5, 2)) + 0.3 * px(lit, (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, 2) / 255;
    const toLampZ = -pc[2] / Math.max(r, 1e-3);     // its direction to the light, toward the camera (+) or away (-)
    const face = sitc ? 0.06 : 0.45 + 0.55 * Math.max(0, toLampZ);
    const fl = flashAt(ctx.timeline, t).flash;
    const alb = 0.6;
    const amb = 0.02 + 0.1 * fl;
    // in front of the light it is a dark shape (its lit side faces the lamp, away from us), a silhouette with a glowing
    // fringe; a lit, tan moth over a white-hot flame read as a gray patch on the pixel greenhouse's lantern (2026-10-21).
    // With `silhouette` (pixel looks) it also stays a dark shape while it is over the lamp's lit glass, whichever side.
    const overGlass = Math.hypot(pc[0], pc[1]) < 1.1;
    const sil = opts.silhouette ? (overGlass ? 1 : Math.max(0, toLampZ)) : 0;
    U.uCol.value.set(...lampCol.map((c) => (c * I * face * alb) * (1 - 0.97 * sil) + amb));
    const back = Math.max(0, -toLampZ, 0.8 * sil);
    U.uRim.value.set(...lampCol.map((c) => c * I * back * 0.5));
  };
  ctx.animate((t) => {
    const on = evs.filter((e) => t >= e.t && t <= e.t + e.dur).slice(0, meshes.length);
    meshes.forEach((m, i) => { m.visible = i < on.length; if (i < on.length) draw(m, on[i], t); });
  });
  return meshes;
}
