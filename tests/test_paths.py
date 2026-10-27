"""tools/cozy/paths.py (TASKS.md T10): the one scene.json format, writes that never leave half a file, config read
fresh. Free, offline, under a second. Its scratch folder is cache/test_paths/ (gitignored), removed after.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_paths.py -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cozy.paths as P  # noqa: E402


class Paths(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "cache" / "test_paths"
        shutil.rmtree(self.root, ignore_errors=True)
        (self.root / "scenes" / "s").mkdir(parents=True)
        (self.root / "config").mkdir()
        self.patch = mock.patch.object(P, "ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_root_and_folders(self):
        self.patch.stop()
        try:
            self.assertEqual(P.ROOT, ROOT)
            self.assertTrue(Path(P.PY).exists(), P.PY)
            self.assertEqual(P.scene_dir("a"), ROOT / "scenes" / "a")
            self.assertEqual(P.plate_dir("a"), ROOT / "out" / "plates" / "a")
            self.assertEqual(P.keyart_dir(), ROOT / "assets" / "keyart")
            self.assertEqual(P.out_dir("a"), ROOT / "out" / "a")
        finally:
            self.patch.start()

    def test_scene_json_format(self):
        spec = {"title": "Café ☔", "layers": [{"type": "rain", "z": 1.5}], "events": {}}
        p = P.save_scene("s", spec)
        self.assertEqual(p, self.root / "scenes" / "s" / "scene.json")
        raw = p.read_bytes()
        self.assertEqual(raw, (json.dumps(spec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(P.load_scene("s"), spec)
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["scene.json"], "a temp file was left behind")

    def test_failed_write_keeps_the_old_file(self):
        p = P.save_scene("s", {"seed": 1})
        before = p.read_bytes()
        with mock.patch.object(P.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                P.save_scene("s", {"seed": 2})
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["scene.json"], "a temp file was left behind")

    def test_config_is_read_fresh(self):
        c = self.root / "config" / "x.json"
        c.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 1})
        c.write_text('{"a": 2}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 2})


if __name__ == "__main__":
    unittest.main()
