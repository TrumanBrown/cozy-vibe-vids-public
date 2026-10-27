// Segmented, resumable master render (docs/decisions/0001-tech-stack.md, "Assembly: B"). The whole video is
// rendered frame by frame in fixed-length segments (default 5 min), so a crash or a Windows restart costs at
// most one segment; re-running the same command resumes. Audio segments (tools/audio.py: random access,
// sample-exact) render in parallel on the CPU while the GPU renders video, and are encoded in one pass, so
// there are no gaps at the joins.
//
// out/<scene>/render/<tag>/                      (tag = <duration>_seed<N> unless --name)
//   render.json          manifest: config fingerprint, per-segment status/size/hash/timing, outputs, QA summary
//   timeline.json        the event timeline used (its duration = this render's length)
//   music_plan.json      music playlist (no entries without tracks in music/)
//   seg/v_###.mp4        video segments (HEVC NVENC; kept for resume/re-mux); seg/a_###.wav (+ _music) audio segments,
//                        deleted once encoded
//   ambience.flac/.m4a   ambience-only mix: 24-bit FLAC master + AAC 384k for the upload
//   music_mix.flac/.m4a  ambience + music (only with tracks)
//   master.mp4           all video segments (stream copy) + ambience     master_music.mp4  + music mix (only with tracks)
//   qa.json, qa.md       frames/timestamps, segment joins (decoded vs fresh renders), determinism (a re-rendered
//                        segment's hash), loudness (ffmpeg ebur128), events per hour, render stats
//   thumbs/*.png         4K thumbnail candidates     credits.txt  for the YouTube description
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { plateHash } from './inputs.mjs';
import { launchElectron } from './launch.mjs';

const hhmmss = (s) => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const label = (D) => (D % 3600 === 0 ? `${D / 3600}h` : D % 60 === 0 ? `${D / 60}m` : `${D}s`);
const pad = (k) => String(k).padStart(3, '0');
const sha1 = (s) => crypto.createHash('sha1').update(s).digest('hex');
const posix = (p) => p.split(path.sep).join('/');
const sha256File = (f) => new Promise((res, rej) => {
  const h = crypto.createHash('sha256');
  fs.createReadStream(f).on('data', (d) => h.update(d)).on('end', () => res(h.digest('hex'))).on('error', rej);
});

function run(cmd, args, { cwd, lowPriority = false } = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd, stdio: ['ignore', 'pipe', 'pipe'] });
    // Background-friendly: audio jobs run below normal priority (keeps the desktop responsive). They still
    // slow the video from ~100 to ~55 fps while they run (memory bandwidth, not CPU time); running them in
    // parallel is nevertheless faster overall than rendering audio before or after the video.
    if (lowPriority) try { os.setPriority(p.pid, os.constants.priority.PRIORITY_BELOW_NORMAL); } catch { /* best effort */ }
    let out = '', err = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { err += d; });
    p.on('close', (code) => (code === 0 ? resolve({ out, err }) : reject(new Error(`${path.basename(cmd)} ${args.slice(0, 2).join(' ')} failed (${code}): ${err.slice(-800)}`))));
  });
}

function ffmpeg(args) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { maxBuffer: 1 << 28 });
  if (r.status !== 0) throw new Error(`ffmpeg ${args.join(' ').slice(0, 200)} failed: ${r.stderr}`);
  return r;
}

const probe = (args) => spawnSync('ffprobe', ['-v', 'error', ...args], { maxBuffer: 1 << 30 }).stdout.toString().trim();

// The page's messages in an Electron run's output, as electron-main.cjs tags them: [{ level: 'info' | 'warning' |
// 'error', text }], progress lines left out. A layer reports a defect (a critter path end in plain sight, a lamp the
// moth can't find) with console.warn, and the QA report fails on any (TASKS.md T6).
export const pageMessages = (out) => [...out.matchAll(/^\[page( warning| error)?\] (.*)$/gm)]
  .map((m) => ({ level: m[1] ? m[1].trim() : 'info', text: m[2].trim() }))
  .filter((m) => !/^progress \d+\/\d+/.test(m.text));

// Electron segment render with condensed progress (one line per ~15 s instead of every 150 frames). It fails on an exit
// code or an ERROR or FATAL line in its output, and returns stdout for pageMessages.
async function electron(root, args, onProgress) {
  const { code, out, err } = await launchElectron(root, args, { onProgress });
  const bad = (out + err).split('\n').filter((l) => /ERROR|FATAL/.test(l)).slice(0, 4).join(' | ');
  if (code !== 0 || bad) throw new Error(`electron exit ${code}: ${bad || err.slice(-400)}`);
  return out;
}

// The rendered scene and the scenes its scene.js imports (a mock wraps another scene), by folder name.
export function sceneClosure(root, name, seen = new Set()) {
  if (seen.has(name)) return seen;
  seen.add(name);
  const f = path.join(root, 'scenes', name, 'scene.js');
  if (fs.existsSync(f)) for (const m of fs.readFileSync(f, 'utf8').matchAll(/from\s+['"]\.\.\/([\w.-]+)\/scene\.js['"]/g)) sceneClosure(root, m[1], seen);
  return seen;
}

// What the segments depend on (TASKS.md T9): the code that makes the frames (src/engine, src/library, the page and its
// sinks) and the sound (tools/audio.py and music.py with every tool module they import, cozy.code), this scene and
// the scenes it imports with their own key art folders (critter sprites), the textures and models the code-built
// scenes load, the plate folder's content with its fire and steam clips (src/render/inputs.mjs), and the timeline,
// music plan and settings. QA and pipeline scripts are left out so fixing them doesn't block a resume, and so are
// other scenes: editing the next video's scene.json doesn't stop this one's render from resuming.
export function fingerprint(root, S, settings, { scene, py }) {
  const git = (args) => spawnSync('git', args, { cwd: root, maxBuffer: 1 << 28 }).stdout;
  const scenes = [...sceneClosure(root, scene)].sort();
  const dirs = ['src/engine', 'src/library', 'src/render/page.js', 'src/render/page.html', 'src/render/sink.cjs', 'src/render/electron-main.cjs',
    ...scenes.flatMap((s) => [`scenes/${s}`, `assets/keyart/${s}`]), 'assets/textures', 'assets/models'];
  // Content hash (not the commit), so committing docs mid-render doesn't block a resume; CRLF/LF-insensitive.
  const files = git(['ls-files', '--cached', '--others', '--exclude-standard', '--', ...dirs]).toString().split('\n').filter(Boolean).sort();
  const norm = (f) => sha1(fs.readFileSync(path.join(root, f)).toString('latin1').replace(/\r\n/g, '\n'));
  const code = sha1(files.map((f) => (fs.existsSync(path.join(root, f)) ? `${f}:${norm(f)}` : '')).join(','));
  const r = spawnSync(py, ['-c', 'import sys; sys.path.insert(0, "tools"); from cozy.code import code_hash; print(code_hash("audio", "music"))'], { cwd: root });
  if (r.status !== 0) throw new Error(`could not hash the audio code (tools/cozy/code.py): ${r.stderr}`);
  const audio = r.stdout.toString().trim();
  const plate = S.plate ? plateHash(root, S.plate)?.hash ?? null : null;
  return { code, audio, plate, scenes, ...settings };
}

async function pool(items, n, fn) {
  const q = [...items];
  await Promise.all(Array.from({ length: Math.min(n, q.length) }, async () => { while (q.length) await fn(q.shift()); }));
}

export async function renderMaster({ root, a, target, sceneName, duration, from, length, common, writeTimeline, python }) {
  const { default: S } = await import(pathToFileURL(path.resolve(target, 'scene.js')).href);
  const fps = S.fps ?? 30;
  const D = duration ?? S.duration ?? 36000;
  // Optional window of the full video (e.g. one test hour of the real 10 h master): [R0, R0 + L).
  const R0 = from ?? 0, L = length ?? D - R0;
  if (R0 < 0 || L <= 0 || R0 + L > D + 1e-6) throw new Error(`window ${R0}+${L} s is outside the ${D} s video`);
  const windowed = R0 > 0 || L < D;
  const seed = a.seed ? Number(a.seed) : S.seed ?? 1;
  const segS = Number(a.segment);
  const codec = a.codec, cq = a.cq ? Number(a.cq) : null;
  const tag = a.name ?? (windowed ? `${label(L)}_at${label(R0)}_seed${seed}` : `${label(D)}_seed${seed}`);
  const dir = path.join(root, 'out', sceneName, 'render', tag);
  const segDir = path.join(dir, 'seg'), qaDir = path.join(dir, 'qa'), thumbDir = path.join(dir, 'thumbs');
  for (const d of [segDir, qaDir, thumbDir]) fs.mkdirSync(d, { recursive: true });
  const T0 = Date.now();
  const log = (s) => console.log(`[render ${hhmmss((Date.now() - T0) / 1000)}] ${s}`);
  const py = python();
  log(`${sceneName} | ${windowed ? `${hhmmss(R0)}-${hhmmss(R0 + L)} of a ${hhmmss(D)} video` : hhmmss(D)} at ${fps} fps | seed ${seed} | segments of ${segS} s | -> ${dir}`);

  // 1. Timeline (with boat audio profiles) and music plan for exactly this video length.
  const tlPath = path.join(dir, 'timeline.json');
  const tl = await writeTimeline(target, tlPath, D);
  const planPath = path.join(dir, 'music_plan.json');
  if (a.music === 'off') fs.writeFileSync(planPath, JSON.stringify({ version: 1, seed, duration: D, cfg: {}, tracks: [], entries: [] }));
  else await run(py, [path.join(root, 'tools', 'music.py'), 'plan', tlPath, '--out', planPath]);
  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  const withMusic = plan.entries.length > 0;
  log(`timeline: ${tl.events.length} events | music: ${withMusic ? `${plan.tracks.length} tracks` : 'none (ambience only)'}`);

  // 2. Manifest: resume when nothing that the segments depend on has changed.
  const frames = Math.round(L * fps), segF = Math.round(segS * fps), F0 = Math.round(R0 * fps);
  const segs = [];
  for (let s = 0, k = 0; s < frames; s += segF, k++) segs.push({ k, start: F0 + s, count: Math.min(segF, frames - s) });
  const fp = fingerprint(root, S, {
    seed, duration: D, from: R0, length: L, fps, segF, codec, cq, width: a.width, height: a.height, params: a.params ?? null,
    timeline: sha1(fs.readFileSync(tlPath)), music: sha1(fs.readFileSync(planPath)),
  }, { scene: sceneName, py });
  const fpHash = sha1(JSON.stringify(fp));
  const manPath = path.join(dir, 'render.json');
  let man = fs.existsSync(manPath) ? JSON.parse(fs.readFileSync(manPath, 'utf8')) : null;
  if (man && man.fingerprintHash !== fpHash) {
    if (!a.force) throw new Error(`${manPath} was rendered from different code/config. Re-run with --force to start over, or use --name <new tag>.`);
    log('--force: code/config changed, starting over');
    for (const f of fs.readdirSync(segDir)) fs.rmSync(path.join(segDir, f), { force: true });
    man = null;
  }
  man ??= {
    version: 1, scene: sceneName, tag, seed, duration: D, from: R0, length: L, fps, frames, segment: segS, codec, cq,
    git: spawnSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root }).stdout.toString().trim(),
    fingerprint: fp, fingerprintHash: fpHash, created: new Date().toISOString(), segments: segs.map((s) => ({ ...s, video: null, audio: null })),
  };
  const save = () => { man.updated = new Date().toISOString(); fs.writeFileSync(manPath, JSON.stringify(man, null, 1)); };
  save();
  const N = man.segments.length;
  // every distinct page message of the segments, with the segments that printed it; warnings are logged once
  man.page ??= [];
  const notePage = (out, k) => {
    for (const m of pageMessages(out)) {
      let e = man.page.find((x) => x.level === m.level && x.text === m.text);
      if (!e) {
        e = { ...m, segments: [] };
        man.page.push(e);
        if (m.level !== 'info') log(`page ${m.level}: ${m.text}`);
      }
      if (!e.segments.includes(k)) e.segments.push(k);
    }
  };

  // 3. Audio segments on the CPU (parallel), unless the encoded audio already exists.
  const audioFinal = path.join(dir, 'ambience.flac');
  const audioNeeded = !(man.outputs?.audio && fs.existsSync(audioFinal));
  let audioDone = man.segments.filter((s) => s.audio?.done).length;
  const audioTask = audioNeeded ? pool(man.segments.filter((s) => !(s.audio?.done && fs.existsSync(s.audio.file))), Math.max(1, Number(a['audio-jobs'])), async (s) => {
    const t0 = Date.now();
    const wav = path.join(segDir, `a_${pad(s.k)}.wav`);
    await run(py, [path.join(root, 'tools', 'audio.py'), tlPath, '--start', String(s.start / fps), '--duration', String(s.count / fps), '--out', wav,
      ...(withMusic ? ['--music', planPath] : [])], { lowPriority: true });
    s.audio = { file: wav, music: withMusic ? wav.replace(/\.wav$/, '_music.wav') : null, sec: +((Date.now() - t0) / 1000).toFixed(1), done: true };
    audioDone++;
    save();
  }) : Promise.resolve();
  audioTask.catch(() => {});

  // 4. Video segments on the GPU (sequential), each a fresh Electron process; one retry per segment.
  const cqArgs = cq ? ['--cq', String(cq)] : [];
  let doneFrames = man.segments.filter((s) => s.video?.done).reduce((n, s) => n + s.count, 0);
  const vStart = Date.now(), framesAtStart = doneFrames;
  for (const s of man.segments) {
    const file = path.join(segDir, `v_${pad(s.k)}.mp4`);
    if (s.video?.done && fs.existsSync(file) && fs.statSync(file).size === s.video.bytes) continue;
    for (let tries = 1; ; tries++) {
      try {
        const t0 = Date.now();
        let last = 0;
        const out = await electron(root, [...common(), '--start', String(s.start), '--count', String(s.count), '--out', file, '--codec', codec, ...cqArgs], (i, n, f) => {
          if (Date.now() - last < 15000 && i < n) return;
          last = Date.now();
          const rate = (doneFrames + i - framesAtStart) / ((Date.now() - vStart) / 1000);
          log(`video seg ${s.k + 1}/${N} ${i}/${n} @ ${f.toFixed(0)} fps | total ${(100 * (doneFrames + i) / frames).toFixed(1)}% | audio ${audioDone}/${N} | ETA ${hhmmss((frames - doneFrames - i) / Math.max(rate, 1))}`);
        });
        notePage(out, s.k);
        const sec = (Date.now() - t0) / 1000;
        s.video = { file, bytes: fs.statSync(file).size, sha256: await sha256File(file), sec: +sec.toFixed(1), fps: +(s.count / sec).toFixed(1), done: true };
        doneFrames += s.count;
        save();
        break;
      } catch (e) {
        if (tries >= 2) throw e;
        log(`segment ${s.k} failed (${e.message}); retrying`);
      }
    }
  }
  log(`video segments done | waiting for audio (${audioDone}/${N})`);
  await audioTask;

  // 5. Assemble: audio in one encode pass; masters = all video segments (stream copy) + audio, in one mux.
  const list = (files, name) => {
    const f = path.join(segDir, name);
    fs.writeFileSync(f, files.map((x) => `file '${posix(x)}'`).join('\n') + '\n');
    return f;
  };
  const videoList = list(man.segments.map((s) => s.video.file), 'video.txt');
  const big = L > 7200;
  // A window cut from the middle of the video starts and ends mid-rain: soft audio fades at its edges. A looped
  // window (the timeline repeats with it, events.loop) is played back to back by loop_master, so it gets none: its
  // sound already runs on seamlessly across the join (tools/audio.py folds time into the period).
  const loopWin = tl.loop?.period && Math.abs(L / tl.loop.period - Math.round(L / tl.loop.period)) < 1e-9;
  const af = windowed && !loopWin ? ['-af', `afade=t=in:st=0:d=1.5,afade=t=out:st=${(L - 2).toFixed(3)}:d=2`] : [];
  const enc = (wavs, base) => {
    const l = list(wavs, `${base}.txt`);
    ffmpeg(['-f', 'concat', '-safe', '0', '-i', l, ...af, '-c:a', 'flac', '-sample_fmt', 's32', path.join(dir, `${base}.flac`)]);
    ffmpeg(['-f', 'concat', '-safe', '0', '-i', l, ...af, '-c:a', 'aac', '-b:a', '384k', path.join(dir, `${base}.m4a`)]);
  };
  if (audioNeeded) {
    enc(man.segments.map((s) => s.audio.file), 'ambience');
    if (withMusic) enc(man.segments.map((s) => s.audio.music), 'music_mix');
    man.outputs = { ...(man.outputs ?? {}), audio: true };
    save();
    const fd = Number(probe(['-show_entries', 'format=duration', '-of', 'csv=p=0', audioFinal]));
    if (Math.abs(fd - L) < 0.05 && !a['keep-wav']) for (const s of man.segments) for (const f of [s.audio.file, s.audio.music]) if (f) fs.rmSync(f, { force: true });
    log(`audio encoded (ambience${withMusic ? ' + music mix' : ''}; FLAC + AAC 384k)`);
  }
  const mux = (aud, out) => ffmpeg(['-f', 'concat', '-safe', '0', '-i', videoList, '-i', path.join(dir, aud), '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy',
    ...(big ? [] : ['-movflags', '+faststart']), path.join(dir, out)]);
  mux('ambience.m4a', 'master.mp4');
  if (withMusic) mux('music_mix.m4a', 'master_music.mp4');
  fs.rmSync(path.join(dir, 'video.mp4'), { force: true });   // older renders kept a video-only intermediate
  const video = path.join(dir, 'master.mp4');
  man.outputs = { ...(man.outputs ?? {}), master: 'master.mp4', ...(withMusic ? { master_music: 'master_music.mp4' } : {}) };
  save();
  log(`master.mp4${withMusic ? ' + master_music.mp4' : ''} muxed`);

  // 6. Credits, thumbnails, QA.
  await run(py, [path.join(root, 'tools', 'music.py'), 'credits', planPath, '--out', path.join(dir, 'credits.txt')]);
  await thumbnails({ root, a, common, tl, R0, L, fps, thumbDir, log });
  if (a.qa !== 'off') await qa({ root, a, man, dir, qaDir, video, tl, R0, L, fps, frames, F0, withMusic, common, codec, cqArgs, py, log, save });
  const vsec = man.segments.reduce((n, s) => n + s.video.sec, 0);
  log(`done in ${hhmmss((Date.now() - T0) / 1000)} (video ${hhmmss(vsec)} at ${(frames / vsec).toFixed(1)} fps) -> ${path.join(dir, 'master.mp4')}`);
}

// Thumbnail candidates: calm moments spread over the video (never within 10 s of lightning) and the boat
// at its best (nearest point while fully visible), as 4K PNGs.
async function thumbnails({ root, a, common, tl, R0, L, fps, thumbDir, log }) {
  const n = Math.max(0, Number(a.thumbs));
  if (!n) return;
  const strikes = tl.events.filter((e) => e.type === 'lightning').map((e) => e.t);
  const calm = (t) => { for (let k = 0; k < 40 && strikes.some((s) => Math.abs(s - t) < 10); k++) t += 12; return t; };
  const ts = [];
  for (const boat of tl.events.filter((e) => e.type === 'boat' && e.profile)) {
    const p = boat.profile;
    let best = -1;
    p.dist.forEach((d, i) => {
      const t = boat.t + i * p.dt;
      if (t >= R0 && t < R0 + L && p.vis[i] >= 0.99 && (best < 0 || Math.abs(d - 125) < Math.abs(p.dist[best] - 125))) best = i;
    });
    if (best >= 0) { ts.push(boat.t + best * p.dt); break; }
  }
  for (let i = 0; ts.length < n; i++) ts.push(calm(R0 + L * (0.12 + 0.76 * (i / Math.max(n - 2, 1)))));
  const last = Math.round((R0 + L) * fps) - 1;
  const fr = [...new Set(ts.map((t) => Math.min(Math.round(t * fps), last)))].sort((x, y) => x - y);
  await electron(root, [...common(), '--stills', fr.join(','), '--pattern', path.join(thumbDir, 'thumb_f{frame}.png')]);
  log(`thumbnails: ${fr.length} -> ${thumbDir}`);
}

// QA report (GOALS deliverable 6): frames and timestamps, segment joins frame-exact against fresh renders,
// determinism (one segment re-rendered: identical bytes), loudness, events, render stats.
async function qa({ root, a, man, dir, qaDir, video, tl, R0, L, fps, frames, F0, withMusic, common, codec, cqArgs, py, log, save }) {
  const R = { checks: {} };
  const ok = (name, pass, detail) => { R.checks[name] = { pass, ...detail }; log(`QA ${name}: ${pass ? 'PASS' : 'FAIL'} ${JSON.stringify(detail)}`); };
  const F1 = F0 + frames;   // absolute frame range of this render: [F0, F1)

  // Frames and timestamps: every frame present exactly once at k / fps.
  const pts = probe(['-select_streams', 'v:0', '-show_entries', 'packet=pts_time', '-of', 'csv=p=0', video]).split(/\r?\n/).map(Number).sort((x, y) => x - y);
  const off = pts.reduce((m, t, k) => Math.max(m, Math.abs(t - pts[0] - k / fps)), 0);
  ok('frames', pts.length === frames && off < 0.25 / fps, { frames: pts.length, expected: frames, max_ts_error_ms: +(off * 1000).toFixed(2) });

  // Segment joins (+ a few random frames): decode frames from the master and compare them with fresh renders
  // of the same frame and its neighbours. A dropped or duplicated frame at a join would match a neighbour.
  const rnd = (k) => { let x = Math.imul(man.seed ^ 0x9e3779b9, k + 1) >>> 0; x ^= x >>> 15; x = Math.imul(x, 0x2c1b3c6d) >>> 0; return ((x ^ (x >>> 12)) >>> 0) / 4294967296; };
  const targets = [];
  for (const s of man.segments.slice(1)) targets.push(s.start - 1, s.start);
  const nr = a.qa === 'quick' ? 2 : 3 + Math.round(L / 3600);
  for (let i = 0; i < nr; i++) targets.push(F0 + 1 + Math.floor(rnd(i) * (frames - 2)));
  const uniq = [...new Set(targets)].sort((x, y) => x - y);
  const inside = (f) => f >= F0 && f < F1;
  const fresh = [...new Set(uniq.flatMap((f) => [f - 1, f, f + 1]).filter(inside))];
  const fp = (f) => path.join(qaDir, `fresh_f${String(f).padStart(6, '0')}.png`), dp = (f) => path.join(qaDir, `dec_f${String(f).padStart(6, '0')}.png`);
  await electron(root, [...common(), '--stills', fresh.join(','), '--pattern', path.join(qaDir, 'fresh_f{frame}.png')]);
  for (const f of uniq) {
    const r = f - F0;   // position in the master
    ffmpeg(['-ss', String(r === 0 ? 0 : (r - 0.5) / fps), '-i', video, '-frames:v', '1', '-vf', 'scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24', dp(f)]);
  }
  const pairs = uniq.map((f) => ({ id: f, a: dp(f), b: fp(f), near: [f - 1, f + 1].filter(inside).map(fp) }));
  fs.writeFileSync(path.join(qaDir, 'pairs.json'), JSON.stringify(pairs));
  await run(py, [path.join(root, 'tools', 'render_qa.py'), 'compare', path.join(qaDir, 'pairs.json'), path.join(qaDir, 'compare.json')]);
  const cmp = JSON.parse(fs.readFileSync(path.join(qaDir, 'compare.json'), 'utf8'));
  const joins = new Set(man.segments.slice(1).flatMap((s) => [s.start - 1, s.start]));
  const bad = cmp.filter((c) => c.error || !c.aligned || !c.clean);
  ok('joins', bad.length === 0, {
    joins: man.segments.length - 1, frames_checked: cmp.length, min_psnr_db: Math.min(...cmp.map((c) => c.psnr ?? 0)),
    min_margin_db: +Math.min(...cmp.map((c) => (c.psnr ?? 0) - Math.max(...(c.near.length ? c.near : [0])))).toFixed(2),
    bad: bad.map((c) => ({ frame: c.id, join: joins.has(c.id), ...c })),
  });

  // Determinism: re-render one segment and compare bytes (NVENC is deterministic for identical frames).
  if (a.qa !== 'quick' && man.segments.length) {
    const s = man.segments[Math.min(man.segments.length - 1, Math.floor(rnd(99) * man.segments.length))];
    const redo = path.join(qaDir, `redo_v_${pad(s.k)}.mp4`);
    await electron(root, [...common(), '--start', String(s.start), '--count', String(s.count), '--out', redo, '--codec', codec, ...cqArgs]);
    const h = await sha256File(redo);
    ok('determinism', h === s.video.sha256, { segment: s.k, identical_bytes: h === s.video.sha256 });
    fs.rmSync(redo, { force: true });
  }

  // Loudness (ffmpeg ebur128 with true peak) of what gets uploaded (AAC) and of the lossless master.
  const ebu = (f) => {
    const r = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', f, '-af', 'ebur128=peak=true', '-f', 'null', '-'], { maxBuffer: 1 << 28 });
    const s = r.stderr.toString().split('Summary:').pop();
    const num = (re) => { const m = re.exec(s); return m ? Number(m[1]) : null; };
    return { lufs: num(/I:\s+(-?[\d.]+) LUFS/), lra: num(/LRA:\s+([\d.]+) LU/), true_peak: num(/Peak:\s+(-?[\d.]+|-inf) dBFS/) };
  };
  const amb = ebu(path.join(dir, 'ambience.m4a')), ambF = ebu(path.join(dir, 'ambience.flac'));
  ok('loudness_ambience', amb.lufs >= -21.5 && amb.lufs <= -18.5 && amb.true_peak <= -1.5, { aac: amb, flac: ambF, target: '-20 LUFS (+-1.5), true peak <= -1.5 dBTP' });
  if (withMusic) {
    const mus = ebu(path.join(dir, 'music_mix.m4a'));
    // The ambience (lowered by ambience_db under music) and the music bus added up, as tools/music.py mix_target.
    const mc = JSON.parse(fs.readFileSync(path.join(dir, 'music_plan.json'), 'utf8')).cfg;
    const want = 10 * Math.log10(10 ** (((tl.audio?.lufs ?? -20) + (mc.ambience_db ?? 0)) / 10) + 10 ** (mc.lufs / 10));
    ok('loudness_music', mus.lufs !== null && Math.abs(mus.lufs - want) <= 1.5 && mus.true_peak <= -1.5,
      { aac: mus, target: `${(want - 1.5).toFixed(1)}..${(want + 1.5).toFixed(1)} LUFS, true peak <= -1.5 dBTP` });
  }
  // Thunder on the final encoded audio: short-term rise over the bed per strike (GOALS: <= ~6 dB).
  await run(py, [path.join(root, 'tools', 'render_qa.py'), 'thunder', path.join(dir, 'ambience.m4a'), path.join(dir, 'timeline.json'), String(R0), String(L), path.join(qaDir, 'thunder.json')]);
  const th = JSON.parse(fs.readFileSync(path.join(qaDir, 'thunder.json'), 'utf8'));
  const thMax = th.length ? Math.max(...th.map((x) => x.over_bed_db)) : null;
  const near = th.filter((x) => x.type !== 'farflash'), far = th.filter((x) => x.type === 'farflash');
  const mx = (a) => (a.length ? Math.max(...a.map((x) => x.over_bed_db)) : null);
  ok('thunder', thMax === null || thMax <= 6, { strikes: near.length, max_over_bed_db: mx(near), far_rumbles: far.length, far_max_over_bed_db: mx(far), limit_db: 6 });
  const vd = Number(probe(['-select_streams', 'v:0', '-show_entries', 'stream=duration', '-of', 'csv=p=0', path.join(dir, 'master.mp4')]));
  const ad = Number(probe(['-select_streams', 'a:0', '-show_entries', 'stream=duration', '-of', 'csv=p=0', path.join(dir, 'master.mp4')]));
  ok('av_sync', Math.abs(vd - L) < 0.05 && Math.abs(ad - L) < 0.05, { video_s: vd, audio_s: ad, expected_s: L });
  // What the layers warned about while drawing (a critter path end in plain sight, a missing lamp): a defect to fix. A
  // shader compiler's note (D3D's precision warning X4122 on the voxel scenes) is the driver's, not the scene's.
  const compilerNote = (m) => m.level === 'warning' && /^THREE\.WebGLProgram: Program Info Log:/.test(m.text) && !/\berror\b/i.test(m.text);
  const warned = (man.page ?? []).filter((m) => m.level !== 'info' && !compilerNote(m));
  ok('page', warned.length === 0, { warnings: warned.length, messages: (man.page ?? []).length });

  // Events per hour (of this render's window) and render stats.
  const hours = Math.ceil(L / 3600);
  const ev = {};
  for (const e of tl.events) {
    if (e.t < R0 || e.t >= R0 + L) continue;
    ev[e.type] ??= Array(hours).fill(0);
    ev[e.type][Math.min(hours - 1, Math.floor((e.t - R0) / 3600))]++;
  }
  const size = (f) => (fs.existsSync(f) ? fs.statSync(f).size : 0);
  const vsec = man.segments.reduce((n, s) => n + s.video.sec, 0), asec = man.segments.reduce((n, s) => n + (s.audio?.sec ?? 0), 0);
  const pet = Array.isArray(tl.pet) ? tl.pet : tl.pet?.events ?? [];
  R.events = { per_hour: ev, pet_motions: pet.filter((p) => p.t >= R0 && p.t < R0 + L).length };
  R.stats = {
    video_render_s: +vsec.toFixed(0), video_fps: +(frames / vsec).toFixed(1), audio_cpu_s: +asec.toFixed(0),
    master_gb: +(size(path.join(dir, 'master.mp4')) / 1e9).toFixed(2),
    video_mbps: +((man.segments.reduce((n, s) => n + s.video.bytes, 0) * 8) / L / 1e6).toFixed(1),
  };
  R.pass = Object.values(R.checks).every((c) => c.pass);
  fs.writeFileSync(path.join(dir, 'qa.json'), JSON.stringify(R, null, 1));
  const md = [`# QA: ${man.scene} ${man.tag}`, '', `Overall: **${R.pass ? 'PASS' : 'FAIL'}**`, '', '| Check | Result | Detail |', '|---|---|---|',
    ...Object.entries(R.checks).map(([k, c]) => `| ${k} | ${c.pass ? 'PASS' : 'FAIL'} | ${JSON.stringify(Object.fromEntries(Object.entries(c).filter(([x]) => x !== 'pass' && x !== 'bad')))} |`),
    '', '## Events per hour', '', ...Object.entries(ev).map(([k, v]) => `- ${k}: ${v.join(', ')}`), '',
    ...(warned.length ? ['## Page warnings', '', ...warned.map((m) => `- ${m.level}: ${m.text} (segments ${m.segments.join(', ')})`), ''] : []),
    '## Render stats', '', ...Object.entries(R.stats).map(([k, v]) => `- ${k}: ${v}`), ''];
  fs.writeFileSync(path.join(dir, 'qa.md'), md.join('\n'));
  man.qa = { pass: R.pass, checks: Object.fromEntries(Object.entries(R.checks).map(([k, c]) => [k, c.pass])) };
  save();
  log(`QA ${R.pass ? 'PASS' : 'FAIL'} -> ${path.join(dir, 'qa.md')}`);
}
