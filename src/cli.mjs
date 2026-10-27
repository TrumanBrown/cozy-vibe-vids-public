#!/usr/bin/env node
// cozy-vibe-vids CLI.
//   node src/cli.mjs still   <sceneDir> [--frames 0,900] [--width 3840 --height 2160] [--seed N] [--out dir] [--name prefix]
//   node src/cli.mjs preview <sceneDir> [--seconds 10] [--start 0 | --event lightning:0] [--width ...] [--seed N] [--out file.mp4]
//                            [--codec hevc_nvenc|h264_nvenc] [--audio on|off]   (audio: tools/audio.py, muxed as AAC)
//   node src/cli.mjs timeline <sceneDir> [--seed N] [--out file.json]   (event timeline + weather sync -> out/<scene>/timeline.json)
//   node src/cli.mjs render  <sceneDir> [--duration 1h|10h|<s>] [--seed N] [--segment 300] [--name tag] [--music auto|off]
//                            [--audio-jobs 4] [--cq 19] [--qa full|quick|off] [--thumbs 5] [--force]
//                            [--from 8h --length 1h]   (render only that window of the full video, e.g. a test hour)
//                            (segmented, resumable master render -> out/<scene>/render/<tag>/; see src/render/pipeline.mjs)
//   node src/cli.mjs palette <image.png> [--colors 12]
// still/preview also take --params key=value,key2=value2 (scene variants/QA, read as ctx.params in build()).
// --duration (still/preview/timeline/render) overrides the scene's video length, e.g. a 1 h test video.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { launchElectron } from './render/launch.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [cmd, target, ...rest] = process.argv.slice(2);
const { values: a } = parseArgs({
  args: rest,
  options: {
    frames: { type: 'string', default: '0' }, width: { type: 'string', default: '3840' }, height: { type: 'string', default: '2160' },
    seed: { type: 'string' }, out: { type: 'string' }, name: { type: 'string' },
    seconds: { type: 'string', default: '10' }, start: { type: 'string', default: '0' }, codec: { type: 'string', default: 'hevc_nvenc' },
    colors: { type: 'string', default: '12' },
    cam: { type: 'string' }, target: { type: 'string' }, fov: { type: 'string' }, ssaa: { type: 'string' }, params: { type: 'string' },
    event: { type: 'string' }, audio: { type: 'string', default: 'on' },
    duration: { type: 'string' }, segment: { type: 'string', default: '300' }, music: { type: 'string', default: 'auto' },
    'audio-jobs': { type: 'string', default: '4' }, cq: { type: 'string' }, qa: { type: 'string', default: 'full' },
    thumbs: { type: 'string', default: '5' }, force: { type: 'boolean', default: false }, 'keep-wav': { type: 'boolean', default: false },
    from: { type: 'string' }, length: { type: 'string' },
  },
});

// "1h", "90m", "300s", "300" -> seconds (undefined if not given).
const parseDuration = (s) => {
  if (!s) return undefined;
  const m = /^(\d+(?:\.\d+)?)\s*(h|m|s)?$/i.exec(s.trim());
  if (!m) throw new Error(`bad --duration ${s} (use 1h, 90m, 300s or seconds)`);
  return Number(m[1]) * { h: 3600, m: 60, s: 1 }[(m[2] ?? 's').toLowerCase()];
};
const durationOverride = parseDuration(a.duration);

// Every command but palette takes a scene folder; say so plainly instead of failing deep in the renderer.
if (['still', 'preview', 'timeline', 'render', 'guides'].includes(cmd) && !(target && fs.existsSync(path.join(path.resolve(target), 'scene.js')))) {
  console.error(target ? `no scene.js in ${path.resolve(target)}` : `usage: node src/cli.mjs ${cmd} <sceneDir> [options]`);
  process.exit(2);
}
if (cmd === 'palette' && !(target && fs.existsSync(target))) {
  console.error(target ? `no image at ${path.resolve(target)}` : 'usage: node src/cli.mjs palette <image.png> [--colors 12]');
  process.exit(2);
}

// Everything Electron prints goes to the console; an exit code or an ERROR line fails the command.
async function runElectron(args) {
  const { code, out } = await launchElectron(root, args, { echo: true });
  if (code !== 0 || out.includes('ERROR')) throw new Error(code === 0 ? 'render failed (the ERROR line above says why)' : `render failed (exit ${code})`);
  return out;
}

const sceneName = (dir) => path.basename(path.resolve(dir));
const vec = (s) => s.split(',').map(Number);
const camOverride = () => {
  const c = {};
  if (a.cam) c.pos = vec(a.cam);
  if (a.target) c.target = vec(a.target);
  if (a.fov) c.fov = Number(a.fov);
  return Object.keys(c).length ? ['--camera', JSON.stringify(c)] : [];
};
const common = () => ['--scene', target, '--width', a.width, '--height', a.height, ...(a.seed ? ['--seed', a.seed] : []), ...(a.ssaa ? ['--ssaa', a.ssaa] : []), ...(a.params ? [`--params=${a.params}`] : []), ...(durationOverride ? ['--duration', String(durationOverride)] : []), ...camOverride()];

const python = () => [path.join(root, '.venv', 'Scripts', 'python.exe'), path.join(root, '.venv', 'bin', 'python')].find((p) => fs.existsSync(p)) ?? 'python';

// Event timeline + weather sync data for a scene (same function the renderer uses: src/library/timeline.js).
async function writeTimeline(sceneDir, out, duration = durationOverride) {
  const { default: S } = await import(pathToFileURL(path.resolve(sceneDir, 'scene.js')).href);
  const { buildTimeline } = await import('./library/timeline.js');
  const { runoffParams } = await import('./library/rain.js');
  const seed = a.seed ? Number(a.seed) : S.seed ?? 1;
  const fps = S.fps ?? 30;
  const platePath = S.plate ? path.join(root, 'out', 'plates', S.plate, 'plate.json') : null;
  const plate = platePath && fs.existsSync(platePath) ? JSON.parse(fs.readFileSync(platePath, 'utf8')) : null;
  const tl = buildTimeline(S.events ?? {}, { seed, duration: duration ?? S.duration ?? 36000, fps, plate, loopSeconds: S.loopSeconds ?? 60 });
  // Boat events carry their distance/pan profile for the audio (same route and pose code as the renderer);
  // fish rises carry their distance (lake camera) and pan.
  if (S.events?.boat?.route) {
    const { boatProfile, lakeCamera } = await import('./library/boat.js');
    for (const e of tl.events) if (e.type === 'boat') e.profile = boatProfile(S.events.boat.route, e);
    const cam = lakeCamera(S.events.boat.route.camera);
    for (const e of tl.events) {
      if (e.type !== 'fish') continue;
      const P = cam.toWater(e.x, e.y);
      e.dist = Math.round(Math.hypot(P[0] - cam.C[0], cam.C[1], P[2] - cam.C[2]) * 10) / 10;
      e.pan = Math.round(Math.max(-0.9, Math.min(0.9, (e.x - 0.5) * 1.6)) * 1000) / 1000;
    }
  }
  const doc = {
    scene: sceneName(sceneDir), title: S.title, ...tl, loopSeconds: S.loopSeconds ?? 60,
    weather: { wind: S.weather?.wind ?? null, runoff: runoffParams(S.weather?.runoff ?? [], S.loopSeconds ?? 60) },
    audio: S.audio ?? null,
  };
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(doc, null, 1));
  return doc;
}

if (cmd === 'still') {
  const outDir = path.resolve(a.out ?? path.join(root, 'out', sceneName(target), 'stills'));
  const prefix = a.name ?? sceneName(target);
  const res = a.width === '3840' ? '4k' : `${a.width}x${a.height}`;
  await runElectron([...common(), '--stills', a.frames, '--pattern', path.join(outDir, `${prefix}_${res}_f{frame}.png`)]);
} else if (cmd === 'preview') {
  const tlPath = path.join(root, 'out', sceneName(target), 'timeline.json');
  const tl = await writeTimeline(target, tlPath);
  const fps = tl.fps ?? 30;   // the scene's own rate (its timeline is built with it), as the renderer uses
  let start = Number(a.start);
  if (a.event) {
    // --event lightning:2 -> start 6 s before the 3rd lightning strike (thunder lands inside the clip); also boat:N, lantern:N.
    const [type, k] = a.event.split(':');
    const ev = tl.events.filter((e) => e.type === type)[Number(k ?? 0)];
    if (!ev) throw new Error(`no event ${a.event} in the timeline`);
    start = Math.max(0, Math.round((ev.t - 6) * fps));
    console.log(`event ${a.event}: t=${ev.t}s${ev.thunder ? ` (thunder +${ev.thunder.delay}s)` : ''} -> start frame ${start}`);
  }
  const count = Math.round(Number(a.seconds) * fps);
  const out = path.resolve(a.out ?? path.join(root, 'out', sceneName(target), `preview_${a.seconds}s.mp4`));
  const withAudio = a.audio !== 'off' && tl.audio;
  const video = withAudio ? out.replace(/\.mp4$/i, '.video.mp4') : out;
  await runElectron([...common(), '--start', String(start), '--count', String(count), '--out', video, '--codec', a.codec]);
  if (withAudio) {
    const wav = out.replace(/\.mp4$/i, '.wav');
    const r = spawnSync(python(), [path.join(root, 'tools', 'audio.py'), tlPath, '--start', String(start / fps), '--duration', String(count / fps), '--out', wav], { stdio: ['ignore', 'pipe', 'inherit'] });
    if (r.status !== 0) throw new Error('audio render failed');
    process.stdout.write(r.stdout.toString());
    const m = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-i', video, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k', '-shortest', out], { stdio: 'inherit' });
    if (m.status !== 0) throw new Error('mux failed');
    fs.rmSync(video);
    console.log(`muxed audio -> ${out}`);
  }
} else if (cmd === 'timeline') {
  const out = path.resolve(a.out ?? path.join(root, 'out', sceneName(target), 'timeline.json'));
  const tl = await writeTimeline(target, out);
  const n = tl.events.length;
  console.log(`timeline: ${n} events in ${(tl.duration / 3600).toFixed(1)} h (${(n / (tl.duration / 3600)).toFixed(1)}/h) -> ${out}`);
  for (const e of tl.events.slice(0, 5)) console.log(`  ${e.type} #${e.id} t=${e.t}s frame ${e.frame}${e.thunder ? ` thunder +${e.thunder.delay}s` : ''}`);
} else if (cmd === 'render') {
  const { renderMaster } = await import('./render/pipeline.mjs');
  await renderMaster({ root, a, target, sceneName: sceneName(target), duration: durationOverride, from: parseDuration(a.from), length: parseDuration(a.length), common, writeTimeline, python });
} else if (cmd === 'guides') {
  // Color + exact depth guide images for AI enhancement (see tools/enhance.py).
  const prefix = path.resolve(a.out ?? path.join(root, 'out', sceneName(target), 'guides', `f${String(a.start).padStart(6, '0')}`));
  await runElectron([...common(), '--start', a.start, '--guides', prefix]);
} else if (cmd === 'palette') {
  // Median-cut palette of an image (downscaled), printed as hex with pixel share.
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-i', target, '-vf', 'scale=320:-1:flags=area', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], { maxBuffer: 1 << 26 });
  const d = r.stdout;
  const px = [];
  for (let i = 0; i < d.length; i += 3) px.push([d[i], d[i + 1], d[i + 2]]);
  let boxes = [px];
  while (boxes.length < Number(a.colors)) {
    boxes.sort((x, y) => y.length - x.length);
    const b = boxes.shift();
    const ranges = [0, 1, 2].map((c) => Math.max(...b.map((p) => p[c])) - Math.min(...b.map((p) => p[c])));
    const ch = ranges.indexOf(Math.max(...ranges));
    b.sort((x, y) => x[ch] - y[ch]);
    boxes.push(b.slice(0, b.length >> 1), b.slice(b.length >> 1));
  }
  const toHex = (c) => '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const lum = (h) => [1, 3, 5].reduce((s, i, k) => s + parseInt(h.slice(i, i + 2), 16) * [0.2126, 0.7152, 0.0722][k], 0);
  const out = boxes.map((b) => ({ hex: toHex([0, 1, 2].map((c) => b.reduce((s, p) => s + p[c], 0) / b.length)), share: b.length / px.length }))
    .sort((x, y) => lum(x.hex) - lum(y.hex));
  for (const o of out) console.log(`${o.hex}  ${(o.share * 100).toFixed(1)}%`);
} else {
  console.error('usage: node src/cli.mjs still|preview|palette <target> [options]');
  process.exitCode = 2;
}
