r"""Render-code safety net (TASKS.md T1): free, offline, about 10 s. Runs with the tools' checks:

  .venv\Scripts\python -m unittest discover -s tests -v

1. Every module in src/engine and src/library and every scene imports in Node, outside the renderer, and every name
   reached through a dynamic import (autoscene's layers, the CLI's helpers) exists, so a moved or renamed export
   can't break a scene unnoticed.
2. Every scene's seeded event timeline (`node src/cli.mjs timeline`, the scene's own seed and length) comes out the same
   in two runs and matches tests/goldens/timelines.json. A golden is keyed by the timeline's inputs (the scene's
   scene.js and scene.json, the scenes it imports, its local plate.json), so a scene or plate that changed is skipped
   and never blamed on the code. Same inputs and a different timeline means the code changed what it schedules, or a
   Node upgrade changed the math: either way a video could no longer be rebuilt identically.

Record the goldens on code you trust, before a refactor and after a deliberate change to the timeline:

  $env:UPDATE_GOLDENS = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_scenes.py; Remove-Item Env:UPDATE_GOLDENS
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDENS = Path(__file__).resolve().parent / "goldens" / "timelines.json"
NODE = shutil.which("node")
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"
IMPORTS_SCENE = re.compile(r"""from\s+['"]\.\./([\w.-]+)/scene\.js['"]""")


def scene_inputs(name, plate):
    """Hash of what a scene's timeline is made from besides the code. Line endings are normalized, so a checkout
    with CRLF (Windows) and one with LF (WSL) agree."""
    h, seen = hashlib.sha256(), set()

    def add(scene):
        if scene in seen:
            return
        seen.add(scene)
        for f in ("scene.js", "scene.json"):
            p = ROOT / "scenes" / scene / f
            if p.exists():
                h.update(f"{scene}/{f}\n".encode() + p.read_bytes().replace(b"\r\n", b"\n"))
                if f == "scene.js":
                    for dep in IMPORTS_SCENE.findall(p.read_text(encoding="utf-8-sig")):
                        add(dep)

    add(name)
    pj = ROOT / "out" / "plates" / plate / "plate.json" if plate else None
    h.update(b"plate.json\n" + (pj.read_bytes().replace(b"\r\n", b"\n") if pj and pj.exists() else b"none"))
    return h.hexdigest()[:16]


@unittest.skipUnless(NODE, "node isn't on PATH")
class RenderCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name) / "imports.json"
        r = subprocess.run([NODE, str(ROOT / "tests" / "js_scenes.mjs"), str(out)], cwd=ROOT, capture_output=True,
                           text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"tests/js_scenes.mjs failed:\n{r.stderr[-2000:]}")
        cls.js = json.loads(out.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_modules_import(self):
        self.assertGreater(len(self.js["modules"]), 30)
        for rel, err in self.js["modules"].items():
            with self.subTest(module=rel):
                self.assertIsNone(err, err)

    def test_scenes_import(self):
        self.assertGreater(len(self.js["scenes"]), 5)
        for name, s in self.js["scenes"].items():
            with self.subTest(scene=name):
                self.assertIsNone(s["error"], s["error"])

    def test_dynamic_imports_resolve(self):
        self.assertGreater(len(self.js["dynamic"]), 15, "the dynamic-import scan found almost nothing")
        for ref, err in self.js["dynamic"].items():
            with self.subTest(ref=ref):
                self.assertIsNone(err, f"{ref}: {err}")

    def timeline(self, name, run):
        out = Path(self.tmp.name) / f"{name}_{run}.json"
        r = subprocess.run([NODE, "src/cli.mjs", "timeline", f"scenes/{name}", "--out", str(out)], cwd=ROOT,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return out.read_bytes()

    def test_timelines(self):
        goldens = json.loads(GOLDENS.read_text(encoding="utf-8")) if GOLDENS.exists() else {}
        fresh = {}
        for name, s in sorted(self.js["scenes"].items()):
            if s["error"]:
                continue
            with self.subTest(scene=name):
                first, second = self.timeline(name, 1), self.timeline(name, 2)
                self.assertEqual(first, second, "two runs differ: something reads the clock or an unseeded random")
                rec = {"inputs": scene_inputs(name, s["plate"]), "timeline": hashlib.sha256(first).hexdigest()[:16],
                       "events": len(json.loads(first)["events"])}
                fresh[name] = rec
                if UPDATE:
                    continue
                g = goldens.get(name)
                if g is None:
                    self.skipTest(f"{name}: no golden yet (record with UPDATE_GOLDENS=1)")
                if g["inputs"] != rec["inputs"]:
                    self.skipTest(f"{name}: its scene or plate changed since the golden was recorded "
                                  "(record again on code you trust, UPDATE_GOLDENS=1)")
                self.assertEqual(rec["timeline"], g["timeline"],
                                 f"{name}: same inputs, different timeline ({g['events']} events then, "
                                 f"{rec['events']} now): the code changed what it schedules")
        if UPDATE:
            GOLDENS.parent.mkdir(parents=True, exist_ok=True)
            GOLDENS.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
