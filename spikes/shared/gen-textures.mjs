// Generates the spike's original 16x16 pixel textures as PNGs (seeded, no deps).
// Usage: node spikes/shared/gen-textures.mjs [outDir]
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(process.argv[2] ?? path.join(here, 'textures'));
fs.mkdirSync(outDir, { recursive: true });

function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const crcTable = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function writePng(file, w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 4 + 1)] = 0;
    rgba.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0)),
  ]);
  fs.writeFileSync(file, png);
}

const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
const shade = (c, k) => c.map((v) => clamp(v * k));

function texture(name, size, seed, fn) {
  const rand = mulberry32(seed);
  const buf = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const [r, g, b, a = 255] = fn(x, y, rand);
      buf.set([clamp(r), clamp(g), clamp(b), clamp(a)], (y * size + x) * 4);
    }
  }
  writePng(path.join(outDir, `${name}.png`), size, size, buf);
}

// Floor: 4 planks of 4 px, staggered joints, per-plank tone, light grain.
{
  const base = hex('#7a4a22');
  const rand = mulberry32(11);
  const tones = [0, 1, 2, 3].map(() => 0.85 + rand() * 0.3);
  const joints = [0, 1, 2, 3].map(() => Math.floor(rand() * 16));
  texture('floor_planks', 16, 12, (x, y, r) => {
    const p = y >> 2;
    let k = tones[p] * (0.92 + r() * 0.14);
    if ((y & 3) === 3) k *= 0.62;
    if (x === joints[p]) k *= 0.7;
    return shade(base, k);
  });
}

texture('wall_plaster', 16, 21, (x, y, r) => shade(hex('#b8875a'), 0.9 + r() * 0.12));

texture('wood_dark', 16, 31, (x, y, r) => {
  const k = (0.85 + r() * 0.2) * (y % 5 === 0 ? 0.85 : 1);
  return shade(hex('#4a2c16'), k);
});

// Rug: original concentric-diamond weave, rust + ochre + deep plum.
texture('rug', 16, 41, (x, y, r) => {
  const d = Math.abs(x - 7.5) + Math.abs(y - 7.5);
  const ring = Math.floor(d) % 4;
  const border = x === 0 || y === 0 || x === 15 || y === 15;
  const col = border ? hex('#3a1c2c') : [hex('#8a3b1e'), hex('#c98a3a'), hex('#5a2433'), hex('#8a3b1e')][ring];
  return shade(col, 0.9 + r() * 0.15);
});

// Placeholder pet fur: soft smoky gray-brown with darker ticking (not any game mob).
texture('fur', 16, 51, (x, y, r) => {
  const tick = (x * 7 + y * 3) % 11 === 0;
  return shade(hex('#6d6259'), (tick ? 0.7 : 1) * (0.9 + r() * 0.2));
});

texture('shade', 16, 61, (x, y, r) => shade(hex('#ffd9a0'), (x % 4 === 0 ? 0.82 : 1) * (0.95 + r() * 0.05)));

// Distant facade: dark masonry with a 4x4 window grid; *_emit marks lit windows.
{
  const rand = mulberry32(71);
  const lit = Array.from({ length: 16 }, () => rand() < 0.35);
  const isWin = (x, y) => x % 4 !== 0 && x % 4 !== 3 && y % 4 !== 0;
  texture('facade', 16, 72, (x, y, r) =>
    isWin(x, y) ? (lit[(y >> 2) * 4 + (x >> 2)] ? hex('#ffb35c') : hex('#1a1a2a')) : shade(hex('#2b2638'), 0.85 + r() * 0.2));
  texture('facade_emit', 16, 73, (x, y) =>
    isWin(x, y) && lit[(y >> 2) * 4 + (x >> 2)] ? hex('#ffb35c') : [0, 0, 0]);
}

console.log(`textures written to ${outDir}`);
