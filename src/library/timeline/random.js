// Seeded random streams, string hashing and the small helpers the timeline modules share.

// The project's one RNG and string hash (engine/rng.js). The timeline's own copies gave the same numbers for every
// seed it passes (a uint32) and every string (tests/test_js_helpers.py).
export { mulberry32, hashString as hashStr } from '../../engine/rng.js';

export const r3 = (v) => Math.round(v * 1000) / 1000;

export { smooth } from '../util.js';

// Deterministic rate calibration: gen(k) builds a schedule whose spacing scales with k (same random draws
// for every k); bisect k so the schedule has `target` items (or as close as possible). Poisson-like streams
// over a few hours otherwise land +-30% off their configured rate for some seeds.
export function calibrated(gen, target) {
  let lo = 0.2, hi = 5, best = gen(1);
  if (best.length === target || target <= 0) return best;
  for (let i = 0; i < 28; i++) {
    const k = Math.sqrt(lo * hi), s = gen(k);
    if (Math.abs(s.length - target) < Math.abs(best.length - target)) best = s;
    if (s.length === target) return s;
    if (s.length > target) lo = k; else hi = k;
  }
  return best;
}
