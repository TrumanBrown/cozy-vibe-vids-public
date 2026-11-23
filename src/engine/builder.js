// Box builder: everything in a scene is cuboids. Boxes are merged into one mesh per material, with
// UVs in block units (16 texels per block) and per-box tint stored as vertex colors.
//
// Material spec: { tex: { name, ...params }, tint, rough, emissive, emissiveColor, opacity, unlit,
//                  fog, cast, receive, side }
import * as THREE from 'three';
import { getTexture } from './textures.js';

const FACES = {
  px: { n: [1, 0, 0], v: (a, b) => [[b[0], a[1], b[2]], [b[0], a[1], a[2]], [b[0], b[1], a[2]], [b[0], b[1], b[2]]], uv: (p, a, b) => [b[2] - p[2], p[1] - a[1]] },
  nx: { n: [-1, 0, 0], v: (a, b) => [[a[0], a[1], a[2]], [a[0], a[1], b[2]], [a[0], b[1], b[2]], [a[0], b[1], a[2]]], uv: (p, a) => [p[2] - a[2], p[1] - a[1]] },
  py: { n: [0, 1, 0], v: (a, b) => [[a[0], b[1], b[2]], [b[0], b[1], b[2]], [b[0], b[1], a[2]], [a[0], b[1], a[2]]], uv: (p, a, b) => [p[0] - a[0], b[2] - p[2]] },
  ny: { n: [0, -1, 0], v: (a, b) => [[a[0], a[1], a[2]], [b[0], a[1], a[2]], [b[0], a[1], b[2]], [a[0], a[1], b[2]]], uv: (p, a) => [p[0] - a[0], p[2] - a[2]] },
  pz: { n: [0, 0, 1], v: (a, b) => [[a[0], a[1], b[2]], [b[0], a[1], b[2]], [b[0], b[1], b[2]], [a[0], b[1], b[2]]], uv: (p, a) => [p[0] - a[0], p[1] - a[1]] },
  nz: { n: [0, 0, -1], v: (a, b) => [[b[0], a[1], a[2]], [a[0], a[1], a[2]], [a[0], b[1], a[2]], [b[0], b[1], a[2]]], uv: (p, a, b) => [b[0] - p[0], p[1] - a[1]] },
};
const FACE_NAMES = Object.keys(FACES);
const ZERO = [0, 0, 0];

const materialCache = new Map();
let sceneSeed = 1;
export function setTextureSeed(seed) { sceneSeed = seed; }

function specKey(spec) {
  const { tint, ...rest } = spec;
  return JSON.stringify(rest);
}

// Glossier finishes for varnished wood / glazed clay so the env probe shows reflections.
const DEFAULT_ROUGH = { wood: 0.5, bark: 0.95, fabric: 0.95, knit: 1, stone: 0.82, tile: 0.35, clay: 0.6, metal: 0.4, plain: 0.85, paper: 0.9, paint: 0.6, fur: 1, glow: 0.8 };

// Rounded-edge look without extra geometry: each face carries its own (s, t) coordinates in blocks and
// its size, plus world tangents; near an edge the shading normal bends toward that edge's outward
// direction, so every block edge catches a soft highlight like a bevelled cube.
function applyBevel(m, radius) {
  m.userData.bevel = radius;
  m.onBeforeCompile = (sh) => {
    sh.uniforms.bevelR = { value: radius };
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute vec4 aEdge;\nattribute vec3 aTanS;\nattribute vec3 aTanT;\nvarying vec4 vEdge;\nvarying vec3 vTS;\nvarying vec3 vTT;')
      .replace('#include <project_vertex>', '#include <project_vertex>\nvEdge = aEdge;\nvTS = normalize(normalMatrix * aTanS);\nvTT = normalize(normalMatrix * aTanT);');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float bevelR;\nvarying vec4 vEdge;\nvarying vec3 vTS;\nvarying vec3 vTT;')
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
      {
        float r = min(bevelR, 0.4 * min(vEdge.z, vEdge.w));
        if (r > 1e-4) {
          vec2 d0 = vEdge.xy, d1 = vEdge.zw - vEdge.xy;
          float fs = pow(max(0.0, 1.0 - d1.x / r), 2.0) - pow(max(0.0, 1.0 - d0.x / r), 2.0);
          float ft = pow(max(0.0, 1.0 - d1.y / r), 2.0) - pow(max(0.0, 1.0 - d0.y / r), 2.0);
          float fl = gl_FrontFacing ? 1.0 : -1.0;
          normal = normalize(normal + (vTS * fs + vTT * ft) * 1.1 * fl);
        }
      }`);
  };
  m.customProgramCacheKey = () => 'bevel';
}

export function makeMaterial(spec) {
  const key = specKey(spec);
  if (materialCache.has(key)) return materialCache.get(key);
  const tex = spec.img ? getImageTexture(spec.img, spec.imgOpts) : spec.tex ? getTexture(spec.tex, sceneSeed) : null;
  const transparent = spec.opacity !== undefined && spec.opacity < 1;
  const common = {
    map: tex?.map ?? null,
    vertexColors: true,
    transparent,
    opacity: spec.opacity ?? 1,
    depthWrite: !transparent,
    fog: spec.fog ?? true,
    side: spec.side === 'double' || tex?.alpha ? THREE.DoubleSide : THREE.FrontSide,
    alphaTest: tex?.alpha ? 0.5 : 0,
    alphaToCoverage: !!tex?.alpha,
  };
  let m;
  if (spec.unlit) m = new THREE.MeshBasicMaterial(common);
  else {
    m = new THREE.MeshStandardMaterial({ ...common, roughness: spec.rough ?? DEFAULT_ROUGH[tex?.kind] ?? 0.85, metalness: spec.metal ?? 0 });
    if (tex?.normalMap && spec.normal !== 0) { m.normalMap = tex.normalMap; m.normalScale.setScalar(spec.normal ?? 1); }
    if (['fur', 'fabric', 'knit'].includes(tex?.kind)) m.envMapIntensity = 0.35;
    const bevel = spec.bevel ?? (tex?.kind === 'fabric' || tex?.kind === 'knit' ? 0.09 : 0.045);
    if (bevel > 0 && !tex?.alpha) applyBevel(m, bevel);
  }
  if (spec.emissive) {
    m.emissive = new THREE.Color(spec.emissiveColor ?? '#ffffff');
    m.emissiveIntensity = spec.emissive;
    m.emissiveMap = tex?.emissiveMap ?? tex?.map ?? null;
  }
  if (spec.blending === 'add') { m.blending = THREE.AdditiveBlending; m.depthWrite = false; m.transparent = true; }
  m.userData.tex = tex;
  materialCache.set(key, m);
  return m;
}

// Image texture from assets/textures (generated pack). opts: { scale: blocks per image (default 1),
// kind: material kind for roughness/bevel defaults }.
const imageCache = new Map();
const IMG_KIND = { planks: 'wood', log: 'wood', bark: 'bark', stone: 'stone', cobble: 'stone', fieldstone: 'stone', bookshelf: 'paper',
  leaves: 'leaves', wool: 'knit', plaid: 'fabric', kilim: 'fabric', shingles: 'wood', rope: 'fabric', iron: 'metal', fur: 'fur', pumpkin: 'clay', wall: 'plain' };
export function getImageTexture(id, { scale = 1 } = {}) {
  const key = `${id}|${scale}`;
  if (imageCache.has(key)) return imageCache.get(key);
  const load = (file, srgb) => {
    let done;
    pendingLoads.push(new Promise((r) => { done = r; }));
    const t = new THREE.TextureLoader().load(`/assets/textures/${file}`, () => done(), undefined, () => { console.error(`missing texture ${file}`); done(); });
    t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 16;
    t.magFilter = THREE.LinearFilter;
    t.minFilter = THREE.LinearMipmapLinearFilter;
    return t;
  };
  const kind = Object.entries(IMG_KIND).find(([k]) => id.includes(k))?.[1] ?? 'plain';
  const res = { map: load(`${id}.png`, true), normalMap: load(`${id}_n.png`, false), bw: scale, bh: scale, alpha: kind === 'leaves', kind };
  imageCache.set(key, res);
  return res;
}
export const pendingLoads = [];

class Group {
  constructor(spec) {
    this.spec = spec;
    this.pos = []; this.nrm = []; this.uv = []; this.col = []; this.idx = []; this.edge = []; this.ts = []; this.tt = [];
  }
}

export class Builder {
  constructor() {
    this.groups = new Map();
    this.stack = [new THREE.Matrix4()];
    this._v = new THREE.Vector3();
    this._n = new THREE.Vector3();
    this._nm = new THREE.Matrix3();
  }
  get matrix() { return this.stack[this.stack.length - 1]; }

  // Run fn with an extra transform (position, rotation about Y in radians, optional rotation about X/Z).
  at(pos, rotY, fn, { rotX = 0, rotZ = 0, scale = 1 } = {}) {
    const m = new THREE.Matrix4().compose(
      new THREE.Vector3(...pos),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(rotX, rotY, rotZ, 'YXZ')),
      new THREE.Vector3(scale, scale, scale),
    );
    this.stack.push(this.matrix.clone().multiply(m));
    try { fn(this); } finally { this.stack.pop(); }
    return this;
  }

  // Axis-aligned (in local space) box from min to max. opts: { faces: {px: spec,...}, skip: ['ny'], uv: 'box'|'world', uvOff: [u,v] }
  box(min, max, spec, opts = {}) {
    const m = this.matrix;
    this._nm.getNormalMatrix(m);
    const ref = opts.uv === 'world' ? [ZERO, ZERO] : [min, max];
    const [uo, vo] = opts.uvOff ?? [0, 0];
    for (const f of FACE_NAMES) {
      if (opts.skip?.includes(f)) continue;
      const fs = opts.faces?.[f] ?? spec;
      if (!fs) continue;
      const key = specKey(fs);
      if (!this.groups.has(key)) this.groups.set(key, new Group(fs));
      const g = this.groups.get(key);
      const mat = makeMaterial(fs);
      const bw = mat.userData.tex?.bw ?? 1, bh = mat.userData.tex?.bh ?? 1;
      const tint = new THREE.Color(fs.tint ?? '#ffffff');
      const F = FACES[f];
      const base = g.pos.length / 3;
      this._n.set(...F.n).applyMatrix3(this._nm).normalize();
      const wv = F.v(min, max).map((p) => new THREE.Vector3(...p).applyMatrix4(m));
      const sAx = wv[1].clone().sub(wv[0]), tAx = wv[3].clone().sub(wv[0]);
      const FW = sAx.length(), FH = tAx.length();
      sAx.normalize(); tAx.normalize();
      const ec = [[0, 0], [FW, 0], [FW, FH], [0, FH]];
      F.v(min, max).forEach((p, k) => {
        const w = wv[k];
        g.pos.push(w.x, w.y, w.z);
        g.nrm.push(this._n.x, this._n.y, this._n.z);
        const [u, v] = F.uv(p, ref[0], ref[1]);
        g.uv.push((u + uo) / bw, (v + vo) / bh);
        g.col.push(tint.r, tint.g, tint.b);
        g.edge.push(ec[k][0], ec[k][1], FW, FH);
        g.ts.push(sAx.x, sAx.y, sAx.z);
        g.tt.push(tAx.x, tAx.y, tAx.z);
      });
      g.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
    return this;
  }

  // Box from a corner + size, convenience.
  cube(at, size, spec, opts) { return this.box(at, [at[0] + size[0], at[1] + size[1], at[2] + size[2]], spec, opts); }

  // Local point -> world coordinates under the current transform (e.g., where a lamp's light goes).
  world(p) { const v = new THREE.Vector3(...p).applyMatrix4(this.matrix); return [v.x, v.y, v.z]; }

  // Run fn at a world-space position (ignores the current transform stack).
  atWorld(pos, rotY, fn) {
    this.stack.push(new THREE.Matrix4());
    try { return this.at(pos, rotY, fn); } finally { this.stack.pop(); }
  }

  // Build into a THREE.Group (one mesh per material).
  finish(name = 'static') {
    const root = new THREE.Group();
    root.name = name;
    for (const g of this.groups.values()) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(g.pos, 3));
      geo.setAttribute('normal', new THREE.Float32BufferAttribute(g.nrm, 3));
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(g.uv, 2));
      geo.setAttribute('color', new THREE.Float32BufferAttribute(g.col, 3));
      geo.setAttribute('aEdge', new THREE.Float32BufferAttribute(g.edge, 4));
      geo.setAttribute('aTanS', new THREE.Float32BufferAttribute(g.ts, 3));
      geo.setAttribute('aTanT', new THREE.Float32BufferAttribute(g.tt, 3));
      geo.setIndex(g.idx);
      geo.computeBoundingSphere();
      const mat = makeMaterial(g.spec);
      const mesh = new THREE.Mesh(geo, mat);
      const s = g.spec;
      mesh.castShadow = s.cast ?? !(s.emissive || mat.transparent || s.unlit);
      mesh.receiveShadow = s.receive ?? !s.unlit;
      if (mat.transparent) mesh.userData.noAO = true;
      if (mat.transparent) mesh.renderOrder = s.renderOrder ?? 10;
      root.add(mesh);
    }
    return root;
  }
}

// Build a separately animatable part: fn receives a fresh Builder in the part's local space.
export function part(fn, name = 'part') {
  const b = new Builder();
  fn(b);
  return b.finish(name);
}
