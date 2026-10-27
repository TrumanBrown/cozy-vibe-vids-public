// Small pure helpers the layers and the timeline share. No three.js here, so the timeline can use them in Node.

// Smoothstep of x clamped to 0..1.
export const smooth = (x) => { const s = Math.min(Math.max(x, 0), 1); return s * s * (3 - 2 * s); };

// An sRGB channel value (0..1) in linear light.
export const toLin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));

// A seeded hash of two integers in [0, 1).
export function hash(a, b) {
  let h = Math.imul((a | 0) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul((b | 0) + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}
