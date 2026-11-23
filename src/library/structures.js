// Built structures for exteriors and interiors: lanterns, railings, plank cabins with stepped roofs,
// treehouses, rope bridges, village cottages, docks. Origins: footprint center on the ground, front = +z.
import { mat, T } from './props.js';

const plankWall = (tint = '#7a5236') => ({ tex: { name: 'planks', color: '#f2f2f2', plank: 4, v: 0.16 }, tint, rough: 0.9 });
const shingle = (tint = '#4a3428') => ({ tex: { name: 'shingles', color: '#f2f2f2' }, tint, rough: 0.9 });
const iron = mat.plain('#1c1814', 0.6);

// Iron lantern: frame posts around a glowing core, pyramid cap, ring. Returns the core's world position.
export function lantern(b, { s = 0.42, glow = 7, color = '#ffb050', hang = 0 } = {}) {
  const h = s * 1.35, p = s * 0.12;
  if (hang > 0) b.box([-T / 3, h + s * 0.35, -T / 3], [T / 3, h + s * 0.35 + hang, T / 3], iron);
  b.box([-s / 2, 0, -s / 2], [s / 2, p, s / 2], iron);
  b.box([-s / 2 + p * 0.6, p, -s / 2 + p * 0.6], [s / 2 - p * 0.6, h - p, s / 2 - p * 0.6], mat.bulb(color, glow));
  for (const x of [-s / 2, s / 2 - p]) for (const z of [-s / 2, s / 2 - p]) b.box([x, p, z], [x + p, h - p, z + p], iron);
  // One vertical bar across the middle of each face.
  b.box([-p / 2, p, -s / 2 + p * 0.3], [p / 2, h - p, -s / 2 + p * 0.9], iron);
  b.box([-p / 2, p, s / 2 - p * 0.9], [p / 2, h - p, s / 2 - p * 0.3], iron);
  b.box([-s / 2 + p * 0.3, p, -p / 2], [-s / 2 + p * 0.9, h - p, p / 2], iron);
  b.box([s / 2 - p * 0.9, p, -p / 2], [s / 2 - p * 0.3, h - p, p / 2], iron);
  b.box([-s / 2 - p * 0.3, h - p, -s / 2 - p * 0.3], [s / 2 + p * 0.3, h, s / 2 + p * 0.3], iron);
  b.box([-s * 0.32, h, -s * 0.32], [s * 0.32, h + s * 0.18, s * 0.32], iron);
  b.box([-s * 0.12, h + s * 0.18, -s * 0.12], [s * 0.12, h + s * 0.35, s * 0.12], iron);
  return b.world([0, h / 2, 0]);
}

// Wall bracket + hanging lantern (bracket sticks out along +z from the wall at origin).
export function wallLantern(b, { reach = 0.9, drop = 0.5, s = 0.42, glow = 7, color } = {}) {
  b.box([-T, -0.3, 0], [T, 0.15, 2 * T], iron);
  b.box([-T, 0.05, 0], [T, 0.15, reach], iron);
  b.box([-T, -0.15, 0], [T, -0.05, reach * 0.4], iron);
  let pos;
  b.at([0, -drop - s * 1.35 - s * 0.35, reach - T], 0, () => { pos = lantern(b, { s, glow, color, hang: drop }); });
  return pos;
}

// Railing along local x from x0..x1 at z, height h: posts, top rail, balusters.
export function railing(b, { x0, x1, z = 0, h = 1.1, m = mat.wood('#4a2e1c'), postEvery = 2.5, balusterEvery = 0.5, posts = [] }) {
  const pw = 0.22;
  const ps = [];
  for (let x = x0; x <= x1 + 1e-6; x += postEvery) ps.push(Math.min(x, x1 - pw));
  if (ps[ps.length - 1] < x1 - pw - 0.05) ps.push(x1 - pw);
  for (const x of ps) { b.box([x, 0, z - pw / 2], [x + pw, h + 0.12, z + pw / 2], m); posts.push(b.world([x + pw / 2, h + 0.12, z])); }
  b.box([x0, h - 0.12, z - 0.14], [x1, h, z + 0.14], m);
  b.box([x0, 0.25, z - 0.06], [x1, 0.37, z + 0.06], m);
  for (let x = x0 + balusterEvery; x < x1 - 0.1; x += balusterEvery) b.box([x - T, 0.37, z - T], [x + T, h - 0.12, z + T], m);
  return posts;
}

// Stepped hip roof (pyramid of slabs) or gable (steps along z). Base at y=0, footprint w x d with overhang.
export function steppedRoof(b, { w, d, steps = 5, stepH = 0.35, overhang = 0.4, m = shingle(), trim = mat.wood('#2e1e14'), gable = false }) {
  for (let i = 0; i < steps; i++) {
    const k = i / steps;
    const hw = (w / 2 + overhang) * (1 - k * (gable ? 0 : 0.9)), hd = (d / 2 + overhang) * (1 - k * 0.9);
    b.box([-hw, i * stepH, -hd], [hw, (i + 1) * stepH, hd], m, { faces: { ny: trim } });
  }
  if (gable) {
    b.box([-w / 2, 0, -T], [w / 2, steps * stepH * 0.85, T], m);
  } else {
    b.box([-0.2, steps * stepH, -0.2], [0.2, steps * stepH + 0.3, 0.2], trim);
  }
  return steps * stepH;
}

// Window with frame + lit (or dark) panes on a wall facing +z at z (protrudes slightly).
export function wallWindow(b, { x, y, w = 1.2, h = 1.3, z, lit = true, color = '#ffb35c', glow = 2.2, frame = '#2a1a10', curtain = '#8a3a2a', cols = 2, rows = 2 }) {
  const tw = Math.max(8, Math.round(w * 16)), th = Math.max(8, Math.round(h * 16));
  const pane = lit
    ? { tex: { name: 'litWindow', color, frame, curtain, w: tw, h: th, cols, rows, curtainW: Math.round(tw * 0.18) }, tint: '#ffffff', emissive: glow, emissiveColor: '#ffffff', cast: false }
    : mat.plain('#14161e', 0.3);
  b.box([x - w / 2, y, z], [x + w / 2, y + h, z + T], pane);
  const fm = mat.wood(frame);
  b.box([x - w / 2 - T, y - 2 * T, z], [x + w / 2 + T, y, z + 3 * T], fm);
  b.box([x - w / 2 - T, y + h, z], [x + w / 2 + T, y + h + 1.5 * T, z + 2 * T], fm);
}

// Plank cabin: corner logs, plank walls, stepped roof, windows on the front (+z) and sides.
export function cabin(b, { w = 5, d = 4, h = 3, rng, wall = '#7a5236', roof = '#4a3428', corner = '#3e2a1a', lit = 0.8, windowColor = '#ffb35c', roofSteps = 5, gable = false, door = true, chimney = false, glow = 2.2 }) {
  const lights = [];
  b.box([-w / 2, 0, -d / 2], [w / 2, h, d / 2], plankWall(wall));
  const cm = mat.wood(corner);
  for (const x of [-w / 2 - 0.12, w / 2 - 0.28]) for (const z of [-d / 2 - 0.12, d / 2 - 0.28]) b.box([x, -0.1, z], [x + 0.4, h + 0.1, z + 0.4], cm);
  b.box([-w / 2 - 0.1, h - 0.25, -d / 2 - 0.1], [w / 2 + 0.1, h + 0.05, d / 2 + 0.1], cm);
  const nWin = Math.max(1, Math.floor((w - (door ? 1.6 : 0)) / 2));
  for (let i = 0; i < nWin; i++) {
    const x = -w / 2 + (w - (door ? 1.6 : 0)) * ((i + 0.5) / nWin);
    const on = rng.chance(lit);
    wallWindow(b, { x, y: h * 0.38, w: 1.05, h: h * 0.38, z: d / 2, lit: on, color: windowColor, glow });
    if (on) lights.push(b.world([x, h * 0.55, d / 2 + 0.6]));
  }
  for (const side of [-1, 1]) if (rng.chance(0.7)) {
    b.at([side * w / 2, 0, 0], side * Math.PI / 2, () => wallWindow(b, { x: 0, y: h * 0.38, w: 0.9, h: h * 0.36, z: 0, lit: rng.chance(lit), color: windowColor, glow }));
  }
  if (door) {
    b.box([w / 2 - 1.4, 0, d / 2], [w / 2 - 0.4, h * 0.72, d / 2 + T], mat.wood('#3a2416'));
    b.box([w / 2 - 0.62, h * 0.33, d / 2 + T], [w / 2 - 0.52, h * 0.38, d / 2 + 2 * T], mat.metal('#c8a050'));
  }
  b.at([0, h, 0], 0, () => steppedRoof(b, { w, d, steps: roofSteps, stepH: (Math.min(w, d) * 0.55) / roofSteps, m: shingle(roof), gable }));
  if (chimney) b.box([w / 4, h, -d / 4], [w / 4 + 0.7, h + Math.min(w, d) * 0.7, -d / 4 + 0.7], { tex: { name: 'stone' }, tint: '#9a8a7a', rough: 1 });
  return { lights };
}

// Treehouse: platform around a trunk at height `y`, braces, railing with lanterns, cabin on top.
export function treehouse(b, { y = 10, w = 7, d = 6, cabinW = 4.6, cabinD = 3.8, cabinH = 3, rng, lanterns = 3, wall, roof, glow = 2.4 }) {
  const deck = mat.planks('#6a4a30');
  const beam = mat.wood('#3a2618');
  const out = { lanterns: [], windows: [], front: b.world([0, y, d / 2]) };
  b.box([-w / 2, y - 0.3, -d / 2], [w / 2, y, d / 2], deck);
  for (const x of [-w / 2 + 0.3, w / 2 - 0.6]) b.box([x, y - 0.75, -d / 2], [x + 0.3, y - 0.3, d / 2], beam);
  for (const z of [-d / 2, d / 2 - 0.3]) b.box([-w / 2, y - 0.6, z], [w / 2, y - 0.3, z + 0.3], beam);
  for (const s of [-1, 1]) {
    for (let i = 0; i < 6; i++) { const k = i / 6; b.box([s * (0.5 + k * (w / 2 - 0.8)) - 0.18, y - 3 + k * 2.4, d / 2 - 0.5], [s * (0.5 + k * (w / 2 - 0.8)) + 0.18, y - 2.6 + k * 2.4, d / 2 - 0.2], beam); }
  }
  b.at([0, y, 0], 0, () => {
    const posts = [];
    railing(b, { x0: -w / 2, x1: w / 2, z: d / 2 - 0.15, posts });
    b.at([-w / 2 + 0.15, 0, 0], Math.PI / 2, () => railing(b, { x0: -d / 2, x1: d / 2, z: 0, posts }));
    b.at([w / 2 - 0.15, 0, 0], -Math.PI / 2, () => railing(b, { x0: -d / 2, x1: d / 2, z: 0, posts }));
    const c = cabin(b, { w: cabinW, d: cabinD, h: cabinH, rng, wall, roof, lit: 1, glow });
    out.windows.push(...c.lights);
    const picks = [posts[0], posts[Math.floor(posts.length / 3)], posts[posts.length - 1]].slice(0, lanterns);
    out.lanterns.push(...picks);
  });
  for (const p of out.lanterns) b.atWorld(p, 0, () => lantern(b, { s: 0.38, glow: 9 }));
  out.lanterns = out.lanterns.map((p) => [p[0], p[1] + 0.25, p[2]]);
  return out;
}

// Rope bridge between world points A and B (planks on a sagging curve, rope rails, hangers, end posts).
export function ropeBridge(b, { A, B, width = 1.4, sag = 1.2, plank = 0.32, gap = 0.12, m = mat.wood('#5a3e28'), rope = '#a08058', lanterns = true, lanternGlow = 9, lanternEnds = [true, true] }) {
  const rm = { tex: { name: 'rope', color: '#f2f2f2' }, tint: rope, rough: 1 };
  const dx = B[0] - A[0], dy = B[1] - A[1], dz = B[2] - A[2];
  const len = Math.hypot(dx, dz);
  const yaw = Math.atan2(dx, dz);
  const P = (t) => [A[0] + dx * t, A[1] + dy * t - sag * 4 * t * (1 - t), A[2] + dz * t];
  const n = Math.floor(len / (plank + gap));
  const hw = width / 2;
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = (i + 0.5) / n;
    const p = P(t), q = P(Math.min(1, t + 0.01));
    const slope = Math.atan2(q[1] - p[1], Math.hypot(q[0] - p[0], q[2] - p[2]));
    b.at(p, yaw, () => b.box([-hw, -0.08, -plank / 2], [hw, 0.04, plank / 2], m), { rotX: -slope });
  }
  const steps = Math.ceil(len / 0.3);
  for (let i = 0; i <= steps; i++) {
    const t = i / steps, p = P(t);
    const rail = 1.0 + 0.25 * (1 - 4 * t * (1 - t));
    for (const s of [-1, 1]) {
      b.at(p, yaw, () => {
        b.box([s * hw - T, rail - T, -0.16], [s * hw + T, rail + T, 0.16], rm);
        if (i % 3 === 0) b.box([s * hw - T / 2, 0, -T / 2], [s * hw + T / 2, rail, T / 2], rm);
      });
    }
  }
  for (const t of [0, 1]) {
    for (const s of [-1, 1]) b.at(P(t), yaw, () => {
      b.box([s * (hw + 0.1) - 0.13, -0.6, -0.13], [s * (hw + 0.1) + 0.13, 1.6, 0.13], mat.wood('#3a2618'));
      if (lanterns && s > 0 && lanternEnds[t]) out.push(b.world([s * (hw + 0.1), 1.6, 0]));
    });
  }
  for (const p of out) b.atWorld(p, 0, () => lantern(b, { s: 0.34, glow: lanternGlow }));
  return out.map((p) => [p[0], p[1] + 0.25, p[2]]);
}

// Village cottage on a stone base with a gable roof; for lake shores.
export function cottage(b, { w = 6, d = 5, h = 3.4, rng, wall = '#8a6a48', roof = '#3a2a24', lit = 0.85, glow = 2.6 }) {
  b.box([-w / 2 - 0.2, -1.2, -d / 2 - 0.2], [w / 2 + 0.2, 0.2, d / 2 + 0.2], { tex: { name: 'stone' }, tint: '#8a8070', rough: 1 });
  b.at([0, 0.2, 0], 0, () => cabin(b, { w, d, h, rng, wall, roof, lit, gable: rng.chance(0.5), chimney: rng.chance(0.6), glow, roofSteps: 6 }));
}

// Plank dock from the shore at origin out along -z, with posts and optional lantern posts.
export function dock(b, { len = 10, w = 2.4, y = 0.4, postDepth = 2, lanternEvery = 0 }) {
  const out = [];
  b.box([-w / 2, y - 0.2, -len], [w / 2, y, 0], mat.planks('#5a4030'));
  for (let z = 0; z >= -len; z -= 3) for (const x of [-w / 2, w / 2 - 0.25]) b.box([x, y - postDepth, z - 0.25], [x + 0.25, y + 0.3, z], mat.wood('#2e2016'));
  if (lanternEvery) for (let z = -lanternEvery; z >= -len; z -= lanternEvery) {
    b.box([w / 2 - 0.25, y, z - 0.2], [w / 2 - 0.05, y + 2.2, z], mat.wood('#2e2016'));
    b.at([w / 2 - 0.15, y + 2.2, z - 0.1], 0, () => out.push(lantern(b, { s: 0.36, glow: 9 })));
  }
  return out;
}

export { plankWall, shingle };
