// Drives the three.js spike in headless Chromium and pipes frames to ffmpeg (NVENC).
// Usage: node spikes/three/render.mjs --start 0 --count 300 --out out/phase0/three.mp4 [--hash f.json] [--stills 0,150] [--no-ao] [--no-bloom] [--headed]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const { values: a } = parseArgs({
  options: {
    start: { type: 'string', default: '0' },
    count: { type: 'string', default: '300' },
    out: { type: 'string' },
    codec: { type: 'string', default: 'hevc_nvenc' },
    hash: { type: 'string' },
    stills: { type: 'string', default: '' },
    stillsDir: { type: 'string', default: path.join('out', 'phase0', 'three') },
    'no-ao': { type: 'boolean', default: false },
    'no-bloom': { type: 'boolean', default: false },
    msaa: { type: 'string', default: '4' },
    headed: { type: 'boolean', default: false },
    channel: { type: 'string' },
    probe: { type: 'boolean', default: false },
    bench: { type: 'boolean', default: false },
  },
});
const start = Number(a.start), count = Number(a.count);
const stills = new Set(a.stills ? a.stills.split(',').map(Number) : []);

const mime = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  // only this page: a website rebinding its name to 127.0.0.1 is refused, and paths stay inside spikes/
  if (req.headers.host !== `127.0.0.1:${server.address().port}`) { res.writeHead(403).end(); return; }
  if (req.method === 'POST' && req.url === '/sink') { req.on('data', () => {}); req.on('end', () => res.writeHead(204).end()); return; }
  let p;
  try { p = path.normalize(path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname))); } catch { res.writeHead(400).end(); return; }
  const rel = path.relative(root, p);
  if (!rel || rel.split(path.sep)[0] === '..' || path.isAbsolute(rel) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404).end(); return; }
  res.writeHead(200, { 'content-type': mime[path.extname(p)] ?? 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
// the bench's frames come from this page only, never from another site open in the browser
const wss = new WebSocketServer({ server, verifyClient: ({ origin }) => origin === `http://127.0.0.1:${server.address().port}` });
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const tLaunch = performance.now();
const browser = await chromium.launch({
  headless: !a.headed,
  channel: a.channel,
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-gpu-rasterization', '--disable-gpu-driver-bug-workarounds', '--force_high_performance_gpu'],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.error(`[page] ${m.text()}`); });
page.on('pageerror', (e) => console.error(`[page error] ${e.message}`));
await page.goto(`http://127.0.0.1:${port}/three/index.html`);
await page.waitForFunction(() => window.spike);
const info = await page.evaluate((o) => window.spike.init(o), { ao: !a['no-ao'], bloom: !a['no-bloom'], msaa: Number(a.msaa) });
console.log(`renderer: ${info.renderer} | three r${info.three} | init ${((performance.now() - tLaunch) / 1000).toFixed(1)}s`);
if (a.probe) { await browser.close(); server.close(); process.exit(0); }
if (a.bench) {
  wss.on('connection', (ws) => ws.on('message', () => {}));
  console.log(JSON.stringify(await page.evaluate(({ n, url }) => window.spike.bench(n, url), { n: 30, url: `ws://127.0.0.1:${port}` })));
  await browser.close(); server.close(); process.exit(0);
}

const W = 3840, H = 2160;
const ffArgs = (out) => ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', `${W}x${H}`, '-r', '30',
  '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-i', '-',
  '-c:v', a.codec, '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-maxrate', '80M', '-bufsize', '160M',
  ...(a.codec === 'hevc_nvenc' ? ['-tag:v', 'hvc1'] : []), '-movflags', '+faststart', out];
let ff = null;
if (a.out) {
  fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
  ff = spawn('ffmpeg', ffArgs(a.out), { stdio: ['pipe', 'inherit', 'inherit'] });
}
if (stills.size) fs.mkdirSync(a.stillsDir, { recursive: true });

const hashes = {};
const stillJobs = [];
let received = 0, tFirst = 0;
const done = new Promise((resolve) => {
  wss.on('connection', (ws) => {
    ws.on('message', (data) => {
      const buf = Buffer.from(data);
      const frame = start + received++;
      if (received === 1) tFirst = performance.now();
      if (a.hash) hashes[frame] = crypto.createHash('sha256').update(buf).digest('hex');
      if (stills.has(frame)) {
        const file = path.join(a.stillsDir, `frame_${String(frame).padStart(5, '0')}.png`);
        const p = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', `${W}x${H}`, '-i', '-',
          '-vf', 'scale=in_color_matrix=bt709:in_range=limited:out_range=full,format=rgb24', '-frames:v', '1', file]);
        p.stdin.end(buf);
        stillJobs.push(new Promise((r) => p.on('close', r)));
      }
      if (ff && !ff.stdin.write(buf)) { ws.pause(); ff.stdin.once('drain', () => ws.resume()); }
      if (received % 60 === 0) process.stdout.write(`  ${received}/${count} frames, ${(received / ((performance.now() - tFirst) / 1000)).toFixed(1)} fps\r`);
    });
    ws.on('close', resolve);
  });
});

const tRun = performance.now();
const result = await page.evaluate(({ s, c, url }) => window.spike.run(s, c, url), { s: start, c: count, url: `ws://127.0.0.1:${port}` });
await done;
if (ff) { ff.stdin.end(); await new Promise((r) => ff.on('close', r)); }
await Promise.all(stillJobs);
const wall = (performance.now() - tRun) / 1000;
await browser.close();
server.close();

if (a.hash) fs.writeFileSync(a.hash, JSON.stringify(hashes, null, 1));
const summary = { engine: 'three', renderer: info.renderer, frames: received, wallSec: +wall.toFixed(2), fps: +(received / wall).toFixed(2), pageRenderFps: +(result.frames / (result.ms / 1000)).toFixed(2), out: a.out ?? null };
console.log(`\n${JSON.stringify(summary)}`);
