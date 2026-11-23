// Runs the three.js spike validation: 10 s render (+stills), determinism, random access, loop seam.
// Usage: node spikes/three/validate.mjs [outDir]
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const electron = path.join(here, 'node_modules', 'electron', 'dist', process.platform === 'win32' ? 'electron.exe' : 'electron');
const out = path.resolve(process.argv[2] ?? path.join('out', 'phase0', 'three'));
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

function render(args) {
  const r = spawnSync(electron, [path.join(here, 'electron-main.cjs'), ...args], { encoding: 'utf8' });
  const line = r.stdout.split('\n').find((l) => l.startsWith('{'));
  if (r.status !== 0 || !line) throw new Error(`render failed (${r.status}): ${r.stdout}\n${r.stderr.slice(-2000)}`);
  return JSON.parse(line);
}
const load = (f) => JSON.parse(fs.readFileSync(path.join(out, f), 'utf8'));
function compare(a, b, map = (k) => k) {
  const keys = Object.keys(b);
  const bad = keys.filter((k) => a[map(k)] !== b[k]);
  return { compared: keys.length, identical: keys.length - bad.length, differing: bad.slice(0, 10) };
}
function mse(fa, fb) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-i', fa, '-i', fb, '-lavfi', 'psnr', '-f', 'null', '-'], { encoding: 'utf8' });
  const m = /PSNR .*average:(inf|[\d.]+)/.exec(r.stderr);
  return m[1] === 'inf' ? 0 : +((255 * 255) / 10 ** (Number(m[1]) / 10)).toFixed(3);
}
const still = (n) => path.join(out, `frame_${String(n).padStart(5, '0')}.png`);

const report = {};
report.render10s = render(['--count', '300', '--out', path.join(out, 'three_10s.mp4'), '--hash', path.join(out, 'hash_a.json'),
  '--stills', '0,45,100,135,180,240,298,299', '--stillsDir', out]);
render(['--count', '300', '--hash', path.join(out, 'hash_b.json')]);
render(['--start', '150', '--count', '30', '--hash', path.join(out, 'hash_c.json')]);
render(['--start', '290', '--count', '20', '--hash', path.join(out, 'hash_d.json')]);
const A = load('hash_a.json');
report.determinism = compare(A, load('hash_b.json'));
report.randomAccess = compare(A, load('hash_c.json'));
const D = load('hash_d.json');
report.loopWrap = compare(A, Object.fromEntries(Object.entries(D).filter(([k]) => Number(k) >= 300)), (k) => String(Number(k) - 300));
report.seam = { normalStepMse: mse(still(298), still(299)), seamStepMse: mse(still(299), still(0)) };
report.seam.ratio = +(report.seam.seamStepMse / report.seam.normalStepMse).toFixed(3);
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1));
