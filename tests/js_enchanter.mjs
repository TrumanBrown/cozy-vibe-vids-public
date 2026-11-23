// The Enchanter's Tower's movers, for tests/test_enchanter.py: node tests/js_enchanter.mjs <scene.json> <out.json>
// The pure functions behind them over a 20 minute loop at 30 fps: the book (enchant.js flipSchedule, bookPose), the
// tank's fish and axolotl (aquarium.js tankMap, fishSwims, fishAt, axolotlPlan), the happy ghast (ghast.js ghastAt) and
// the timeline's ghast events for a 10 h spec.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { flipSchedule, bookPose } = await imp('src/library/enchant.js');
const { tankMap, fishSwims, fishAt, axolotlPlan } = await imp('src/library/aquarium.js');
const { ghastAt } = await imp('src/library/ghast.js');
const { buildTimeline } = await imp('src/library/timeline.js');

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const P = spec.events?.loop?.period ?? 1200, seed = spec.seed ?? 1, dt = 1 / 30;
const out = {};

// the book: the largest change of any loose page between frames, and the pose either side of the loop's join
const flips = flipSchedule(P, seed);
let worstPsi = 0, worstLift = 0, missing = 0, prev = bookPose(0, P, flips);
for (let f = 1; f < P * 30; f++) {
  const b = bookPose(f * dt, P, flips);
  b.pages.forEach((p, i) => {
    if (!p) { missing++; return; }
    worstPsi = Math.max(worstPsi, Math.abs(p.psi - prev.pages[i].psi));
    worstLift = Math.max(worstLift, Math.abs(p.lift - prev.pages[i].lift));
  });
  prev = b;
}
// the loop's join: its last frame against the one just before its start, which is the same moment of the loop
const end = bookPose(P - dt, P, flips), start = bookPose(-dt, P, flips);
out.book = {
  flips: flips.length, forward: flips.filter((x) => x[1] > 0).length, back: flips.filter((x) => x[1] < 0).length,
  first: flips[0][0], last: flips[flips.length - 1][0], worstPsi, worstLift, missing,
  join: Math.max(...start.pages.map((p, i) => Math.max(Math.abs(p.psi - end.pages[i].psi), Math.abs(p.lift - end.pages[i].lift))),
    Math.abs(start.bob - end.bob), Math.abs(start.yaw - end.yaw), Math.abs(start.open - end.open)),
};

// the tank
const aq = spec.layers.find((L) => L.type === 'aquarium');
const map = tankMap(aq.tank);
const px = (s) => map.at(s.u, s.v, s.w);
out.fish = fishSwims(aq.fish ?? 5, P, seed, aq.tank.surface ?? 0.9).map(({ f }) => {
  let worstMove = 0, worstTurn = 0, lo = [9, 9, 9], hi = [-9, -9, -9], minClear = 9;
  let a = fishAt(f, 0, map);
  for (let k = 1; k <= P * 30; k++) {
    const b = fishAt(f, k * dt, map);
    const [x0, y0] = px(a), [x1, y1] = px(b);
    worstMove = Math.max(worstMove, Math.hypot(x1 - x0, y1 - y0));
    const dot = a.head[0] * b.head[0] + a.head[1] * b.head[1] + a.head[2] * b.head[2];
    worstTurn = Math.max(worstTurn, Math.acos(Math.min(1, Math.max(-1, dot))));
    [b.u, b.v, b.w].forEach((v, i) => { lo[i] = Math.min(lo[i], v); hi[i] = Math.max(hi[i], v); });
    minClear = Math.min(minClear, b.v - map.floor(b.u));
    a = b;
  }
  const e = fishAt(f, P - dt, map), s = fishAt(f, -dt, map);
  return { worstMove, worstTurn, lo, hi, minClear, join: Math.hypot(...px(e).slice(0, 2).map((v, i) => v - px(s)[i])) };
});
const plan = axolotlPlan(aq.axolotl.spots, P, map, seed);
{
  let worstMove = 0, worstTurn = 0, swimming = 0, a = plan(0);
  for (let k = 1; k < P * 30; k++) {
    const b = plan(k * dt);
    const [x0, y0] = px(a), [x1, y1] = px(b);
    worstMove = Math.max(worstMove, Math.hypot(x1 - x0, y1 - y0));
    const dot = a.head[0] * b.head[0] + a.head[1] * b.head[1] + a.head[2] * b.head[2];
    worstTurn = Math.max(worstTurn, Math.acos(Math.min(1, Math.max(-1, dot))));
    if (b.swim > 0.5) swimming++;
    a = b;
  }
  const e = plan(P - dt), s = plan(0);
  out.axolotl = { worstMove, worstTurn, swimming: swimming / (P * 30),
    join: Math.hypot(px(e)[0] - px(s)[0], px(e)[1] - px(s)[1]),
    joinTurn: Math.acos(Math.min(1, e.head[0] * s.head[0] + e.head[1] * s.head[1] + e.head[2] * s.head[2])) };
}

// the ghast: one pass at 30 fps, and the timeline's passes over 10 h
const G = spec.events.ghast;
const tl = buildTimeline({ loop: { period: P }, ghast: G }, { seed, duration: 36000, fps: 30, loopSeconds: P });
const passes = tl.events.filter((e) => e.type === 'ghast');
const ev = passes[0];
const frames = [];
for (let f = 0; f <= ev.dur * 30; f++) {
  const tau = f / 30, s = ghastAt(ev, tau);
  frames.push({ tau, x: s.x, y: s.y, speed: s.speed, look: s.look, yaw: s.yaw, vis: s.vis });
}
out.ghast = { ev, frames, passes: passes.map((e) => ({ t: e.t, dur: e.dur, x0: e.x0, x1: e.x1, hold: e.hold, at: e.at })) };
fs.writeFileSync(process.argv[3], JSON.stringify(out));
