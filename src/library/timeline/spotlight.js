// Spotlight events (rareEvents) and the heron's flight.

import { mulberry32, hashStr, r3 } from './random.js';
import { lanternDips } from './lights.js';

// Spotlight events (docs/GOALS.md "rare"): boat, heron, lantern gutter. Rates per hour, one at a time
// (`rareGap` s apart), clear of each lightning strike, no back-to-back repeats (a per-type cooldown).
// Candidates are oversampled Poisson per type; a greedy pass in time order accepts those that fit, with a
// rate credit so each type converges to its perHour rate instead of bunching.
export function rareEvents(spec, seed, duration, busy0, groups) {
  const r = mulberry32((Math.imul(seed, 2246822519) ^ hashStr('rare')) >>> 0);
  const U = (a, b) => a + (b - a) * r();
  const types = [];
  const lant = groups.filter((g) => g.kind === 'lantern');
  if (spec?.lantern && lant.length) types.push({ type: 'lantern', cooldown: 1200, ...spec.lantern });
  if (spec?.boat && !spec.boat.ambient) types.push({ type: 'boat', cooldown: 1800, ...spec.boat });
  if (spec?.heron) types.push({ type: 'heron', cooldown: 2700, ...spec.heron });
  if (spec?.train) types.push({ type: 'train', cooldown: 900, dur: [14, 22], ...spec.train });
  const byType = Object.fromEntries(types.map((T) => [T.type, T]));
  const cands = [];
  for (const T of types) {
    const rate = (T.perHour ?? 1) * (T.oversample ?? 8) / 3600;
    let t = (T.startAfter ?? 300) - Math.log(1 - r()) / rate;
    while (t < duration - 180) {
      const [d0, d1] = T.dur ?? [3, 4];
      const e = { type: T.type, t: r3(t), dur: r3(U(d0, d1)), seed: Math.floor(r() * 2147483647) };
      if (T.type === 'lantern') { const g = lant[Math.floor(r() * lant.length)]; e.light = g.id; e.x = g.x; }
      if (T.type === 'boat') { e.dir = r() < 0.5 ? 1 : -1; e.lane = r3(r()); }
      if (T.type === 'heron') Object.assign(e, heronFlight(T, r));
      if (T.type === 'train') { e.dir = r() < 0.5 ? 1 : -1; e.cars = 4 + Math.floor(r() * 5); e.lit = r3(U(0.6, 0.9)); }
      if (e.t + e.dur < duration - 30) cands.push(e);
      t += -Math.log(1 - r()) / rate;
    }
  }
  cands.sort((a, b) => a.t - b.t);
  const busy = busy0.slice();
  const out = [];
  const gap = spec?.rareGap ?? 120;
  const lastEnd = {}, count = {};
  const r2 = mulberry32((Math.imul(seed, 1597334677) ^ hashStr('rare-dir')) >>> 0);
  let lastDir = 0;
  for (const e of cands) {
    const T = byType[e.type];
    const credit = (T.perHour ?? 1) * (e.t - (T.startAfter ?? 300)) / 3600 + 1;
    if ((count[e.type] ?? 0) >= credit) continue;
    if (lastEnd[e.type] !== undefined && e.t - lastEnd[e.type] < T.cooldown) continue;
    const a = e.t - gap, b = e.t + e.dur + gap;
    if (busy.some(([x, y]) => a < y && b > x)) continue;
    if (e.type === 'boat') {   // boats mostly alternate direction (out and back), so it never looks scripted
      if (lastDir && r2() < 0.75) e.dir = -lastDir;
      lastDir = e.dir;
    }
    if (e.type === 'lantern') e.dips = lanternDips(e);
    busy.push([e.t, e.t + e.dur]);
    out.push(e);
    lastEnd[e.type] = e.t + e.dur;
    count[e.type] = (count[e.type] ?? 0) + 1;
  }
  return out;
}

// A heron crossing the valley: distance from the camera (m), altitude above the water (m), airspeed
// (m/s), direction (+1 = to the right), a gentle climb/sink over the crossing, wingbeat rate (Hz) and the
// share of time spent gliding. The crossing spans the frame plus a margin (it enters and leaves behind
// the porch frame), so its duration follows from the distance: half width = D * (W/2) / focalPx.
// With `screenY: [y0, y1]` (image rows, 0..1) and `camera: { horizon, height }` (boat.js lakeCamera) the
// altitude is chosen so the bird crosses the frame at that row: a dark silhouette needs a bright band of
// sky or mist behind it (pinhole camera tilted to the horizon row, as in lakeCamera).
function heronFlight(T, r) {
  const U = (a, b) => a + (b - a) * r();
  const F = T.focalPx ?? 2700;
  const D = U(...(T.distance ?? [160, 280]));
  let h = U(...(T.screenY ?? T.altitude ?? [22, 42]));
  if (T.screenY) {
    const { horizon = 0.453, height = 16 } = T.camera ?? {};
    const th = Math.atan((1080 - horizon * 2160) / F), s = Math.sin(th), c = Math.cos(th);
    const a = (1080 - h * 2160) / F;
    h = height + (D * (a * c - s)) / (c + a * s);
  }
  const v = U(...(T.speed ?? [8, 10.5]));
  const halfW = D * 1920 / F + 15;
  return {
    dir: r() < 0.5 ? 1 : -1, dist: r3(D), alt: r3(h), speed: r3(v), dur: r3(2 * halfW / v),
    sink: r3(U(...(T.sink ?? [-4, 3]))), flapHz: r3(U(1.9, 2.4)), glide: r3(U(...(T.glide ?? [0.15, 0.35]))), phase: r3(U(0, 1)),
  };
}
