// MOCK, not a video (user 2026-10-18): a pet that really moves, in pixel art. The same blocky cat as the Treetop
// mock (src/library/cat3d.js), snapped to the farmhouse's pixel grid and 12 fps by the engine's output pass like
// every other layer. A second cat walks in from the left behind the plant and the dining chair, crosses to the
// hearth rug, sits by the fire, lies down, curls up asleep, wakes, stretches and walks back out. The art's depth
// is wrong at the rocking chair (it reads farther than the floor), so the cat never goes near it. The
// pixel-farmhouse sample is unchanged; this wraps it.
//   node src/cli.mjs preview scenes/catmock-pixel --start 0 --seconds 58
import base from '../pixel-farmhouse/scene.js';
import { cat3dLayer } from '../../src/library/cat3d.js';

// [x, y, body length px at 4K]: the painted cat (~500 px curled at y 0.80) scaled by distance below the horizon
const IN = [[-0.07, 0.64, 290], [0.05, 0.641, 288], [0.2, 0.639, 284], [0.35, 0.634, 278], [0.5, 0.628, 272], [0.62, 0.622, 266], [0.745, 0.616, 262]];
const OUT = [...IN].reverse();

export default {
  ...base,
  name: 'catmock-pixel',
  title: 'Mock: a 3D cat in the pixel farmhouse',
  async build(ctx) {
    await base.build(ctx);
    await cat3dLayer(ctx, {
      plate: 'pixel-farmhouse',
      coat: ctx.params?.coat ?? 'grey-tabby',
      ambient: 2.4,
      start: 2,
      elev: 17,                      // the round rug is drawn ~0.3 as tall as wide
      paths: { in: IN, out: OUT },
      // the fire to its right and a little behind; the candle and lamp across the room
      key: { dir: [0.75, 0.35, -0.45], color: '#ff9a4a', intensity: 2.6 },
      fill: { dir: [-0.6, 0.6, 0.35], color: '#ffc884', intensity: 0.6 },
      program: [
        { do: 'walk', path: 'in', speed: 14 },
        { do: 'turn', to: 45 },
        { do: 'stand', dur: 2, look: [[0.8, -30, 0], [2, -10, 0]] },
        { do: 'sit', dur: 7, look: [[1.5, -40, -10], [3.5, -40, -10], [5, 10, 0], [7, 0, 0]] },
        { do: 'lie', dur: 4, look: [[2, -25, 5], [4, 0, 0]] },
        { do: 'curl', dur: 12 },
        { do: 'stand', dur: 2 },
        { do: 'stretch', dur: 3 },
        { do: 'stand', dur: 1 },
        { do: 'turn', to: -90 },
        { do: 'walk', path: 'out', speed: 14 },
      ],
    });
  },
};
