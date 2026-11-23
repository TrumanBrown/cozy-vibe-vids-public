// Wind: the gust flurries (timeline events) and the steady wind with its gusts, each with its exact drift integral.

// Gust flurry wind (m/s, signed): a raised-cosine gust of amplitude `amp` over [ev.t, ev.t + ev.dur].
// flurryInt is its exact integral from the gust's start (m); rain.js evaluates the same formulas in GLSL
// from flurryUniform, leaves.js drifts leaves with flurryDrift, tools/audio.py follows flurryWind.
export function flurryInt(ev, s) {
  const u = Math.min(Math.max(s, 0), ev.dur);
  return ev.amp * (0.5 * u - (ev.dur / (4 * Math.PI)) * Math.sin((2 * Math.PI * u) / ev.dur));
}
const flurryCache = new WeakMap();
function flurriesOf(tl) {
  if (!tl) return [];
  let f = flurryCache.get(tl);
  if (!f) { f = (tl.events ?? []).filter((e) => e.type === 'flurry'); flurryCache.set(tl, f); }
  return f;
}
export function flurryWind(tl, t) {
  let v = 0;
  for (const e of flurriesOf(tl)) {
    if (e.t > t) break;
    const s = t - e.t;
    if (s < e.dur) v += e.amp * 0.5 * (1 - Math.cos((2 * Math.PI * s) / e.dur));
  }
  return v;
}
export function flurryDrift(tl, t0, t1) {
  let d = 0;
  for (const e of flurriesOf(tl)) {
    if (e.t > t1) break;
    if (e.t + e.dur < t0) continue;
    d += flurryInt(e, t1 - e.t) - flurryInt(e, t0 - e.t);
  }
  return d;
}
// The gust in effect at time t for shaders: [seconds since its start, duration, amplitude] (amp 0 = none).
// Flurries are minutes apart, so only the latest one can still move anything on screen.
export function flurryUniform(tl, t) {
  let last = null;
  for (const e of flurriesOf(tl)) { if (e.t > t) break; last = e; }
  return last && t - last.t < last.dur + 30 ? [t - last.t, last.dur, last.amp] : [0, 1, 0];
}
// Flurry strength envelope at t (0..1): for the vines' sway boost (plate.js) and steam drafts (steam.js). It is the
// sound's definition (audio.py flurry_env): the gust's wind |flurryWind| / 2 m/s, capped at 1, so a stronger gust holds
// the full lean for longer, and what you see moves with what you hear (tests/test_parity.py).
export function flurryEnv(tl, t) {
  return Math.min(Math.abs(flurryWind(tl, t)) / 2, 1);
}

// Wind at absolute time t (m/s) and its exact integral over [t0, t] (m): the same formulas as
// windAt() / the drift integral in rain.js (gust strength scaled by the weather track at t).
export function windAt(w, t, xFrac, gustK = 1) {
  const th = 2 * Math.PI * (w.gustCycles * t / w.loop - w.fronts * xFrac);
  return w.mean + w.gust * gustK * (0.75 * Math.sin(th) + 0.25 * Math.sin(2 * th + 1.3));
}
export function windDrift(w, t0, t1, xFrac, gustK = 1) {
  const m = w.gustCycles, K = w.gust * gustK * w.loop / (2 * Math.PI * m);
  const a0 = 2 * Math.PI * (m * t0 / w.loop - w.fronts * xFrac), a1 = 2 * Math.PI * (m * t1 / w.loop - w.fronts * xFrac);
  return w.mean * (t1 - t0) - K * (0.75 * (Math.cos(a1) - Math.cos(a0)) + 0.125 * (Math.cos(2 * a1 + 1.3) - Math.cos(2 * a0 + 1.3)));
}
