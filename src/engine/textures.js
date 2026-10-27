// Procedural pixel textures at 16 texels per block. Every texture is generated from code + seed (no
// external images). Generators draw into an Img with y pointing down; `bw`/`bh` say how many blocks
// the image spans so UVs stay at one texel density everywhere.
import * as THREE from 'three';
import { Rng } from './rng.js';

export const TPB = 16; // texels per block

export const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
export const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
export const mul = (c, k) => c.map((v) => v * k);
const clamp8 = (v) => (v < 0 ? 0 : v > 255 ? 255 : Math.round(v));
const col = (c) => (typeof c === 'string' ? hex(c) : c);

export class Img {
  constructor(w, h, fill = [0, 0, 0], alpha = 255) {
    this.w = w; this.h = h;
    this.d = new Uint8Array(w * h * 4);
    for (let i = 0; i < w * h; i++) this.d.set([fill[0], fill[1], fill[2], alpha], i * 4);
  }
  set(x, y, c, a = 255) {
    x = Math.floor(x); y = Math.floor(y);
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    const i = (y * this.w + x) * 4;
    this.d[i] = clamp8(c[0]); this.d[i + 1] = clamp8(c[1]); this.d[i + 2] = clamp8(c[2]); this.d[i + 3] = clamp8(a);
  }
  get(x, y) { const i = (y * this.w + x) * 4; return [this.d[i], this.d[i + 1], this.d[i + 2], this.d[i + 3]]; }
  rect(x, y, w, h, c, a = 255) { for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.set(x + i, y + j, c, a); }
  each(fn) { for (let y = 0; y < this.h; y++) for (let x = 0; x < this.w; x++) fn(x, y); }
}

// Smooth value noise on an integer lattice (periodic in `period` cells so textures tile).
function valueNoise(r, period) {
  const g = Array.from({ length: period * period }, () => r.next());
  const at = (i, j) => g[((j % period) + period) % period * period + (((i % period) + period) % period)];
  return (x, y) => {
    const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const a = at(i, j) + (at(i + 1, j) - at(i, j)) * sx;
    const b = at(i, j + 1) + (at(i + 1, j + 1) - at(i, j + 1)) * sx;
    return a + (b - a) * sy;
  };
}

const G = {};

G.noise = (r, { color = '#888888', v = 0.08, blotch = 0.06, bw = 1, bh = 1 }) => {
  const c = col(color);
  const img = new Img(TPB * bw, TPB * bh);
  const n = valueNoise(r, 4);
  img.each((x, y) => img.set(x, y, mul(c, 1 + (r.next() - 0.5) * 2 * v + (n((x / img.w) * 4, (y / img.h) * 4) - 0.5) * 2 * blotch)));
  return { img, bw, bh };
};

// Planks running along u, 4x4 blocks so joints are sparse (one per plank per 2 m), with grain streaks.
G.planks = (r, { color = '#7a4a22', plank = 4, v = 0.14, gap = 0.8 }) => {
  const c = col(color);
  const S = 64;
  const img = new Img(S, S);
  for (let row = 0; row < S / plank; row++) {
    const tone = 1 + (r.next() - 0.5) * 2 * v;
    const j1 = r.int(0, S - 1), j2 = (j1 + r.int(24, 40)) % S;
    const grain = Array.from({ length: plank }, () => 0.94 + r.next() * 0.1);
    for (let y = row * plank; y < (row + 1) * plank; y++) {
      const edge = y === (row + 1) * plank - 1;
      for (let x = 0; x < S; x++) {
        let k = tone * grain[y - row * plank] * (0.97 + r.next() * 0.05);
        if (r.chance(0.02)) k *= 0.88;
        if (edge) k *= gap;
        if (x === j1 || x === j2) k *= 0.8;
        img.set(x, y, mul(c, k));
      }
    }
  }
  return { img, bw: 4, bh: 4 };
};

// Fine furniture wood: grain streaks along u.
G.wood = (r, { color = '#6a3f1f', v = 0.1 }) => {
  const c = col(color);
  const img = new Img(16, 16);
  const rows = Array.from({ length: 16 }, () => 1 + (r.next() - 0.5) * 2 * v);
  img.each((x, y) => img.set(x, y, mul(c, rows[y] * (0.95 + r.next() * 0.08) * (r.chance(0.03) ? 0.85 : 1))));
  return { img, bw: 1, bh: 1 };
};

// Horizontal log wall: each log `h` texels tall with a rounded profile and dark chinking.
G.logs = (r, { color = '#7b4a26', h = 8 }) => {
  const c = col(color);
  const img = new Img(32, 32);
  const profile = (t) => [0.62, 0.95, 1.08, 1.06, 1.02, 0.98, 0.9, 0.78, 0.65, 0.55][Math.min(9, Math.floor(t * 10))];
  for (let row = 0; row < 32 / h; row++) {
    const tone = 0.9 + r.next() * 0.2;
    const crack = Array.from({ length: 32 }, () => r.chance(0.08));
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < 32; x++) {
        let k = tone * profile(y / h) * (0.92 + r.next() * 0.12);
        if (crack[x] && y > 1 && y < h - 2) k *= 0.8;
        if (y === h - 1) k = 0.32;
        img.set(x, row * h + y, mul(c, k));
      }
    }
  }
  return { img, bw: 2, bh: 2 };
};

// Fieldstone: irregular rows of stones with mortar and a bevel.
G.stone = (r, { colors = ['#6d6458', '#7d7366', '#5d564d', '#8a7e6e'], mortar = '#3a332c' }) => {
  const img = new Img(32, 32, hex(mortar));
  let y = 0;
  while (y < 32) {
    const rh = Math.min(32 - y, r.int(4, 7));
    let x = -r.int(0, 6);
    while (x < 32) {
      const w = r.int(5, 10);
      const c = hex(r.pick(colors));
      for (let j = 0; j < rh - 1; j++) for (let i = 0; i < w - 1; i++) {
        let k = 0.92 + r.next() * 0.14;
        if (j === 0 || i === 0) k *= 1.12;
        if (j === rh - 2 || i === w - 2) k *= 0.8;
        img.set((x + i + 32) % 32, y + j, mul(c, k));
      }
      x += w;
    }
    y += rh;
  }
  return { img, bw: 2, bh: 2 };
};

G.brick = (r, { color = '#8a4a32', mortar = '#4a3a30', v = 0.12 }) => {
  const c = col(color), m = col(mortar);
  const img = new Img(32, 32, m);
  for (let row = 0; row < 8; row++) {
    const off = row % 2 ? 4 : 0;
    for (let b = -1; b < 4; b++) {
      const tone = 1 + (r.next() - 0.5) * 2 * v;
      for (let j = 0; j < 3; j++) for (let i = 0; i < 7; i++) img.set((b * 8 + off + i + 32) % 32, row * 4 + j, mul(c, tone * (0.94 + r.next() * 0.1)));
    }
  }
  return { img, bw: 2, bh: 2 };
};

G.tiles = (r, { color = '#c9b79a', grout = '#7a6a58', size = 4 }) => {
  const c = col(color), g = col(grout);
  const img = new Img(16, 16, g);
  for (let ty = 0; ty < 16; ty += size) for (let tx = 0; tx < 16; tx += size) {
    const tone = 0.92 + r.next() * 0.14;
    for (let j = 0; j < size - 1; j++) for (let i = 0; i < size - 1; i++) img.set(tx + i, ty + j, mul(c, tone * (i === 0 || j === 0 ? 1.06 : 1)));
  }
  return { img, bw: 1, bh: 1 };
};

G.fabric = (r, { color = '#8a5a3a', v = 0.06 }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul(c, ((x + y) % 2 ? 0.95 : 1.03) * (1 + (r.next() - 0.5) * 2 * v))));
  return { img, bw: 1, bh: 1 };
};

G.knit = (r, { color = '#a04a3a' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => {
    const cx = x % 4, ry = (y + (cx < 2 ? cx : 3 - cx)) % 4;
    img.set(x, y, mul(c, (ry === 3 ? 0.7 : ry === 0 ? 1.12 : 1) * (0.96 + r.next() * 0.06)));
  });
  return { img, bw: 1, bh: 1 };
};

G.quilt = (r, { palette = ['#8a3b2e', '#c98a3a', '#4e5f6e', '#d8c49a', '#6b4a63'], size = 4 }) => {
  const img = new Img(32, 32);
  for (let ty = 0; ty < 32; ty += size) for (let tx = 0; tx < 32; tx += size) {
    const c = hex(r.pick(palette));
    for (let j = 0; j < size; j++) for (let i = 0; i < size; i++) {
      const seam = i === size - 1 || j === size - 1;
      img.set(tx + i, ty + j, mul(c, (seam ? 0.78 : 1) * (0.95 + r.next() * 0.08)));
    }
  }
  return { img, bw: 2, bh: 2 };
};

G.stripes = (r, { colors = ['#7a3b2a', '#c8a070'], width = 2, dir = 'v', bw = 1, bh = 1 }) => {
  const cs = colors.map(hex);
  const img = new Img(TPB * bw, TPB * bh);
  img.each((x, y) => img.set(x, y, mul(cs[Math.floor((dir === 'v' ? x : y) / width) % cs.length], 0.95 + r.next() * 0.08)));
  return { img, bw, bh };
};

// Original rug designs (concentric steps, kilim zigzags, or banded) spanning bw x bh blocks.
G.rug = (r, { palette = ['#7a2e1e', '#c98a3a', '#3a1c2c', '#d8b98a'], style = 'steps', bw = 4, bh = 3 }) => {
  const p = palette.map(hex);
  const W = Math.round(TPB * bw), H = Math.round(TPB * bh);
  const img = new Img(W, H);
  img.each((x, y) => {
    const ex = Math.min(x, W - 1 - x), ey = Math.min(y, H - 1 - y), edge = Math.min(ex, ey);
    let c;
    if (edge < 2) c = p[2];
    else if (edge < 3) c = p[3];
    else if (style === 'steps') {
      const d = Math.floor((Math.abs(x - W / 2 + 0.5) + Math.abs(y - H / 2 + 0.5)) / 3);
      c = p[[0, 1, 0, 2, 0, 3][d % 6]];
    } else if (style === 'kilim') {
      const band = Math.floor(y / 8);
      const z = Math.abs(((x + (band % 2) * 4) % 8) - 4);
      c = (y % 8) - 2 === z || (y % 8) - 3 === z ? p[band % 2 ? 1 : 3] : p[band % 3 === 0 ? 0 : 2];
    } else {
      c = p[Math.floor(y / 4) % p.length];
    }
    img.set(x, y, mul(c, 0.92 + r.next() * 0.12));
  });
  return { img, bw, bh };
};

// Book spine for a book `h` texels tall (use uvOff [0, 1 - h/16] so the top aligns): two bands near each end.
G.bookspine = (r, { h = 10 }) => {
  const img = new Img(16, 16);
  img.each((x, y) => {
    const band = y === 1 || y === 2 || y === h - 3 || y === h - 2;
    img.set(x, y, mul([206, 206, 206], (band ? 1.22 : 1) * (0.95 + r.next() * 0.07)));
  });
  return { img, bw: 1, bh: 1 };
};
G.pages = (r) => {
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul([226, 214, 186], y % 2 ? 0.92 : 1)));
  return { img, bw: 1, bh: 1 };
};

// Cut-out foliage (alpha-tested). palette: per-pixel color variety (autumn mixes); light: top-left highlight.
G.leaves = (r, { color = '#3f6b34', palette = null, density = 0.62, bw = 1, bh = 1 }) => {
  const cs = palette ? palette.map(hex) : [col(color)];
  const W = TPB * bw, H = TPB * bh;
  const img = new Img(W, H, [0, 0, 0], 0);
  const n = valueNoise(r, 4 * Math.max(bw, bh));
  const n2 = valueNoise(r, 3);
  img.each((x, y) => {
    const v = n((x / 4), (y / 4)) * 0.6 + r.next() * 0.4;
    if (v < 1 - density) return;
    const ci = Math.min(cs.length - 1, Math.floor(n2((x / W) * 3, (y / H) * 3) * cs.length * 1.2 + r.next() * 0.6));
    img.set(x, y, mul(cs[Math.max(0, ci)], 0.72 + v * 0.5), 255);
  });
  return { img, bw, bh, alpha: true };
};

// Single fallen leaf sprite (maple-ish 5-point blob), 16x16, alpha.
G.leafSprite = (r, { palette = ['#d8641e', '#e8a030', '#b8401a', '#c87a28'] }) => {
  const img = new Img(16, 16, [0, 0, 0], 0);
  const c = hex(r.pick(palette));
  const shape = [
    '.......#........',
    '......###.......',
    '..#...###...#...',
    '..##.#####.##...',
    '...#########....',
    '.#############..',
    '..###########...',
    '...#########....',
    '....#######.....',
    '.....#####......',
    '......###.......',
    '.......#........',
    '.......#........',
    '................',
    '................',
    '................',
  ];
  shape.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === '#') img.set(x, y + 2, mul(c, (x === 7 ? 0.75 : 1) * (0.88 + r.next() * 0.2))); }));
  return { img, bw: 1, bh: 1, alpha: true };
};

// Tartan / buffalo plaid. size = check size in texels.
G.plaid = (r, { a = '#8a1e1e', b = '#2a1414', c = null, size = 4, bw = 2, bh = 2 }) => {
  const A = col(a), B = col(b), C = c ? col(c) : null;
  const W = TPB * bw, H = TPB * bh;
  const img = new Img(W, H);
  img.each((x, y) => {
    const u = Math.floor(x / size) % 2, v = Math.floor(y / size) % 2;
    let k = u && v ? B : u || v ? mix(A, B, 0.5) : A;
    if (C && (x % (size * 4) === 1 || y % (size * 4) === 1)) k = C;
    img.set(x, y, mul(k, 0.93 + r.next() * 0.1));
  });
  return { img, bw, bh };
};

// Roof shingles: staggered rows, each shingle with a darker lower lip.
G.shingles = (r, { color = '#5a3a2a', v = 0.14 }) => {
  const c = col(color);
  const img = new Img(32, 32);
  for (let row = 0; row < 8; row++) {
    const off = row % 2 ? 3 : 0;
    for (let s = -1; s < 6; s++) {
      const tone = 1 + (r.next() - 0.5) * 2 * v;
      for (let j = 0; j < 4; j++) for (let i = 0; i < 6; i++) {
        const k = tone * (j === 3 ? 0.62 : i === 5 ? 0.82 : 1) * (0.94 + r.next() * 0.1);
        img.set((s * 6 + off + i + 32) % 32, row * 4 + j, mul(c, k));
      }
    }
  }
  return { img, bw: 2, bh: 2 };
};

// Bark: vertical ridges.
G.bark = (r, { color = '#4a3424' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  const ridge = Array.from({ length: 16 }, () => 0.8 + r.next() * 0.35);
  img.each((x, y) => img.set(x, y, mul(c, ridge[x] * (r.chance(0.08) ? 0.75 : 1) * (0.93 + r.next() * 0.1))));
  return { img, bw: 1, bh: 1 };
};

// Lit window: warm glow with muntins and a soft brighter center (color + emissive).
G.litWindow = (r, { color = '#ffb35c', frame = '#2a1a10', cols = 2, rows = 2, w = 16, h = 16, curtain = '#8a3a2a', curtainW = 3 }) => {
  const c = col(color), f = col(frame), cu = col(curtain);
  const img = new Img(w, h), em = new Img(w, h, [0, 0, 0]);
  img.each((x, y) => {
    const isFrame = x === 0 || y === 0 || x === w - 1 || y === h - 1 || cols > 1 && x % Math.round(w / cols) === 0 || rows > 1 && y % Math.round(h / rows) === 0;
    if (isFrame) { img.set(x, y, f); return; }
    if (x <= curtainW || x >= w - 1 - curtainW) { const k = 0.55 + r.next() * 0.1; img.set(x, y, mul(cu, 1)); em.set(x, y, mul(mix(cu, c, 0.35), k)); return; }
    const d = Math.hypot((x - w / 2) / w, (y - h / 2) / h);
    const k = (1.05 - d * 0.8) * (0.94 + r.next() * 0.08);
    img.set(x, y, mul(c, k)); em.set(x, y, mul(c, k));
  });
  return { img, emissive: em, bw: w / TPB, bh: h / TPB };
};

G.rope = (r, { color = '#a08058' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul(c, ((x + y) % 4 < 2 ? 1.08 : 0.82) * (0.95 + r.next() * 0.08))));
  return { img, bw: 1, bh: 1 };
};

G.pot = (r, { color = '#a0522d' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul(c, (y < 3 ? 1.1 : 1) * (y === 3 ? 0.75 : 1) * (0.94 + r.next() * 0.1))));
  return { img, bw: 1, bh: 1 };
};

G.metal = (r, { color = '#b08a4a' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul(c, (y % 4 === 0 ? 1.15 : 1) * (0.95 + r.next() * 0.06))));
  return { img, bw: 1, bh: 1 };
};

// Glowing lamp shade fabric (used as both color and emissive map).
G.shade = (r, { color = '#ffd9a0' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => img.set(x, y, mul(c, (x % 4 === 0 ? 0.82 : 1) * (0.96 + r.next() * 0.05) * (y > 13 ? 0.9 : 1))));
  return { img, bw: 1, bh: 1 };
};

// Building facade with a window grid. Returns color + emissive (lit windows; walls glow faintly so
// silhouettes read against the sky). panes: draw muntins in windows.
G.facade = (r, {
  wall = '#2b2638', bw = 8, bh = 8, cellW = 8, cellH = 12, winW = 5, winH = 7, lit = 0.35,
  warm = ['#e8913a', '#f0a850', '#d87a30', '#f4b860'], cool = ['#7fa8e8'], coolRatio = 0.08, dark = '#151622',
  wallGlow = 0.12, panes = false,
}) => {
  const W = TPB * bw, H = TPB * bh;
  const wallC = col(wall);
  const img = new Img(W, H, wallC);
  const em = new Img(W, H, [0, 0, 0]);
  img.each((x, y) => {
    const c = mul(wallC, 0.88 + r.next() * 0.2);
    img.set(x, y, c);
    em.set(x, y, mul(c, wallGlow));
  });
  const ox = Math.floor((cellW - winW) / 2), oy = Math.floor((cellH - winH) / 2);
  for (let cy = 0; cy + cellH <= H; cy += cellH) for (let cx = 0; cx + cellW <= W; cx += cellW) {
    const on = r.chance(lit);
    const lc = on ? hex(r.chance(coolRatio) ? r.pick(cool) : r.pick(warm)) : null;
    const curtain = on && r.chance(0.35) ? r.int(1, winW - 2) : -1;
    const level = on ? 0.45 + r.next() * 0.5 : 0;
    const midX = Math.floor(winW / 2), midY = Math.floor(winH * 0.4);
    for (let j = 0; j < winH; j++) for (let i = 0; i < winW; i++) {
      const x = cx + ox + i, y = cy + oy + j;
      const muntin = panes && (i === midX || j === midY);
      if (on && !muntin && !(curtain >= 0 && Math.abs(i - curtain) < Math.max(1, winW / 4))) {
        const k = level * (j === 0 ? 0.8 : 1) * (0.94 + r.next() * 0.08);
        img.set(x, y, mul(lc, k));
        em.set(x, y, mul(lc, k));
      } else if (on && !muntin) {
        img.set(x, y, mul(lc, level * 0.35));
        em.set(x, y, mul(lc, level * 0.35));
      } else {
        img.set(x, y, mul(hex(dark), 0.9 + r.next() * 0.2));
        em.set(x, y, [0, 0, 0]);
      }
    }
    for (let i = -1; i <= winW; i++) { img.set(cx + ox + i, cy + oy + winH, mul(wallC, 1.25)); em.set(cx + ox + i, cy + oy + winH, mul(wallC, wallGlow * 1.5)); }
  }
  return { img, emissive: em, bw, bh };
};

G.fur = (r, { color = '#8a8a8a', color2 = null, stripes = 0, v = 0.08 }) => {
  const c = col(color), c2 = color2 ? col(color2) : mul(c, 0.7);
  const img = new Img(16, 16);
  img.each((x, y) => {
    const s = stripes && (Math.floor((y + (x % 5 === 0 ? 1 : 0)) / stripes) % 2 === 0);
    img.set(x, y, mul(s ? c2 : c, 1 + (r.next() - 0.5) * 2 * v));
  });
  return { img, bw: 1, bh: 1 };
};

// Creature face sized exactly to a head's front face (w x h texels).
G.face = (r, { w = 6, h = 5, fur = '#8a8a8a', muzzle = null, blaze = null, eyes = 'closed', eyeColor = '#2a1a12', nose = '#b06a6a', eyeRow = 2, eyeGap = 2 }) => {
  const f = col(fur);
  const img = new Img(w, h);
  img.each((x, y) => img.set(x, y, mul(f, 0.95 + r.next() * 0.08)));
  if (muzzle) for (let y = h - 2; y < h; y++) for (let x = 1; x < w - 1; x++) img.set(x, y, col(muzzle));
  if (blaze) for (let y = 0; y < h; y++) for (let x = Math.floor((w - 1) / 2); x <= Math.ceil((w - 1) / 2); x++) img.set(x, y, col(blaze));
  const cx = (w - 1) / 2;
  const ex1 = Math.round(cx - eyeGap / 2 - 0.5), ex2 = Math.round(cx + eyeGap / 2 + 0.5);
  const ec = col(eyeColor);
  // Closed eyes read as soft dark lids; open eyes are darker with no highlight (tiny at this density).
  const e = eyes === 'closed' ? mix(ec, f, 0.15) : ec;
  img.set(ex1, eyeRow, e); img.set(ex2, eyeRow, e);
  // Closed eyes: a short lid line (outer corner one texel lower) so they read as "asleep", not a dot.
  if (eyes === 'closed' && w >= 6) { img.set(ex1 - 1, eyeRow + 1, mix(ec, f, 0.45)); img.set(ex2 + 1, eyeRow + 1, mix(ec, f, 0.45)); }
  if (nose) { img.set(Math.floor(cx), eyeRow + 1, col(nose)); if (w % 2 === 0) img.set(Math.ceil(cx), eyeRow + 1, col(nose)); }
  return { img, bw: w / TPB, bh: h / TPB };
};

G.wicker = (r, { color = '#b08850' }) => {
  const c = col(color);
  const img = new Img(16, 16);
  img.each((x, y) => {
    const over = (Math.floor(x / 2) + Math.floor(y / 2)) % 2 === 0;
    img.set(x, y, mul(c, (over ? 1.08 : 0.82) * (0.95 + r.next() * 0.08)));
  });
  return { img, bw: 1, bh: 1 };
};

G.paper = (r, { color = '#e8dcc0', lines = '#9a8a70' }) => {
  const img = new Img(16, 16, col(color));
  for (let y = 3; y < 15; y += 2) for (let x = 2; x < 14; x++) if (r.chance(0.8)) img.set(x, y, col(lines));
  return { img, bw: 1, bh: 1 };
};

// Picture frame canvas: abstract original landscape (sky band, hills, sun), no text or logos.
G.painting = (r, { palette = ['#d8a060', '#9a5a3a', '#4a5a4a', '#2a2a38'], w = 12, h = 10 }) => {
  const p = palette.map(hex);
  const img = new Img(w, h);
  const hill = Array.from({ length: w }, (_, x) => Math.round(h * 0.55 + Math.sin(x * 0.7 + r.next()) * 1.5));
  img.each((x, y) => img.set(x, y, y < hill[x] ? mix(p[0], p[1], y / h) : y < hill[x] + 2 ? p[2] : p[3]));
  img.set(Math.floor(w * 0.7), Math.floor(h * 0.25), [255, 230, 170]);
  return { img, bw: w / TPB, bh: h / TPB };
};

// Detailed leaf cards (alpha), 32x32 design, grayscale-ish so instances tint them.
// shape: 'maple' (5 pointed lobes) | 'round' (oval) | 'needle' (pine sprig).
G.leafCard = (r, { shape = 'maple', size = 32 }) => {
  const S = size;
  const img = new Img(S, S, [0, 0, 0], 0);
  const cx = S / 2 - 0.5, cy = S * 0.56;
  const lobes = shape === 'maple' ? 5 : 0;
  const tw = r.range(-0.15, 0.15);
  const inside = (x, y) => {
    const dx = (x - cx) / (S * 0.5), dy = (cy - y) / (S * 0.5);
    if (shape === 'needle') return Math.abs(dx) < 0.07 + 0.02 * Math.sin(dy * 30) && dy > -0.55 && dy < 0.85 || (Math.abs(dx - dy * 0.0) < 0.6 && Math.abs((dy * 6) % 1) < 0.18 && Math.abs(dx) < 0.5 * (1 - Math.abs(dy - 0.15)) && dy > -0.4 && dy < 0.8);
    const a = Math.atan2(dx, dy) + tw, d = Math.hypot(dx, dy);
    if (shape === 'round') return (dx * dx) / 0.42 + ((dy - 0.12) * (dy - 0.12)) / 0.78 < 0.62;
    // maple: lobed radius with pointed tips; lower lobes shorter; small notch at the stem.
    const lobe = Math.pow(Math.abs(Math.cos((a * lobes) / 2)), 0.55);
    const low = 1 - 0.35 * Math.max(0, -Math.cos(a));
    const teeth = 0.06 * Math.abs(Math.sin(a * 18));
    return d < (0.34 + 0.56 * lobe) * low - teeth && dy > -0.62;
  };
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    if (!inside(x, y)) continue;
    const dx = (x - cx) / (S * 0.5), dy = (cy - y) / (S * 0.5);
    const a = Math.atan2(dx, dy), d = Math.hypot(dx, dy);
    // Veins: midrib + lobe veins (maple), or midrib + side veins (round).
    let vein = Math.abs(dx) < 0.035 && dy > -0.4 ? 1 : 0;
    if (shape === 'maple') for (const va of [-1.25, -2.4, 1.25, 2.4]) { const p = Math.abs(Math.sin(a - va)) * d; if (p < 0.03 && Math.cos(a - va) > 0) vein = 0.8; }
    if (shape === 'round') { const sv = Math.abs(((dy - Math.abs(dx) * 0.8) * 5) % 1); if (sv < 0.12 && Math.abs(dx) > 0.04) vein = 0.5; }
    const edge = inside(x - 1, y) && inside(x + 1, y) && inside(x, y - 1) && inside(x, y + 1) ? 1 : 0.78;
    const k = (0.82 + 0.18 * (1 - d)) * edge * (1 - vein * 0.22) * (0.94 + r.next() * 0.1);
    img.set(x, y, [235 * k, 235 * k, 235 * k], 255);
  }
  if (shape !== 'needle') for (let y = Math.floor(cy); y < S; y++) { const x = Math.round(cx); if (y < cy + S * 0.36) img.set(x, y, [120, 110, 90], 255); }
  return { img, bw: 1, bh: 1, alpha: true };
};

export const generators = G;

// ---------------------------------------------------------------------------------------------
// Hi-res enhancement: keeps the pixel-art design legible (each design texel stays a visible cell)
// but renders it at UPx resolution with soft per-texel shading, material micro-detail (wood grain,
// fabric weave, stone grit), and a normal map derived from the result. This is what moves the look
// from "flat blocks" toward the shader-pack style of the references.
const KIND = {
  planks: 'wood', wood: 'wood', logs: 'wood', shingles: 'wood', bark: 'bark', wicker: 'fabric', rope: 'fabric',
  plaid: 'fabric', fabric: 'fabric', quilt: 'fabric', rug: 'fabric', stripes: 'fabric', knit: 'knit', shade: 'fabric',
  stone: 'stone', brick: 'stone', tiles: 'tile', pot: 'clay', metal: 'metal', noise: 'plain', bookspine: 'paper', pages: 'paper',
  paper: 'paper', painting: 'paint', fur: 'fur', face: 'fur', facade: 'plain', litWindow: 'glow',
};
const NORMAL_STRENGTH = { wood: 2.2, bark: 3.5, fabric: 2.0, knit: 3.0, stone: 3.2, tile: 2.2, clay: 1.4, metal: 1.0, plain: 1.2, paper: 0.8, paint: 0.6, fur: 1.6, glow: 0.3 };
const PILLOW = { wood: 0.35, bark: 0.4, fabric: 0.7, knit: 0.9, stone: 0.9, tile: 0.8, clay: 0.4, metal: 0.2, plain: 0.25, paper: 0.15, paint: 0.1, fur: 0.5, glow: 0 };

function noise1(r, n) { const g = Array.from({ length: n + 1 }, () => r.next()); return (x) => { const i = Math.floor(x) % n, f = x - Math.floor(x), s = f * f * (3 - 2 * f); return g[i] + (g[i + 1] - g[i]) * s; }; }

function enhance(img, kind, r) {
  const { w, h } = img;
  const U = Math.max(1, Math.min(4, Math.floor(4096 / Math.max(w, h))));
  const W = w * U, H = h * U;
  const col = new Float32Array(W * H * 3), height = new Float32Array(W * H), alpha = new Uint8Array(W * H);
  const grainRow = noise1(r, 512), grainFine = Array.from({ length: H }, () => r.next());
  const get = (x, y) => { x = (x + w) % w; y = (y + h) % h; const i = (y * w + x) * 4; return [img.d[i], img.d[i + 1], img.d[i + 2], img.d[i + 3]]; };
  const lum = (c) => (c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722) / 255;
  const pillow = PILLOW[kind] ?? 0.3;
  for (let Y = 0; Y < H; Y++) for (let X = 0; X < W; X++) {
    const x = Math.floor(X / U), y = Math.floor(Y / U);
    const fx = (X % U + 0.5) / U, fy = (Y % U + 0.5) / U;
    const c = get(x, y);
    // Soften toward neighbors near texel borders (0.5 = halfway), keeping cell centers crisp.
    const nx = fx < 0.5 ? get(x - 1, y) : get(x + 1, y), ny = fy < 0.5 ? get(x, y - 1) : get(x, y + 1);
    const bx = Math.max(0, 0.5 - Math.min(fx, 1 - fx) * 2) * 0.45, by = Math.max(0, 0.5 - Math.min(fy, 1 - fy) * 2) * 0.45;
    let rgb = [0, 1, 2].map((k) => c[k] * (1 - bx - by) + nx[k] * bx + ny[k] * by);
    // Material micro-detail.
    let m = 1, hgt = lum(c);
    const rnd = r.next();
    if (kind === 'wood' || kind === 'bark') {
      const g = grainRow((X * 0.035) + Y * 7.3) * 0.6 + grainFine[Y] * 0.4;
      m *= 0.9 + g * 0.2 + (rnd - 0.5) * 0.04;
      hgt += (g - 0.5) * 0.25;
      if (kind === 'bark') hgt += Math.sin(X * 0.9 + grainRow(Y * 0.05) * 6) * 0.08;
    } else if (kind === 'fabric') {
      const weave = ((X >> 0) + (Y >> 0)) % 2 ? 0.95 : 1.04;
      const twill = ((X + Y) % 4 < 2) ? 1.02 : 0.97;
      m *= weave * twill * (0.97 + rnd * 0.05);
      hgt += (weave - 1) * 0.6 + (twill - 1) * 0.6;
    } else if (kind === 'knit') {
      const v = Math.abs(((X % 4) - 1.5)) / 1.5, s = ((Y + Math.round(v * 2)) % 4) / 3;
      m *= 0.86 + s * 0.22; hgt += s * 0.3;
    } else if (kind === 'stone' || kind === 'tile' || kind === 'clay') {
      m *= 0.92 + rnd * 0.14; hgt += (rnd - 0.5) * 0.12;
    } else if (kind === 'fur') {
      const strand = grainRow(X * 2.3 + Math.sin(Y * 0.35) * 2 + Y * 0.15) * 0.65 + rnd * 0.35;
      m *= 0.84 + strand * 0.3; hgt += (strand - 0.5) * 0.35;
    } else if (kind !== 'glow') {
      m *= 0.98 + rnd * 0.04;
    }
    // Pillowy cell relief: raised centers, soft gutters between design texels.
    const edgeD = Math.min(fx, 1 - fx, fy, 1 - fy);
    hgt += pillow * 0.18 * Math.min(1, edgeD * 4);
    // Subtle ambient occlusion in the gutters where neighboring cells are darker.
    const gutter = Math.min(1, edgeD * 4);
    m *= 1 - (1 - gutter) * 0.06 * pillow;
    const i = Y * W + X;
    col[i * 3] = rgb[0] * m; col[i * 3 + 1] = rgb[1] * m; col[i * 3 + 2] = rgb[2] * m;
    height[i] = hgt;
    alpha[i] = c[3];
  }
  const color = new Uint8Array(W * H * 4), normal = new Uint8Array(W * H * 4);
  const s = (NORMAL_STRENGTH[kind] ?? 1) * U * 0.5;
  const hAt = (X, Y) => height[((Y + H) % H) * W + ((X + W) % W)];
  for (let Y = 0; Y < H; Y++) for (let X = 0; X < W; X++) {
    const i = Y * W + X;
    color[i * 4] = clamp8(col[i * 3]); color[i * 4 + 1] = clamp8(col[i * 3 + 1]); color[i * 4 + 2] = clamp8(col[i * 3 + 2]); color[i * 4 + 3] = alpha[i];
    const dx = (hAt(X + 1, Y) - hAt(X - 1, Y)) * s, dy = (hAt(X, Y + 1) - hAt(X, Y - 1)) * s;
    // Image y grows downward but UV v grows upward, so +dy here is -dv.
    const n = [-dx, dy, 1], l = Math.hypot(...n);
    normal[i * 4] = clamp8((n[0] / l * 0.5 + 0.5) * 255); normal[i * 4 + 1] = clamp8((n[1] / l * 0.5 + 0.5) * 255); normal[i * 4 + 2] = clamp8((n[2] / l * 0.5 + 0.5) * 255); normal[i * 4 + 3] = 255;
  }
  return { W, H, color, normal };
}

const cache = new Map();

function dataTexture(data, w, h, { srgb = true, nearest = false } = {}) {
  const flipped = new Uint8Array(data.length);
  for (let y = 0; y < h; y++) flipped.set(data.subarray((h - 1 - y) * w * 4, (h - y) * w * 4), y * w * 4);
  const t = new THREE.DataTexture(flipped, w, h, THREE.RGBAFormat, THREE.UnsignedByteType);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.magFilter = nearest ? THREE.NearestFilter : THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 16;
  t.needsUpdate = true;
  return t;
}

// Returns { map, normalMap?, emissiveMap?, bw, bh, alpha, kind } for a texture spec { name, seed?, ...params }.
export function getTexture(spec, sceneSeed = 1) {
  const key = JSON.stringify(spec) + '|' + sceneSeed;
  if (cache.has(key)) return cache.get(key);
  const { name, seed = 0, ...params } = spec;
  const gen = G[name];
  if (!gen) throw new Error(`unknown texture generator "${name}"`);
  const rng = new Rng(`${sceneSeed}:${name}:${seed}:${JSON.stringify(params)}`);
  const out = gen(rng, params);
  const kind = KIND[name];
  let res;
  if (kind && !out.alpha) {
    const e = enhance(out.img, kind, rng.fork('enhance'));
    res = { map: dataTexture(e.color, e.W, e.H), normalMap: dataTexture(e.normal, e.W, e.H, { srgb: false }), kind };
    if (out.emissive) { const ee = enhance(out.emissive, 'glow', rng.fork('enhance-e')); res.emissiveMap = dataTexture(ee.color, ee.W, ee.H); }
  } else {
    res = { map: dataTexture(out.img.d, out.img.w, out.img.h, { nearest: !out.alpha && !kind }), emissiveMap: out.emissive ? dataTexture(out.emissive.d, out.emissive.w, out.emissive.h) : null, kind: kind ?? 'none' };
  }
  Object.assign(res, { bw: out.bw, bh: out.bh, alpha: !!out.alpha });
  cache.set(key, res);
  return res;
}