// Lightning: strikes come in loose clusters (a storm cell passing) at a configured average rate. Each
// strike is 1-3 return strokes merged into one soft envelope (rise 0.1 s, decay ~0.3 s, plus a slow
// cloud afterglow), so the screen never flashes more than once or twice per second (WCAG 2.3.1 allows
// 3). Thunder follows by `delay` seconds = distance / speed of sound; farther strikes are dimmer and
// quieter.

import { mulberry32, hashStr, r3, smooth, calibrated } from './random.js';

export const SPEED_OF_SOUND = 343;

function strike(r, L, t, id) {
  const U = (a, b) => a + (b - a) * r();
  const [d0, d1] = L.delay ?? [2, 6];
  const delay = U(d0, d1);
  const near = 1 - (delay - d0) / Math.max(d1 - d0, 1e-6); // 1 = closest
  const power = (0.5 + 0.5 * near) * U(0.85, 1.1) * (L.brightness ?? 1);
  const strokes = [[0, 1]];
  if (r() < 0.6) strokes.push([r3(U(0.12, 0.2)), r3(U(0.4, 0.65))]);
  if (strokes.length > 1 && r() < 0.35) strokes.push([r3(strokes[1][0] + U(0.14, 0.24)), r3(U(0.2, 0.4))]);
  return {
    type: 'lightning', id, t: r3(t), frame: null,
    x: r3(U(0.26, 0.74)), y: r3(U(0.04, 0.2)),          // glow center in the sky (image coords, y down)
    power: r3(power), strokes,
    thunder: {
      t: r3(t + delay), delay: r3(delay), distance_m: Math.round(delay * SPEED_OF_SOUND),
      gain: r3(0.55 + 0.45 * near), seed: Math.floor(r() * 2147483647),
    },
  };
}

// Storm strikes (spec.lightning, see buildTimeline) for this seed and video length, in time order.
export function lightningStrikes(L, seed, duration) {
  const events = [];
  if (L && (L.perHour ?? 0) > 0) {
    const [cMin, cMax] = L.cluster ?? [1, 3];
    const within = L.withinCluster ?? [80, 300];
    const minGap = L.minGap ?? 120;
    const mCluster = (cMin + cMax) / 2;
    const meanWithin = (within[0] + within[1]) / 2;
    // Mean spacing of cluster starts so the long-run rate is perHour strikes per hour.
    const cycle = (3600 * mCluster) / L.perHour;
    const idle = Math.max(cycle - (mCluster - 1) * meanWithin - minGap, 30);
    const end = duration - (L.endBefore ?? 45);
    const maxIdle = L.maxGap ?? 4200;
    const gen = (k) => {
      const r = mulberry32((Math.imul(seed, 2654435761) ^ hashStr('lightning')) >>> 0);
      const U = (a, b) => a + (b - a) * r();
      // Gamma(2)-distributed quiet spells (less clumpy than exponential), capped so no long silences.
      const quiet = () => Math.min((-Math.log(1 - r()) - Math.log(1 - r())) * 0.5 * idle * k, maxIdle);
      const out = [];
      // L.first: the first storm cell comes within this many seconds of startAfter (strong openings); without
      // it the draw order is unchanged, so existing timelines stay identical
      let t = (L.startAfter ?? 240) + (L.first != null ? Math.min(L.first, U(0, 0.5) * idle * k) : U(0, 0.5) * idle * k);
      while (t < end) {
        const n = cMin + Math.floor(r() * (cMax - cMin + 1));
        for (let i = 0; i < n && t < end; i++) {
          out.push(strike(r, L, t, out.length));
          if (i < n - 1) t += U(within[0], within[1]);
        }
        t += minGap + quiet();
      }
      return out;
    };
    // Hit the configured rate for this seed and length (a 10 h video at "6/h" really has ~60 strikes).
    events.push(...calibrated(gen, Math.round((L.perHour * (end - (L.startAfter ?? 240))) / 3600)));
  }
  return events;
}

const RISE = 0.1, DECAY = 0.3, GLOW_RISE = 0.2, GLOW_DECAY = 0.9, GLOW = 0.25, SPAN = 4.5;

// Flash envelope of one strike at dt seconds after it starts (0 before), peak ~1 * power.
export function strikeEnvelope(ev, dt) {
  if (dt < 0 || dt > SPAN) return 0;
  let v = 0;
  for (const [o, a] of ev.strokes) {
    const u = dt - o;
    if (u > 0) v += a * smooth(u / RISE) * Math.exp(-Math.max(u - RISE, 0) / DECAY);
  }
  v += GLOW * smooth(dt / GLOW_RISE) * Math.exp(-Math.max(dt - GLOW_RISE, 0) / GLOW_DECAY);
  return v * ev.power;
}

// Lightning light at time t: { flash, x, y } for the storm strikes (x, y = glow center of the dominant strike,
// image coords; read by every layer), plus { far, fx, fy } for distant flashes (plate.js: the cloud bank only).
export function flashAt(tl, t) {
  const ev = tl?.events;
  if (!ev?.length) return { flash: 0, x: 0.5, y: 0.1, far: 0, fx: 0.5, fy: 0.2 };
  let lo = 0, hi = ev.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (ev[m].t <= t) lo = m + 1; else hi = m; } // first event after t
  let flash = 0, best = 0, x = 0.5, y = 0.1, far = 0, fbest = 0, fx = 0.5, fy = 0.2;
  for (let i = lo - 1; i >= 0 && t - ev[i].t <= SPAN; i--) {
    const e = ev[i];
    if (e.type === 'lightning') {
      const v = strikeEnvelope(e, t - e.t);
      flash += v;
      if (v > best) { best = v; x = e.x; y = e.y; }
    } else if (e.type === 'farflash') {
      const v = strikeEnvelope(e, t - e.t);
      far += v;
      if (v > fbest) { fbest = v; fx = e.x; fy = e.y; }
    }
  }
  return { flash, x, y, far, fx, fy };
}
