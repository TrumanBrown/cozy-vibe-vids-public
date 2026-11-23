// Original cuboid creatures. Each is a THREE.Group of separately posable parts (for later state
// changes), designed at the project's texel density (1 texel = 1/16 block), slightly chibi-scaled.
// Do-not-copy: no game-mob proportions, cream-dog-with-red-collar, or creeper-like faces.
import * as THREE from 'three';
import { part } from '../engine/builder.js';
import { mat, T } from './props.js';

const furSpec = (tint, stripes = 0, v = 0.08) => ({ img: 'fur_grey', imgOpts: { scale: 0.6 }, tint: '#' + [1, 3, 5].map((i) => Math.min(255, Math.round(parseInt(tint.slice(i, i + 2), 16) * 1.8)).toString(16).padStart(2, '0')).join(''), rough: 1, bevel: 0.06 });

function place(g, pos = [0, 0, 0], rot = [0, 0, 0]) {
  g.position.set(...pos);
  g.rotation.set(rot[0], rot[1], rot[2], 'YXZ');
  return g;
}

function assemble(name, parts) {
  const root = new THREE.Group();
  root.name = name;
  for (const p of Object.values(parts)) root.add(p);
  return { group: root, parts };
}

// --- Cat: smoky gray-brown tabby with a pale chest and muzzle; round-ish loaf body, big head. -------
export function cat({ fur = '#7d7268', light = '#d8cbb8', nose = '#c48a80', pose = 'curled' } = {}) {
  const F = furSpec(fur, 3);
  const L = mat.plain(light, 1);
  const face = { tex: { name: 'face', w: 6, h: 5, fur, muzzle: light, eyes: pose === 'curled' ? 'closed' : 'open', nose, eyeRow: 2, eyeGap: 2 }, tint: '#ffffff', rough: 1 };
  const parts = {
    body: part((b) => {
      b.box([-6 * T, 0, -4 * T], [5 * T, 6 * T, 4 * T], F);
      b.box([-7 * T, 0, -4.5 * T], [-1 * T, 6.5 * T, 4.5 * T], F);
      b.box([3 * T, 0, -3 * T], [6 * T, 5 * T, 3 * T], L, { faces: { py: F } });
    }, 'cat.body'),
    head: part((b) => {
      b.box([-3 * T, 0, -2.5 * T], [3 * T, 5 * T, 2.5 * T], F, { faces: { pz: face } });
      for (const s of [-1, 1]) {
        const x0 = s < 0 ? -3 * T : 1 * T;
        b.box([x0, 5 * T, -1 * T], [x0 + 2 * T, 7 * T, 0.5 * T], F, { faces: { pz: mat.plain('#b88078', 1) } });
      }
      b.box([-3.5 * T, 0.5 * T, -1.5 * T], [-3 * T, 3 * T, 1.5 * T], F);
      b.box([3 * T, 0.5 * T, -1.5 * T], [3.5 * T, 3 * T, 1.5 * T], F);
    }, 'cat.head'),
    paws: part((b) => {
      b.box([0, 0, 0], [4 * T, 1.5 * T, 1.5 * T], L);
      b.box([0, 0, 2 * T], [4 * T, 1.5 * T, 3.5 * T], L);
    }, 'cat.paws'),
    tail: part((b) => {
      b.box([-1 * T, 0, 0], [1 * T, 2 * T, 4.5 * T], F);
      b.box([-1 * T, 0, 3 * T], [7 * T, 2 * T, 5 * T], F);
      b.box([6 * T, 0, 3 * T], [10 * T, 2 * T, 5 * T], furSpec('#4a4038', 0));
    }, 'cat.tail'),
  };
  const poses = {
    curled: { body: [[0, 0, 0], [0, 0, 0]], head: [[6.5 * T, 1.2 * T, 2.5 * T], [0, 0.65, 0.22]], paws: [[3 * T, 0, 3.5 * T], [0, 0.3, 0]], tail: [[-6 * T, 0, 3.5 * T], [0, 0, 0]] },
    loaf: { body: [[0, 0, 0], [0, 0, 0]], head: [[6 * T, 4 * T, 0], [0, 1.3, 0]], paws: [[5 * T, 0, -1.75 * T], [0, 0, 0]], tail: [[-6 * T, 0, 3.5 * T], [0, 0, 0]] },
  };
  for (const [k, [p, r]] of Object.entries(poses[pose])) place(parts[k], p, r);
  return assemble('cat', parts);
}

// --- Spaniel: chestnut with a white blaze, bib, muzzle and paws; long feathered ears. Lies in a
// "sphinx" pose with its chin on its front paws, facing +z so the face reads from the camera.
export function spaniel({ coat = '#9a5a32', white = '#e8dfd2', ear = '#6e3a1e', nose = '#2a1a14', pose = 'sleep' } = {}) {
  const C = furSpec(coat, 0, 0.1);
  const Cd = furSpec(ear, 0, 0.12);
  const W = { ...furSpec(white, 0, 0.05), tint: white };
  const asleep = pose === 'sleep';
  const face = { tex: { name: 'face', w: 6, h: 5, fur: coat, blaze: white, eyes: asleep ? 'closed' : 'open', nose: null, eyeRow: 1, eyeGap: 3, eyeColor: '#2a160c' }, tint: '#ffffff', rough: 1, bevel: 0.04 };
  const parts = {
    body: part((b) => {
      b.box([-3.5 * T, 0, -7 * T], [3.5 * T, 5.5 * T, 5 * T], C);
      b.box([-3 * T, 0.5 * T, 4.5 * T], [3 * T, 5 * T, 6 * T], W); // bib
      b.box([-3.6 * T, 5.5 * T, -6 * T], [3.6 * T, 6.3 * T, 3 * T], C); // back ridge
      for (const s of [-1, 1]) {
        const x0 = s < 0 ? -4.6 * T : 2.4 * T;
        b.box([x0, 0, -7 * T], [x0 + 2.2 * T, 4.4 * T, -1.5 * T], C); // haunch
        b.box([x0, 0, -1.5 * T], [x0 + 2.2 * T, 1.4 * T, 1.5 * T], W); // tucked hind paw
        b.box([s < 0 ? -3 * T : 0.8 * T, 0, 5 * T], [s < 0 ? -0.8 * T : 3 * T, 1.6 * T, 10 * T], C); // foreleg
        b.box([s < 0 ? -3 * T : 0.8 * T, 0, 10 * T], [s < 0 ? -0.8 * T : 3 * T, 1.5 * T, 12 * T], W); // front paw
      }
      // Feathered tail curled along the left side.
      b.box([-5.2 * T, 0, -9 * T], [-3.4 * T, 1.8 * T, -5 * T], C);
      b.box([-6.2 * T, 0, -5.5 * T], [-4.4 * T, 1.6 * T, -1 * T], Cd);
    }, 'dog.body'),
    head: part((b) => {
      b.box([-3 * T, 0, -2.5 * T], [3 * T, 5 * T, 2.5 * T], C, { faces: { pz: face } });
      b.box([-0.6 * T, 5 * T, -1.5 * T], [0.6 * T, 5.3 * T, 2.5 * T], W); // blaze over the crown
      b.box([-1.8 * T, 0, 2.5 * T], [1.8 * T, 2.4 * T, 6 * T], W); // muzzle
      b.box([-0.9 * T, 1.6 * T, 6 * T], [0.9 * T, 2.6 * T, 6.6 * T], mat.plain(nose, 0.35));
      for (const s of [-1, 1]) {
        const x0 = s < 0 ? -4 * T : 3 * T;
        b.box([x0, -1.2 * T, -1.5 * T], [x0 + T, 4.6 * T, 1.8 * T], Cd); // long ear
        b.box([x0 + (s < 0 ? -0.3 : 0.3) * T, -1.6 * T, -1.2 * T], [x0 + T + (s < 0 ? -0.3 : 0.3) * T, 0.6 * T, 1.4 * T], Cd); // feathered tip
      }
    }, 'dog.head'),
  };
  const poses = {
    sleep: { body: [[0, 0, 0], [0, 0, 0]], head: [[0, 1.5 * T, 9.3 * T], [0.1, 0.12, 0.08]] },
    alert: { body: [[0, 0, 0], [0, 0, 0]], head: [[0, 4.5 * T, 8.2 * T], [-0.15, -0.2, 0]] },
  };
  for (const [k, [p, r]] of Object.entries(poses[pose])) place(parts[k], p, r);
  return assemble('spaniel', parts);
}

// --- Dachshund in a knitted sweater, curled nose-to-tail. -------------------------------------------
export function dachshund({ coat = '#8a4626', sweater = '#3e6a4a', ear = '#6a321a', pose = 'curled' } = {}) {
  const C = furSpec(coat, 0, 0.08);
  const K = mat.knit(sweater);
  const face = { tex: { name: 'face', w: 5, h: 4, fur: coat, eyes: 'closed', nose: null, eyeRow: 1, eyeGap: 2, eyeColor: '#1e120c' }, tint: '#ffffff', rough: 1 };
  const parts = {
    rear: part((b) => {
      b.box([-5 * T, 0, -3 * T], [3 * T, 5 * T, 3 * T], C);
      b.box([-4 * T, 0, 3 * T], [-1 * T, 1.5 * T, 5 * T], C);
    }, 'dach.rear'),
    front: part((b) => {
      b.box([-3 * T, 0, -3 * T], [5 * T, 5 * T, 3 * T], C);
      b.box([-2.5 * T, 0.5 * T, -3.4 * T], [3.5 * T, 5.4 * T, 3.4 * T], K);
      b.box([3 * T, 0, 2.5 * T], [5 * T, 1.5 * T, 5 * T], C);
    }, 'dach.front'),
    head: part((b) => {
      b.box([-2.5 * T, 0, -2 * T], [2.5 * T, 4 * T, 2 * T], C, { faces: { pz: face } });
      b.box([-1.5 * T, 0, 2 * T], [1.5 * T, 2.5 * T, 6 * T], C);
      b.box([-0.75 * T, 1.5 * T, 6 * T], [0.75 * T, 2.5 * T, 6.5 * T], mat.plain('#1e120c', 0.4));
      b.box([-3.5 * T, -1.5 * T, -1 * T], [-2.5 * T, 3.5 * T, 1.5 * T], furSpec(ear, 0));
      b.box([2.5 * T, -1.5 * T, -1 * T], [3.5 * T, 3.5 * T, 1.5 * T], furSpec(ear, 0));
    }, 'dach.head'),
    tail: part((b) => b.box([-1 * T, 0, 0], [0.5 * T, 1.2 * T, 7 * T], C), 'dach.tail'),
  };
  const poses = {
    curled: {
      rear: [[-4 * T, 0, -1 * T], [0, 0.55, 0]], front: [[4 * T, 0, -1.5 * T], [0, -0.55, 0]],
      head: [[1 * T, 1.5 * T, 3.5 * T], [0, -1.9, 0.12]], tail: [[-8 * T, 0, -1 * T], [0, 0.4, 0]],
    },
  };
  for (const [k, [p, r]] of Object.entries(poses[pose])) place(parts[k], p, r);
  return assemble('dachshund', parts);
}
