// Imports every module in src/engine and src/library, subfolders included, and every scene outside the renderer, looks
// up every name that src/ reaches through a dynamic import, and writes what happened as JSON to the file given as the
// first argument (stdout stays free for anything a module prints):
//   {"modules": {"src/library/rain.js": null | "<error>"}, "scenes": {"<scene>": {"plate": "<plate>" | null, "error": null | "<error>"}},
//    "dynamic": {"src/cli.mjs:81 ./library/timeline.js buildTimeline": null | "<error>",
//                "src/library/autoscene.js LAYERS.leaves ./leaves.js leavesLayer": null | "<error>"}}
// Used by tests/test_scenes.py (TASKS.md T1).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const brief = (e) => String(e?.stack ?? e).split('\n').slice(0, 3).join(' | ');
const out = { modules: {}, scenes: {} };
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));

for (const dir of ['src/engine', 'src/library']) {
  for (const rel of walk(path.join(root, dir)).filter((x) => x.endsWith('.js')).map((f) => path.relative(root, f).split(path.sep).join('/')).sort()) {
    try {
      await import(pathToFileURL(path.join(root, rel)).href);
      out.modules[rel] = null;
    } catch (e) {
      out.modules[rel] = brief(e);
    }
  }
}

for (const name of fs.readdirSync(path.join(root, 'scenes')).sort()) {
  const file = path.join(root, 'scenes', name, 'scene.js');
  if (!fs.existsSync(file)) continue;
  try {
    const { default: S } = await import(pathToFileURL(file).href);
    out.scenes[name] = { plate: S?.plate ?? null, error: null };
  } catch (e) {
    out.scenes[name] = { plate: null, error: brief(e) };
  }
}

// A name reached through a dynamic import (autoscene's layers, the CLI's helpers) fails only when a scene uses it,
// not when the module loads, so each one is looked up here.
out.dynamic = {};
for (const file of walk(path.join(root, 'src')).filter((f) => /\.m?js$/.test(f)).sort()) {
  const src = fs.readFileSync(file, 'utf8');
  const rel = path.relative(root, file).split(path.sep).join('/');
  const refs = [
    ...[...src.matchAll(/\(await import\('(\.[^']+)'\)\)\.(\w+)/g)].map((m) => [m.index, m[1], [m[2]]]),
    ...[...src.matchAll(/const \{([^}]+)\} = await import\('(\.[^']+)'\)/g)].map((m) => [m.index, m[2], m[1].split(',').map((s) => s.split(':')[0].trim()).filter(Boolean)]),
  ];
  for (const [at, spec, names] of refs) {
    const line = src.slice(0, at).split('\n').length;
    let mod = null, err = null;
    try {
      mod = await import(pathToFileURL(path.resolve(path.dirname(file), spec)).href);
    } catch (e) {
      err = brief(e);
    }
    for (const n of names) out.dynamic[`${rel}:${line} ${spec} ${n}`] = err ?? (n in mod ? null : 'not exported');
  }
}
// autoscene.js picks a layer's function by type from its LAYERS registry, most of them loaded from their module only
// when a scene uses them: each one is looked up the way a scene would.
try {
  const { LAYERS } = await import(pathToFileURL(path.join(root, 'src/library/autoscene.js')).href);
  for (const [type, R] of Object.entries(LAYERS)) {
    const key = `src/library/autoscene.js LAYERS.${type} ${R.module ?? '(imported)'} ${R.name ?? R.fn?.name}`;
    try {
      const fn = R.fn ?? (await import(pathToFileURL(path.join(root, 'src/library', R.module)).href))[R.name];
      out.dynamic[key] = typeof fn === 'function' ? null : 'not exported';
    } catch (e) {
      out.dynamic[key] = brief(e);
    }
  }
} catch (e) {
  out.dynamic['src/library/autoscene.js LAYERS'] = brief(e);
}

fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
