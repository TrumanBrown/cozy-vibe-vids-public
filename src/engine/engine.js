// Engine runtime: turns a scene module into a pure frame function, render(frameIndex) -> pixels.
// Time is always frameIndex / fps. Scenes register animations with ctx.animate((t, frame) => ...).
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Rng, seedMathRandom } from './rng.js';
import { outputFrag } from './output.glsl.js';
import { buildTimeline } from '../library/timeline.js';

// GTAO's normal/depth pre-pass would include rain, glass, haze cards, etc.; hide them for that pass.
class SceneGTAOPass extends GTAOPass {
  _overrideVisibility() {
    super._overrideVisibility();
    const cache = this._visibilityCache;
    this.scene.traverse((o) => {
      if (o.visible && (o.userData.noAO || (o.isMesh && o.material?.transparent))) { o.visible = false; cache.push(o); }
    });
  }
}

const BLOOM_BASE_HEIGHT = 1080; // bloom runs at a fixed resolution so previews match 4K output

export const DEFAULT_POST = {
  exposure: 1.0,
  toneMapping: 'agx',
  ao: { enabled: true, radius: 0.6, thickness: 1.0, distanceExponent: 1.5, scale: 1.0, samples: 16, blend: 1.0 },
  bloom: { enabled: true, strength: 0.55, radius: 0.55, threshold: 0.75 },
  grade: { lift: [0, 0, 0], gamma: [1, 1, 1], gain: [1, 1, 1], saturation: 1.0, contrast: 1.0 },
  vignette: 0.45,
  fog: null,
};

function merge(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b ?? {})) out[k] = v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object' ? merge(a[k], v) : v;
  return out;
}

async function loadVoxel() {
  const { Builder, setTextureSeed, pendingLoads } = await import('./builder.js');
  const { Foliage } = await import('./foliage.js');
  return { Builder, setTextureSeed, pendingLoads, Foliage };
}

export class Engine {
  async init(sceneModule, { width = 3840, height = 2160, seed, canvas, camera, ssaa, params = {}, duration } = {}) {
    const S = (this.def = sceneModule.default ?? sceneModule);
    this.seed = seed ?? S.seed ?? 1;
    // The voxel builder and its foliage, the code-built look the plates replaced on 2026-10-15, load only for a scene
    // without a plate (treetop, lakeside, loft); a plate scene never imports or builds them. Loaded before the seeding,
    // as the static imports were.
    const voxel = S.plate ? null : await loadVoxel();
    seedMathRandom(this.seed ^ 0x5bd1e995);
    voxel?.setTextureSeed(this.seed);
    this.W = width; this.H = height;
    const SS = (this.ssaa = Math.max(1, Math.round(ssaa ?? S.ssaa ?? 1)));
    const IW = width * SS, IH = height * SS;
    this.fps = S.fps ?? 30;
    this.loopSeconds = S.loopSeconds ?? 60;
    const post = (this.post = merge(DEFAULT_POST, typeof S.post === 'function' ? S.post(params) : S.post));

    const renderer = (this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', preserveDrawingBuffer: false }));
    renderer.setPixelRatio(1);
    renderer.setSize(IW, IH, false);
    renderer.toneMapping = { agx: THREE.AgXToneMapping, aces: THREE.ACESFilmicToneMapping, neutral: THREE.NeutralToneMapping, none: THREE.NoToneMapping }[post.toneMapping];
    renderer.toneMappingExposure = post.exposure;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;

    const scene = (this.scene = new THREE.Scene());
    scene.background = new THREE.Color(S.background ?? '#000000');
    if (post.fog) scene.fog = new THREE.FogExp2(post.fog.color, post.fog.density);
    const cam = (this.camera = new THREE.PerspectiveCamera(S.camera.fov, width / height, S.camera.near ?? 0.05, S.camera.far ?? 600));
    const camDef = { ...S.camera, ...(camera ?? {}) };
    cam.fov = camDef.fov;
    cam.updateProjectionMatrix();
    cam.position.set(...camDef.pos);
    cam.lookAt(...camDef.target);

    this.animations = [];
    this.prefetchers = [];
    // Event timeline for the whole video (not just this render range): previews show exactly what the
    // final render shows at the same time. params.events=off disables events (base-loop QA). `duration`
    // overrides the scene's video length (e.g. a 1 h test render gets its own 1 h timeline).
    const plateMeta = S.plate ? await fetch(`/out/plates/${S.plate}/plate.json`).then((r) => {
      if (!r.ok) throw new Error(`out/plates/${S.plate}/plate.json is missing (HTTP ${r.status}): prepare the plate first (tools/plate_prep.py <image.png> --name ${S.plate})`);
      return r.json();
    }) : null;
    this.duration = duration ?? S.duration ?? 36000;
    this.timeline = S.events && params.events !== 'off'
      ? buildTimeline(S.events, { seed: this.seed, duration: this.duration, fps: this.fps, plate: plateMeta, loopSeconds: this.loopSeconds })
      : null;
    this.loopPeriod = this.timeline?.loop?.period ?? 0;
    const b = voxel ? new voxel.Builder() : null;
    const rng = new Rng(this.seed);
    const ctx = (this.ctx = {
      THREE, scene, camera: cam, b, rng, fps: this.fps, loopSeconds: this.loopSeconds, seed: this.seed, params, timeline: this.timeline,
      // For layers that draw their own offscreen pass each frame (cat3d.js renders a 3D model into a texture).
      renderer,
      add: (o) => { scene.add(o); return o; },
      animate: (fn) => this.animations.push(fn),
      // Async work a frame needs before it renders (e.g. loading the pet clip frames it shows): awaited by the
      // page before every render(frame); fn(t, frame) gets the same time as animate.
      prefetch: (fn) => this.prefetchers.push(fn),
      light: makeLightHelpers(scene),
      // the video time of the frame being drawn; differs from the t layers get only in a looped video (timeAt)
      realTime: () => this.realTime ?? null,
      // out/plates/<plate>/plate.json, already read above (null for a scene without a plate)
      plateMeta,
    });
    const foliage = (ctx.foliage = voxel ? new voxel.Foliage(this.seed, { camera: camDef.pos }) : null);
    await S.build(ctx);
    let leafCount = 0;
    if (voxel) {
      scene.add(b.finish());
      await Promise.all(voxel.pendingLoads);
      leafCount = foliage.count;
      foliage.finish(scene);
    }

    // Environment probe: a cube capture of this very scene (at t=0), prefiltered with PMREM, gives
    // glossy reflections and an approximate bounce-light term for every standard material.
    if (S.envProbe) {
      this.update(0);
      const cubeRT = new THREE.WebGLCubeRenderTarget(S.envProbe.size ?? 256, { type: THREE.HalfFloatType });
      const cubeCam = new THREE.CubeCamera(0.05, 800, cubeRT);
      cubeCam.position.set(...S.envProbe.pos);
      cubeCam.update(renderer, scene);
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromCubemap(cubeRT.texture).texture;
      scene.environmentIntensity = S.envProbe.intensity ?? 0.5;
      pmrem.dispose();
      cubeRT.dispose();
    }

    // Post chain: scene (MSAA) -> GTAO -> bloom -> tone map + sRGB -> grade/vignette/dither -> YUV or RGB.
    const composer = (this.composer = new EffectComposer(renderer));
    composer.setPixelRatio(1);
    composer.setSize(IW, IH);
    composer.renderTarget1.samples = composer.renderTarget2.samples = S.msaa ?? 4;
    composer.renderToScreen = false;
    composer.addPass(new RenderPass(scene, cam));
    if (post.ao.enabled) {
      const ao = new SceneGTAOPass(scene, cam, IW, IH);
      ao.updateGtaoMaterial({ radius: post.ao.radius, thickness: post.ao.thickness, distanceExponent: post.ao.distanceExponent, scale: post.ao.scale, samples: post.ao.samples });
      ao.blendIntensity = post.ao.blend;
      composer.addPass(ao);
    }
    if (post.bloom.enabled) {
      const bh = BLOOM_BASE_HEIGHT, bw = Math.round((bh * width) / height);
      const bloom = new UnrealBloomPass(new THREE.Vector2(bw, bh), post.bloom.strength, post.bloom.radius, post.bloom.threshold);
      const setSize = bloom.setSize.bind(bloom);
      bloom.setSize = () => setSize(bw, bh);
      bloom.setSize();
      composer.addPass(bloom);
    }
    composer.addPass(new OutputPass());

    const g = post.grade;
    this.outMat = new THREE.RawShaderMaterial({
      glslVersion: THREE.GLSL3,
      uniforms: {
        src: { value: null }, size: { value: new THREE.Vector2(width, height) }, mode: { value: 0 }, ssaa: { value: SS },
        vignette: { value: post.vignette }, lift: { value: new THREE.Vector3(...g.lift) }, gamma: { value: new THREE.Vector3(...g.gamma) },
        gain: { value: new THREE.Vector3(...g.gain) }, saturation: { value: g.saturation }, contrast: { value: g.contrast },
        pixel: { value: 0 }, pixelOrigin: { value: new THREE.Vector2() },
      },
      vertexShader: 'in vec3 position; void main(){ gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: outputFrag,
      depthTest: false, depthWrite: false,
    });
    this.quadScene = new THREE.Scene();
    this.quadScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.outMat));
    // Pixel-art grid: the scene's own, or the plate's (plate_prep pixelize writes it to plate.json); in 4K px.
    const pix = S.pixel === 'plate' ? plateMeta?.pixel : S.pixel;
    if (pix?.cell) {
      this.outMat.uniforms.pixel.value = pix.cell * width / 3840;
      this.outMat.uniforms.pixelOrigin.value.set(...pix.origin.map((v) => v * width / 3840));
    }
    this.quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.yuvTarget = new THREE.WebGLRenderTarget(width / 4, (height * 3) / 2, { depthBuffer: false });
    this.rgbTarget = new THREE.WebGLRenderTarget(width, height, { depthBuffer: false });
    this.yuvBytes = (width * height * 3) / 2;
    this.rgbBytes = width * height * 4;

    const gl = renderer.getContext();
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    let tris = 0;
    scene.traverse((o) => { if (o.isMesh && o.geometry.index) tris += (o.geometry.index.count / 3) * (o.isInstancedMesh ? o.count : 1); });
    return { renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'unknown', three: THREE.REVISION, triangles: tris, seed: this.seed, leaves: leafCount, ssaa: SS };
  }

  timeAt(frame) {
    // Pixel-art scenes animate on a stepped clock (e.g. 12 fps, like hand-made sprite animation).
    const af = this.def.animFps;
    let t = af ? Math.floor((frame / this.fps) * af + 1e-6) / af : frame / this.fps;
    // A looped video (scene events.loop, timeline.js loopTimeline): every layer sees time folded into one period, so
    // frame t and t + period are the same picture whatever a layer does with absolute time (a boat's water shimmer,
    // smoke wobbles), and the window joins seamlessly. Folded into [period, 2 period): the timeline repeats there
    // and the period before is in it (what spills over from it is in progress). The intro title reads the real time.
    const P = this.loopPeriod;
    if (P) { this.realTime = t; t = P + (((t % P) + P) % P); }
    return t;
  }

  async prefetch(frame) {
    if (!this.prefetchers.length) return;
    const t = this.timeAt(frame);
    await Promise.all(this.prefetchers.map((fn) => fn(t, frame)));
  }

  update(frame) {
    const t = this.timeAt(frame);
    for (const fn of this.animations) fn(t, frame);
  }

  // Renders frame into the YUV (mode 0) or RGB (mode 1) target.
  render(frame, mode = 0) {
    this.update(frame);
    this.composer.render();
    this.outMat.uniforms.src.value = this.composer.readBuffer.texture;
    this.outMat.uniforms.mode.value = mode;
    this.renderer.setRenderTarget(mode === 0 ? this.yuvTarget : this.rgbTarget);
    this.renderer.render(this.quadScene, this.quadCam);
    this.renderer.setRenderTarget(null);
  }

  readSync(mode, buf) {
    const t = mode === 0 ? this.yuvTarget : this.rgbTarget;
    this.renderer.readRenderTargetPixels(t, 0, 0, t.width, t.height, buf);
    return buf;
  }

  readAsync(mode, buf) {
    const t = mode === 0 ? this.yuvTarget : this.rgbTarget;
    return this.renderer.readRenderTargetPixelsAsync(t, 0, 0, t.width, t.height, buf);
  }

  // Guide pass for AI enhancement: exact linear view distance per pixel (W x H Float32, rows
  // bottom-up). Transparent effects (rain, glass, haze, steam) are hidden; alpha-tested leaves keep
  // their silhouettes because each depth material copies the source map + alphaTest.
  renderDepth(frame, out) {
    this.update(frame);
    const W = this.W, H = this.H, cam = this.camera;
    if (!this.depthTarget) this.depthTarget = new THREE.WebGLRenderTarget(W, H, { type: THREE.FloatType, samples: 0 });
    const swapped = [], hidden = [];
    this.scene.traverse((o) => {
      if (!o.isMesh || !o.visible) return;
      const m = o.material;
      if (m.transparent || m.blending === THREE.AdditiveBlending || o.userData.noDepthGuide) { o.visible = false; hidden.push(o); return; }
      const dm = new THREE.MeshDepthMaterial({ depthPacking: THREE.BasicDepthPacking, map: m.alphaTest > 0 ? m.map : null, alphaTest: m.alphaTest, side: m.side });
      swapped.push([o, m]);
      o.material = dm;
    });
    const bg = this.scene.background, fog = this.scene.fog;
    this.scene.background = new THREE.Color(0, 0, 0);
    this.scene.fog = null;
    this.renderer.setRenderTarget(this.depthTarget);
    this.renderer.clear();
    this.renderer.render(this.scene, cam);
    this.renderer.setRenderTarget(null);
    const rgba = new Float32Array(W * H * 4);
    this.renderer.readRenderTargetPixels(this.depthTarget, 0, 0, W, H, rgba);
    for (const [o, m] of swapped) { o.material.dispose(); o.material = m; }
    for (const o of hidden) o.visible = true;
    this.scene.background = bg; this.scene.fog = fog;
    const n = cam.near, f = cam.far;
    for (let i = 0; i < W * H; i++) {
      const d = 1 - rgba[i * 4]; // fragCoordZ in 0..1 (1 = far / background)
      out[i] = d >= 0.999999 ? f : (n * f) / (f - (f - n) * d);
    }
    return { near: n, far: f };
  }
}

function makeLightHelpers(scene) {
  const shadowSetup = (l, o) => {
    l.castShadow = !!o.shadow;
    if (o.shadow) {
      l.shadow.mapSize.set(o.mapSize ?? 1024, o.mapSize ?? 1024);
      l.shadow.radius = o.softness ?? 4;
      l.shadow.bias = o.bias ?? -0.002;
      l.shadow.normalBias = o.normalBias ?? 0.02;
      l.shadow.intensity = o.shadowIntensity ?? 1;
      if (l.shadow.camera) { l.shadow.camera.near = o.near ?? 0.05; }
    }
  };
  return {
    point(o) {
      const l = new THREE.PointLight(o.color ?? '#ffffff', o.intensity ?? 1, o.distance ?? 0, o.decay ?? 2);
      l.position.set(...o.pos);
      shadowSetup(l, o);
      scene.add(l);
      return l;
    },
    spot(o) {
      const l = new THREE.SpotLight(o.color ?? '#ffffff', o.intensity ?? 1, o.distance ?? 0, o.angle ?? Math.PI / 4, o.penumbra ?? 0.6, o.decay ?? 2);
      l.position.set(...o.pos);
      l.target.position.set(...o.target);
      shadowSetup(l, o);
      scene.add(l, l.target);
      return l;
    },
    dir(o) {
      const l = new THREE.DirectionalLight(o.color ?? '#ffffff', o.intensity ?? 1);
      l.position.set(...o.pos);
      l.target.position.set(...(o.target ?? [0, 0, 0]));
      shadowSetup(l, o);
      if (o.shadow && o.box) Object.assign(l.shadow.camera, { left: -o.box, right: o.box, top: o.box, bottom: -o.box, far: o.far ?? 200 });
      scene.add(l, l.target);
      return l;
    },
    hemi(o) {
      const l = new THREE.HemisphereLight(o.sky, o.ground, o.intensity ?? 1);
      scene.add(l);
      return l;
    },
    ambient(o) {
      const l = new THREE.AmbientLight(o.color, o.intensity ?? 1);
      scene.add(l);
      return l;
    },
  };
}
