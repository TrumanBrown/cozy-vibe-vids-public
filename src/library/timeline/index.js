// Seeded event timeline (docs/GOALS.md: "All randomness is seeded and written to an event timeline
// (JSON) that drives both video and audio"). Pure function of (scene events spec, seed, duration): the
// frame renderer reads it for lightning light, tools/audio.py for thunder, and `node src/cli.mjs
// timeline` writes it to out/<scene>/timeline.json as a render deliverable.
//
// The modules, by job: random.js (seeded streams, hashing), lightning.js (storm strikes and their light),
// weather.js (the slow weather track), lights.js (night lights, windows, lantern and region dips), wind.js (gust
// flurries and the steady wind), leaves.js (leaf and petal schedules), pet.js (pet micro-motions), spotlight.js
// (one-at-a-time events), ambient.js (frequent small events) and build.js (buildTimeline, the seamless loop).
// The types it gives its events and the pet's motions are listed in ../types.json (tests/test_types.py).

export { buildTimeline } from './build.js';
export { SPEED_OF_SOUND, strikeEnvelope, flashAt } from './lightning.js';
export { weatherTrack, trackAt } from './weather.js';
export { regionDip, lightLevel, lanternDips, lanternDip, lightLevels, windowDip } from './lights.js';
export { flurryInt, flurryWind, flurryDrift, flurryUniform, flurryEnv, windAt, windDrift } from './wind.js';
export { petState } from './pet.js';
