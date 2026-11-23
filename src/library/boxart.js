// Blocky models built from boxes in code (cat3d.js, frog3d.js): pixel-art materials painted per face, a stable hash
// for the grain, and hex colors. A part's painter gets a point on the box's surface (units, centered on the box) and
// the face index, and returns the sRGB color there.
import * as THREE from 'three';

export function hash3(a, b, c) {
  let h = (a * 374761393 + b * 668265263 + c * 2147483647) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export const hex = (s) => [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16));

// BoxGeometry face layout (three.js buildPlane): texel (c, r) of face f -> the point on the box surface.
export const FACES = [
  { u: 2, v: 1, ud: -1, vd: -1, w: 0, ws: 1 },   // +x
  { u: 2, v: 1, ud: 1, vd: -1, w: 0, ws: -1 },   // -x
  { u: 0, v: 2, ud: 1, vd: 1, w: 1, ws: 1 },     // +y
  { u: 0, v: 2, ud: 1, vd: -1, w: 1, ws: -1 },   // -y
  { u: 0, v: 1, ud: 1, vd: -1, w: 2, ws: 1 },    // +z
  { u: 0, v: 1, ud: -1, vd: -1, w: 2, ws: -1 },  // -z
];

// Six pixel-art materials for a box of size [sx, sy, sz] units: color(p, face) gives the sRGB color at point p; each
// texel's brightness varies by +-grain/2 (a cat's fur 0.14, a frog's skin less).
export function boxMaterials(size, texels, color, partId, { grain = 0.14, roughness = 0.92 } = {}) {
  return FACES.map((f, fi) => {
    const cw = Math.max(1, Math.round(size[f.u] * texels)), ch = Math.max(1, Math.round(size[f.v] * texels));
    const cv = document.createElement('canvas');
    cv.width = cw; cv.height = ch;
    const g = cv.getContext('2d');
    const img = g.createImageData(cw, ch);
    for (let r = 0; r < ch; r++) {
      for (let c = 0; c < cw; c++) {
        const p = [0, 0, 0];
        p[f.u] = ((c + 0.5) / cw * size[f.u] - size[f.u] / 2) * f.ud;
        p[f.v] = ((r + 0.5) / ch * size[f.v] - size[f.v] / 2) * f.vd;
        p[f.w] = f.ws * size[f.w] / 2;
        const col = hex(color(p, fi));
        const n = 1 - grain / 2 + grain * hash3(partId * 7 + fi, c, r);
        const k = (r * cw + c) * 4;
        img.data[k] = Math.min(255, col[0] * n); img.data[k + 1] = Math.min(255, col[1] * n); img.data[k + 2] = Math.min(255, col[2] * n);
        img.data[k + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(cv);
    t.colorSpace = THREE.SRGBColorSpace;
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    return new THREE.MeshStandardMaterial({ map: t, roughness, metalness: 0 });
  });
}
