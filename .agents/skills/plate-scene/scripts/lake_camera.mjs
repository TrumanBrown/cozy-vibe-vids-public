// Lake-camera helper for plate scenes (plate-scene skill). It uses the renderer's own lakeCamera / makePath /
// boatPose from src/library/boat.js, so the numbers match what boatLayer draws and what the audio profile hears.
//
// Usage (repo root):
//   node .agents/skills/plate-scene/scripts/lake_camera.mjs fit   --rows 0.62:21 0.70:33 [--focal 2700]
//   node .agents/skills/plate-scene/scripts/lake_camera.mjs pts   --horizon 0.453 --height 16 [--focal 2700] --pts 0.30,0.70 0.31,0.70
//   node .agents/skills/plate-scene/scripts/lake_camera.mjs route scenes/<scene> [--dur 130]
//
// fit    rows y (0..1, y down) with the measured width (4K px) of a 1 m block face that sits at the water level at
//        that row (shore stones, dock planks, a block-wide reed clump). Solves the camera height (m) and horizon
//        row for lakeCamera({ focalPx, horizon, height }) by least squares. Needs >= 2 rows, far apart.
// pts    screen points (x,y in 0..1) -> position on the water plane (m), distance from the camera, px per meter,
//        and the distance between consecutive points (two points one shore block apart should be ~1 m).
// route  the scene's events.boat.route: path length, per-point distance and scale, the boat's size, the fade
//        zones, and the boat's screen position, speed, haze and visibility along one trip (dir +1, far -> near).
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const { lakeCamera, makePath, boatPose } = await import(new URL('../../../../src/library/boat.js', import.meta.url).href);

const W = 3840, H = 2160, BOAT_M = 4.5;   // boat.js model: 36 voxels of 0.125 m from stern to bow
const [cmd, ...rest] = process.argv.slice(2);
const opt = {};
for (let i = 0, key = null; i < rest.length; i++) {
  const s = rest[i];
  if (s.startsWith('--')) { key = s.slice(2); opt[key] = []; } else if (key) opt[key].push(...s.split(';').filter(Boolean)); else (opt._ ??= []).push(s);
}
const num = (k, d) => (opt[k]?.length ? Number(opt[k][0]) : d);
const f1 = (v) => v.toFixed(1), f3 = (v) => v.toFixed(3);

function cameraInfo(cam, horizon) {
  const th = Math.atan((H / 2 - horizon * H) / cam.F);
  return `focal ${cam.F} px, height ${f1(cam.C[1])} m, horizon row ${f3(horizon)} (${f1(horizon * H)} px), pitch ${f1((th * 180) / Math.PI)} deg down`;
}

// Water position, distance (m) and px per meter for screen point (x, y); null above the horizon.
function onWater(cam, x, y) {
  const p = cam.toWater(x, y);
  const q = cam.project(p);
  if (!(q[2] > 0) || !Number.isFinite(q[2])) return null;
  return { p, dep: q[2], dist: Math.hypot(p[0] - cam.C[0], cam.C[1], p[2] - cam.C[2]), ppm: cam.pxPerM(q[2]) };
}

if (cmd === 'fit') {
  const F = num('focal', 2700);
  const rows = (opt.rows ?? []).flatMap((s) => s.split(',')).map((s) => s.split(':').map(Number));
  if (rows.length < 2 || rows.some((r) => r.length !== 2 || r.some((v) => !Number.isFinite(v)))) {
    console.error('fit needs --rows y:px y:px ... (at least two rows; y in 0..1, block width in 4K px)');
    process.exit(2);
  }
  // Block width at row Y (px): s = cos(pitch) * (Y - Yh) / height  ->  linear in Y.
  const n = rows.length, Ys = rows.map((r) => r[0] * H), S = rows.map((r) => r[1]);
  const my = Ys.reduce((a, b) => a + b, 0) / n, ms = S.reduce((a, b) => a + b, 0) / n;
  const a = Ys.reduce((acc, y, i) => acc + (y - my) * (S[i] - ms), 0) / Ys.reduce((acc, y) => acc + (y - my) ** 2, 0);
  const b = ms - a * my;
  if (!(a > 0)) { console.error('block widths must grow toward the bottom of the frame; check the measurements'); process.exit(1); }
  const Yh = -b / a, horizon = Yh / H;
  const height = Math.cos(Math.atan((H / 2 - Yh) / F)) / a;
  const cam = lakeCamera({ focalPx: F, horizon, height, W, H });
  console.log(`fit: horizon ${f3(horizon)}, height ${f1(height)} m  ->  camera: { focalPx: ${F}, horizon: ${f3(horizon)}, height: ${f1(height)} }`);
  console.log(cameraInfo(cam, horizon));
  for (const [y, s] of rows) {
    const w = onWater(cam, 0.5, y);
    console.log(`  row ${f3(y)}: measured ${f1(s)} px/block, model ${w ? f1(w.ppm) : '-'} px/m, ${w ? f1(w.dist) : '-'} m from the camera`);
  }
} else if (cmd === 'pts') {
  const horizon = num('horizon', 0.453), cam = lakeCamera({ focalPx: num('focal', 2700), horizon, height: num('height', 16), W, H });
  console.log(cameraInfo(cam, horizon));
  const pts = (opt.pts ?? []).map((s) => s.split(',').map(Number));
  let prev = null;
  for (const [x, y] of pts) {
    const w = onWater(cam, x, y);
    if (!w) { console.log(`  (${f3(x)}, ${f3(y)}): above the horizon, not on the water plane`); prev = null; continue; }
    const step = prev ? `  | ${f3(Math.hypot(w.p[0] - prev.p[0], w.p[2] - prev.p[2]))} m from the previous point` : '';
    console.log(`  (${f3(x)}, ${f3(y)}): water x ${f1(w.p[0])} m, z ${f1(w.p[2])} m, ${f1(w.dist)} m away, ${f1(w.ppm)} px/m${step}`);
    prev = w;
  }
} else if (cmd === 'route') {
  const sceneDir = opt._?.[0];
  if (!sceneDir) { console.error('route needs a scene folder, e.g. scenes/treetop-plate'); process.exit(2); }
  const { default: S } = await import(pathToFileURL(path.resolve(sceneDir, 'scene.js')).href);
  const route = S.events?.boat?.route;
  if (!route?.path?.length) { console.error(`${sceneDir}: no events.boat.route.path`); process.exit(1); }
  const cam = lakeCamera({ ...route.camera, W, H });
  const pth = makePath(cam, route.path);
  const fade = route.fade ?? [30, 6];
  const dur = num('dur', (S.events.boat.dur ?? [110, 150]).reduce((a, b) => a + b, 0) / 2);
  console.log(cameraInfo(cam, route.camera?.horizon ?? 0.453));
  console.log(`route: ${route.path.length} points, ${f1(pth.total)} m; fades in over the first ${fade[0]} m (far end), out over the last ${fade[1]} m (near end)`);
  let s = 0, prev = null;
  for (const [x, y] of route.path) {
    const w = onWater(cam, x, y);
    if (!w) { console.log(`  (${f3(x)}, ${f3(y)}): ABOVE THE HORIZON (move the point down or lower the horizon)`); continue; }
    if (prev) s += Math.hypot(w.p[0] - prev.p[0], w.p[2] - prev.p[2]);
    console.log(`  (${f3(x)}, ${f3(y)}): ~${f1(s)} m along, ${f1(w.dist)} m away, ${f1(w.ppm)} px/m, boat ~${Math.round(BOAT_M * w.ppm)} px long broadside`);
    prev = w;
  }
  const hz = [95, 260];   // boat.js default hull haze range (m); override with boatLayer opts.haze
  console.log(`one trip, dir +1 (far -> near), ${f1(dur)} s (mean of events.boat.dur; --dur to change):`);
  for (let k = 0; k <= 10; k++) {
    const t = (k / 10) * dur, p = boatPose(pth, { t: 0, dur, dir: 1 }, t, fade);
    const q = cam.project([p.x, 0, p.z]);
    const dist = Math.hypot(p.x - cam.C[0], cam.C[1], p.z - cam.C[2]);
    const u = Math.min(Math.max((q[2] - hz[0]) / (hz[1] - hz[0]), 0), 1);
    console.log(`  t ${f1(t).padStart(6)} s: screen (${f3(q[0] / W)}, ${f3(q[1] / H)}), ${f1(dist)} m away, ${p.speed.toFixed(2)} m/s, haze ${(u * u * (3 - 2 * u)).toFixed(2)}, visible ${p.vis.toFixed(2)}`);
  }
} else {
  console.error('usage: lake_camera.mjs fit --rows y:px ... | pts --horizon h --height m --pts x,y ... | route scenes/<scene> [--dur s]');
  process.exit(2);
}
