// The frog's visits for tests/test_frog.py: node tests/js_frog.mjs <out.json>
// Plans 40 visits from the jungle temple's events.frog with fixed seeds, each twice (the same seed must plan the same),
// at slot lengths across its `dur`, and notes every hop after the first that starts out of sight (it would come back).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { planFrog, outOfSight } = await imp('src/library/timeline/frog.js');
const { mulberry32 } = await imp('src/library/timeline/random.js');
const F = JSON.parse(fs.readFileSync(path.join(root, 'scenes', 'jungle-temple-night', 'scene.json'), 'utf8')).events.frog;
const [d0, d1] = F.dur ?? [90, 180];
const visits = [];
for (let seed = 1; seed <= 40; seed++) {
  const durMax = d0 + ((d1 - d0) * (seed % 10)) / 9;
  const a = planFrog(F, mulberry32(seed), durMax), b = planFrog(F, mulberry32(seed), durMax);
  // a hop from out of sight after the frog has been in view: it would come back (on the way in, off-screen hops are fine)
  let seen = false;
  const back = [];
  for (const h of a.hops) {
    if (seen && outOfSight(F, [h[2], h[3]])) back.push(h[0]);
    if (!outOfSight(F, [h[4], h[5]])) seen = true;
  }
  const gone = outOfSight(F, [a.hops[a.hops.length - 1][4], a.hops[a.hops.length - 1][5]]);
  visits.push({ seed, durMax, plan: a, same: JSON.stringify(a) === JSON.stringify(b), back, gone });
}
fs.writeFileSync(process.argv[2], JSON.stringify({ spec: F, visits }, null, 1));
