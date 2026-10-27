// Concept A v2 : "Autumn Treetop Library" in the texture-pack voxel look: every shape is a block,
// every surface uses the generated hi-res texture pack (assets/textures). Inside a treehouse room:
// fieldstone fireplace (left), bookshelves, plaid-and-knit bed with a sleeping cat (right), kilim rug.
// The whole back wall opens onto a balcony over a rainy autumn wood of block trees, with two lantern-lit
// treehouses joined by a rope bridge.
// Units: 1 = one block (~0.5 m). Room: x 0..11, z 0..9, y 0..5. Opening in the back wall (z = 0).
import * as THREE from 'three';
import { M, blk, blockBed, blockShelf, blockFireplace, blockLantern, blockCandle, blockPumpkin, blockPlant, blockVine } from '../../src/library/blocks.js';
import { rain, steam, hazeCard, sky, flicker, fire, fallingLeaves, scatterLeaves } from '../../src/library/effects.js';
import { blockTree, LEAF_TINTS, cloud } from '../../src/library/nature.js';
import { cat } from '../../src/library/creatures.js';
import { mug } from '../../src/library/props.js';

const OPEN = [3, 10.4];

export default {
  name: 'treetop',
  title: 'Autumn Treetop Library',
  seed: 11,
  fps: 30,
  loopSeconds: 60,
  camera: { pos: [7.0, 2.6, 6.8], target: [6.2, 3.0, -8], fov: 68 },
  background: '#141a30',
  ssaa: 2,
  envProbe: { pos: [5.5, 2.0, 4.5], intensity: 0.6, size: 256 },
  post: {
    toneMapping: 'aces',
    exposure: 1.05,
    fog: { color: '#3c4470', density: 0.012 },
    bloom: { strength: 0.55, radius: 0.6, threshold: 0.8 },
    ao: { radius: 0.5, blend: 1.0 },
    grade: { lift: [0.01, 0.008, 0.016], gamma: [1, 1, 1], gain: [1.03, 1.0, 0.97], saturation: 1.1, contrast: 1.05 },
    vignette: 0.45,
  },

  async build(ctx) {
    const { b, rng, light } = ctx;
    const [o0, o1] = OPEN;

    // --- Shell (log walls, plank floor and ceiling, beams) ------------------------------------------
    blk(b, -1, -1, -0.5, 13, 1, 10, M.planks(), { uv: 'world' });
    blk(b, -1, 5, -0.5, 13, 1, 10, M.dark(), { uv: 'world' });
    for (const x of [1.5, 5.5, 9.5]) b.box([x, 4.6, -0.5], [x + 0.5, 5, 9.5], M.log());
    blk(b, -1, 0, -0.5, 1, 5, 10, M.log(), { uv: 'world' });
    blk(b, 11, 0, -0.5, 1, 5, 10, M.log(), { uv: 'world' });
    blk(b, -1, -1, 9.5, 13, 7, 0.5, M.log(), { uv: 'world' });
    blk(b, 0, 0, -0.5, o0, 5, 0.5, M.log(), { uv: 'world' });
    blk(b, o1, 0, -0.5, 11 - o1, 5, 0.5, M.log(), { uv: 'world' });
    blk(b, o0, 4.3, -0.5, o1 - o0, 0.7, 0.5, M.log(), { uv: 'world' });
    // Log posts + lintel framing the opening (end-grain caps).
    for (const x of [o0 - 0.35, o1 - 0.15]) b.box([x, 0, -0.6], [x + 0.5, 4.4, 0.15], M.bark(), { faces: { py: M.logEnd() } });
    b.box([o0 - 0.4, 4.1, -0.6], [o1 + 0.4, 4.55, 0.15], M.bark(), { faces: { px: M.logEnd(), nx: M.logEnd() } });

    // --- Balcony ---------------------------------------------------------------------------------------
    blk(b, o0 - 0.5, -0.4, -3.5, o1 - o0 + 1, 0.4, 3.0, M.deck(), { uv: 'world' });
    b.box([o0 - 0.5, -0.4, -3.6], [o1 + 0.5, 0, -3.5], M.dark());
    const rail = M.dark('#d8c0a8');
    for (let x = o0 - 0.4; x <= o1 + 0.4; x += 1.75) b.box([x, 0, -3.4], [x + 0.22, 1.25, -3.18], rail);
    b.box([o0 - 0.5, 1.05, -3.42], [o1 + 0.5, 1.25, -3.16], rail);
    b.box([o0 - 0.5, 0.45, -3.36], [o1 + 0.5, 0.55, -3.22], rail);
    for (let x = o0 - 0.2; x < o1 + 0.4; x += 0.35) b.box([x, 0.55, -3.32], [x + 0.08, 1.05, -3.26], rail);
    let balLantern;
    b.at([o0 - 0.3, 1.25, -3.3], 0, () => { balLantern = blockLantern(b, { glow: 3 }); });
    b.at([3.0, 0, -2.4], 0, () => blockPumpkin(b, { s: 0.55 }));
    b.at([3.6, 0, -2.8], 0.4, () => blockPumpkin(b, { s: 0.36 }));
    b.at([9.6, 0, -1.6], 0, () => blockPlant(b, { rng: rng.fork('mum'), s: 0.42 }));
    // Vines over the opening.
    const vr = rng.fork('vines');
    for (let x = o0 - 0.3; x < o1 + 0.3; x += vr.range(0.3, 0.6)) { if (Math.sin(x * 0.8) < -0.2) continue; blockVine(b, { rng: vr, x, y: 4.1, z: 0.15, len: vr.chance(0.18) ? vr.range(0.8, 1.6) : vr.range(0.2, 0.45), s: 0.22 }); }
    for (let y = 1.6; y < 4.1; y += 0.28) if (vr.chance(0.6)) b.box([o1 - 0.3, y, 0.15], [o1 - 0.04, y + 0.26, 0.4], M.leaves(vr.pick(['#ffffff', '#ffd8b8']), 0.12));

    // --- Fireplace (left wall, facing +x) -------------------------------------------------------------
    let fp;
    b.at([0, 0, 4.2], Math.PI / 2, () => { fp = blockFireplace(b, { w: 3, h: 5, d: 1.1 }); });
    let candleA, candleB;
    b.at([0.6, 2.3, 3.2], 0, () => { candleA = blockCandle(b, { h: 0.32 }); });
    b.at([0.6, 2.3, 5.2], 0, () => { candleB = blockCandle(b, { h: 0.22 }); });
    b.at([0.6, 2.3, 4.6], 0, () => blockPumpkin(b, { s: 0.36 }));
    b.at([0.55, 2.3, 3.8], 0, () => blockPlant(b, { rng: rng.fork('mantel-plant'), s: 0.3 }));
    // Bookshelves either side of the fireplace + over the back-left wall.
    b.at([0, 0, 1.6], Math.PI / 2, () => blockShelf(b, { w: 2, h: 4 }));
    b.at([0, 0, 6.9], Math.PI / 2, () => blockShelf(b, { w: 2, h: 4 }));
    b.at([1.6, 0, 0], 0, () => blockShelf(b, { w: 2, h: 4 }));

    // --- Bed (right), cat, night table + lantern -----------------------------------------------------
    b.at([9.4, 0, 4.3], 0, () => blockBed(b, { w: 2.2, l: 3.4 }));
    const kitty = cat({ pose: 'curled', fur: '#6e655e', light: '#ece2d4' });
    kitty.group.position.set(9.4, 0.74, 4.4);
    kitty.group.rotation.y = -0.7;
    kitty.group.scale.setScalar(1.3);
    ctx.add(kitty.group);
    b.box([10.55, 0, 1.8], [11, 1.1, 2.55], M.dark()); // night stand
    b.box([10.5, 1.1, 1.75], [11, 1.18, 2.6], M.planks());
    let nightLantern, mugTop;
    b.at([10.75, 1.18, 2.0], 0, () => { nightLantern = blockLantern(b, { s: 0.3, glow: 2.5 }); });
    b.at([10.7, 1.18, 2.4], 0, () => { mugTop = mug(b, { tint: '#c8a080' }); });
    steam(ctx, { pos: mugTop, rng: rng.fork('steam'), h: 0.7, count: 10 });
    b.at([7.6, 0, 7.6], 0, () => { b.box([-0.5, 0, -0.4], [0.5, 0.9, 0.4], M.dark()); b.box([-0.55, 0.9, -0.45], [0.55, 1.0, 0.45], M.planks()); }); // chest
    b.at([7.6, 1.0, 7.6], 0.3, () => b.box([-0.3, 0, -0.22], [0.3, 0.22, 0.22], M.books()));

    // --- Rug + leaves on the floor ---------------------------------------------------------------------
    b.box([3.0, 0, 3.0], [7.6, 0.03, 6.6], M.kilim(), { uv: 'world' });
    const leafPal = ['#d8641e', '#e8a030', '#b8401a', '#c87a28', '#e0b040'];
    scatterLeaves(ctx, { min: [o0, -3.3], max: [o1, 2.5], y: 0.001, count: 36, rng: rng.fork('floor-leaves'), palette: leafPal, size: 0.28 });
    scatterLeaves(ctx, { min: [3.2, 3.2], max: [7.4, 6.4], y: 0.035, count: 6, rng: rng.fork('rug-leaves'), palette: leafPal, size: 0.28 });
    scatterLeaves(ctx, { min: [8.5, 3.6], max: [10.4, 5.8], y: 0.75, count: 3, rng: rng.fork('bed-leaves'), palette: leafPal, size: 0.26 });
    fallingLeaves(ctx, { min: [o0 + 0.5, 0.05, -2.5], max: [o1 - 0.5, 3.8, 2.0], count: 5, rng: rng.fork('falling'), palette: leafPal, active: 0.2, size: 0.28 });

    // --- Exterior: block trees, treehouses, rope bridge -------------------------------------------------
    const er = rng.fork('outside');
    const inRoom = (x, y, z) => x > -1.5 && x < 12.5 && y > -1.5 && y < 6.5 && z > -4 && z < 10;
    const T = LEAF_TINTS.autumn;
    // Our own tree: canopy above/around the balcony.
    b.at([-9, -16, -6], 0, () => blockTree(b, { rng: er.fork('own'), h: 27, crownR: 6, crownH: 5, tints: T, exclude: inRoom }));
    // Treehouse 1 (mid-left) on a big tree.
    const th1 = { x: 0, z: -24, y: 1.5 };
    b.at([th1.x, -14, th1.z], 0, () => blockTree(b, { rng: er.fork('t1'), h: 28, crownR: 7, crownH: 5, tints: T, tw: 2 }));
    const tl = [];
    const house = (cx, cy, cz, rot, r) => b.at([cx, cy, cz], rot, () => {
      blk(b, -3, -0.4, -2.5, 6, 0.4, 5, M.deck());
      for (const [x, z] of [[-3, -2.5], [2.6, -2.5], [-3, 2.1], [2.6, 2.1]]) b.box([x, 0, z], [x + 0.4, 1.0, z + 0.4], M.dark());
      b.box([-3, 0.85, 2.1], [3, 1.0, 2.5], M.dark());
      b.box([-2, 0, -1.8], [2, 2.6, 1.2], M.planks(), { faces: { pz: M.log() } });
      for (const x of [-1.3, 0.5]) b.box([x, 0.9, 1.2], [x + 0.8, 1.8, 1.26], M.flame('#ffb050', 1.2));
      for (let i = 0; i < 4; i++) b.box([-2.4 + i * 0.45, 2.6 + i * 0.4, -2.2 + i * 0.25], [2.4 - i * 0.45, 3.0 + i * 0.4, 1.6 - i * 0.25], M.shingles());
      tl.push(b.world([-0.9, 1.35, 1.8]), b.world([0.9, 1.35, 1.8]));
      b.at([2.7, 1.0, 2.2], 0, () => tl.push(blockLantern(b, { glow: 2.5 })));
      b.at([-2.8, 1.0, 2.2], 0, () => tl.push(blockLantern(b, { glow: 2.5 })));
    });
    house(th1.x, th1.y, th1.z + 3.2, 0.15, er);
    // Treehouse 2 (right, further).
    b.at([22, -14, -35], 0, () => blockTree(b, { rng: er.fork('t2'), h: 30, crownR: 7, crownH: 6, tints: T, tw: 2 }));
    house(22, 4, -31.8, -0.35, er);
    // Rope bridge between the two decks.
    const A = [3.2, th1.y + 0.1, th1.z + 3.6], B = [19.4, 4.1, -29.8];
    const steps = 22;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps, p = [A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t - 1.2 * 4 * t * (1 - t), A[2] + (B[2] - A[2]) * t];
      const yaw = Math.atan2(B[0] - A[0], B[2] - A[2]);
      b.at(p, yaw, () => {
        b.box([-0.6, -0.08, -0.18], [0.6, 0.02, 0.18], M.planks('#c8a888'));
        for (const s of [-1, 1]) b.box([s * 0.6 - 0.03, 0.75, -0.25], [s * 0.6 + 0.03, 0.82, 0.25], M.rope());
        if (i % 3 === 0) for (const s of [-1, 1]) b.box([s * 0.6 - 0.02, 0, -0.02], [s * 0.6 + 0.02, 0.78, 0.02], M.rope());
      });
    }
    // Forest: mid and far block trees on the ground below, fading into fog.
    const fr = er.fork('forest');
    for (let i = 0; i < 40; i++) {
      const x = fr.range(-60, 70), z = fr.range(-22, -90);
      if (Math.hypot(x - th1.x, z - th1.z) < 9 || Math.hypot(x - 22, z + 35) < 10) continue;
      const far = z < -50;
      b.at([Math.round(x), -14 - fr.int(0, 3), Math.round(z)], 0, () => blockTree(b, { rng: fr, h: fr.int(16, 24), crownR: fr.int(4, 7), crownH: fr.int(5, 7), u: far ? 2 : 1, tints: far ? ['#e0a088', '#c88070', '#d8b090', '#b07068'] : T, branches: !far, glow: far ? 0.3 : 0.25, tw: far ? 1 : 2 }));
    }
    sky(ctx, { center: [6, 50, -400], w: 1600, h: 360, top: '#0e1228', bottom: '#4a5280' });
    const cr = er.fork('clouds');
    for (let i = 0; i < 12; i++) cloud(b, { c: [cr.range(-260, 260), cr.range(40, 110), cr.range(-300, -360)], w: cr.range(60, 130), h: cr.range(10, 20), rng: cr, color: '#262c4c', light: '#3a4270', pieces: 9 });
    hazeCard(ctx, { center: [6, -8, -40], w: 400, h: 30, color: '#3c4470', opacity: 0.5 });
    hazeCard(ctx, { center: [6, 0, -100], w: 700, h: 70, color: '#3c4470', opacity: 0.6 });

    rain(ctx, { min: [-8, -14, -12], max: [18, 8, -3.8], count: 500, color: '#d8ccc0', opacity: 0.14, rng: rng.fork('rain-near'), len: [0.5, 0.9], speed: 18, tilt: 0.05, width: 1 / 32 });
    rain(ctx, { min: [-50, -16, -60], max: [60, 22, -12], count: 5000, color: '#a8b0d8', opacity: 0.11, rng: rng.fork('rain-mid'), len: [0.9, 1.6], speed: 18, tilt: 0.05, width: 1 / 16 });

    // --- Lights ------------------------------------------------------------------------------------------
    light.hemi({ sky: '#5a5a80', ground: '#4a2a18', intensity: 0.7 });
    light.dir({ pos: [-40, 60, -100], target: [6, 0, 0], color: '#7a86c8', intensity: 0.7 });
    const ff = flicker(rng.fork('fire'), ctx.loopSeconds, { amount: 0.16, hz: [1.5, 6] });
    const fireLight = light.point({ pos: fp.lightPos, color: '#ff8a3a', intensity: 18, shadow: true, mapSize: 2048, softness: 6 });
    ctx.animate((t) => { fireLight.intensity = 18 * ff(t); });
    fire(ctx, { pos: fp.firePos, w: 0.9, d: 0.35, h: 0.9, count: 120, rng: rng.fork('flames'), size: [0.06, 0.13] });
    light.point({ pos: nightLantern, color: '#ffb060', intensity: 6, shadow: true, mapSize: 1024, softness: 5 });
    for (const c of [candleA, candleB]) light.point({ pos: c, color: '#ffa850', intensity: 1.5, distance: 4 });
    light.point({ pos: [5.5, 3.0, 6.0], color: '#ffa860', intensity: 6 }); // warm bounce fill
    light.point({ pos: [9.2, 2.6, 5.5], color: '#ffb070', intensity: 5 }); // bed fill
    light.point({ pos: [balLantern[0], balLantern[1], balLantern[2] + 0.3], color: '#ffa850', intensity: 4 });
    for (const p of tl) light.point({ pos: p, color: '#ffa850', intensity: 8, distance: 9 });
  },
};
