// What a render reads from a scene's plate folder (out/plates/<plate>/, written by tools/plate_prep.py and the tools
// after it), and one content hash of it. The render's resume fingerprint (pipeline.mjs) and the picture goldens
// (tests/test_goldens.py) both use it, so they agree on what counts as a change.
//
// Every file counts, subfolders included (fire/ clips, steam/ flipbooks, pet/, petsprite/), except what the checks
// write there after the plate is built, which no layer reads: the outdoor check's tile cache, the weather audit's
// pockets and frames, top-level JPEGs (previews and check images; layers read PNG and JSON at the top level, and
// JPEG frames only inside the clip folders) and files named *preview* or weather_audit*. A check run while a render
// is paused then can't block its resume, and regenerated clips can't slip past it.
//
//   node src/render/inputs.mjs <plate>     -> {"plate", "hash", "files", "bytes"} as JSON (tests/test_goldens.py)
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const CHECK_DIRS = new Set(['outdoor_check', 'audit_pockets', 'audit_frames']);
const isCheckFile = (name) => /\.jpe?g$/i.test(name) || /preview/i.test(name) || /^weather_audit/i.test(name);

// Relative paths (posix, sorted) of the plate folder's render inputs; [] when the folder doesn't exist.
export function plateFiles(root, plate) {
  const dir = path.join(root, 'out', 'plates', plate ?? '');
  if (!plate || !fs.existsSync(dir)) return [];
  const out = [];
  const walk = (d, rel) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (!(rel === '' && CHECK_DIRS.has(e.name))) walk(path.join(d, e.name), r);
      } else if (!(rel === '' && isCheckFile(e.name))) {
        out.push(r);
      }
    }
  };
  walk(dir, '');
  return out.sort();
}

// sha1 over every input's path and bytes, or null when the plate folder doesn't exist.
export function plateHash(root, plate) {
  const dir = path.join(root, 'out', 'plates', plate ?? '');
  if (!plate || !fs.existsSync(dir)) return null;
  const h = crypto.createHash('sha1');
  let bytes = 0;
  const files = plateFiles(root, plate);
  for (const f of files) {
    const b = fs.readFileSync(path.join(dir, f));
    bytes += b.length;
    h.update(`${f}\n${b.length}\n`);
    h.update(b);
  }
  return { hash: h.digest('hex'), files: files.length, bytes };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
  const plate = process.argv[2];
  if (!plate) {
    console.error('usage: node src/render/inputs.mjs <plate>');
    process.exit(2);
  }
  process.stdout.write(`${JSON.stringify({ plate, ...(plateHash(root, plate) ?? { hash: null, files: 0, bytes: 0 }) })}\n`);
}
