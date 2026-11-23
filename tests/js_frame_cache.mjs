// frameCache (src/library/overlay.js) against the first-in-first-out cache fire.js, pet.js and steam.js each had:
// render frames ask for a few flipbook frames, some asked for before; no frame handed out may be closed before the
// next render frame starts, and frames that fall out are still closed. Prints JSON to stdout.
import { frameCache } from '../src/library/overlay.js';
import { mulberry32 } from '../src/engine/rng.js';

const bitmap = (key, log) => ({ key, closed: false, close() { this.closed = true; log.push(key); } });

function fifo(limit, open) {
  const cache = new Map(), order = [];
  return (key) => {
    if (cache.has(key)) return cache.get(key);
    const p = open(key);
    cache.set(key, p);
    order.push(key);
    while (order.length > limit) {
      const old = order.shift();
      const q = cache.get(old);
      cache.delete(old);
      q?.then((bm) => bm.close?.());
    }
    return p;
  };
}

const flush = () => new Promise((r) => setImmediate(r));

// fire.js's walk over its one kept clip (97 frames): runs from seeded frames for seeded lengths, 0.8 clip frames a
// render frame (24 fps clip, 30 fps video), clamped at the clip's end, each crossfading for 8 render frames into the
// next. A render frame asks for its run's two neighbouring frames, then the next run's two while they cross.
async function walk(make, limit, frames = 50000, seed = 3) {
  const closed = [];
  const get = make(limit, (k) => Promise.resolve(bitmap(k, closed)));
  const r = mulberry32(seed);
  const hi = 96, X = 8;
  const run = (t0) => ({ t0, f0: Math.floor(r() * 60), len: 40 + Math.floor(r() * 50) });
  const at = (u, t) => Math.min(hi, u.f0 + 0.8 * (t - u.t0));
  let cur = run(0), next = null, inUse = 0;
  for (let t = 0; t < frames; t++) {
    if (!next && t >= cur.t0 + cur.len - X) next = run(t);
    if (next && t >= next.t0 + X) { cur = next; next = null; }
    const keys = [];
    for (const u of next ? [cur, next] : [cur]) {
      const i0 = Math.floor(at(u, t));
      keys.push(i0, Math.min(i0 + 1, hi));
    }
    const bms = await Promise.all(keys.map((k) => get(k)));
    await flush();
    inUse += bms.filter((b) => b.closed).length;
  }
  return { frames, in_use_closed: inUse, closed: closed.length };
}

// The case itself: 'a' is the oldest of four when a render frame asks for it again and then for a new frame.
async function oldestReused(make) {
  const log = [];
  const get = make(4, (k) => Promise.resolve(bitmap(k, log)));
  for (const k of ['a', 'b', 'c', 'd']) await get(k);
  const again = await get('a');
  await get('e');
  await flush();
  return { a_closed: again.closed, closed: log };
}

const out = {
  oldest_reused: { lru: await oldestReused(frameCache), fifo: await oldestReused(fifo) },
  walk: { fifo: await walk(fifo, 40), lru: await walk(frameCache, 40), lru_small: await walk(frameCache, 6) },
};
process.stdout.write(JSON.stringify(out));
