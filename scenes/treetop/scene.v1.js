// Concept B : "Autumn Treetop Library": a reading room high in a maple. Wide open balcony doors (left)
// look out over a rainy autumn canopy village : lantern-lit treehouses, rope bridges, misty forest
// layers and blocky storm clouds. A stone fireplace (back right), a reading chair with a sleeping cat,
// tall bookshelves; leaves drift in and gather on the floor.
// Units: 1 block ~ 0.5 m. Room x 0..14, z 0..12, y 0..6; balcony z -4..0. Camera looks toward -z.
import { mat, T, bookshelf, armchair, rug, mug, bookStack, candle, pictureFrame, cushion, throwBlanket, fireplace, pumpkin, chest, logBasket, pottedPlant, table } from '../../src/library/props.js';
import { rain, steam, hazeCard, sky, flicker, fire, fallingLeaves, scatterLeaves } from '../../src/library/effects.js';
import { broadleaf, pine, leafBlob, cloud, LEAF_PALETTES } from '../../src/library/nature.js';
import { lantern, wallLantern, railing, treehouse, ropeBridge } from '../../src/library/structures.js';
import { cat } from '../../src/library/creatures.js';

const AUTUMN = LEAF_PALETTES.autumn;
const FAR = ['#a8503a', '#94443e', '#7a3c44', '#b0603e'];
const OPEN = [0.6, 9.6]; // x-range of the balcony opening

export default {
  name: 'treetop',
  title: 'Autumn Treetop Library',
  seed: 11,
  fps: 30,
  loopSeconds: 60,
  camera: { pos: [8.2, 2.85, 6.6], target: [4.0, 2.95, -10], fov: 66 },
  background: '#141a30',
  ssaa: 2,
  envProbe: { pos: [6, 2.6, 4], intensity: 0.55, size: 256 },
  post: {
    toneMapping: 'aces',
    exposure: 1.05,
    fog: { color: '#4a4670', density: 0.0062 },
    bloom: { strength: 0.5, radius: 0.55, threshold: 0.85 },
    ao: { radius: 0.6, blend: 1.0 },
    grade: { lift: [0.012, 0.012, 0.022], gamma: [1, 1, 1], gain: [1.02, 1.0, 0.98], saturation: 1.1, contrast: 1.04 },
    vignette: 0.45,
  },

  async build(ctx) {
    const { b, rng, light } = ctx;
    const logs = { tex: { name: 'logs', color: '#f2f2f2' }, tint: '#9a6a42', rough: 0.95 };
    const beam = mat.wood('#4a2e1c');
    const [ox0, ox1] = OPEN;

    // --- Room shell ---------------------------------------------------------------------------
    b.box([-1, -1, -0.5], [15, 0, 13], mat.planks('#8a5e3a'), { uv: 'world' });
    b.box([-1, 6, -0.5], [15, 7, 13], mat.planks('#6a4428'), { uv: 'world' });
    for (let z = 1; z < 13; z += 2.5) b.box([0, 5.55, z], [14, 6, z + 0.45], beam);
    b.box([-1, 0, -0.5], [0, 6, 13], logs, { uv: 'world' });
    b.box([14, 0, -0.5], [15, 6, 13], logs, { uv: 'world' });
    b.box([-1, -1, 13], [15, 7, 13.5], logs, { uv: 'world' }); // behind the camera: blocks the moon key
    b.box([-1, 0, -0.5], [ox0, 6, 0], logs, { uv: 'world' });
    b.box([ox1, 0, -0.5], [14, 6, 0], logs, { uv: 'world' });
    b.box([ox0, 5.3, -0.5], [ox1, 6, 0], logs, { uv: 'world' });
    b.box([ox0 - 0.3, 0, -0.6], [ox0 + 0.2, 5.5, 0.1], beam);
    b.box([ox1 - 0.2, 0, -0.6], [ox1 + 0.3, 5.5, 0.1], beam);
    b.box([ox0 - 0.3, 5.15, -0.6], [ox1 + 0.3, 5.55, 0.1], beam);
    // Shutter (one leaf, folded back against the left wall).
    b.at([ox0 + 0.2, 0.1, 0.1], -Math.PI * 0.5, () => {
      b.box([0, 0, 0], [1.6, 4.3, 0.12], mat.wood('#6a4428'));
      for (let y = 0.5; y < 4.2; y += 0.95) b.box([0.08, y, 0.12], [1.52, y + 0.12, 0.2], mat.wood('#3a2416'));
      b.box([0.08, 0.3, 0.12], [0.2, 4.0, 0.2], mat.wood('#3a2416'));
    });

    // --- Balcony ------------------------------------------------------------------------------
    b.box([ox0 - 0.5, -0.6, -4], [ox1 + 0.5, 0, 0], mat.planks('#7a5434'), { uv: 'world' });
    for (const x of [ox0 - 0.4, 5, ox1 + 0.1]) b.box([x, -3, -3.9], [x + 0.3, -0.6, -3.6], beam);
    b.at([0, 0, -3.75], 0, () => railing(b, { x0: ox0 - 0.5, x1: 2.4, z: 0, m: beam }));
    b.at([0, 0, -3.75], 0, () => railing(b, { x0: 3.9, x1: ox1 + 0.5, z: 0, m: beam }));
    b.at([ox0 - 0.35, 0, 0], Math.PI / 2, () => railing(b, { x0: 0, x1: 3.9, z: 0, m: beam }));
    b.at([ox1 + 0.35, 0, 0], -Math.PI / 2, () => railing(b, { x0: -3.9, x1: 0, z: 0, m: beam }));
    let balLantern, balLantern2;
    b.at([ox0 - 0.35, 1.22, -3.75], 0, () => { balLantern = lantern(b, { s: 0.42, glow: 4 }); });
    b.at([ox1 + 0.35, 1.22, -3.75], 0, () => { balLantern2 = lantern(b, { s: 0.42, glow: 4 }); });
    b.at([7.6, 0, -2.6], 0, () => pumpkin(b, { s: 0.6 }));
    b.at([8.3, 0, -3.0], 0, () => pumpkin(b, { s: 0.4, tint: '#e0a030' }));
    b.at([7.9, 0, -1.6], 0.5, () => pumpkin(b, { s: 0.32, tint: '#c8b080' }));
    b.at([0.4, 0, -1.4], 0, () => pottedPlant(b, { rng: rng.fork('mum'), potW: 0.55, potH: 0.45, height: 1.0, spread: 0.3, clumps: 10, clump: [0.2, 0.32], leaf: { tex: { name: 'leaves', color: '#f2f2f2', palette: ['#e8a030', '#d8641e', '#f0c040'], density: 0.85 }, tint: '#ffffff', rough: 0.8 } }));

    // Trailing autumn vine (leaf cards) along the top beam and down the right post.
    const vr = rng.fork('vines');
    const VINE = ['#a8401a', '#c8601e', '#8a3418', '#b87a2a', '#6a6a2a', '#9a4a1c'];
    const fol = ctx.foliage;
    const vineStem = mat.plain('#3a2a18');
    for (let x = ox0; x < ox1 + 0.2; x += vr.range(0.06, 0.14)) {
      if (Math.sin(x * 0.9) + vr.range(-0.4, 0.4) < -0.2) continue;
      for (let k = 0; k < 2; k++) fol.leaf([x + vr.range(-0.06, 0.06), 5.1 + vr.range(-0.2, 0.08), 0.12 + vr.range(0, 0.2)], vr.range(0.16, 0.26), VINE[vr.int(0, VINE.length - 1)], vr, { normal: [0, -0.2, 1] });
      if (vr.chance(0.16)) {
        const len = vr.range(0.5, 2.0);
        b.box([x - T / 6, 5.15 - len, 0.15], [x + T / 6, 5.15, 0.15 + T / 3], vineStem);
        fol.strand({ start: [x, 5.05, 0.16], len, size: 0.2, palette: VINE, rng: vr, step: 0.1, sway: 0.04 });
      }
    }
    b.box([ox1 - 0.38, 0.2, 0.12], [ox1 - 0.34, 5.15, 0.16], vineStem);
    fol.strand({ start: [ox1 - 0.36, 5.1, 0.16], len: 4.9, size: 0.22, palette: VINE, rng: vr, step: 0.08, sway: 0.06 });
    // --- Fireplace (back wall, right) -----------------------------------------------------------
    let fp;
    b.at([11.7, 0, 0], 0, () => { fp = fireplace(b, { w: 3.4, h: 6, d: 1.0, stone: '#7a7068' }); });
    b.at([10.4, 2.35, 0.65], 0, () => candle(b, { h: 0.34 }));
    b.at([10.75, 2.35, 0.6], 0, () => candle(b, { h: 0.22 }));
    b.at([11.4, 2.35, 0.65], 0, () => pumpkin(b, { s: 0.42 }));
    b.at([12.0, 2.35, 0.7], 0, () => pumpkin(b, { s: 0.3, tint: '#e8b040' }));
    b.at([12.8, 2.35, 0.6], 0.3, () => bookStack(b, { n: 3, rng: rng.fork('mantel') }));
    b.at([11.7, 3.4, 0.8], 0, () => pictureFrame(b, { w: 1.2, h: 0.95, palette: ['#e0a050', '#b04a28', '#5a3a2a', '#2a1e1e'] }));
    b.at([9.8, 0, 1.6], 0.2, () => logBasket(b, { rng: rng.fork('logs') }));

    // --- Bookshelves (right wall) + wall lantern ------------------------------------------------
    for (const [i, z] of [7.2, 9.6].entries()) b.at([13.64, 0, z], -Math.PI / 2, () => bookshelf(b, { w: 2.4, h: 5.4, d: 0.7, shelves: 6, m: mat.wood('#5a3420'), rng: rng.fork(`shelf${i}`), fill: 0.92 }));
    let wallL;
    b.at([13.98, 3.9, 5.2], -Math.PI / 2, () => { wallL = wallLantern(b, { reach: 0.6, drop: 0.15, s: 0.4, glow: 7 }); });
    // Left wall: low shelf + chest near the camera, painting above.
    b.at([0.36, 0, 5.6], Math.PI / 2, () => bookshelf(b, { w: 2.6, h: 2.2, d: 0.7, shelves: 2, m: mat.wood('#5a3420'), rng: rng.fork('low'), fill: 0.85 }));
    b.at([0.6, 2.2, 5.2], 0.3, () => pottedPlant(b, { rng: rng.fork('fern'), potW: 0.4, potH: 0.35, height: 0.8, spread: 0.35, clumps: 9, clump: [0.2, 0.3] }));
    b.at([0.6, 2.2, 6.2], 0, () => candle(b, { h: 0.28 }));
    b.at([0.05, 3.4, 2.4], Math.PI / 2, () => pictureFrame(b, { w: 1.4, h: 1.1, palette: ['#d8a060', '#a05030', '#3a4a3a', '#1e1e28'] }));
    b.at([1.0, 0, 7.6], Math.PI / 2, () => chest(b, {}));

    // --- Reading corner in front of the fire ----------------------------------------------------
    b.at([6.4, 0, 3.6], 0, () => rug(b, { w: 7, d: 4.4, palette: ['#6a2a1c', '#a8702e', '#2a2026', '#9a7a52'], style: 'kilim' }));
    b.at([3.3, 0, 3.2], 1.75, () => armchair(b, { fabric: { tex: { name: 'plaid', a: '#8a2a22', b: '#2a1414', size: 3 }, tint: '#ffffff', rough: 1 } }));
    b.at([2.95, 0.8, 3.25], 1.75, () => cushion(b, { w: 0.7, h: 0.55, m: mat.knit('#d8c49a'), tilt: 0.5 }));
    b.at([2.55, 2.1, 3.3], 1.75, () => throwBlanket(b, { w: 1.1, flat: 0.5, hang: 1.0, m: mat.knit('#c87a3a') }));
    b.at([4.5, 0, 5.0], 0, () => table(b, { w: 1.0, d: 1.0, h: 1.05, top: mat.wood('#5a3620') }));
    let tableLantern, mugTop;
    b.at([4.3, 1.05, 4.85], 0, () => { tableLantern = lantern(b, { s: 0.36, glow: 0.55 }); });
    b.at([4.75, 1.05, 5.25], 0, () => { mugTop = mug(b, { tint: '#d8c8a8' }); });
    b.at([4.7, 1.05, 4.7], 0.4, () => bookStack(b, { n: 2, rng: rng.fork('side') }));
    steam(ctx, { pos: mugTop, rng: rng.fork('steam'), h: 0.7, count: 10 });
    const kitty = cat({ pose: 'curled', fur: '#7a6e66', light: '#e2d6c4' });
    b.at([7.0, 0, 2.2], 0.15, () => { b.box([-0.55, 0, -0.45], [0.55, 0.22, 0.45], mat.fabric('#7a3328')); b.box([-0.5, 0.22, -0.4], [0.5, 0.26, 0.4], mat.fabric('#8a3a2e')); });
    kitty.group.position.set(7.0, 0.26, 2.25);
    kitty.group.rotation.y = -0.5;
    kitty.group.scale.setScalar(1.3);
    ctx.add(kitty.group);

    // Leaves blown in.
    const leafPal = ['#d8641e', '#e8a030', '#b8401a', '#c87a28', '#e0b040'];
    scatterLeaves(ctx, { min: [ox0, -3.4], max: [ox1, 3.5], y: 0, count: 46, rng: rng.fork('floor-leaves'), palette: leafPal });
    scatterLeaves(ctx, { min: [3.2, 1.6], max: [9.8, 5.6], y: T, count: 8, rng: rng.fork('rug-leaves'), palette: leafPal });
    fallingLeaves(ctx, { min: [ox0 + 0.5, 0.05, -2.5], max: [ox1, 5.2, 2.5], count: 7, rng: rng.fork('falling'), palette: leafPal, active: 0.2 });

    // --- Exterior ------------------------------------------------------------------------------
    const er = rng.fork('outside');
    const inRoom = (x, y, z) => x > -1.5 && x < 15.5 && y > -3.2 && y < 7.5 && z > -4.6 && z < 13.5;
    // Our maple's own canopy, framing the top of the opening (sightlines: opening spans roughly
    // -43..+8 deg horizontally and -7..+13 deg vertically from the camera).
    b.at([-17, -26, -12], 0, () => broadleaf(b, { h: 36, rng: er.fork('near-l'), palette: AUTUMN, spread: 0.95, blobs: 6, leaf: 0.5, exclude: inRoom }));
    leafBlob(b, { c: [-2.5, 9.5, -9], r: 3.4, rng: er.fork('overhang1'), palette: AUTUMN, leaf: 0.3, exclude: inRoom });

    // Three treehouses at eye level, crowns above them: th1 (near-left, bridged from our balcony),
    // th2 (mid-right), th3 (far-left, bridged to th1).
    let th1, th2, th3;
    const crown = { midBlob: false, blobs: 7, spread: 1.1 };
    b.at([-3, -28, -27], 0, () => broadleaf(b, { h: 46, rng: er.fork('th1-tree'), palette: AUTUMN, canopyBase: 0.8, leaf: 0.55, ...crown, spread: 0.95 }));
    b.at([-3, -28, -27], 0.3, () => { th1 = treehouse(b, { y: 26.5, w: 9, d: 7.5, cabinW: 6, cabinH: 3.8, rng: er.fork('th1') }); });
    const bridge1 = ropeBridge(b, { lanternGlow: 5, lanternEnds: [false, true], A: [3.15, -0.1, -4.6], B: [th1.front[0] + 1.2, th1.front[1], th1.front[2] + 0.4], sag: 2.0, width: 1.3 });
    b.at([12, -30, -56], 0, () => broadleaf(b, { h: 54, rng: er.fork('th2-tree'), palette: AUTUMN, canopyBase: 0.6, leaf: 0.9, ...crown }));
    b.at([12, -30, -56], -0.5, () => { th2 = treehouse(b, { y: 27, w: 8, d: 7, cabinW: 5, cabinH: 3.2, rng: er.fork('th2') }); });
    b.at([-30, -30, -92], 0, () => broadleaf(b, { h: 58, rng: er.fork('th3-tree'), palette: FAR, canopyBase: 0.6, leaf: 1.8, ...crown }));
    b.at([-30, -30, -92], 0.3, () => { th3 = treehouse(b, { y: 30, w: 7, d: 6, cabinW: 4.6, cabinH: 3, rng: er.fork('th3'), lanterns: 2 }); });
    const bridge2 = ropeBridge(b, { A: [th1.front[0] - 4, th1.front[1], th1.front[2] - 7], B: [th3.front[0] + 2, th3.front[1], th3.front[2]], sag: 3, width: 1.2 });
    // More life in the distance: small far treehouses (lit windows + lanterns) and lantern strings.
    const far = er.fork('far-houses');
    const farLights = [];
    for (const [x, z, y, h] of [[34, -110, 33, 60], [-62, -128, 36, 62], [-8, -150, 40, 66], [48, -160, 38, 64]]) {
      b.at([x, -30, z], 0, () => broadleaf(b, { h, rng: far, palette: FAR, canopyBase: 0.62, leaf: 2.6, midBlob: false, blobs: 7, spread: 1.1 }));
      b.at([x, -30, z], far.range(-0.6, 0.6), () => { const t = treehouse(b, { y, w: 7, d: 6, cabinW: 4.6, cabinH: 3, rng: far, lanterns: 2, glow: 3 }); farLights.push(t.lanterns[0]); });
    }
    const strings = er.fork('strings');
    for (const [A, B] of [[[th1.front[0] + 4, th1.front[1] + 4.5, th1.front[2] - 2], [th2.front[0] - 4, th2.front[1] + 5, th2.front[2] + 1]]]) {
      const n = 14;
      for (let i = 1; i < n; i++) {
        const t = i / n;
        const p = [A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t - 2.2 * 4 * t * (1 - t), A[2] + (B[2] - A[2]) * t];
        b.box([p[0] - 0.12, p[1] - 0.24, p[2] - 0.12], [p[0] + 0.12, p[1], p[2] + 0.12], mat.bulb(strings.pick(['#ffcf7a', '#ffb060', '#ffe0a0']), 7));
      }
    }

    // Forest layers: mid maples, darker/bluer far canopy, hill silhouettes.
    const fr = er.fork('forest');
    for (let i = 0; i < 18; i++) {
      const x = fr.range(-110, 70), z = fr.range(-48, -135);
      if (Math.hypot(x + 6, z + 36) < 16 || Math.hypot(x - 12, z + 56) < 16 || Math.hypot(x + 30, z + 92) < 16) continue;
      b.at([x, -30, z], fr.range(0, 6), () => broadleaf(b, { h: fr.range(30, 46), rng: fr, palette: z < -85 ? FAR : AUTUMN, spread: fr.range(0.85, 1.15), blobs: 6, leaf: z < -85 ? 2.6 : 1.8, canopyBase: 0.6 }));
    }
    for (let i = 0; i < 46; i++) {
      const x = fr.range(-200, 120), z = fr.range(-125, -200);
      b.at([x, -30, z], 0, () => (fr.chance(0.3) ? pine(b, { h: fr.range(30, 44), rng: fr, color: '#2e2e48', far: true }) : leafBlob(b, { c: [0, fr.range(26, 40), 0], r: fr.range(6, 10), rng: fr, palette: FAR, leaf: 2.2, cover: 1.6 })));
    }
    for (let i = 0; i < 10; i++) {
      const x = fr.range(-300, 200), w = fr.range(60, 120), h = fr.range(26, 50), z = fr.range(-240, -280);
      b.box([x - w / 2, -30, z - 20], [x + w / 2, -30 + h, z], mat.plain('#2a2e4c', 1));
    }
    sky(ctx, { center: [6, 60, -520], w: 1800, h: 420, top: '#0e1228', bottom: '#4a5280' });
    const cr = er.fork('clouds');
    for (let i = 0; i < 16; i++) cloud(b, { c: [cr.range(-320, 220), cr.range(40, 130), cr.range(-380, -440)], w: cr.range(60, 140), h: cr.range(10, 24), rng: cr, color: '#2a3052', light: '#3e4674', pieces: 10 });
    hazeCard(ctx, { center: [-10, -8, -45], w: 500, h: 50, color: '#3c4470', opacity: 0.4 });
    hazeCard(ctx, { center: [-10, -4, -130], w: 900, h: 90, color: '#3c4470', opacity: 0.55 });

    // Rain: near curtain past the balcony, mid, far.
    rain(ctx, { min: [-12, -14, -16], max: [14, 10, -6], count: 500, color: '#d8c8b8', opacity: 0.12, width: T / 2, rng: rng.fork('rain-near'), len: [0.5, 0.9], speed: 18, tilt: 0.05 });
    rain(ctx, { min: [-70, -30, -60], max: [40, 26, -16], count: 4000, color: '#a8b0d8', opacity: 0.12, rng: rng.fork('rain-mid'), len: [0.9, 1.6], speed: 18, tilt: 0.05, width: T });
    rain(ctx, { min: [-200, -30, -170], max: [120, 60, -60], count: 5000, color: '#9aa2c8', opacity: 0.09, rng: rng.fork('rain-far'), len: [2, 3], speed: 18, tilt: 0.05, width: 2 * T });

    // --- Lights ----------------------------------------------------------------------------------
    light.hemi({ sky: '#6a5a78', ground: '#5a3018', intensity: 1.1 });
    light.dir({ pos: [-60, 80, -140], target: [6, 0, 0], color: '#7a86c8', intensity: 0.6 });
    light.dir({ pos: [70, 110, 150], target: [-10, 0, -60], color: '#b8a0c0', intensity: 2.2, shadow: true, mapSize: 4096, box: 140, far: 500, softness: 2, bias: -0.0005, normalBias: 0.05 });
    const ff = flicker(rng.fork('fire'), ctx.loopSeconds, { amount: 0.16, hz: [1.5, 6] });
    const fireLight = light.point({ pos: fp.lightPos, color: '#ff8a3a', intensity: 55, shadow: true, mapSize: 2048, softness: 6 });
    ctx.animate((t) => { fireLight.intensity = 55 * ff(t); });
    fire(ctx, { pos: fp.firePos, w: 1.2, d: 0.4, h: 1.15, count: 160, rng: rng.fork('flames'), size: [0.08, 0.17] });
    light.point({ pos: tableLantern, color: '#ffb060', intensity: 10, shadow: true, mapSize: 1024, softness: 5 });
    light.point({ pos: wallL, color: '#ffb060', intensity: 12 });
    light.point({ pos: [3.5, 4.8, 5.5], color: '#ffa860', intensity: 26 }); // warm bounce fill
    light.point({ pos: [10.5, 1.6, 3.4], color: '#ff9a50', intensity: 12 }); // fire bounce into the room
    light.point({ pos: [12.8, 4.6, 7.5], color: '#ffa860', intensity: 14 }); // shelves
    light.point({ pos: [11, 4.8, 9], color: '#ffa860', intensity: 10 });
    for (const p of [balLantern, balLantern2]) light.point({ pos: [p[0], p[1] + 0.1, p[2] + 0.3], color: '#ffa850', intensity: 5 });
    light.point({ pos: [8.4, 1.2, 2.4], color: '#ff9a48', intensity: 5, distance: 5 }); // fire spill on the cat
    for (const p of [...th1.lanterns, ...th1.windows.slice(0, 2), ...bridge1]) light.point({ pos: p, color: '#ffa850', intensity: 30, distance: 16 });
    for (const p of [...th2.lanterns.slice(0, 2), ...th3.lanterns.slice(0, 1), bridge2[0], ...farLights]) light.point({ pos: p, color: '#ffa850', intensity: 40, distance: 18 });
  },
};
