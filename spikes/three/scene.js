// three.js spike: builds the shared benchmark scene and renders deterministic frames.
// Exposes window.spike.{init, renderFrame, run} for the Node driver (render.mjs).
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const TAU = Math.PI * 2;

// Some three.js addons (e.g. GTAO's noise texture) call Math.random(); seed it so runs are bit-identical.
Math.random = (() => {
  let s = 0x2f6b9a1d;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
})();
const fract = (v) => v - Math.floor(v);
const smooth = (v) => v * v * (3 - 2 * v);

async function loadTex(name) {
  const tex = await new THREE.TextureLoader().loadAsync(`/shared/textures/${name}.png`);
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 8;
  return tex;
}

// Box geometry with UVs in world block units so textures tile at 16 texels per block.
function addBox(target, min, max, uvOrigin = [0, 0, 0]) {
  const [x0, y0, z0] = min, [x1, y1, z1] = max;
  const [ox, oy, oz] = uvOrigin;
  const faces = [
    { n: [1, 0, 0], v: [[x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1]], uv: (p) => [-(p[2] - oz), p[1] - oy] },
    { n: [-1, 0, 0], v: [[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]], uv: (p) => [p[2] - oz, p[1] - oy] },
    { n: [0, 1, 0], v: [[x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0]], uv: (p) => [p[0] - ox, -(p[2] - oz)] },
    { n: [0, -1, 0], v: [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], uv: (p) => [p[0] - ox, p[2] - oz] },
    { n: [0, 0, 1], v: [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], uv: (p) => [p[0] - ox, p[1] - oy] },
    { n: [0, 0, -1], v: [[x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0]], uv: (p) => [-(p[0] - ox), p[1] - oy] },
  ];
  for (const f of faces) {
    const base = target.pos.length / 3;
    for (const p of f.v) {
      target.pos.push(...p);
      target.nrm.push(...f.n);
      target.uv.push(...f.uv(p));
    }
    target.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
}
function toGeometry(t) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(t.pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(t.nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(t.uv, 2));
  g.setIndex(t.idx);
  return g;
}
const emptyGeo = () => ({ pos: [], nrm: [], uv: [], idx: [] });
function boxMesh(size, material, uvOrigin) {
  const t = emptyGeo();
  const h = size.map((s) => s / 2);
  addBox(t, [-h[0], -h[1], -h[2]], h, uvOrigin ?? [-h[0], -h[1], -h[2]]);
  const m = new THREE.Mesh(toGeometry(t), material);
  m.castShadow = m.receiveShadow = true;
  return m;
}

// GPU conversion: float sRGB -> vignette -> BT.709 limited-range YUV420p, TPDF-dithered, packed
// into an RGBA8 target (W/4 x 1.5H) so one readPixels yields the exact yuv420p byte stream.
const yuvFrag = /* glsl */ `
precision highp float;
uniform sampler2D src;
uniform ivec2 size;
uniform float frame;
uniform float vignette;
uniform float ditherAnimated;
out vec4 outColor;

float hash(vec3 p) {
  p = fract(p * vec3(0.1031, 0.1030, 0.0973));
  p += dot(p, p.yxz + 33.33);
  return fract((p.x + p.y) * p.z);
}
vec3 px(int x, int y) {
  vec3 c = clamp(texelFetch(src, ivec2(x, size.y - 1 - y), 0).rgb, 0.0, 1.0);
  vec2 uv = (vec2(x, y) + 0.5) / vec2(size) - 0.5;
  uv.x *= float(size.x) / float(size.y);
  return c * mix(1.0, smoothstep(1.25, 0.25, length(uv)), vignette);
}
float q(float v, vec3 seed) {
  float f = frame * ditherAnimated;
  float d = hash(seed + vec3(0.0, 0.0, f)) + hash(seed + vec3(17.0, 31.0, f + 7.0)) - 1.0;
  return clamp(floor(v + d + 0.5), 0.0, 255.0) / 255.0;
}
void main() {
  ivec2 o = ivec2(gl_FragCoord.xy);
  int W = size.x, H = size.y;
  vec4 res;
  if (o.y < H) {
    for (int k = 0; k < 4; k++) {
      int x = o.x * 4 + k;
      float y = 16.0 + 219.0 * dot(px(x, o.y), vec3(0.2126, 0.7152, 0.0722));
      res[k] = q(y, vec3(x, o.y, 1.0));
    }
  } else {
    int r = o.y - H;
    bool isV = r >= H / 4;
    if (isV) r -= H / 4;
    for (int k = 0; k < 4; k++) {
      int b = o.x * 4 + k;
      int cr = 2 * r + (b >= W / 2 ? 1 : 0);
      int cc = b % (W / 2);
      vec3 c = 0.25 * (px(2 * cc, 2 * cr) + px(2 * cc + 1, 2 * cr) + px(2 * cc, 2 * cr + 1) + px(2 * cc + 1, 2 * cr + 1));
      float yl = dot(c, vec3(0.2126, 0.7152, 0.0722));
      float v = isV ? 128.0 + 224.0 * (c.r - yl) / 1.5748 : 128.0 + 224.0 * (c.b - yl) / 1.8556;
      res[k] = q(v, vec3(cc, cr, isV ? 3.0 : 2.0));
    }
  }
  outColor = res;
}`;

class Spike {
  async init(opts = {}) {
    const S = (this.S = await (await fetch('/shared/scene.json')).json());
    this.opts = { width: S.width, height: S.height, ao: true, bloom: true, msaa: 4, shadows: true, ditherAnimated: false, ...opts };
    const { width: W, height: H } = this.opts;

    const canvas = document.createElement('canvas');
    document.body.appendChild(canvas);
    const renderer = (this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' }));
    renderer.setPixelRatio(1);
    renderer.setSize(W, H, false);
    renderer.toneMapping = THREE.AgXToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.shadowMap.enabled = this.opts.shadows;
    renderer.shadowMap.type = THREE.PCFShadowMap;

    const scene = (this.scene = new THREE.Scene());
    scene.fog = new THREE.FogExp2(S.palette.fog, 0.022);
    const cam = (this.camera = new THREE.PerspectiveCamera(S.camera.fovY, W / H, 0.05, 400));
    cam.position.set(...S.camera.pos);
    cam.lookAt(...S.camera.target);

    const texNames = ['floor_planks', 'wall_plaster', 'wood_dark', 'rug', 'fur', 'shade', 'facade', 'facade_emit'];
    const tex = Object.fromEntries(await Promise.all(texNames.map(async (n) => [n, await loadTex(n)])));
    for (const n of texNames) if (n !== 'facade_emit') tex[n].colorSpace = THREE.SRGBColorSpace;
    tex.facade_emit.colorSpace = THREE.SRGBColorSpace;

    // Static boxes merged per material.
    const groups = new Map();
    for (const b of S.boxes) {
      const key = b.tex ?? `color:${b.color}`;
      if (!groups.has(key)) groups.set(key, { b, geo: emptyGeo() });
      addBox(groups.get(key).geo, b.min, b.max);
    }
    for (const [key, { b, geo }] of groups) {
      let mat;
      if (!b.tex) mat = new THREE.MeshBasicMaterial({ color: b.color, fog: false });
      else {
        mat = new THREE.MeshStandardMaterial({ map: tex[b.tex], roughness: 0.92, metalness: 0 });
        if (b.emissive) {
          mat.emissive = new THREE.Color(b.emissiveColor ?? '#ffffff');
          mat.emissiveMap = tex[b.emissiveTex ?? b.tex];
          mat.emissiveIntensity = b.emissive;
        }
      }
      const mesh = new THREE.Mesh(toGeometry(geo), mat);
      mesh.castShadow = key !== 'facade' && key !== 'shade';
      mesh.receiveShadow = true;
      scene.add(mesh);
    }

    // Lights: warm lamp (point, soft shadows), dim cool fill through the window, faint warm ambient.
    const lamp = new THREE.PointLight(S.palette.lampLight, 9, S.lamp.range, 1.6);
    lamp.position.set(...S.lamp.pos);
    lamp.castShadow = this.opts.shadows;
    lamp.shadow.mapSize.set(2048, 2048);
    lamp.shadow.radius = 6;
    lamp.shadow.bias = -0.002;
    lamp.shadow.intensity = 0.8;
    scene.add(lamp);
    const win = new THREE.SpotLight(S.palette.windowLight, 60, 40, 0.55, 0.8, 1.5);
    win.position.set(4, 7, -9);
    win.target.position.set(4, 0, 4);
    win.castShadow = this.opts.shadows;
    win.shadow.mapSize.set(2048, 2048);
    win.shadow.radius = 4;
    scene.add(win, win.target);
    scene.add(new THREE.HemisphereLight('#6a4428', '#24140a', 0.6));

    // Glass + drops.
    const g = S.window;
    const glass = new THREE.Mesh(
      new THREE.PlaneGeometry(g.x[1] - g.x[0], g.y[1] - g.y[0]),
      new THREE.MeshStandardMaterial({ color: S.palette.glassTint, transparent: true, opacity: 0.18, roughness: 0.15, depthWrite: false }),
    );
    glass.position.set((g.x[0] + g.x[1]) / 2, (g.y[0] + g.y[1]) / 2, g.glassZ);
    scene.add(glass);
    // Explicit transparent draw order: three otherwise sorts InstancedMeshes by a bounding sphere computed
    // lazily on first render, which makes the output depend on the start frame.
    glass.renderOrder = 2;
    const dropMat = new THREE.MeshStandardMaterial({ color: '#9fa6c0', transparent: true, opacity: 0.35, roughness: 0.1, emissive: '#2a2438', depthWrite: false });
    const beads = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1 / 32), dropMat, S.drops.beads.length);
    const m4 = new THREE.Matrix4();
    S.drops.beads.forEach(([x, y, s], i) => beads.setMatrixAt(i, m4.compose(new THREE.Vector3(x, y, g.glassZ + 0.03), new THREE.Quaternion(), new THREE.Vector3(s, s, 1))));
    beads.renderOrder = 3;
    scene.add(beads);
    this.slide = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1 / 32), dropMat, S.drops.slide.length);
    this.slide.frustumCulled = false;
    this.slide.renderOrder = 4;
    scene.add(this.slide);

    // Rain: chunky 1-texel streaks.
    this.rain = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1 / 16, 1, 1 / 16),
      new THREE.MeshBasicMaterial({ color: S.palette.rain, transparent: true, opacity: 0.38, depthWrite: false }),
      S.rain.streaks.length,
    );
    this.rain.frustumCulled = false;
    this.rain.renderOrder = 1;
    scene.add(this.rain);

    // Ceiling fan.
    const fan = (this.fan = new THREE.Group());
    const wood = new THREE.MeshStandardMaterial({ map: tex.wood_dark, roughness: 0.85 });
    const rod = boxMesh([0.0625, S.fan.drop, 0.0625], wood);
    rod.position.y = -S.fan.drop / 2;
    const motor = boxMesh([0.3, 0.18, 0.3], wood);
    motor.position.y = -S.fan.drop;
    this.fanBlades = new THREE.Group();
    this.fanBlades.position.y = -S.fan.drop;
    for (let i = 0; i < S.fan.blades; i++) {
      const arm = new THREE.Group();
      arm.rotation.y = (i / S.fan.blades) * TAU;
      const blade = boxMesh(S.fan.blade, wood);
      blade.position.x = S.fan.blade[0] / 2 + 0.12;
      arm.add(blade);
      this.fanBlades.add(arm);
    }
    fan.add(rod, motor, this.fanBlades);
    fan.position.set(...S.fan.pos);
    scene.add(fan);

    // Pet.
    const furMat = new THREE.MeshStandardMaterial({ map: tex.fur, roughness: 0.95 });
    this.pet = new THREE.Group();
    this.pet.position.set(...S.pet.origin);
    this.pet.rotation.y = S.pet.yaw;
    this.petParts = {};
    for (const p of S.pet.parts) {
      const m = boxMesh(p.size, furMat);
      this.petParts[p.name] = m;
      this.pet.add(m);
    }
    scene.add(this.pet);

    // Post: render (MSAA) -> GTAO -> bloom -> tone map/sRGB (float) -> YUV pack.
    const composer = (this.composer = new EffectComposer(renderer));
    composer.setPixelRatio(1);
    composer.setSize(W, H);
    composer.renderTarget1.samples = composer.renderTarget2.samples = this.opts.msaa;
    composer.renderToScreen = false;
    composer.addPass(new RenderPass(scene, cam));
    if (this.opts.ao) {
      const ao = new GTAOPass(scene, cam, W, H);
      ao.blendIntensity = 0.85;
      composer.addPass(ao);
    }
    if (this.opts.bloom) composer.addPass(new UnrealBloomPass(new THREE.Vector2(W, H), 0.6, 0.65, 0.6));
    composer.addPass(new OutputPass());

    this.yuvTarget = new THREE.WebGLRenderTarget(W / 4, (H * 3) / 2, { type: THREE.UnsignedByteType, depthBuffer: false });
    this.yuvMat = new THREE.RawShaderMaterial({
      glslVersion: THREE.GLSL3,
      uniforms: { src: { value: null }, size: { value: new THREE.Vector2(W, H) }, frame: { value: 0 }, vignette: { value: 0.55 }, ditherAnimated: { value: this.opts.ditherAnimated ? 1 : 0 } },
      vertexShader: 'in vec3 position; void main(){ gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: yuvFrag,
    });
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.yuvMat);
    this.quadScene = new THREE.Scene();
    this.quadScene.add(this.quad);
    this.quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.yuvBytes = (W * H * 3) / 2;

    const gl = renderer.getContext();
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    return {
      renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      three: THREE.REVISION,
      yuvBytes: this.yuvBytes,
    };
  }

  update(frame) {
    const S = this.S;
    const L = S.loopSeconds;
    const loopFrames = Math.round(L * S.fps);
    const t = (frame % loopFrames) / S.fps;
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3();

    this.fanBlades.rotation.y = -TAU * S.fan.revsPerLoop * (t / L);

    const { yTop, yBottom, tilt } = S.rain;
    q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), tilt);
    S.rain.streaks.forEach(([x, z, ph, cyc, len], i) => {
      const k = fract(ph + (cyc * t) / L);
      const y = yTop - k * (yTop - yBottom);
      v.set(x + (yTop - y) * Math.tan(tilt), y, z);
      this.rain.setMatrixAt(i, m4.compose(v, q, sc.set(1, len, 1)));
    });
    this.rain.instanceMatrix.needsUpdate = true;

    const g = S.window;
    S.drops.slide.forEach(([x, ph, cyc, s], i) => {
      const k = fract(ph + (cyc * t) / L);
      const y = g.y[1] - 0.1 - smooth(k) * (g.y[1] - g.y[0] - 0.2);
      this.slide.setMatrixAt(i, m4.compose(v.set(x, y, g.glassZ + 0.035), q.identity(), sc.set(s, s * 1.6, 1)));
    });
    this.slide.instanceMatrix.needsUpdate = true;

    // Pet pose blend: 0 = lie, 1 = sit.
    let s = 0;
    const sched = S.pet.schedule;
    for (const [a, b, from, to] of sched) {
      if (t >= a && t < b) { const k = smooth((t - a) / (b - a)); s = from === 'lie' ? k : 1 - k; break; }
      if (t >= b) s = to === 'sit' ? 1 : 0;
    }
    const euler = (rot) => { const e = [0, 0, 0]; e['xyz'.indexOf(rot[0])] = rot[1]; return e; };
    for (const p of S.pet.parts) {
      const m = this.petParts[p.name];
      if (p.follow) continue;
      const ea = euler(p.lie.rot), eb = euler(p.sit.rot);
      const e = ea.map((a, i) => a + (eb[i] - a) * s);
      if (p.look) e[1] += p.look * s * Math.sin((TAU * t) / L);
      m.position.set(...p.lie.p.map((a, i) => a + (p.sit.p[i] - a) * s));
      if (p.breathe) m.position.y += p.breathe * Math.sin((TAU * 4 * t) / L);
      m.rotation.set(e[0], e[1], e[2], 'XYZ');
    }
    for (const p of S.pet.parts) {
      if (!p.follow) continue;
      const head = this.petParts[p.follow], m = this.petParts[p.name];
      m.position.copy(new THREE.Vector3(...p.offset).applyEuler(head.rotation).add(head.position));
      m.rotation.copy(head.rotation);
    }
  }

  renderFrame(frame) {
    this.update(frame);
    this.composer.render();
    this.yuvMat.uniforms.src.value = this.composer.readBuffer.texture;
    this.yuvMat.uniforms.frame.value = frame;
    this.renderer.setRenderTarget(this.yuvTarget);
    this.renderer.render(this.quadScene, this.quadCam);
    this.renderer.setRenderTarget(null);
  }

  // Splits per-frame cost: render only, render + readback, render + readback + websocket send.
  async bench(n, wsUrl) {
    const gl = this.renderer.getContext();
    const W4 = this.yuvTarget.width, H15 = this.yuvTarget.height;
    const buf = new Uint8Array(this.yuvBytes);
    const time = async (fn) => { const t = performance.now(); for (let i = 0; i < n; i++) await fn(i); gl.finish(); return +((performance.now() - t) / n).toFixed(2); };
    const out = {};
    out.renderMs = await time((i) => { this.renderFrame(i); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4)); });
    out.syncReadMs = await time((i) => { this.renderFrame(i); this.renderer.readRenderTargetPixels(this.yuvTarget, 0, 0, W4, H15, buf); });
    out.asyncReadMs = await time(async (i) => { this.renderFrame(i); await this.renderer.readRenderTargetPixelsAsync(this.yuvTarget, 0, 0, W4, H15, buf); });
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    await new Promise((res) => { ws.onopen = res; });
    out.sendOnlyMs = await time(async () => { ws.send(buf); while (ws.bufferedAmount > 0) await new Promise((r) => setTimeout(r, 0)); });
    ws.close();
    out.fetchPostMs = await time(async () => { await fetch('/sink', { method: 'POST', body: buf }); });
    const socks = await Promise.all([0, 1, 2, 3].map(() => new Promise((res) => { const s = new WebSocket(wsUrl); s.binaryType = 'arraybuffer'; s.onopen = () => res(s); })));
    out.ws4Ms = +((await time(async () => {
      for (const s of socks) s.send(buf);
      while (socks.some((s) => s.bufferedAmount > 0)) await new Promise((r) => setTimeout(r, 0));
    })) / 4).toFixed(2);
    socks.forEach((s) => s.close());
    out.fetch4Ms = +((await time(async () => { await Promise.all([0, 1, 2, 3].map(() => fetch('/sink', { method: 'POST', body: buf }))); })) / 4).toFixed(2);
    return out;
  }

  // Electron path: render [start, start+count) and write frames straight into ffmpeg via Node.
  async runNode(start, count, o) {
    const { createSink } = window.require(o.sinkPath);
    const sink = createSink({ W: this.opts.width, H: this.opts.height, fps: this.S.fps, ...o });
    const W4 = this.yuvTarget.width, H15 = this.yuvTarget.height;
    const pool = [0, 1, 2].map(() => new Uint8Array(this.yuvBytes));
    const writes = [null, null, null];
    let prev = null;
    const t0 = performance.now();
    for (let i = 0; i < count; i++) {
      const slot = i % 3;
      if (writes[slot]) await writes[slot];
      this.renderFrame(start + i);
      if (o.readMode === 'async') {
        const read = this.renderer.readRenderTargetPixelsAsync(this.yuvTarget, 0, 0, W4, H15, pool[slot]);
        if (prev) { await prev.read; writes[prev.slot] = sink.write(prev.frame, pool[prev.slot]); }
        prev = { read, slot, frame: start + i };
      } else {
        this.renderer.readRenderTargetPixels(this.yuvTarget, 0, 0, W4, H15, pool[slot]);
        writes[slot] = sink.write(start + i, pool[slot]);
      }
    }
    if (prev) { await prev.read; writes[prev.slot] = sink.write(prev.frame, pool[prev.slot]); }
    await Promise.all(writes);
    const renderMs = performance.now() - t0;
    const hashes = await sink.close();
    return { frames: count, renderMs, totalMs: performance.now() - t0, hashes };
  }

  // Renders [start, start+count) and streams packed YUV frames to the driver over a WebSocket.
  async run(start, count, wsUrl) {
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const W4 = this.yuvTarget.width, H15 = this.yuvTarget.height;
    const pool = [0, 1, 2].map(() => new Uint8Array(this.yuvBytes));
    let pending = null;
    const t0 = performance.now();
    const flush = async () => {
      if (!pending) return;
      const buf = await pending;
      while (ws.bufferedAmount > this.yuvBytes * 3) await new Promise((r) => setTimeout(r, 1));
      ws.send(buf);
    };
    for (let i = 0; i < count; i++) {
      this.renderFrame(start + i);
      const read = this.renderer.readRenderTargetPixelsAsync(this.yuvTarget, 0, 0, W4, H15, pool[i % 3]);
      await flush();
      pending = read;
    }
    await flush();
    while (ws.bufferedAmount > 0) await new Promise((r) => setTimeout(r, 2));
    const ms = performance.now() - t0;
    await new Promise((r) => { ws.onclose = r; ws.close(); });
    return { frames: count, ms };
  }
}

window.spike = new Spike();
