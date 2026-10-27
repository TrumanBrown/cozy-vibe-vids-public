// Instanced leaf-card foliage. Scenes (via nature.js helpers) add leaves in world space; the engine
// turns them into a few InstancedMeshes after build. Leaves are alpha-tested cards with real leaf
// silhouettes (maple/round/needle), tinted per instance, softly self-lit so canopies stay rich at night.
import * as THREE from 'three';
import { getTexture } from './textures.js';
import { Rng } from './rng.js';

let current = null;
export const currentFoliage = () => current;

const SHAPES = ['maple', 'round', 'needle'];
const VARIANTS = 3;
const Z = new THREE.Vector3(0, 0, 1);

export class Foliage {
  constructor(seed, { castDistance = 45, camera = [0, 0, 0] } = {}) {
    this.seed = seed;
    this.castDistance = castDistance;
    this.camera = new THREE.Vector3(...camera);
    this.buckets = new Map(); // key -> { shape, variant, cast, list: [] }
    current = this;
  }

  // One leaf: world position, size (blocks), color (THREE.Color or hex), outward hint (unit vec3), rng.
  leaf(pos, size, color, rng, { shape = 'maple', normal = null, glow = 1 } = {}) {
    const p = new THREE.Vector3(...pos);
    const cast = p.distanceTo(this.camera) < this.castDistance && size < 1.2;
    const variant = rng.int(0, VARIANTS - 1);
    const key = `${shape}:${variant}:${cast ? 1 : 0}`;
    if (!this.buckets.has(key)) this.buckets.set(key, { shape, variant, cast, list: [] });
    const n = new THREE.Vector3(rng.range(-1, 1), rng.range(-0.4, 1), rng.range(-1, 1));
    if (normal) n.addScaledVector(new THREE.Vector3(...normal), 1.3);
    n.normalize();
    const q = new THREE.Quaternion().setFromUnitVectors(Z, n);
    q.multiply(new THREE.Quaternion().setFromAxisAngle(Z, rng.range(0, Math.PI * 2)));
    const c = color instanceof THREE.Color ? color.clone() : new THREE.Color(color);
    this.buckets.get(key).list.push({ p, q, s: size, c, glow });
  }

  // Leaves distributed through an ellipsoid shell (denser near the surface), shaded darker underneath
  // and inside. palette: array of hex strings.
  cloud({ c, r, squash = 0.7, size = 0.45, palette, rng, cover = 5, shape = 'maple', exclude = null, inner = 0.55, glow = 1 }) {
    const ry = r * squash;
    const area = 4 * Math.PI * Math.pow((r * r + r * ry + r * ry) / 3, 1);
    const n = Math.max(12, Math.round((cover * area) / (size * size)));
    const cols = palette.map((h) => new THREE.Color(h));
    for (let i = 0; i < n; i++) {
      const u = rng.range(-1, 1), th = rng.range(0, Math.PI * 2);
      const rad = Math.pow(rng.next(), 0.35) * (1 - inner) + inner; // biased to the shell
      const sxz = Math.sqrt(1 - u * u);
      const dir = [Math.cos(th) * sxz, u, Math.sin(th) * sxz];
      const pos = [c[0] + dir[0] * r * rad, c[1] + dir[1] * ry * rad, c[2] + dir[2] * r * rad];
      if (exclude && exclude(...pos)) continue;
      const up = u * 0.5 + 0.5;
      const shadeK = (0.3 + 0.85 * Math.pow(up, 1.3)) * (0.55 + 0.45 * rad);
      const col = cols[rng.int(0, cols.length - 1)].clone().multiplyScalar(shadeK * rng.range(0.85, 1.12));
      this.leaf(pos, size * rng.range(0.75, 1.3), col, rng, { shape, normal: dir, glow: glow * (0.6 + 0.4 * (u * 0.5 + 0.5)) });
    }
  }

  // Hanging/trailing strand from `start` going down `len`, with leaves every `step`.
  strand({ start, len, size = 0.22, palette, rng, step = 0.12, sway = 0.08, shape = 'maple', toward = [0, 0, 1] }) {
    const cols = palette.map((h) => new THREE.Color(h));
    for (let y = 0; y < len; y += step * rng.range(0.6, 1.3)) {
      const k = y / Math.max(len, 1e-3);
      const pos = [start[0] + Math.sin(y * 3.1) * sway + rng.range(-1, 1) * size * 0.4, start[1] - y, start[2] + rng.range(-1, 1) * size * 0.4];
      this.leaf(pos, size * rng.range(0.8, 1.25) * (1 - k * 0.3), cols[rng.int(0, cols.length - 1)].clone().multiplyScalar(rng.range(0.8, 1.1)), rng, { shape, normal: toward });
    }
  }

  finish(scene) {
    const out = [];
    for (const { shape, variant, cast, list } of this.buckets.values()) {
      const tex = getTexture({ name: 'leafCard', shape, seed: variant }, this.seed);
      const mat = new THREE.MeshStandardMaterial({
        map: tex.map, alphaTest: 0.5, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 0.7,
        emissive: '#ffffff', emissiveMap: tex.map, emissiveIntensity: 0.22,
      });
      // Tint the self-glow by the instance color too (otherwise it would be white).
      mat.onBeforeCompile = (sh) => {
        sh.fragmentShader = sh.fragmentShader.replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\n#ifdef USE_COLOR\ntotalEmissiveRadiance *= vColor.rgb;\n#endif');
      };
      mat.customProgramCacheKey = () => 'leafglow';
      const geo = new THREE.PlaneGeometry(1, 1);
      const mesh = new THREE.InstancedMesh(geo, mat, list.length);
      const m4 = new THREE.Matrix4(), sc = new THREE.Vector3();
      list.forEach((l, i) => {
        mesh.setMatrixAt(i, m4.compose(l.p, l.q, sc.set(l.s, l.s, l.s)));
        mesh.setColorAt(i, l.c.clone().multiplyScalar(1));
      });
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.frustumCulled = false;
      mesh.castShadow = cast;
      mesh.receiveShadow = true;
      mesh.userData.noAO = true;
      mesh.name = `foliage:${shape}:${variant}`;
      scene.add(mesh);
      out.push(mesh);
    }
    current = null;
    return out;
  }

  get count() { let n = 0; for (const b of this.buckets.values()) n += b.list.length; return n; }
}

export { SHAPES, Rng };
