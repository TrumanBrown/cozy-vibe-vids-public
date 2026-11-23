// The enchanting table's book and the glyphs that drift into it (Truman 2026-11-22, the Enchanter's Tower: movers he
// picked for the room; as in the game, the book floats over the table, turns and flips its pages, and glyphs fly into it
// from the bookshelves around it).
//
// The book: an original blocky book built from boxes in code (leather covers with gold corners, a spine, a block of pages
// on each cover, three loose pages that turn), floating over the table's middle, open toward the room and tilted back.
// It bobs slowly, turns a little this way and that, its covers breathe open and shut a few degrees, and every few
// seconds it turns a page or a few in a row. Rendered every frame into its own texture from the camera's side of it and
// composited onto the plate: the low sun behind it rims its top edges, the room's warm light fills the side it shows,
// and it casts a soft shadow forward onto the table's top. The glyphs: small runes of our own (pixel shapes made here,
// never the game's alphabet), pale blue-white, some grayer, each flying from a point on a bookshelf toward the book on
// a gentle curve, dropping into it at the end and fading out there; a few a second, steady. Everything is a pure
// function of time with whole cycles per loop, so the 20 minute window joins.
//
// opts: { plate, at: [x, y] (px at 4K: the table top's middle), size (px: the book's height, 260), lift (px: its middle
//   above the table top, 210), horizon (px: eye level, 1060), focal (px, 1600), sun: [x, y] (px), tilt (rad: tilted
//   back, 0.5), turn (rad: how far it turns each way, 0.35), key { color, intensity }, fill { color, intensity },
//   ambient (1.1), table: [[x, y] x 4] (px: the table top, where its shadow falls), shadow (0.28),
//   glyphs: { sources: [[x0, y0, x1, y1] px], rate (per s, 4), size (px: a rune's height, 34), life: [s, s] },
//   renderOrder (10) }
import * as THREE from 'three';
import { plateTexture, imagePixels, boxMean, instancedQuad, PREMUL } from './overlay.js';
import { boxMaterials, hash3 } from './boxart.js';
import { mulberry32 } from '../engine/rng.js';
import { smooth } from './util.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;
const C = { leather: '#6a2e1f', leatherDark: '#4a1f15', inner: '#3a1a11', gold: '#d6b14c', page: '#efe5cc', pageEdge: '#d6caa9', ink: '#b8ab8e' };
const FLIP = 0.62;            // s a page takes to turn
const NPAGE = 4;              // loose pages, two lying on each side at the loop's start
const LEAF = 0.08;            // a loose page's thickness (units)

// the face of a page: cream with faint lines of "writing" (dashes, never letters), each page and each side of it its own
// (seed), so a page lifting off a stack shows the next one under it. p in units on a 5 x 8 page, 2 texels a unit; mirror
// for a page seen from its back
const pagePaint = (seed, mirror = false) => (p, f) => {
  if (f !== 4 && f !== 5) return C.pageEdge;
  const ry = Math.floor((4 - p[1]) * 2), cx = Math.floor(((mirror ? -p[0] : p[0]) + 2.5) * 2);
  if (ry < 3 || ry > 13 || ry % 2 === 0 || cx < 1 || cx > 8) return C.page;
  return hash3(ry, cx, seed) > 0.35 ? C.ink : C.page;
};

function buildBook() {
  const root = new THREE.Group();
  const cover = (side) => {
    const piv = new THREE.Group();
    const paint = (p, f) => {
      const corner = Math.abs(p[0]) > 2.2 && Math.abs(p[1]) > 4.2;
      if (f === 4) return C.inner;                                  // its inside, under the pages
      if (corner || (Math.abs(p[1]) > 4 && f === 5)) return C.gold;
      return hash3(Math.floor(p[0] + 9), Math.floor(p[1] + 9), f) > 0.8 ? C.leatherDark : C.leather;
    };
    const m = new THREE.Mesh(new THREE.BoxGeometry(6, 10, 0.5), boxMaterials([6, 10, 0.5], 2, paint, 51 + side, { grain: 0.1, roughness: 0.8 }));
    m.position.set(side * 3, 0, -0.25);
    piv.add(m);
    const top = pagePaint(5 + side);
    const pages = new THREE.Mesh(new THREE.BoxGeometry(5, 8, 0.9), boxMaterials([5, 8, 0.9], 2, (p, f) => (f === 4 ? top(p, f)
      : Math.floor((p[2] + 0.45) * 6) % 2 ? C.pageEdge : C.page), 55 + side, { grain: 0.05, roughness: 0.9 }));
    pages.position.set(side * 2.7, 0, 0.45);
    piv.add(pages);
    root.add(piv);
    return piv;
  };
  const left = cover(-1), right = cover(1);
  const spine = new THREE.Mesh(new THREE.BoxGeometry(1, 10, 0.6), boxMaterials([1, 10, 0.6], 2, (p) => (Math.abs(p[1]) > 3.6 && Math.abs(p[1]) < 4.4 ? C.gold : C.leatherDark), 57, { grain: 0.1 }));
  spine.position.set(0, 0, -0.55);
  root.add(spine);
  // the loose pages turn about the line where the two stacks' tops meet, over the spine (placed each frame: it moves
  // as the covers breathe); each is a thin board from that line outward, its front (+z) up while it lies on the right
  // stack, its back up on the left one
  const flips = Array.from({ length: NPAGE }, (_, i) => {
    const g = new THREE.Group();
    const front = pagePaint(20 + 2 * i), back = pagePaint(21 + 2 * i, true);
    const m = new THREE.Mesh(new THREE.BoxGeometry(5, 8, LEAF), boxMaterials([5, 8, LEAF], 2, (p, f) => (f === 5 ? back(p, f) : front(p, f)), 60 + i, { grain: 0.04, roughness: 0.9 }));
    g.add(m);
    root.add(g);
    return g;
  });
  return { root, left, right, flips };
}

// The page turns over a loop, from the loop's own seed: [[start s, dir]] sorted by start, dir 1 a turn from the right
// stack to the left (reading on), -1 back. Bursts of one to three a few seconds apart, mostly forward and now and then
// back; a turn always takes the top loose page of its side. Moving tops between two stacks keeps the right stack plus the
// left one reversed in the same order, so the same number of turns each way brings every page back where it started:
// the last turns of the loop square it, done well before its end, and the 20 minute window joins.
export function flipSchedule(P, seed = 1) {
  const r = mulberry32((seed * 7919 + 13) >>> 0);
  const out = [];
  const start = NPAGE / 2;
  let right = start;
  for (let t = 1.5 + 2.5 * r(); t < P - 8; t += 4.5 + 6 * r()) {
    let dir = r() < 0.7 ? 1 : -1;
    if (!(dir > 0 ? right : NPAGE - right)) dir = -dir;
    const n = Math.min(dir > 0 ? right : NPAGE - right, 1 + Math.floor(3 * r() * r() * 1.4));
    for (let k = 0; k < n; k++) out.push([t + 0.34 * k, dir]);
    right -= dir * n;
  }
  for (let t = P - 6; right !== start; t += 0.34) {
    const dir = right > start ? 1 : -1;
    out.push([t, dir]);
    right -= dir;
  }
  return out;
}

// The book's pose at loop time t (s, 0..P): { bob (units, + up), yaw (rad), open (rad: each cover's fold toward the
// room), pages: [{ psi (rad about the spine: open while it lies on the right stack, pi - open on the left), lift (units
// along the page's own normal, + toward its front: its height in its stack) }] }. Whole cycles per loop.
export function bookPose(t, P, flips) {
  const cyc = (per) => TAU * Math.max(1, Math.round(P / per)) / P;
  const bob = 0.36 * Math.sin(cyc(3.4) * t) + 0.12 * Math.sin(cyc(11.7) * t + 1.1);
  const yaw = 0.6 * Math.sin(cyc(41) * t + 0.4) + 0.4 * Math.sin(cyc(97) * t + 2.0);
  const open = 0.42 + 0.06 * Math.sin(cyc(12.6) * t + 0.7);
  // replay the turns so far: each side's loose pages bottom to top, and the ones in the air
  const sides = { 1: [0, 1], [-1]: [2, 3] };        // 1: the right stack, -1: the left one
  const air = [];
  for (const [s, dir] of flips) {
    if (s > t) break;
    const page = sides[dir].pop();
    if (page === undefined) continue;
    if (t >= s + FLIP) sides[-dir].push(page);
    else air.push({ page, dir, k: smooth((t - s) / FLIP), from: sides[dir].length });
  }
  const h = (i) => 0.05 + LEAF * (i + 0.5);
  const pages = Array(NPAGE);
  for (const sd of [1, -1]) sides[sd].forEach((p, i) => { pages[p] = { psi: sd > 0 ? open : Math.PI - open, lift: sd * h(i) }; });
  const landing = { 1: sides[1].length, [-1]: sides[-1].length };
  for (const a of air) {
    const to = landing[-a.dir]++;
    const p0 = a.dir > 0 ? open : Math.PI - open, p1 = Math.PI - p0;
    pages[a.page] = { psi: p0 + (p1 - p0) * a.k, lift: (1 - a.k) * a.dir * h(a.from) - a.k * a.dir * h(to) };
  }
  return { bob, yaw, open, pages };
}

// ------------------------------------------------------------------ glyphs
// 16 runes on a 5 x 6 grid: three or four strokes each (bars, hooks, dots), our own shapes
function runeAtlas(seed) {
  const r = mulberry32((seed * 104729 + 7) >>> 0);
  const N = 16, G = 8;
  const cv = document.createElement('canvas');
  cv.width = N * G; cv.height = G;
  const g = cv.getContext('2d');
  g.fillStyle = '#fff';
  for (let i = 0; i < N; i++) {
    const on = new Set();
    const strokes = 3 + Math.floor(2 * r());
    for (let s = 0; s < strokes; s++) {
      const vert = r() < 0.55, len = 2 + Math.floor(3 * r());
      const x = Math.floor(r() * (vert ? 5 : 6 - len)), y = Math.floor(r() * (vert ? 7 - len : 6));
      for (let k = 0; k < len; k++) on.add(vert ? `${x},${y + k}` : `${x + k},${y}`);
    }
    if (r() < 0.5) on.add(`${Math.floor(r() * 5)},${Math.floor(r() * 6)}`);
    for (const c of on) {
      const [x, y] = c.split(',').map(Number);
      if (x < 5 && y < 6) g.fillRect(i * G + 1 + x, 1 + y, 1, 1);
    }
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.magFilter = THREE.NearestFilter;
  tex.minFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  return { tex, N, G };
}

const glyphVert = /* glsl */ `
attribute vec4 aS;      // source box x0, y0, x1, y1 (px)
attribute vec4 aP;      // period (s), phase (0..1), life (s), seed
uniform float uTime, uLoop, uSize, uDip, uArc;
uniform vec2 uBook;
varying vec2 vT;
varying float vA, vRune, vF;
float h(float k, float s) { return fract(sin(k * 91.7 + s * 47.3) * 24634.6345); }
void main() {
  float per = aP.x, n = floor(uLoop / per + 0.5);
  float tt = uTime + aP.y * per;
  float k = mod(floor(tt / per), n);
  float age = tt - floor(tt / per) * per;
  float s = age / aP.z;
  if (s >= 1.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
  vec2 S = vec2(mix(aS.x, aS.z, h(k, aP.w)), mix(aS.y, aS.w, h(k, aP.w + 1.0)));
  vec2 B = uBook - vec2(0.0, uDip);
  // toward a point over the book, a floating curve on the way, then down into it
  vec2 p = mix(S, B, s) + vec2(0.0, uDip * s * s * s * s) - vec2(0.0, uArc * (0.6 + 0.8 * h(k, aP.w + 2.0)) * sin(3.14159 * s));
  float sz = uSize * (0.75 + 0.5 * h(k, aP.w + 3.0)) * (1.0 - 0.3 * s);
  vA = smoothstep(0.0, 0.14, s) * (1.0 - smoothstep(0.8, 1.0, s));
  vRune = floor(h(k, aP.w + 4.0) * 16.0);
  vF = 0.4 + 0.6 * h(k, aP.w + 5.0);
  vT = position.xy * 0.5 + 0.5;
  vec2 q = p + position.xy * sz * 0.75;
  gl_Position = vec4(q.x / ${W}.0 * 2.0 - 1.0, 1.0 - q.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;
const glyphFrag = /* glsl */ `
uniform sampler2D tRunes;
uniform float uGain;
varying vec2 vT;
varying float vA, vRune, vF;
void main() {
  // the rune's 8 x 8 cell, flipped to image rows: crisp pixel strokes (a glow from the neighbouring texels drew a gray
  // square around each rune)
  vec2 c = vec2((vRune + vT.x) / 16.0, 1.0 - vT.y);
  float a = vA * 0.9 * texture2D(tRunes, c).r;
  if (a < 0.003) discard;
  vec3 col = vec3(0.9 * vF, 0.9 * vF, vF) * uGain;
  gl_FragColor = vec4(col * a, a);
}`;

const quadVert = /* glsl */ `
uniform vec4 uBox;
varying vec2 vT;
varying vec2 vUv;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = vec2(q.x, 1.0 - q.y);
  vec2 px = uBox.xy + vT * uBox.zw;
  vUv = vec2(px.x / ${W}.0, 1.0 - px.y / ${H}.0);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;
const bookFrag = /* glsl */ `
uniform sampler2D tBook;
varying vec2 vT;
void main() {
  vec4 c = texture2D(tBook, vec2(vT.x, 1.0 - vT.y));
  if (c.a < 0.002) discard;
  gl_FragColor = c;
}`;
// its shadow on the table's top: a soft ellipse thrown forward, only inside the top's outline
const shadowFrag = /* glsl */ `
uniform vec2 uC, uR;
uniform float uK;
uniform vec2 uTop[4];
varying vec2 vT;
varying vec2 vUv;
float side(vec2 p, vec2 a, vec2 b) { return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x); }
void main() {
  vec2 px = vec2(vUv.x * ${W}.0, (1.0 - vUv.y) * ${H}.0);
  float inTop = 1.0;
  for (int i = 0; i < 4; i++) inTop *= step(0.0, side(px, uTop[i], uTop[(i + 1) - 4 * ((i + 1) / 4)]));
  vec2 q = (px - uC) / uR;
  float k = exp(-dot(q, q) * 2.0) * uK * inTop;
  if (k < 0.003) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, k);
}`;

export async function enchantLayer(ctx, opts) {
  const R = ctx.renderer;
  if (!R || !opts.at) return null;
  const P = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const [ax, ay] = opts.at;
  const size = opts.size ?? 260, ppu = size / 10;
  const lift = opts.lift ?? 210;
  const focal = opts.focal ?? 1600, cx = W / 2, cy = opts.horizon ?? 1060;
  const book = buildBook();
  const scene3 = new THREE.Scene();
  const holder = new THREE.Group();
  holder.add(book.root);
  scene3.add(holder);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x404040, opts.ambient ?? 1.1);
  const key = new THREE.DirectionalLight(opts.key?.color ?? '#ffc07a', opts.key?.intensity ?? 2.8);
  const fill = new THREE.DirectionalLight(opts.fill?.color ?? '#ffb27a', opts.fill?.intensity ?? 0.9);
  scene3.add(hemi, key, fill);
  const [sunX, sunY] = opts.sun ?? [2195, 785];
  key.position.set(sunX - cx, cy - sunY, -focal).normalize().multiplyScalar(100);
  // the room's light on the side it shows: the fire and the candles to the right, from in front
  fill.position.set(0.7, 0.35, 1).normalize().multiplyScalar(100);
  const blur = (await imagePixels(`/out/plates/${opts.plate}/blur.png`)) ?? (await imagePixels(`/out/plates/${opts.plate}/plate.png`));
  const avg = boxMean(blur, W, H);
  // the window behind and above it, the table's red top under it
  hemi.color.setRGB(...avg(ax - 1.2 * size, ay - lift - 1.8 * size, ax + 1.2 * size, ay - lift - 0.6 * size).map((v) => v * 0.7));
  hemi.groundColor.setRGB(...avg(ax - 0.6 * size, ay - 0.05 * size, ax + 0.6 * size, ay + 0.1 * size));
  // one texel per screen pixel: the open book is at most 14 units across, the box 16
  const RT = Math.ceil((16 * ppu) / 16) * 16;
  const rt = new THREE.WebGLRenderTarget(RT, RT, { type: THREE.HalfFloatType, samples: 4 });
  const half = RT / 2 / ppu;
  const cam = new THREE.OrthographicCamera(-half, half, half, -half, 1, 400);
  const mat = new THREE.ShaderMaterial({ vertexShader: quadVert, fragmentShader: bookFrag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4() }, tBook: { value: rt.texture } } });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  const top = opts.table ?? [[ax - 230, ay - 28], [ax + 230, ay - 28], [ax + 250, ay + 30], [ax - 250, ay + 30]];
  const smat = new THREE.ShaderMaterial({ vertexShader: quadVert, fragmentShader: shadowFrag, ...PREMUL,
    uniforms: { uBox: { value: new THREE.Vector4(ax - 0.9 * size, ay - 0.3 * size, 1.8 * size, 0.6 * size) }, uC: { value: new THREE.Vector2() },
      uR: { value: new THREE.Vector2(0.42 * size, 0.06 * size) }, uK: { value: 0 }, uTop: { value: top.map(([x, y]) => new THREE.Vector2(x, y)) } } });
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), smat);
  const ro = opts.renderOrder ?? 10;
  shadow.renderOrder = ro - 0.5;
  quad.renderOrder = ro;
  for (const m of [shadow, quad]) { m.frustumCulled = false; m.userData.noAO = true; ctx.add(m); }

  // glyphs
  const G = opts.glyphs ?? {};
  const sources = G.sources ?? [];
  let gmat = null;
  if (sources.length) {
    const atlas = runeAtlas(ctx.seed ?? 1);
    const rate = G.rate ?? 4, [l0, l1] = G.life ?? [1.7, 2.3];
    const r = mulberry32(((ctx.seed ?? 1) * 31337 + 5) >>> 0);
    const meanPer = 3.0, N = Math.max(1, Math.round(rate * meanPer));
    const aS = new Float32Array(N * 4), aP = new Float32Array(N * 4);
    for (let i = 0; i < N; i++) {
      const per = P / Math.max(1, Math.round(P / (meanPer * (0.8 + 0.4 * r()))));
      aS.set(sources[i % sources.length], i * 4);
      aP.set([per, r(), Math.min(per - 0.2, l0 + (l1 - l0) * r()), Math.floor(r() * 997)], i * 4);
    }
    const gg = instancedQuad(N);
    gg.setAttribute('aS', new THREE.InstancedBufferAttribute(aS, 4));
    gg.setAttribute('aP', new THREE.InstancedBufferAttribute(aP, 4));
    gmat = new THREE.ShaderMaterial({ vertexShader: glyphVert, fragmentShader: glyphFrag, ...PREMUL,
      uniforms: { uTime: { value: 0 }, uLoop: { value: P }, uSize: { value: G.size ?? 34 }, uDip: { value: G.dip ?? 0.35 * size },
        uArc: { value: G.arc ?? 60 }, uBook: { value: new THREE.Vector2(ax, ay - lift) }, tRunes: { value: atlas.tex }, uGain: { value: G.gain ?? 1.0 } } });
    const gm = new THREE.Mesh(gg, gmat);
    gm.frustumCulled = false;
    gm.renderOrder = ro + 1;
    gm.userData.noAO = true;
    ctx.add(gm);
  }

  const flips = flipSchedule(P, ctx.seed ?? 1);
  const prevClear = new THREE.Color();
  ctx.animate((t) => {
    const tm = ((t % P) + P) % P;
    const pose = bookPose(tm, P, flips);
    const tilt = opts.tilt ?? 0.5, turn = opts.turn ?? 0.35;
    // the book's own frame: covers folded toward the room by `open`, tilted back, turned about the vertical. A loose page
    // turns about the line where the two stacks' tops meet, 0.9 / cos(open) over the spine, and reaches from it to the
    // stack's outer edge (5.2 - 0.9 tan(open) units), lifted along its own normal to its height in its stack
    book.left.rotation.y = pose.open;
    book.right.rotation.y = -pose.open;
    const reach = 5.2 - 0.9 * Math.tan(pose.open);
    book.flips.forEach((g, i) => {
      const pg = pose.pages[i];
      g.position.set(0, 0, 0.9 / Math.cos(pose.open));
      g.rotation.y = -pg.psi;
      const m = g.children[0];
      m.scale.x = reach / 5;
      m.position.set(reach / 2, 0, pg.lift);
    });
    book.root.rotation.set(-tilt, 0, 0);
    holder.rotation.set(0, turn * pose.yaw, 0);
    const bx = ax, by = ay - lift - pose.bob * ppu;
    const n = new THREE.Vector3(cx - bx, by - cy, focal).normalize();
    cam.position.copy(n).multiplyScalar(200);
    cam.up.set(0, 1, 0);
    cam.lookAt(0, 0, 0);
    const prevRT = R.getRenderTarget(), prevA = R.getClearAlpha(), prevAuto = R.autoClear;
    R.getClearColor(prevClear);
    R.setRenderTarget(rt);
    R.setClearColor(0x000000, 0);
    R.clear(true, true, true);
    R.autoClear = false;
    R.render(scene3, cam);
    R.autoClear = prevAuto;
    R.setRenderTarget(prevRT);
    R.setClearColor(prevClear, prevA);
    mat.uniforms.uBox.value.set(bx - RT / 2, by - RT / 2, RT, RT);
    // the shadow: forward of its foot, softer and lighter the higher it floats
    const up = (ay - by) / lift;
    smat.uniforms.uC.value.set(bx, ay + 4);
    smat.uniforms.uK.value = (opts.shadow ?? 0.28) / (0.6 + 0.4 * up);
    if (gmat) gmat.uniforms.uTime.value = tm;
  });
  return quad;
}
