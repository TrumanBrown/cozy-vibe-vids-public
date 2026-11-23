"""What decides whether a render or a cached file is still good (TASKS.md T9). Free, offline, a few seconds.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_inputs.py -v

- The plate hash (src/render/inputs.mjs) sees every render input, clips in subfolders included, and none of what the
  checks write into the plate folder later.
- A render's fingerprint covers its own scene and the scenes it imports, not the others.
- A tool's code hash (tools/cozy/code.py) follows its imports, even those inside functions.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
NODE = shutil.which("node")


def node_json(script):
    r = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't on PATH")
class PlateHash(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        p = self.root / "out" / "plates" / "p"
        for f, data in {"plate.json": b"{}", "masks.png": b"m", "steam/cup/s_0000.jpg": b"s0", "fire/fire.json": b"{}",
                        "outdoor_check/tile_00.jpg": b"t", "audit_pockets/x.png": b"a", "regions_preview.png": b"r",
                        "clean_preview.jpg": b"c", "weather_audit_full.png": b"w", "mask_edges.jpg": b"e"}.items():
            (p / f).parent.mkdir(parents=True, exist_ok=True)
            (p / f).write_bytes(data)
        self.plate = p

    def tearDown(self):
        self.tmp.cleanup()

    def info(self):
        root = self.root.as_posix()
        return node_json("import { plateHash, plateFiles } from './src/render/inputs.mjs';"
                         f"console.log(JSON.stringify({{ h: plateHash('{root}', 'p'), files: plateFiles('{root}', 'p'), none: plateHash('{root}', 'nope') }}));")

    def test_inputs_and_check_outputs(self):
        first = self.info()
        self.assertEqual(first["files"], ["fire/fire.json", "masks.png", "plate.json", "steam/cup/s_0000.jpg"])
        self.assertIsNone(first["none"])
        for f in ("outdoor_check/tile_00.jpg", "audit_pockets/x.png", "regions_preview.png", "clean_preview.jpg",
                  "weather_audit_full.png", "mask_edges.jpg"):
            (self.plate / f).write_bytes(b"rewritten by a check")
        self.assertEqual(self.info()["h"]["hash"], first["h"]["hash"], "a check's output changed the plate hash")
        (self.plate / "steam/cup/s_0000.jpg").write_bytes(b"s0 regenerated")
        self.assertNotEqual(self.info()["h"]["hash"], first["h"]["hash"], "a regenerated steam frame didn't change it")

    def test_a_scene_and_the_scenes_it_imports(self):
        got = node_json("import { sceneClosure } from './src/render/pipeline.mjs';"
                        f"console.log(JSON.stringify(['catmock-treetop', 'leaf-campfire-rain'].map((s) => [...sceneClosure('{ROOT.as_posix()}', s)].sort())));")
        self.assertEqual(got, [["catmock-treetop", "treetop-plate"], ["leaf-campfire-rain"]])


class CodeHash(unittest.TestCase):
    def setUp(self):
        import cozy.code as C
        self.C = C
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "cozy").mkdir()
        (t / "cozy" / "__init__.py").write_text("")
        (t / "cozy" / "util.py").write_text("X = 1\n")
        (t / "a.py").write_text("import json\n\n\ndef f():\n    from b import g\n    return g()\n")
        (t / "b.py").write_text("from cozy.util import X\n\n\ndef g():\n    return X\n")
        (t / "c.py").write_text("Y = 2\n")
        self.t = t
        self.old = C.TOOLS
        C.TOOLS = t
        C._direct.cache_clear()

    def tearDown(self):
        self.C.TOOLS = self.old
        self.C._direct.cache_clear()
        self.tmp.cleanup()

    def test_follows_imports_inside_functions(self):
        names = [p.relative_to(self.t).as_posix() for p in self.C.code_files("a")]
        self.assertEqual(names, ["a.py", "b.py", "cozy/__init__.py", "cozy/util.py"])
        h = self.C.code_hash("a")
        (self.t / "c.py").write_text("Y = 3\n")
        self.assertEqual(self.C.code_hash("a"), h, "a module a.py doesn't import changed its hash")
        (self.t / "cozy" / "util.py").write_text("X = 2\n")
        self.C._direct.cache_clear()
        self.assertNotEqual(self.C.code_hash("a"), h, "an edit two imports away didn't change the hash")

    def test_the_real_audio_closure(self):
        self.C.TOOLS = self.old
        self.C._direct.cache_clear()
        names = {p.name for p in self.C.code_files("audio")}
        self.assertTrue({"audio.py", "audio_analyze.py", "music.py"} <= names, names)

    def test_packages_and_relative_imports(self):
        """`from cozy.pkg import sub` brings in the module and the package's __init__.py, and a relative import
        inside the package is followed (tools/cozy/audio is such a package)."""
        pkg = self.t / "cozy" / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('"""a package"""\n')
        (pkg / "sub.py").write_text("from .helper import H\n")
        (pkg / "helper.py").write_text("H = 1\n")
        (self.t / "d.py").write_text("from cozy.pkg import sub\n")
        names = [p.relative_to(self.t).as_posix() for p in self.C.code_files("d")]
        self.assertEqual(names, ["cozy/__init__.py", "cozy/pkg/__init__.py", "cozy/pkg/helper.py", "cozy/pkg/sub.py", "d.py"])


if __name__ == "__main__":
    unittest.main()
