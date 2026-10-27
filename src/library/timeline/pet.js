// The pet's schedule of micro-motions and its pose at a time.

import { mulberry32, hashStr, r3, smooth } from './random.js';

// Pet micro-motions (subtle, frequent; not "rare events"): a slower, deeper sigh breath, and for a pet that may move
// (Treetop's, published 2026-10-16, sets its own rates) ear flicks (also ~0.6 s after near thunder, the cat hears it)
// and tail-tip twitches. Min gap between pet events. A painted pet only breathes (AGENTS.md, 2026-10-18), so ear,
// tail and thunderEar default to 0: a scene.json that leaves them out gets sighs only (TASKS.md T7).
// spec: { ear: perHour, tail: perHour, sigh: perHour, thunderEar: probability, minGap: s }
export function petSchedule(P, seed, duration, events) {
  const r = mulberry32((Math.imul(seed, 668265263) ^ hashStr('pet')) >>> 0);
  const U = (a, b) => a + (b - a) * r();
  const cands = [];
  const kinds = { ear: [0.6, 0.9], tail: [1.0, 1.5], sigh: [4.0, 5.5] };
  for (const [type, perHour] of Object.entries({ ear: P.ear ?? 0, tail: P.tail ?? 0, sigh: P.sigh ?? 3 })) {
    const rate = perHour / 3600;
    // P.first (s): the first of each kind within that long (strong openings); without it the draws are unchanged
    let t = P.first != null ? (() => { const u = -Math.log(1 - r()) / rate; return Math.min(P.first + 0.25 * u, 60 + u); })() : 60 - Math.log(1 - r()) / rate;
    while (t < duration - 10) {
      const e = { type, t: r3(t), dur: r3(U(...kinds[type])), amp: r3(U(0.75, 1.15)), seed: Math.floor(r() * 2147483647) };
      if (type === 'ear') { e.ears = r() < 0.25 ? 2 : 1; e.double = r() < 0.35 ? 1 : 0; }
      cands.push(e);
      t += -Math.log(1 - r()) / rate;
    }
  }
  for (const ev of events) {
    if (ev.type !== 'lightning' || ev.thunder.gain < 0.6) continue;
    if (r() < (P.thunderEar ?? 0)) cands.push({ type: 'ear', t: r3(ev.thunder.t + U(0.35, 0.9)), dur: 0.8, amp: r3(U(1.0, 1.25)), ears: 2, double: 1, react: 1, seed: Math.floor(r() * 2147483647) });
  }
  cands.sort((a, b) => a.t - b.t);
  const out = [];
  const gap = P.minGap ?? 25;
  for (const e of cands) {
    const last = out[out.length - 1];
    if (last && e.t < last.t + last.dur + (e.react ? 1 : gap)) continue;
    out.push(e);
  }
  return out;
}

// Pet pose at time t: ear angles (rad, ears A and B), tail-tip lift (0..1), breath amplitude multiplier.
export function petState(tl, t) {
  const st = { earA: 0, earB: 0, tail: 0, breath: 1 };
  const ev = tl?.pet;
  if (!ev?.length) return st;
  let lo = 0, hi = ev.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= t) lo = m + 1; else hi = m; }
  for (let i = lo - 1; i >= 0 && i >= lo - 3; i--) {
    const e = ev[i], u = t - e.t;
    if (u < 0 || u > e.dur) continue;
    if (e.type === 'ear') {
      // Quick flick back (80 ms), brief hold, ease home; optional second, smaller flick.
      const one = (x) => (x < 0 ? 0 : x < 0.08 ? smooth(x / 0.08) : x < 0.14 ? 1 : 1 - smooth((x - 0.14) / 0.28));
      const a = e.amp * (one(u) + (e.double ? 0.7 * one(u - 0.36) : 0));
      st.earA = Math.max(st.earA, a);
      if (e.ears === 2) st.earB = Math.max(st.earB, 0.8 * one(u - 0.05) * e.amp);
    } else if (e.type === 'tail') {
      const b = (x, w) => (x < 0 || x > w ? 0 : Math.sin(Math.PI * x / w) ** 2);
      st.tail = Math.max(st.tail, e.amp * (b(u, 0.45) + 0.6 * b(u - 0.5, 0.4)));
    } else if (e.type === 'sigh') {
      st.breath = Math.max(st.breath, 1 + 1.3 * e.amp * Math.sin(Math.PI * u / e.dur) ** 2);
    }
  }
  return st;
}
