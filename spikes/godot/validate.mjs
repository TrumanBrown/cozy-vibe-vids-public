// Godot spike driver + validation (10 s render, determinism, random access, loop wrap, seam).
// Usage: node spikes/godot/validate.mjs [outDir] [--only-render] [extra godot user args...]
// Finds Godot via $GODOT or the winget install folder.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function findGodot() {
  if (process.env.GODOT) return process.env.GODOT;
  const pk = path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), 'AppData', 'Local'), 'Microsoft', 'WinGet', 'Packages');
  const dir = fs.existsSync(pk) && fs.readdirSync(pk).find((d) => d.startsWith('GodotEngine.GodotEngine_'));
  const exe = dir && fs.readdirSync(path.join(pk, dir)).find((f) => /^Godot_v4.*_console\.exe$/.test(f));
  if (!exe) throw new Error('Godot not found; set GODOT to the Godot 4 executable');
  return path.join(pk, dir, exe);
}
function findFfmpeg() {
  const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', ['ffmpeg'], { encoding: 'utf8' });
  return r.stdout.split(/\r?\n/)[0].trim() || 'ffmpeg';
}

const godot = findGodot();
const ffmpeg = findFfmpeg();
const argv = process.argv.slice(2);
const out = path.resolve(argv[0] && !argv[0].startsWith('--') ? argv.shift() : path.join('out', 'phase0', 'godot'));
const onlyRender = argv.includes('--only-render');
const extra = argv.filter((x) => x !== '--only-render');
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

export function render(args) {
  const r = spawnSync(godot, ['--path', here, '--', '--ffmpeg', ffmpeg, ...extra, ...args], { encoding: 'utf8', maxBuffer: 64 << 20, timeout: 600_000 });
  const line = r.stdout.split(/\r?\n/).find((l) => l.startsWith('{'));
  if (!line) throw new Error(`godot failed (${r.status}):\n${r.stdout.slice(-3000)}\n${r.stderr.slice(-3000)}`);
  const errs = (r.stderr + r.stdout).split(/\r?\n/).filter((l) => /ERROR|SCRIPT ERROR/.test(l));
  if (errs.length) console.error(errs.slice(0, 10).join('\n'));
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
report.render10s = render(['--count', '300', '--out', path.join(out, 'godot_10s.mp4'), '--hash', path.join(out, 'hash_a.json'),
  '--stills', '0,45,100,135,180,240,298,299', '--stills-dir', out]);
console.log(JSON.stringify(report.render10s));
if (!onlyRender) {
  report.renderNoEncode = render(['--count', '300', '--hash', path.join(out, 'hash_b.json')]);
  render(['--start', '150', '--count', '30', '--hash', path.join(out, 'hash_c.json')]);
  render(['--start', '290', '--count', '20', '--hash', path.join(out, 'hash_d.json')]);
  const A = load('hash_a.json');
  report.determinism = compare(A, load('hash_b.json'));
  report.randomAccess = compare(A, load('hash_c.json'));
  const D = load('hash_d.json');
  report.loopWrap = compare(A, Object.fromEntries(Object.entries(D).filter(([k]) => Number(k) >= 300)), (k) => String(Number(k) - 300));
  report.seam = { normalStepMse: mse(still(298), still(299)), seamStepMse: mse(still(299), still(0)) };
  report.seam.ratio = +(report.seam.seamStepMse / report.seam.normalStepMse).toFixed(3);
}
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1));
