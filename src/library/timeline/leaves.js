// Leaf and petal schedules: what falls, where and when, for leaves.js and petals.js.

import { mulberry32, hashStr, r3 } from './random.js';
import { windAt } from './wind.js';
import { trackAt } from './weather.js';

// Falling leaves: a Poisson stream thinned by gust strength (gusts shake leaves loose). Each leaf carries
// everything leaves.js needs to compute its flight as a pure function of time.
// spec: { perMinute, gustBoost, depth: [m, m], size: [m, m], x: [frac, frac], wind: {mean, gust, gustCycles, fronts, loop},
//         focalPx, height (px), palette: [first, last] }
export function leafSchedule(L, seed, duration, track, flurries = []) {
  const r = mulberry32((Math.imul(seed, 3266489917) ^ hashStr('leaves')) >>> 0);
  const U = (a, b) => a + (b - a) * r();
  const w = L.wind ?? { mean: 0, gust: 0, gustCycles: 1, fronts: 0, loop: 120 };
  const base = (L.perMinute ?? 2.5) / 60, boost = L.gustBoost ?? 1.2;
  const gNom = Math.abs(w.mean) + Math.abs(w.gust) + 1e-6;
  const rate = (t) => base * (0.45 + boost * Math.abs(windAt(w, t, 0.45, trackAt(track, 'wind', t))) / gNom);
  const rmax = base * (0.45 + boost * 1.8);
  const [z0, z1] = L.depth ?? [2.4, 7], [s0, s1] = L.size ?? [0.06, 0.11], [x0, x1] = L.x ?? [0.03, 0.83];
  const F = L.focalPx ?? 2700, H = L.height ?? 2160;
  const [p0, p1] = L.palette ?? [2, 5];
  const out = [];
  const leaf = (rr, t) => {
    const Ur = (a, b) => a + (b - a) * rr();
    const z = z0 * Math.pow(z1 / z0, Math.pow(rr(), 1.6));     // more near leaves
    const size = Ur(s0, s1), vt = Ur(0.5, 0.95), ppm = F / z;
    const p = {
      t: r3(t), x: r3(Ur(x0, x1)), z: r3(z), s: r3(size), shape: Math.floor(rr() * 3), c: p0 + Math.floor(rr() * (p1 - p0 + 1)),
      red: r3(Math.pow(rr(), 2)), vt: r3(vt), A: r3(Ur(0.08, 0.3)), f: r3(Ur(0.35, 0.85)), ph: r3(Ur(0, 6.283)),
      B: r3(Ur(0.2, 0.7)), spin: r3((rr() < 0.3 ? 1 : 0) * Ur(-2.5, 2.5)), fl: r3(Ur(0.4, 1.6)), fm: rr() < 0.55 ? 1 : 0, th0: r3(Ur(-3.14, 3.14)),
    };
    p.dur = r3((H + 2 * size * ppm + 40) / (vt * ppm) + 0.5);
    return p;
  };
  let t = L.startAfter ?? 5;
  while (true) {
    t += -Math.log(1 - r()) / rmax;
    if (t >= duration - 2) break;
    const accept = r() < rate(t) / rmax;
    // Draw all parameters whether or not the leaf is accepted, so rate tuning doesn't reshuffle leaves.
    const p = leaf(r, t);
    if (accept) out.push(p);
  }
  // Gust flurries shake a handful of leaves loose at once (own random stream: the regular leaves stay put).
  for (const f of flurries) {
    const rf = mulberry32((f.seed ^ hashStr('flurry-leaves')) >>> 0);
    for (let i = 0; i < (f.leaves ?? 0); i++) {
      const tl = f.t + f.dur * (0.15 + 0.5 * rf());
      if (tl < duration - 2) out.push(leaf(rf, tl));
    }
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

// Cherry petals (petals.js): specks drifting down from a blossoming tree in the plate (tree: its canopy box), and
// now and then a petal blown past near the opening that lands on the street (near). Both are Poisson streams
// thinned by gust strength, and every gust flurry shakes a burst loose. Each petal carries everything petals.js
// needs to compute its flight as a pure function of time.
// spec: { wind: {mean, gust, gustCycles, fronts, loop}, gustBoost (1.4), dir (prevailing drift: 1 right, -1 left),
//         tree: { perMinute, box: [x0, y0, x1, y1], fall: m below the canopy (6), drift: [m/s, m/s] (0.15-0.5) },
//         near: { perMinute, depth: [m, m], x: [frac, frac], stay: [s, s], drift: [m/s, m/s] (0.1-0.4) },
//         flurry: { tree: [n0, n1], near: [n0, n1] } }
export function petalSchedule(P, seed, duration, track, flurries = []) {
  const w = P.wind ?? { mean: 0, gust: 0, gustCycles: 1, fronts: 0, loop: 120 };
  const gNom = Math.abs(w.mean) + Math.abs(w.gust) + 1e-6, boost = P.gustBoost ?? 1.4;
  const out = [];
  const T = P.tree, N = P.near;
  // the air petals drift on: a breeze too light to tilt the rain (it falls at 6-9 m/s) still carries a petal
  // sideways at a few tenths of a m/s, along the prevailing wind (P.dir: 1 right, -1 left)
  const dir = P.dir ?? (Math.sign(w.mean) || 1);
  const tree = (rr, t) => {
    const U = (a, b) => a + (b - a) * rr();
    const [x0, y0, x1, y1] = T.box;
    // a point in the canopy (the ellipse in its box), petals fall from its lower half more often
    const a = U(0, 6.2832), q = Math.sqrt(rr());
    const vt = U(0.55, 0.95);
    return {
      k: 0, t: r3(t), x: r3((x0 + x1) / 2 + 0.45 * (x1 - x0) * q * Math.cos(a)), y: r3((y0 + y1) / 2 + 0.4 * (y1 - y0) * Math.abs(q * Math.sin(a)) * (rr() < 0.7 ? 1 : -1)),
      s: r3(U(0.012, 0.016)), vt: r3(vt), A: r3(U(0.05, 0.18)), f: r3(U(0.4, 0.9)), ph: r3(U(0, 6.283)), B: r3(U(0.3, 0.9)),
      spin: r3(U(-2, 2)), fl: r3(U(0.8, 2.2)), th0: r3(U(-3.14, 3.14)), c: r3(rr()), dur: r3((T.fall ?? 6) / vt + 0.5),
      vx: r3(dir * U(...(T.drift ?? [0.15, 0.5]))),
    };
  };
  const near = (rr, t) => {
    const U = (a, b) => a + (b - a) * rr();
    const [z0, z1] = N.depth ?? [3.5, 8], [x0, x1] = N.x ?? [0.3, 0.75], [s0, s1] = N.stay ?? [20, 40];
    const vt = U(0.5, 0.85);
    return {
      k: 1, t: r3(t), x: r3(U(x0, x1)), z: r3(z0 * Math.pow(z1 / z0, rr())), s: r3(U(0.012, 0.016)), vt: r3(vt), A: r3(U(0.08, 0.25)),
      f: r3(U(0.35, 0.8)), ph: r3(U(0, 6.283)), B: r3(U(0.3, 0.9)), spin: r3(U(-2.5, 2.5)), fl: r3(U(0.7, 1.8)), th0: r3(U(-3.14, 3.14)),
      c: r3(rr()), stay: r3(U(s0, s1)), vx: r3(dir * U(...(N.drift ?? [0.1, 0.4]))),
    };
  };
  const poisson = (key, perMinute, make) => {
    const r = mulberry32((Math.imul(seed, 3266489917) ^ hashStr(key)) >>> 0);
    const base = perMinute / 60, rmax = base * (0.45 + boost * 1.8);
    const rate = (t) => base * (0.45 + boost * Math.abs(windAt(w, t, 0.45, trackAt(track, 'wind', t))) / gNom);
    let t = P.startAfter ?? 2;
    while (true) {
      t += -Math.log(1 - r()) / rmax;
      if (t >= duration - 2) break;
      const accept = r() < rate(t) / rmax;
      const p = make(r, t);
      if (accept) out.push(p);
    }
  };
  if (T?.perMinute && T.box) poisson('petals-tree', T.perMinute, tree);
  if (N?.perMinute) poisson('petals-near', N.perMinute, near);
  // a gust flurry shakes a burst loose (own random stream per flurry)
  for (const f of flurries) {
    const rf = mulberry32((f.seed ^ hashStr('flurry-petals')) >>> 0);
    const [a0, a1] = P.flurry?.tree ?? [10, 24], [b0, b1] = P.flurry?.near ?? [3, 7];
    const nt = T?.box ? a0 + Math.floor(rf() * (a1 - a0 + 1)) : 0, nn = N ? b0 + Math.floor(rf() * (b1 - b0 + 1)) : 0;
    for (let i = 0; i < nt; i++) { const tl = f.t + f.dur * (0.1 + 0.6 * rf()); if (tl < duration - 2) out.push(tree(rf, tl)); }
    for (let i = 0; i < nn; i++) { const tl = f.t + f.dur * (0.05 + 0.5 * rf()); if (tl < duration - 2) out.push(near(rf, tl)); }
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}
