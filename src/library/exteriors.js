// Exterior backdrops seen through windows. Built with the same box builder (static) or as scrolling
// groups (train). Scale: 1 block ~ 0.5 m.
import * as THREE from 'three';
import { part } from '../engine/builder.js';
import { mat, T } from './props.js';

// One building: facade texture (with lit windows) on all vertical faces; flat dark roof.
export function building(b, { x0, x1, z, y0 = -2, depth = 12, height, rng, wall = '#2b2638', lit = 0.35, cellW = 24, cellH = 40, winW = 14, winH = 22, warm, cool, coolRatio = 0.08, glow = 1.6, roof = '#14121c', panes = false, wallGlow = 0.12 }) {
  const bw = Math.max(1, Math.round(x1 - x0)), bh = Math.max(1, Math.min(48, Math.round(height - y0)));
  const spec = {
    tex: { name: 'facade', seed: rng.int(0, 1e9), wall, bw, bh, cellW, cellH, winW, winH, lit, panes, wallGlow, ...(warm ? { warm } : {}), ...(cool ? { cool } : {}), coolRatio },
    tint: '#ffffff', rough: 0.95, emissive: glow, emissiveColor: '#ffffff', cast: false,
  };
  b.box([x0, y0, z - depth], [x1, height, z], spec, { faces: { py: mat.plain(roof, 1), ny: null } });
  return spec;
}

// City across a street: low near row (rooftops visible from upstairs), shop fronts, streetlamps,
// a mid-rise row behind, then distant towers.
export function cityStreet(b, ctx, { rng, nearZ = -26, xRange = [-40, 50], streetY = -14, nearFloors = [2, 3], midZ = [-48, -75], towerZ = [-110, -260] }) {
  const lamps = [];
  let x = xRange[0];
  while (x < xRange[1]) {
    const w = rng.int(10, 18);
    const floors = rng.int(nearFloors[0], nearFloors[1]);
    const h = streetY + floors * 6 + rng.int(0, 2);
    const z = nearZ - rng.int(0, 3);
    const wall = rng.pick(['#3a2a2a', '#2e2a36', '#40302a', '#2a2a30', '#352a33']);
    building(b, { x0: x, x1: x + w, z, y0: streetY, depth: 14, height: h, rng, wall, lit: rng.range(0.3, 0.55), cellW: rng.pick([24, 28, 32]), cellH: 96, winW: rng.pick([12, 14, 16]), winH: 40, panes: true, glow: 1.0 });
    b.box([x - 0.3, h, z - 14], [x + w + 0.3, h + 0.6, z + 0.4], mat.plain('#1e1820', 1));
    // Rooftop clutter: chimneys, a water tank on legs, a lit roof-access shed.
    const rr = rng.next();
    if (rr < 0.4) {
      const cx = x + rng.int(2, w - 4);
      for (const lx of [0, 2.2]) b.box([cx + lx, h + 0.6, z - 9], [cx + lx + 0.4, h + 3, z - 8.6], mat.plain('#1a1418', 1));
      b.box([cx - 0.3, h + 3, z - 10], [cx + 2.9, h + 6, z - 7], mat.wood('#2e221c'));
      b.box([cx - 0.5, h + 6, z - 10.2], [cx + 3.1, h + 6.6, z - 6.8], mat.plain('#1a1418', 1));
    } else if (rr < 0.75) {
      const cx = x + rng.int(1, w - 4);
      b.box([cx, h + 0.6, z - 6], [cx + 3, h + 3, z - 3], mat.plain('#2a2228', 1));
      b.box([cx + 1, h + 0.9, z - 2.98], [cx + 1.9, h + 2.4, z - 2.9], mat.bulb('#ffb860', 3));
    }
    for (let i = 0; i < rng.int(1, 3); i++) {
      const cx = x + rng.range(1, w - 2), cz = z - rng.range(2, 12);
      b.box([cx, h + 0.6, cz], [cx + 0.8, h + rng.range(1.5, 3), cz + 0.8], mat.plain('#2a1e1c', 1));
    }
    // Shop front at street level: glowing window + awning.
    const sx0 = x + 1, sx1 = x + w - 1;
    const shopColor = rng.pick(['#ffb85c', '#ff9a50', '#6fd0c8', '#ffcf80']);
    b.box([sx0, streetY + 0.6, z + 0.05], [sx1, streetY + 4.5, z + 0.15], mat.glow(shopColor, rng.range(1.2, 2.2), { name: 'noise', color: '#ffffff', v: 0.15, blotch: 0.2 }));
    b.box([sx0 - 0.3, streetY + 4.6, z], [sx1 + 0.3, streetY + 5, z + 2.2], { tex: { name: 'stripes', colors: rng.pick([['#6a2a2a', '#c8b090'], ['#2a4a3a', '#c8b090'], ['#2a3a5a', '#d0c0a0']]), width: 4 }, tint: '#ffffff', rough: 1 });
    x += w + rng.int(0, 2);
  }
  b.box([xRange[0], streetY - 1, nearZ - 2], [xRange[1], streetY, -2], mat.plain('#16141a', 0.35));
  b.box([xRange[0], streetY, nearZ - 0.2], [xRange[1], streetY + 0.3, nearZ + 4], mat.plain('#2a2628', 0.6));
  for (let lx = xRange[0] + 6; lx < xRange[1]; lx += 22) {
    b.box([lx - 0.2, streetY, nearZ + 3], [lx + 0.2, streetY + 9, nearZ + 3.4], mat.plain('#141214', 0.6));
    b.box([lx - 0.2, streetY + 9, nearZ + 3], [lx + 1.6, streetY + 9.3, nearZ + 3.4], mat.plain('#141214', 0.6));
    b.box([lx + 1, streetY + 8.6, nearZ + 2.9], [lx + 1.7, streetY + 9, nearZ + 3.5], mat.bulb('#ffc070', 8));
    lamps.push([lx + 1.35, streetY + 8.3, nearZ + 3.2]);
  }
  // Mid-rise row.
  x = xRange[0] - 30;
  while (x < xRange[1] + 30) {
    const w = rng.int(12, 22);
    const h = streetY + rng.int(5, 11) * 6;
    const z = rng.range(midZ[1], midZ[0]);
    building(b, { x0: x, x1: x + w, z, y0: streetY, depth: 16, height: h, rng, wall: rng.pick(['#2e2630', '#33282c', '#282430']), lit: rng.range(0.3, 0.55), cellW: rng.pick([20, 24]), cellH: 96, winW: rng.pick([12, 14]), winH: 44, glow: 1.8 });
    b.box([x - 0.3, h, z - 16], [x + w + 0.3, h + 0.6, z + 0.4], mat.plain('#1a1620', 1));
    x += w + rng.int(1, 4);
  }
  // Distant towers.
  for (let i = 0; i < 34; i++) {
    const tz = rng.range(towerZ[1], towerZ[0]);
    const tx = rng.range(-160, 180);
    const w = rng.int(14, 30);
    const h = rng.int(40, 150);
    building(b, { x0: tx, x1: tx + w, z: tz, y0: streetY - 10, depth: w, height: h, rng, wall: rng.pick(['#26222e', '#2a2630', '#1e1c26']), lit: rng.range(0.25, 0.5), cellW: 16, cellH: 64, winW: 10, winH: 40, glow: 2.2 });
    if (rng.chance(0.3)) b.box([tx + w / 2 - 0.3, h, tz - w / 2 - 0.3], [tx + w / 2 + 0.3, h + rng.int(6, 14), tz - w / 2 + 0.3], mat.plain('#18161e', 1));
    if (rng.chance(0.35)) b.box([tx + w / 2 - 0.5, h + 0.2, tz - w / 2 - 0.5], [tx + w / 2 + 0.5, h + 1, tz - w / 2 + 0.5], mat.bulb('#ff5a4a', 6));
  }
  return { lamps };
}

// Pine tree from stacked, shrinking tiers.
export function pine(b, { h = 14, rng, color = '#1e3324', trunk = '#2a1c14' }) {
  const tw = Math.max(0.4, h * 0.05);
  b.box([-tw / 2, 0, -tw / 2], [tw / 2, h * 0.35, tw / 2], mat.wood(trunk));
  const tiers = Math.max(3, Math.round(h / 3));
  for (let i = 0; i < tiers; i++) {
    const k = i / tiers;
    const y = h * 0.18 + k * h * 0.78;
    const r = (1 - k) * h * 0.24 + 0.4;
    const th = (h * 0.82) / tiers + 0.3;
    b.at([0, 0, 0], rng.range(0, Math.PI / 2), () => b.box([-r, y, -r], [r, y + th, r], { tex: { name: 'leaves', color: '#f2f2f2', density: 0.9 }, tint: color, rough: 0.9 }));
  }
}

// Lakeside forest at night: far ridges, pine bands on both shores, dark lake, a dock lamp.
export function lakeForest(b, ctx, { rng, shoreZ = -10, farShoreZ = -70, waterY = -2 }) {
  const lights = [];
  // Lake surface (slightly glossy to catch light).
  b.box([-120, waterY - 1, farShoreZ], [120, waterY, shoreZ + 2], mat.plain('#0e1418', 0.25));
  // Near shore: grass/rock bank and a few close pines at the sides.
  b.box([-60, waterY - 1, shoreZ], [60, waterY + 0.6, -2], mat.plain('#1a2018', 1));
  for (let i = 0; i < 10; i++) {
    const x = rng.chance(0.5) ? rng.range(-40, -9) : rng.range(9, 40);
    b.at([x, waterY + 0.6, rng.range(shoreZ - 2, shoreZ + 4)], 0, () => pine(b, { h: rng.range(14, 22), rng, color: '#18281c' }));
  }
  // Dock with a lantern post.
  const dx = 7;
  b.box([dx - 1.2, waterY + 0.3, shoreZ - 12], [dx + 1.2, waterY + 0.6, shoreZ], mat.wood('#3a2a1e'));
  for (let z = shoreZ - 12; z <= shoreZ; z += 4) for (const sx of [-1.1, 0.9]) b.box([dx + sx, waterY - 1, z], [dx + sx + 0.25, waterY + 0.4, z + 0.25], mat.wood('#2a1e14'));
  b.box([dx + 0.8, waterY + 0.6, shoreZ - 11.8], [dx + 1.1, waterY + 3.6, shoreZ - 11.5], mat.wood('#2a1e14'));
  b.box([dx + 0.7, waterY + 3.6, shoreZ - 11.9], [dx + 1.2, waterY + 4.2, shoreZ - 11.4], mat.bulb('#ffb860', 9));
  lights.push([dx + 0.95, waterY + 3.9, shoreZ - 11.65]);
  // Reflection streak of the dock lamp on the water.
  for (let i = 0; i < 9; i++) {
    const z = shoreZ - 12.5 + i * 1.1;
    const w = 0.25 + rng.range(0, 0.35);
    b.box([dx + 0.95 - w, waterY + 0.01, z], [dx + 0.95 + w, waterY + 0.03, z + 0.5], mat.glow('#ff9a40', 0.8 * (1 - i / 10), { name: 'noise', color: '#ffffff', v: 0.3, blotch: 0 }));
  }
  // Far shore: dense pine band + a couple of cabin windows.
  for (let i = 0; i < 140; i++) {
    const x = rng.range(-150, 150);
    b.at([x, waterY, farShoreZ - rng.range(0, 14)], 0, () => pine(b, { h: rng.range(10, 24), rng, color: '#142018' }));
  }
  for (let i = 0; i < 3; i++) {
    const x = rng.range(-50, 60), z = farShoreZ - rng.range(2, 6);
    b.box([x, waterY, z - 4], [x + 5, waterY + 3.5, z], mat.plain('#1a1612', 1));
    b.box([x + 1, waterY + 1.2, z + 0.02], [x + 2, waterY + 2.2, z + 0.1], mat.bulb('#ffaa55', 4));
    lights.push(null);
  }
  // Ridges behind.
  for (let i = 0; i < 12; i++) {
    const x = rng.range(-220, 220), w = rng.range(40, 90), h = rng.range(14, 38), z = rng.range(-150, -110);
    b.box([x - w / 2, waterY, z - 30], [x + w / 2, waterY + h, z], mat.plain('#121a1c', 1));
    b.box([x - w / 3, waterY + h, z - 25], [x + w / 3, waterY + h + h * 0.3, z - 5], mat.plain('#121a1c', 1));
  }
  return { lights: lights.filter(Boolean) };
}

// Train landscape: layers that scroll along -x at different speeds, periodic in the loop.
// Each layer is built twice side by side (period `span`) so it tiles seamlessly.
export function trainLandscape(ctx, { rng, groundY = -3, span = 240, layers }) {
  const L = ctx.loopSeconds;
  const groups = [];
  for (const layer of layers) {
    const g = new THREE.Group();
    for (const copy of [0, 1]) {
      const r = rng.fork(`${layer.name}`); // same content in both copies
      const p = part((b) => layer.build(b, r, span), layer.name);
      p.position.x = copy * span;
      g.add(p);
    }
    ctx.add(g);
    const cycles = layer.cycles;
    ctx.animate((t) => { g.position.x = -span / 2 - (((cycles * t) / L) % 1) * span; });
    groups.push(g);
  }
  return groups;
}
