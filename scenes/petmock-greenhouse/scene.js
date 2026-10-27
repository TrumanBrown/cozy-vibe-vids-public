// MOCK, not the video (user 2026-10-21, rounds 4 to 6 the same day): the pixel greenhouse's dog animated entirely, as
// pixel-art sprites painted into the picture (tools/pet_sprite.py, src/library/petsprite.js). One hour, then it repeats:
// asleep, it opens its eyes, lifts its head, pushes itself up, sits, stands (each pose painted from the one before it,
// the painted head carried up, so it stays the same dog: round 6), walks along the front and up the aisle to the back
// door and sits there looking out at the rain, breathing, wagging now and then; after 18 minutes it stands, turns,
// walks back, turns at its mat and lies down the way it got up. 70% of the hour on the bed, 30% at the door (one trip
// an hour, bed to door and back, then the hour loops). Everything else is the sample.
//   node src/cli.mjs preview scenes/petmock-greenhouse --start 510 --seconds 25 --audio off
import base from '../pixel-greenhouse-rain/scene.js';
import { petSpriteLayer } from '../../src/library/petsprite.js';

// the floor between the mat and the aisle, the aisle's mouth and its middle (image coords of the feet)
const FRONT = [[0.33, 0.795], [0.43, 0.765]];
const MOUTH = [0.5052, 0.7222];
const MID = [0.497, 0.62];
const OUT = ['drawn:stand', ...FRONT, MOUTH];
const AISLE = [MOUTH, MID, 'drawn:sit_back'];
const BACK = ['drawn:sit_back', MID, MOUTH];
const HOME = [MOUTH, ...[...FRONT].reverse(), 'drawn:stand'];
const WALK = { speed: 0.8, fps: 6 };   // a big puppy strolling
const CYCLE = 3600, AT_DOOR = 0.3 * CYCLE;

export default {
  ...base,
  name: 'petmock-greenhouse',
  title: 'Mock: the greenhouse dog as pixel sprites',
  async build(ctx) {
    await base.build(ctx);
    if (ctx.params?.layers === 'off') return;
    await petSpriteLayer(ctx, {
      plate: 'pixel-greenhouse-rain',
      scene: 'pixel-greenhouse-rain',
      start: 0,
      cycle: CYCLE,
      // its head-top height standing: 500 px with its feet on the mat, 310 px at the door (L105: it looked too small at the door;
      // the door is ~730 px for 2 m)
      height0: [500, 1750 / 2160],
      height1: [310, 0.5255],
      dogM: 0.85,
      // the image model painted the dog sitting at the door 238 px tall; at that row the size above makes it ~315
      k: { sit_back: 1.32, wag_back: 1.32 },
      lightRef: [0.2151 * 3840, 0.865 * 2160],
      // up the aisle it takes the look the dog sitting at the door was painted with (backlit by the door)
      shade: { ref: 'back', there: ['sit_back', 'wag_back'], from: MOUTH },
      program: [
        { do: 'sleep', dur: 20 },
        { do: 'patch', name: 'drowsy', dur: 2.2 },
        { do: 'patch', name: 'half', dur: 0.8 },
        { do: 'awake', dur: 3.5 },
        { do: 'pose', sheet: 'rise', at: 'drawn', dur: 0.35 },
        { do: 'pose', sheet: 'sit', at: 'drawn', dur: 0.8 },
        { do: 'pose', sheet: 'stand', at: 'drawn', dur: 0.6 },
        { do: 'walk', sheet: 'walk_side', path: OUT, ...WALK },
        { do: 'walk', sheet: 'walk_back', path: AISLE, ...WALK },
        // at the door: stops (both hind paws down), sits looking out, breathing, wagging now and then
        { do: 'pose', sheet: 'walk_back', frames: [1], at: 'drawn:sit_back', dur: 0.4 },
        { do: 'idle', sheet: 'sit_back', frame: 0, at: 'drawn', dur: AT_DOOR,
          wag: { sheet: 'wag_back', frames: [1, 2, 1, 0], fps: 6, cycles: 3, every: [60, 120], seed: 11 },
          breathe: { period: 3.4, share: 0.45, split: 0.45 } },
        // stands, turns to face the room, walks back
        { do: 'pose', sheet: 'walk_back', frames: [1], at: 'drawn:sit_back', dur: 0.4 },
        { do: 'pose', sheet: 'walk_front', frames: [1], at: 'drawn:sit_back', dur: 0.35 },
        { do: 'walk', sheet: 'walk_front', path: BACK, ...WALK },
        { do: 'walk', sheet: 'walk_side', path: HOME, ...WALK },
        // turns at the mat through the front view to face the way the painted dog lies, and lies down
        { do: 'pose', sheet: 'walk_front', frames: [1], at: 'drawn:stand', dur: 0.35 },
        { do: 'pose', sheet: 'stand', at: 'drawn', dur: 0.5 },
        { do: 'pose', sheet: 'sit', at: 'drawn', dur: 0.8 },
        { do: 'pose', sheet: 'rise', at: 'drawn', dur: 0.35 },
        { do: 'awake', dur: 3 },
        { do: 'patch', name: 'half', dur: 0.9 },
        { do: 'patch', name: 'drowsy', dur: 2.5 },
      ],
    });
  },
};
