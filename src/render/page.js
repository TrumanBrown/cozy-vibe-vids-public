// Renderer page (runs in Electron's renderer process with Node integration, local content only).
import { Engine } from '../engine/engine.js';

class Page {
  async init(scenePath, opts) {
    try {
      const mod = await import(`/${scenePath}/scene.js`);
      this.engine = new Engine();
      const canvas = document.createElement('canvas');
      document.body.appendChild(canvas);
      return await this.engine.init(mod, { ...opts, canvas });
    } catch (e) {
      // errors that cross into the main process lose their message: report it here first
      console.error(`init failed: ${e?.stack ?? e?.message ?? (e?.type ? `${e.type} event on ${e.target?.src ?? e.target?.url ?? e.target}` : e)}`);
      throw e;
    }
  }

  // Writes guide images for AI enhancement: <prefix>_color.rgba (RGBA8, top-down) and
  // <prefix>_depth.f32 (Float32 linear distance, bottom-up rows) + a JSON sidecar.
  async guides(frame, prefix) {
    const fs = window.require('fs');
    const e = this.engine;
    const rgb = new Uint8Array(e.rgbBytes);
    await e.prefetch(frame);
    e.render(frame, 1);
    e.readSync(1, rgb);
    fs.writeFileSync(`${prefix}_color.rgba`, Buffer.from(rgb));
    const depth = new Float32Array(e.W * e.H);
    const info = e.renderDepth(frame, depth);
    fs.writeFileSync(`${prefix}_depth.f32`, Buffer.from(depth.buffer));
    fs.writeFileSync(`${prefix}_guides.json`, JSON.stringify({ width: e.W, height: e.H, frame, ...info, camera: { pos: e.camera.position.toArray(), fov: e.camera.fov } }));
    return { ok: true };
  }

  // Renders each listed frame as an RGB still (PNG via ffmpeg).
  async stills(frames, o) {
    const { createStillWriter } = window.require(o.sinkPath);
    const e = this.engine;
    const w = createStillWriter({ W: e.W, H: e.H });
    const buf = new Uint8Array(e.rgbBytes);
    const t0 = performance.now();
    for (const f of frames) {
      await e.prefetch(f);
      e.render(f, 1);
      e.readSync(1, buf);
      await w.write(o.pattern.replace('{frame}', String(f).padStart(6, '0')), buf);
    }
    await w.close();
    return { frames: frames.length, ms: performance.now() - t0 };
  }

  // Renders [start, start+count) into an encoded video via ffmpeg (yuv420p from the GPU).
  async video(start, count, o) {
    const { createVideoSink } = window.require(o.sinkPath);
    const e = this.engine;
    const sink = createVideoSink({ W: e.W, H: e.H, fps: e.fps, out: o.out, codec: o.codec, hash: o.hash, cq: o.cq });
    const pool = [0, 1, 2].map(() => new Uint8Array(e.yuvBytes));
    const writes = [null, null, null];
    let prev = null;
    const t0 = performance.now();
    for (let i = 0; i < count; i++) {
      const slot = i % 3;
      if (writes[slot]) await writes[slot];
      await e.prefetch(start + i);
      e.render(start + i, 0);
      const read = e.readAsync(0, pool[slot]);
      if (prev) { await prev.read; writes[prev.slot] = sink.write(prev.frame, pool[prev.slot]); }
      prev = { read, slot, frame: start + i };
      if (o.progress && (i + 1) % 150 === 0) console.log(`progress ${i + 1}/${count} ${((i + 1) / ((performance.now() - t0) / 1000)).toFixed(1)} fps`);
    }
    if (prev) { await prev.read; writes[prev.slot] = sink.write(prev.frame, pool[prev.slot]); }
    await Promise.all(writes);
    const hashes = await sink.close();
    return { frames: count, ms: performance.now() - t0, hashes };
  }
}

window.cvv = new Page();
