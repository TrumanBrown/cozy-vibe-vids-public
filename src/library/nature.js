// Nature: broadleaf + pine trees, voxel hills with forest cover, blocky clouds.
// All geometry goes through the Builder (merged per material, tinted per box).
import { mat, T } from './props.js';
import { currentFoliage } from '../engine/foliage.js';

const AUTUMN = ['#c8501c', '#e0701e', '#f0982c', '#b83c1a', '#e08428', '#d0601c', '#e8a838'];
const SUMMER = ['#3f6b34', '#4f7a3a', '#5a8a42', '#355e2e'];
export const LEAF_PALETTES = { autumn: AUTUMN, summer: SUMMER };

// Foliage material: cutout texture tinted per box, plus a faint self-glow in the palette's mid color
// (stylized sky/subsurface light) so canopies stay saturated at night instead of going muddy.
const leafMat = (palette, density = 0.82, glow = 0.42) => ({
  tex: { name: 'leaves', color: '#f2f2f2', palette: ['#ffffff', '#b8b8b8', '#e0d8c8', '#8c8c8c'], density }, tint: palette[0], rough: 0.85,
  emissive: glow, emissiveColor: palette[Math.floor(palette.length / 2)], cast: true,
});
const shade = (hexc, k) => '#' + [1, 3, 5].map((i) => Math.max(0, Math.min(255, Math.round(parseInt(hexc.slice(i, i + 2), 16) * k))).toString(16).padStart(2, '0')).join('');

// Leaf blob: a dark opaque core (so canopies never look see-through) wrapped in leaf-card clumps:
// a few overlapping sub-clouds give the soft "cauliflower" canopy shape of the references.
// `leaf` = leaf card size in blocks (bigger for distant trees => fewer cards).
// `exclude(x, y, z)` (world coords) skips leaves, e.g. inside a room.
export function leafBlob(b, { c, r = 2, rng, palette = AUTUMN, leaf = 0.5, cover = 5, core = true, dark = 0.3, squash = 0.7, exclude = null, shape = 'maple', clumps = null }) {
  const fol = currentFoliage();
  const wc = b.world(c);
  const ry = r * squash;
  if (core && (!exclude || !exclude(...wc))) {
    const k = 0.42;
    b.box([c[0] - r * k, c[1] - ry * k, c[2] - r * k], [c[0] + r * k, c[1] + ry * k, c[2] + r * k], { ...mat.plain(shade(palette[palette.length - 1], dark), 1), bevel: 0 });
  }
  if (!fol) return;
  const n = clumps ?? Math.max(1, Math.min(6, Math.round(r / 1.6)));
  if (n === 1) { fol.cloud({ c: wc, r, squash, size: leaf, palette, rng, cover, shape, exclude }); return; }
  fol.cloud({ c: wc, r: r * 0.82, squash, size: leaf, palette, rng, cover: cover * 0.5, shape, exclude });
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + rng.range(-0.4, 0.4);
    const sc = [wc[0] + Math.cos(a) * r * 0.45, wc[1] + rng.range(-0.1, 0.35) * ry, wc[2] + Math.sin(a) * r * 0.45];
    fol.cloud({ c: sc, r: r * rng.range(0.5, 0.65), squash: 0.8, size: leaf, palette, rng, cover, shape, exclude, inner: 0.7 });
  }
}

// Bushy plant / potted foliage: leaf cards around stems (world-space via the builder transform).
export function leafTuft(b, { c, r = 0.4, rng, palette = ['#4f7a3a', '#5a8a42', '#3f6b34'], leaf = 0.16, cover = 3, shape = 'round', squash = 0.8 }) {
  const fol = currentFoliage();
  if (fol) fol.cloud({ c: b.world(c), r, squash, size: leaf, palette, rng, cover, shape, inner: 0.25 });
}

// Broadleaf tree (maple/oak style): tapering trunk, stepped branches, canopy blobs at branch tips.
export function broadleaf(b, { h = 16, rng, palette = AUTUMN, trunk = '#3e2c20', spread = 1, blobs = 7, canopyBase = 0.45, leaf = 1.0, exclude = null, midBlob = true, crownY = 0.84 }) {
  const bark = { tex: { name: 'bark', color: '#f2f2f2' }, tint: trunk, rough: 1 };
  const tw = Math.max(0.6, h * 0.06);
  for (let i = 0; i < 4; i++) {
    const w = tw * (1 - i * 0.15), y0 = (h * 0.75 * i) / 4, y1 = (h * 0.75 * (i + 1)) / 4;
    b.box([-w / 2, y0, -w / 2], [w / 2, y1, w / 2], bark);
  }
  b.box([-tw * 0.85, 0, -tw * 0.3], [tw * 0.85, 0.8, tw * 0.3], bark);
  b.box([-tw * 0.3, 0, -tw * 0.85], [tw * 0.3, 0.8, tw * 0.85], bark);
  const tips = [];
  for (let i = 0; i < blobs; i++) {
    const a = (i / blobs) * Math.PI * 2 + rng.range(-0.4, 0.4);
    const y = h * (canopyBase + rng.range(0, 0.3));
    const reach = h * 0.24 * spread * rng.range(0.65, 1);
    const steps = Math.max(3, Math.round(reach / 1.2));
    for (let s = 0; s < steps; s++) {
      const k = (s + 1) / steps, bw = Math.max(0.2, tw * 0.3 * (1 - k * 0.55));
      const x = Math.cos(a) * reach * k, z = Math.sin(a) * reach * k, yy = y - h * 0.14 + k * h * 0.14;
      b.box([x - bw, yy - bw, z - bw], [x + bw, yy + bw, z + bw], bark);
    }
    tips.push([Math.cos(a) * reach, y + h * 0.02, Math.sin(a) * reach, h * 0.15 * spread * rng.range(0.8, 1.15)]);
  }
  tips.push([0, h * Math.max(crownY, canopyBase + 0.16), 0, h * 0.19 * spread]);
  if (midBlob) tips.push([0, h * 0.62, 0, h * 0.17 * spread]);
  for (const [x, y, z, r] of tips) leafBlob(b, { c: [x, y, z], r, rng, palette, leaf: leaf * 0.6, exclude });
  return { top: h, crown: tips };
}

// Pine: stepped square tiers with cutout needles; `far` uses solid tiers (cheaper, reads as silhouette).
export function pine(b, { h = 14, rng, color = '#1e3324', trunk = '#2a1c14', far = false }) {
  const tw = Math.max(0.35, h * 0.05);
  b.box([-tw / 2, 0, -tw / 2], [tw / 2, h * 0.3, tw / 2], far ? mat.plain(trunk, 1) : { tex: { name: 'bark', color: '#f2f2f2' }, tint: trunk, rough: 1 });
  const tiers = Math.max(3, Math.round(h / 2.6));
  const needles = far ? mat.plain(color, 1) : { tex: { name: 'leaves', color: '#f2f2f2', density: 0.92 }, tint: color, rough: 0.9 };
  for (let i = 0; i < tiers; i++) {
    const k = i / tiers;
    const y = h * 0.15 + k * h * 0.8;
    const r = (1 - k) * h * 0.2 + 0.25;
    const th = (h * 0.85) / tiers + 0.25;
    b.at([0, 0, 0], rng.range(0, Math.PI / 2), () => b.box([-r, y, -r], [r, y + th, r], { ...needles, tint: shade(color, 0.85 + k * 0.35) }));
  }
  b.box([-0.15, h * 0.95, -0.15], [0.15, h * 1.05, 0.15], { ...needles, tint: shade(color, 1.2) });
  // Needle sprigs over the tiers (near trees only) so silhouettes read soft instead of boxy.
  const fol = currentFoliage();
  if (fol) for (let i = 0; i < tiers; i++) {
    const k = i / tiers, y = h * 0.15 + k * h * 0.8, r = (1 - k) * h * 0.2 + 0.25;
    const pal = [shade(color, 0.9 + k * 0.3), shade(color, 1.1 + k * 0.3), shade(color, 0.75)];
    fol.cloud({ c: b.world([0, y + 0.3, 0]), r: r * 1.05, squash: 0.35, size: far ? Math.max(0.9, h * 0.09) : 0.6, palette: pal, rng, cover: far ? 1.6 : 2.2, shape: 'needle', inner: 0.75 });
  }
}

// Value noise for terrain (deterministic from rng).
function noise2(rng, cells = 64) {
  const g = Array.from({ length: cells * cells }, () => rng.next());
  const at = (i, j) => g[((j % cells) + cells) % cells * cells + (((i % cells) + cells) % cells)];
  return (x, y) => {
    const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
    const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
    const a = at(i, j) + (at(i + 1, j) - at(i, j)) * sx, c = at(i, j + 1) + (at(i + 1, j + 1) - at(i, j + 1)) * sx;
    return a + (c - a) * sy;
  };
}

// Voxel hillside: columns of `cell`-sized blocks rising away from the shore, covered with pines.
// heightAt(x, z) is returned so callers can place houses on the terrain.
export function hillside(b, { rng, x0, x1, z0, z1, baseY, rise = 30, cell = 3, ground = '#1c2420', treeColor = '#16241c', trees = 0.55, far = true, treeH = [8, 16], bumps = 0.35 }) {
  const n = noise2(rng.fork('terrain'));
  const heightAt = (x, z) => {
    const d = (z0 - z) / (z0 - z1);
    return baseY + Math.max(0, d) ** 0.8 * rise * (1 - bumps + bumps * 2 * n(x / 25, z / 25));
  };
  const gm = mat.plain(ground, 1);
  const tr = rng.fork('trees');
  for (let x = x0; x < x1; x += cell) for (let z = z0; z > z1; z -= cell) {
    const hgt = Math.round(heightAt(x + cell / 2, z - cell / 2) / 1) * 1;
    b.box([x, baseY - 2, z - cell], [x + cell, hgt, z], gm);
    if (tr.chance(trees)) b.at([x + tr.range(0.5, cell - 0.5), hgt, z - tr.range(0.5, cell - 0.5)], 0, () => pine(b, { h: tr.range(treeH[0], treeH[1]), rng: tr, color: treeColor, far }));
  }
  return { heightAt };
}

// Blocky cloud mass: flattened boxes, unlit and unfogged (they sit in front of the sky gradient).
export function cloud(b, { c, w = 40, h = 8, rng, color = '#2a3048', light = '#3a4262', pieces = 9 }) {
  for (let i = 0; i < pieces; i++) {
    const x = c[0] + rng.range(-w / 2, w / 2) * 0.8, y = c[1] + rng.range(-h / 2, h / 2) * 0.6, z = c[2] + rng.range(-4, 4);
    const pw = rng.range(w * 0.25, w * 0.55), ph = rng.range(h * 0.5, h);
    const top = { tex: { name: 'noise', color: '#ffffff', v: 0.02, blotch: 0.05 }, tint: light, unlit: true, fog: false, cast: false, receive: false };
    const body = { ...top, tint: color };
    b.box([x - pw / 2, y - ph / 2, z - 2], [x + pw / 2, y + ph / 2, z + 2], body, { faces: { py: top } });
  }
}

export { T };


// ---------------------------------------------------------------------------------------------------
// Block trees (the voxel look): everything on an integer grid of `u`-sized cubes. Trunk = log blocks
// (bark sides), crown = leaf blocks (alpha-cutout leaf texture) in a stepped round shape with some
// random missing/extra blocks so silhouettes read organic but stay cubic.
// Leaf blocks are tinted per block for color variety; inner blocks are skipped (hidden anyway).
const LEAF_TINTS = { autumn: ['#ffffff', '#ffe0c8', '#ffd0a8', '#f8c8b0', '#fff0d0'], far: ['#c89088', '#b88078', '#d0a090'], green: ['#ffffff', '#e0f0d8'] };

export function blockTree(b, { rng, h = 14, crownR = 4, crownH = 5, u = 1, leaves = 'leaves_autumn', tints = LEAF_TINTS.autumn, trunk = 'bark', glow = 0.25, branches = true, exclude = null, tw = null }) {
  const bark = { img: trunk, rough: 0.95, bevel: 0.03 };
  tw = tw ?? (h > 16 ? 2 : 1);
  for (let y = 0; y < h - 1; y++) b.box([-tw * u / 2, y * u, -tw * u / 2], [tw * u / 2, (y + 1) * u, tw * u / 2], bark);
  const base = h - crownH + 1;
  if (branches) for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    if (!rng.chance(0.6)) continue;
    const by = base + rng.int(0, 2);
    for (let k = 1; k <= Math.max(1, crownR - 2); k++) b.box([(dx * (k + tw / 2 - 0.5) - 0.5) * u, by * u, (dz * (k + tw / 2 - 0.5) - 0.5) * u], [(dx * (k + tw / 2 - 0.5) + 0.5) * u, (by + 1) * u, (dz * (k + tw / 2 - 0.5) + 0.5) * u], bark);
  }
  const filled = new Set();
  const cells = [];
  for (let y = 0; y < crownH; y++) {
    const k = (y + 0.5) / crownH;
    const r = crownR * Math.sqrt(Math.max(0, 1 - Math.pow((k - 0.45) / 0.62, 2)));
    for (let x = -crownR; x <= crownR; x++) for (let z = -crownR; z <= crownR; z++) {
      const d = Math.hypot(x, z);
      if (d > r + rng.range(-0.6, 0.4)) continue;
      cells.push([x, y, z]); filled.add(`${x},${y},${z}`);
    }
  }
  const leafSpec = (tint) => ({ img: leaves, tint, rough: 0.8, emissive: glow, emissiveColor: '#ff9a50', cast: true });
  for (const [x, y, z] of cells) {
    const inner = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]].every(([a, c, e]) => filled.has(`${x + a},${y + c},${z + e}`));
    if (inner) continue;
    const p = [x * u - u / 2, (base + y) * u, z * u - u / 2];
    if (exclude && exclude(...b.world([p[0] + u / 2, p[1] + u / 2, p[2] + u / 2]))) continue;
    b.box(p, [p[0] + u, p[1] + u, p[2] + u], leafSpec(tints[rng.int(0, tints.length - 1)]));
  }
  return { top: (base + crownH) * u, crownBase: base * u };
}

export { LEAF_TINTS };
