// Spike checks. Usage:
//   node spikes/shared/check.mjs hashes a.json b.json        -> identical-frame report on common frames
//   node spikes/shared/check.mjs seam <stillsDir> <last>     -> MSE(last-1,last) vs MSE(last,0) (seam step vs normal step)
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const [cmd, ...args] = process.argv.slice(2);

function mse(a, b) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-i', a, '-i', b, '-lavfi', 'psnr', '-f', 'null', '-'], { encoding: 'utf8' });
  const m = /PSNR .*average:(inf|[\d.]+)/.exec(r.stderr);
  if (!m) throw new Error(`psnr failed for ${a} vs ${b}: ${r.stderr.slice(-400)}`);
  return m[1] === 'inf' ? 0 : +((255 * 255) / 10 ** (Number(m[1]) / 10)).toFixed(3);
}

if (cmd === 'hashes') {
  const [a, b] = args.map((f) => JSON.parse(fs.readFileSync(f, 'utf8')));
  const common = Object.keys(a).filter((k) => k in b);
  const diff = common.filter((k) => a[k] !== b[k]);
  console.log(JSON.stringify({ common: common.length, identical: common.length - diff.length, differing: diff.slice(0, 20) }));
  process.exitCode = diff.length || !common.length ? 1 : 0;
} else if (cmd === 'seam') {
  const [dir, last] = [args[0], Number(args[1])];
  const f = (n) => path.join(dir, `frame_${String(n).padStart(5, '0')}.png`);
  const normal = mse(f(last - 1), f(last));
  const seam = mse(f(last), f(0));
  console.log(JSON.stringify({ normalStepMse: normal, seamStepMse: seam, ratio: +(seam / normal).toFixed(3) }));
} else {
  console.error('unknown command');
  process.exitCode = 2;
}
