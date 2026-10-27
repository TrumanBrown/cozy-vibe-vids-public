// Builds the spike benchmark scene as data (seeded) so both engines render the same thing.
// Units: 1 = one block; 16 texels per block. Everything periodic in loopSeconds.
// Usage: node spikes/shared/gen-scene.mjs [outFile]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const outFile = path.resolve(process.argv[2] ?? path.join(here, 'scene.json'));

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(42);
const r = (a, b) => a + rand() * (b - a);
const ri = (a, b) => Math.floor(r(a, b + 1));
const round = (v) => Math.round(v * 1e4) / 1e4;

const T = 1 / 16;
const boxes = [];
const box = (name, min, max, tex, extra = {}) => boxes.push({ name, min, max, tex, ...extra });

// Room shell: floor, back wall with window opening (x 2..6, y 1..4), left wall, ceiling.
box('floor', [-1, -1, -1], [9, 0, 8], 'floor_planks');
box('ceiling', [-1, 5, -1], [9, 6, 8], 'wall_plaster');
box('wall_left', [-1, 0, -1], [0, 5, 8], 'wall_plaster');
box('wall_right', [8, 0, -1], [9, 5, 8], 'wall_plaster');
box('back_l', [0, 0, -1], [2, 5, 0], 'wall_plaster');
box('back_r', [6, 0, -1], [9, 5, 0], 'wall_plaster');
box('back_low', [2, 0, -1], [6, 1, 0], 'wall_plaster');
box('back_high', [2, 4, -1], [6, 5, 0], 'wall_plaster');

// Window frame (dark wood).
box('sill', [1.875, 0.875, -1], [6.125, 1, 0.25], 'wood_dark');
box('frame_top', [2, 3.875, -0.625], [6, 4, -0.375], 'wood_dark');
box('frame_l', [2, 1, -0.625], [2.125, 4, -0.375], 'wood_dark');
box('frame_r', [5.875, 1, -0.625], [6, 4, -0.375], 'wood_dark');
box('mullion', [3.9375, 1, -0.625], [4.0625, 4, -0.375], 'wood_dark');
box('transom', [2, 2.4375, -0.625], [6, 2.5625, -0.375], 'wood_dark');

// Side table + lamp (shade is emissive).
box('table_top', [6.25, 1, 0.75], [7.75, 1.125, 2.25], 'wood_dark');
for (const [x, z] of [[6.3125, 0.8125], [7.5625, 0.8125], [6.3125, 2.0625], [7.5625, 2.0625]])
  box('table_leg', [x, 0, z], [x + 0.125, 1, z + 0.125], 'wood_dark');
box('lamp_base', [6.75, 1.125, 1.25], [7.25, 1.25, 1.75], 'wood_dark');
box('lamp_pole', [6.9375, 1.25, 1.4375], [7.0625, 1.75, 1.5625], 'wood_dark');
box('lamp_shade', [6.6875, 1.75, 1.1875], [7.3125, 2.25, 1.8125], 'shade', { emissive: 2.4, emissiveColor: '#ff9a48' });

// Rug (one texel thick).
box('rug', [1.5, 0, 3], [5.5, T, 6], 'rug');

// Distant city: facades with lit windows, plus a sky backdrop.
let x = -22;
while (x < 30) {
  const w = ri(4, 9);
  const z0 = -ri(16, 40);
  box('tower', [x, -40, z0 - ri(4, 8)], [x + w, ri(-2, 22), z0], 'facade', { emissiveTex: 'facade_emit', emissive: 1.6 });
  x += w + ri(1, 3);
}
box('sky', [-120, -60, -91], [130, 80, -90], null, { color: '#1b1630' });

// Rain streaks outside: chunky 1-texel-wide pixel streaks; integer cycles per loop => periodic.
const rain = [];
for (let i = 0; i < 1400; i++) {
  rain.push([round(r(-8, 16)), round(r(-14, -1.25)), round(rand()), [12, 14, 16][ri(0, 2)], round(r(0.25, 0.5))]);
}

// Drops on the glass: a few slide down (integer cycles per loop), plus static beads.
const slide = [];
for (let i = 0; i < 10; i++) slide.push([round(r(2.2, 5.8)), round(rand()), ri(1, 2), T]);
const beads = [];
for (let i = 0; i < 70; i++) beads.push([round(r(2.15, 5.85)), round(r(1.05, 3.85)), T]);

// Placeholder pet: original cuboid creature. Each part: size, and per-pose [x,y,z] + single-axis rotation.
const pet = {
  origin: [3.5, T, 4.6],
  yaw: 0.6,
  parts: [
    { name: 'body', size: [0.44, 0.3, 0.8], breathe: 0.012,
      lie: { p: [0, 0.15, 0], rot: ['x', 0] }, sit: { p: [0, 0.36, 0.12], rot: ['x', 0.62] } },
    { name: 'head', size: [0.36, 0.3, 0.32],
      lie: { p: [0, 0.2, -0.52], rot: ['x', 0.12] }, sit: { p: [0, 0.78, -0.2], rot: ['y', 0] }, look: 0.35 },
    { name: 'ear_l', size: [0.1, 0.12, 0.06], follow: 'head', offset: [-0.11, 0.21, 0] },
    { name: 'ear_r', size: [0.1, 0.12, 0.06], follow: 'head', offset: [0.11, 0.21, 0] },
    { name: 'leg_fl', size: [0.1, 0.32, 0.1], lie: { p: [-0.13, 0.05, -0.42], rot: ['x', 1.5708] }, sit: { p: [-0.12, 0.16, -0.22], rot: ['x', 0] } },
    { name: 'leg_fr', size: [0.1, 0.32, 0.1], lie: { p: [0.13, 0.05, -0.42], rot: ['x', 1.5708] }, sit: { p: [0.12, 0.16, -0.22], rot: ['x', 0] } },
    { name: 'leg_bl', size: [0.1, 0.32, 0.1], lie: { p: [-0.2, 0.05, 0.28], rot: ['x', 1.5708] }, sit: { p: [-0.21, 0.07, 0.3], rot: ['x', 1.5708] } },
    { name: 'leg_br', size: [0.1, 0.32, 0.1], lie: { p: [0.2, 0.05, 0.28], rot: ['x', 1.5708] }, sit: { p: [0.21, 0.07, 0.3], rot: ['x', 1.5708] } },
    { name: 'tail', size: [0.08, 0.08, 0.62], lie: { p: [0.16, 0.05, 0.62], rot: ['y', -0.35] }, sit: { p: [0.28, 0.05, 0.02], rot: ['y', 0.15] } },
  ],
  // [startSec, endSec, from, to] within the loop; outside transitions the pose holds.
  schedule: [[3, 4.2, 'lie', 'sit'], [8, 9.2, 'sit', 'lie']],
};

const scene = {
  fps: 30,
  loopSeconds: 10,
  width: 3840,
  height: 2160,
  texelsPerBlock: 16,
  camera: { pos: [6.9, 3.0, 9.6], target: [3.5, 1.45, 1.2], fovY: 48 },
  palette: { ambient: '#3a2414', fog: '#2a2030', lampLight: '#ff9a3c', windowLight: '#6b6aa6', rain: '#c9b9a8', glassTint: '#40384e' },
  lamp: { pos: [7, 2.0, 1.5], intensity: 1, range: 14 },
  boxes,
  window: { glassZ: -0.5, x: [2, 6], y: [1, 4] },
  fan: { pos: [4, 5, 3.4], drop: 0.55, revsPerLoop: 3, blades: 4, blade: [1.25, T, 0.28] },
  rain: { yTop: 12, yBottom: -8, tilt: 0.18, streaks: rain },
  drops: { slide, beads },
  pet: { ...pet, origin: [4.6, T, 3.9] },
};

fs.writeFileSync(outFile, JSON.stringify(scene));
console.log(`scene: ${boxes.length} boxes, ${rain.length} rain streaks -> ${outFile}`);
