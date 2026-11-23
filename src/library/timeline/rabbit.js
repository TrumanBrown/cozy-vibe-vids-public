// A rabbit visiting the floor (rabbit3d.js draws it): it comes in from out of sight in bursts of short hops, stops to
// sniff and look about between bursts, sits a while at a spot or two (washing its face, sitting up on its hind legs to
// look around, turning its head, sniffing the floor) and hops away out of sight. It never goes in a straight line, as
// the frog never does (user 2026-10-27, L166): every hop's heading wanders off the straight way to the next spot, and a
// turn of more than ~55 degrees is a little turning hop of its own. The floor is the frog's (timeline/frog.js:
// floorScale, floorStep, floorTo), with the rabbit's body length as `size`.
//
// spec (scene.json events.rabbit): the frog's keys (perHour or rest, dur, first, startAfter, endBefore, horizon, size,
//   sizeY, focal, enter, exit, spots, spotsPer, avoid, minY, sit, fill) and burst: [2, 5] hops between longer stops,
//   hopLen: [0.7, 1.3] body lengths a hop, acts: [2, 4] acts in a sit, actGap: [4, 10] s between them.
// An event: { type: 'rabbit', t, dur, seed, hops: [[t0, dur, x0, y0, x1, y1, h0, h1, height, turn, dist], ...] (as the
//   frog's, plus the hop's floor distance in body lengths: rabbit3d.js keeps its planted paws still with it),
//   acts: [[t0, dur, kind, side], ...] (kind: groom | up | look | sniff; side +1 or -1, which way a look turns) }
import { r3, mulberry32, hashStr } from './random.js';
import { floorScale, floorStep, floorTo } from './frog.js';

const W = 3840, H = 2160;
const r1 = (v) => Math.round(v * 10) / 10, r2 = (v) => Math.round(v * 100) / 100;
const wrap = (a) => ((((a + 180) % 360) + 360) % 360) - 180;
const ACT_DUR = { groom: [3.5, 6], up: [2.5, 4.5], look: [2.2, 4], sniff: [2, 3.5] };

// Whether a rabbit at image point p is wholly out of the frame: past a side by more than its half length, or below the
// bottom by more than its height with its ears up (about 1.15 body lengths seen from the camera). Once it is, it hops
// no more (the frog's last little hop raised its eyes back over the frame's bottom, 2026-10-27).
export function outOfSight(F, p) {
  const { s } = floorScale(F, p[1]);
  return p[0] * W < -0.65 * s || (p[0] - 1) * W > 0.65 * s || (p[1] - 1) * H > 1.15 * s;
}

const inBox = (p, b) => p[0] > b[0] && p[0] < b[2] && p[1] > b[1] && p[1] < b[3];

// One visit, drawn from r (the stream's generator), fitted into durMax seconds.
export function planRabbit(F, r, durMax) {
  const U = (a, b) => a + (b - a) * r();
  const N = (sd) => (r() + r() + r() - 1.5) * 2 * sd;
  const pick = (a) => a[Math.floor(r() * a.length) % a.length];
  const enter = pick(F.enter), exit = pick(F.exit);
  const pool = [...(F.spots ?? [])];
  const [n0, n1] = F.spotsPer ?? [1, 2];
  const route = [];
  for (let n = Math.min(pool.length, Math.floor(U(n0, n1 + 0.999))); n > 0; n--) route.push(pool.splice(Math.floor(r() * pool.length) % pool.length, 1)[0]);
  const segs = [];               // { hop } | { wait, act } | { sit, acts }
  let pos = [...enter], head = floorTo(F, enter, route[0] ?? exit).h;
  const ok = (p, out) => out || (!(F.avoid ?? []).some((b) => inBox(p, b)) && p[1] >= (F.minY ?? 0));
  const [l0, l1] = F.hopLen ?? [0.7, 1.3];
  const hop = (d, h1, turn, out) => {
    let to = floorStep(F, pos, d, h1);
    for (let k = 0; !ok(to, out) && k < 3; k++) {
      if (!k) h1 = head + wob();
      to = floorStep(F, pos, d * (1 - 0.3 * k), h1);
    }
    if (!ok(to, out)) return false;
    const dist = floorTo(F, pos, to).d;
    const dur = turn ? U(0.28, 0.34) : U(0.34, 0.42) + 0.04 * dist;
    const height = turn ? U(0.06, 0.1) : U(0.12, 0.2) + 0.04 * dist;
    segs.push({ hop: [dur, pos[0], pos[1], to[0], to[1], head, h1, height, turn ? 1 : 0, dist] });
    pos = to;
    head = h1;
    return true;
  };
  const wob = () => (r() < 0.5 ? -1 : 1) * U(3, 9);
  const vary = (h1) => (Math.abs(wrap(h1 - head)) < 4 ? head + (wrap(h1 - head) < 0 ? -1 : 1) * U(4, 10) : h1);
  // a stop between bursts: mostly a sniff and a look about, now and then sitting up on its hind legs
  const stop = () => {
    const long = r() < 0.25;
    const w = long ? U(4, 8) : U(1.2, 3.5);
    const q = r();
    const kind = q < 0.35 ? 'look' : q < 0.55 && long ? 'up' : q < 0.75 ? 'sniff' : null;
    const act = kind ? { kind, dur: Math.min(U(...ACT_DUR[kind]), w - 0.5), side: r() < 0.5 ? -1 : 1 } : null;
    segs.push({ wait: w, act: act && act.dur > 1.2 ? act : null });
  };
  const [b0, b1] = F.burst ?? [2, 5];
  // out of sight as the plan stores it (rounded): judged on the unrounded point, a rabbit a hair inside the margin hopped
  // once more from a start the stored plan has out of sight
  const gone = () => outOfSight(F, [r3(pos[0]), r3(pos[1])]);
  const goTo = (target, out) => {
    let n = 0, burst = Math.floor(U(b0, b1 + 0.999));
    for (let guard = 0; guard < 60; guard++) {
      if (out && gone()) return;
      const { d, h } = floorTo(F, pos, target);
      if (d < (out ? 0.3 : 0.6)) return;
      const dh = wrap(h - head);
      let moved;
      if (Math.abs(dh) > 55 && d > 1.0) {
        moved = hop(U(0.15, 0.35), head + Math.sign(dh) * Math.min(Math.abs(dh), U(40, 75)) + N(6), true, out);
      } else {
        const raw = d > 2.5 ? N(20) : N(8);
        const jit = Math.abs(raw) > 35 ? Math.sign(raw) * U(22, 35) : raw;
        moved = hop(Math.min(d, U(l0, l1)), vary(h + jit), false, out) || hop(Math.min(d, U(l0 * 0.8, l1 * 0.8)), vary(h - jit), false, out);
      }
      if (!moved) moved = hop(Math.min(d, l0), vary(h + wob()), false, out);
      if (!moved) return;
      if (out && gone()) return;
      if (++n >= burst) {
        stop();
        n = 0;
        burst = Math.floor(U(b0, b1 + 0.999));
      } else {
        segs.push({ wait: U(0.1, 0.45) });
      }
    }
  };
  const sitR = F.sit ?? [30, 60], [a0, a1] = F.acts ?? [2, 4], ag = F.actGap ?? [4, 10];
  for (const spot of route) {
    goTo(spot, false);
    // it settles side-on or three-quarters to the camera (a rabbit reads best in profile): a turning hop or two
    const face = (r() < 0.5 ? -1 : 1) * U(40, 80) + N(6);
    for (let k = 0; k < 2 && Math.abs(wrap(face - head)) > 35; k++) {
      const dh = wrap(face - head);
      hop(U(0.1, 0.25), head + Math.sign(dh) * Math.min(Math.abs(dh), U(60, 95)), true, false);
      segs.push({ wait: U(0.4, 1.2) });
    }
    const acts = [];
    const n = Math.floor(U(a0, a1 + 0.999));
    for (let i = 0; i < n; i++) {
      const q = r();
      const kind = q < 0.35 ? 'groom' : q < 0.55 ? 'up' : q < 0.8 ? 'look' : 'sniff';
      acts.push({ after: i ? U(...ag) : U(2, 5), kind, dur: U(...ACT_DUR[kind]), side: r() < 0.5 ? -1 : 1 });
    }
    segs.push({ sit: U(...sitR), acts });
  }
  goTo(exit, true);
  // fit: the sits shrink (never under 12 s) until the visit fits its slot; with `fill` they also grow to fill it
  const busy = segs.reduce((a, s) => a + (s.hop ? s.hop[0] : s.wait ?? 0), 0);
  const sits = segs.filter((s) => s.sit);
  const want = sits.reduce((a, s) => a + s.sit, 0);
  const k = sits.length && (F.fill || busy + want > durMax) ? Math.max(12 * sits.length, durMax - busy) / want : 1;
  const hops = [], acts = [];
  let t = 0;
  for (const s of segs) {
    if (s.hop) {
      const [d, x0, y0, x1, y1, h0, h1, hg, turn, dist] = s.hop;
      hops.push([r3(t), r3(d), r3(x0), r3(y0), r3(x1), r3(y1), r1(h0), r1(h1), r2(hg), turn, r2(dist)]);
      t += d;
    } else if (s.wait != null) {
      if (s.act) acts.push([r3(t + 0.25), r3(s.act.dur), s.act.kind, s.act.side]);
      t += s.wait;
    } else {
      const len = s.sit * k;
      // each act follows the one before; one that would run into the sit's last 1.5 s is left out
      let at = 0;
      for (const a of s.acts) {
        at += a.after;
        if (at + a.dur > len - 1.5) break;
        acts.push([r3(t + at), r3(a.dur), a.kind, a.side]);
        at += a.dur;
      }
      t += len;
    }
  }
  return { hops, acts, dur: r3(t + 0.5), enter: [r3(enter[0]), r3(enter[1])], h0: r1(hops[0]?.[6] ?? 90) };
}

// The timeline stream (ambient.js): one visit at a time; with `rest` the visits are a chain (as the frog's, L173: a
// creature he likes on screen most of the video, and each loop period opens with it hopping in).
export function rabbits({ spec, seed, duration, out, stream }) {
  const Fg = spec?.rabbit;
  if (!(Fg?.perHour || Fg?.rest) || !Fg.enter?.length || !Fg.exit?.length) return;
  const [d0, d1] = Fg.dur ?? [90, 180];
  if (Fg.rest) {
    const r = mulberry32((Math.imul(seed, 1103515245) ^ hashStr('rabbit')) >>> 0);
    const U = (a, b) => a + (b - a) * r();
    const end = duration - (Fg.endBefore ?? 30);
    for (let t = (Fg.startAfter ?? 2) + U(0, Fg.first ?? 4); ;) {
      const plan = planRabbit(Fg, r, U(d0, d1));
      if (t + plan.dur > end) break;
      out.push({ type: 'rabbit', t: r3(t), seed: Math.floor(r() * 2147483647), ...plan });
      t += plan.dur + U(...Fg.rest);
    }
    return;
  }
  stream('rabbit', { minGap: d1 + 60, ...Fg }, (r, t) => {
    const plan = planRabbit(Fg, r, d0 + (d1 - d0) * r());
    return { type: 'rabbit', t: r3(t), seed: Math.floor(r() * 2147483647), ...plan };
  });
}
