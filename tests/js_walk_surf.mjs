// Probe for tests/test_walk.py and tests/test_surf.py: the walker's stops and gait (critters.js, timeline/ambient.js) and
// the surf's spray plan (surf.js), printed as JSON. node tests/js_walk_surf.mjs
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), '..');
const lib = (f) => import(pathToFileURL(path.join(root, 'src', 'library', f)).href);
const S = await lib('surf.js');
const C = await lib('critters.js');
const A = await lib('timeline/ambient.js');

const spot = { x: 2000, y: 1000, w: 200, h: 120, min: 0.5 };
const wave = { t: 10, amp: 0.9, peel: 1 };
const walk = { stops: [4, 7], stop: [1.2, 4.5] };
const ev = { t: 0, dur: 40, from: 0, to: 1, stops: A.walkStops(123, 40, walk) };
const taus = Array.from({ length: 401 }, (_, i) => i * 0.1);
const edges = { step: 8, top: Array.from({ length: 480 }, () => 960), bot: Array.from({ length: 480 }, (_, i) => 1060 + i * 0.1), x0: 1400, x1: 3839 };
const G = C.gaitFor('hermitcrab', true);
const M = await lib('moth.js');
const mothEv = (seed) => ({ t: 0, dur: 60, R0: 2.0, w: 2.2, th0: 1.1, ph: [0.3, 1.2, 2.2, 0.7, 4.1, 5.0], hz: 30, lands: [], ...A.mothBehind(seed) });
const mothTaus = Array.from({ length: 1201 }, (_, i) => i * 0.025);
const moths = [11, 22, 33, 44, 55].map((s) => {
  const ev = mothEv(s);
  return { ev, start: M.mothAt(ev, 0).p, end: M.mothAt(ev, ev.dur).p, entry: mothTaus.map((t) => M.mothAt(ev, t).p), exit: mothTaus.map((t) => M.mothAt(ev, ev.dur - t).p) };
});
console.log(JSON.stringify({
  plume: {
    before: S.plume(spot, wave, 0, 0).length,
    after: S.plume(spot, wave, S.LIFE + 0.5, 0).length,
    small: S.plume(spot, { ...wave, amp: 0.3 }, 0.5, 0).length,
    rise: S.plume(spot, wave, 0.5, 0),
    again: S.plume(spot, wave, 0.5, 0),
    late: S.plume(spot, wave, 3.5, 0),
  },
  spot,
  arrival: [S.arrival({ t: 10, peel: 1 }, 0.5, 0.25, { travel: 2.6, peel: 1.6, lead: 1 }), S.arrival({ t: 10, peel: -1 }, 0.5, 0.25, { travel: 2.6, peel: 1.6, lead: 1 })],
  shore: [S.shoreAt(edges, 2000, 1000), S.shoreAt(edges, 100, 2000)],
  edges: { top: edges.top[250], bot: edges.bot[250] },
  stops: [ev.stops, A.walkStops(123, 40, walk), A.walkStops(5, 30, { stops: [3, 3], stop: [10, 10] }), A.walkStops(77, 36, walk)],
  ev,
  progress: taus.map((t) => C.critterProgress(ev, t)),
  taus,
  gaits: { crab: G, snail: C.gaitFor('snail', true), beetle: C.gaitFor('beetle', true), mouse: C.gaitFor('woodmouse', true), off: C.gaitFor('hermitcrab', false), over: C.gaitFor('hermitcrab', { bob: 0.08 }) },
  pose: Array.from({ length: 60 }, (_, i) => C.walkPose(G, 56, i * 0.7, 1)),
  still: C.walkPose(G, 56, 13.3, 0),
  moths,
  mothAgain: A.mothBehind(11),
}));
