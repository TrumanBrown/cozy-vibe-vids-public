// The dragon's pass, for tests/test_dragon.py: node tests/js_dragon.mjs <out.json>
// dragon.js's own shape over a pass at 30 fps, and the timeline's dragon events for a 10 h spec.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { dragonShape, dragonWings } = await imp('src/library/dragon.js');
const { buildTimeline } = await imp('src/library/timeline.js');

const ev = { t: 0, dur: 34, x0: 1.04, y0: 0.14, x1: -0.04, y1: 0.11, arc: 0.03, span: 160, seed: 1058635181 };
const frames = [];
for (let f = 0; f <= ev.dur * 30; f++) {
  const tau = f / 30, s = dragonShape(ev, tau);
  const pts = [...s.near, ...s.far, ...s.caps.filter((c) => c[4] > 0).flatMap((c) => [[c[0], c[1]], [c[2], c[3]]])];
  // the drawing box (dragon.js uQuad) less each part's reach
  const reach = Math.max(0, ...pts.map(([x, y]) => Math.max(Math.abs(x - s.x) / (0.75 * s.S), Math.abs(y - s.y) / (0.6 * s.S))));
  frames.push({ tau, flap: dragonWings(ev)(tau).flap, reach, near: s.near, far: s.far, x: s.x, y: s.y });
}
const tl = buildTimeline({ loop: { period: 1200 }, dragon: { perHour: 3, minGap: 600, startAfter: 20, first: 45, dur: [30, 40], span: [140, 175] } },
  { seed: 7, duration: 36000, fps: 30, loopSeconds: 1200 });
const events = tl.events.filter((e) => e.type === 'dragon').map((e) => ({ t: e.t, dur: e.dur, x0: e.x0, x1: e.x1, span: e.span }));
fs.writeFileSync(process.argv[2], JSON.stringify({ frames, events }));
