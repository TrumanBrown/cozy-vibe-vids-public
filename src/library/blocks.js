// Block props for the texture-pack look: full and half blocks with generated hi-res textures.
// Units: 1 block = 1.0 (a "voxel"). Origin: footprint center on the floor; front = +z.
import { getImageTexture } from '../engine/builder.js';

export const M = {
  planks: (tint = '#ffffff') => ({ img: 'oak_planks', tint, rough: 0.45 }),
  deck: (tint = '#ffffff') => ({ img: 'oak_planks_b', tint, rough: 0.55 }),
  dark: (tint = '#ffffff') => ({ img: 'dark_planks', tint, rough: 0.4 }),
  log: (tint = '#ffffff') => ({ img: 'log_wall', imgOpts: { scale: 2 }, tint, rough: 0.6 }),
  bark: (tint = '#ffffff') => ({ img: 'bark', tint, rough: 0.95 }),
  logEnd: (tint = '#ffffff') => ({ img: 'log_end', tint, rough: 0.7 }),
  stone: (tint = '#ffffff') => ({ img: 'fieldstone', imgOpts: { scale: 2 }, tint, rough: 0.85 }),
  bricks: (tint = '#ffffff') => ({ img: 'stone_bricks', tint, rough: 0.85 }),
  cobble: (tint = '#ffffff') => ({ img: 'cobble', tint, rough: 0.85 }),
  books: (tint = '#ffffff') => ({ img: 'bookshelf', tint, rough: 0.7 }),
  wool: (tint = '#ffffff') => ({ img: 'wool_red', imgOpts: { scale: 0.5 }, tint, rough: 1, bevel: 0.12 }),
  cream: (tint = '#ffffff') => ({ img: 'wool_cream', imgOpts: { scale: 0.5 }, tint, rough: 1, bevel: 0.14 }),
  plaid: (tint = '#ffffff') => ({ img: 'plaid', tint, rough: 1, bevel: 0.1 }),
  kilim: (tint = '#ffffff') => ({ img: 'kilim', imgOpts: { scale: 2 }, tint, rough: 1, bevel: 0 }),
  shingles: (tint = '#ffffff') => ({ img: 'shingles', tint, rough: 0.8 }),
  rope: (tint = '#ffffff') => ({ img: 'rope', tint, rough: 1 }),
  iron: (tint = '#ffffff') => ({ img: 'iron', tint, rough: 0.45, metal: 0.4, bevel: 0.02 }),
  pumpkin: (tint = '#ffffff') => ({ img: 'pumpkin', tint, rough: 0.6, bevel: 0.08 }),
  leaves: (tint = '#ffffff', glow = 0.22) => ({ img: 'leaves_autumn', tint, rough: 0.8, emissive: glow, emissiveColor: '#ff9a50', cast: true }),
  green: (tint = '#ffffff') => ({ img: 'leaves_green', tint, rough: 0.8, emissive: 0.05, emissiveColor: '#80c060', cast: true }),
  glow: (color, k = 3) => ({ img: 'wool_cream', tint: color, emissive: k, emissiveColor: color, cast: false, bevel: 0 }),
  flame: (color = '#ffb050', k = 5) => ({ tex: { name: 'noise', color: '#ffffff', v: 0, blotch: 0 }, tint: color, emissive: k, emissiveColor: color, cast: false, bevel: 0 }),
};

// Full-block box helper on the grid (min corner + size in blocks).
export const blk = (b, x, y, z, w = 1, h = 1, d = 1, m, opts) => b.box([x, y, z], [x + w, y + h, z + d], m, opts);

// Bed: plank frame, mattress, red knit blanket draped over the foot and sides, cream pillows.
export function blockBed(b, { w = 2, l = 3 } = {}) {
  const fr = M.dark();
  b.box([-w / 2, 0, -l / 2], [w / 2, 0.35, l / 2], fr);
  for (const x of [-w / 2, w / 2 - 0.18]) for (const z of [-l / 2, l / 2 - 0.18]) b.box([x, 0, z], [x + 0.18, 0.5, z + 0.18], fr);
  b.box([-w / 2, 0, -l / 2 - 0.2], [w / 2, 1.35, -l / 2], fr); // headboard
  b.box([-w / 2 + 0.1, 1.2, -l / 2 - 0.25], [w / 2 - 0.1, 1.45, -l / 2 + 0.05], fr);
  b.box([-w / 2 + 0.05, 0.35, -l / 2 + 0.02], [w / 2 - 0.05, 0.62, l / 2 - 0.02], M.cream('#f4ece0'));
  // Blanket: top slab from 1/3 down, sides and foot drape down past the mattress, a folded band.
  const bl = M.wool();
  const z0 = -l / 2 + l * 0.33;
  b.box([-w / 2 - 0.06, 0.62, z0], [w / 2 + 0.06, 0.74, l / 2 + 0.06], bl);
  b.box([-w / 2 - 0.06, 0.26, z0], [-w / 2, 0.74, l / 2 + 0.06], bl);
  b.box([w / 2, 0.26, z0], [w / 2 + 0.06, 0.74, l / 2 + 0.06], bl);
  b.box([-w / 2 - 0.06, 0.22, l / 2], [w / 2 + 0.06, 0.74, l / 2 + 0.06], bl);
  b.box([-w / 2 - 0.07, 0.74, z0], [w / 2 + 0.07, 0.84, z0 + 0.35], M.cream('#f0e4d4')); // folded sheet edge
  // Pillows (slightly tilted, puffy bevel).
  for (const s of [-1, 1]) b.at([s * w / 4.2, 0.62, -l / 2 + 0.35], s * 0.06, () => b.box([-0.42, 0, -0.22], [0.42, 0.34, 0.22], { ...M.cream('#fbf6ee'), bevel: 0.16 }), { rotX: -0.3 });
  b.at([0.25, 0.74, z0 + 0.8], 0.4, () => b.box([-0.4, 0, -0.3], [0.4, 0.08, 0.3], M.plaid())); // throw folded on the bed
}

// Bookshelf block wall section: w x h blocks of bookshelf texture with dark plank caps.
export function blockShelf(b, { w = 2, h = 3, d = 0.5 } = {}) {
  b.box([-w / 2, 0, -d], [w / 2, h, 0], M.dark(), { faces: { pz: M.books() } });
  b.box([-w / 2 - 0.04, h, -d - 0.04], [w / 2 + 0.04, h + 0.12, 0.06], M.dark());
}

// Fieldstone fireplace with mantel; firebox opening facing +z. Returns { firePos, lightPos, mantelY }.
export function blockFireplace(b, { w = 3, h = 6, d = 1.2 } = {}) {
  const st = M.stone(), stD = M.stone('#8a8078');
  b.box([-w / 2, 0, 0], [-0.6, 2, d], st);
  b.box([0.6, 0, 0], [w / 2, 2, d], st);
  b.box([-0.6, 1.2, 0], [0.6, 2, d], st);
  b.box([-0.6, 0, 0], [0.6, 1.2, 0.25], stD);
  b.box([-w / 2 - 0.3, 0, d], [w / 2 + 0.3, 0.2, d + 0.7], M.bricks());
  b.box([-w / 2 - 0.25, 2, -0.05], [w / 2 + 0.25, 2.3, d + 0.3], M.dark()); // mantel
  b.box([-w / 2 + 0.4, 2.3, 0], [w / 2 - 0.4, h, d * 0.8], st); // chimney
  for (const x of [-0.45, -0.15, 0.15]) b.at([x + 0.15, 0.06, 0.65], 0.3 - x, () => b.box([-0.35, 0, -0.08], [0.35, 0.16, 0.08], M.bark()));
  b.box([-0.45, 0.04, 0.5], [0.45, 0.06, 0.85], M.flame('#ff4a10', 1.2));
  return { firePos: b.world([0, 0.12, 0.65]), lightPos: b.world([0, 0.8, d + 1.2]), mantelY: 2.3 };
}

// Lantern: iron frame around a glowing block. Returns the core world position.
export function blockLantern(b, { s = 0.38, glow = 5, color = '#ffb050' } = {}) {
  const ir = M.iron();
  b.box([-s / 2, 0, -s / 2], [s / 2, s * 0.12, s / 2], ir);
  b.box([-s * 0.38, s * 0.12, -s * 0.38], [s * 0.38, s * 1.05, s * 0.38], M.flame(color, glow));
  for (const x of [-s / 2, s / 2 - s * 0.1]) for (const z of [-s / 2, s / 2 - s * 0.1]) b.box([x, s * 0.12, z], [x + s * 0.1, s * 1.05, z + s * 0.1], ir);
  b.box([-s / 2, s * 1.05, -s / 2], [s / 2, s * 1.18, s / 2], ir);
  b.box([-s * 0.28, s * 1.18, -s * 0.28], [s * 0.28, s * 1.35, s * 0.28], ir);
  return b.world([0, s * 0.6, 0]);
}

export function blockCandle(b, { h = 0.3, w = 0.12 } = {}) {
  b.box([-w / 2, 0, -w / 2], [w / 2, h, w / 2], { ...M.cream('#f0e6d0'), bevel: 0.01 });
  b.box([-0.03, h, -0.03], [0.03, h + 0.11, 0.03], M.flame('#ffb347', 6));
  return b.world([0, h + 0.07, 0]);
}

export function blockPumpkin(b, { s = 0.5 } = {}) {
  b.box([-s / 2, 0, -s / 2], [s / 2, s * 0.8, s / 2], M.pumpkin());
  b.box([-s * 0.07, s * 0.8, -s * 0.07], [s * 0.07, s, s * 0.07], M.bark('#6a7a3a'));
}

// Potted autumn shrub: planks pot + a cluster of leaf blocks.
export function blockPlant(b, { rng, s = 0.42, leaves = 'autumn' } = {}) {
  b.box([-s / 2, 0, -s / 2], [s / 2, s * 0.8, s / 2], M.dark('#c08060'));
  const lm = leaves === 'autumn' ? M.leaves('#ffffff', 0.15) : M.green();
  const q = s * 0.55;
  for (const [x, y, z] of [[0, 0, 0], [-1, 0, 0], [1, 0, 0], [0, 0, -1], [0, 0, 1], [0, 1, 0], [rng.int(-1, 1), 1, rng.int(-1, 1)]]) {
    b.box([x * q - q / 2, s * 0.8 + y * q, z * q - q / 2], [x * q + q / 2, s * 0.8 + (y + 1) * q, z * q + q / 2], lm);
  }
}

// Leaf vine strip: small leaf blocks hanging from (x, y, z) down `len`.
export function blockVine(b, { rng, x, y, z, len = 2, s = 0.32 }) {
  for (let k = 0; k < len; k += s) {
    if (rng.chance(0.15)) continue;
    const dx = rng.range(-0.1, 0.1);
    b.box([x + dx - s / 2, y - k - s, z], [x + dx + s / 2, y - k, z + s * 0.5], M.leaves(rng.pick(['#ffffff', '#ffd8b8', '#f0c0a0']), 0.12));
  }
}

export { getImageTexture };
