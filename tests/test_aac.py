"""Every AAC encode of something someone hears goes without perceptual noise substitution (cozy.media aac(), the
pipeline's AAC): with it ffmpeg's decoder fills noisy bands from a random generator that runs on from the file's
start, and the spruce cabin's 40 minute ambience came out with 9 clicks up to +1.1 dBTP where the source peaks at
-2.3 dBTP (2026-11-06). Free, offline, instant.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_aac.py -v
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.media import aac  # noqa: E402

ENCODE = re.compile(r"""["']-c:a["']\s*,\s*["']aac["']""")


class Aac(unittest.TestCase):
    def test_the_shared_options_turn_pns_off(self):
        a = aac("384k")
        self.assertEqual(a[:2], ["-c:a", "aac"])
        self.assertEqual(a[a.index("-aac_pns") + 1], "0")
        self.assertEqual(a[a.index("-b:a") + 1], "384k")
        js = (ROOT / "src" / "render" / "pipeline.mjs").read_text(encoding="utf-8")
        self.assertIn("export const AAC = ['-c:a', 'aac', '-aac_pns', '0'];", js)

    def test_no_encode_spells_it_out_again(self):
        found = []
        for p in list((ROOT / "tools").rglob("*.py")) + list((ROOT / "src").rglob("*.mjs")) + list((ROOT / "src").rglob("*.js")):
            text = p.read_text(encoding="utf-8", errors="replace")
            for m in ENCODE.finditer(text):
                if p.name in ("media.py", "pipeline.mjs") and "aac_pns" in text[m.start(): m.start() + 80]:
                    continue
                found.append(f"{p.relative_to(ROOT)}:{text[: m.start()].count(chr(10)) + 1}")
        self.assertEqual(found, [], "AAC encodes that don't use cozy.media aac() or the pipeline's AAC")


if __name__ == "__main__":
    unittest.main()
