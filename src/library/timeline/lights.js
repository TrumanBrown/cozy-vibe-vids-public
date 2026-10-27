// Lights: region dips (neon, candle gutter), the night schedule of switchable windows, lantern guttering and window
// presence, and the per-light levels the plate reads.

import { mulberry32, hashStr, r3, smooth } from './random.js';

// Brightness dip (0..1) of a named region at time t from its neon / gutter events (cosine-shaped dips).
export function regionDip(tl, name, t) {
  if (!tl?.events) return 0;
  if (!tl._regionEv) Object.defineProperty(tl, '_regionEv', { value: tl.events.filter((e) => e.region && e.dips), enumerable: false });
  let d = 0;
  for (const ev of tl._regionEv) {
    if (ev.region !== name || t < ev.t || t > ev.t + ev.dur) continue;
    for (const [c, w, depth] of ev.dips) {
      const u = (t - ev.t - c) / w;
      if (Math.abs(u) < 1) d = Math.max(d, depth * 0.5 * (1 + Math.cos(Math.PI * u)));
    }
  }
  return d;
}

// Night lights: each switchable window goes dark once in the late hours; some stay on all night, some
// come back on for a few minutes (someone up late). [{id, off: [[tOff, tOn | null], ...]}]
export function lightSchedule(L, seed, duration, ids) {
  const r = mulberry32((Math.imul(seed, 3266489917) ^ hashStr('nightlights')) >>> 0);
  const from = L.offFrom ?? 0.55 * duration, to = L.offTo ?? 0.97 * duration;
  return ids.map((id) => {
    const u = r(), v = r(), w = r(), x = r(), y = r();
    if (u < (L.stayOn ?? 0.25)) return { id, off: [] };
    const tOff = from + (to - from) * Math.pow(v, 0.85);
    const iv = [[r3(tOff), null]];
    if (w < (L.revisit ?? 0.15)) {
      const t1 = tOff + 600 + 2400 * x, t2 = t1 + 180 + 600 * y;
      if (t2 < duration - 60) { iv[0][1] = r3(t1); iv.push([r3(t2), null]); }
    }
    return { id, off: iv };
  });
}

// Level (1 = on) of a scheduled light at time t; fades over `fade` s (distant lights switch softly).
export function lightLevel(entry, t, fade = 0.6) {
  let lv = 1;
  for (const [a, b] of entry.off) {
    const down = smooth((t - a) / fade), up = b === null ? 0 : smooth((t - b) / fade);
    lv = Math.min(lv, 1 - down * (1 - up));
  }
  return lv;
}

// Lantern guttering: 2-3 soft dips within the event (never more than 2 per second), depth 0.25-0.6.
// The dips ([center s, half-width s, depth]) are stored on the event, so the audio guttering matches.
export function lanternDips(ev) {
  const r = mulberry32(ev.seed >>> 0);
  const n = 2 + Math.floor(r() * 2);
  const out = [];
  for (let i = 0; i < n; i++) {
    const c = (i + 0.5 + 0.6 * (r() - 0.5)) * ev.dur / n, w = 0.22 + 0.2 * r(), depth = 0.25 + 0.35 * r();
    out.push([r3(c), r3(w), r3(depth)]);
  }
  return out;
}
export function lanternDip(ev, dt) {
  if (dt < 0 || dt > ev.dur) return 0;
  let d = 0;
  for (const [c, w, depth] of ev.dips ?? lanternDips(ev)) {
    const u = (dt - c) / w;
    if (Math.abs(u) < 1) d = Math.max(d, depth * 0.5 * (1 + Math.cos(Math.PI * u)));
  }
  return d;
}

// Per-light levels at time t for ids 0..n-1 (0 = unused): night schedule x window presence x lantern dips.
export function lightLevels(tl, t, n = 64) {
  const out = new Float32Array(n).fill(1);
  for (const e of tl?.lights ?? []) if (e.id < n) out[e.id] = lightLevel(e, t);
  const ws = tl?.windows;
  if (ws?.length) {
    let lo = 0, hi = ws.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (ws[m].t <= t) lo = m + 1; else hi = m; }
    for (let i = lo - 1; i >= 0 && t - ws[i].t <= WINDOW_MAX_DUR; i--) {
      const w = ws[i];
      if (w.id < n) out[w.id] = Math.min(out[w.id], 1 - windowDip(w, t));
    }
  }
  for (const ev of tl?.events ?? []) {
    if (ev.type !== 'lantern' || ev.light >= n) continue;
    if (t >= ev.t && t <= ev.t + ev.dur) out[ev.light] = Math.min(out[ev.light], 1 - lanternDip(ev, t - ev.t));
  }
  return out;
}

// Window presence (people moving about in the distant houses, all evening):
//   pass  someone walks past the window: a soft dip and back over 1.6-3.2 s
//   dim   a lamp turned down or a curtain drawn for 25-90 s (slow 2 s fades)
//   away  the room's light goes out for 2-7 min, then on again (0.7 s soft switch, like the night schedule)
// Only windows that are on (night schedule) for the whole event; one change at a time, `minGap` s apart.
const WINDOW_MAX_DUR = 430;
export function windowSchedule(Wd, seed, duration, ids, lights) {
  if (!ids.length) return [];
  const r = mulberry32((Math.imul(seed, 2654435789) ^ hashStr('windows')) >>> 0);
  const U = (a, b) => a + (b - a) * r();
  // depth = how far the light drops (1 = fully off); passes and dims are kept clearly visible on distant panes.
  const kinds = { pass: [Wd.pass ?? 4, [1.6, 3.2], [0.6, 0.85]], dim: [Wd.dim ?? 2, [25, 90], [0.45, 0.7]], away: [Wd.away ?? 1.5, [120, 420], [1, 1]] };
  const cands = [];
  for (const [kind, [perHour, [d0, d1], [p0, p1]]] of Object.entries(kinds)) {
    if (!(perHour > 0)) continue;
    const rate = perHour / 3600;
    let t = 60 - Math.log(1 - r()) / rate;
    while (t < duration - 30) {
      cands.push({ kind, t: r3(t), dur: r3(U(d0, d1)), depth: r3(U(p0, p1)), pick: r() });
      t += -Math.log(1 - r()) / rate;
    }
  }
  cands.sort((a, b) => a.t - b.t);
  const night = Object.fromEntries(lights.map((l) => [l.id, l]));
  const on = (id, a, b) => !night[id] || (lightLevel(night[id], a) > 0.99 && lightLevel(night[id], b) > 0.99);
  const out = [], busyUntil = {};
  let last = -1e9;
  for (const c of cands) {
    if (c.t - last < (Wd.minGap ?? 45)) continue;
    const free = ids.filter((id) => (busyUntil[id] ?? -1) < c.t && on(id, c.t - 1, c.t + c.dur + 1));
    if (!free.length) continue;
    const id = free[Math.floor(c.pick * free.length)];
    out.push({ id, kind: c.kind, t: c.t, dur: c.dur, depth: c.depth });
    busyUntil[id] = c.t + c.dur + 60;
    last = c.t;
  }
  return out;
}
export function windowDip(w, t) {
  const u = t - w.t;
  if (u < 0 || u > w.dur) return 0;
  if (w.kind === 'pass') return w.depth * Math.sin((Math.PI * u) / w.dur) ** 2;
  const ramp = w.kind === 'away' ? 0.7 : 2.0;
  return w.depth * Math.min(smooth(u / ramp), smooth((w.dur - u) / ramp));
}
