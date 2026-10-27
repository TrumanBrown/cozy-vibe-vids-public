// The types src/ knows, for tests/test_types.py (TASKS.md T14):
//   node tests/js_types.mjs <out.json>
// writes {"layers": [autoscene.js LAYERS keys], "scenes": {"<scene>": {"events": [...], "pet": [...]}},
// "can_emit": [...]}: the event and pet-motion types in each scene's timeline (built as `node src/cli.mjs timeline`
// builds it), and every type a timeline gives when its spec switches on every generator.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { LAYERS } = await imp('src/library/autoscene.js');
const { buildTimeline } = await imp('src/library/timeline.js');
const typesOf = (tl) => ({ events: [...new Set(tl.events.map((e) => e.type))].sort(), pet: [...new Set((tl.pet ?? []).map((e) => e.type))].sort() });
const out = { layers: Object.keys(LAYERS), scenes: {} };

for (const name of fs.readdirSync(path.join(root, 'scenes')).sort()) {
  const file = path.join(root, 'scenes', name, 'scene.js');
  if (!fs.existsSync(file)) continue;
  const { default: S } = await import(pathToFileURL(file).href);
  const pj = S.plate ? path.join(root, 'out', 'plates', S.plate, 'plate.json') : null;
  const plate = pj && fs.existsSync(pj) ? JSON.parse(fs.readFileSync(pj, 'utf8')) : null;
  const warn = console.warn;
  console.warn = () => {};
  const tl = buildTimeline(S.events ?? {}, { seed: S.seed ?? 1, duration: S.duration ?? 36000, fps: S.fps ?? 30, plate, loopSeconds: S.loopSeconds ?? 60 });
  console.warn = warn;
  out.scenes[name] = typesOf(tl);
}

// Every generator at once: storms, spotlight events (a boat on a route, then boats as traffic), every ambient stream
// and the pet's three motions, over a plate with lanterns, windows, neon and candles.
const plate = {
  light_groups: [{ id: 1, kind: 'lantern', x: 0.3 }, { id: 2, kind: 'window', size_px: 40 }],
  regions: [{ name: 'sign', kind: 'neon' }, { name: 'candle', kind: 'candle' }],
};
const every = {
  lightning: { perHour: 6 }, lantern: { perHour: 2 }, heron: { perHour: 1 }, train: { perHour: 2 },
  fish: { perHour: 20, zones: [[0.1, 0.6, 0.4, 0.8]] }, flurry: { perHour: 6 }, farflash: { perHour: 12 }, neon: { perHour: 10 },
  gutter: { perHour: 8 }, car: { perHour: 30 }, ember: { perHour: 12 }, star: { perHour: 4 }, birds: { perHour: 10 },
  critter: [{ perHour: 3 }], ant: { perHour: 6 }, perch: { perHour: 6, slots: [3] }, moth: { perHour: 5 },
  petAct: { perHour: 3, acts: [{ name: 'stretch' }] }, pet: { ear: 4, tail: 3, sigh: 5, thunderEar: 0.7 },
  lights: {}, windows: { pass: 5 },
};
const can = new Set();
for (const boat of [{ perHour: 2 }, { ambient: true }]) {
  const t = typesOf(buildTimeline({ ...every, boat }, { seed: 3, duration: 36000, fps: 30, plate, loopSeconds: 120 }));
  for (const x of [...t.events, ...t.pet]) can.add(x);
}
out.can_emit = [...can].sort();
fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
