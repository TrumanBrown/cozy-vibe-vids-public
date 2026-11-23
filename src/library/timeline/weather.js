// The slow weather track (rain, runoff streams, wind) and its interpolation.

import { mulberry32, hashStr, r3 } from './random.js';

// Slow weather evolution (docs/GOALS.md "rain intensity drifts"), sampled every dt seconds:
//   rain     drop rate multiplier (video density, audio grain rate/level)
//   streams  roof-runoff flow multiplier (rain, delayed ~90 s as water builds up on the roof)
//   wind     gust strength multiplier
// Smooth seeded noise (7 and 25 min scales) plus storm swells around each lightning strike, so heavier
// rain and gustier wind arrive with the thunder. Swells are relative to their long-run mean (rain is a
// little lighter between storms), so frequent storms don't raise the average rain or loudness. Video and
// audio interpolate the same samples.
export function weatherTrack(spec = {}, seed = 1, duration = 36000, events = [], period = 0) {
  const dt = spec.dt ?? 5;
  const n = Math.ceil(duration / dt) + 1;
  const r = mulberry32((Math.imul(seed, 2246822519) ^ hashStr('weather')) >>> 0);
  // period (a looped video, loopTimeline): every knot spacing rounded so the period holds whole cycles, the knots
  // wrap, the storm swells wrap, and the stream lag runs a period ahead, so the track repeats exactly
  const knots = (span, amp) => {
    if (period) {
      const m = Math.max(1, Math.round(period / span)), sp = period / m;
      const k = Array.from({ length: m }, () => (r() * 2 - 1) * amp);
      const at = (i) => k[((i % m) + m) % m];
      return (t) => { const x = t / sp, i = Math.floor(x), f = x - i, s = f * f * (3 - 2 * f); return at(i) + (at(i + 1) - at(i)) * s; };
    }
    const k = Array.from({ length: Math.ceil(duration / span) + 3 }, () => (r() * 2 - 1) * amp);
    return (t) => { const x = t / span, i = Math.floor(x), f = x - i, s = f * f * (3 - 2 * f); return k[i] + (k[i + 1] - k[i]) * s; };
  };
  const [rA, wA] = [spec.rainAmp ?? 1, spec.windAmp ?? 1];
  const rainSlow = knots(1500, 0.11 * rA), rainMid = knots(420, 0.06 * rA);
  const windSlow = knots(900, 0.18 * wA), windMid = knots(300, 0.1 * wA);
  const strikes = events.filter((e) => e.type === 'lightning').flatMap((e) => (period ? [e.t - period, e.t, e.t + period] : [e.t]));
  const W = spec.stormHalfWidth ?? 600;
  const storm = (t) => {
    let b = 0;
    for (const s of strikes) { const u = Math.abs(t - s) / W; if (u < 1) b = Math.max(b, 0.5 + 0.5 * Math.cos(Math.PI * u)); }
    return b;
  };
  const st = Array.from({ length: n }, (_, i) => storm(i * dt));
  const mst = spec.stormRelative === false ? 0 : st.reduce((a, b) => a + b, 0) / n;
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const rain = [], wind = [], streams = [];
  const lag = Math.exp(-dt / (spec.streamLag ?? 90));
  const rainAt = (i) => clamp(1 + rainSlow(i * dt) + rainMid(i * dt) + (spec.stormRain ?? 0.22) * (st[i % n] - mst), 0.7, 1.35);
  let s = null;
  if (period) for (let i = 0; i < n - 1; i++) { const rv = rainAt(i); s = s === null ? rv : rv + (s - rv) * lag; }
  for (let i = 0; i < n; i++) {
    const t = i * dt, sw = st[i] - mst;
    const rv = rainAt(i);
    s = s === null ? rv : rv + (s - rv) * lag;
    rain.push(r3(rv));
    streams.push(r3(s));
    wind.push(r3(clamp(1 + windSlow(t) + windMid(t) + (spec.stormWind ?? 0.35) * sw, 0.5, 1.7)));
  }
  return { dt, rain, streams, wind };
}

// Linear interpolation of a track channel at time t (same as the shaders' linear texture filtering
// and tools/audio.py's np.interp).
export function trackAt(track, key, t) {
  const a = track?.[key];
  if (!a?.length) return 1;
  const x = Math.min(Math.max(t / track.dt, 0), a.length - 1);
  const i = Math.min(Math.floor(x), a.length - 2), f = x - i;
  return a[i] + (a[i + 1] - a[i]) * f;
}
