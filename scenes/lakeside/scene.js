// Concept C : "Lakeside Stilt Cabin": a small writing room on stilts over a rainy lake at blue hour.
// A wide multi-pane window (rain beads and runs on the glass) looks across the water to a village of
// lit cottages at the foot of pine hills; their lights stretch into long reflections. Outside right,
// a rowboat is moored at the cabin's little dock under a lantern. Inside: a writing desk with an oil
// lamp, a cast-iron stove with fire glowing through its door, a sleeping spaniel on a round rug.
// Units: 1 block ~ 0.5 m. Room x 0..14, z 0..11, y 0..6; window in the back wall (z = 0).
import * as THREE from 'three';
import { mat, T, bookshelf, armchair, rug, mug, bookStack, candle, cushion, throwBlanket, pottedPlant, hangingPlant, table, chair, windowFrame, tableLamp, teapot, pictureFrame, logBasket, crate } from '../../src/library/props.js';
import { rain, glassDrops, steam, hazeCard, sky, glass, flicker, fire, lake } from '../../src/library/effects.js';
import { pine, cloud, hillside, leafBlob } from '../../src/library/nature.js';
import { lantern, cottage, dock, wallLantern } from '../../src/library/structures.js';
import { spaniel } from '../../src/library/creatures.js';

const WATER_Y = -2.2;
const PINE = ['#2e4a3a', '#3a5a44', '#25402f', '#466a50'];

// Cast-iron wood stove with a glowing door window; returns fire/light positions.
function stove(b) {
  const iron = { ...mat.metal('#2a2624', 0.45), bevel: 0.03 };
  b.box([-0.75, 0.3, -0.6], [0.75, 1.55, 0.6], iron);
  for (const x of [-0.65, 0.5]) for (const z of [-0.5, 0.35]) b.box([x, 0, z], [x + 0.15, 0.3, z + 0.15], iron);
  b.box([-0.85, 1.55, -0.7], [0.85, 1.7, 0.7], iron);
  b.box([-0.18, 1.7, -0.3], [0.18, 6, 0.06], iron); // flue
  b.box([-0.5, 0.5, 0.6], [0.5, 1.25, 0.66], iron);
  b.box([-0.36, 0.62, 0.6], [0.36, 1.13, 0.67], { tex: { name: 'litWindow', color: '#ff7a24', frame: '#1a1412', curtain: '#ff4a10', w: 12, h: 8, cols: 3, rows: 1, curtainW: 0 }, tint: '#ffffff', emissive: 1.2, emissiveColor: '#ffffff', cast: false }); // glass door
  b.box([0.42, 0.85, 0.66], [0.5, 0.95, 0.76], mat.metal('#a08050', 0.3));
  return { firePos: b.world([0, 0.5, 0.35]), lightPos: b.world([0, 0.7, 1.9]) };
}

export default {
  name: 'lakeside',
  title: 'Lakeside Stilt Cabin',
  seed: 23,
  fps: 30,
  loopSeconds: 60,
  camera: { pos: [9.2, 2.7, 8.2], target: [6.9, 2.75, -10], fov: 64 },
  background: '#1a2232',
  ssaa: 2,
  envProbe: { pos: [7, 2.4, 4], intensity: 0.5, size: 256 },
  post: {
    toneMapping: 'aces',
    exposure: 1.05,
    fog: { color: '#5a6480', density: 0.0045 },
    bloom: { strength: 0.5, radius: 0.55, threshold: 0.85 },
    ao: { radius: 0.6, blend: 1.0 },
    grade: { lift: [0.012, 0.014, 0.022], gamma: [1, 1, 1], gain: [1.03, 1.0, 0.97], saturation: 1.08, contrast: 1.04 },
    vignette: 0.45,
  },

  async build(ctx) {
    const { b, rng, light } = ctx;
    const plank = mat.planks('#8a6040');
    const wallWood = { tex: { name: 'planks', color: '#f2f2f2', plank: 4 }, tint: '#9a6c46', rough: 0.6 };
    const beam = mat.wood('#4a2e1c');

    // --- Room shell (vertical-plank walls) ---------------------------------------------------------
    b.box([-1, -1, -0.5], [15, 0, 12], plank, { uv: 'world' });
    b.box([-1, 6, -0.5], [15, 7, 12], mat.planks('#6a4a30'), { uv: 'world' });
    for (let x = 1.5; x < 14; x += 3) b.box([x, 5.55, -0.5], [x + 0.45, 6, 12], beam);
    b.at([0, 0, 0], 0, () => {
      b.box([-1, 0, -0.5], [0, 6, 12], wallWood, { uv: 'world' });
      b.box([14, 0, -0.5], [15, 6, 12], wallWood, { uv: 'world' });
      b.box([-1, -1, 12], [15, 7, 12.5], wallWood, { uv: 'world' });
    });
    // Back wall with a wide window x 1.6..11.4, y 1.3..4.7.
    const [wx0, wx1, wy0, wy1] = [0.9, 12.6, 1.6, 5.4];
    b.box([-1, 0, -0.5], [wx0, 6, 0], wallWood, { uv: 'world' });
    b.box([wx1, 0, -0.5], [15, 6, 0], wallWood, { uv: 'world' });
    b.box([wx0, 0, -0.5], [wx1, wy0, 0], wallWood, { uv: 'world' });
    b.box([wx0, wy1, -0.5], [wx1, 6, 0], wallWood, { uv: 'world' });
    const win = windowFrame(b, { x0: wx0, x1: wx1, y0: wy0, y1: wy1, z: 0, cols: 6, rows: 2, m: mat.wood('#3a2416'), sill: true, sillDepth: 0.5, reveal: 0.5 });
    b.box([0, 0, -0.1], [14, 0.3, 0], beam);

    // --- Desk under the window ---------------------------------------------------------------------
    let lampPos, mugTop;
    b.at([4.6, 0, 1.2], 0, () => table(b, { w: 3.6, d: 1.4, h: 1.5, top: mat.wood('#6a4226') }));
    b.at([3.4, 1.5, 1.0], 0, () => { lampPos = tableLamp(b, { h: 1.0, shadeW: 0.55, shadeH: 0.4, shadeColor: '#ffc88a', glow: 1.6 }); });
    b.at([5.2, 1.5, 1.3], 0.2, () => bookStack(b, { n: 4, rng: rng.fork('desk-books') }));
    b.at([4.4, 1.5, 1.55], 0, () => b.box([-0.35, 0, -0.25], [0.35, 0.03, 0.25], { tex: { name: 'paper' }, tint: '#ffffff', rough: 0.9 }));
    b.at([6.0, 1.5, 1.5], 0, () => { mugTop = mug(b, { tint: '#3e5a6a' }); });
    b.at([5.9, 1.5, 0.9], 0, () => teapot(b, { tint: '#8a4a32' }));
    b.at([4.6, 0, 2.6], Math.PI, () => chair(b, { m: mat.wood('#5a3620'), cushion: mat.fabric('#5a6e7a') }));
    steam(ctx, { pos: mugTop, rng: rng.fork('steam'), h: 0.7, count: 10 });
    b.at([10.4, 1.5, 0.75], 0, () => pottedPlant(b, { rng: rng.fork('sill-plant'), potW: 0.4, potH: 0.35, height: 0.9, spread: 0.4, clumps: 9, clump: [0.2, 0.3], leaf: { tex: { name: 'leaves' }, palette: ['#4f7a3a', '#5e8a44', '#3a6230', '#6a9a4a'], tint: '#4f7a3a' } }));
    b.at([8.9, 1.5, 0.7], 0, () => candle(b, { h: 0.28 }));
    b.at([9.4, 1.5, 0.75], 0.3, () => bookStack(b, { n: 2, rng: rng.fork('sill-books') }));

    // --- Stove corner (right) ----------------------------------------------------------------------
    let st;
    b.box([12.5, 0, 0], [14, 0.12, 2.4], { tex: { name: 'stone' }, tint: '#7a7068', rough: 0.85 });
    b.box([12.5, 0, 0], [14, 3.4, 0.1], { tex: { name: 'brick', color: '#8a5a42', mortar: '#4a3a30' }, tint: '#ffffff', rough: 0.9 });
    b.at([13.25, 0.12, 0.95], -0.35, () => { st = stove(b); });
    b.at([12.2, 0, 2.6], 0.3, () => logBasket(b, { rng: rng.fork('logs') }));
    b.at([2.6, 0, 6.6], 0.6, () => armchair(b, { fabric: { tex: { name: 'plaid', a: '#8a3a2a', b: '#2a1814', c: '#c8a060', size: 3 }, tint: '#ffffff', rough: 1 } }));
    b.at([2.55, 0.8, 6.55], 0.6, () => cushion(b, { w: 0.7, h: 0.55, m: mat.knit('#c8a060'), tilt: 0.5 }));
    b.at([2.1, 2.1, 6.15], 0.6, () => throwBlanket(b, { w: 1.1, flat: 0.5, hang: 1.0, m: mat.knit('#a04a3a') }));
    // Paddles and a coiled rope on the right wall.
    for (const [z, rot] of [[6.4, 0.08], [7.0, -0.06]]) b.at([13.92, 0.4, z], 0, () => {
      b.box([-0.04, 0, -0.05], [0.04, 3.0, 0.05], mat.wood('#a07a4a'));
      b.box([-0.05, 3.0, -0.2], [0.05, 3.9, 0.2], mat.wood('#8a5a32'));
    }, { rotX: rot });
    b.at([13.9, 3.3, 8.4], -Math.PI / 2, () => b.box([-0.35, -0.35, 0], [0.35, 0.35, 0.18], { tex: { name: 'rope', color: '#f2f2f2' }, tint: '#b8945a', rough: 1 }));
    let wallL;
    b.at([13.98, 3.8, 9.6], -Math.PI / 2, () => { wallL = wallLantern(b, { reach: 0.6, drop: 0.15, s: 0.4, glow: 2.5 }); });

    // --- Left wall: shelves, picture, crate --------------------------------------------------------
    for (const [i, z] of [3.0, 5.4].entries()) b.at([0.36, 0, z], Math.PI / 2, () => bookshelf(b, { w: 2.4, h: 5.2, d: 0.7, shelves: 6, m: mat.wood('#5a3420'), rng: rng.fork(`shelf${i}`), fill: 0.9 }));
    b.at([0.05, 2.8, 8.2], Math.PI / 2, () => pictureFrame(b, { w: 1.3, h: 1.0, palette: ['#c8b890', '#6a8aa0', '#3a5a4a', '#1e2a30'] }));
    b.at([1.1, 0, 8.6], 0.2, () => crate(b, {}));
    b.at([1.1, 0.7, 8.6], 0, () => pottedPlant(b, { rng: rng.fork('fern'), potW: 0.45, potH: 0.4, height: 1.1, spread: 0.45, clumps: 12, clump: [0.25, 0.35], leaf: { tex: { name: 'leaves' }, palette: ['#3f6b34', '#4f7a3a', '#5a8a42'], tint: '#3f6b34' } }));
    b.at([2.4, 6, 3.4], 0, () => hangingPlant(b, { rng: rng.fork('hp'), drop: 1.0, maxLen: 1.5, leaf: { tex: { name: 'leaves' }, palette: ['#5a8a42', '#6a9a4a', '#4a7a3a'], tint: '#5a8a42' } }));

    // --- Rug + spaniel -----------------------------------------------------------------------------
    b.at([9.8, 0, 3.8], 0, () => rug(b, { w: 5, d: 4, palette: ['#2e4a5a', '#c8a060', '#1e2a30', '#d8c8a0'], style: 'steps' }));
    const dog = spaniel({ pose: 'sleep' });
    dog.group.position.set(10.6, T, 3.4);
    dog.group.rotation.y = 0.55;
    dog.group.scale.setScalar(1.45);
    ctx.add(dog.group);

    // --- Exterior: stilts, dock, rowboat ----------------------------------------------------------
    for (const x of [0, 5, 10, 14]) b.box([x - 0.25, WATER_Y - 3, -0.9], [x + 0.25, -1, -0.4], mat.wood('#3a2a1e'));
    b.box([-1, -1.2, -1], [15, -1, 0], mat.wood('#4a3424'));
    let dockLamp;
    b.at([16.5, WATER_Y + 0.6, -1.5], 0, () => { [dockLamp] = dock(b, { len: 9, w: 2.6, y: 0.4, postDepth: 3, lanternEvery: 8 }); });
    // Rowboat (simple stepped hull) moored beside the dock.
    b.at([13.6, WATER_Y, -6.5], 0.15, () => {
      const hull = { ...mat.wood('#7a4a2a'), rough: 0.45 };
      b.box([-0.7, -0.1, -2.6], [0.7, 0.5, 2.6], hull);
      b.box([-0.5, -0.3, -2.2], [0.5, -0.1, 2.2], hull);
      b.box([-0.55, 0.0, -2.45], [0.55, 0.45, 2.45], mat.plain('#2a1e16', 1));
      b.box([-0.7, 0.42, -0.25], [0.7, 0.52, 0.25], mat.wood('#a07a4a'));
      b.box([-0.25, 0.5, -2.9], [0.25, 0.75, -2.5], hull);
    });

    // Lake with reflections and rain rings.
    await lake(ctx, { x0: -400, x1: 400, z0: -1, z1: -400, y: WATER_Y, color: '#0e161e', reflect: 0.85, ripple: 0.018, fog: { color: '#5a6480', density: 0.0045 }, resolution: [1920, 1080] });

    // Far shore village (z ~ -70): cottages on stone bases, lamp posts, a small jetty.
    const vr = rng.fork('village');
    const shoreZ = -66;
    b.box([-200, WATER_Y - 1, shoreZ - 30], [240, WATER_Y + 0.8, shoreZ], mat.plain('#2a2e2c', 0.9));
    const villageLights = [];
    let x = -58;
    while (x < 70) {
      const w = vr.range(5, 8), d = vr.range(4.5, 6);
      const z = shoreZ - vr.range(3, 9);
      const y0 = WATER_Y + 0.8 + vr.range(0, 1.5);
      b.at([x, y0, z], vr.range(-0.25, 0.25), () => cottage(b, { w, d, h: vr.range(3.2, 4.2), rng: vr, wall: vr.pick(['#8a6a48', '#7a5a42', '#9a7a58', '#6a7480']), roof: vr.pick(['#3a2a24', '#2e3236', '#4a2e26']), lit: 0.8, glow: 3.2 }));
      villageLights.push([x, y0 + 2, z + d / 2 + 1.5]);
      if (vr.chance(0.5)) {
        b.box([x + w / 2 + 1, WATER_Y + 0.8, shoreZ + 1], [x + w / 2 + 1.25, WATER_Y + 4.6, shoreZ + 1.25], mat.plain('#1a1612', 0.6));
        b.atWorld([x + w / 2 + 1.12, WATER_Y + 4.6, shoreZ + 1.12], 0, () => lantern(b, { s: 0.45, glow: 6 }));
      }
      x += w + vr.range(3, 9);
    }
    // Hills of pines behind the village, a few lit cabin windows on the slope.
    hillside(b, { rng: rng.fork('hills'), x0: -220, x1: 260, z0: shoreZ - 14, z1: -230, baseY: WATER_Y + 0.8, rise: 60, cell: 6, treeColor: '#22362a', ground: '#2a3430', trees: 0.75, far: true, treeH: [9, 16] });
    for (let i = 0; i < 9; i++) {
      const hx = vr.range(-120, 160), hz = vr.range(-95, -150);
      b.atWorld([hx, WATER_Y + 4 + (-(hz - shoreZ)) * 0.35, hz], 0, () => b.box([0, 0, 0], [0.9, 0.9, 0.2], mat.bulb('#ffb860', 2)));
    }
    // Near shore trees framing the window edges.
    const nr = rng.fork('near-trees');
    for (const [tx, tz, h] of [[-26, -24, 30], [-18, -34, 26], [34, -26, 28], [42, -36, 32]]) b.at([tx, WATER_Y - 0.5, tz], 0, () => pine(b, { h, rng: nr, color: '#3e5e48' }));

    sky(ctx, { center: [6, 50, -520], w: 1800, h: 420, top: '#222c44', bottom: '#7a84a0' });
    const cr = rng.fork('clouds');
    for (let i = 0; i < 16; i++) cloud(b, { c: [cr.range(-320, 320), cr.range(50, 140), cr.range(-380, -440)], w: cr.range(80, 160), h: cr.range(12, 26), rng: cr, color: '#2e3648', light: '#465068', pieces: 10 });
    hazeCard(ctx, { center: [6, WATER_Y + 6, -62], w: 600, h: 16, color: '#4a5468', opacity: 0.45 });
    hazeCard(ctx, { center: [6, WATER_Y + 30, -240], w: 1200, h: 80, color: '#5a6480', opacity: 0.5 });

    rain(ctx, { min: [-10, WATER_Y, -14], max: [22, 10, -1.2], count: 900, color: '#c8ccd8', opacity: 0.12, rng: rng.fork('rain-near'), len: [0.5, 0.9], speed: 18, tilt: 0.05, width: T / 2 });
    rain(ctx, { min: [-90, WATER_Y, -70], max: [110, 30, -14], count: 4500, color: '#a8b0c8', opacity: 0.08, rng: rng.fork('rain-mid'), len: [0.9, 1.6], speed: 18, tilt: 0.05, width: T });
    glass(ctx, { x0: win.x0, x1: win.x1, y0: win.y0, y1: win.y1, z: win.glassZ, tint: '#3a4250', opacity: 0.1 });
    const dropsFrame = new THREE.Group();
    dropsFrame.position.z = win.glassZ - 0.01;
    ctx.add(dropsFrame);
    glassDrops(ctx, { x0: win.x0, x1: win.x1, y0: win.y0, y1: win.y1, rng: rng.fork('drops'), beads: 120, sliders: 16, parent: dropsFrame, opacity: 0.12, color: '#d0d8e8' });

    // --- Lights --------------------------------------------------------------------------------------
    light.hemi({ sky: '#6a7090', ground: '#4a3020', intensity: 1.0 });
    light.dir({ pos: [-60, 90, -160], target: [6, 0, 0], color: '#8a96b8', intensity: 1.6 });
    light.dir({ pos: [0, 60, 200], target: [0, 0, -100], color: '#7a86a8', intensity: 1.4 }); // sky fill on the far shore
    light.dir({ pos: [80, 120, 160], target: [-10, 0, -60], color: '#a8a8c0', intensity: 1.2, shadow: true, mapSize: 4096, box: 150, far: 500, softness: 2, bias: -0.0005, normalBias: 0.05 });
    const fl = flicker(rng.fork('stove'), ctx.loopSeconds, { amount: 0.18, hz: [1.5, 6] });
    const stoveLight = light.point({ pos: st.lightPos, color: '#ff8a3a', intensity: 6, shadow: true, mapSize: 1024, softness: 6 });
    ctx.animate((t) => { stoveLight.intensity = 6 * fl(t); });
    light.point({ pos: lampPos, color: '#ffb468', intensity: 26, shadow: true, mapSize: 2048, softness: 6 });
    light.point({ pos: wallL, color: '#ffb060', intensity: 10 });
    light.point({ pos: [7, 4.8, 6], color: '#ffa860', intensity: 12 }); // warm bounce fill
    light.point({ pos: [11.0, 1.2, 3.0], color: '#ff9a50', intensity: 3, distance: 5 }); // stove spill on the dog
    if (dockLamp) light.point({ pos: dockLamp, color: '#ffa850', intensity: 25, distance: 14 });
    for (const p of villageLights) light.point({ pos: p, color: '#ffa850', intensity: 30, distance: 14 });
  },
};
