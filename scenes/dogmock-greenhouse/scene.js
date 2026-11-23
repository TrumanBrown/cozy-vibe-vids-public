// MOCK, not the video (user 2026-10-21, round 7): instead of sprite poses painted one by one (each came out a somewhat
// different dog), a free rigged 3D dog (Quaternius' Shiba Inu, CC0) replaces the painted one: the plate shows the empty
// bed and this one model is the dog in every frame. A short program for his look at it moving (he asked for a short
// clip before any hour). The model has no sit or lie clip.
//   node src/cli.mjs preview scenes/dogmock-greenhouse --start 360 --seconds 24 --audio off
import base from '../pixel-greenhouse-rain/scene.js';
import { dog3dLayer } from '../../src/library/dog3d.js';

const W = 3840, H = 2160;
const MAT = [820 / W, 1758 / H];
// in front of the aisle, left of its middle: it arrives facing up the aisle (about 155 deg) with its head over the aisle
// floor, not over a bed, and far enough out that the arc it turns round on clears the left bed
const STOP = [1840 / W, 1620 / H];

export default {
  ...base,
  name: 'dogmock-greenhouse',
  title: 'Mock: a 3D dog in the pixel greenhouse',
  async build(ctx) {
    await base.build(ctx);
    if (ctx.params?.layers === 'off') return;
    await dog3dLayer(ctx, {
      plate: 'pixel-greenhouse-rain',
      model: '/assets/models/quaternius/ShibaInu.glb',
      empty: ctx.params?.empty === 'off' ? null : { url: '/assets/keyart/pixel-greenhouse-rain/petsprite/patch_empty.png', x: 497, y: 1476, w: 663, h: 298 },
      // the painted dog's own colors (k-means of the painted dog awake, pet_sprite.py dog_palette), darkest first. The
      // default: six fill tones a step apart, as a pixel artist would shade it, and the darkest for the eyes and nose;
      // pal=full: all fifteen (a speckled, rendered look)
      palette: ctx.params?.palette === 'off' ? [] : ctx.params?.pal !== 'full'
        ? ['#1a1113', '#472317', '#733518', '#9b4d1f', '#c06322', '#dc8a3c', '#e8a458']
        : ['#1a1113', '#2a1717', '#472317', '#602e18', '#733518', '#843c18', '#8f4018',
          '#994518', '#9b4d1f', '#a6501d', '#b4581f', '#c06322', '#ce732a', '#dc8a3c', '#e8a458'],
      edge: '#2a1717',
      cell: 8.495,
      // a golden coat all over (the Shiba's white muzzle, chest and legs a lighter gold, as the painted dog's chest is),
      // the ears hanging, the head a little bigger: a retriever puppy more than a Shiba
      colors: { Main: ctx.params?.main ?? '#d9782f', Main_Light: ctx.params?.light ?? '#eba04f', Eyes_White: '#1a1113', Eyes_Black: '#1a1113' },
      aim: [
        ...['L', 'R'].map((s) => ({ chain: [`Ear1.${s}`, `Ear2.${s}`, `Ear3.${s}`, `Ear4.${s}`, `Ear4.${s}_end`],
          dir: [[0.15, 0.95, 0.15], [0.75, 0.6, 0.1], [0.95, 0.25, 0.05], [0.98, 0.15, 0.0]] })),
        // the tail carried a little below level and no longer than to the hocks: hanging to the floor it read as a fifth
        // leg from behind
        { chain: ['Tail1', 'Tail2', 'Tail3', 'Tail3_end'], dir: [[0.25, 0, -0.97], [0.55, 0, -0.83], [0.8, 0, -0.6]] },
      ],
      bones: {
        Head: (() => { const k = String(ctx.params?.headk ?? '1.32').split(':').map(Number); return k.length === 3 ? k : k[0]; })(),
        'Ear1.L': Number(ctx.params?.eark ?? 1.6), 'Ear1.R': Number(ctx.params?.eark ?? 1.6),
        // a puppy's thicker legs (each bone's own y runs along it)
        ...Object.fromEntries(['FrontUpperLeg.L', 'FrontUpperLeg.R', 'BackUpperLeg.L', 'BackUpperLeg.R'].map((b) => [b, [1.4, 1, 1.4]])),
        // the Shiba's curl is modeled into the mesh past the last tail bone: aiming the bones down leaves a hook, so the
        // last bone (the curl) is folded away and the one before made longer and fuller
        Tail3: Number(ctx.params?.tail3 ?? 0.05), Tail2: [1.4, Number(ctx.params?.tail2 ?? 1.25), 1.4],
      },
      // fur in clusters of two or three cells, as painted (finer, it speckled like dither)
      fur: ctx.params?.fur === 'off' ? null : { cells: Number(ctx.params?.furcells ?? 30), amp: Number(ctx.params?.furamp ?? 0.12) },
      // a strong key and less ambient: the back and head take the light tones, the far side a flat dark brown (weaker
      // ambient left black blotches there)
      ambient: Number(ctx.params?.amb ?? 2.4),
      // the lantern on the bench up and to the left, the dawn through the glass behind
      key: { dir: [-0.55, 0.75, 0.35], color: '#ffa64d', intensity: Number(ctx.params?.keyi ?? 5.5) },
      fill: { dir: [0.5, 0.6, -0.6], color: '#9fb8ff', intensity: 0.45 },
      occlude: false,
      // inner lines where a nearer part overlaps (a darker shade of the coat, as pixel art draws them)
      inner: ctx.params?.inner === 'off' ? false : { color: ctx.params?.inner ?? '#472317', depth: Number(ctx.params?.innerd ?? 0.25) },
      // its head-top 470 px with its feet on the mat; the same floor as the sprite mock (L105: the door's own scale)
      floor: { row: 1758, height: 470, horizon: 131.6 },
      // after the opening line (gone by 11 s): it stands on the mat, walks across to the mouth of the aisle and stops
      // looking up it toward the door, looks around, turns round on a tight curve, walks back onto the mat and stands
      // with its head low (the model has no lie or sit clip; a turn to face right again passes through a front view
      // that reads poorly)
      start: 12,
      program: [
        { do: 'idle', clip: 'Idle', at: MAT, heading: 70, dur: 3 },
        { do: 'walk', path: [[1250 / W, 1752 / H], [1560 / W, 1745 / H], [1734 / W, 1717 / H], STOP] },
        { do: 'idle', clip: 'Idle_2', dur: 3.5 },
        { do: 'walk', path: [[1350 / W, 1745 / H], [1100 / W, 1760 / H], MAT] },
        { do: 'idle', clip: 'Idle_2_HeadLow', dur: 4 },
      ],
    });
  },
};
