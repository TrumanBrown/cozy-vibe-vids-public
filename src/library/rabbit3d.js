// The rabbit of a blocky look (user 2026-11-06: the jungle temple's frog was really good, and he wants something like it
// in the snowy spruce cabin): an original blocky snow rabbit built from boxes in code, posed every frame from its
// timeline event (timeline/rabbit.js plans it: bursts of short hops with stops to sniff and look about, little turning
// hops, sits at a spot or two with acts) and composited onto the plate by creature3d.js like the frog.
//
// Each hop is a rabbit's slow hop: it gathers, pushes off with its hind feet planted and its heels rising, flies a short
// arc with the front paws reaching and the hind legs trailing, lands on its front paws, vaults over them as the hind
// legs swing under, and settles. Every paw on the floor stays where it was planted (worked out on the floor along the
// hop, turning hops too), so nothing slides. While it sits it twitches its nose in bursts, swivels each ear on its
// own, breathes and now and then blinks; its acts: washing its face (groom), sitting up on its hind legs to look
// around (up), turning its head (look), sniffing the floor (sniff).
//
// opts: { plate, floor: scene.json events.rabbit (horizon, size: body px at sizeY, focal), palette ('snow' | 'brown' |
//   'grey'), key, fill, ambient, keyRef, shadow, reflect, reflectFade (creature3d.js), texels (per unit, 2.0),
//   renderOrder (8) }
import * as THREE from 'three';
import { hash3, boxMaterials } from './boxart.js';
import { creatureLayer } from './creature3d.js';

export const BL = 9.0;                                 // body length nose to tail, sitting (units): the floor's `size` px
const T = { w: 4.4, h: 4.3, l: 5.4 };           // trunk, compact as a sitting rabbit's; its pitch pivots on the rump's bottom back edge
const HD = { w: 3.7, h: 3.3, l: 3.4 };          // head
const MZ = { w: 2.2, h: 1.4, l: 0.6 };          // muzzle, the nose on its top front: short, a rabbit's
const EAR = { w: 1.1, h: 4.4, d: 0.55 };
const EYE = 0.95;
const TAIL = [1.6, 1.5, 1.3];
const LEG = { thigh: 2.5, shin: 3.2, foot: 3.0, tw: 1.3, sw: 1.0, fw: 1.2, fh: 0.55, hip: [1.5, 1.6] };   // hind: the knee forward of the hip
const HAUNCH = [1.1, 2.9, 3.3];                 // the round haunch on each side of the rump, fixed to the trunk
const ARM = { up: 1.4, fore: 1.5, w: 0.8, paw: [1.0, 0.45, 1.2] };
const PIVOT_Z = -2.7;                           // the rump's back edge behind the root point (about the body's middle)
const HEEL = { x: T.w / 2 - 0.3, z: -2.2, y: LEG.fh / 2 };    // where the hind heels sit (root frame)
const PAW = { x: 0.85, z: 2.2, y: ARM.paw[1] / 2 };           // and the front paws, close together under the chest
const TAU = 2 * Math.PI, DEG = Math.PI / 180;

const PALETTES = {
  snow: { fur: '#f3f0ea', shade: '#e2dcd2', belly: '#fbfaf6', inner: '#e6a0a4', tip: '#2e2a27', nose: '#d4848c',
    eye: '#1c1311', rim: '#4a3a33', mouth: '#a2968a', toe: '#c2b9ad', whisker: '#8f857b' },
  brown: { fur: '#8a6a4c', shade: '#6d5139', belly: '#e0d0b8', inner: '#d39a8c', tip: '#4a3626', nose: '#c4847a',
    eye: '#140e0b', rim: '#3a2a1f', mouth: '#5a4130', toe: '#5e4634', whisker: '#3e2e22' },
  grey: { fur: '#a29d96', shade: '#86817a', belly: '#e6e2dc', inner: '#d9a3a3', tip: '#4c4844', nose: '#c88e94',
    eye: '#16110f', rim: '#3d3532', mouth: '#5f5953', toe: '#6f6a64', whisker: '#4a4540' },
};

// Skin per part: p is a point on the box's surface (units, centered), f the face (0 +x, 1 -x, 2 top, 3 bottom,
// 4 front, 5 back).
function painters(C) {
  const speck = (p, s) => hash3(Math.floor(p[0] * 2 + 40) + s, Math.floor(p[1] * 2 + 40), Math.floor(p[2] * 2 + 40)) > 0.9;
  const fur = (p, s) => (speck(p, s) ? C.shade : C.fur);
  return {
    trunk: (p, f) => {
      if (f === 3) return C.belly;
      if (f === 4 && p[1] < 0.6) return C.belly;                       // the chest
      return fur(p, 1);
    },
    head: (p, f) => {
      if (f === 3) return C.belly;
      if (f === 4 && p[1] < -0.4 && Math.abs(p[0]) < 1.3) return C.belly;   // the cheeks under the muzzle
      return fur(p, 2);
    },
    muzzle: (p, f) => {
      if (f === 4) {
        if (p[1] > 0.15 && Math.abs(p[0]) < 0.42) return C.nose;           // the nose
        if (Math.abs(p[0]) < 0.12 && p[1] > -0.45) return C.mouth;          // the split lip
        if (p[1] < -0.45 && Math.abs(p[0]) < 0.55) return C.mouth;
        if (Math.abs(p[0]) > 0.65 && hash3(Math.floor(p[0] * 4 + 20), Math.floor(p[1] * 4 + 20), 9) > 0.55) return C.whisker;
        return C.belly;
      }
      if (f === 3) return C.belly;
      return fur(p, 3);
    },
    eye: (side) => (p, f) => {
      const outer = (f === 0 && side > 0) || (f === 1 && side < 0);
      if (outer) {
        if (p[2] > 0.08 && p[2] < 0.36 && p[1] > 0.08 && p[1] < 0.36) return '#fff6ee';   // a catchlight
        return Math.max(Math.abs(p[1]), Math.abs(p[2])) > EYE / 2 - 0.2 ? C.rim : C.eye;
      }
      return C.rim;
    },
    ear: (p, f) => {
      if (p[1] > EAR.h / 2 - 0.9) return C.tip;                           // black-tipped, like a snow hare's
      if (f === 4 && Math.abs(p[0]) < EAR.w / 2 - 0.25 && p[1] > -EAR.h / 2 + 0.5) return C.inner;
      return fur(p, 4);
    },
    tail: () => C.belly,
    thigh: (p, f) => (f === 3 ? C.belly : fur(p, 5)),
    shin: (p, f) => fur(p, 6),
    foot: (p, f) => (f === 3 ? C.toe : f === 2 && p[2] > LEG.foot / 2 - 0.6 && (((p[0] * 3) % 1) + 1) % 1 < 0.3 ? C.toe : fur(p, 7)),
    arm: (p, f) => fur(p, 8),
    paw: (p, f) => (f === 3 ? C.toe : f === 4 && (((p[0] * 3) % 1) + 1) % 1 < 0.3 ? C.toe : C.fur),
  };
}

function buildRabbit(palette, texels) {
  const P = painters(PALETTES[palette] ?? PALETTES.snow);
  const box = (size, paint, id, rough = 0.95) => new THREE.Mesh(new THREE.BoxGeometry(...size),
    boxMaterials(size, texels, paint, id, { grain: 0.07, roughness: rough }));
  const root = new THREE.Group();
  const trunkG = new THREE.Group();
  root.add(trunkG);
  const trunk = box([T.w, T.h, T.l], P.trunk, 1);
  trunkG.add(trunk);
  const tail = box(TAIL, P.tail, 2);
  trunkG.add(tail);
  // the haunches: fixed to the trunk, so a folded leg hides in them and a kicking one comes out behind
  for (const [i, sx] of [[0, 1], [1, -1]]) {
    const h = box(HAUNCH, P.thigh, 22 + i);
    h.position.set(sx * (T.w / 2 + HAUNCH[0] / 2 - 0.25), HAUNCH[1] / 2 + 0.15, HAUNCH[2] / 2 + 0.2);
    trunkG.add(h);
  }
  const headG = new THREE.Group();
  headG.rotation.order = 'YXZ';
  trunkG.add(headG);
  const head = box([HD.w, HD.h, HD.l], P.head, 3);
  head.position.set(0, 0.5, 1.2);
  headG.add(head);
  const muzzle = box([MZ.w, MZ.h, MZ.l], P.muzzle, 4);
  headG.add(muzzle);
  const eyes = [1, -1].map((s, i) => {
    const e = box([0.3, EYE, EYE], P.eye(s), 5 + i, 0.35);
    e.position.set(s * (HD.w / 2 + 0.1), 0.85, 1.75);
    headG.add(e);
    return e;
  });
  const ears = [1, -1].map((s, i) => {
    const g = new THREE.Group();
    g.position.set(s * 0.95, 0.5 + HD.h / 2 - 0.15, 0.55);
    g.rotation.order = 'YXZ';
    const e = box([EAR.w, EAR.h, EAR.d], P.ear, 7 + i);
    e.position.y = EAR.h / 2;
    g.add(e);
    headG.add(g);
    return g;
  });
  // the limbs live in the root's frame: placed every frame between their joints
  const seg = (size, paint, id) => { const m = box(size, paint, id); root.add(m); return m; };
  const legs = [1, -1].map((s, i) => ({
    s, thigh: seg([LEG.tw, LEG.tw * 1.1, LEG.thigh], P.thigh, 10 + i), shin: seg([LEG.sw, LEG.sw, LEG.shin], P.shin, 12 + i),
    foot: seg([LEG.fw, LEG.fh, LEG.foot], P.foot, 14 + i),
  }));
  const arms = [1, -1].map((s, i) => ({
    s, up: seg([ARM.w, ARM.w, ARM.up], P.arm, 16 + i), fore: seg([ARM.w * 0.9, ARM.w * 0.9, ARM.fore], P.arm, 18 + i),
    paw: seg(ARM.paw, P.paw, 20 + i),
  }));
  return { root, trunkG, trunk, tail, headG, muzzle, eyes, ears, legs, arms };
}

// ---- poses: p trunk pitch (nose up); ry the rump pivot's height; zo its offset forward; ha the head's pitch (nose up,
// absolute); eb the ears laid back (rad); tl the tail raised; sq the trunk's length (stretched in flight) ----
const SIT = { p: 0.16, ry: 0.5, zo: 0, ha: 0.1, eb: 0.12, tl: 0, sq: 1 };            // alert, between bursts
const LOAF = { p: 0.02, ry: 0.2, zo: -0.1, ha: 0.12, eb: 0.32, tl: 0, sq: 0.97 };    // settled on a long sit, belly down
const GATHER = { p: 0.1, ry: 0.55, zo: -0.4, ha: 0.02, eb: 0.25, tl: 0.1, sq: 0.95 };
const PUSH = { p: 0.06, ry: 1.25, zo: 0.9, ha: 0.06, eb: 0.45, tl: 0.5, sq: 1.08 };
const FLY = { p: -0.06, ry: 1.3, zo: 0.6, ha: 0.02, eb: 0.55, tl: 0.6, sq: 1.1 };
const LAND = { p: -0.3, ry: 2.1, zo: 0.5, ha: -0.06, eb: 0.45, tl: 0.4, sq: 1.03 };
const SWING = { p: -0.1, ry: 1.4, zo: 0.2, ha: 0, eb: 0.3, tl: 0.25, sq: 0.97 };
const SETTLE = { p: 0.2, ry: 0.45, zo: -0.1, ha: 0.1, eb: 0.18, tl: 0.05, sq: 0.95 };
const ACT = {
  up: { p: 1.15, ry: 0.9, zo: -0.4, ha: 0.05, eb: -0.05, tl: 0, sq: 1.02 },
  groom: { p: 0.55, ry: 0.5, zo: -0.5, ha: -0.3, eb: 0.2, tl: 0, sq: 1 },
  sniff: { p: 0.08, ry: 0.4, zo: 0.1, ha: -0.55, eb: 0.18, tl: 0, sq: 1 },
  look: { p: 0.2, ry: 0.5, zo: 0, ha: 0.12, eb: 0.1, tl: 0, sq: 1 },
};

const mix = (a, b, w) => {
  const o = {};
  for (const k of Object.keys(a)) o[k] = a[k] + (b[k] - a[k]) * w;
  return o;
};
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const smooth = (x) => { const u = clamp01(x); return u * u * (3 - 2 * u); };
const wrapDeg = (a) => ((((a + 180) % 360) + 360) % 360) - 180;
const lerp2 = (a, b, w) => [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w];

function hopPose(u, small) {
  const seq = [[0, SIT], [0.12, GATHER], [0.26, PUSH], [0.42, FLY], [0.58, LAND], [0.72, SWING], [0.84, SETTLE], [1, SIT]];
  let i = 0;
  while (i < seq.length - 2 && u >= seq[i + 1][0]) i++;
  const [u0, a] = seq[i], [u1, b] = seq[i + 1];
  const p = mix(a, b, smooth((u - u0) / (u1 - u0)));
  return small ? mix(SIT, p, 0.55) : p;
}

// R_y(a): a point of a frame turned by a (rad, heading) into the frame around it; x across, z forward
const rot = (a, x, z) => [x * Math.cos(a) + z * Math.sin(a), -x * Math.sin(a) + z * Math.cos(a)];

// The paws in a hop, in the root's frame at u: { front: [[x, y, z], ...], hind: [[x, y, z, footAngle], ...] }. The hop
// goes D units along its own heading; the root starts turned d0 rad from it and turns to it (kh of the way at u), and
// its middle is s of the way. A paw on the floor stays where it was planted at the start, or where it lands at the end.
function hopPaws(u, s, D, d0, kh, arc) {
  const du = d0 * (1 - kh);
  const at = (o, end) => {
    const P = end ? [o[0], D + o[1]] : rot(d0, o[0], o[1]);
    return rot(-du, P[0], P[1] - s * D);
  };
  const front = [], hind = [];
  for (const sx of [1, -1]) {
    const o = [sx * PAW.x, PAW.z];
    if (u < 0.12) {
      const q = at(o, false);
      front.push([q[0], PAW.y, q[1]]);
    } else if (u < 0.58) {
      const k = (u - 0.12) / 0.46, q = lerp2(at(o, false), at(o, true), smooth(k));
      front.push([q[0], PAW.y + 1.6 * Math.sin(Math.PI * k) + arc, q[1]]);
    } else {
      const q = at(o, true);
      front.push([q[0], PAW.y, q[1]]);
    }
    const oh = [sx * HEEL.x, HEEL.z];
    // the push: the heel rises while the toes stay on the floor (the foot turns about them)
    const fa0 = 0.6 * smooth((Math.min(u, 0.28) - 0.14) / 0.14);
    const lift = [LEG.foot * Math.sin(fa0), LEG.foot * (1 - Math.cos(fa0))];
    if (u < 0.28) {
      const q = at(oh, false);
      hind.push([q[0], HEEL.y + lift[0], q[1] + lift[1], fa0]);
    } else if (u < 0.8) {
      const k = (u - 0.28) / 0.52, w = Math.pow(smooth(k), 1.35);
      const a = at(oh, false), b = at(oh, true);
      const q = lerp2([a[0], a[1] + lift[1]], b, w);
      const fa = k < 0.3 ? fa0 + (2.0 - fa0) * smooth(k / 0.3) : k < 0.85 ? 2.0 + (0.35 - 2.0) * smooth((k - 0.3) / 0.55) : 0.35 * (1 - smooth((k - 0.85) / 0.15));
      hind.push([q[0], HEEL.y + lift[0] * (1 - w) + 1.2 * Math.sin(Math.PI * k) + arc, q[1], fa]);
    } else {
      const q = at(oh, true);
      hind.push([q[0], HEEL.y, q[1], 0]);
    }
  }
  return { front, hind };
}

const SIT_PAWS = {
  front: [[PAW.x, PAW.y, PAW.z], [-PAW.x, PAW.y, PAW.z]],
  hind: [[HEEL.x, HEEL.y, HEEL.z, 0], [-HEEL.x, HEEL.y, HEEL.z, 0]],
};

// Seeded smooth noise in -1..1: two sines at unrelated rates.
const wander = (t, seed, k, hz) => 0.6 * Math.sin(TAU * hz * t + 6.28 * hash3(seed, k, 1)) + 0.4 * Math.sin(TAU * hz * 2.37 * t + 6.28 * hash3(seed, k, 2));

// Where the rabbit is at tau s into its event and how it holds itself: { x, y (image coords: the floor under it),
// h (heading, rad), arc (units above the floor), pose, paws, act: { kind, w, stroke, side }, yaw, ears: [a, b], nose,
// eye, breath, hop: { u, s, D, du } while it hops (how far through the hop, its middle's share of the way, the way in
// units, its heading off the hop's own) or null }.
export function rabbitAt(ev, tau) {
  const hops = ev.hops ?? [];
  if (!hops.length || tau < 0 || tau > ev.dur) return null;
  const seed = ev.seed ?? 1;
  const i = hops.findIndex((h) => tau < h[0] + h[1]);
  let x, y, hd, arc = 0, pose, paws, hopping = false, hop = null;
  if (i >= 0 && tau >= hops[i][0]) {
    const [t0, d, x0, y0, x1, y1, h0, h1, hg, turn, dist] = hops[i];
    const u = (tau - t0) / d, s = smooth((u - 0.1) / 0.8);
    x = x0 + (x1 - x0) * s; y = y0 + (y1 - y0) * s;
    const kh = smooth((u - 0.08) / 0.6);
    hd = h0 + wrapDeg(h1 - h0) * kh;
    const v = clamp01((u - 0.28) / 0.3);
    arc = hg * BL * Math.sin(Math.PI * v);
    pose = hopPose(u, !!turn);
    const D = (dist ?? 0) * BL, d0 = wrapDeg(h0 - h1) * DEG;
    paws = hopPaws(u, s, D, d0, kh, arc);
    hopping = true;
    hop = { u, s, D, du: d0 * (1 - kh) };
  } else {
    const k = i < 0 ? hops.length - 1 : i - 1;
    if (k < 0) { x = hops[0][2]; y = hops[0][3]; hd = hops[0][6]; } else { x = hops[k][4]; y = hops[k][5]; hd = hops[k][7]; }
    // a long sit: it settles into a loaf, belly down and paws tucked, and perks up again before it hops off
    const since = k < 0 ? 0 : tau - (hops[k][0] + hops[k][1]), until = i < 0 ? 1e9 : hops[i][0] - tau;
    const w = since + until > 8 ? smooth((since - 1.5) / 2.5) * smooth((until - 0.8) / 2.0) : 0;
    pose = mix(SIT, LOAF, w);
    paws = w > 0 ? { front: SIT_PAWS.front.map((q) => [q[0], q[1], q[2] - 0.6 * w]), hind: SIT_PAWS.hind.map((q) => [q[0], q[1], q[2] + 0.2 * w, 0]) } : SIT_PAWS;
  }
  // an act blends in and out over 0.45 s
  let act = null, yaw = 0, earBias = 0;
  for (const [a0, ad, kind, side] of ev.acts ?? []) {
    if (tau < a0 || tau > a0 + ad || hopping) continue;
    const w = smooth((tau - a0) / 0.45) * smooth((a0 + ad - tau) / 0.45);
    pose = mix(pose, ACT[kind] ?? SIT, w);
    act = { kind, w, side: side || 1, stroke: 0.5 - 0.5 * Math.cos((TAU * (tau - a0)) / 0.75) };
    if (kind === 'groom') pose.ha -= 0.12 * act.stroke * w;
    if (kind === 'look') { yaw = (side || 1) * 0.7 * w; earBias = (side || 1) * 0.35 * w; }
    if (kind === 'up') yaw = 0.35 * w * wander(tau, seed, 9, 0.18);
    break;
  }
  // life: the nose twitches in bursts (always while sniffing), each ear swivels on its own, it breathes, and it blinks
  // now and then (rabbits blink seldom)
  const win = Math.floor(tau / 2.2);
  const twitchOn = act?.kind === 'sniff' || hash3(seed, win, 3) > 0.45;
  const nose = twitchOn && !hopping ? 0.14 * Math.max(0, Math.sin(TAU * 5.5 * tau)) : 0;
  const ears = [0, 1].map((k) => (hopping ? 0 : 0.22 * wander(tau, seed, 4 + k, 0.09)) + earBias);
  const T0 = 9 + 10 * hash3(seed, 7, 7), ph = (tau + 13 * hash3(seed, 8, 8)) % T0;
  const eye = ph < 0.16 ? 0.15 : 1;
  const breath = 1 + 0.018 * Math.sin(TAU * 0.75 * tau);
  if (!hopping) yaw += 0.12 * wander(tau, seed, 6, 0.05);
  return { x, y, h: hd * DEG, arc, pose, paws, act, yaw, ears, nose, eye, breath, hop };
}

// ---- kinematics in the root's frame (y up, z the way it faces), the floor at y 0 ----
// Two bones from a to the target: the bend on the forward side (a hind knee) or the back (a front elbow).
function ik2(a, tgt, L1, L2, back) {
  const dy = tgt[1] - a[1], dz = tgt[2] - a[2];
  let d = Math.hypot(dy, dz);
  const dMax = L1 + L2 - 0.05, dMin = Math.abs(L1 - L2) + 0.05;
  const k = d > dMax ? dMax / d : d < dMin ? dMin / Math.max(d, 1e-6) : 1;
  const e = [tgt[0], a[1] + dy * k, a[2] + dz * k];
  d = Math.min(dMax, Math.max(dMin, d));
  const th = Math.atan2(e[1] - a[1], e[2] - a[2]);
  const al = Math.acos(Math.min(1, Math.max(-1, (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))));
  const mx = (a[0] + e[0]) / 2;
  const c1 = [mx, a[1] + L1 * Math.sin(th + al), a[2] + L1 * Math.cos(th + al)];
  const c2 = [mx, a[1] + L1 * Math.sin(th - al), a[2] + L1 * Math.cos(th - al)];
  return { mid: (c1[2] >= c2[2]) !== back ? c1 : c2, end: e };
}

const Z = new THREE.Vector3(0, 0, 1);
const tmp = new THREE.Vector3();
function place(mesh, a, b, len) {
  tmp.set(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  const n = tmp.length() || 1;
  tmp.divideScalar(n);
  mesh.quaternion.setFromUnitVectors(Z, tmp);
  mesh.position.set(a[0] + (tmp.x * len) / 2, a[1] + (tmp.y * len) / 2, a[2] + (tmp.z * len) / 2);
}

function applyPose(M, st) {
  const P = st.pose, c = Math.cos(P.p), s = Math.sin(P.p), sq = P.sq;
  const ry = P.ry + st.arc, rz = PIVOT_Z + P.zo;
  // a point of the trunk (its frame: y up from the belly, z forward from the rump) in the root's frame
  const R = (x, y, z) => [x, ry + y * c + z * s, rz + z * c - y * s];
  M.trunkG.position.set(0, ry, rz);
  M.trunkG.rotation.set(-P.p, 0, 0);
  M.trunk.scale.set(1, st.breath, sq);
  M.trunk.position.set(0, (T.h / 2) * st.breath, (T.l * sq) / 2);
  M.tail.position.set(0, T.h * 0.62, -0.35);
  M.tail.rotation.set(-0.5 * P.tl, 0, 0);
  M.headG.position.set(0, T.h * 0.7, T.l * sq - 0.5);
  M.headG.rotation.set(-(P.ha - P.p), st.yaw, 0);
  M.muzzle.position.set(0, -0.35 + st.nose, HD.l / 2 + 1.2 + MZ.l / 2 - 0.15);
  for (const e of M.eyes) e.scale.y = st.eye;
  M.ears.forEach((g, i) => g.rotation.set(-P.eb, st.ears[i] + (i ? -0.08 : 0.08), (i ? -1 : 1) * 0.12));
  M.legs.forEach((L, i) => {
    const sd = L.s, hp = R(sd * (T.w / 2 + 0.15), LEG.hip[0], LEG.hip[1]);
    const tg = st.paws.hind[i];
    const { mid, end } = ik2(hp, tg, LEG.thigh, LEG.shin, false);
    const fa = tg[3] ?? 0;
    const toe = [end[0], end[1] - Math.sin(fa) * LEG.foot, end[2] + Math.cos(fa) * LEG.foot];
    place(L.thigh, hp, mid, LEG.thigh);
    place(L.shin, mid, end, LEG.shin);
    place(L.foot, end, toe, LEG.foot);
  });
  M.arms.forEach((A, i) => {
    const sd = A.s, sh = R(sd * (T.w / 2 - 0.8), 0.9, T.l * sq - 1.0);
    let tg = st.paws.front[i];
    const ac = st.act;
    if (ac && (ac.kind === 'up' || ac.kind === 'groom')) {
      // off the floor: held before the chest (sitting up), or rubbing up and down the face (washing)
      const body = ac.kind === 'up' ? [sh[0] - sd * 0.3, sh[1] - 1.2, sh[2] + 0.45]
        : [sh[0] - sd * 0.55, sh[1] + 0.2 + 1.3 * ac.stroke, sh[2] + 1.7];
      tg = tg.map((v, k) => v + (body[k] - v) * ac.w);
    }
    const { mid, end } = ik2(sh, tg, ARM.up, ARM.fore, true);
    place(A.up, sh, mid, ARM.up);
    place(A.fore, mid, end, ARM.fore);
    A.paw.quaternion.identity();
    A.paw.position.set(end[0], end[1], end[2] + ARM.paw[2] / 2 - 0.35);
  });
}

// ---- the layer (creature3d.js composites it: lit from the plate, hidden behind nearer things, a contact shadow, and
// its reflection on a glossy floor) ----
export function rabbitLayer(ctx, opts) {
  return creatureLayer(ctx, opts, {
    type: 'rabbit', BL, span: 30, cy: 5, maxRT: 1536, above: [-0.8, -1.5, 0.8, -0.5], ground: [-0.7, -0.15, 0.7, 0.2],
    build: () => buildRabbit(opts.palette ?? 'snow', opts.texels ?? 2.0),
    at: rabbitAt,
    apply: applyPose,
    footprint: () => [BL * 0.85, T.w + 2.2],
  });
}
