// Concept A : "Canal Bookshop Loft": the reading loft above a bookshop, its whole back wall one big
// steel factory window over a rainy canal street. Across the water: narrow gabled townhouses with lit
// windows, shop fronts and awnings, street trees in late-autumn gold, an arched footbridge with lamps,
// moored boats, and wet cobbles and water reflecting every light. Inside: a long window seat with a
// sleeping cat, string lights, tall shelves, a reading chair under a floor lamp.
// Units: 1 block ~ 0.5 m. Room x 0..16, z 0..12, y 0..6.5; window wall z = 0. Street level y = -9.
import * as THREE from 'three';
import { mat, T, bookshelf, armchair, rug, mug, bookStack, candle, cushion, throwBlanket, pottedPlant, hangingPlant, floorLamp, stringLights, pictureFrame, table, teapot, crate } from '../../src/library/props.js';
import { rain, glassDrops, steam, hazeCard, sky, glass, flicker, lake, fallingLeaves } from '../../src/library/effects.js';
import { leafBlob, cloud } from '../../src/library/nature.js';
import { building } from '../../src/library/exteriors.js';
import { lantern, railing } from '../../src/library/structures.js';
import { cat } from '../../src/library/creatures.js';

const STREET_Y = -5.5;
const WATER_Y = -7.2;
const GOLD = ['#e0a020', '#f0c030', '#d08018', '#f8d050', '#c87018'];

// Steel factory window: thin dark mullions in a cols x rows grid, deep sill. Returns glass rect.
function factoryWindow(b, { x0, x1, y0, y1, cols, rows }) {
  const steel = { ...mat.metal('#23252a', 0.4), bevel: 0.01 };
  const z = -0.25, t = 0.07;
  b.box([x0, y0, z - t], [x1, y0 + 0.14, z + t], steel);
  b.box([x0, y1 - 0.14, z - t], [x1, y1, z + t], steel);
  for (let c = 0; c <= cols; c++) { const x = x0 + ((x1 - x0) * c) / cols; b.box([x - (c % cols ? t / 2 : t), y0, z - t], [x + (c % cols ? t / 2 : t), y1, z + t], steel); }
  for (let r = 1; r < rows; r++) { const y = y0 + ((y1 - y0) * r) / rows; b.box([x0, y - t / 2, z - t], [x1, y + t / 2, z + t], steel); }
  return { x0, x1, y0, y1, glassZ: z - 0.01 };
}

// Narrow gabled townhouse (Amsterdam-ish canal house, original proportions) facing +z at z.
function townhouse(b, { x, z, w, floors, rng, wall, trim = '#d8d0c0' }) {
  const fh = 5.4;
  const h = floors * fh;
  const spec = building(b, {
    x0: x - w / 2, x1: x + w / 2, z, y0: STREET_Y + 4.8, depth: 10, height: STREET_Y + 4.8 + h, rng, wall, lit: rng.range(0.4, 0.7),
    cellW: Math.round((w * 16) / Math.max(2, Math.round(w / 2.6))), cellH: Math.round(fh * 16), winW: 18, winH: 40, glow: 2.2, panes: true, wallGlow: 0.08,
  });
  void spec;
  const top = STREET_Y + 4.8 + h;
  // Stepped gable.
  const gm = { tex: { name: 'brick', color: '#f2f2f2', mortar: '#9a9a9a' }, tint: wall, rough: 0.9 };
  for (let i = 0; i < 4; i++) {
    const hw = (w / 2) * (1 - i * 0.22);
    b.box([x - hw, top + i * 1.2, z - 0.6], [x + hw, top + (i + 1) * 1.2, z], gm);
  }
  b.box([x - 0.35, top + 4.8, z - 0.6], [x + 0.35, top + 5.6, z + 0.15], mat.plain(trim, 0.6)); // hoist beam
  b.box([x - w / 2 - 0.15, top - 0.3, z - 0.3], [x + w / 2 + 0.15, top, z + 0.25], mat.plain(trim, 0.6));
  // Ground floor shop with awning.
  const shop = rng.pick(['#ffb85c', '#ff9a50', '#ffc878', '#f0a060']);
  b.box([x - w / 2, STREET_Y, z - 1], [x + w / 2, STREET_Y + 4.8, z], mat.plain(rng.pick(['#2a2420', '#1e2a26', '#2a1e22']), 0.6));
  b.box([x - w / 2 + 0.6, STREET_Y + 0.6, z + 0.02], [x + w / 2 - 0.6, STREET_Y + 3.8, z + 0.1], { tex: { name: 'litWindow', color: shop, frame: '#1e1814', curtain: shop, w: 32, h: 24, cols: 3, rows: 2, curtainW: 0 }, tint: '#ffffff', emissive: 1.8, emissiveColor: '#ffffff', cast: false });
  const aw = rng.pick([['#6a2a2a', '#d8c8a8'], ['#2a4a3a', '#d8c8a8'], ['#2a3a5a', '#d0c0a0'], ['#7a5a2a', '#e0d0b0']]);
  b.at([x, STREET_Y + 4.1, z], 0, () => b.box([-w / 2 + 0.3, 0, 0], [w / 2 - 0.3, 0.35, 2.2], { tex: { name: 'stripes', colors: aw, width: 4 }, tint: '#ffffff', rough: 1 }), { rotX: 0.35 });
  return { shopLight: [x, STREET_Y + 2.4, z + 2.5], top };
}

export default {
  name: 'loft',
  title: 'Canal Bookshop Loft',
  seed: 7,
  fps: 30,
  loopSeconds: 60,
  camera: { pos: [9.8, 3.2, 7.4], target: [7.4, 1.2, -16], fov: 66 },
  background: '#141422',
  ssaa: 2,
  envProbe: { pos: [8, 2.8, 5], intensity: 0.55, size: 256 },
  post: {
    toneMapping: 'aces',
    exposure: 1.05,
    fog: { color: '#3c3a52', density: 0.006 },
    bloom: { strength: 0.5, radius: 0.55, threshold: 0.85 },
    ao: { radius: 0.6, blend: 1.0 },
    grade: { lift: [0.012, 0.01, 0.02], gamma: [1, 1, 1], gain: [1.03, 1.0, 0.96], saturation: 1.08, contrast: 1.04 },
    vignette: 0.45,
  },

  async build(ctx) {
    const { b, rng, light } = ctx;
    const brick = { tex: { name: 'brick', color: '#8a4a32', mortar: '#4a3428' }, tint: '#ffffff', rough: 0.9 };
    const plaster = mat.plaster('#b98a62');
    const beam = mat.wood('#3e2416');

    // --- Shell -----------------------------------------------------------------------------------
    b.box([-1, -1, -0.5], [17, 0, 12.5], mat.planks('#7a5232'), { uv: 'world' });
    b.box([-1, 6.5, -0.5], [17, 7.5, 12.5], mat.planks('#5a3a24'), { uv: 'world' });
    for (let x = 1.5; x < 16; x += 3.5) b.box([x, 6.0, -0.5], [x + 0.5, 6.5, 12.5], beam);
    b.box([-1, 0, -0.5], [0, 6.5, 12.5], brick, { uv: 'world' });
    b.box([16, 0, -0.5], [17, 6.5, 12.5], plaster, { uv: 'world' });
    b.box([-1, -1, 12.5], [17, 7.5, 13], plaster, { uv: 'world' });
    const [wx0, wx1, wy0, wy1] = [0.9, 15.1, 0.75, 5.9];
    b.box([0, 0, -0.5], [wx0, 6.5, 0], brick, { uv: 'world' });
    b.box([wx1, 0, -0.5], [16, 6.5, 0], brick, { uv: 'world' });
    b.box([wx0, 0, -0.5], [wx1, wy0, 0], brick, { uv: 'world' });
    b.box([wx0, wy1, -0.5], [wx1, 6.5, 0], brick, { uv: 'world' });
    const win = factoryWindow(b, { x0: wx0, x1: wx1, y0: wy0, y1: wy1, cols: 9, rows: 4 });
    // Outside ledge below the window.
    b.box([wx0 - 0.2, wy0 - 0.25, -0.9], [wx1 + 0.2, wy0 - 0.05, -0.4], { tex: { name: 'stone' }, tint: '#7a7068', rough: 0.6 });
    // Outer facade of our own building (seen in the window's depth, and in reflections).
    b.box([-30, STREET_Y, -0.9], [46, -0.9, -0.5], brick, { uv: 'world' });

    // --- Window seat with cushions and the cat ----------------------------------------------------
    b.box([wx0, 0, 0], [wx1, 0.7, 1.5], mat.wood('#4a2c18'));
    for (let x = wx0 + 0.2; x < wx1 - 1; x += 1.6) b.box([x, 0.12, 1.5], [x + 1.4, 0.55, 1.52], mat.wood('#5a3620'));
    b.box([wx0 + 0.05, 0.7, 0.05], [wx1 - 0.05, 0.95, 1.45], mat.fabric('#5a2a28'));
    const cushions = [[1.9, 0.3, '#c98a3a'], [2.7, 0.05, '#d9c49a'], [6.4, -0.2, '#4e6a6e'], [12.8, 0.25, '#a0503a'], [13.6, -0.15, '#d9c49a']];
    for (const [x, r, c] of cushions) b.at([x, 0.95, 0.45], r, () => cushion(b, { w: 0.85, h: 0.7, m: x === 2.7 || x === 13.6 ? mat.knit(c) : mat.fabric(c) }));
    b.at([11.6, 0.95, 0.75], 0, () => throwBlanket(b, { w: 1.4, flat: 0.7, hang: 0.9, m: mat.knit('#a0503a') }));
    b.at([4.4, 0.95, 0.8], 0.15, () => bookStack(b, { n: 3, rng: rng.fork('seat-books') }));
    let mugTop;
    b.at([5.0, 0.95, 1.05], 0, () => { mugTop = mug(b, { tint: '#d8c8a8' }); });
    steam(ctx, { pos: mugTop, rng: rng.fork('steam'), h: 0.7, count: 10 });
    const kitty = cat({ pose: 'curled', fur: '#3a3430', light: '#e8e0d4' });
    kitty.group.position.set(9.0, 0.95, 0.75);
    kitty.group.rotation.y = 0.2;
    kitty.group.scale.setScalar(1.7);
    ctx.add(kitty.group);
    b.at([7.6, 0.95, 0.55], 0, () => candle(b, { h: 0.26 }));
    b.at([14.4, 0.95, 0.5], 0, () => pottedPlant(b, { rng: rng.fork('sill-plant'), potW: 0.45, potH: 0.4, height: 1.1, spread: 0.4, clumps: 10, clump: [0.22, 0.32], leaf: { palette: ['#4f7a3a', '#5e8a44', '#3a6230'] } }));
    stringLights(b, { points: [[wx0 + 0.1, 5.95, 0.25], [8, 5.95, 0.25], [wx1 - 0.1, 5.95, 0.25]], n: 30, sag: 0.45, rng: rng.fork('lights'), glow: 1.6 });
    for (const [x, d] of [[3.2, 1.1], [12.6, 0.9]]) b.at([x, 6.5, 1.0], 0, () => hangingPlant(b, { rng: rng.fork(`hp${x}`), drop: d, maxLen: 1.6, leaf: { palette: ['#5a8a42', '#6a9a4a', '#4a7a3a'] } }));

    // --- Library wall (left) + reading chair ----------------------------------------------------
    for (const [i, z] of [3.4, 5.8, 8.2].entries()) b.at([0.36, 0, z], Math.PI / 2, () => bookshelf(b, { w: 2.4, h: 6.0, d: 0.7, shelves: 7, m: mat.wood('#4a2a18'), rng: rng.fork(`shelf${i}`), fill: 0.92 }));
    b.at([1.25, 0, 6.6], 0, () => {
      const m = mat.wood('#5a3620');
      b.box([-T, 0, -0.35], [T, 6.0, -0.25], m);
      b.box([-T, 0, 0.25], [T, 6.0, 0.35], m);
      for (let y = 0.5; y < 5.9; y += 0.6) b.box([-T, y, -0.25], [T, y + 2 * T, 0.25], m);
    }, { rotZ: 0.12 });
    b.at([4.4, 0, 6.2], 0, () => rug(b, { w: 5, d: 4, palette: ['#7a2e1e', '#c98a3a', '#2e2430', '#d8b98a'], style: 'steps' }));
    b.at([3.5, 0, 5.6], 0.9, () => armchair(b, { fabric: mat.fabric('#6a3a2a') }));
    b.at([3.45, 0.8, 5.6], 0.9, () => cushion(b, { w: 0.7, h: 0.55, m: mat.knit('#c8a060'), tilt: 0.5 }));
    let lampPos;
    b.at([2.2, 0, 4.2], 0, () => { lampPos = floorLamp(b, { h: 3.4, shadeColor: '#ffcf96', glow: 0.9 }); });
    b.at([5.2, 0, 4.8], 0, () => table(b, { w: 1.0, d: 1.0, h: 1.05, top: mat.wood('#5a3620') }));
    b.at([5.0, 1.05, 4.7], 0.3, () => teapot(b, { tint: '#4e6e6a' }));
    b.at([5.4, 1.05, 5.0], 0.4, () => bookStack(b, { n: 2, rng: rng.fork('table-books') }));

    // --- Right side: desk, crates of books, plant -----------------------------------------------
    b.at([14.2, 0, 4.4], -Math.PI / 2, () => table(b, { w: 2.6, d: 1.2, h: 1.5, top: mat.wood('#6a4226') }));
    let deskLantern;
    b.at([14.4, 1.5, 3.6], 0, () => { deskLantern = lantern(b, { s: 0.36, glow: 0.35 }); });
    b.at([14.3, 1.5, 4.8], 0.2, () => bookStack(b, { n: 4, rng: rng.fork('desk-books') }));
    b.at([15.2, 0, 7.4], 0.1, () => crate(b, {}));
    b.at([15.2, 0.7, 7.4], 0, () => bookStack(b, { n: 3, rng: rng.fork('crate-books') }));
    b.at([15.95, 3.2, 6.4], -Math.PI / 2, () => pictureFrame(b, { w: 1.3, h: 1.0, palette: ['#d8a060', '#a05a3a', '#4a5a4a', '#2a2a38'] }));
    b.at([15.0, 0, 1.9], 0, () => pottedPlant(b, { rng: rng.fork('fig'), potW: 0.7, potH: 0.75, height: 3.2, spread: 0.8, clumps: 20, clump: [0.35, 0.6], leaf: { palette: ['#3e6a32', '#4a7a3a', '#2e5a2a'] } }));

    // --- Exterior: our street + canal + far quay ------------------------------------------------
    const er = rng.fork('outside');
    b.box([-60, STREET_Y - 1, -4], [80, STREET_Y, -0.5], { tex: { name: 'stone' }, tint: '#4a4644', rough: 0.35 }, { uv: 'world' }); // wet cobbles
    b.box([-60, WATER_Y - 3, -5], [80, STREET_Y, -4], { tex: { name: 'stone' }, tint: '#5a5450', rough: 0.7 }, { uv: 'world' }); // quay wall
    b.box([-60, WATER_Y - 3, -32], [80, STREET_Y, -31], { tex: { name: 'stone' }, tint: '#5a5450', rough: 0.7 }, { uv: 'world' });
    b.box([-60, STREET_Y - 1, -40], [80, STREET_Y, -31], { tex: { name: 'stone' }, tint: '#4a4644', rough: 0.35 }, { uv: 'world' });
    await lake(ctx, { x0: -60, x1: 80, z0: -4, z1: -31, y: WATER_Y, color: '#0c1016', reflect: 0.9, ripple: 0.014, fog: { color: '#3c3a52', density: 0.006 }, resolution: [1920, 1080] });

    // Railings + lamp posts along our quay; mooring posts.
    const lamps = [];
    b.at([0, STREET_Y, -3.8], 0, () => railing(b, { x0: -40, x1: 60, z: 0, h: 1.2, m: mat.metal('#1c1c20', 0.5), postEvery: 4, balusterEvery: 0.6 }));
    for (let x = -34; x < 60; x += 28) {
      b.box([x - 0.18, STREET_Y, -3.2], [x + 0.18, STREET_Y + 7.5, -2.84], mat.metal('#1c1c20', 0.5));
      b.atWorld([x, STREET_Y + 7.5, -3.02], 0, () => lamps.push(lantern(b, { s: 0.7, glow: 7, color: '#ffc070' })));
    }
    // Far quay: townhouses, trees, lamps.
    const shopLights = [];
    let x = -46;
    const tr = er.fork('houses');
    while (x < 66) {
      const w = tr.range(5.5, 8);
      const h = townhouse(b, { x: x + w / 2, z: -40, w, floors: tr.int(3, 4), rng: tr, wall: tr.pick(['#6a3a2e', '#3a3a44', '#5a4a3a', '#7a5a42', '#4a2e2a', '#2e3a3a']) });
      shopLights.push(h.shopLight);
      x += w + 0.05;
    }
    for (let tx = -40; tx < 64; tx += tr.range(9, 13)) {
      b.box([tx - 0.3, STREET_Y, -34.6], [tx + 0.3, STREET_Y + 9, -34], { tex: { name: 'bark', color: '#f2f2f2' }, tint: '#2e2620', rough: 1 });
      leafBlob(b, { c: [tx, STREET_Y + 11, -34.3], r: tr.range(3.4, 4.4), rng: tr, palette: GOLD, leaf: 0.4, squash: 0.85, cover: 7 });
    }
    for (let lx = -38; lx < 62; lx += 14) {
      b.box([lx - 0.15, STREET_Y, -32.4], [lx + 0.15, STREET_Y + 6.5, -32.1], mat.metal('#1c1c20', 0.5));
      b.atWorld([lx, STREET_Y + 6.5, -32.25], 0, () => lamps.push(lantern(b, { s: 0.6, glow: 7, color: '#ffc070' })));
    }
    // Arched footbridge across the canal with lamps.
    const bx = 18;
    for (let i = 0; i <= 27; i++) {
      const z = -4 - i, k = i / 27, y = STREET_Y + Math.sin(k * Math.PI) * 2.2;
      b.box([bx - 2, y - 0.5, z - 1], [bx + 2, y, z], { tex: { name: 'brick', color: '#8a5a42', mortar: '#4a3a30' }, tint: '#ffffff', rough: 0.8 });
      for (const s of [-1, 1]) b.box([bx + s * 2 - 0.15, y, z - 1], [bx + s * 2 + 0.15, y + 1.1, z], mat.metal('#1c1c20', 0.5));
    }
    b.box([bx - 1.9, WATER_Y - 2, -19], [bx + 1.9, STREET_Y + 1.2, -16], { tex: { name: 'brick', color: '#8a5a42', mortar: '#4a3a30' }, tint: '#ffffff', rough: 0.8 });
    b.box([bx - 1.95, WATER_Y, -18.9], [bx + 1.95, STREET_Y - 0.3, -16.1], mat.plain('#0a0a0e', 1)); // pier shadow
    for (const z of [-6, -29]) b.atWorld([bx + 2, STREET_Y + 2.2 * Math.sin(((-4 - z) / 27) * Math.PI) + 1.1, z], 0, () => lamps.push(lantern(b, { s: 0.45, glow: 7 })));
    // Moored boats.
    for (const [mx, c] of [[-4, '#2a4a5a'], [30, '#6a2a22'], [44, '#2a3a2a']]) b.at([mx, WATER_Y, -27.5], 0, () => {
      const hull = { ...mat.wood(c), rough: 0.4 };
      b.box([-4.5, -0.3, -1.2], [4.5, 1.0, 1.2], hull);
      b.box([-3.5, 1.0, -1.0], [2.0, 2.4, 1.0], mat.wood('#5a3a24'));
      b.box([-3.2, 1.5, 1.0], [1.6, 2.1, 1.05], { tex: { name: 'litWindow', color: '#ffb35c', frame: '#2a1a10', curtain: '#8a3a2a', w: 48, h: 10, cols: 4, rows: 1, curtainW: 0 }, tint: '#ffffff', emissive: 1.6, emissiveColor: '#ffffff', cast: false });
      b.box([-3.7, 2.4, -1.15], [2.2, 2.6, 1.15], mat.plain('#1e1a18', 0.6));
    });

    // Distant rooftops + sky.
    for (let i = 0; i < 30; i++) {
      const dx = er.range(-160, 200), dz = er.range(-70, -140), w = er.range(8, 18), h = er.range(14, 40);
      building(b, { x0: dx, x1: dx + w, z: dz, y0: STREET_Y, depth: 10, height: STREET_Y + h, rng: er, wall: er.pick(['#2a2630', '#302a2c']), lit: er.range(0.25, 0.45), cellW: 20, cellH: 80, winW: 10, winH: 34, glow: 2.2, wallGlow: 0.06 });
      b.box([dx + 1, STREET_Y + h, dz - 9], [dx + w - 1, STREET_Y + h + 4, dz - 1], mat.plain('#1a1820', 1));
    }
    sky(ctx, { center: [8, 60, -500], w: 1800, h: 420, top: '#100e1c', bottom: '#4a3c4c' });
    const cr = er.fork('clouds');
    for (let i = 0; i < 14; i++) cloud(b, { c: [cr.range(-300, 300), cr.range(50, 130), cr.range(-380, -440)], w: cr.range(80, 160), h: cr.range(12, 24), rng: cr, color: '#262232', light: '#3a3446', pieces: 10 });
    hazeCard(ctx, { center: [8, STREET_Y + 8, -60], w: 600, h: 30, color: '#3c3a52', opacity: 0.35 });
    hazeCard(ctx, { center: [8, STREET_Y + 20, -150], w: 900, h: 70, color: '#3c3a52', opacity: 0.55 });
    fallingLeaves(ctx, { min: [-20, STREET_Y + 1, -36], max: [50, STREET_Y + 12, -32], count: 10, rng: er.fork('leaves'), palette: GOLD, active: 0.35, size: 0.45 });

    // Rain: in front of the glass, over the canal, far.
    rain(ctx, { min: [-6, STREET_Y, -6], max: [22, 8, -1.0], count: 300, color: '#d0ccd8', opacity: 0.08, rng: rng.fork('rain-near'), len: [0.5, 0.9], speed: 18, tilt: 0.06, width: T / 2 });
    rain(ctx, { min: [-50, STREET_Y, -40], max: [70, 22, -6], count: 4500, color: '#b0aac8', opacity: 0.07, rng: rng.fork('rain-mid'), len: [0.9, 1.6], speed: 18, tilt: 0.06, width: T });
    glass(ctx, { x0: win.x0, x1: win.x1, y0: win.y0, y1: win.y1, z: win.glassZ, tint: '#3a3448', opacity: 0.08 });
    const dropsFrame = new THREE.Group();
    dropsFrame.position.z = win.glassZ - 0.01;
    ctx.add(dropsFrame);
    glassDrops(ctx, { x0: win.x0, x1: win.x1, y0: win.y0, y1: win.y1, rng: rng.fork('drops'), beads: 140, sliders: 18, parent: dropsFrame, opacity: 0.14, color: '#d8d0e0' });

    // --- Lights -----------------------------------------------------------------------------------
    light.hemi({ sky: '#5a5070', ground: '#4a2a18', intensity: 0.9 });
    light.dir({ pos: [-60, 90, -160], target: [8, 0, 0], color: '#7a7aa8', intensity: 0.9 });
    light.point({ pos: lampPos, color: '#ffbe7a', intensity: 22, shadow: true, mapSize: 2048, softness: 6 });
    light.point({ pos: deskLantern, color: '#ffb060', intensity: 5 });
    light.point({ pos: [8, 5.0, 1.6], color: '#ffb070', intensity: 20, shadow: true, mapSize: 2048, softness: 8 }); // string lights over the seat
    light.point({ pos: [8, 5.6, 7], color: '#ffa860', intensity: 14 }); // warm bounce fill
    const fl = flicker(rng.fork('candle'), ctx.loopSeconds, { amount: 0.15 });
    const cl = light.point({ pos: [7.6, 1.55, 0.9], color: '#ff9a40', intensity: 1.5, distance: 4 });
    ctx.animate((t) => { cl.intensity = 1.5 * fl(t); });
    for (const p of lamps) light.point({ pos: p, color: '#ffb060', intensity: 30, distance: 14 });
    for (const p of shopLights) light.point({ pos: p, color: '#ffa850', intensity: 25, distance: 10 });
  },
};
