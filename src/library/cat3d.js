// A pet that really moves (user 2026-10-18, docs/DECISIONS.md): an original blocky cat built from boxes in code,
// with pixel-art fur, posed every frame by a deterministic behavior program (walk, look around, sit, lie down,
// curl up asleep, wake, stretch) and lit like the plate around it. Never generated frames: a painted pet only
// breathes, and a pet that moves is a model like this one, in looks it matches (blocky, pixel art, low-poly).
//
// It renders into its own texture every frame (an orthographic view from the scene camera's angle down at the
// floor, one texel per screen pixel) and is composited like the critter: hidden behind anything nearer than the
// floor where it stands (plate depth), tinted by the light around it, with a soft contact shadow.
//
// opts: { plate, coat ('grey-tabby' | 'orange-tabby' | 'black-white' | 'calico'), start (scene s the program
//   starts), paths: { <name>: [[x, y, body px], ...] } (image coords 0..1 and the body's length in 4K px there),
//   program: [{ do: 'walk', path, speed? } | { do: 'turn', to: deg } | { do: 'stand' | 'sit' | 'lie' | 'curl' |
//   'stretch', dur, look?: [[s, yaw deg, pitch deg], ...] }], elev (deg the camera looks down at the floor, 15),
//   key: { dir: [x, y, z], color, intensity }, fill: { dir, color, intensity }, ambient (hemisphere gain, 1),
//   shadow (0.42), texels (per unit, 3), renderOrder (8) }
// Headings: 0 = facing the camera, 90 = facing screen right, -90 = left, 180 = away.
import * as THREE from 'three';
import { plateTexture, imagePixels, boxMean, dirLight, PREMUL } from './overlay.js';

const W = 3840, H = 2160;
// Proportions in units (1 unit ~ 3.5 cm): a cat ~45 cm long without head and tail.
const U = { bodyW: 5, bodyH: 5, bodyL: 13, headW: 5.5, headH: 4.5, headD: 4.5, leg: 6, legW: 2, tailSeg: 4, tailN: 3 };
const ATTACH_Y = -1.5;                    // legs attach 1.5 below the body's center line (hip frame)
const FRONT_Z = U.bodyL - 2, HIND_Z = 2;  // leg attach points along the body from its rear end
const STAND_HIP = -ATTACH_Y + U.leg;      // hip pivot height when standing on straight legs (7.5)
const ROOT_HIP_Z = -U.bodyL / 2;          // hip pivot (rear end of the body) relative to the root (under the body's middle)

const COATS = {
  'grey-tabby': { base: '#8d929b', dark: '#4f535b', light: '#d3d5da', nose: '#d4919c', eye: '#b9cf52', inner: '#d9a3ad' },
  'orange-tabby': { base: '#d98a3d', dark: '#9c5420', light: '#f2d6ae', nose: '#e0919a', eye: '#9fc743', inner: '#efb3a8' },
  'black-white': { base: '#2b2b30', dark: '#18181b', light: '#ebe8e2', nose: '#d78f9b', eye: '#d6c24a', inner: '#c98f9a' },
  'calico': { base: '#efe9de', dark: '#2e2926', light: '#f6f2ea', patch: '#d98a3d', nose: '#e29aa3', eye: '#c4b148', inner: '#e8b0b0' },
};

function hash3(a, b, c) {
  let h = (a * 374761393 + b * 668265263 + c * 2147483647) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
const hex = (s) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16));

// BoxGeometry face layout (three.js buildPlane): texel (c, r) of face f -> the point on the box surface.
const FACES = [
  { u: 2, v: 1, ud: -1, vd: -1, w: 0, ws: 1 },   // +x
  { u: 2, v: 1, ud: 1, vd: -1, w: 0, ws: -1 },   // -x
  { u: 0, v: 2, ud: 1, vd: 1, w: 1, ws: 1 },     // +y
  { u: 0, v: 2, ud: 1, vd: -1, w: 1, ws: -1 },   // -y
  { u: 0, v: 1, ud: 1, vd: -1, w: 2, ws: 1 },    // +z
  { u: 0, v: 1, ud: -1, vd: -1, w: 2, ws: -1 },  // -z
];

// Six pixel-art materials for a box of size [sx, sy, sz] units: color(p, face) gives the sRGB color at point p.
function boxMaterials(size, texels, color, partId) {
  return FACES.map((f, fi) => {
    const cw = Math.max(1, Math.round(size[f.u] * texels)), ch = Math.max(1, Math.round(size[f.v] * texels));
    const cv = document.createElement('canvas');
    cv.width = cw; cv.height = ch;
    const g = cv.getContext('2d');
    const img = g.createImageData(cw, ch);
    for (let r = 0; r < ch; r++) {
      for (let c = 0; c < cw; c++) {
        const p = [0, 0, 0];
        p[f.u] = ((c + 0.5) / cw * size[f.u] - size[f.u] / 2) * f.ud;
        p[f.v] = ((r + 0.5) / ch * size[f.v] - size[f.v] / 2) * f.vd;
        p[f.w] = f.ws * size[f.w] / 2;
        const col = hex(color(p, fi));
        const n = 0.93 + 0.14 * hash3(partId * 7 + fi, c, r);   // fur grain
        const k = (r * cw + c) * 4;
        img.data[k] = Math.min(255, col[0] * n); img.data[k + 1] = Math.min(255, col[1] * n); img.data[k + 2] = Math.min(255, col[2] * n);
        img.data[k + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(cv);
    t.colorSpace = THREE.SRGBColorSpace;
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    return new THREE.MeshStandardMaterial({ map: t, roughness: 0.92, metalness: 0 });
  });
}

// Coat patterns per part (points in the part's own units, centered on the box).
function painters(coat) {
  const C = COATS[coat] ?? COATS['grey-tabby'];
  const stripe = (z, period, width) => ((z % period) + period) % period < width;
  const patch = (p, s) => C.patch && hash3(Math.floor(p[0] / 2.5 + 50), Math.floor(p[1] / 2.5 + 50), Math.floor(p[2] / 3 + 50) + s) > 0.62;
  const darkPatch = (p, s) => C.patch && hash3(Math.floor(p[0] / 3 + 70), Math.floor(p[1] / 3 + 70), Math.floor(p[2] / 3.5 + 70) + s) > 0.8;
  const fur = (p, s, belly) => {
    if (belly) return C.light;
    if (C.patch) return darkPatch(p, s) ? C.dark : patch(p, s) ? C.patch : C.base;
    return C.base;
  };
  return {
    body: (p, f) => {
      const belly = p[1] < -1.6 || f === 3;
      if (!C.patch && !belly && p[1] > -1.2 && stripe(p[2] + 20, 3, 1)) return C.dark;
      if (!C.patch && f === 2 && Math.abs(p[0]) < 0.6) return C.dark;     // the dark line along the spine
      return fur(p, 1, belly);
    },
    head: (p, f) => {
      if (f === 4) {   // face: forehead "M" marks; the eyes are drawn by eyes()
        if (!C.patch && p[1] > 1.3 && (Math.abs(p[0]) < 0.4 || Math.abs(Math.abs(p[0]) - 1.3) < 0.4)) return C.dark;
        if (p[1] < -1.1) return C.light;
      }
      if (!C.patch && f === 2 && stripe(p[2] + 20, 2, 0.5)) return C.dark;
      return fur(p, 2, false);
    },
    muzzle: (p, f) => (f === 4 && p[1] > 0.4 && Math.abs(p[0]) < 0.6 ? C.nose : f === 4 && p[1] < -0.4 && Math.abs(p[0]) < 0.3 ? C.dark : C.light),
    ear: (p, f) => (f === 4 && p[1] < 0.5 && Math.abs(p[0]) < 0.5 ? C.inner : p[1] > 0.6 ? C.dark : fur(p, 3, false)),
    leg: (p) => (p[1] < -2.4 ? C.light : !C.patch && stripe(p[1] + 20, 2, 0.5) ? C.dark : fur(p, 4, false)),
    tail: (p) => (p[2] < -1.6 && C.patch ? C.dark : !C.patch && stripe(p[2] + 20, 1.6, 0.8) ? C.dark : fur(p, 5, false)),
    tailTip: (p) => (p[2] < -1.0 ? C.dark : !C.patch && stripe(p[2] + 20, 1.6, 0.8) ? C.dark : fur(p, 6, false)),
    eyes: (open) => (p, f) => {
      if (f === 4 && Math.abs(Math.abs(p[0]) - 1.3) < 0.55 && p[1] > -0.2 && p[1] < 0.8) {
        if (!open) return p[1] < 0.2 && p[1] > -0.05 ? C.dark : fur(p, 2, false);
        return Math.abs(Math.abs(p[0]) - 1.3) < 0.18 ? '#151515' : C.eye;   // a slit pupil in a bright iris
      }
      return null;
    },
    C,
  };
}

function buildCat(coat, texels) {
  const P = painters(coat);
  const box = (size, paint, id, pos) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(...size), boxMaterials(size, texels, paint, id));
    if (pos) m.position.set(...pos);
    return m;
  };
  const root = new THREE.Group();
  const hip = new THREE.Group();
  root.add(hip);
  const body = box([U.bodyW, U.bodyH, U.bodyL], P.body, 1, [0, 0, U.bodyL / 2]);
  hip.add(body);
  const neck = new THREE.Group();
  neck.rotation.order = 'YXZ';
  neck.position.set(0, U.bodyH / 2 - 0.5, U.bodyL - 0.5);
  hip.add(neck);
  const headSize = [U.headW, U.headH, U.headD];
  const headOpen = boxMaterials(headSize, texels, (p, f) => P.eyes(true)(p, f) ?? P.head(p, f), 2);
  const headShut = boxMaterials(headSize, texels, (p, f) => P.eyes(false)(p, f) ?? P.head(p, f), 2);
  const head = new THREE.Mesh(new THREE.BoxGeometry(...headSize), headOpen);
  head.position.set(0, -0.2, 2.4);     // in front of the shoulders, its top a little above the back
  neck.add(head);
  head.add(box([2.6, 1.6, 1], P.muzzle, 3, [0, -1.15, U.headD / 2 + 0.45]));
  const ears = [1, -1].map((s) => {
    const g = new THREE.Group();
    g.position.set(s * 1.6, U.headH / 2, 0.2);
    g.add(box([1.6, 1.6, 0.8], P.ear, 4, [0, 0.8, 0]));
    head.add(g);
    return g;
  });
  // legs: LF, RF, LH, RH (the cat's left is +x when it faces +z)
  const legs = [[1.5, FRONT_Z], [-1.5, FRONT_Z], [1.5, HIND_Z], [-1.5, HIND_Z]].map(([x, z], i) => {
    const g = new THREE.Group();
    g.position.set(x, ATTACH_Y, z);
    g.add(box([U.legW, U.leg, U.legW], P.leg, 10 + i, [0, -U.leg / 2, 0]));
    hip.add(g);
    return g;
  });
  const tails = [];
  let parent = hip;
  for (let i = 0; i < U.tailN; i++) {
    const g = new THREE.Group();
    g.position.set(0, i === 0 ? U.bodyH / 2 - 0.9 : 0, i === 0 ? 0.4 : -U.tailSeg);
    const last = i === U.tailN - 1;
    g.add(box([1.2, 1.2, U.tailSeg + 0.4], last ? P.tailTip : P.tail, 20 + i, [0, 0, -U.tailSeg / 2]));
    parent.add(g);
    tails.push(g);
    parent = g;
  }
  return { root, hip, body, neck, head, ears, legs, tails, setEyes: (open) => { head.material = open ? headOpen : headShut; } };
}

// ---- poses: plain objects, blended field by field; angles in radians ----
// hipY: hip pivot height; dz: hip pivot shift along the body; pitch: body nose-up; roll; hYaw/hPitch (+ = nose
// down, in the world)/hRoll/hDrop: the head; legs: [LF, RF, LH, RH] world pitch of each leg (+ = paw forward);
// tail: [pitch, yaw] x 3 segments (+ pitch = up, relative); eyes 0..1; breath 0..1; ears; support: 1 = standing
// on its legs (the lowest paw is kept on the floor), 0 = resting on its body.
const SIT_PITCH = 0.47;
const base = () => ({ hipY: STAND_HIP, dz: 0, pitch: 0, roll: 0, hYaw: 0, hPitch: 0.06, hRoll: 0, hDrop: 0, legs: [0, 0, 0, 0],
  tail: [0.45, 0, 0.35, 0.08, 0.5, 0.15], eyes: 1, breath: 0.35, earL: 0, earR: 0, support: 1 });

const TAU = 2 * Math.PI;
const smooth = (x) => { const u = Math.min(1, Math.max(0, x)); return u * u * u * (u * (6 * u - 15) + 10); };
// deterministic little lives inside a hold: blinks, ear flicks, tail swishes (seconds since the hold began)
const blink = (tau, seed) => { const T = 3.7 + 2.1 * hash3(seed, 1, 1), ph = (tau + 7 * hash3(seed, 2, 2)) % T; return ph < 0.16 ? 0 : 1; };
const pulse = (tau, period, len, seed) => { const ph = (tau + period * hash3(seed, 3, 3)) % period; return ph < len ? Math.sin(Math.PI * ph / len) : 0; };

function lookAt(look, tau) {
  if (!look?.length) return [0, 0];
  let prev = [0, 0, 0];
  for (const k of look) {
    if (tau < k[0]) {
      const w = smooth((tau - prev[0]) / Math.max(0.3, Math.min(1.1, k[0] - prev[0])));
      return [(prev[1] + (k[1] - prev[1]) * w) * Math.PI / 180, (prev[2] + (k[2] - prev[2]) * w) * Math.PI / 180];
    }
    prev = k;
  }
  return [prev[1] * Math.PI / 180, prev[2] * Math.PI / 180];
}

const POSES = {
  stand(tau, s) {
    const p = base();
    const [ly, lp] = lookAt(s.look, tau);
    p.hYaw = ly; p.hPitch += lp;
    p.tail[1] = 0.12 * Math.sin(TAU * tau / 3.1); p.tail[5] = 0.25 * Math.sin(TAU * tau / 2.3 + 1);
    p.eyes = blink(tau, s.seed);
    p.earL = 0.35 * pulse(tau, 6.1, 0.35, s.seed);
    return p;
  },
  walk(tau, s) {
    const p = base(), ph = s.phase, A = 0.42;
    [0.25, 0.75, 0, 0.5].forEach((o, i) => { p.legs[i] = A * Math.sin(TAU * (ph + o)); });
    p.roll = 0.03 * Math.sin(TAU * ph);
    p.hPitch = 0.12 + 0.04 * Math.sin(2 * TAU * ph);
    p.tail = [0.75, 0.1 * Math.sin(Math.PI * ph), 0.3, 0.12 * Math.sin(Math.PI * ph + 1), 0.35, 0.25 * Math.sin(Math.PI * ph + 2)];
    p.eyes = blink(tau, s.seed);
    return p;
  },
  sit(tau, s) {
    const p = base(), c = Math.cos(SIT_PITCH), sn = Math.sin(SIT_PITCH);
    p.pitch = SIT_PITCH;
    p.hipY = (U.bodyH / 2) * c + 0.2;                                    // the rump rests on the floor
    p.dz = ROOT_HIP_Z + FRONT_Z - (ROOT_HIP_Z + FRONT_Z * c - ATTACH_Y * sn);   // front paws stay where they stood
    p.legs = [0, 0, 1.4, 1.4];                                           // hind legs folded forward along the floor
    p.support = 0;
    const [ly, lp] = lookAt(s.look, tau);
    p.hYaw = ly; p.hPitch = -0.05 + lp;
    p.tail = [SIT_PITCH - 1.05, 0, 1.05, 0.8, 0.05, 0.7 + 0.22 * Math.sin(TAU * tau / 2.6) * pulse(tau, 9, 4, s.seed)];
    p.eyes = Math.min(blink(tau, s.seed), tau % 11 > 6 && tau % 11 < 6.6 ? 0 : 1);   // and a slow blink now and then
    p.earR = 0.3 * pulse(tau, 7.3, 0.3, s.seed + 1);
    p.breath = 0.45;
    return p;
  },
  lie(tau, s) {
    const p = base();
    p.hipY = U.bodyH / 2 + 0.1; p.pitch = 0;
    p.legs = [1.57, 1.57, 1.57, 1.57];
    p.support = 0;
    const [ly, lp] = lookAt(s.look, tau);
    p.hYaw = ly; p.hPitch = 0.04 + lp;
    p.tail = [-1.0, 0.25, 1.0, 0.9, 0.0, 0.8 + 0.12 * Math.sin(TAU * tau / 3.4)];
    p.eyes = blink(tau, s.seed);
    p.breath = 0.6;
    return p;
  },
  curl(tau, s) {
    const p = POSES.lie(tau, s);
    // chin down on the front paws, turned a little toward its tail side
    p.hYaw = 0.45; p.hPitch = 0.35; p.hDrop = -1.2; p.hRoll = 0.12;
    p.tail = [-1.0, 0.45, 1.0, 1.35, 0.0, 1.35];   // wrapped around the camera side toward the paws
    p.eyes = 0; p.breath = 1; p.earL = -0.15; p.earR = -0.15;
    return p;
  },
  stretch(tau, s) {
    const p = base();
    p.pitch = -0.38; p.dz = 1.0;
    p.legs = [1.3, 1.3, 0, 0];
    p.hPitch = -0.35;
    p.tail = [0.9, 0, 0.2, 0, 0.2, 0];
    p.eyes = tau % 2.4 < 1.2 ? 0 : 1;
    return p;
  },
};

function blend(a, b, w) {
  const o = {};
  for (const k of Object.keys(a)) o[k] = Array.isArray(a[k]) ? a[k].map((v, i) => v + (b[k][i] - v) * w) : a[k] + (b[k] - a[k]) * w;
  return o;
}

// Kinematics: keep standing paws on the floor and the body above it, then set the rig.
function applyPose(cat, p, t) {
  const th = p.pitch, c = Math.cos(th), s = Math.sin(th);
  const yOf = (y, z) => y * c + z * s;
  let hipY = p.hipY;
  const paws = [FRONT_Z, FRONT_Z, HIND_Z, HIND_Z].map((z, i) => yOf(ATTACH_Y, z) - U.leg * Math.cos(p.legs[i]) - (U.legW / 2) * Math.abs(Math.sin(p.legs[i])));
  hipY -= p.support * (hipY + Math.min(...paws));
  const belly = Math.min(yOf(-U.bodyH / 2, 0), yOf(-U.bodyH / 2, U.bodyL));
  hipY = Math.max(hipY, -belly + 0.05);
  cat.hip.position.set(0, hipY, ROOT_HIP_Z + p.dz);
  cat.hip.rotation.set(-th, 0, p.roll);
  const br = 1 + 0.028 * p.breath * Math.sin(TAU * t / 3.0);
  cat.body.scale.set(1 + 0.4 * (br - 1), br, 1);
  cat.neck.position.y = U.bodyH / 2 - 0.5 + p.hDrop;
  cat.neck.rotation.set(p.hPitch + th, p.hYaw, p.hRoll);
  cat.legs.forEach((g, i) => { g.rotation.x = th - p.legs[i]; });
  cat.tails.forEach((g, i) => { g.rotation.order = 'YXZ'; g.rotation.set(p.tail[2 * i], p.tail[2 * i + 1], 0); });
  cat.ears[0].rotation.set(-0.2 * Math.max(0, -p.earL), 0, 0.5 * p.earL);
  cat.ears[1].rotation.set(-0.2 * Math.max(0, -p.earR), 0, -0.5 * p.earR);
  cat.setEyes(p.eyes > 0.5);
}

// ---- the behavior program: a list of steps from opts.start, each a pure function of time ----
const TRANS = { stand: 0.6, sit: 1.1, lie: 1.3, curl: 1.6, stretch: 0.9, walk: 0.35, turn: 0.3 };
const STRIDE = 12;    // units travelled per gait cycle

// A walking path on the floor: image points with the body's length in px there. Distances are measured on the
// floor (screen y foreshortened by the view: k = 1 / sin(elev)), in units.
function floorPath(pts, k) {
  const P = pts.map(([x, y, s]) => [x * W, y * H, s]);
  const S = [];
  const N = 400;
  for (let i = 0; i <= N; i++) {
    const u = (i / N) * (P.length - 1), j = Math.min(Math.floor(u), P.length - 2), f = u - j;
    const q = [0, 1, 2].map((c) => P[j][c] + (P[j + 1][c] - P[j][c]) * f);
    const prev = S[i - 1];
    const d = prev ? prev.d + Math.hypot(q[0] - prev.x, (q[1] - prev.y) * k) / ((q[2] + prev.size) / 2 / U.bodyL) : 0;
    S.push({ x: q[0], y: q[1], size: q[2], d });
  }
  const at = (dist) => {
    let lo = 0, hi = S.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (S[m].d <= dist) lo = m; else hi = m; }
    const a = S[lo], b = S[hi], f = b.d > a.d ? Math.min(1, Math.max(0, (dist - a.d) / (b.d - a.d))) : 0;
    return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, size: a.size + (b.size - a.size) * f, h: Math.atan2(b.x - a.x, (b.y - a.y) * k) };
  };
  return { len: S[S.length - 1].d, at };
}

function compile(opts, k) {
  const paths = Object.fromEntries(Object.entries(opts.paths ?? {}).map(([n, p]) => [n, floorPath(p, k)]));
  const steps = [];
  let t = opts.start ?? 0, pos = null, heading = 0;
  for (const st of opts.program ?? []) {
    const seed = steps.length + 1;
    if (st.do === 'walk') {
      const P = paths[st.path], ta = 0.6, v = st.speed ?? 11;    // ~0.4 m/s, an unhurried walk
      const T = P.len / v + ta;
      steps.push({ kind: 'walk', t0: t, t1: t + T, P, v: P.len / (T - ta), ta, h0: pos ? heading : P.at(0).h, seed });
      pos = P.at(P.len); heading = pos.h; t += T;
    } else if (st.do === 'turn') {
      const dh = ((((st.to * Math.PI) / 180 - heading + Math.PI) % TAU) + TAU) % TAU - Math.PI;
      const T = st.dur ?? Math.max(0.7, (Math.abs(dh) / (Math.PI / 2)) * 1.0);
      steps.push({ kind: 'turn', t0: t, t1: t + T, h0: heading, h1: heading + dh, pos, seed });
      heading += dh; t += T;
    } else {
      const T = st.dur ?? 4;
      steps.push({ kind: st.do, t0: t, t1: t + T, look: st.look, pos, h: heading, seed });
      t += T;
    }
  }
  return { steps, end: t };
}

function stepPose(s, tau) {
  if (s.kind === 'walk') {
    const T = s.t1 - s.t0, ta = s.ta, v = s.v;
    const dist = tau < ta ? (0.5 * v * tau * tau) / ta : tau > T - ta ? s.P.len - (0.5 * v * (T - tau) ** 2) / ta : v * (tau - ta / 2);
    const p = s.P.at(Math.min(s.P.len, Math.max(0, dist)));
    const w = smooth(tau / 0.6);
    const dh = (((p.h - s.h0 + Math.PI) % TAU) + TAU) % TAU - Math.PI;
    return { pose: POSES.walk(tau, { phase: dist / STRIDE, seed: s.seed }), x: p.x, y: p.y, size: p.size, heading: s.h0 + dh * w };
  }
  if (s.kind === 'turn') {
    const T = s.t1 - s.t0, w = smooth(tau / T);
    const pose = POSES.stand(tau, { seed: s.seed });
    // small steps in place while it turns
    [0.25, 0.75, 0, 0.5].forEach((o, i) => { pose.legs[i] = 0.18 * Math.sin(TAU * (1.6 * tau + o)) * Math.sin(Math.PI * Math.min(1, tau / T)); });
    return { pose, x: s.pos.x, y: s.pos.y, size: s.pos.size, heading: s.h0 + (s.h1 - s.h0) * w };
  }
  return { pose: POSES[s.kind](tau, s), x: s.pos.x, y: s.pos.y, size: s.pos.size, heading: s.h };
}

// Where the cat is and how it stands at scene time t (null when it is not in the scene).
function catAt(prog, t) {
  const S = prog.steps;
  if (!S.length || t < S[0].t0 || t >= prog.end) return null;
  const i = S.findIndex((s) => t < s.t1);
  const s = S[i], tau = t - s.t0;
  const cur = stepPose(s, tau);
  const tr = (TRANS[s.kind] ?? 0.6) + (i > 0 && ['lie', 'curl'].includes(S[i - 1].kind) && !['lie', 'curl'].includes(s.kind) ? 0.8 : 0);
  if (i > 0 && tau < tr) {
    const prev = stepPose(S[i - 1], S[i - 1].t1 - S[i - 1].t0);
    cur.pose = blend(prev.pose, cur.pose, smooth(tau / tr));
  }
  return cur;
}

// ---- the layer ----
const quadVert = /* glsl */ `
uniform vec4 uBox;        // x, y (top left, px at 4K, y down), w, h
varying vec2 vT;          // 0..1 across the box, y down
varying vec2 vUv;         // plate uv (y up)
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
// anything clearly nearer than the floor where the cat stands hides it (as for the critter)
const OCCLUDE = /* glsl */ `
float frontOf(vec2 uv) {
  float d0 = texture2D(tDepth, uFootUv).r, d = texture2D(tDepth, uv).r;
  return 1.0 - smoothstep(d0 * 1.06 + 0.01, d0 * 1.12 + 0.02, d);
}`;
const catFrag = /* glsl */ `
uniform sampler2D tCat, tDepth;
uniform vec2 uFootUv;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
void main() {
  vec4 c = texture2D(tCat, vec2(vT.x, 1.0 - vT.y));   // premultiplied: coverage-weighted color over a clear target
  if (c.a < 0.002) discard;
  float f = frontOf(vUv);
  if (f <= 0.0) discard;
  gl_FragColor = vec4(c.rgb * f, c.a * f);
}`;
const shadowFrag = /* glsl */ `
uniform sampler2D tDepth;
uniform vec2 uFootUv;
uniform float uShadow;
varying vec2 vT;
varying vec2 vUv;
${OCCLUDE}
void main() {
  vec2 q = vT * 2.0 - 1.0;
  float r2 = dot(q, q);
  float k = exp(-r2 * 2.4) * (1.0 - smoothstep(0.8, 1.0, r2)) * uShadow * frontOf(vUv);
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;

export async function cat3dLayer(ctx, opts) {
  const R = ctx.renderer;
  if (!R || !opts.program?.length) return null;
  const elev = ((opts.elev ?? 15) * Math.PI) / 180, k = 1 / Math.sin(elev);
  const prog = compile(opts, k);
  const cat = buildCat(opts.coat ?? 'grey-tabby', opts.texels ?? 3);
  const scene3 = new THREE.Scene();
  scene3.add(cat.root);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 1.6);
  scene3.add(hemi);
  dirLight(scene3, opts.key, { color: '#ffb066', intensity: 2.4, dir: [-0.45, 0.75, -0.35] });
  dirLight(scene3, opts.fill, { color: '#ffc884', intensity: 0.8, dir: [0.6, 0.5, 0.4] });
  // offscreen target: one texel per screen pixel at the largest size the cat reaches, 34 units across
  const maxPpu = Math.max(...Object.values(opts.paths ?? {}).flat().map((p) => p[2] / U.bodyL));
  const RT = Math.min(2048, Math.ceil((34 * maxPpu) / 16) * 16);
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 1000);
  const CY = 8;    // the view is centered this high above the floor point
  const tDepth = await plateTexture(opts.plate, 'depth8.png');
  // the defocused plate (older plates have none: the plate itself, sampled over a wide box, is close enough)
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);   // mean linear color of the defocused plate in a 4K px box
  const mk = (frag, extra) => new THREE.ShaderMaterial({
    vertexShader: quadVert, fragmentShader: frag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4() }, tDepth: { value: tDepth }, uFootUv: { value: new THREE.Vector2() }, ...extra },
  });
  const mat = mk(catFrag, { tCat: { value: rt.texture } });
  const smat = mk(shadowFrag, { uShadow: { value: 0 } });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), smat);
  quad.renderOrder = opts.renderOrder ?? 8;
  shadow.renderOrder = (opts.renderOrder ?? 8) - 0.5;
  for (const m of [shadow, quad]) { m.frustumCulled = false; m.visible = false; m.userData.noAO = true; ctx.add(m); }
  const prevClear = new THREE.Color();
  ctx.animate((t) => {
    const st = catAt(prog, t);
    quad.visible = shadow.visible = !!st;
    if (!st) return;
    applyPose(cat, st.pose, t);
    cat.root.rotation.y = st.heading;
    const ppu = st.size / U.bodyL, half = RT / 2 / ppu;
    Object.assign(cam, { left: -half, right: half, top: half, bottom: -half });
    cam.updateProjectionMatrix();
    cam.position.set(0, CY + Math.sin(elev) * 300, Math.cos(elev) * 300);
    cam.lookAt(0, CY, 0);
    // the room's light where it stands: the defocused plate above it (sky) and at its feet (ground)
    const sky = avg(st.x - 0.8 * st.size, st.y - 1.4 * st.size, st.x + 0.8 * st.size, st.y - 0.5 * st.size);
    const gnd = avg(st.x - 0.6 * st.size, st.y - 0.1 * st.size, st.x + 0.6 * st.size, st.y + 0.15 * st.size);
    hemi.color.setRGB(...sky);
    hemi.groundColor.setRGB(...gnd);
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, cam);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    // the floor point (the root) is CY*cos(elev) units below the view's center
    const ay = RT / 2 + CY * Math.cos(elev) * ppu;
    mat.uniforms.uBox.value.set(st.x - RT / 2, st.y - ay, RT, RT);
    const foot = [st.x / W, 1 - (st.y + 2) / H];
    mat.uniforms.uFootUv.value.set(...foot);
    smat.uniforms.uFootUv.value.set(...foot);
    // contact shadow: the body's footprint seen on the floor
    const sh = Math.abs(Math.sin(st.heading)), ch = Math.abs(Math.cos(st.heading));
    const rest = 1 - st.pose.support, L = U.bodyL * (0.62 - 0.07 * rest) + 2, Wd = U.bodyW + 2;
    const rx = (sh * L + ch * Wd) * 0.5 * ppu, ry = (ch * L + sh * Wd) * 0.5 * ppu * Math.sin(elev) + 3;
    smat.uniforms.uBox.value.set(st.x - rx, st.y - ry, 2 * rx, 2 * ry);
    smat.uniforms.uShadow.value = (opts.shadow ?? 0.42) * (0.6 + 0.4 * rest);
  });
  return quad;
}
