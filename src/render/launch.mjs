// The one way to start the Electron renderer (src/render/electron-main.cjs): the CLI's still, preview and guides
// commands and the render pipeline both come here. It collects what Electron prints, with Chromium's own noise on
// stderr (GPU process, disk cache) left out, and reports an Electron that isn't installed plainly. Whether a run
// failed is the caller's to say: { code, out, err } comes back for every run that started.
//   echo        print stdout and the kept stderr as they come (the CLI)
//   onProgress  (i, n, fps) for each "progress i/n f fps" line the page prints (the pipeline condenses them)
import path from 'node:path';
import { spawn } from 'node:child_process';

const NOISE = /GPU|disk_cache|persistent_cache|gpu_disk/;

export function launchElectron(root, args, { echo = false, onProgress = null } = {}) {
  const exe = path.join(root, 'node_modules', 'electron', 'dist', process.platform === 'win32' ? 'electron.exe' : 'electron');
  return new Promise((resolve, reject) => {
    const p = spawn(exe, [path.join(root, 'src', 'render', 'electron-main.cjs'), ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    p.on('error', (e) => reject(new Error(e.code === 'ENOENT' ? `Electron isn't installed (${exe}): run npm install` : `could not start Electron: ${e.message}`)));
    p.stdout.on('data', (d) => {
      const s = d.toString();
      if (echo) process.stdout.write(s);
      out += s;
      if (onProgress) for (const m of s.matchAll(/progress (\d+)\/(\d+) ([\d.]+) fps/g)) onProgress(Number(m[1]), Number(m[2]), Number(m[3]));
    });
    p.stderr.on('data', (d) => {
      const s = d.toString();
      if (NOISE.test(s)) return;
      if (echo) process.stderr.write(s);
      err += s;
    });
    p.on('close', (code) => resolve({ code, out, err }));
  });
}
