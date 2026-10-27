// MOCK, not a video (user 2026-10-18): what a pet that really moves could look like. An original blocky cat
// rendered in code (src/library/cat3d.js) walks onto the Treetop porch's rug, looks around, sits, lies down,
// curls up asleep, wakes, stretches and walks off. The published Treetop scene is unchanged; this wraps it.
//   node src/cli.mjs preview scenes/catmock-treetop --start 0 --seconds 50
import base from '../treetop-plate/scene.js';
import { cat3dLayer } from '../../src/library/cat3d.js';

const IN = [[1.07, 0.772, 470], [0.93, 0.776, 480], [0.82, 0.785, 495], [0.72, 0.8, 520]];

export default {
  ...base,
  name: 'catmock-treetop',
  title: 'Mock: a 3D cat on the Treetop porch',
  async build(ctx) {
    await base.build(ctx);
    await cat3dLayer(ctx, {
      plate: 'treetop_rainy',
      coat: ctx.params?.coat ?? 'grey-tabby',
      start: 2,
      elev: 15,
      paths: { in: IN, out: [...IN].reverse() },
      // lanterns on the railing behind it (warm, from the back left) and the shelf lamp (right)
      key: { dir: [-0.45, 0.75, -0.35], color: '#ffae5e', intensity: 2.4 },
      fill: { dir: [0.7, 0.45, 0.2], color: '#ffc27a', intensity: 0.9 },
      program: [
        { do: 'walk', path: 'in' },
        { do: 'turn', to: -40 },
        { do: 'stand', dur: 2.5, look: [[0.8, -25, 0], [1.8, 15, -8], [2.5, 0, 0]] },
        { do: 'sit', dur: 8, look: [[2, 30, -12], [4.5, 30, -12], [6, -15, 0], [8, 0, 0]] },
        { do: 'lie', dur: 5, look: [[2, -20, 5], [5, 0, 0]] },
        { do: 'curl', dur: 12 },
        { do: 'stand', dur: 2.2 },
        { do: 'stretch', dur: 3 },
        { do: 'stand', dur: 1 },
        { do: 'turn', to: 90 },
        { do: 'walk', path: 'out' },
      ],
    });
  },
};
