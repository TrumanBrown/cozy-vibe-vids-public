// ffmpeg sinks used from the renderer process: encoded video from packed yuv420p, and PNG stills from RGBA.
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const COLOR_TAGS = ['-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709'];
const CODECS = {
  hevc_nvenc: ['-c:v', 'hevc_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-maxrate', '80M', '-bufsize', '160M', '-tag:v', 'hvc1'],
  h264_nvenc: ['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '18', '-b:v', '0', '-maxrate', '100M', '-bufsize', '200M', '-profile:v', 'high'],
};

// How an ffmpeg run ended: null when it worked, else why not (its own message is already on stderr). Kept from the
// spawn on, so a run that ends early is still seen; a failed encode (no NVENC, a full disk) fails the render instead
// of leaving a broken file behind.
function ended(p, file) {
  p.stdin.on('error', () => {});   // a write after ffmpeg quit: reported through the exit below
  return new Promise((resolve) => {
    p.on('error', (e) => resolve(e.code === 'ENOENT' ? 'ffmpeg is not on PATH (docs/SETUP.md)' : `ffmpeg: ${e.message}`));
    p.on('close', (code, sig) => resolve(code === 0 ? null : `ffmpeg exited with ${code ?? sig} writing ${file}`));
  });
}

function createVideoSink({ W, H, fps, out, codec = 'hevc_nvenc', hash = false, cq }) {
  if (!CODECS[codec]) throw new Error(`unknown codec ${codec} (use ${Object.keys(CODECS).join(' or ')})`);
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  const enc = [...CODECS[codec]];
  if (cq && enc.includes('-cq')) enc[enc.indexOf('-cq') + 1] = String(cq);   // quality override (lower = better/bigger)
  const ff = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', `${W}x${H}`, '-r', String(fps),
    ...COLOR_TAGS, '-i', '-', ...enc, ...COLOR_TAGS, '-movflags', '+faststart', out], { stdio: ['pipe', 'ignore', 'inherit'] });
  const done = ended(ff, out);
  const hashes = {};
  return {
    write(frame, u8) {
      const buf = Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength);
      if (hash) hashes[frame] = crypto.createHash('sha256').update(buf).digest('hex');
      return new Promise((resolve, reject) => ff.stdin.write(buf, (err) => (err ? done.then((why) => reject(new Error(why ?? err.message))) : resolve())));
    },
    async close() {
      ff.stdin.end();
      const why = await done;
      if (why) throw new Error(why);
      return hashes;
    },
  };
}

function createStillWriter({ W, H }) {
  const jobs = [];
  return {
    write(file, u8) {
      fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
      const p = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-i', '-',
        '-vf', 'format=rgb24', '-frames:v', '1', file], { stdio: ['pipe', 'ignore', 'inherit'] });
      const job = ended(p, file).then((why) => { if (why) throw new Error(why); });
      job.catch(() => {});   // reported by close()
      jobs.push(job);
      p.stdin.end(Buffer.from(u8));
      return Promise.resolve();
    },
    async close() { await Promise.all(jobs); },
  };
}

module.exports = { createVideoSink, createStillWriter };
