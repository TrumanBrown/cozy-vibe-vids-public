r"""A dragon far off (src/library/dragon.js, the timeline's 'dragon' events): free, offline, a few seconds.

  .venv\Scripts\python -m unittest discover -s tests -p test_dragon.py -v

Truman's ideas round on the Sleeping Hound Inn (2026-11-15): in Skyrim dragons fly over at random. Its silhouette is a 3D
pose built in code every frame (bat wings with a beating dihedral, seen a little from below, an S-necked horned head, a
swaying tail). These hold it to what was looked at: nothing of it reaches past the box it is drawn in (a clipped wing tip
would show as a straight cut), the wings really beat in bouts with glides between, no part of it jumps between frames,
and the timeline gives one pass per 20 minute loop, early in it.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, "node isn't on PATH")
class Dragon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dragon.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_dragon.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"tests/js_dragon.mjs failed:\n{r.stderr[-2000:]}")
            cls.js = json.loads(out.read_text(encoding="utf-8"))

    def test_nothing_reaches_past_its_box(self):
        worst = max(f["reach"] for f in self.js["frames"])
        self.assertLess(worst, 0.97, f"a part reaches {worst:.2f} of the drawing box: it would be cut straight")

    def test_it_glides_and_beats_in_bouts(self):
        fl = [f["flap"] for f in self.js["frames"]]
        flapping = sum(1 for v in fl if v > 0.5) / len(fl)
        self.assertGreater(flapping, 0.2, "it should beat its wings now and then")
        self.assertLess(flapping, 0.7, "a big dragon mostly glides")
        # the far wing's tip swings in a beat: its height over the body changes by a good part of the wingspan
        tips = [f["y"] - min(p[1] for p in f["far"]) for f in self.js["frames"] if f["flap"] > 0.9]
        self.assertGreater(max(tips) - min(tips), 0.25 * 160)

    def test_no_part_jumps_between_frames(self):
        fr = self.js["frames"]
        worst = 0.0
        for a, b in zip(fr, fr[1:]):
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            for pa, pb in zip(a["near"] + a["far"], b["near"] + b["far"]):
                worst = max(worst, ((pb[0] - pa[0] - dx) ** 2 + (pb[1] - pa[1] - dy) ** 2) ** 0.5)
        self.assertLess(worst, 6.0, f"a wing point moved {worst:.1f} px in one frame against the body")

    def test_one_pass_per_loop_early_in_it(self):
        ev = [e for e in self.js["events"] if 0 <= e["t"] < 36000]
        self.assertEqual(len(ev), 30)
        for e in ev:
            self.assertLess(e["t"] % 1200, 120, "early in the loop: the opening shows it")
            self.assertTrue(30 <= e["dur"] <= 40 and 140 <= e["span"] <= 175)
            self.assertEqual(sorted([e["x0"], e["x1"]]), [-0.08, 1.08])


if __name__ == "__main__":
    unittest.main()
