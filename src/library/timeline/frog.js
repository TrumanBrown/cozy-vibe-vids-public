// A frog visiting the floor (frog3d.js draws it; tools/cozy/audio reads the croaks): it comes in from out of sight,
// crosses to a spot or two in short hops with pauses, now and then a little turning hop, sits there a while and
// croaks, and hops away out of sight. Frogs never glide or go in a straight line (user 2026-10-27, the jungle
// temple's sprite frog): every hop's heading wanders off the straight way to the next spot, and a turn of more than
// ~55 degrees is a hop of its own.
//
// The floor is seen at a low angle (the spec: horizon, the image row of the eye line; size, the frog's body length in
// px at row sizeY; focal, px). One body length on the floor is floorScale(y).s px across the image there and that
// times sin(view angle) up or down it.
//
// spec (scene.json events.frog): { perHour, dur: [min, max] s, first, startAfter, horizon (0.68), size (120),
//   sizeY (0.9), focal (2700), enter: [[x, y], ...] and exit: [[x, y], ...] (image coords, out of sight: past the
//   frame's edge), spots: [[x, y], ...] (where it may sit), spotsPer: [1, 2], avoid: [[x0, y0, x1, y1], ...] (boxes a
//   hop never lands in: the pet, a step), minY (the floor's far edge: no landing above it), sit: [30, 60] s at a spot,
//   series: [1, 2] series of croaks in a sit, croakGap: [8, 20] s between them, fill (the sits grow to fill `dur`),
//   rest: [min, max] s (visits as a chain with rests between them instead of a rate; see frogs) }
// Visits must not overlap (frog3d.js draws one frog): at a rate, the stream's spacing (minGap, at most 0.8 of
// 3600 / perHour) has to be longer than the longest visit; a chain can't overlap. review.py checks the timeline.
// An event: { type: 'frog', t, dur, seed, hops: [[t0, dur, x0, y0, x1, y1, h0, h1, height, turn], ...] (s from t, image
//   coords, headings in degrees: 0 faces the camera, 90 screen right; height in body lengths; turn 1 for a small
//   turning hop), croaks: [s, ...] }
import { r3, mulberry32, hashStr } from './random.js';

const W = 3840, H = 2160;
const r1 = (v) => Math.round(v * 10) / 10, r2 = (v) => Math.round(v * 100) / 100;
const wrap = (a) => ((((a + 180) % 360) + 360) % 360) - 180;

// The frog's body length (px) and the view angle down onto the floor (rad) at image row y.
export function floorScale(F, y) {
  const hz = F.horizon ?? 0.68, y0 = F.sizeY ?? 0.9;
  const s = (F.size ?? 120) * Math.max(0.05, (y - hz) / (y0 - hz));
  const el = Math.atan((Math.max(0.01, y - hz) * H) / (F.focal ?? 2700));
  return { s, el };
}

// The image point d body lengths from p along heading h (deg), in four steps (the scale changes down the floor).
export function floorStep(F, p, d, h) {
  let px = p[0] * W, py = p[1] * H;
  const a = (h * Math.PI) / 180;
  for (let i = 0; i < 4; i++) {
    const { s, el } = floorScale(F, py / H);
    px += (d / 4) * Math.sin(a) * s;
    py += (d / 4) * Math.cos(a) * s * Math.sin(el);
  }
  return [px / W, py / H];
}

// Floor distance (body lengths) and heading (deg) from image point a to b.
export function floorTo(F, a, b) {
  const { s, el } = floorScale(F, (a[1] + b[1]) / 2);
  const fx = ((b[0] - a[0]) * W) / s, fz = ((b[1] - a[1]) * H) / (s * Math.sin(el));
  return { d: Math.hypot(fx, fz), h: (Math.atan2(fx, fz) * 180) / Math.PI };
}

// Whether a frog sitting at image point p is wholly out of the frame: past a side by more than its half length (0.6 of
// a body length from its middle, the toes included), or below the bottom by more than its height (its eyes are about
// 0.65 of a body length up). Once it is, it hops no more: on its way out a last little hop raised its eyes back over
// the frame's bottom edge for a moment (the jungle temple's 10 h window, 2026-10-27).
export function outOfSight(F, p) {
  const { s } = floorScale(F, p[1]);
  return p[0] * W < -0.6 * s || (p[0] - 1) * W > 0.6 * s || (p[1] - 1) * H > 0.75 * s;
}

const inBox = (p, b) => p[0] > b[0] && p[0] < b[2] && p[1] > b[1] && p[1] < b[3];

// One visit, drawn from r (the stream's generator): hops, pauses, sits and croaks, fitted into durMax seconds.
export function planFrog(F, r, durMax) {
  const U = (a, b) => a + (b - a) * r();
  const N = (sd) => (r() + r() + r() - 1.5) * 2 * sd;      // about normal, sd
  const pick = (a) => a[Math.floor(r() * a.length) % a.length];
  const enter = pick(F.enter), exit = pick(F.exit);
  const pool = [...(F.spots ?? [])];
  const [n0, n1] = F.spotsPer ?? [1, 2];
  const route = [];
  for (let n = Math.min(pool.length, Math.floor(U(n0, n1 + 0.999))); n > 0; n--) route.push(pool.splice(Math.floor(r() * pool.length) % pool.length, 1)[0]);
  const segs = [];               // { hop } | { wait } | { sit, croaks }
  let pos = [...enter], head = floorTo(F, enter, route[0] ?? exit).h;
  const ok = (p, out) => out || (!(F.avoid ?? []).some((b) => inBox(p, b)) && p[1] >= (F.minY ?? 0));
  const hop = (d, h1, turn, out) => {
    let to = floorStep(F, pos, d, h1);
    // a landing on the pet or past the floor's edge: on along its own heading instead, then shorter; the hop is recorded
    // with the heading it really takes (it faces where it goes)
    for (let k = 0; !ok(to, out) && k < 3; k++) {
      if (!k) h1 = head + wob();
      to = floorStep(F, pos, d * (1 - 0.3 * k), h1);
    }
    if (!ok(to, out)) return false;
    const dur = turn ? U(0.3, 0.36) : U(0.36, 0.44) + 0.02 * d;
    const height = turn ? U(0.15, 0.26) : U(0.3, 0.48) + 0.05 * d;
    segs.push({ hop: [dur, pos[0], pos[1], to[0], to[1], head, h1, height, turn ? 1 : 0] });
    pos = to;
    head = h1;
    return true;
  };
  // a few degrees either way: even a hop straight at its target is never quite on the last one's line
  const wob = () => (r() < 0.5 ? -1 : 1) * U(3, 9);
  // and a hop never keeps the last one's heading: two jitter draws alike made three hops in a row on one line
  const vary = (h1) => (Math.abs(wrap(h1 - head)) < 4 ? head + (wrap(h1 - head) < 0 ? -1 : 1) * U(4, 10) : h1);
  const goTo = (target, out) => {
    for (let guard = 0; guard < 40; guard++) {
      // on its way out: gone once it is out of sight (another hop could raise it back into view)
      if (out && outOfSight(F, pos)) return;
      const { d, h } = floorTo(F, pos, target);
      if (d < (out ? 0.3 : 0.8)) return;
      const dh = wrap(h - head);
      let moved;
      if (Math.abs(dh) > 55 && d > 1.2) {
        moved = hop(U(0.25, 0.55), head + Math.sign(dh) * Math.min(Math.abs(dh), U(40, 75)) + N(6), true, out);
      } else {
        // its heading wanders off the straight way; past 35 degrees a fresh draw (clamped, two far-off draws in a row
        // made the same heading twice: a straight run)
        const raw = d > 3 ? N(20) : N(8);
        const jit = Math.abs(raw) > 35 ? Math.sign(raw) * U(22, 35) : raw;
        // blocked one way (the floor's far edge, the pet): the other way round
        moved = hop(Math.min(d, U(1.4, 3.0)), vary(h + jit), false, out) || hop(Math.min(d, U(1.2, 2.2)), vary(h - jit), false, out);
      }
      if (!moved) moved = hop(Math.min(d, 1.2), vary(h + wob()), false, out);
      if (!moved) return;
      if (out && outOfSight(F, pos)) return;
      // mostly a short pause, now and then a long still look about
      segs.push({ wait: r() < 0.22 ? U(3.5, 8) : U(0.5, 2.6) });
    }
  };
  // the sits: how long (s), and how many series of croaks in each (the first sit of a visit always croaks); `croakGap`:
  // the seconds between series in a sit
  const sitR = F.sit ?? [30, 60], [c0, c1] = F.series ?? [1, 2], cg = F.croakGap ?? [8, 20];
  let firstSit = true;
  for (const spot of route) {
    goTo(spot, false);
    // it settles facing roughly the camera's way: a turning hop (two for a big turn) when it faces well away
    const face = N(25);
    for (let k = 0; k < 2 && Math.abs(wrap(face - head)) > 40; k++) {
      const dh = wrap(face - head);
      hop(U(0.2, 0.4), head + Math.sign(dh) * Math.min(Math.abs(dh), U(70, 100)), true, false);
      segs.push({ wait: U(0.6, 1.5) });
    }
    // one or two series of croaks, a few seconds into the sit and well apart
    const series = [];
    let n = Math.floor(U(c0, c1 + 0.999));
    if (firstSit && n < 1) n = 1;
    for (let s = 0; s < n; s++) series.push({ after: s ? U(...cg) : U(3, 8), k: Math.floor(U(2, 4.999)), gap: U(0.8, 1.1) });
    segs.push({ sit: U(...sitR), series });
    firstSit = false;
  }
  goTo(exit, true);
  // fit: the sits shrink (never under 12 s) until the visit fits its slot; with `fill` they also grow to fill it, so a
  // visit lasts about its slot (the jungle temple's frog, on screen most of the video: L173)
  const busy = segs.reduce((a, s) => a + (s.hop ? s.hop[0] : s.wait ?? 0), 0);
  const sits = segs.filter((s) => s.sit);
  const want = sits.reduce((a, s) => a + s.sit, 0);
  const k = sits.length && (F.fill || busy + want > durMax) ? Math.max(12 * sits.length, durMax - busy) / want : 1;
  const hops = [], croaks = [];
  let t = 0;
  for (const s of segs) {
    if (s.hop) {
      const [d, x0, y0, x1, y1, h0, h1, hg, turn] = s.hop;
      hops.push([r3(t), r3(d), r3(x0), r3(y0), r3(x1), r3(y1), r1(h0), r1(h1), r2(hg), turn]);
      t += d;
    } else if (s.wait) {
      t += s.wait;
    } else {
      const len = s.sit * k;
      // each series follows the one before; a series that would run into the sit's last 2 s is left out
      let at = 0;
      for (const sr of s.series) {
        at += sr.after;
        if (at + sr.k * sr.gap > len - 2) break;
        for (let i = 0; i < sr.k; i++) croaks.push(r3(t + at + i * sr.gap));
        at += sr.k * sr.gap;
      }
      t += len;
    }
  }
  return { hops, croaks: croaks.sort((a, b) => a - b), dur: r3(t + 0.5), enter: [r3(enter[0]), r3(enter[1])], h0: r1(hops[0]?.[6] ?? 90) };
}

// The timeline stream (ambient.js): one visit at a time, the first `first` s into the video. With `rest` ([min, max] s)
// the visits are a chain instead of a rate: a visit, a rest, the next visit, until the next would end past the video's
// end less `endBefore` (30). For a frog on screen most of the time (the jungle temple: L173): a rate's spacing is capped
// at 0.8 of its mean, which made long visits overlap or spill past a loop period's end, and the seam repair then dropped
// the opening visit; a chain never spills, so each period opens with the frog hopping in.
export function frogs({ spec, seed, duration, out, stream }) {
  const Fg = spec?.frog;
  if (!(Fg?.perHour || Fg?.rest) || !Fg.enter?.length || !Fg.exit?.length) return;
  const [d0, d1] = Fg.dur ?? [90, 180];
  if (Fg.rest) {
    const r = mulberry32((Math.imul(seed, 1103515245) ^ hashStr('frog')) >>> 0);
    const U = (a, b) => a + (b - a) * r();
    const end = duration - (Fg.endBefore ?? 30);
    for (let t = (Fg.startAfter ?? 2) + U(0, Fg.first ?? 4); ;) {
      const plan = planFrog(Fg, r, U(d0, d1));
      if (t + plan.dur > end) break;
      out.push({ type: 'frog', t: r3(t), seed: Math.floor(r() * 2147483647), ...plan });
      t += plan.dur + U(...Fg.rest);
    }
    return;
  }
  stream('frog', { minGap: d1 + 60, ...Fg }, (r, t) => {
    const plan = planFrog(Fg, r, d0 + (d1 - d0) * r());
    return { type: 'frog', t: r3(t), seed: Math.floor(r() * 2147483647), ...plan };
  });
}
