// The frog of a blocky look (user 2026-10-27: the jungle temple's sprite frog glided along a straight line and looked
// poor; frogs hop): an original blocky tree frog built from boxes in code, posed every frame from its timeline event
// (timeline/frog.js plans it: short hops with pauses, turning hops, a sit with croaks at a spot or two) and lit like
// the plate around it. Each hop is a crouch, a push with the hind legs straightening behind it, an arc through the air
// with the legs trailing and the hands reaching forward, a landing on the hands and a settle back into its sit; while
// it sits its throat pumps, it blinks now and then, and when it croaks its vocal sac swells under its chin.
//
// creature3d.js renders it into its own texture every frame (an orthographic view from the scene camera's angle down
// at the floor where it is, one texel per screen pixel) and composites it onto the plate: hidden behind anything
// clearly nearer than the floor under it (plate depth), with a soft contact shadow that stays on the floor in a hop.
//
// opts: { plate, floor: scene.json events.frog (horizon, size: body px at sizeY, focal), palette ('red-eyed' |
//   'green' | 'orange'), key: { dir, color, intensity } (the main light, toward it; scaled by the floor's light where
//   the frog is against keyRef, 0.06 linear), fill, ambient (hemisphere gain), shadow (0.45), texels (per unit, 2.4),
//   renderOrder (8) }
import * as THREE from 'three';
import { hash3, boxMaterials } from './boxart.js';
import { creatureLayer } from './creature3d.js';

const BL = 9;                                   // body length nose to rump, sitting (units): the floor's `size` px
const T = { w: 6.0, h: 2.6, l: 6.2 };           // trunk; its pitch pivots on the rump's bottom edge
const HD = { w: 6.6, h: 2.4, l: 3.8 };          // head
const EYE = 2.1;
const SAC = { w: 3.4, h: 0.7, l: 2.0 };         // vocal sac under the chin
const LEG = { thigh: 4.0, shin: 4.0, foot: 3.4, tw: 1.8, sw: 1.3, fw: 2.4, fh: 0.45 };
const ARM = { len: 3.0, w: 1.0, hand: [1.9, 0.4, 1.7] };
const PIVOT_Z = -4.2;                           // the rump behind the root point (the root is about the body's middle)
const TAU = 2 * Math.PI;

const PALETTES = {
  'red-eyed': { top: '#5cb636', light: '#86d34f', flank: '#2b5eb3', bar: '#ead03f', belly: '#efe5c4', toe: '#ff8a2a', gap: '#c4581a',
    eye: '#d8241c', rim: '#8e130e', pupil: '#121212', mouth: '#356f1f', sac: '#ebe2ad', inner: '#3a6ece' },
  green: { top: '#4f9a35', light: '#6cb64a', flank: '#3f7f2c', bar: '#93c45b', belly: '#e3dcb6', toe: '#9fce6a', gap: '#5f8a3c',
    eye: '#c8a62d', rim: '#5b4a12', pupil: '#121212', mouth: '#2c5a1c', sac: '#d9d39d', inner: '#467a33' },
  orange: { top: '#c9772f', light: '#dd9450', flank: '#9a5523', bar: '#e6b56a', belly: '#f1dfbd', toe: '#d99a5c', gap: '#7a421b',
    eye: '#2a2a2a', rim: '#141414', pupil: '#050505', mouth: '#7a421b', sac: '#f0d8a8', inner: '#a8612b' },
};

// Skin per part: p is a point on the box's surface (units, centered), f the face (0 +x, 1 -x, 2 top, 3 bottom,
// 4 front, 5 back).
function painters(C) {
  const speck = (p, s) => hash3(Math.floor(p[0] * 1.3 + 40) + s, Math.floor(p[1] * 1.3 + 40), Math.floor(p[2] * 1.3 + 40)) > 0.86;
  const skin = (p, s) => (speck(p, s) ? C.light : C.top);
  const bars = (z) => (((z * 0.75) % 1) + 1) % 1 < 0.32;
  return {
    trunk: (p, f) => {
      if (f === 3) return C.belly;
      if ((f === 0 || f === 1) && p[1] < 0.15) return bars(p[2] + 9) ? C.bar : C.flank;   // the blue flank with its bars
      if (f === 5 && p[1] < -0.3) return C.belly;
      return skin(p, 1);
    },
    head: (p, f) => {
      if (f === 3) return C.belly;
      const mouth = p[1] > -0.55 && p[1] < -0.3;
      if (f === 4 || f === 0 || f === 1) {
        if (mouth && (f === 4 || p[2] > -0.6)) return C.mouth;
        if (p[1] <= -0.55) return C.belly;                      // the jaw's pale underside
      }
      if (f === 4 && p[1] > 0.55 && Math.abs(p[0]) < 0.45) return C.mouth;   // the nostrils
      return skin(p, 2);
    },
    eye: (side) => (p, f) => {
      if (f === 3) return C.top;
      const e = EYE / 2 - 0.25;
      const edge = Math.max(Math.abs(p[0]), Math.abs(p[1]), Math.abs(p[2])) > e && f !== 2;
      // a vertical slit on the front and the outer side, a catchlight at its upper corner
      const face = f === 4 ? [p[0], p[1]] : (f === 0 && side > 0) || (f === 1 && side < 0) ? [p[2], p[1]] : null;
      if (face) {
        if (face[0] > 0.35 && face[0] < 0.7 && face[1] > 0.4 && face[1] < 0.75) return '#fff4e8';
        if (Math.abs(face[0]) < 0.2 && Math.abs(face[1]) < 0.62) return C.pupil;
      }
      return edge ? C.rim : C.eye;
    },
    sac: () => C.sac,
    thigh: (p, f) => (f === 3 || (f === 1 && p[0] < 0) ? C.inner : bars(p[2] + 3) && f !== 2 ? C.bar : skin(p, 4)),
    shin: (p, f) => (f === 3 ? C.inner : skin(p, 5)),
    arm: (p, f) => (f === 3 ? C.belly : skin(p, 6)),
    // orange toes, the gaps between them darker
    foot: (p, f) => (f === 2 && (((p[0] * 1.6) % 1) + 1) % 1 < 0.22 ? C.gap : C.toe),
  };
}

function buildFrog(palette, texels) {
  const P = painters(PALETTES[palette] ?? PALETTES['red-eyed']);
  const box = (size, paint, id) => new THREE.Mesh(new THREE.BoxGeometry(...size),
    boxMaterials(size, texels, paint, id, { grain: 0.1, roughness: 0.55 }));
  const root = new THREE.Group();
  const trunkG = new THREE.Group();
  root.add(trunkG);
  const trunk = box([T.w, T.h, T.l], P.trunk, 1);
  trunk.position.set(0, T.h / 2, T.l / 2);
  trunkG.add(trunk);
  const headG = new THREE.Group();
  headG.position.set(0, T.h * 0.62, T.l - 0.4);
  trunkG.add(headG);
  const head = box([HD.w, HD.h, HD.l], P.head, 2);
  head.position.set(0, 0, HD.l / 2 - 0.3);
  headG.add(head);
  const eyes = [1, -1].map((s, i) => {
    const e = box([EYE, EYE, EYE], P.eye(s), 3 + i);
    e.position.set(s * 2.25, HD.h / 2 + 0.55, HD.l - 1.5);
    headG.add(e);
    return e;
  });
  const sac = box([SAC.w, SAC.h, SAC.l], P.sac, 5);
  headG.add(sac);
  // the limbs live in the root's frame: placed every frame between their joints
  const seg = (size, paint, id) => { const m = box(size, paint, id); root.add(m); return m; };
  const legs = [1, -1].map((s, i) => ({
    s, thigh: seg([LEG.tw, LEG.tw * 0.9, LEG.thigh], P.thigh, 10 + i), shin: seg([LEG.sw, LEG.sw, LEG.shin], P.shin, 12 + i),
    foot: seg([LEG.fw, LEG.fh, LEG.foot], P.foot, 14 + i),
  }));
  const arms = [1, -1].map((s, i) => ({ s, arm: seg([ARM.w, ARM.w, ARM.len], P.arm, 16 + i), hand: seg(ARM.hand, P.foot, 18 + i) }));
  return { root, trunkG, trunk, headG, eyes, sac, legs, arms };
}

// ---- poses: p trunk pitch (nose up); ankle [dz, dy] from the hip; foot: its angle below forward (0 flat forward, ~pi
// trailing back); arm: from straight down toward forward; hp head pitch (nose down, from the trunk's: a sitting frog's
// head is about level while its back slopes); squash: the trunk's height ----
const SIT = { p: 0.36, ankle: [-0.07, -0.98], foot: 0.06, arm: 0.12, hp: 0.3, squash: 1 };
const CROUCH = { p: 0.26, ankle: [0.35, -0.7], foot: 0.06, arm: -0.12, hp: 0.34, squash: 0.93 };
const LAUNCH = { p: 0.5, ankle: [-6.9, -2.2], foot: 2.7, arm: -0.55, hp: 0.12, squash: 1.06 };
const AIR = { p: 0.05, ankle: [-7.4, -0.6], foot: 3.0, arm: 0.85, hp: 0.12, squash: 1.04 };
const LAND = { p: -0.12, ankle: [-3.2, -1.7], foot: 0.5, arm: 0.55, hp: 0.3, squash: 0.9 };

const mix = (a, b, w) => {
  const o = {};
  for (const k of Object.keys(a)) o[k] = Array.isArray(a[k]) ? a[k].map((v, i) => v + (b[k][i] - v) * w) : a[k] + (b[k] - a[k]) * w;
  return o;
};
const smooth = (x) => { const u = Math.min(1, Math.max(0, x)); return u * u * (3 - 2 * u); };
const wrapDeg = (a) => ((((a + 180) % 360) + 360) % 360) - 180;

// A hop's pose at u (0..1 of it); a turning hop (small) bends only half as far from the sit.
function hopPose(u, small) {
  const seq = [[0, SIT], [0.18, CROUCH], [0.32, LAUNCH], [0.55, AIR], [0.8, LAND], [1, SIT]];
  let i = 0;
  while (i < seq.length - 2 && u >= seq[i + 1][0]) i++;
  const [u0, a] = seq[i], [u1, b] = seq[i + 1];
  const p = mix(a, b, smooth((u - u0) / (u1 - u0)));
  return small ? mix(SIT, p, 0.5) : p;
}

// Croak envelope at s seconds after a croak starts: the sac swells over 0.12 s, holds, and goes down by 0.55 s.
const croakEnv = (s) => (s < 0 || s > 0.55 ? 0 : s < 0.12 ? smooth(s / 0.12) : s < 0.34 ? 1 : 1 - smooth((s - 0.34) / 0.21));

// Where the frog is at tau s into its event and how it holds itself: { x, y (image coords: the floor under it),
// h (heading, rad), arc (units above its sit), pose, sac: [sx, sy, sz], eye }.
export function frogAt(ev, tau) {
  const hops = ev.hops ?? [];
  if (!hops.length || tau < 0 || tau > ev.dur) return null;
  let i = hops.findIndex((h) => tau < h[0] + h[1]);
  let x, y, hd, arc = 0, pose;
  if (i >= 0 && tau >= hops[i][0]) {
    const [t0, d, x0, y0, x1, y1, h0, h1, hg, turn] = hops[i];
    const u = (tau - t0) / d, s = smooth((u - 0.2) / 0.64);
    x = x0 + (x1 - x0) * s; y = y0 + (y1 - y0) * s;
    hd = h0 + wrapDeg(h1 - h0) * smooth((u - 0.12) / 0.48);
    const v = Math.min(1, Math.max(0, (u - 0.24) / 0.6));
    arc = 4 * hg * BL * v * (1 - v);
    pose = hopPose(u, !!turn);
  } else {
    const k = i < 0 ? hops.length - 1 : i - 1;
    if (k < 0) { x = hops[0][2]; y = hops[0][3]; hd = hops[0][6]; } else { x = hops[k][4]; y = hops[k][5]; hd = hops[k][7]; }
    pose = { ...SIT };
  }
  // life while it sits (the throat pumps, it blinks) and its croaks
  let ck = 0;
  for (const c of ev.croaks ?? []) ck = Math.max(ck, croakEnv(tau - c));
  const pump = 0.05 + 0.05 * Math.sin(TAU * 2.3 * tau);
  const sac = [1 + 0.3 * ck, 1 + pump + 1.1 * ck, 1 + 0.45 * ck];
  pose.squash *= 1 - 0.05 * ck + 0.012 * Math.sin(TAU * 0.7 * tau);
  pose.hp -= 0.06 * ck;
  const T0 = 3.6 + 3.4 * hash3(ev.seed ?? 1, 7, 7), ph = (tau + 9 * hash3(ev.seed ?? 1, 8, 8)) % T0;
  const eye = ph < 0.14 ? 0 : 1;
  return { x, y, h: (hd * Math.PI) / 180, arc, pose, sac, eye };
}

// ---- kinematics in the root's frame (y up, z the way it faces), with the rump's pivot at height 0 ----
function ik2(hip, ank, L1, L2, kx) {
  const dy = ank[1] - hip[1], dz = ank[2] - hip[2];
  let d = Math.hypot(dy, dz);
  const dMax = L1 + L2 - 0.05, dMin = Math.abs(L1 - L2) + 0.05;
  const k = d > dMax ? dMax / d : d < dMin ? dMin / Math.max(d, 1e-6) : 1;
  const a = [ank[0], hip[1] + dy * k, hip[2] + dz * k];
  d = Math.min(dMax, Math.max(dMin, d));
  const th = Math.atan2(a[1] - hip[1], a[2] - hip[2]);
  const al = Math.acos(Math.min(1, Math.max(-1, (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))));
  // the knee on the forward side of the hip-ankle line
  const c1 = [kx, hip[1] + L1 * Math.sin(th + al), hip[2] + L1 * Math.cos(th + al)];
  const c2 = [kx, hip[1] + L1 * Math.sin(th - al), hip[2] + L1 * Math.cos(th - al)];
  return { knee: c1[2] >= c2[2] ? c1 : c2, ank: a };
}

function joints(pose) {
  const c = Math.cos(pose.p), s = Math.sin(pose.p);
  const R = (y, z) => [y * c + z * s, PIVOT_Z + z * c - y * s];
  const J = { legs: [], arms: [], minY: Math.min(R(0, 0)[0], R(0, T.l)[0], R(-0.3, T.l + HD.l - 0.5)[0]) };
  const low = (y) => { J.minY = Math.min(J.minY, y); };
  for (const sd of [1, -1]) {
    const [hy, hz] = R(0.85, 0.9);
    const hip = [sd * (T.w / 2 + 0.15), hy, hz];
    const { knee, ank } = ik2(hip, [sd * (T.w / 2 + 0.4), hy + pose.ankle[1], hz + pose.ankle[0]], LEG.thigh, LEG.shin, sd * (T.w / 2 + 0.55));
    const toe = [ank[0] + sd * 0.5, ank[1] - Math.sin(pose.foot) * LEG.foot, ank[2] + Math.cos(pose.foot) * LEG.foot];
    J.legs.push({ hip, knee, ank, toe });
    low(knee[1] - 0.8); low(ank[1] - 0.25); low(toe[1] - 0.25);
    const [sy, sz] = R(0.75, T.l - 1.1);
    const sh = [sd * (T.w / 2 - 0.2), sy, sz];
    const wr = [sh[0] + sd * 0.15, sy - Math.cos(pose.arm) * ARM.len, sz + Math.sin(pose.arm) * ARM.len];
    J.arms.push({ sh, wr });
    low(wr[1] - ARM.hand[1]);
  }
  return J;
}

const Z = new THREE.Vector3(0, 0, 1);
const tmp = new THREE.Vector3();
function place(mesh, a, b, len, lift) {
  tmp.set(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const n = tmp.length() || 1;
  tmp.divideScalar(n);
  mesh.quaternion.setFromUnitVectors(Z, tmp);
  mesh.position.set(a[0] + (tmp.x * len) / 2, a[1] + lift + (tmp.y * len) / 2, a[2] + (tmp.z * len) / 2);
}

function applyPose(F, st) {
  const pose = st.pose, J = joints(pose);
  const lift = -J.minY + st.arc;                 // the lowest point on the floor, plus the hop's arc
  F.trunkG.position.set(0, lift, PIVOT_Z);
  F.trunkG.rotation.set(-pose.p, 0, 0);
  F.trunk.scale.set(1, pose.squash, 1);
  F.trunk.position.y = (T.h / 2) * pose.squash;
  F.headG.position.y = T.h * 0.62 * pose.squash;
  F.headG.rotation.set(pose.hp, 0, 0);
  F.sac.scale.set(...st.sac);
  F.sac.position.set(0, -HD.h / 2 - (SAC.h * st.sac[1]) / 2 + 0.35, HD.l - 1.3);
  for (const e of F.eyes) { e.scale.y = 0.3 + 0.7 * st.eye; e.position.y = HD.h / 2 + 0.55 - (1 - st.eye) * 0.5; }
  J.legs.forEach((j, i) => {
    const L = F.legs[i];
    place(L.thigh, j.hip, j.knee, LEG.thigh, lift);
    place(L.shin, j.knee, j.ank, LEG.shin, lift);
    place(L.foot, j.ank, j.toe, LEG.foot, lift);
  });
  J.arms.forEach((j, i) => {
    const A = F.arms[i];
    place(A.arm, j.sh, j.wr, ARM.len, lift);
    A.hand.quaternion.identity();
    A.hand.position.set(j.wr[0], j.wr[1] + lift - ARM.hand[1] / 2, j.wr[2] + 0.45);
  });
}

// ---- the layer (creature3d.js composites it: lit from the plate, hidden behind nearer things, a contact shadow) ----
export function frogLayer(ctx, opts) {
  return creatureLayer(ctx, opts, {
    type: 'frog', BL, span: 26, cy: 4, above: [-0.8, -1.2, 0.8, -0.4], ground: [-0.7, -0.15, 0.7, 0.2],
    build: () => buildFrog(opts.palette ?? 'red-eyed', opts.texels ?? 2.4),
    at: frogAt,
    apply: applyPose,
    footprint: () => [BL * 0.75, T.w + 2.5],
  });
}
