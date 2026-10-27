// Electron main process: hidden GPU window that renders a scene's frames (stills or video).
// Launched by src/cli.mjs : never start electron.exe directly from a shell (GUI-subsystem binary).
// Args after the script: --scene <dir> --width --height --seed  and either
//   --stills a,b,c --pattern <file with {frame}>   or   --start N --count N --out <file> [--codec] [--hash file]
const { app, BrowserWindow, powerSaveBlocker } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pipeline } = require('node:stream');
const { parseArgs } = require('node:util');

const root = path.resolve(__dirname, '..', '..');
process.on('uncaughtException', (e) => { process.stderr.write(`FATAL ${e.stack ?? e}\n`); app.exit(1); });

const argv = process.argv.slice(process.argv.findIndex((x) => x.endsWith('electron-main.cjs')) + 1);
const { values: a } = parseArgs({
  args: argv,
  strict: false,
  options: {
    scene: { type: 'string' }, width: { type: 'string', default: '3840' }, height: { type: 'string', default: '2160' }, seed: { type: 'string' },
    stills: { type: 'string' }, pattern: { type: 'string' },
    start: { type: 'string', default: '0' }, count: { type: 'string' }, out: { type: 'string' }, codec: { type: 'string', default: 'hevc_nvenc' },
    hash: { type: 'string' }, summary: { type: 'string' }, camera: { type: 'string' }, ssaa: { type: 'string' }, guides: { type: 'string' }, params: { type: 'string' },
    duration: { type: 'string' }, cq: { type: 'string' },
  },
});

app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('force_high_performance_gpu');
app.commandLine.appendSwitch('use-angle', 'd3d11');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
// Per-run profile dir; Electron holds files in it until exit, so stale ones are swept at startup.
{
  const tmp = os.tmpdir();
  for (const d of fs.readdirSync(tmp)) {
    if (!d.startsWith('cvv-electron-')) continue;
    try { fs.rmSync(path.join(tmp, d), { recursive: true, force: true }); } catch { /* in use by a concurrent run */ }
  }
  app.setPath('userData', fs.mkdtempSync(path.join(tmp, 'cvv-electron-')));
}

const mime = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };
// The folders the render page loads from (page.html's import map, page.js, the layers' fetches). Nothing else in the
// repo (.git, config, out/<scene>, marketing/private) is served, even to the page (security review 2026-10-26).
const SERVED = ['src', 'scenes', 'assets', path.join('node_modules', 'three'), path.join('out', 'plates')];
// A bad request or a file that can't be read fails only that request (the page reports it): a throw in here would be
// uncaught and end the whole render.
function serve() {
  const server = http.createServer((req, res) => {
    // only the render's own page: a website that rebinds its name to 127.0.0.1 can't read the repo during a render
    if (req.headers.host !== `127.0.0.1:${server.address().port}`) { res.writeHead(403).end(); return; }
    let p, st;
    try {
      p = path.normalize(path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname)));
    } catch {
      res.writeHead(400).end();
      return;
    }
    // inside the served folders only (a prefix test on the repo would also let ../cozy-vibe-vids-old through)
    const rel = path.relative(root, p);
    const served = SERVED.some((d) => rel.startsWith(d + path.sep));
    if (!served) process.stderr.write(`serve: refused ${req.url} (the page loads only from ${SERVED.join(', ')})\n`);
    try { st = served ? fs.statSync(p) : null; } catch { st = null; }
    if (!st || st.isDirectory()) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'content-type': mime[path.extname(p)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
    pipeline(fs.createReadStream(p), res, (e) => {
      if (e && e.code !== 'ERR_STREAM_PREMATURE_CLOSE') process.stderr.write(`serve ${p}: ${e.message}\n`);
    });
  });
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(server)));
}

// page.js sets window.cvv once its whole import graph has loaded. A module that stops the graph never lets it come, and
// a render used to wait for it forever (an autopilot render stage would sit there all night): end with what page.html
// recorded instead, and give up after START_S in any case. The page starts in about a second.
const START_S = 120;
async function pageStarted(js) {
  const t0 = Date.now();
  for (;;) {
    const s = await js('({ ready: !!window.cvv, errors: window.cvvStartErrors ?? [] })');
    if (s.ready) return;
    if (s.errors.length) throw new Error(`the render page didn't start: ${s.errors.join(' | ')}`);
    if (Date.now() - t0 > START_S * 1000) throw new Error(`the render page didn't start within ${START_S} s and reported no error`);
    await new Promise((r) => setTimeout(r, 20));
  }
}

app.whenReady().then(async () => {
  const log = (s) => process.stdout.write(`${s}\n`);
  try {
    const server = await serve();
    const win = new BrowserWindow({ show: false, width: 1280, height: 720, webPreferences: { nodeIntegration: true, contextIsolation: false, backgroundThrottling: false } });
    // The page has Node, so it never leaves the render: no navigation away and no new windows.
    win.webContents.on('will-navigate', (e) => e.preventDefault());
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    // Every page message reaches the log, tagged with its level (TASKS.md T6): layers say what they draw with
    // console.log and a defect with console.warn, and pipeline.mjs keeps the warnings for the render's QA report.
    win.webContents.on('console-message', (e) => {
      if (e.message.includes('Electron Security Warning')) return;
      log(`${e.level === 'error' ? '[page error]' : e.level === 'warning' ? '[page warning]' : '[page]'} ${e.message}`);
    });
    await win.loadURL(`http://127.0.0.1:${server.address().port}/src/render/page.html`);
    const js = (s) => win.webContents.executeJavaScript(s);
    await pageStarted(js);
    const sceneRel = path.relative(root, path.resolve(a.scene)).split(path.sep).join('/');
    const params = Object.fromEntries((a.params ?? '').split(',').filter(Boolean).map((kv) => { const i = kv.indexOf('='); return i < 0 ? [kv, 'true'] : [kv.slice(0, i), kv.slice(i + 1)]; }));
    const opts = { width: Number(a.width), height: Number(a.height), params, ...(a.seed ? { seed: Number(a.seed) } : {}), ...(a.camera ? { camera: JSON.parse(a.camera) } : {}), ...(a.ssaa ? { ssaa: Number(a.ssaa) } : {}), ...(a.duration ? { duration: Number(a.duration) } : {}) };
    const info = await js(`window.cvv.init(${JSON.stringify(sceneRel)}, ${JSON.stringify(opts)})`);
    log(`renderer: ${info.renderer} | three r${info.three} | seed ${info.seed} | ${info.triangles} tris | ${info.leaves} leaves | ssaa ${info.ssaa}`);
    const sinkPath = path.join(__dirname, 'sink.cjs');
    const t0 = Date.now();
    let summary;
    if (a.guides) {
      fs.mkdirSync(path.dirname(path.resolve(a.guides)), { recursive: true });
      await js(`window.cvv.guides(${Number(a.start)}, ${JSON.stringify(path.resolve(a.guides))})`);
      summary = { mode: 'guides', prefix: a.guides, sec: +((Date.now() - t0) / 1000).toFixed(2) };
    } else if (a.stills) {
      const frames = a.stills.split(',').map(Number);
      const r = await js(`window.cvv.stills(${JSON.stringify(frames)}, ${JSON.stringify({ sinkPath, pattern: path.resolve(a.pattern) })})`);
      summary = { mode: 'stills', frames: r.frames, sec: +((Date.now() - t0) / 1000).toFixed(2) };
    } else {
      const count = Number(a.count);
      // Long renders: keep Windows from suspending the app (sleep) while frames are being produced.
      const blocker = powerSaveBlocker.start('prevent-app-suspension');
      const r = await js(`window.cvv.video(${Number(a.start)}, ${count}, ${JSON.stringify({ sinkPath, out: path.resolve(a.out), codec: a.codec, hash: !!a.hash, progress: true, ...(a.cq ? { cq: Number(a.cq) } : {}) })})`);
      powerSaveBlocker.stop(blocker);
      if (a.hash) fs.writeFileSync(a.hash, JSON.stringify(r.hashes, null, 1));
      const sec = (Date.now() - t0) / 1000;
      summary = { mode: 'video', frames: r.frames, sec: +sec.toFixed(2), fps: +(r.frames / sec).toFixed(2), out: a.out };
    }
    summary.renderer = info.renderer;
    log(JSON.stringify(summary));
    if (a.summary) fs.writeFileSync(a.summary, JSON.stringify(summary));
    server.close();
  } catch (e) {
    // the page can reject with plain objects (e.g. a failed image load's event): show what they hold
    let detail = e?.stack ?? e?.message;
    if (!detail) { try { detail = JSON.stringify(e, Object.getOwnPropertyNames(e ?? {})); } catch { detail = String(e); } }
    log(`ERROR ${detail}`);
    // app.quit() ends with 0 whatever process.exitCode says, so a failed run used to look like a success to anything
    // that reads only the exit code. Exit 1 once the ERROR line is written out.
    process.stdout.write('', () => app.exit(1));
    return;
  }
  app.quit();
});
