// Frame sink used from the Electron renderer (Node-enabled): pipes packed yuv420p frames into
// ffmpeg, hashes frames, and writes requested stills as PNG.
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

function encodeArgs({ W, H, fps, codec, out }) {
  return ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', `${W}x${H}`, '-r', String(fps),
    '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-i', '-',
    '-c:v', codec, '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-maxrate', '80M', '-bufsize', '160M',
    ...(codec === 'hevc_nvenc' ? ['-tag:v', 'hvc1'] : []), '-movflags', '+faststart', out];
}

function createSink({ W, H, fps = 30, out, codec = 'hevc_nvenc', hash = false, stills = [], stillsDir, ref = null, dumpDir = null }) {
  let ff = null;
  if (out) {
    fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
    ff = spawn('ffmpeg', encodeArgs({ W, H, fps, codec, out }), { stdio: ['pipe', 'ignore', 'inherit'] });
  }
  const stillSet = new Set(stills);
  if (stillSet.size) fs.mkdirSync(stillsDir, { recursive: true });
  const hashes = {};
  const jobs = [];
  return {
    // Resolves once the buffer has been handed to the OS and may be reused.
    write(frame, u8) {
      const buf = Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength);
      if (hash) hashes[frame] = crypto.createHash('sha256').update(buf).digest('hex');
      if (ref && ref[frame] && ref[frame] !== hashes[frame] && dumpDir) {
        fs.mkdirSync(dumpDir, { recursive: true });
        fs.writeFileSync(path.join(dumpDir, `mismatch_${frame}.yuv`), buf);
      }
      if (dumpDir && !ref) { fs.mkdirSync(dumpDir, { recursive: true }); fs.writeFileSync(path.join(dumpDir, `frame_${frame}.yuv`), buf); }
      if (stillSet.has(frame)) {
        const file = path.join(stillsDir, `frame_${String(frame).padStart(5, '0')}.png`);
        const p = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-s', `${W}x${H}`, '-i', '-',
          '-vf', 'scale=in_color_matrix=bt709:in_range=limited:out_range=full,format=rgb24', '-frames:v', '1', file]);
        p.stdin.end(Buffer.from(buf));
        jobs.push(new Promise((r) => p.on('close', r)));
      }
      if (!ff) return Promise.resolve();
      return new Promise((resolve, reject) => ff.stdin.write(buf, (err) => (err ? reject(err) : resolve())));
    },
    async close() {
      if (ff) { ff.stdin.end(); await new Promise((r) => ff.on('close', r)); }
      await Promise.all(jobs);
      return hashes;
    },
  };
}

module.exports = { createSink, encodeArgs };
