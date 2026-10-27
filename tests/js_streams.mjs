// Every ambient event stream with every option, through buildTimeline, for tests/test_streams.py: no scene uses all of
// them (the shooting star, pet acts, birds and a boat already out at the start, a reversed prevailing gust, a single
// critter spec), so the scene goldens can't vouch for them.
//   node tests/js_streams.mjs <out.json>   -> {"<spec>/<seed>": {"sha256": ..., "types": {type: count}}}
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { buildTimeline } = await import(pathToFileURL(path.join(root, 'src', 'library', 'timeline.js')).href);

const route = { camera: { focalPx: 2700, horizon: 0.453, height: 16 }, path: [[0.468, 0.523], [0.443, 0.553], [0.4, 0.585], [0.348, 0.611], [0.315, 0.648], [0.302, 0.703]], fade: [30, 6] };
const regions = [{ name: 'sign', kind: 'neon' }, { name: 'sign2', kind: 'neon' }, { name: 'candle', kind: 'candle' }, { name: 'lamp', kind: 'lamp' }, { name: 'fire', kind: 'fire' }];
const SPECS = {
  // the spotlight boat, a list of critters, ants in file, every option of the busy opening
  a: {
    lightning: { perHour: 6, cluster: [1, 4], withinCluster: [50, 180], minGap: 90, maxGap: 1800, startAfter: 150, endBefore: 45, delay: [2, 6] },
    farflash: { perHour: 24, minGap: 35, startAfter: 60, delay: [3, 5], power: [0.45, 0.85], x: [0.2, 0.62], y: [0.12, 0.25], clear: 20 },
    boat: { perHour: 4, dur: [110, 150], startAfter: 300, cooldown: 480, route },
    fish: { perHour: 20, minGap: 60, jump: 0.7, zones: [[0.3, 0.597, 0.38, 0.624, 1.4], [0.38, 0.556, 0.5, 0.592, 2], [0.5, 0.566, 0.555, 0.584, 0.7]] },
    flurry: { perHour: 3, minGap: 420, dur: [5, 8], amp: [1, 2.4], leaves: [4, 9], prevailing: 1, intro: [600, 2] },
    neon: { perHour: 30, minGap: 45, startAfter: 10, first: 20, intro: [300, 2] },
    gutter: { perHour: 12, minGap: 300, startAfter: 30, depth: 0.55, first: 60 },
    car: { perHour: 70, minGap: 14, dur: [6, 10], startAfter: 3, rightward: 0.7, headlights: 0.4 },
    ember: { perHour: 14, minGap: 90, startAfter: 8 },
    star: { perHour: 8, minGap: 60, startAfter: 20, box: [0.15, 0.05, 0.85, 0.3] },
    birds: { perHour: 80, minGap: 14, startAfter: 4, band: [0.47, 0.1, 0.76, 0.3], size: [20, 46], count: [1, 6], first: 6, intro: [300, 1.5], cross: [0.4, 0.8], flap: [3.5, 5], speed: [7, 10] },
    critter: [{ perHour: 10, dur: [51, 68], startAfter: 4, first: 6, forward: 0.7 }, { perHour: 10, dur: [95, 130], startAfter: 12, first: 20 }],
    ant: { perHour: 20, dur: [16, 28], paths: 3, startAfter: 5, first: 25, intro: [300, 3], file: 0.45 },
    perch: { perHour: 20, slots: [5, 3], group: [1, 4], stay: [90, 420], together: 0.35, atStart: 3, startAfter: 4, first: 10, intro: [300, 2], comeBack: 0.9, calm: 30 },
    moth: { perHour: 24, dur: [45, 140], lands: 2, startAfter: 15, first: 30, intro: [300, 1.5] },
    petAct: { perHour: 4, minGap: 300, startAfter: 60, acts: [{ name: 'stretch', weight: 2, dur: 8, hold: [2, 6] }, { name: 'yawn', weight: 1, dur: 5 }] },
  },
  // boats as traffic already out at the start, one critter spec, a gust from the other side, named neon regions
  b: {
    lightning: { perHour: 10, cluster: [2, 4], withinCluster: [50, 120], minGap: 60, maxGap: 900, startAfter: 60, endBefore: 45, delay: [1, 4] },
    boat: { ambient: true, dur: [130, 170], startAfter: 2, first: 4, idle: [10, 45], atStart: true, route },
    flurry: { perHour: 5, minGap: 300, amp: [1.5, 2.5], prevailing: -1 },
    neon: { perHour: 20, regions: ['sign2'], depth: 0.6 },
    gutter: { perHour: 8, regions: ['lamp'] },
    critter: { perHour: 6, dur: [200, 300], startAfter: 30 },
    ant: { perHour: 12, dur: [14, 26] },
    perch: { perHour: 30, slots: [2], atStart: 2, stay: [60, 200] },
    birds: { perHour: 40 },
    star: { perHour: 5 },
    moth: { perHour: 10, lands: 3 },
    petAct: { perHour: 6, acts: [{ name: 'sigh', dur: 4 }] },
  },
};

const out = {};
for (const [name, spec] of Object.entries(SPECS)) {
  for (const seed of [1, 7]) {
    const tl = buildTimeline(spec, { seed, duration: 36000, fps: 30, plate: { regions }, loopSeconds: 60 });
    const types = {};
    for (const e of tl.events) types[e.type] = (types[e.type] ?? 0) + 1;
    out[`${name}/${seed}`] = { sha256: crypto.createHash('sha256').update(JSON.stringify(tl)).digest('hex').slice(0, 16), types };
  }
}
fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
