// The ambient event streams (ambientEvents): fish, gusts, distant lightning, region dips, cars, embers, stars, birds,
// critters, ants, perched birds, boats as traffic, moths and pet acts. One function each, run in the order of STREAMS,
// which is the order their events have in the timeline.

import { mulberry32, hashStr, r3, calibrated } from './random.js';
import { SPEED_OF_SOUND } from './lightning.js';
import { lanternDips } from './lights.js';

// Ambient events: frequent, small, allowed to overlap the spotlight ones (but not cluttering them).
//   fish      a fish rising: splash + expanding rings at a point on open water (screen zones [x0, y0, x1, y1, weight])
//   flurry    a gust: wind bump (rain, runoff, leaves, vines, audio), a burst of leaves shaken loose
//   farflash  distant lightning in the cloud bank behind the mountains, a soft low rumble later
// Each stream has Gamma(2) spacing above a minimum gap and exactly the configured long-run rate.
export function ambientEvents(spec, seed, duration, events, regions = []) {
  const out = [];
  const ctx = { spec, seed, duration, events, regions, out, stream: streamInto(out, seed, duration) };
  for (const add of STREAMS) add(ctx);
  return out;
}

// Gamma(2) spacing (steadier than Poisson) above a minimum gap, calibrated to the configured rate.
// S.first: the first event comes within this many seconds of startAfter (strong openings).
// S.intro: [until s, x]: x times as many events before `until` (the busy opening), on top of the rate.
function streamInto(out, seed, duration) {
  return (key, S, make) => {
    const mean = 3600 / S.perHour, gap = Math.min(S.minGap ?? 0, 0.8 * mean);
    const t0 = S.startAfter ?? 120, end = duration - (S.endBefore ?? 30);
    const [iu, ix] = S.intro ?? [0, 1];
    const gen = (k) => {
      const r = mulberry32((Math.imul(seed, 1103515245) ^ hashStr(key)) >>> 0);
      const step = () => gap + (mean - gap) * k * 0.5 * (-Math.log(1 - r()) - Math.log(1 - r()));
      const res = [];
      // (the default keeps the original draw order: existing timelines stay identical)
      let t = S.first != null ? (() => { const u = r(); return t0 + u * Math.min(S.first, step()); })() : t0 + r() * step();
      for (; t < end; ) {
        const e = make(r, t);
        if (e) res.push(e);
        const s = step();
        t += t < iu ? Math.max(gap, s / ix) : s;
      }
      return res;
    };
    const extra = iu > t0 ? (S.perHour * (Math.min(iu, end) - t0) / 3600) * (ix - 1) : 0;
    out.push(...calibrated(gen, Math.round((S.perHour * (end - t0)) / 3600 + extra)));
  };
}

function fish({ spec, events, stream }) {
  const F = spec?.fish;
  if (!F?.perHour || !F.zones?.length) return;
  const boats = events.filter((e) => e.type === 'boat');
  const wsum = F.zones.reduce((s, z) => s + (z[4] ?? 1), 0);
  stream('fish', F, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    let u = r() * wsum, z = F.zones[0];
    for (const zz of F.zones) { u -= zz[4] ?? 1; if (u <= 0) { z = zz; break; } }
    const e = {
      type: 'fish', t: r3(t), dur: r3(U(6, 8)), x: r3(U(z[0], z[2])), y: r3(U(z[1], z[3])), size: r3(U(0.8, 1.4)),
      jump: r() < (F.jump ?? 0.35) ? 1 : 0, seed: Math.floor(r() * 2147483647),
    };
    // Not while the boat is out (its wake owns the water then).
    return boats.some((b) => e.t > b.t - 30 && e.t < b.t + b.dur + 30) ? null : e;
  });
}

function flurry({ spec, stream }) {
  const Fl = spec?.flurry;
  if (!Fl?.perHour) return;
  const prevail = Math.sign(Fl.prevailing ?? 1) || 1;
  stream('flurry', Fl, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const [d0, d1] = Fl.dur ?? [5, 8], [a0, a1] = Fl.amp ?? [1, 2], [n0, n1] = Fl.leaves ?? [4, 9];
    return {
      type: 'flurry', t: r3(t), dur: r3(U(d0, d1)), amp: r3(U(a0, a1) * (r() < 0.8 ? prevail : -prevail)),
      leaves: n0 + Math.floor(r() * (n1 - n0 + 1)), seed: Math.floor(r() * 2147483647),
    };
  });
}

// Distant lightning: a storm far off behind the mountains lights the cloud bank from inside, faintly and
// much more often than the storm strikes overhead; a soft low rumble follows 8-20 s later. 1-3 pulses
// >= 0.25 s apart (WCAG: <= 3 per second; far below the flash-area threshold anyway). Kept clear of the
// storm strikes (flash and thunder) so two never pile up. Not a storm: no rain swell, no cat reaction.
function farflash({ spec, events, stream }) {
  const FF = spec?.farflash;
  if (!FF?.perHour) return;
  const strikes = events.filter((e) => e.type === 'lightning');
  const clear = FF.clear ?? 20;
  stream('farflash', FF, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const [d0, d1] = FF.delay ?? [8, 20], [p0, p1] = FF.power ?? [0.2, 0.45];
    const [x0, x1] = FF.x ?? [0.12, 0.8], [y0, y1] = FF.y ?? [0.14, 0.28];
    const delay = U(d0, d1);
    const strokes = [[0, 1]];
    if (r() < 0.55) strokes.push([r3(U(0.25, 0.4)), r3(U(0.4, 0.8))]);
    if (strokes.length > 1 && r() < 0.3) strokes.push([r3(strokes[1][0] + U(0.3, 0.45)), r3(U(0.25, 0.5))]);
    const e = {
      type: 'farflash', t: r3(t), x: r3(U(x0, x1)), y: r3(U(y0, y1)), power: r3(U(p0, p1)), strokes,
      thunder: { t: r3(t + delay), delay: r3(delay), distance_m: Math.round(delay * SPEED_OF_SOUND), gain: r3(U(0, 1)), seed: Math.floor(r() * 2147483647) },
    };
    return strikes.some((s) => Math.abs(s.t - e.t) < clear || Math.abs(s.thunder.t - e.thunder.t) < clear) ? null : e;
  });
}

// Region light events. A region name list defaults to every region of the matching kind (plate.json).
const regionsOf = (S, kinds, regions) => (S.regions?.length ? S.regions : regions.filter((g) => kinds.includes(g.kind)).map((g) => g.name));

// Neon sign buzz: 2-4 quick soft dips within ~1 s, >= 0.34 s apart (WCAG: <= 3 per second; small area).
function neon({ spec, regions, stream }) {
  const N = spec?.neon;
  const neonRegions = N ? regionsOf(N, ['neon'], regions) : [];
  if (!N?.perHour || !neonRegions.length) return;
  stream('neon', N, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const n = 2 + Math.floor(r() * 3), dips = [];
    let c = U(0.05, 0.15);
    for (let i = 0; i < n; i++) { dips.push([r3(c), r3(U(0.05, 0.09)), r3(U(0.35, N.depth ?? 0.75))]); c += U(0.34, 0.5); }
    return { type: 'neon', t: r3(t), dur: r3(c + 0.1), region: neonRegions[Math.floor(r() * neonRegions.length)], dips, seed: Math.floor(r() * 2147483647) };
  });
}

// Candle gutter: a draft makes a flame dip 2-3 times over a few seconds (like the lantern, smaller).
function gutter({ spec, regions, stream }) {
  const Gt = spec?.gutter;
  const gutRegions = Gt ? regionsOf(Gt, ['candle', 'lamp', 'lantern', 'flame'], regions) : [];
  if (!Gt?.perHour || !gutRegions.length) return;
  stream('gutter', Gt, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const e = { type: 'gutter', t: r3(t), dur: r3(U(2.0, 3.5)), region: gutRegions[Math.floor(r() * gutRegions.length)], seed: Math.floor(r() * 2147483647) };
    e.dips = lanternDips(e).map(([c, w, d]) => [c, w, r3(d * (Gt.depth ?? 0.6))]);
    return e;
  });
}

// A car passes on the street outside (traffic.js): headlights coming, tail lights going; wet-road
// reflections; a soft tire hiss in the audio.
function car({ spec, stream }) {
  const C = spec?.car;
  if (!C?.perHour) return;
  stream('car', C, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const [d0, d1] = C.dur ?? [4, 7];
    const dir = r() < (C.rightward ?? 0.5) ? 1 : -1;
    return { type: 'car', t: r3(t), dur: r3(U(d0, d1)), dir, lane: r3(r()), lights: r() < (C.headlights ?? 0.5) ? 'head' : 'tail', size: r3(U(0.85, 1.15)), seed: Math.floor(r() * 2147483647) };
  });
}

// A log settles in the fire: a burst of sparks (fire.js) and a crackle-pop (audio).
function ember({ spec, stream }) {
  const Em = spec?.ember;
  if (!Em?.perHour) return;
  stream('ember', Em, (r, t) => ({ type: 'ember', t: r3(t), dur: 2.5, n: 6 + Math.floor(r() * 10), power: r3(0.6 + 0.4 * r()), seed: Math.floor(r() * 2147483647) }));
}

// A shooting star crosses the sky region: short, soft, slanting down.
function star({ spec, stream }) {
  const St = spec?.star;
  if (!St?.perHour) return;
  const [bx0, by0, bx1, by1] = St.box ?? [0.1, 0.05, 0.9, 0.35];
  stream('star', St, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const x0 = U(bx0, bx1), y0 = U(by0, by0 + 0.5 * (by1 - by0)), dir = r() < 0.5 ? 1 : -1;
    const len = U(0.08, 0.18);
    return { type: 'star', t: r3(t), dur: r3(U(0.6, 1.1)), x0: r3(x0), y0: r3(y0), x1: r3(x0 + dir * len), y1: r3(Math.min(by1, y0 + len * U(0.25, 0.5))), power: r3(U(0.5, 1)) };
  });
}

// Small birds crossing the open sky (birds.js): a flock of 1-7 with loose spacing, each flapping at its own
// rate. band: [x0, y0, x1, y1] of the sky they cross (image coords); size: lead bird's wingspan px at 4K.
function birds({ spec, stream }) {
  const Bd = spec?.birds;
  if (!Bd?.perHour) return;
  stream('birds', Bd, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const [x0, y0, x1, y1] = Bd.band ?? [0.1, 0.05, 0.9, 0.35];
    const [c0, c1] = Bd.count ?? [1, 6];
    const n = c0 + Math.floor(r() * (c1 - c0 + 1));
    const span = U(...(Bd.size ?? [14, 30]));
    const speed = span * U(...(Bd.speed ?? [7, 11]));
    const members = [];
    for (let i = 0; i < n; i++) {
      members.push({
        dx: r3(i === 0 ? 0 : U(0.7, 2.4) * span * i), dy: r3(U(-1.3, 1.3) * span * Math.min(i, 2)), span: r3(span * U(0.85, 1.12)),
        hz: r3(U(...(Bd.flap ?? [3.2, 5.0]))), phase: r3(r()), glideT: r3(U(2.2, 4.2)), wave: r3(U(0.1, 0.3) * span), waveT: r3(U(1.4, 2.6)),
      });
    }
    const margin = 0.03;
    // cross: [x0, x1] the whole flight (image x; default the band +- 3%): flocks that cross the whole frame enter
    // and leave out of sight (behind the buildings or the frame edge), never fading in or out in open sky
    const [cx0, cx1] = Bd.cross ?? [x0 - margin, x1 + margin];
    const wpx = (cx1 - cx0) * 3840 + Math.max(...members.map((m) => m.dx));
    return {
      type: 'birds', t: r3(t), dur: r3(wpx / speed), dir: r() < 0.5 ? 1 : -1, x0: r3(cx0), x1: r3(cx1),
      y: r3(U(y0 + 0.15 * (y1 - y0), y1 - 0.15 * (y1 - y0))), climb: r3(U(-0.025, 0.025)), span: r3(span), speed: r3(speed), members,
      seed: Math.floor(r() * 2147483647),
    };
  });
}

// A small creature crawling along a surface (critters.js; the path is the layer's): a snail on a wet step, a
// ladybug on a sill. It covers part of the path over minutes, pausing now and then; one at a time with long gaps.
// critter: one spec or a list (several creatures, each with its own path layer: the critter layer's `track` is its
// index here; the first keeps the stream key 'critter', so adding more leaves the first one's events unchanged).
function critters({ spec, stream }) {
  const Crs = Array.isArray(spec?.critter) ? spec.critter : spec?.critter ? [spec.critter] : [];
  Crs.forEach((Cr, ci) => {
    if (!Cr?.perHour) return;
    const [d0, d1] = Cr.dur ?? [240, 420];
    stream(ci ? `critter${ci}` : 'critter', { minGap: d1 + 120, ...Cr }, (r, t) => {
      const U = (a, b) => a + (b - a) * r();
      const fwd = r() < (Cr.forward ?? 0.5);
      // the whole path: it comes out from behind one end and goes out of sight at the other
      return {
        type: 'critter', t: r3(t), dur: r3(U(d0, d1)), from: fwd ? 0 : 1, to: fwd ? 1 : 0, pauses: [r3(U(0.15, 0.35)), r3(U(0.55, 0.8))],
        pauseLen: r3(U(0.04, 0.1)), seed: Math.floor(r() * 2147483647), ...(ci ? { track: ci } : {}),
      };
    });
  });
}

// An ant walking across a table or counter (ant.js; the paths are the layer's): it wanders along one of the
// paths at walking speed with short stops to feel about with its antennae. One event at a time; `file` (0..1) is
// the share of events where 2-3 ants come along the same trail one after another (`n`; ant.js keeps them apart).
function ants({ spec, stream }) {
  const An = spec?.ant;
  if (!An?.perHour) return;
  const [d0, d1] = An.dur ?? [14, 26];
  stream('ant', { minGap: d1 + 20 + (An.file ? 20 : 0), ...An }, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const stops = [];
    const ns = Math.floor(U(1, 3.999));
    for (let i = 0; i < ns; i++) stops.push([r3(U(0.12, 0.88)), r3(U(0.6, 2.2))]);
    stops.sort((a, b) => a[0] - b[0]);
    const e = {
      type: 'ant', t: r3(t), dur: r3(U(d0, d1)), path: Math.floor(r() * (An.paths ?? 1)), fwd: r() < 0.5 ? 1 : 0,
      stops, seed: Math.floor(r() * 2147483647),
    };
    // (drawn last: without `file` the draws, and so existing timelines, are unchanged)
    if (An.file) e.n = r() < An.file ? (r() < 0.4 ? 3 : 2) : 1;
    return e;
  });
}

// Birds sitting on a power line or a pole's crossarm (perch.js; the perches and their slots are the layer's): a
// group of 1-4 lands one by one, each stays minutes; some groups leave together. A near thunderclap flushes every
// bird sitting at that moment, and none lands in the `calm` s (25) after one. atStart: birds already sitting at t = 0.
function perches(ctx) {
  const Pc = ctx.spec?.perch;
  if (!Pc?.perHour || !Pc.slots?.length) return;
  perchGroups(ctx, Pc);
  if (Pc.atStart) perchAtStart(ctx, Pc);
  // Free slots in landing order (busy until the bird before has flown off), the thunder flush.
  const claps = ctx.events.filter((e) => e.type === 'lightning').map((e) => e.thunder.t).sort((a, b) => a - b);
  perchComeBack(ctx, Pc, claps);
  perchSlots(ctx, Pc, claps);
}

// One bird of a group (r: the stream's random numbers): when it lands and leaves, how it flies in and out.
function perchMember(r, land, stay) {
  const U = (a, b) => a + (b - a) * r();
  const dirIn = r() < 0.5 ? 1 : -1, dirOut = r() < 0.5 ? 1 : -1;
  const inT = U(2.6, 4.0);
  return {
    slot: r(), face: r3(r() < 0.45 ? U(-0.35, 0.35) : (r() < 0.5 ? -1 : 1) * U(0.6, 1)),
    land: r3(land), inT: r3(inT), leave: r3(land + inT + stay),
    inDx: r3(-dirIn * U(700, 1200)), inDy: r3(-U(60, 200)), outT: r3(U(2.8, 4.2)), outDx: r3(dirOut * U(800, 1400)), outDy: r3(-U(120, 380)),
    hz: r3(U(4.2, 5.8)), size: r3(U(0.9, 1.1)), seed: Math.floor(r() * 2147483647),
  };
}

function perchGroups({ stream }, Pc) {
  const nPerch = Pc.slots.length;
  stream('perch', { minGap: 20, ...Pc }, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const [g0, g1] = Pc.group ?? [1, 4];
    const n = g0 + Math.floor(r() * (g1 - g0 + 1));
    const [s0, s1] = Pc.stay ?? [60, 300];
    const perch = Math.floor(r() * nPerch);
    const together = r() < (Pc.together ?? 0.35), all = U(s0, s1);
    const members = [];
    let land = 0;
    for (let i = 0; i < n; i++) {
      members.push(perchMember(r, land, together ? Math.max(15, all - land + U(-0.3, 0.3)) : U(s0, s1)));
      land += U(2, 25);
    }
    return { type: 'perch', t: r3(t), perch, members };
  });
}

// atStart: birds already sitting at t = 0, one per perch in turn.
function perchAtStart({ seed, out }, Pc) {
  const nPerch = Pc.slots.length;
  const r = mulberry32((Math.imul(seed, 2246822519) ^ hashStr('perchStart')) >>> 0);
  for (let i = 0; i < Pc.atStart; i++) {
    const m = perchMember(r, 0, 0);
    const sat = 10 + 50 * r();   // it landed this long before the video starts
    m.land = r3(-sat - m.inT);
    m.leave = r3(30 + 240 * r());
    out.push({ type: 'perch', t: 0, perch: i % nPerch, members: [m], start: 1 });
  }
}

// Flushed birds come back: after a clap that scattered birds, often a few return once it is calm again.
function perchComeBack({ seed, out }, Pc, claps) {
  const nPerch = Pc.slots.length;
  const rr = mulberry32((Math.imul(seed, 3266489917) ^ hashStr('perchReturn')) >>> 0);
  for (const c of claps) {
    const sitting = out.reduce((n, e) => n + (e.type !== 'perch' ? 0 : e.members.filter((m) => e.t + m.land + m.inT < c && e.t + m.leave > c).length), 0);
    if (!sitting || rr() > (Pc.comeBack ?? 0.75)) continue;
    const n = 1 + Math.floor(rr() * Math.min(3, sitting));
    const [s0, s1] = Pc.stay ?? [60, 300];
    const members = [];
    let land = 0;
    for (let i = 0; i < n; i++) { members.push(perchMember(rr, land, s0 + (s1 - s0) * rr())); land += 2 + 15 * rr(); }
    out.push({ type: 'perch', t: r3(c + (Pc.calm ?? 25) + 5 + 55 * rr()), perch: Math.floor(rr() * nPerch), members });
  }
}

// Each bird takes a free slot of its perch in landing order (busy until the bird before has flown off); a clap flushes
// every bird sitting then and none lands in the calm after it. A group left with no bird is dropped.
function perchSlots({ out }, Pc, claps) {
  const busy = Pc.slots.map((n) => Array.from({ length: n }, () => -1e9));
  const ps = out.filter((e) => e.type === 'perch').sort((a, b) => a.t - b.t);
  const items = ps.flatMap((e) => e.members.map((m) => ({ e, m, t0: e.t + m.land }))).sort((a, b) => a.t0 - b.t0);
  const kept = new Map(ps.map((e) => [e, []]));
  for (const { e, m, t0 } of items) {
    const tLand = t0 + m.inT;
    if (!e.start && claps.some((c) => t0 > c - 2 && t0 < c + (Pc.calm ?? 25))) continue;
    let tLeave = e.t + m.leave;
    const flush = claps.find((c) => c > tLand && c < tLeave);
    if (flush != null) tLeave = flush + 0.15 + 0.7 * ((m.seed % 1000) / 1000);
    const sl = busy[e.perch];
    const free = sl.map((b, i) => [i, b]).filter(([, b]) => b < t0 - 1);
    if (!free.length) continue;
    const pick = free[Math.min(free.length - 1, Math.floor(m.slot * free.length))][0];
    sl[pick] = tLeave + m.outT + 1;
    kept.get(e).push({ ...m, slot: pick, leave: r3(tLeave - e.t) });
  }
  for (const e of ps) {
    const ms = kept.get(e);
    if (!ms.length) { out.splice(out.indexOf(e), 1); continue; }
    e.members = ms;
    e.dur = r3(Math.max(...ms.map((m) => m.leave + m.outT)) + 0.5);
    delete e.start;
  }
}

// Boats as everyday traffic (boat.ambient: a city canal, a busy river): one after another, never two at once, with
// an idle spell between them (idle: [s, s]), at any time (also during storms); they mostly alternate direction
// like the spotlight boats. Share of time with a boat out = mean dur / (mean dur + mean idle).
function boatTraffic({ spec, seed, duration, out }) {
  const Bo = spec?.boat;
  if (!Bo?.ambient) return;
  const r = mulberry32((Math.imul(seed, 1103515245) ^ hashStr('boat-ambient')) >>> 0);
  const U = (a, b) => a + (b - a) * r();
  const [d0, d1] = Bo.dur ?? [120, 160], [g0, g1] = Bo.idle ?? [20, 80];
  let t = (Bo.startAfter ?? 5) + U(0, Bo.first ?? 30), last = 0;
  // atStart: a boat is already out at t = 0, u0 of the way along its pass (strong openings)
  const u0 = Bo.atStart ? U(0.3, 0.45) : 0;
  if (Bo.atStart) t = 0;
  while (t < duration - (Bo.endBefore ?? 30) - d1) {
    const e = { type: 'boat', t: r3(t), dur: r3(U(d0, d1)), dir: r() < 0.5 ? 1 : -1, lane: r3(r()), seed: Math.floor(r() * 2147483647) };
    if (t === 0 && u0) { e.u0 = r3(u0); e.dur = r3(e.dur * (1 - u0)); }
    if (last && r() < 0.75) e.dir = -last;
    last = e.dir;
    out.push(e);
    t = e.t + e.dur + U(g0, g1);
  }
}

// A moth visiting a lamp (moth.js; the lamp is the layer's): it comes in out of the dark, circles the light in
// erratic loops, lands on the lit pane now and then, and flies off. Each visit carries its own flight constants.
function moth({ spec, stream }) {
  const Mo = spec?.moth;
  if (!Mo?.perHour) return;
  const [d0, d1] = Mo.dur ?? [45, 140];
  stream('moth', { minGap: 10, ...Mo }, (r, t) => {
    const U = (a, b) => a + (b - a) * r();
    const dur = U(d0, d1);
    const lands = [];
    const nl = Math.floor(U(0, (Mo.lands ?? 2) + 0.999));
    for (let i = 0; i < nl; i++) lands.push([r3(U(0.15, 0.85) * dur), r3(U(2, 9)), r3(U(-0.65, 0.65)), r3(U(-0.7, 0.6))]);
    lands.sort((a, b) => a[0] - b[0]);
    const side = () => { const a = U(-2.6, -0.5); return [r3(Math.cos(a) * U(5, 8) * (r() < 0.5 ? -1 : 1)), r3(U(-1, 4)), r3(U(-3, 2))]; };
    return {
      type: 'moth', t: r3(t), dur: r3(dur), R0: r3(U(1.6, 2.4)), w: r3((r() < 0.5 ? -1 : 1) * U(1.6, 3.2)), th0: r3(U(0, 6.283)),
      ph: [r3(U(0, 6.283)), r3(U(0, 6.283)), r3(U(0, 6.283)), r3(U(0, 6.283)), r3(U(0, 6.283)), r3(U(0, 6.283))],
      hz: r3(U(28, 45)), from: side(), to: side(), lands, seed: Math.floor(r() * 2147483647),
    };
  });
}

// Pet behaviors (pet.js plays clips from tools/pet_clips.py): acts: [{ name, weight, dur: seconds of motion
// (in + out), hold: [s0, s1] seconds held at the rest pose }]. One at a time with long gaps.
function petActs({ spec, stream }) {
  const Pa = spec?.petAct;
  if (!Pa?.perHour || !Pa.acts?.length) return;
  const wsum = Pa.acts.reduce((s, a) => s + (a.weight ?? 1), 0);
  stream('petact', Pa, (r, t) => {
    let u = r() * wsum, act = Pa.acts[0];
    for (const a of Pa.acts) { u -= a.weight ?? 1; if (u <= 0) { act = a; break; } }
    const [h0, h1] = act.hold ?? [0, 0];
    const hold = r3(h0 + (h1 - h0) * r());
    return { type: 'petact', t: r3(t), act: act.name, hold, dur: r3((act.dur ?? 8) + hold), seed: Math.floor(r() * 2147483647) };
  });
}

const STREAMS = [fish, flurry, farflash, neon, gutter, car, ember, star, birds, critters, ants, perches, boatTraffic, moth, petActs];
