// The picture's side of the formulas tools/audio.py follows (TASKS.md T14), evaluated at the times given, for
// tests/test_parity.py:
//   node tests/js_parity.mjs <scene dir> <timeline.json> <times.json> <out.json>
// It takes the scene the way the renderer does (weather.wind, weather.runoff, loopSeconds) and the timeline's weather
// track and gust flurries, and writes {"scene": {...}, "wind": [...], "flow": [[...] per stream], "flurry_wind": [...],
// "flurry_env": [...]}:
//   wind         |windAt at 0.45 of the width, gust times the track's wind| / (|mean| + gust), as audio.py gust()
//   flow         rain.js flowAt at the loop time times the track's stream strength, clamped as the shader does
//   flurry_wind  timeline.js flurryWind (m/s); audio.py's flurry_env is its |value| / 2, capped at 1
//   flurry_env   timeline.js flurryEnv, the vines' sway (plate.js): the same definition since 2026-10-27
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [sceneDir, tlPath, timesPath, outPath] = process.argv.slice(2);
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { windAt, trackAt, flurryWind, flurryEnv } = await imp('src/library/timeline.js');
const { flowAt, runoffParams } = await imp('src/library/rain.js');
const { default: S } = await import(pathToFileURL(path.resolve(sceneDir, 'scene.js')).href);
const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
const times = JSON.parse(fs.readFileSync(timesPath, 'utf8'));

const L = S.loopSeconds ?? 60;
const wind = { ...S.weather.wind, loop: L };
const norm = Math.abs(wind.mean) + wind.gust;
const streams = runoffParams(S.weather.runoff ?? [], L);
const out = {
  scene: { loopSeconds: L, wind: S.weather.wind, runoff: streams },
  wind: times.map((t) => Math.abs(windAt(wind, t, 0.45, trackAt(tl.track, 'wind', t))) / norm),
  flow: streams.map((s) => times.map((t) => Math.min(Math.max(flowAt(t % L, s.flow, s.burst, s.burstCycles, s.seedf, L) * trackAt(tl.track, 'streams', t), 0.04), 1))),
  flurry_wind: times.map((t) => flurryWind(tl, t)),
  flurry_env: times.map((t) => flurryEnv(tl, t)),
};
fs.writeFileSync(outPath, JSON.stringify(out));
