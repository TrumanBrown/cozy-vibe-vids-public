r"""Flipbook frames (fire clips, pet clips, steam) are never closed while a render frame still uses them: overlay.js
frameCache keeps the most recently used, where each layer's own first-in-first-out cache could close a frame the same
render frame had just been handed when it was the oldest. Its upload then failed ("texSubImage2D: The source data has
been detached") and the texture kept the frame before; the Spruce Clock Cabin's sample (2026-11-06) failed render QA
on it. Free, offline, a second.

  .venv\Scripts\python -m unittest discover -s tests -p test_frame_cache.py -v
"""
import json
import subprocess
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, "node isn't on PATH")
class FrameCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(ROOT / "tests" / "js_frame_cache.mjs")], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"tests/js_frame_cache.mjs failed:\n{r.stderr[-2000:]}")
        cls.js = json.loads(r.stdout)

    def test_oldest_frame_asked_for_again_stays_open(self):
        o = self.js["oldest_reused"]
        self.assertFalse(o["lru"]["a_closed"])
        self.assertEqual(o["lru"]["closed"], ["b"])
        self.assertTrue(o["fifo"]["a_closed"], "the old cache no longer shows the failure, so this test can't see it either")

    def test_fire_walk(self):
        w = self.js["walk"]
        self.assertGreater(w["fifo"]["in_use_closed"], 0, "the walk no longer reaches the case the old cache failed")
        for k in ("lru", "lru_small"):
            with self.subTest(cache=k):
                self.assertEqual(w[k]["in_use_closed"], 0)
                self.assertGreater(w[k]["closed"], w[k]["frames"] // 2, "frames that fall out are closed")

    def test_layers_use_it(self):
        for f in ("fire.js", "pet.js", "steam.js"):
            with self.subTest(layer=f):
                src = (ROOT / "src" / "library" / f).read_text(encoding="utf-8")
                self.assertIn("frameCache(", src)
                self.assertNotIn(".close?.()", src, f"{f} closes bitmaps itself again")


if __name__ == "__main__":
    unittest.main()
