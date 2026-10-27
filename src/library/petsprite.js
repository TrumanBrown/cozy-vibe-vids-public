// A pet that really moves, in pixel art (user 2026-10-21 on the pixel greenhouse: animate the whole dog, lifting its
// head, walking to the door, lying back down, a tail wag now and then, with a sprite for each animation). Pixel art is
// drawn frame by frame, so sprites are the look's own way to move.
// tools/pet_sprite.py paints every pose into the picture itself, each from the one before it (round 6: the dog must
// never change style): the painted pet's head carried up by whole cells with the image model painting only
// the body that joins it to the painted rump (rise, sit, stand), the back and front views painted beside the standing
// dog, the walks and the wag as those frames with only the legs or the tail repainted; and patches on the plate's own
// grid: the painted pet drowsy, half awake, awake, and the empty mat. The generated video of a painted pet stays retired
// (DECISIONS 2026-10-18). Mocks only for now.
//
// Each frame of the program shows one of: the plate as painted (asleep, the plate layer breathes it), a patch, or the
// empty mat with a sprite frame on the floor. Every frame was painted somewhere in the picture (drawn_at, its feet) and
// shows there at its own size, cell for cell; elsewhere its size follows the floor's perspective from that row
// ((y - horizon) / (drawn row - horizon)) in steps of a few percent with the anchor on the art's grid, so a sprite keeps
// its own pixels from frame to frame instead of shimmering. It moves at a pace in meters per second along the floor
// (screen paths turned into floor distances through the camera height). Tinted by the plate's light at its feet
// (blur.png) relative to the light it was painted in (lit_at), with a soft contact shadow.
//
// opts: { plate, scene, start (scene s the program starts), cycle (s: the program repeats, the rest of each cycle asleep;
//   round 4: one trip an hour, bed to door and back, then the hour loops),
//   program: [{ do: 'sleep' | 'awake', dur } | { do: 'patch', name ('drowsy', 'half', 'awake'), dur } |
//   { do: 'pose', sheet, frames: [i...], fps (8), at, flip (false), dur, breathe } |
//   { do: 'idle', sheet, frame, at, flip, dur, wag: { sheet, frames, fps, cycles, every: [s, s], seed }, breathe } |
//   { do: 'walk', sheet, path: [point, ...], speed (m/s, 0.5), fps (6) }],
//   a point (at, path): [x, y] image coords of the feet, or 'drawn:<sheet>' (where that sheet was painted); at: 'drawn'
//   is the pose's own sheet's. horizon (0.31: the floor's vanishing row), height0: [px, row] (the pet's head-top height in
//   4K px with its feet at that row, image coords), height1: [px, row] (a second one: the horizon follows from the two;
//   a painted room is rarely one true perspective), dogM (0.45: that height in m), focal (3325 px at 4K), k: { <sheet>:
//   factor } (a sheet the image model painted a size the floor model disagrees with), shadow (0.35), renderOrder (35: in
//   front of the glass behind it) }
// breathe: { period (3.4 s), share (0.45 of it lifted), cells (1), split (0.45: the frame's lower part that stays) }:
// a pose held a while lifts its upper body by a cell and back, the way pixel art breathes (a still sprite reads frozen)
import * as THREE from 'three';
import { mulberry32 } from '../engine/rng.js';
import { PREMUL, imagePixels } from './overlay.js';

const W = 3840, H = 2160;

const vert = /* glsl */ `
uniform vec4 uRect;     // x0, y0, x1, y1 (px, y down)
varying vec2 vQ;        // 0..1 across the rect, y down
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vQ = vec2(q.x, 1.0 - q.y);
  vec2 p = mix(uRect.xy, uRect.zw, vQ);
  gl_Position = vec4(p.x / ${W}.0 * 2.0 - 1.0, 1.0 - p.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;

// A sprite frame on the grid: each cell takes the frame's average over the cell (premultiplied mip levels), solid
// where it covers most of it, colored from a sharper level, as a hand-made sprite keeps its own colors. At its own size
// (uExact) the frame's cells are the plate's cells, read texel for texel. The rect has room above the frame (uPadK) for
// a breath: the rows above uSplit move up by uLift (frame heights), the rows just below stretch to meet them
const spriteFrag = /* glsl */ `
uniform sampler2D tFrame;
uniform float uFlip, uScale, uCell, uAlpha, uPadK, uLift, uSplit, uExact;
uniform vec2 uTexSize;
uniform vec3 uTint;
varying vec2 vQ;
void main() {
  vec2 st = vec2(uFlip > 0.5 ? 1.0 - vQ.x : vQ.x, (1.0 - vQ.y) * uPadK);
  st.y -= uLift * smoothstep(uSplit - 0.1, uSplit, st.y);
  if (st.y > 1.0) discard;
  if (uExact > 0.5) {
    vec4 c = textureLod(tFrame, st, 0.0);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb / c.a * uTint * uAlpha, uAlpha);
    return;
  }
  float lod = uCell > 0.0 ? max(0.0, log2(uCell / uScale) - 0.5) : 0.0;
  vec4 c = textureLod(tFrame, st, lod);
  if (c.a < 0.5) discard;
  vec4 k = textureLod(tFrame, st, max(0.0, lod - 1.5));
  vec3 col = k.a > 0.05 ? k.rgb / k.a : c.rgb / c.a;
  // a cell on the silhouette's edge takes the darkest color under it: scaled down, the one-cell dark edge would be
  // averaged into the fur and the dog lose its outline at the door (round 6)
  vec2 d = vec2(uCell / max(uScale, 1e-3)) / uTexSize;
  float edge = 0.0;
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.785398;
    edge = max(edge, step(textureLod(tFrame, st + vec2(cos(a), sin(a)) * d * 0.8, 0.0).a, 0.5));
  }
  if (edge > 0.5) {
    float dl = 1e9;
    for (int j = 0; j < 4; j++) {
      for (int i = 0; i < 4; i++) {
        vec4 t = textureLod(tFrame, st + ((vec2(float(i), float(j)) + 0.5) / 4.0 - 0.5) * d, 0.0);
        if (t.a > 0.5) {
          vec3 tc = t.rgb / t.a;
          float l = dot(tc, vec3(0.2126, 0.7152, 0.0722));
          if (l < dl) { dl = l; col = tc; }
        }
      }
    }
  }
  gl_FragColor = vec4(col * uTint * uAlpha, uAlpha);
}`;

const patchFrag = /* glsl */ `
uniform sampler2D tPatch;
uniform float uAlpha;
varying vec2 vQ;
void main() {
  vec4 c = texture2D(tPatch, vec2(vQ.x, 1.0 - vQ.y));
  if (c.a < 0.5) discard;
  gl_FragColor = vec4(c.rgb * uAlpha, uAlpha);
}`;

const shadowFrag = /* glsl */ `
uniform float uAlpha;
varying vec2 vQ;
void main() {
  vec2 d = (vQ - 0.5) * 2.0;
  float a = uAlpha * (1.0 - smoothstep(0.35, 1.0, length(d)));
  if (a < 0.004) discard;
  gl_FragColor = vec4(0.0, 0.0, 0.0, a);
}`;

const loadTex = async (url, { nearest = false, premul = false } = {}) => {
  const t = await new THREE.TextureLoader().loadAsync(url);
  t.colorSpace = THREE.SRGBColorSpace;
  t.premultiplyAlpha = premul;
  if (nearest) {
    t.generateMipmaps = false;
    t.minFilter = t.magFilter = THREE.NearestFilter;
  } else {
    t.generateMipmaps = true;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    t.magFilter = THREE.NearestFilter;
  }
  return t;
};

function quad(ctx, frag, uniforms, order) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL, uniforms: { uRect: { value: new THREE.Vector4() }, uAlpha: { value: 1 }, ...uniforms },
  }));
  m.frustumCulled = false;
  m.renderOrder = order;
  m.userData.noAO = true;
  m.visible = false;
  ctx.add(m);
  return m;
}

export async function petSpriteLayer(ctx, opts) {
  const dir = `/out/plates/${opts.plate}/petsprite`;
  const meta = await fetch(`${dir}/petsprite.json`).then((r) => r.json());
  const plateMeta = await fetch(`/out/plates/${opts.plate}/plate.json`).then((r) => r.json());
  const grid = plateMeta.pixel ?? null;
  const cell = grid?.cell ?? 0, [ox, oy] = grid?.origin ?? [0, 0];
  // frames
  const frames = {};
  for (const [sheet, list] of Object.entries(meta.frames)) {
    frames[sheet] = await Promise.all(list.map(async (f) => ({ ...f, tex: await loadTex(`${dir}/${f.file}`, { premul: true }) })));
  }
  // where a sheet was painted (4K px, its feet): every frame carries it (round 6: the poses are painted in the picture)
  const drawnAt = (sheet) => {
    const d = frames[sheet]?.[0]?.drawn_at;
    if (!d) throw new Error(`petsprite: ${sheet} has no drawn_at (run tools/pet_sprite.py cut)`);
    return d;
  };
  // a point: [x, y] in image coords, or 'drawn:<sheet>' (where that sheet was painted)
  const pt = (p) => (typeof p === 'string' ? drawnAt(p.split(':')[1]).map((v, i) => v / (i ? H : W)) : p);
  // patches on the plate's grid
  const patches = {};
  for (const name of ['drowsy', 'half', 'awake', 'empty']) {
    const p = meta[name];
    if (p) patches[name] = { ...p, tex: await loadTex(`/assets/keyart/${opts.scene}/petsprite/${p.file}`, { nearest: true }) };
  }
  // the floor: the pet's head-top height at its feet's row, meters along the floor. With two heights the horizon is
  // where they meet (a painted room is rarely one true perspective: the dog has to fit the door it sits at)
  const [h0, row0] = opts.height0 ?? [384, 0.81];
  const y0 = row0 * H;
  let yh = (opts.horizon ?? 0.31) * H;
  if (opts.height1) {
    const [h1, row1] = opts.height1;
    yh = (h1 * y0 - h0 * row1 * H) / (h1 - h0);
  }
  const ppm0 = h0 / (opts.dogM ?? 0.45);
  const camH = (y0 - yh) / ppm0, focal = opts.focal ?? 3325;
  const heightAt = (y) => h0 * Math.max(0.05, (y - yh) / (y0 - yh));
  const ppm = (y) => ppm0 * Math.max(0.05, (y - yh) / (y0 - yh));
  const depth = (y) => focal * camH / Math.max(1, y - yh);
  // light: blur.png at the feet against where the painted pet lies (its colors are the sprites' palette)
  const blur = await imagePixels(`/out/plates/${opts.plate}/blur.png`);
  const lin = (v) => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const lightAt = (x, y) => {
    const acc = [0, 0, 0];
    let n = 0;
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) {
        const ix = Math.min(blur.width - 1, Math.max(0, Math.round((x + dx * 24) * blur.width / W)));
        const iy = Math.min(blur.height - 1, Math.max(0, Math.round((y + dy * 12) * blur.height / H)));
        const o = (iy * blur.width + ix) * 4;
        for (let c = 0; c < 3; c++) acc[c] += lin(blur.data[o + c]);
        n++;
      }
    }
    return acc.map((v) => v / n);
  };
  const lum = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  const ref = lightAt(...(opts.lightRef ?? [0.215 * W, 0.81 * H]));
  // every frame carries the light it was painted in (`lit_at`; the back and front views were painted in the standing
  // dog's light, wherever they stand): it is darkened relative to that spot as it moves away from the lamp, never
  // brightened past its painted colors, and its hue is its own (the plate's blur is bright where the glass door is
  // behind the feet, and it lit the dog at the door up and blue, round 6)
  const refs = new Map();
  const tintAt = (x, y, litAt) => {
    const key = litAt ? `${litAt[0]},${litAt[1]}` : '';
    if (!refs.has(key)) refs.set(key, litAt ? lightAt(litAt[0], litAt[1] + 0.03 * heightAt(litAt[1])) : ref);
    const R = refs.get(key);
    const g = Math.min(1, Math.max(0.45, Math.sqrt(lum(lightAt(x, y)) / Math.max(lum(R), 1e-4))));
    return [g, g, g];
  };
  // the shade it walks into (opts.shade: { ref, there: [sheets], from: row }): the image model painted the dog sitting
  // at the door darker than beside the lamp, backlit by the door (round 6: walking up bright and sitting down dark was a
  // switch). The walking frames take that look gradually from row `from` to the door: their mean color at the door is
  // the sitting dog's (lin_mean of there[0] over ref's); the sheets painted there show as painted
  const shade = opts.shade && frames[opts.shade.ref] && frames[opts.shade.there[0]] ? (() => {
    const a = frames[opts.shade.there[0]][0], b = frames[opts.shade.ref][0];
    return { K: a.lin_mean.map((v, c) => v / Math.max(1e-5, b.lin_mean[c])), door: a.drawn_at[1],
      from: pt(opts.shade.from)[1] * H, there: new Set(opts.shade.there) };
  })() : null;
  const shadeAt = (sheet, y) => {
    if (!shade) return [1, 1, 1];
    const t = Math.min(1, Math.max(0, (shade.from - y) / (shade.from - shade.door)));
    const w = t * t * (3 - 2 * t);
    return shade.K.map((k) => (1 + (k - 1) * w) / (shade.there.has(sheet) ? k : 1));
  };
  // walks: floor distance along each path (lateral m from the row's scale, into depth from the camera height)
  const program = (opts.program ?? []).map((st, n) => {
    if ((st.do === 'pose' || st.do === 'idle') && typeof st.at === 'string') {
      st = { ...st, at: st.at === 'drawn' ? pt(`drawn:${st.sheet}`) : pt(st.at) };
    }
    if (st.do === 'idle' && st.wag) {
      // tail wags now and then while it sits, at seeded times (the same every hour)
      const r = mulberry32(st.wag.seed ?? 7 + n), [lo, hi] = st.wag.every ?? [60, 120];
      const len = (st.wag.cycles ?? 2) * st.wag.frames.length / (st.wag.fps ?? 8);
      const wags = [];
      for (let w = (lo + (hi - lo) * r()) * 0.5; w + len < st.dur - 3; w += lo + (hi - lo) * r()) wags.push(w);
      if (ctx.params?.petlog) console.warn(`petsprite: wags at ${wags.map((w) => w.toFixed(1)).join(', ')} s into the idle`);
      return { ...st, wags, wagLen: len };
    }
    if (st.do !== 'walk') return { ...st };
    const P = st.path.map(pt).map(([x, y]) => [x * W, y * H]);
    const pts = [P[0]];
    const cum = [0];
    for (let i = 1; i < P.length; i++) {
      const [ax, ay] = P[i - 1], [bx, by] = P[i];
      for (let j = 1; j <= 60; j++) {
        const f = j / 60, x = ax + (bx - ax) * f, y = ay + (by - ay) * f;
        const [px, py] = pts[pts.length - 1];
        const ds = Math.hypot((x - px) / ppm((y + py) / 2), depth(y) - depth(py));
        pts.push([x, y]);
        cum.push(cum[cum.length - 1] + ds);
      }
    }
    const len = cum[cum.length - 1];
    return { ...st, pts, cum, dur: len / (st.speed ?? 0.5) };
  });
  let t0 = opts.start ?? 0;
  for (const st of program) {
    st.t0 = t0;
    t0 += st.dur;
  }
  const end = t0;
  if (ctx.params?.petlog) console.warn(`petsprite: ${program.map((s) => `${s.do === 'patch' ? s.name : s.do}${s.sheet ? `:${s.sheet}` : ''}@${s.t0.toFixed(1)}+${s.dur.toFixed(1)}`).join(' ')}`);
  const along = (st, s) => {
    const d = Math.min(Math.max(s, 0), 1) * st.cum[st.cum.length - 1];
    let i = st.cum.findIndex((c) => c >= d);
    if (i <= 0) return { x: st.pts[0][0], y: st.pts[0][1], dx: st.pts[1][0] - st.pts[0][0] };
    const f = (d - st.cum[i - 1]) / Math.max(1e-9, st.cum[i] - st.cum[i - 1]);
    return { x: st.pts[i - 1][0] + (st.pts[i][0] - st.pts[i - 1][0]) * f, y: st.pts[i - 1][1] + (st.pts[i][1] - st.pts[i - 1][1]) * f,
      dx: st.pts[i][0] - st.pts[i - 1][0] };
  };
  // where the pet is at t: { patch, sprite: { sheet, i, x, y, flip, lift } } or null (asleep: the plate as painted)
  const start = opts.start ?? 0;
  const fold = (t) => (opts.cycle && t >= start ? start + ((t - start) % opts.cycle) : t);
  // the painted pet holds its breath while anything is drawn over it (plate.js reads ctx.petHold), eased over a second
  // before it wakes and after it falls asleep
  const awakeFrom = program.find((s) => s.do !== 'sleep')?.t0 ?? end;
  const awakeTo = [...program].reverse().find((s) => s.do !== 'sleep');
  const awakeEnd = awakeTo ? awakeTo.t0 + awakeTo.dur : end;
  ctx.petHold = (tl) => {
    const t = fold(ctx.realTime?.() ?? tl);
    if (t >= awakeFrom && t < awakeEnd) return 1;
    const u = Math.min(1, (t < awakeFrom ? awakeFrom - t : t - awakeEnd) / 1.0);
    return 1 - u * u * (3 - 2 * u);
  };
  const breath = (st, tau) => {
    if (!st.breathe) return 0;
    const b = st.breathe === true ? {} : st.breathe;
    const P = b.period ?? 3.4, ph = (tau / P) % 1;
    return ph < (b.share ?? 0.45) ? (b.cells ?? 1) * (cell || 8) : 0;
  };
  const stateAt = (tIn) => {
    const t = fold(tIn);
    if (t < start || t >= end) return null;
    const st = program.find((s) => t >= s.t0 && t < s.t0 + s.dur);
    const tau = t - st.t0;
    if (st.do === 'sleep') return null;
    if (st.do === 'awake') return { patch: 'awake' };
    if (st.do === 'patch') return { patch: st.name };
    const at = (p) => ({ x: p[0] * W, y: p[1] * H });
    if (st.do === 'idle') {
      const w = st.wags?.find((w0) => tau >= w0 && tau < w0 + st.wagLen);
      const i = w === undefined ? st.frame : st.wag.frames[Math.floor((tau - w) * (st.wag.fps ?? 8)) % st.wag.frames.length];
      return { patch: 'empty', sprite: { sheet: st.wag && w !== undefined ? (st.wag.sheet ?? st.sheet) : st.sheet, i, ...at(st.at),
        flip: !!st.flip, lift: breath(st, tau), split: st.breathe?.split } };
    }
    const fps = st.fps ?? (st.do === 'walk' ? 6 : 8);
    const list = st.frames ?? frames[st.sheet].map((_, i) => i);
    const i = list[Math.floor(tau * fps) % list.length];
    if (st.do === 'pose') {
      return { patch: 'empty', sprite: { sheet: st.sheet, i, ...at(st.at), flip: !!st.flip, lift: breath(st, tau), split: st.breathe?.split } };
    }
    const p = along(st, tau / st.dur);
    const flip = st.sheet.endsWith('_side') ? p.dx < 0 : false;
    return { patch: 'empty', sprite: { sheet: st.sheet, i, x: p.x, y: p.y, flip, lift: 0 } };
  };

  const order = opts.renderOrder ?? 35;
  const patchMeshes = Object.fromEntries(Object.entries(patches).map(([n, p]) => {
    const m = quad(ctx, patchFrag, { tPatch: { value: p.tex } }, opts.patchOrder ?? 0.5);
    m.material.uniforms.uRect.value.set(p.x, p.y, p.x + p.w, p.y + p.h);
    return [n, m];
  }));
  const shadow = quad(ctx, shadowFrag, {}, order - 1);
  const sprite = quad(ctx, spriteFrag, {
    tFrame: { value: null }, uFlip: { value: 0 }, uScale: { value: 1 }, uCell: { value: cell }, uTint: { value: new THREE.Vector3(1, 1, 1) },
    uPadK: { value: 1 }, uLift: { value: 0 }, uSplit: { value: 0.45 }, uExact: { value: 0 }, uTexSize: { value: new THREE.Vector2(1, 1) },
  }, order);
  const snap = (v, o) => (cell ? o + Math.round((v - o) / cell) * cell : Math.round(v));
  if (opts.cycle && end - start > opts.cycle) console.warn(`petsprite: the program (${(end - start).toFixed(0)} s) is longer than its cycle`);

  ctx.animate((tl) => {
    // the program runs on the video's own clock: a looped scene folds every layer's time into [period, 2 period)
    // (engine timeAt), and the mock's program is written in seconds from the start of the clip
    const t = ctx.realTime?.() ?? tl;
    const s = stateAt(t);
    for (const [n, m] of Object.entries(patchMeshes)) m.visible = !!s && s.patch === n;
    sprite.visible = shadow.visible = !!s?.sprite;
    if (!s?.sprite) return;
    const { sheet, i, flip } = s.sprite;
    const f = frames[sheet][i];
    const hh = heightAt(s.sprite.y);
    // size: 1 where the frame was painted, elsewhere the floor's perspective from that row, in steps of ~4% (1 is a
    // step), the anchor on the grid: the sprite keeps its own pixels between steps; at 1 it shows its own cells exactly
    const raw = hh / heightAt(f.drawn_at[1]) * (opts.k?.[sheet] ?? 1);
    const scale = Math.exp(Math.round(Math.log(raw) / 0.04) * 0.04);
    const x = snap(s.sprite.x, ox), y = snap(s.sprite.y, oy);
    const [tw, th] = f.size, [ax, ay] = f.anchor;
    const axs = flip ? tw - ax : ax;
    const U = sprite.material.uniforms;
    U.tFrame.value = f.tex;
    U.uFlip.value = flip ? 1 : 0;
    U.uScale.value = scale;
    U.uExact.value = Math.abs(scale - 1) < 1e-6 ? 1 : 0;
    U.uTexSize.value.set(f.size[0], f.size[1]);
    const fh = th * scale, pad = 2 * (cell || 8);
    U.uPadK.value = (fh + pad) / fh;
    U.uLift.value = (s.sprite.lift ?? 0) / fh;
    U.uSplit.value = s.sprite.split ?? 0.45;
    U.uRect.value.set(x - axs * scale, y - ay * scale - pad, x + (tw - axs) * scale, y + (th - ay) * scale);
    const sh = shadeAt(sheet, y);
    U.uTint.value.set(...tintAt(x, y + 0.03 * hh, f.lit_at).map((v, c) => v * sh[c]));
    const rx = 0.45 * f.width * scale, ry = Math.max(4, 0.2 * rx * Math.min(1, (y - yh) / (y0 - yh) + 0.3));
    shadow.material.uniforms.uRect.value.set(x - rx, y - ry * 0.75, x + rx, y + ry * 1.25);
    shadow.material.uniforms.uAlpha.value = opts.shadow ?? 0.35;
  });
  return { end, stateAt };
}
