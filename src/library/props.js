// Reusable props, built from cuboids. Convention: origin = center of the footprint on the floor,
// front faces +z. 1 block ~ 0.5 m; T = one texel (1/16 block).
import { Rng } from '../engine/rng.js';
import { currentFoliage } from '../engine/foliage.js';

export const T = 1 / 16;

const neutral = '#f2f2f2';
export const mat = {
  wood: (tint = '#6b4226') => ({ tex: { name: 'wood', color: neutral }, tint, rough: 0.5 }),
  planks: (tint = '#7a4a22') => ({ tex: { name: 'planks', color: neutral }, tint, rough: 0.55 }),
  plaster: (tint = '#b8875a') => ({ tex: { name: 'noise', color: neutral, v: 0.05, blotch: 0.06 }, tint, rough: 0.95 }),
  plain: (tint = '#888888', rough = 0.9) => ({ tex: { name: 'noise', color: neutral, v: 0.035, blotch: 0.02 }, tint, rough }),
  fabric: (tint = '#8a5a3a') => ({ tex: { name: 'fabric', color: neutral }, tint, rough: 1 }),
  knit: (tint = '#a04a3a') => ({ tex: { name: 'knit', color: neutral }, tint, rough: 1 }),
  metal: (tint = '#b08a4a', rough = 0.45) => ({ tex: { name: 'metal', color: neutral }, tint, rough }),
  pot: (tint = '#a0522d') => ({ tex: { name: 'pot', color: neutral }, tint, rough: 0.85 }),
  leaves: (tint = '#4f7a3a', density = 0.62) => ({ tex: { name: 'leaves', color: neutral, density }, tint, rough: 0.8 }),
  wicker: (tint = '#b08850') => ({ tex: { name: 'wicker', color: neutral }, tint, rough: 0.9 }),
  glow: (color, k = 3, tex = { name: 'shade', color: '#ffffff' }) => ({ tex, tint: color, emissive: k, emissiveColor: color, cast: false }),
  bulb: (color = '#ffd29a', k = 6) => ({ tex: { name: 'noise', color: '#ffffff', v: 0, blotch: 0 }, tint: color, emissive: k, emissiveColor: color, cast: false, unlit: false }),
};

// --- Furniture -----------------------------------------------------------------------------------

export function table(b, { w = 2, d = 1.2, h = 1.5, top = mat.wood(), leg = top, thick = 2 * T, legW = 2 * T, apron = true } = {}) {
  b.box([-w / 2, h - thick, -d / 2], [w / 2, h, d / 2], top);
  const lx = [-w / 2 + T, w / 2 - T - legW], lz = [-d / 2 + T, d / 2 - T - legW];
  for (const x of lx) for (const z of lz) b.box([x, 0, z], [x + legW, h - thick, z + legW], leg);
  if (apron) {
    for (const z of lz) b.box([lx[0] + legW, h - thick - 3 * T, z], [lx[1], h - thick, z + T], leg);
    for (const x of lx) b.box([x, h - thick - 3 * T, lz[0] + legW], [x + T, h - thick, lz[1]], leg);
  }
  return { topY: h };
}

export function chair(b, { w = 0.9, d = 0.9, seat = 0.9, back = 1.85, m = mat.wood('#5a3620'), cushion = null } = {}) {
  const lw = 2 * T;
  b.box([-w / 2, seat - 2 * T, -d / 2], [w / 2, seat, d / 2], m);
  if (cushion) b.box([-w / 2 + T, seat, -d / 2 + T], [w / 2 - T, seat + 2 * T, d / 2 - T], cushion);
  for (const [x, z] of [[-w / 2, -d / 2], [w / 2 - lw, -d / 2], [-w / 2, d / 2 - lw], [w / 2 - lw, d / 2 - lw]]) b.box([x, 0, z], [x + lw, seat - 2 * T, z + lw], m);
  b.box([-w / 2, seat, -d / 2], [-w / 2 + lw, back, -d / 2 + lw], m);
  b.box([w / 2 - lw, seat, -d / 2], [w / 2, back, -d / 2 + lw], m);
  for (const y of [back - 4 * T, seat + 0.45]) b.box([-w / 2 + lw, y, -d / 2], [w / 2 - lw, y + 3 * T, -d / 2 + lw], m);
}

export function armchair(b, { w = 1.7, d = 1.6, fabric = mat.fabric('#7a3b2a'), leg = mat.wood('#3a2416'), seatH = 0.8 } = {}) {
  const legH = 3 * T;
  for (const [x, z] of [[-w / 2 + T, -d / 2 + T], [w / 2 - 3 * T, -d / 2 + T], [-w / 2 + T, d / 2 - 3 * T], [w / 2 - 3 * T, d / 2 - 3 * T]]) b.box([x, 0, z], [x + 2 * T, legH, z + 2 * T], leg);
  b.box([-w / 2, legH, -d / 2], [w / 2, seatH - 4 * T, d / 2], fabric);
  b.box([-w / 2 + 0.3, seatH - 4 * T, -d / 2 + 0.35], [w / 2 - 0.3, seatH + 2 * T, d / 2 - T], fabric);
  b.box([-w / 2, legH, -d / 2], [w / 2, 2.1, -d / 2 + 0.35], fabric);
  b.box([-w / 2, seatH - 4 * T, -d / 2 + 0.35], [-w / 2 + 0.3, 1.25, d / 2], fabric);
  b.box([w / 2 - 0.3, seatH - 4 * T, -d / 2 + 0.35], [w / 2, 1.25, d / 2], fabric);
}

export function cushion(b, { w = 0.7, h = 0.6, d = 0.22, m = mat.fabric('#c98a3a'), rot = 0, tilt = 0.25 } = {}) {
  b.at([0, 0, 0], rot, () => b.box([-w / 2, 0, -d / 2], [w / 2, h, d / 2], m), { rotX: -tilt });
}

// Throw blanket draped over an edge: flat part + hanging part.
export function throwBlanket(b, { w = 1.2, flat = 0.6, hang = 0.6, m = mat.knit('#a04a3a') } = {}) {
  b.box([-w / 2, 0, -flat], [w / 2, 2 * T, 0], m);
  b.box([-w / 2, -hang, 0], [w / 2, 2 * T, 2 * T], m);
}

// --- Books -------------------------------------------------------------------------------------

export const BOOK_PALETTE = ['#7a2e24', '#2f4a5a', '#5a6a3a', '#8a6a2e', '#4a2e4a', '#9a4a2a', '#2e3a2e', '#6a4a3a', '#a08a5a', '#3a3a5a'];

function bookBox(b, x0, y0, z0, w, h, d, tint, spineFace = 'pz') {
  const ht = Math.max(4, Math.min(16, Math.round(h * 16)));
  const cover = mat.plain(tint, 0.8);
  const spine = { tex: { name: 'bookspine', h: ht }, tint, rough: 0.7 };
  const pages = { tex: { name: 'pages' }, tint: '#ffffff', rough: 0.95 };
  const faces = { py: pages, ny: cover, [spineFace]: spine, [spineFace === 'pz' ? 'nz' : 'pz']: pages };
  b.box([x0, y0, z0], [x0 + w, y0 + h, z0 + d], cover, { faces, uvOff: [0, 1 - ht / 16] });
}

// Row of upright books between x0 and x1 standing on y, spines facing +z at zFront.
export function booksRow(b, { x0, x1, y, zFront, depth = 0.55, rng, palette = BOOK_PALETTE, fill = 0.9, maxH = 11, minH = 7 }) {
  let x = x0 + rng.range(0, 2) * T;
  while (x < x1 - 2 * T) {
    if (rng.chance(1 - fill)) { x += rng.int(2, 5) * T; continue; }
    if (rng.chance(0.08) && x1 - x > 0.5) {
      const n = rng.int(2, 4);
      let yy = y;
      for (let i = 0; i < n; i++) {
        const th = rng.int(2, 3) * T;
        bookBox(b, x + rng.int(0, 1) * T, yy, zFront - depth * 0.9, 0.42, th, depth * 0.9, rng.pick(palette), 'pz');
        yy += th;
      }
      x += 0.5;
      continue;
    }
    const w = rng.int(2, 4) * T, h = rng.int(minH, maxH) * T, d = depth * rng.range(0.82, 1);
    if (x + w > x1) break;
    bookBox(b, x, y, zFront - d, w, h, d, rng.pick(palette));
    x += w;
  }
}

export function bookStack(b, { n = 4, rng, palette = BOOK_PALETTE } = {}) {
  let y = 0;
  for (let i = 0; i < n; i++) {
    const th = rng.int(2, 4) * T, w = rng.int(6, 9) * T, d = rng.int(5, 7) * T;
    b.at([rng.range(-1, 1) * T, 0, rng.range(-1, 1) * T], rng.range(-0.25, 0.25), () => bookBox(b, -w / 2, y, -d / 2, w, th, d, rng.pick(palette)));
    y += th;
  }
  return y;
}

export function bookshelf(b, { w = 2, h = 4, d = 0.7, shelves = 5, m = mat.wood('#4e2e1a'), rng, palette, fill = 0.88, back = true } = {}) {
  const t = 2 * T;
  b.box([-w / 2, 0, -d / 2], [-w / 2 + t, h, d / 2], m);
  b.box([w / 2 - t, 0, -d / 2], [w / 2, h, d / 2], m);
  b.box([-w / 2, h - t, -d / 2], [w / 2, h, d / 2], m);
  if (back) b.box([-w / 2 + t, 0, -d / 2], [w / 2 - t, h - t, -d / 2 + T], m);
  b.box([-w / 2 + t, 0, -d / 2], [w / 2 - t, 3 * T, d / 2], m);
  const span = (h - 3 * T - t) / shelves;
  for (let i = 0; i < shelves; i++) {
    const y = 3 * T + i * span;
    if (i > 0) b.box([-w / 2 + t, y - t, -d / 2], [w / 2 - t, y, d / 2], m);
    booksRow(b, { x0: -w / 2 + t, x1: w / 2 - t, y, zFront: d / 2 - T, depth: d - 3 * T, rng, palette, fill, maxH: Math.min(12, Math.floor((span - t) * 16) - 1) });
  }
}

// --- Plants ------------------------------------------------------------------------------------

// Leaf cards for a plant clump; leaf is a material spec (its palette or tint gives the colors).
function plantLeaves(b, c, r, leaf, rng, cover = 3) {
  const fol = currentFoliage();
  const pal = leaf?.palette ?? leaf?.tex?.palette ?? [leaf?.tint ?? '#4f7a3a'];
  const palette = pal.length > 1 ? pal : [pal[0], shadeHex(pal[0], 0.8), shadeHex(pal[0], 1.15)];
  if (fol) fol.cloud({ c: b.world(c), r, squash: 0.85, size: Math.max(0.09, r * 0.45), palette, rng, cover, shape: leaf?.shape ?? 'round', inner: 0.2 });
  else b.at(c, 0, () => b.box([-r, -r * 0.6, -r], [r, r * 0.6, r], leaf));
}
const shadeHex = (h, k) => '#' + [1, 3, 5].map((i) => Math.max(0, Math.min(255, Math.round(parseInt(h.slice(i, i + 2), 16) * k))).toString(16).padStart(2, '0')).join('');

export function pottedPlant(b, { rng, pot = mat.pot(), leaf = mat.leaves(), potW = 0.45, potH = 0.42, height = 1.1, spread = 0.45, clumps = 7, clump = [0.22, 0.4] } = {}) {
  b.box([-potW / 2, 0, -potW / 2], [potW / 2, potH, potW / 2], pot);
  b.box([-potW / 2 - T, potH - 2 * T, -potW / 2 - T], [potW / 2 + T, potH, potW / 2 + T], pot);
  b.box([-potW / 2 + T, potH - T, -potW / 2 + T], [potW / 2 - T, potH - T / 2, potW / 2 - T], mat.plain('#2a1a10'));
  const stem = mat.plain('#3a4a2a');
  for (let i = 0; i < clumps; i++) {
    const s = rng.range(clump[0], clump[1]);
    const a = rng.range(0, Math.PI * 2), r = rng.range(0, spread) * (i / clumps);
    const x = Math.cos(a) * r, z = Math.sin(a) * r, y = potH + rng.range(0.15, 1) * (height - potH);
    b.box([x - T / 2, potH, z - T / 2], [x + T / 2, y, z + T / 2], stem);
    plantLeaves(b, [x, y + s * 0.15, z], s * 0.55, leaf, rng);
  }
}

// Hanging planter: three cords from y=0 down to a pot, with trailing vines below.
export function hangingPlant(b, { rng, drop = 0.9, pot = mat.pot('#8a5a3a'), leaf = mat.leaves('#5a8a42'), vines = 6, maxLen = 1.4 } = {}) {
  const cord = mat.plain('#c8b088');
  const py = -drop;
  for (const [x, z] of [[-0.18, 0], [0.12, 0.14], [0.12, -0.14]]) b.box([x * 0.2 - T / 4, py + 0.3, z * 0.2 - T / 4], [x * 0.2 + T / 4, 0, z * 0.2 + T / 4], cord);
  b.box([-0.22, py, -0.22], [0.22, py + 0.3, 0.22], pot);
  plantLeaves(b, [0, py + 0.38, 0], 0.32, leaf, rng);
  for (let i = 0; i < vines; i++) {
    const a = (i / vines) * Math.PI * 2 + rng.range(-0.3, 0.3);
    const x = Math.cos(a) * 0.26, z = Math.sin(a) * 0.26;
    const len = rng.range(0.3, maxLen);
    for (let y = 0; y < len; y += 0.16) {
      const s = rng.range(0.1, 0.17);
      plantLeaves(b, [x + rng.range(-1, 1) * T, py + 0.1 - y - s / 2, z + rng.range(-1, 1) * T], s * 0.6, leaf, rng, 1.6);
    }
  }
}

// --- Lights ------------------------------------------------------------------------------------

// Table lamp; returns the world position of the bulb (put the PointLight there).
export function tableLamp(b, { h = 0.95, shadeW = 0.5, shadeH = 0.38, base = mat.metal('#6a4a2a'), shadeColor = '#ffc98a', glow = 2.2 } = {}) {
  b.box([-0.14, 0, -0.14], [0.14, 2 * T, 0.14], base);
  b.box([-T, 2 * T, -T], [T, h - shadeH * 0.6, T], base);
  b.box([-shadeW / 2, h - shadeH, -shadeW / 2], [shadeW / 2, h, shadeW / 2], mat.glow(shadeColor, glow), { skip: ['py', 'ny'] });
  return b.world([0, h - shadeH * 0.55, 0]);
}

export function floorLamp(b, { h = 3.2, shadeW = 0.7, shadeH = 0.5, base = mat.metal('#4a3a2a'), shadeColor = '#ffc98a', glow = 2 } = {}) {
  b.box([-0.22, 0, -0.22], [0.22, 2 * T, 0.22], base);
  b.box([-T, 2 * T, -T], [T, h - shadeH * 0.5, T], base);
  b.box([-shadeW / 2, h - shadeH, -shadeW / 2], [shadeW / 2, h, shadeW / 2], mat.glow(shadeColor, glow), { skip: ['py', 'ny'] });
  return b.world([0, h - shadeH * 0.5, 0]);
}

// Pendant: origin at the ceiling attachment; dark metal shade open at the bottom with a glowing bulb.
export function pendantLamp(b, { drop = 1.4, shadeW = 0.6, shadeH = 0.32, shade = mat.metal('#2e3a34', 0.5), bulbColor = '#ffd7a0', glow = 7 } = {}) {
  b.box([-T / 2, -drop + shadeH, -T / 2], [T / 2, 0, T / 2], mat.plain('#1a1410'));
  b.box([-0.08, -drop + shadeH, -0.08], [0.08, -drop + shadeH + 0.08, 0.08], shade);
  b.box([-shadeW / 2, -drop, -shadeW / 2], [shadeW / 2, -drop + shadeH, shadeW / 2], shade, { skip: ['ny'] });
  b.box([-0.08, -drop + 0.02, -0.08], [0.08, -drop + 0.16, 0.08], mat.bulb(bulbColor, glow));
  return b.world([0, -drop - 0.05, 0]);
}

// String lights along a polyline with catenary-ish sag; bulbs are small emissive cubes.
export function stringLights(b, { points, n = 20, sag = 0.18, colors = ['#ffcf7a', '#ffb060', '#ffe0a0'], glow = 5, rng }) {
  const wire = mat.plain('#1e1810');
  const segs = points.length - 1;
  const lerp = (a, c, t) => a.map((v, i) => v + (c[i] - v) * t);
  for (let s = 0; s < segs; s++) {
    const A = points[s], B = points[s + 1];
    const steps = 40;
    for (let k = 0; k <= steps; k++) {
      const t = k / steps;
      const p = lerp(A, B, t); p[1] -= sag * 4 * t * (1 - t);
      b.box([p[0] - T / 4, p[1] - T / 4, p[2] - T / 4], [p[0] + T / 4, p[1] + T / 4, p[2] + T / 4], wire);
    }
    const per = Math.max(1, Math.round(n / segs));
    for (let k = 0; k < per; k++) {
      const t = (k + 0.5) / per;
      const p = lerp(A, B, t); p[1] -= sag * 4 * t * (1 - t) + T;
      const c = colors[(s * per + k) % colors.length];
      b.box([p[0] - T, p[1] - 2 * T, p[2] - T], [p[0] + T, p[1], p[2] + T], mat.bulb(c, glow * (rng ? rng.range(0.85, 1.1) : 1)));
    }
  }
}

export function candle(b, { h = 0.22, w = 0.12, color = '#e8dcc0', flame = '#ffb347' } = {}) {
  b.box([-w / 2, 0, -w / 2], [w / 2, h, w / 2], mat.plain(color, 0.6));
  b.box([-T / 2, h, -T / 2], [T / 2, h + T, T / 2], mat.plain('#1a1410'));
  b.box([-T, h + T, -T], [T, h + 3.5 * T, T], mat.bulb(flame, 8));
  return b.world([0, h + 2.5 * T, 0]);
}

// --- Small things ------------------------------------------------------------------------------

export function rug(b, { w = 4, d = 3, palette, style = 'steps' } = {}) {
  const spec = { tex: { name: 'rug', palette, style, bw: w, bh: d }, tint: '#ffffff', rough: 1 };
  b.box([-w / 2, 0, -d / 2], [w / 2, T, d / 2], spec);
}

export function mug(b, { tint = '#c8b8a0' } = {}) {
  const m = mat.plain(tint, 0.5);
  b.box([-1.5 * T, 0, -1.5 * T], [1.5 * T, 3 * T, 1.5 * T], m);
  b.box([1.5 * T, 0.75 * T, -T / 2], [2.5 * T, 2.25 * T, T / 2], m);
  b.box([-1.25 * T, 2.6 * T, -1.25 * T], [1.25 * T, 2.8 * T, 1.25 * T], mat.plain('#3a2210', 0.3));
  return b.world([0, 3 * T, 0]);
}

export function teapot(b, { tint = '#5a7a7a' } = {}) {
  const m = mat.plain(tint, 0.4);
  b.box([-3 * T, 0, -2.5 * T], [3 * T, 4 * T, 2.5 * T], m);
  b.box([-2 * T, 4 * T, -1.5 * T], [2 * T, 5 * T, 1.5 * T], m);
  b.box([-0.5 * T, 5 * T, -0.5 * T], [0.5 * T, 5.6 * T, 0.5 * T], m);
  b.box([3 * T, 1.5 * T, -0.5 * T], [5 * T, 3 * T, 0.5 * T], m);
  b.box([-4.5 * T, 1 * T, -0.5 * T], [-3 * T, 3.5 * T, 0.5 * T], m);
  return b.world([4.5 * T, 3 * T, 0]);
}

export function pictureFrame(b, { w = 0.75, h = 0.6, frame = mat.wood('#3a2416'), palette, depth = T } = {}) {
  const tw = Math.round((w - 4 * T) * 16), th = Math.round((h - 4 * T) * 16);
  b.box([-w / 2, 0, 0], [w / 2, h, depth], frame);
  b.box([-w / 2 + 2 * T, 2 * T, depth], [w / 2 - 2 * T, h - 2 * T, depth + T / 4], { tex: { name: 'painting', w: tw, h: th, palette }, tint: '#ffffff', rough: 0.7 });
}

export function crate(b, { w = 0.9, h = 0.7, d = 0.8, m = mat.wood('#8a6a42') } = {}) {
  b.box([-w / 2, 0, -d / 2], [w / 2, h, d / 2], m);
  b.box([-w / 2 - T / 2, h * 0.45, -d / 2 - T / 2], [w / 2 + T / 2, h * 0.55, d / 2 + T / 2], mat.wood('#6a4a2a'));
}

// Window frame for an opening spanning x0..x1, y0..y1 in a wall whose inner face is at z (room toward +z).
export function windowFrame(b, { x0, x1, y0, y1, z, cols = 2, rows = 2, m = mat.wood('#3a2416'), sill = true, sillDepth = 0.35, bar = 2 * T, reveal = 0.4 }) {
  b.box([x0, y1 - bar, z - reveal / 2 - bar / 2], [x1, y1, z - reveal / 2 + bar / 2], m);
  b.box([x0, y0, z - reveal / 2 - bar / 2], [x1, y0 + bar, z - reveal / 2 + bar / 2], m);
  b.box([x0, y0, z - reveal / 2 - bar / 2], [x0 + bar, y1, z - reveal / 2 + bar / 2], m);
  b.box([x1 - bar, y0, z - reveal / 2 - bar / 2], [x1, y1, z - reveal / 2 + bar / 2], m);
  for (let c = 1; c < cols; c++) { const x = x0 + ((x1 - x0) * c) / cols; b.box([x - T, y0, z - reveal / 2 - T], [x + T, y1, z - reveal / 2 + T], m); }
  for (let r = 1; r < rows; r++) { const y = y0 + ((y1 - y0) * r) / rows; b.box([x0, y - T, z - reveal / 2 - T], [x1, y + T, z - reveal / 2 + T], m); }
  if (sill) b.box([x0 - 2 * T, y0 - 2 * T, z - reveal], [x1 + 2 * T, y0, z + sillDepth], m);
  return { glassZ: z - reveal / 2 - 1.5 * T, x0: x0 + bar, x1: x1 - bar, y0: y0 + bar, y1: y1 - bar };
}

export { Rng };

// Stone fireplace against a wall (back at z=0, front toward +z). Returns { firePos, lightPos, mantelY }.
export function fireplace(b, { w = 3.2, h = 5, d = 1.1, open = [1.6, 1.3], stone = '#8a8072', mantel = mat.wood('#4a2c18'), chimneyW = 2.2 } = {}) {
  const st = { tex: { name: 'stone' }, tint: stone, rough: 1 };
  const [ow, oh] = open;
  b.box([-w / 2, 0, 0], [-ow / 2, 2.1, d], st);
  b.box([ow / 2, 0, 0], [w / 2, 2.1, d], st);
  b.box([-ow / 2, oh, 0], [ow / 2, 2.1, d], st);
  b.box([-ow / 2, 0, 0], [ow / 2, oh, 0.2], { ...st, tint: '#2a201a' });
  b.box([-ow / 2, 0, 0.2], [-ow / 2 + 0.05, oh, d], { ...st, tint: '#3a2e26' });
  b.box([ow / 2 - 0.05, 0, 0.2], [ow / 2, oh, d], { ...st, tint: '#3a2e26' });
  b.box([-ow / 2, oh - 0.05, 0.2], [ow / 2, oh, d], { ...st, tint: '#2a201a' });
  b.box([-w / 2 - 0.3, 0, d], [w / 2 + 0.3, 0.25, d + 0.6], st); // hearth
  b.box([-w / 2 - 0.25, 2.1, -0.05], [w / 2 + 0.25, 2.35, d + 0.35], mantel);
  b.box([-chimneyW / 2, 2.35, 0], [chimneyW / 2, h, d * 0.8], st);
  // Grate + logs.
  const ironM = mat.plain('#1c1814', 0.6);
  for (let x = -ow / 2 + 0.25; x < ow / 2 - 0.2; x += 0.22) b.box([x, 0.02, d - 0.3], [x + 0.06, 0.38, d - 0.24], ironM);
  b.box([-ow / 2 + 0.2, 0.02, d - 0.3], [ow / 2 - 0.2, 0.08, 0.35], ironM);
  const logM = { tex: { name: 'bark', color: '#f2f2f2' }, tint: '#4a3020', rough: 1 };
  b.box([-0.55, 0.08, 0.45], [0.5, 0.3, 0.68], logM);
  b.at([0, 0.3, 0.55], 0.35, () => b.box([-0.45, 0, -0.1], [0.45, 0.2, 0.1], logM));
  b.box([-0.4, 0.06, 0.4], [0.4, 0.1, 0.8], mat.bulb('#ff4a10', 1.1)); // embers
  return { firePos: b.world([0, 0.12, 0.6]), lightPos: b.world([0, 0.7, d + 0.2]), mantelY: 2.35 };
}

// Blocky pumpkin/gourd: segmented body + stem.
export function pumpkin(b, { s = 0.5, tint = '#d86a1e' } = {}) {
  const m = mat.plain(tint, 0.7);
  b.box([-s / 2, 0, -s * 0.4], [s / 2, s * 0.75, s * 0.4], m);
  b.box([-s * 0.4, 0, -s / 2], [s * 0.4, s * 0.75, s / 2], { ...m, tint: '#c25a18' });
  b.box([-s * 0.06, s * 0.75, -s * 0.06], [s * 0.06, s * 0.95, s * 0.06], mat.plain('#4a5a2a', 0.8));
}

export function chest(b, { w = 1.4, h = 0.9, d = 0.8, m = mat.wood('#6a4428') } = {}) {
  b.box([-w / 2, 0, -d / 2], [w / 2, h * 0.7, d / 2], m);
  b.box([-w / 2 - T / 2, h * 0.7, -d / 2 - T / 2], [w / 2 + T / 2, h, d / 2 + T / 2], m);
  const band = mat.plain('#2a2420', 0.5);
  for (const x of [-w / 2 + 0.15, w / 2 - 0.25]) b.box([x, 0, -d / 2 - T / 2], [x + 0.1, h + T / 2, d / 2 + T / 2], band);
  b.box([-0.08, h * 0.55, d / 2], [0.08, h * 0.78, d / 2 + T], mat.metal('#c8a050'));
}

export function logBasket(b, { w = 0.9, d = 0.6, h = 0.55, rng } = {}) {
  b.box([-w / 2, 0, -d / 2], [w / 2, h, d / 2], mat.wicker('#9a7040'));
  const logM = { tex: { name: 'bark', color: '#f2f2f2' }, tint: '#5a3a24', rough: 1 };
  for (let i = 0; i < 5; i++) {
    const x = -w / 2 + 0.12 + (i % 3) * 0.24, y = h - 0.05 + Math.floor(i / 3) * 0.16;
    b.box([x, y, -d / 2 - 0.05], [x + 0.16, y + 0.16, d / 2 + 0.05], { ...logM, tint: rng ? rng.pick(['#5a3a24', '#6a4a2a', '#4a3020']) : '#5a3a24' });
  }
}

// Bed with plaid quilt and pillows; head against z = -d/2.
export function bed(b, { w = 2.6, d = 4.2, frame = mat.wood('#4a2c18'), quilt = { tex: { name: 'plaid', a: '#9a2a22', b: '#2a1414' }, tint: '#ffffff', rough: 1 }, sheet = mat.fabric('#d8ccb8'), pillow = { tex: { name: 'plaid', a: '#a83a2a', b: '#3a1a14', size: 2, bw: 1, bh: 1 }, tint: '#ffffff', rough: 1 } } = {}) {
  b.box([-w / 2, 0, -d / 2], [w / 2, 0.55, d / 2], frame);
  b.box([-w / 2, 0.55, -d / 2], [w / 2, 1.0, d / 2 - 0.1], sheet);
  b.box([-w / 2 - T, 0.85, -d / 2 + 1.1], [w / 2 + T, 1.08, d / 2], quilt);
  b.box([-w / 2 - T, 0.3, d / 2 - 0.1], [w / 2 + T, 1.08, d / 2 + T], quilt);
  for (const s of [-1, 1]) b.at([s * w / 4, 1.0, -d / 2 + 0.45], s * 0.1, () => b.box([-0.5, 0, -0.25], [0.5, 0.42, 0.25], pillow), { rotX: -0.35 });
  b.box([-w / 2, 0, -d / 2 - 0.25], [w / 2, 2.0, -d / 2], frame);
  b.box([-w / 2, 0, d / 2], [w / 2, 1.2, d / 2 + 0.2], frame);
}
