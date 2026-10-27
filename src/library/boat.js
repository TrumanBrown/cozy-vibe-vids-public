// Rare event: a small covered lantern boat travels the river (timeline event type 'boat').
// The boat is a voxel model ray-marched per pixel (4 sub-samples, so its edges never shimmer) through a
// pinhole camera that matches the plate: the focal length is shared with rain/leaves, and the camera
// height and horizon are calibrated so the shore blocks come out ~1 m. Its heading, foreshortening,
// size and speed therefore follow a world-space path on the water plane. Water effects in the same pass:
// a mirrored reflection broken up by ripples (Fresnel), the lantern's glitter streak, warm spill from
// the cabin, a Kelvin wake and a contact shadow at the waterline. The porch occludes it (outdoor mask);
// paths start in the far mist and end behind the railing, so it never pops in or out. Pure function of
// the event and time.
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { imagePixels, loadTex } from './overlay.js';

const VS = 0.125;                              // voxel size (m)
const LO = [-18, -2, -6], HI = [18, 16, 6];    // model grid (voxels): x to the bow, y up, z starboard
const LANTERN = [15, 14.5, 0], CABIN = [-4, 4.0, 0];   // light positions (voxel coords)

// Plate camera: pinhole at height `height` (m) above the water plane, pitched down so the water's
// horizon sits at image row `horizon` (0..1, y down). Screen px <-> world (x, y up, z toward the camera).
export function lakeCamera({ focalPx = 2700, horizon = 0.453, height = 16, W = 3840, H = 2160 } = {}) {
  const F = focalPx, cx = W / 2, cy = H / 2;
  const th = Math.atan((cy - horizon * H) / F);
  const s = Math.sin(th), c = Math.cos(th);
  const f = [0, -s, -c], u = [0, c, -s], r = [1, 0, 0], C = [0, height, 0];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const ray = (px, py) => {
    const a = (px - cx) / F, b = -(py - cy) / F;
    const d = [0, 1, 2].map((i) => r[i] * a + u[i] * b + f[i]);
    const n = Math.hypot(...d);
    return d.map((v) => v / n);
  };
  const toWater = (x, y) => { const d = ray(x * W, y * H); const t = -height / d[1]; return [C[0] + t * d[0], 0, C[2] + t * d[2]]; };
  const project = (p) => {
    const D = [p[0] - C[0], p[1] - C[1], p[2] - C[2]];
    const dep = dot(D, f);
    return [cx + (F * dot(D, r)) / dep, cy - (F * dot(D, u)) / dep, dep];
  };
  return { F, W, H, C, r, u, f, toWater, project, pxPerM: (dep) => F / dep };
}

// Smooth world path through screen points on the water (Catmull-Rom), arc-length parametrized.
export function makePath(cam, pts) {
  const P = pts.map(([x, y]) => cam.toWater(x, y));
  const cr = (p0, p1, p2, p3, t) => [0, 2].map((i) => 0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t * t + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t * t * t));
  const S = [];
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(i - 1, 0)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(i + 2, P.length - 1)];
    for (let k = 0; k < 48; k++) S.push(cr(p0, p1, p2, p3, k / 48));
  }
  S.push([P[P.length - 1][0], P[P.length - 1][2]]);
  const L = [0];
  for (let i = 1; i < S.length; i++) L.push(L[i - 1] + Math.hypot(S[i][0] - S[i - 1][0], S[i][1] - S[i - 1][1]));
  const total = L[L.length - 1];
  const pos = (s) => {
    s = Math.min(Math.max(s, 0), total);
    let lo = 0, hi = L.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (L[m] <= s) lo = m; else hi = m; }
    const k = (s - L[lo]) / Math.max(L[hi] - L[lo], 1e-9);
    return [S[lo][0] + (S[hi][0] - S[lo][0]) * k, S[lo][1] + (S[hi][1] - S[lo][1]) * k];
  };
  return { total, pos };
}

// Boat pose on its route at time t (renderer and audio profile share this): position on the water plane,
// heading, progress u, route distance s from the far end, and visibility (fades are by route distance:
// out of the far mist / only once hidden behind the railing).
// k: the share of a slow start and stop (0.3: a spotlight boat setting out and arriving; 0: traffic passing through)
const ease = (u, k = 0.3) => u * u * (3 - 2 * u) * k + u * (1 - k);
export function boatPose(path, ev, t, fade = [30, 6], lanes = 0, easeK = 0.3) {
  // u0: a pass already under way when the event starts (a boat out at t = 0); dur is what is left of it
  const u0 = ev.u0 ?? 0;
  const u = Math.min(Math.max(u0 + (1 - u0) * (t - ev.t) / ev.dur, 0), 1);
  const s = (ev.dir > 0 ? ease(u, easeK) : 1 - ease(u, easeK)) * path.total;
  let [x, z] = path.pos(s);
  const a = path.pos(s - 1.5), b = path.pos(s + 1.5);
  // lanes (m): each boat keeps its own line, offset across the route by (lane - 0.5) * lanes
  if (lanes && ev.lane != null) {
    const tx = b[0] - a[0], tz = b[1] - a[1], tn = Math.hypot(tx, tz) || 1, off = (ev.lane - 0.5) * lanes;
    x += (-tz / tn) * off; z += (tx / tn) * off;
  }
  const fx = (b[0] - a[0]) * ev.dir, fz = (b[1] - a[1]) * ev.dir;
  const n = Math.hypot(fx, fz) || 1;
  const vis = Math.max(0, Math.min(1, s / fade[0], (path.total - s) / fade[1]));
  const speed = (path.total / ev.dur) * (1 - easeK + easeK * 6 * u * (1 - u));
  return { u, s, x, z, fx: fx / n, fz: fz / n, vis, speed };
}

// Audio profile of a boat event for tools/audio.py: distance to the camera (m), pan (-1..1 from the
// screen x), speed (m/s) and visibility every `dt` s.
export function boatProfile(route, ev, dt = 0.25) {
  const cam = lakeCamera(route.camera);
  const path = makePath(cam, route.path);
  const out = { dt, dist: [], pan: [], speed: [], vis: [] };
  for (let t = ev.t; t <= ev.t + ev.dur + 1e-6; t += dt) {
    const p = boatPose(path, ev, t, route.fade, route.lanes, route.ease);
    const q = cam.project([p.x, 0.5, p.z]);
    out.dist.push(Math.round(Math.hypot(p.x - cam.C[0], cam.C[1], p.z - cam.C[2]) * 10) / 10);
    out.pan.push(Math.round(Math.max(-1, Math.min(1, (q[0] / cam.W - 0.5) * 2)) * 1000) / 1000);
    out.speed.push(Math.round(p.speed * 100) / 100);
    out.vis.push(Math.round(p.vis * 1000) / 1000);
  }
  return out;
}

// The quad covers only the boat's screen box; vPx = 4K pixel coordinates (y down) at any render size.
const vert = /* glsl */ `
uniform vec4 uBox;
uniform vec2 uRes;
varying vec2 vPx;
void main() {
  vec2 p = position.xy * 0.5 + 0.5;
  vPx = mix(uBox.xy, uBox.zw, vec2(p.x, 1.0 - p.y));
  gl_Position = vec4(vPx.x / uRes.x * 2.0 - 1.0, 1.0 - vPx.y / uRes.y * 2.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
precision highp float;
precision highp int;
uniform sampler2D tLights, tMask, tPlate, tDepth, tBlurO;
uniform float uProf[32];    // occlusion: the water's depth8 by image row (uProfY: the rows spanned)
uniform vec2 uProfY;
uniform float uD0;          // the water's depth8 under the boat
uniform vec3 uOcc;          // on (1/0), dark ratio (thin dark things in front: plate / blurred plate below it), below row
uniform float uAirLod;      // mip level of the plate used as the haze (airlight) color around the boat
uniform vec2 uRes;
uniform vec3 uC, uR, uU, uF;
uniform float uFocal;
uniform vec3 uB;            // boat origin (world): midship on the waterline, plus bob
uniform mat3 uToLocal;      // world -> boat axes (bow, up, starboard)
uniform vec2 uFwd, uSide;   // heading / starboard on the water plane (world xz)
uniform vec3 uSky, uEnv, uCanopy;
uniform vec2 uGlint;        // screen position (px) of the lantern's mirror image
uniform vec2 uLamp;         // screen position (px) of the lantern
uniform float uPxPerM, uTime, uVis, uHaze, uHazeL, uFlash, uLantern, uSpeed, uDebug;   // uHaze: hull, uHazeL: lantern light
varying vec2 vPx;
// Haze (airlight) color at this pixel: the plate around the boat, blurred (mip), so the haze tints the
// boat toward its surroundings without letting sharp light reflections behind it show through.
vec3 gAir;

float h31(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }

int halfBeam(int x) {
  float u = (float(x) + 0.5) / 18.0;
  float k = x >= 0 ? 1.0 - u * u : 1.0 - pow(abs(u), 3.5);
  return int(floor(6.0 * sqrt(max(k, 0.0)) + 0.5));
}
int sheer(int x) {
  float u = (float(x) + 0.5) / 18.0;
  return 3 + int(floor(u > 0.0 ? 3.2 * u * u * u : 1.6 * u * u));
}
// 0 empty, 1 planks, 2 gunwale/benches, 3 floor, 4 canopy matting, 5 pole, 6 lantern frame, 7 lantern glass
int vox(ivec3 c) {
  int x = c.x, y = c.y, z = c.z;
  if (x < -18 || x >= 18 || y < -2 || y >= 16 || z < -6 || z >= 6) return 0;
  int az = z >= 0 ? z : -z - 1;
  int hb = halfBeam(x), sh = sheer(x);
  if (az < hb && y <= sh) {
    int inner = min(min(halfBeam(x - 1), halfBeam(x + 1)), hb) - 1;
    bool open = az < inner && y >= 1 && x > -17 && x < 16;
    if (!open) return y == sh ? 2 : (y <= 0 && az < inner ? 3 : 1);
    if ((x == 9 || x == -14) && y == 2) return 2;
  }
  // Cabin: a long, low, open-ended hood of woven matting aft of midship, two small windows a side.
  if (x >= -12 && x <= 4 && y > sh) {
    float zc = float(z) + 0.5, yc = float(y) + 0.5;
    float r = length(vec2(zc, max(yc - 5.5, 0.0)));
    bool win = y == 5 && az == 5 && ((x >= -9 && x <= -8) || (x >= -3 && x <= -2));
    if (r >= 4.6 && r < 5.6 && !win) return 4;
  }
  // Bow pole with the lantern on top (leads the boat; seen from the front most of the way).
  if (x == 14 && z == 0 && y > sheer(14) && y < 13) return 5;
  if ((x == 14 || x == 15) && (z == -1 || z == 0) && y >= 13 && y <= 15) return y == 14 ? 7 : 6;
  return 0;
}

vec3 shade(int m, ivec3 cell, vec3 n, vec3 p) {
  if (m == 7) return vec3(1.0, 0.6, 0.26) * 1.7 * uLantern;
  float h = h31(vec3(cell));
  vec3 alb;
  if (m == 1) alb = vec3(0.075, 0.044, 0.026) * (0.75 + 0.5 * h) * ((cell.y & 1) == 0 ? 1.0 : 0.82);
  else if (m == 2) alb = vec3(0.26, 0.16, 0.085) * (0.8 + 0.4 * h);
  else if (m == 3) alb = vec3(0.16, 0.10, 0.055) * (0.8 + 0.4 * h);
  else if (m == 4) alb = uCanopy * (0.8 + 0.4 * h) * ((cell.x & 1) == 0 ? 1.0 : 0.78);
  else if (m == 5) alb = vec3(0.07, 0.045, 0.028);
  else alb = vec3(0.035, 0.03, 0.028);
  vec3 upL = uToLocal * vec3(0.0, 1.0, 0.0);
  float up = dot(n, upL);
  // Inside the hood the sky is blocked: those faces see mostly the cabin light.
  float rr = length(vec2(p.z, max(p.y - 5.5, 0.0)));
  float ao = (p.x > -12.05 && p.x < 5.05 && rr < 5.05 && p.y > 0.95) ? 0.2 : 1.0;
  vec3 amb = (uSky * (0.6 + 0.4 * up) + uEnv * 0.5 * (1.0 - max(up, 0.0))) * ao;
  vec3 Lp = vec3(LANTERN) - p;
  float dl = length(Lp) * ${VS};
  vec3 lant = vec3(1.0, 0.6, 0.3) * 1.0 * uLantern * max(dot(n, normalize(Lp)), 0.0) / (1.0 + dl * dl * 2.0);
  vec3 Ip = vec3(CABIN) - p;
  float di = length(Ip) * ${VS};
  vec3 cab = vec3(1.0, 0.55, 0.25) * 2.4 * max(dot(n, normalize(Ip)), 0.0) / (1.0 + di * di * 3.0);
  vec3 col = alb * (amb + lant + cab + uFlash * ao * vec3(0.55, 0.6, 0.78) * (0.35 + 0.65 * max(up, 0.0)));
  if (m == 4) col += uCanopy * vec3(1.0, 0.62, 0.32) * 0.1;    // the lit cabin glows faintly through the matting
  return col;
}

// March the voxel model along a world ray; returns premultiplied color (alpha 1 on a hit, haze applied).
vec4 march(vec3 ro, vec3 rd, float tmax) {
  vec3 o = uToLocal * (ro - uB) / ${VS};
  vec3 d = uToLocal * rd / ${VS};
  d = mix(d, vec3(1e-6), vec3(lessThan(abs(d), vec3(1e-6))));
  vec3 inv = 1.0 / d;
  vec3 ta = (vec3(${LO.join('.0, ')}.0) - o) * inv, tb = (vec3(${HI.join('.0, ')}.0) - o) * inv;
  vec3 t0 = min(ta, tb), t1 = max(ta, tb);
  float tn = max(max(t0.x, t0.y), max(t0.z, 0.0)), tf = min(min(t1.x, t1.y), t1.z);
  if (tn >= tf || tn > tmax) return vec4(0.0);
  vec3 p = o + d * (tn + 1e-4);
  ivec3 cell = ivec3(floor(p));
  ivec3 stp = ivec3(sign(d));
  vec3 dt = abs(inv);
  vec3 tnx = (vec3(cell) + max(vec3(stp), 0.0) - o) * inv;
  int axis = t0.x > t0.y ? (t0.x > t0.z ? 0 : 2) : (t0.y > t0.z ? 1 : 2);
  float t = tn;
  for (int i = 0; i < 90; i++) {
    if (t > tmax || t > tf) break;
    int m = vox(cell);
    if (m > 0) {
      vec3 n = vec3(0.0);
      if (axis == 0) n.x = -float(stp.x); else if (axis == 1) n.y = -float(stp.y); else n.z = -float(stp.z);
      vec3 col = shade(m, cell, n, o + d * t);
      float hz = m == 7 ? uHazeL * 0.5 : uHaze;
      return vec4(mix(col, gAir, hz), 1.0);   // opaque: haze adds airlight, it doesn't make the hull see-through
    }
    if (tnx.x < tnx.y && tnx.x < tnx.z) { cell.x += stp.x; t = tnx.x; tnx.x += dt.x; axis = 0; }
    else if (tnx.y < tnx.z) { cell.y += stp.y; t = tnx.y; tnx.y += dt.y; axis = 1; }
    else { cell.z += stp.z; t = tnx.z; tnx.z += dt.z; axis = 2; }
  }
  return vec4(0.0);
}

// ---- the sampan (opts.model 'sampan'): a smooth hull for painterly scenes, local metres (x to the bow, y up from the
// waterline, z starboard): a planked hull with sheer and rocker, a woven matting arch over the middle (open at both
// ends, lit inside), and a paper lantern on a pole at the bow.
uniform float uModel;
uniform vec3 uLampCol;
uniform vec3 uLampPos;      // the lantern's center (local m)
const vec3 CABIN_S = vec3(-0.45, 0.62, 0.0);
float hullTop(float u) { return 0.36 + 0.24 * u * u * (u > 0.0 ? 1.0 : 0.55); }
float sdSampan(vec3 p, out int m) {
  float L = 2.3;
  float u = clamp(p.x / L, -1.0, 1.0);
  float hb = 0.7 * sqrt(max(1.0 - (u > 0.0 ? u * u : pow(abs(u), 3.0)), 0.0)) + 0.02;
  float top = hullTop(u), bot = -0.2 + 0.18 * pow(abs(u), 3.0);
  vec2 c = vec2(0.0, 0.5 * (top + bot)), hs = vec2(hb, 0.5 * (top - bot));
  float r = min(0.14, 0.9 * hb);
  vec2 q = abs(vec2(p.z, p.y) - c) - hs + r;
  float dh = max(length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r, abs(p.x) - L);
  m = p.y > top - 0.05 ? 2 : 1;
  float d = dh;
  // the matting arch
  float ra = length(vec2(p.z, max(p.y - 0.4, 0.0))) - 0.55;
  float dc = max(max(abs(ra) - 0.03, 0.4 - p.y), abs(p.x + 0.4) - 0.92);
  if (dc < d) { d = dc; m = 4; }
  // bow pole and the lantern
  vec3 lp = p - vec3(uLampPos.x, 0.0, 0.0);
  float dp = max(length(lp.xz) - 0.028, max(p.y - (uLampPos.y - 0.12), 0.3 - p.y));
  if (dp < d) { d = dp; m = 5; }
  vec3 rl = vec3(0.13, 0.17, 0.13);
  vec3 ql = p - uLampPos;
  float k0 = length(ql / rl), k1 = length(ql / (rl * rl));
  float dl = k0 * (k0 - 1.0) / max(k1, 1e-5);
  if (dl < d) { d = dl; m = 7; }
  // its caps
  float dcap = max(length(ql.xz) - 0.07, abs(abs(ql.y) - 0.175) - 0.02);
  if (dcap < d) { d = dcap; m = 6; }
  return d;
}
float sdS(vec3 p) { int m; return sdSampan(p, m); }
vec3 nrmS(vec3 p, float e) {
  vec2 k = vec2(1.0, -1.0);
  return normalize(k.xyy * sdS(p + k.xyy * e) + k.yyx * sdS(p + k.yyx * e) + k.yxy * sdS(p + k.yxy * e) + k.xxx * sdS(p + k.xxx * e));
}
vec3 shadeS(int m, vec3 p, vec3 n) {
  if (m == 7) {
    // a paper lantern: brightest at its middle, ribbed
    float rib = 0.85 + 0.15 * smoothstep(0.2, 0.9, abs(sin((p.y - uLampPos.y) * 75.0)));
    return uLampCol * 1.9 * uLantern * rib * (0.75 + 0.25 * (1.0 - abs(n.y)));
  }
  float h = fract(sin(dot(floor(p * vec3(9.0, 30.0, 9.0)), vec3(127.1, 311.7, 74.7))) * 43758.5453);
  vec3 alb;
  if (m == 1) alb = vec3(0.07, 0.042, 0.025) * (0.8 + 0.35 * h) * (0.86 + 0.14 * step(0.5, fract(p.y * 11.0)));
  else if (m == 2) alb = vec3(0.2, 0.125, 0.07) * (0.85 + 0.3 * h);
  else if (m == 4) {
    float weave = 0.82 + 0.18 * sin(p.x * 70.0) * sin(atan(p.y - 0.4, p.z) * 46.0);
    alb = uCanopy * weave * (0.85 + 0.3 * h);
  }
  else if (m == 5) alb = vec3(0.06, 0.04, 0.025);
  else alb = vec3(0.03, 0.025, 0.022);
  float up = n.y;
  // under the arch the sky is blocked
  bool inside = abs(p.x + 0.4) < 0.92 && p.y > 0.3 && length(vec2(p.z, max(p.y - 0.4, 0.0))) < 0.53;
  float ao = inside ? 0.15 : 1.0;
  vec3 amb = (uSky * (0.6 + 0.4 * up) + uEnv * 0.5 * (1.0 - max(up, 0.0))) * ao;
  vec3 Lp = uLampPos - p;
  float dl = length(Lp);
  vec3 lant = uLampCol * 0.9 * uLantern * max(dot(n, Lp / dl), 0.0) / (1.0 + dl * dl * 2.0);
  vec3 Ip = CABIN_S - p;
  float di = length(Ip);
  vec3 cab = vec3(1.0, 0.55, 0.25) * 2.2 * max(dot(n, Ip / di), 0.0) / (1.0 + di * di * 3.0) * (inside || m == 4 ? 1.0 : 0.35);
  vec3 col = alb * (amb + lant + cab + uFlash * ao * vec3(0.55, 0.6, 0.78) * (0.35 + 0.65 * max(up, 0.0)));
  if (m == 4) col += uCanopy * vec3(1.0, 0.62, 0.32) * 0.12;    // the lit cabin glows faintly through the matting
  return col;
}
// Sphere-trace the sampan along a world ray (t0: path length before ro, for the pixel-footprint hit threshold).
vec4 marchS(vec3 ro, vec3 rd, float tmax, float t0) {
  vec3 o = uToLocal * (ro - uB), d = uToLocal * rd;
  d = mix(d, vec3(1e-6), vec3(lessThan(abs(d), vec3(1e-6))));
  vec3 inv = 1.0 / d;
  vec3 ta = (vec3(-2.45, -0.35, -0.85) - o) * inv, tb = (vec3(2.45, 1.95, 0.85) - o) * inv;
  vec3 a0 = min(ta, tb), a1 = max(ta, tb);
  float tn = max(max(a0.x, a0.y), max(a0.z, 0.0)), tf = min(min(a1.x, a1.y), a1.z);
  if (tn >= tf || tn > tmax) return vec4(0.0);
  float t = tn;
  for (int i = 0; i < 72; i++) {
    vec3 p = o + d * t;
    int m;
    float h = sdSampan(p, m);
    float thr = 0.35 * (t0 + t) / uFocal;
    if (h < thr) {
      vec3 n = nrmS(p, max(thr, 0.004));
      vec3 col = shadeS(m, p, n);
      float hz = m == 7 ? uHazeL * 0.5 : uHaze;
      return vec4(mix(col, gAir, hz), 1.0);
    }
    t += h * 0.75;
    if (t > tf || t > tmax) break;
  }
  return vec4(0.0);
}
vec4 marchAny(vec3 ro, vec3 rd, float tmax, float t0) { return uModel > 0.5 ? marchS(ro, rd, tmax, t0) : march(ro, rd, tmax); }

vec3 rayDir(vec2 px) { return normalize(uF + uR * ((px.x - uRes.x * 0.5) / uFocal) - uU * ((px.y - uRes.y * 0.5) / uFocal)); }

// What stands in front of the boat and its reflection (opts.occlude): anything clearly nearer than the water at
// that row or under the boat (depth8.png: posts, poles, lamps, bushes), and below the railing's top row thin dark
// things the depth map smears into the water (rails, balusters: much darker than the plate around them).
float occAt(vec2 px, vec2 uv) {
  if (uOcc.x < 0.5) return 1.0;
  float y = px.y / uRes.y;
  float f = clamp((y - uProfY.x) / max(uProfY.y - uProfY.x, 1e-4), 0.0, 1.0) * 31.0;
  int i = int(floor(f));
  float d0 = max(uD0, mix(uProf[i], uProf[min(i + 1, 31)], fract(f)));
  float o = 1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, texture2D(tDepth, uv).r);
  if (y > uOcc.z) {
    float Lp = dot(texture2D(tPlate, uv).rgb, vec3(0.2126, 0.7152, 0.0722));
    float Lb = dot(texture2D(tBlurO, uv).rgb, vec3(0.2126, 0.7152, 0.0722));
    o *= smoothstep(uOcc.y * 0.85, uOcc.y * 1.15, Lp / max(Lb, 1e-4));
  }
  return o;
}

void main() {
  vec2 px = vPx;
  vec2 uv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
  float outdoor = texture2D(tLights, uv).g;
  if (outdoor < 0.004) discard;
  float water = texture2D(tMask, uv).g;
  gAir = textureLod(tPlate, uv, uAirLod).rgb;
  vec4 acc = vec4(0.0);
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    vec3 d = rayDir(px + o);
    float tw = d.y < 0.0 ? -uC.y / d.y : 1e9;
    vec4 c = marchAny(uC, d, tw, 0.0);
    if (c.a < 0.5 && tw < 1e8 && water > 0.01) {
      // Mirror image in the rippled water: ripples tilt the reflected ray, stretching it into bands.
      vec3 P = uC + d * tw;
      float rip = sin(P.z * 3.1 + P.x * 0.7 + uTime * 2.3) * 0.5 + sin(P.x * 2.3 - P.z * 1.7 + uTime * 3.1) * 0.3
                + sin(P.z * 7.3 + P.x * 0.9 - uTime * 4.7) * 0.2;
      vec3 dr = normalize(vec3(d.x + rip * 0.003, -d.y * (1.0 + rip * 0.4), d.z));
      vec4 rc = marchAny(P + dr * 0.002, dr, 1e9, tw);
      float fres = 0.02 + 0.98 * pow(1.0 - clamp(-d.y, 0.0, 1.0), 5.0);
      c = rc * fres * water;
    }
    acc += c;
  }
  acc *= 0.25;

  // Water around the boat (pixel center): wake, contact shadow, lantern glitter, warm cabin spill.
  vec3 glow = vec3(0.0);
  float shadow = 0.0;
  vec3 d0 = rayDir(px);
  if (d0.y < 0.0 && water > 0.01) {
    vec3 P = uC + d0 * (-uC.y / d0.y);
    vec2 rel = P.xz - uB.xz;
    float along = dot(rel, uFwd), side = dot(rel, uSide);
    float as = -along - 2.1;                       // m astern of the transom
    float wake = 0.0;
    if (as > -0.3 && as < 26.0) {
      float w = 0.1 + 0.035 * max(as, 0.0);
      float arm = abs(side) - 0.36 * max(as, 0.0) - 0.6;
      wake += exp(-arm * arm / (w * w)) * exp(-max(as, 0.0) / 10.0) * (0.6 + 0.4 * sin(as * 4.0 - uTime * 2.6));
      wake += 0.7 * exp(-side * side / 0.3) * exp(-max(as, 0.0) / 3.0) * smoothstep(-0.3, 0.5, as)
            * (0.55 + 0.45 * sin(as * 8.0 + side * 5.0 - uTime * 4.5));
    }
    float ab = along - 2.25;                       // m ahead of the stem
    float bowArm = abs(side) - 0.36 * max(-ab, 0.0) - 0.3;
    wake += 0.6 * exp(-bowArm * bowArm / 0.02) * smoothstep(0.4, -0.2, ab) * exp(-max(-ab, 0.0) / 1.2);
    wake *= uSpeed * (1.0 - uHaze);
    // Waterline contact shadow (the hull's footprint, a little wider).
    float x = clamp(along / 2.25, -1.0, 1.0);
    float hbm = 0.75 * sqrt(max(1.0 - (along > 0.0 ? x * x : pow(abs(x), 3.5)), 0.0));
    float inside = step(abs(along), 2.4);
    shadow = 0.45 * inside * (1.0 - smoothstep(0.0, 0.35, abs(side) - hbm)) * (1.0 - uHaze);
    // Lantern glitter: a broken vertical streak under the lantern's mirror image (like the plate's).
    vec2 g = px - uGlint;
    float gw = max(0.16 * uPxPerM, 1.6);
    float shimmer = 0.5 + 0.5 * sin(px.y * 0.95 + uTime * 8.0 + 3.0 * sin(px.y * 0.13 + uTime * 2.1));
    float streak = exp(-g.x * g.x / (2.0 * gw * gw)) * exp(-max(g.y, -3.0 * g.y) / (2.4 * uPxPerM)) * shimmer;
    // Warm spill from the cabin's open ends and windows.
    float spill = exp(-side * side / 1.2) * exp(-(along + 0.45) * (along + 0.45) / 2.5);
    glow = vec3(1.0, 0.62, 0.3) * (streak * 0.9 * uLantern * (1.0 - 0.5 * uHazeL) + spill * 0.06 * (1.0 - uHaze))
         + (uSky * 1.6 + vec3(0.02, 0.025, 0.035)) * wake;
    glow *= water;
    shadow *= water;
  }
  // Lantern halo (rain and mist scatter its light into a small soft glow, like the plate's lanterns).
  vec2 lq = px - uLamp;
  float sig = max(0.3 * uPxPerM, 2.5);
  glow += vec3(1.0, 0.6, 0.27) * 0.32 * uLantern * (1.0 - 0.4 * uHazeL) * exp(-dot(lq, lq) / (2.0 * sig * sig));
  vec4 outc = vec4(acc.rgb + glow * (1.0 - acc.a), acc.a + shadow * (1.0 - acc.a)) * outdoor * uVis * occAt(px, uv);
  if (uDebug > 0.5) { float c = max(outc.a, dot(glow, vec3(0.3))); gl_FragColor = vec4(c, c, c, 1.0); return; }
  gl_FragColor = outc;
}`.replace(/vec3\(LANTERN\)/g, `vec3(${LANTERN.map((v) => v.toFixed(2)).join(', ')})`).replace(/vec3\(CABIN\)/g, `vec3(${CABIN.map((v) => v.toFixed(2)).join(', ')})`);

const CANOPIES = [[0.10, 0.075, 0.045], [0.05, 0.065, 0.045], [0.09, 0.045, 0.035], [0.08, 0.07, 0.06]];

// opts: { plate, camera: {focalPx, horizon, height}, path: [[x, y], ...] (screen, far end first), fade: [m, m],
//         lanes (m: boats keep their own line across this band), ease (0.3: share of a slow start and stop; 0 for traffic), haze: { hull: [m, m], lantern: [m, m, max] },
//         occlude: { ratio (0.5), below: image row } (hide it behind what stands in front of the water; off when
//         absent: a plain lake), model ('voxel' | 'sampan': a smooth hull for painterly scenes), lanternColor
//         ('#ff6a2e', sampan), speedRef (m/s for full wake), debug }
export async function boatLayer(ctx, opts) {
  const boats = (ctx.timeline?.events ?? []).filter((e) => e.type === 'boat');
  if (!boats.length || !opts.path?.length) return null;
  const W = 3840, H = 2160;
  const cam = lakeCamera({ ...opts.camera, W, H });
  const path = makePath(cam, opts.path);
  const dir = `/out/plates/${opts.plate}`;
  const [tLights, tMask, tPlate, meta] = await Promise.all([loadTex(`${dir}/lights.png`), loadTex(`${dir}/masks.png`),
    loadTex(`${dir}/plate.png`, { srgb: true, mips: true }), fetch(`${dir}/plate.json`).then((r) => r.json())]);
  // occlusion: the water's depth by row along the route (the farthest fifth of the water pixels there: posts
  // and rails that the coarse water mask includes don't count)
  const sampan = opts.model === 'sampan';
  const LAMP_S = [1.85, 1.68, 0];
  const lampCol = (() => { const c = new THREE.Color(opts.lanternColor ?? '#ff6a2e'); return [c.r, c.g, c.b]; })();
  const occ = opts.occlude;
  const prof = new Array(32).fill(0);
  let profY = [0, 1], tDepth = tLights, tBlurO = tLights;
  if (occ) {
    const [dep, msk] = await Promise.all([imagePixels(`${dir}/depth8.png`), imagePixels(`${dir}/masks.png`)]);
    [tDepth, tBlurO] = await Promise.all([loadTex(`${dir}/depth8.png`), loadTex(`${dir}/blur.png`, { srgb: true })]);
    const xs = opts.path.map((q) => q[0]), ys = opts.path.map((q) => q[1]);
    profY = [Math.min(...ys) - 0.01, Math.max(...ys) + 0.06];
    const xa = Math.max(0, Math.min(...xs) - 0.02), xb = Math.min(1, Math.max(...xs) + 0.02);
    for (let i = 0; i < 32; i++) {
      const y = profY[0] + (profY[1] - profY[0]) * i / 31;
      const row = Math.round(y * (dep.height - 1)), mrow = Math.round(y * (msk.height - 1));
      const v = [];
      for (let x = Math.round(xa * (dep.width - 1)); x <= Math.round(xb * (dep.width - 1)); x += 2) {
        if (msk.data[(mrow * msk.width + Math.round(x * msk.width / dep.width)) * 4 + 1] > 128) v.push(dep.data[(row * dep.width + x) * 4] / 255);
      }
      v.sort((a, b) => a - b);
      prof[i] = v.length >= 6 ? v[Math.floor(0.2 * v.length)] : NaN;
    }
    // rows without water (above the far shore, below the railing): the nearest row that has some
    for (let i = 0; i < 32; i++) if (Number.isNaN(prof[i])) { let k = 1; while (k < 32 && Number.isNaN(prof[i - k] ?? NaN) && Number.isNaN(prof[i + k] ?? NaN)) k++; prof[i] = Number.isNaN(prof[i - k] ?? NaN) ? (prof[i + k] ?? 0) : prof[i - k]; }
  }
  const profAt = (y) => { const f = Math.min(Math.max((y - profY[0]) / (profY[1] - profY[0]), 0), 1) * 31, i = Math.floor(f); return prof[i] + (prof[Math.min(i + 1, 31)] - prof[i]) * (f - i); };
  const env = meta.env_linear ?? { sky: [0.08, 0.1, 0.2], outdoor: [0.07, 0.056, 0.095] };
  const v3 = (a) => new THREE.Vector3(...a);
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
    blendDst: opts.debug ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: {
      tLights: { value: tLights }, tMask: { value: tMask }, tPlate: { value: tPlate }, uAirLod: { value: 6 },
      uRes: { value: new THREE.Vector2(W, H) }, uBox: { value: new THREE.Vector4() },
      uC: { value: v3(cam.C) }, uR: { value: v3(cam.r) }, uU: { value: v3(cam.u) }, uF: { value: v3(cam.f) }, uFocal: { value: cam.F },
      uB: { value: new THREE.Vector3() }, uToLocal: { value: new THREE.Matrix3() }, uFwd: { value: new THREE.Vector2() }, uSide: { value: new THREE.Vector2() },
      uSky: { value: v3(env.sky) }, uEnv: { value: v3(env.outdoor) }, uCanopy: { value: v3(CANOPIES[0]) }, uGlint: { value: new THREE.Vector2() },
      uLamp: { value: new THREE.Vector2() },
      uPxPerM: { value: 20 }, uTime: { value: 0 }, uVis: { value: 0 }, uHaze: { value: 0 }, uHazeL: { value: 0 }, uFlash: { value: 0 }, uLantern: { value: 1 },
      uSpeed: { value: 1 }, uDebug: { value: opts.debug ? 1 : 0 },
      tDepth: { value: tDepth }, tBlurO: { value: tBlurO }, uProf: { value: prof }, uProfY: { value: new THREE.Vector2(...profY) }, uD0: { value: 0 },
      uOcc: { value: new THREE.Vector3(occ ? 1 : 0, occ?.ratio ?? 0.5, occ?.below ?? 2) },
      uModel: { value: sampan ? 1 : 0 }, uLampCol: { value: new THREE.Vector3(...lampCol) }, uLampPos: { value: new THREE.Vector3(...LAMP_S) },
    },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 5;          // on the plate, under rain and leaves
  mesh.visible = false;
  ctx.add(mesh);

  const M = new THREE.Matrix4(), R = new THREE.Matrix4(), toW = new THREE.Matrix4();
  const corners = [];
  if (sampan) for (const x of [-2.4, 2.4]) for (const y of [-0.3, 1.9]) for (const z of [-0.8, 0.8]) corners.push(new THREE.Vector3(x, y, z));
  else for (const x of [LO[0], HI[0]]) for (const y of [LO[1], HI[1]]) for (const z of [LO[2], HI[2]]) corners.push(new THREE.Vector3(x * VS, y * VS, z * VS));
  const speedRef = opts.speedRef ?? 2;
  const poseAt = (ev, t) => boatPose(path, ev, t, opts.fade, opts.lanes, opts.ease);
  ctx.animate((t) => {
    let ev = null;
    for (const e of boats) if (t >= e.t && t <= e.t + e.dur) { ev = e; break; }
    mesh.visible = !!ev;
    if (!ev) return;
    const p = poseAt(ev, t), m = mat.uniforms, tau = t - ev.t, ph = (ev.seed % 1000) * 0.01;
    const bob = 0.025 * Math.sin(2 * Math.PI * 0.42 * tau + ph) + 0.012 * Math.sin(2 * Math.PI * 0.71 * tau + 2 * ph);
    const roll = 0.025 * Math.sin(2 * Math.PI * 0.37 * tau + 3 * ph), pitch = 0.012 * Math.sin(2 * Math.PI * 0.53 * tau + ph);
    const fwd = new THREE.Vector3(p.fx, 0, p.fz), up = new THREE.Vector3(0, 1, 0), side = new THREE.Vector3(-p.fz, 0, p.fx);
    M.makeBasis(fwd, up, side).multiply(R.makeRotationX(roll)).multiply(toW.makeRotationZ(pitch));
    M.setPosition(p.x, bob, p.z);
    m.uB.value.set(p.x, bob, p.z);
    m.uToLocal.value.setFromMatrix4(M).transpose();
    m.uFwd.value.set(p.fx, p.fz);
    m.uSide.value.set(-p.fz, p.fx);
    // Screen box: the model, its mirror image, the wake behind it and the glitter below the lantern.
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (v) => { const q = cam.project([v.x, v.y, v.z]); x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); };
    for (const c of corners) { const w = c.clone().applyMatrix4(M); add(w); add(new THREE.Vector3(w.x, -w.y, w.z)); }
    for (const [a, sd] of [[-30, -12], [-30, 12], [4, -3], [4, 3]]) add(new THREE.Vector3(p.x + p.fx * a - p.fz * sd, 0, p.z + p.fz * a + p.fx * sd));
    const dep = cam.project([p.x, 0, p.z])[2], ppm = cam.pxPerM(dep);
    const L = (sampan ? new THREE.Vector3(...LAMP_S) : new THREE.Vector3(LANTERN[0] * VS, LANTERN[1] * VS, LANTERN[2] * VS)).applyMatrix4(M);
    const g = cam.project([L.x, -L.y, L.z]), lp = cam.project([L.x, L.y, L.z]);
    y1 = Math.max(y1, g[1] + 10 * ppm);
    const halo = Math.max(1.2 * ppm, 10);
    x0 = Math.min(x0, lp[0] - halo); x1 = Math.max(x1, lp[0] + halo); y0 = Math.min(y0, lp[1] - halo);
    m.uBox.value.set(Math.max(0, Math.floor(x0) - 4), Math.max(0, Math.floor(y0) - 4), Math.min(W, Math.ceil(x1) + 4), Math.min(H, Math.ceil(y1) + 4));
    m.uGlint.value.set(g[0], g[1]);
    m.uLamp.value.set(lp[0], lp[1]);
    m.uPxPerM.value = ppm;
    if (occ) m.uD0.value = profAt(cam.project([p.x, 0, p.z])[1] / H);
    // Haze by camera distance (m). Hull: smoothstep [95, 260] m, so the boat emerges from the mist as a
    // lantern glow first and fades out smoothly (no see-through, no pop). Lantern light: linear to 0.8.
    const hz = opts.haze ?? { hull: [95, 260], lantern: [110, 230, 0.8] };
    const uh = Math.min(Math.max((dep - hz.hull[0]) / (hz.hull[1] - hz.hull[0]), 0), 1);
    m.uHaze.value = uh * uh * (3 - 2 * uh);
    m.uHazeL.value = Math.min(Math.max((dep - hz.lantern[0]) / (hz.lantern[1] - hz.lantern[0]), 0), 1) * hz.lantern[2];
    m.uAirLod.value = Math.min(Math.max(Math.log2(ppm * 3), 3), 7);   // blur ~ 2/3 of the boat's length
    const speed = p.speed;
    m.uSpeed.value = Math.min(speed / speedRef, 1.2);
    m.uCanopy.value.set(...CANOPIES[ev.seed % CANOPIES.length]);
    m.uVis.value = p.vis;
    m.uTime.value = t;
    m.uLantern.value = 0.92 + 0.08 * Math.sin(2 * Math.PI * 3.1 * t + 1.3) * Math.sin(2 * Math.PI * 0.7 * t);
    m.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
  });
  return { mesh, path, cam };
}
