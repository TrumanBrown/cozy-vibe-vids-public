// The rabbit's visits for tests/test_rabbit.py: node tests/js_rabbit.mjs <out.json>
// Plans 40 visits on a cabin floor like the spruce cabin's with fixed seeds, each twice (the same seed must plan the
// same), notes every hop after the first that starts out of sight (it would come back), and follows every paw through
// every hop with rabbit3d.js's own rabbitAt: where each one is on the floor (in the hop's own frame, which doesn't move)
// while it is planted, so a paw that slides shows as a spread.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const imp = (rel) => import(pathToFileURL(path.join(root, rel)).href);
const { planRabbit, outOfSight } = await imp('src/library/timeline/rabbit.js');
const { rabbitAt, BL } = await imp('src/library/rabbit3d.js');
const { mulberry32 } = await imp('src/library/timeline/random.js');
const { floorScale } = await imp('src/library/timeline/frog.js');


const F = {
  rest: [35, 80], dur: [290, 340], horizon: 0.5, size: 540, sizeY: 0.9, focal: 3000,
  enter: [[1.1, 0.74], [-0.1, 0.8]], exit: [[1.1, 0.76], [-0.1, 0.82]],
  spots: [[0.47, 0.72], [0.56, 0.76], [0.66, 0.71], [0.76, 0.75]], spotsPer: [2, 3], acts: [3, 6], actGap: [4, 12],
  avoid: [[0.18, 0.55, 0.5, 0.67], [0.5, 0.55, 0.64, 0.66]], minY: 0.67, sit: [40, 90], fill: true,
};
const [d0, d1] = F.dur;
// a planted paw's spot on the floor in the hop's frame: the root's offset turned back by its heading, plus where the
// root has got to
const rot = (a, x, z) => [x * Math.cos(a) + z * Math.sin(a), -x * Math.sin(a) + z * Math.cos(a)];
const onFloor = (st, p) => { const [x, z] = rot(st.hop.du, p[0], p[2]); return [x, z + st.hop.s * st.hop.D]; };
const spread = (pts) => (pts.length < 2 ? 0 : Math.max(...pts.map((p) => Math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]))));
// where a paw shows on screen (px at 4K), as creature3d.js draws it: the root's image point, the paw turned by the
// heading, across at the row's scale and toward the camera foreshortened by the view angle
const onScreen = (st, p) => {
  const { s, el } = floorScale(F, st.y), ppu = s / BL;
  const wx = p[0] * Math.cos(st.h) + p[2] * Math.sin(st.h), wz = -p[0] * Math.sin(st.h) + p[2] * Math.cos(st.h);
  return [st.x * 3840 + wx * ppu, st.y * 2160 + wz * Math.sin(el) * ppu - p[1] * Math.cos(el) * ppu];
};

const visits = [];
const slide = { front: 0, hind: 0, worst: null, px: 0, worstPx: null };
for (let seed = 1; seed <= 40; seed++) {
  const durMax = d0 + ((d1 - d0) * (seed % 10)) / 9;
  const a = planRabbit(F, mulberry32(seed), durMax), b = planRabbit(F, mulberry32(seed), durMax);
  let seen = false;
  const back = [];
  for (const h of a.hops) {
    if (seen && outOfSight(F, [h[2], h[3]])) back.push(h[0]);
    if (!outOfSight(F, [h[4], h[5]])) seen = true;
  }
  const last = a.hops[a.hops.length - 1];
  const gone = outOfSight(F, [last[4], last[5]]);
  // every paw while it is planted: the front ones before they lift and after they land, the hind ones before the heels
  // rise and after they land
  const ev = { ...a, seed };
  for (const h of a.hops) {
    const win = { front: [[0, 0.11], [0.59, 1]], hind: [[0, 0.13], [0.81, 1]] };
    for (const kind of ['front', 'hind']) {
      for (const [u0, u1] of win[kind]) {
        for (let side = 0; side < 2; side++) {
          const pts = [], scr = [];
          for (let k = 0; k <= 12; k++) {
            const st = rabbitAt(ev, h[0] + (u0 + ((u1 - u0) * k) / 12) * h[1] - 1e-6 * (k === 12));
            if (st?.hop) { pts.push(onFloor(st, st.paws[kind][side])); scr.push(onScreen(st, st.paws[kind][side])); }
          }
          const sp = spread(pts), spx = spread(scr);
          // on screen, only where it shows (a paw out of the frame can't be seen sliding)
          if (scr.length && scr[0][0] > 0 && scr[0][0] < 3840 && scr[0][1] < 2160 && spx > slide.px) { slide.px = spx; slide.worstPx = { seed, hop: h, kind, side, u0, u1 }; }
          if (sp > slide[kind]) { slide[kind] = sp; if (sp >= Math.max(slide.front, slide.hind)) slide.worst = { seed, hop: h, kind, side, u0, u1 }; }
        }
      }
    }
  }
  visits.push({ seed, durMax, plan: a, same: JSON.stringify(a) === JSON.stringify(b), back, gone });
}
fs.writeFileSync(process.argv[2], JSON.stringify({ spec: F, visits, slide }, null, 1));
