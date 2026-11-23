// Electron driver for the three.js spike: hidden GPU window, frames piped straight to ffmpeg.
// Usage: npx electron spikes/three/electron-main.cjs --start 0 --count 300 --out out/x.mp4 [--hash h.json] [--stills 0,150] [--summary s.json] [--read async]
const { app, BrowserWindow } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { parseArgs } = require('node:util');

const root = path.resolve(__dirname, '..');
process.on('uncaughtException', (e) => { process.stderr.write(`FATAL ${e.stack ?? e}\n`); app.exit(1); });
const argv = process.argv.slice(process.argv.findIndex((x) => x.endsWith('electron-main.cjs')) + 1);
const { values: a } = parseArgs({
  args: argv,
  strict: false,
  options: {
    start: { type: 'string', default: '0' }, count: { type: 'string', default: '300' },
    out: { type: 'string' }, codec: { type: 'string', default: 'hevc_nvenc' }, hash: { type: 'string' },
    stills: { type: 'string', default: '' }, stillsDir: { type: 'string', default: path.join('out', 'phase0', 'three') },
    summary: { type: 'string' }, read: { type: 'string', default: 'async' }, ref: { type: 'string' }, dumpDir: { type: 'string' },
    'no-ao': { type: 'boolean', default: false }, 'no-bloom': { type: 'boolean', default: false }, msaa: { type: 'string', default: '4' },
  },
});

app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('force_high_performance_gpu');
app.commandLine.appendSwitch('use-angle', 'd3d11');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
// Per-run profile dir so concurrent runs don't fight over caches. Electron keeps files in it open
// until the process exits, so stale dirs from earlier runs are swept (best-effort) at startup instead.
{
  const tmp = require('node:os').tmpdir();
  for (const d of fs.readdirSync(tmp)) {
    if (!d.startsWith('cvv-electron-')) continue;
    try { fs.rmSync(path.join(tmp, d), { recursive: true, force: true }); } catch { /* still in use by another run */ }
  }
  app.setPath('userData', fs.mkdtempSync(path.join(tmp, 'cvv-electron-')));
}

const mime = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };
function serve() {
  const server = http.createServer((req, res) => {
    // only this page: a website rebinding its name to 127.0.0.1 is refused, and paths stay inside spikes/
    if (req.headers.host !== `127.0.0.1:${server.address().port}`) { res.writeHead(403).end(); return; }
    let p;
    try { p = path.normalize(path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname))); } catch { res.writeHead(400).end(); return; }
    const rel = path.relative(root, p);
    if (!rel || rel.split(path.sep)[0] === '..' || path.isAbsolute(rel) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'content-type': mime[path.extname(p)] ?? 'application/octet-stream' });
    fs.createReadStream(p).pipe(res);
  });
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(server)));
}

app.whenReady().then(async () => {
  const log = (s) => process.stdout.write(`${s}\n`);
  try {
    const server = await serve();
    const win = new BrowserWindow({ show: false, width: 1280, height: 720, webPreferences: { nodeIntegration: true, contextIsolation: false, backgroundThrottling: false } });
    win.webContents.on('will-navigate', (e) => e.preventDefault());
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('console-message', (e) => { if (e.level === 'error' || e.level === 'warning') log(`[page] ${e.message}`); });
    await win.loadURL(`http://127.0.0.1:${server.address().port}/three/index.html`);
    const js = (s) => win.webContents.executeJavaScript(s);
    while (!(await js('!!window.spike'))) await new Promise((r) => setTimeout(r, 20));
    const info = await js(`window.spike.init(${JSON.stringify({ ao: !a['no-ao'], bloom: !a['no-bloom'], msaa: Number(a.msaa) })})`);
    log(`renderer: ${info.renderer}`);
    const o = {
      sinkPath: path.join(__dirname, 'sink.cjs'), out: a.out ? path.resolve(a.out) : null, codec: a.codec, hash: !!a.hash,
      stills: a.stills ? a.stills.split(',').map(Number) : [], stillsDir: path.resolve(a.stillsDir), readMode: a.read,
      ref: a.ref ? JSON.parse(fs.readFileSync(a.ref, 'utf8')) : null, dumpDir: a.dumpDir ? path.resolve(a.dumpDir) : null,
    };
    const t0 = Date.now();
    const r = await js(`window.spike.runNode(${Number(a.start)}, ${Number(a.count)}, ${JSON.stringify(o)})`);
    const wall = (Date.now() - t0) / 1000;
    if (a.hash) fs.writeFileSync(a.hash, JSON.stringify(r.hashes, null, 1));
    const summary = { engine: 'three-electron', renderer: info.renderer, frames: r.frames, wallSec: +wall.toFixed(2), fps: +(r.frames / wall).toFixed(2), out: a.out ?? null, read: a.read };
    log(JSON.stringify(summary));
    if (a.summary) fs.writeFileSync(a.summary, JSON.stringify(summary));
    server.close();
  } catch (e) {
    log(`ERROR ${e.stack ?? e}`);
    process.exitCode = 1;
  }
  app.quit();
});
