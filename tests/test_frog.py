"""The jungle temple's frog hops (lessons L166): src/library/timeline/frog.js plans each visit, and a frog never
glides or goes in a straight line, comes and goes out of sight, and fits the time the timeline gives it."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]


def out_of_frame(x, y):
    return x < 0 or x > 1 or y > 1


@unittest.skipUnless(NODE, "node isn't on PATH")
class FrogPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "frog.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_frog.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise RuntimeError(f"tests/js_frog.mjs failed:\n{r.stderr[-2000:]}")
            cls.data = json.loads(out.read_text(encoding="utf-8"))

    def test_same_seed_same_visit(self):
        self.assertTrue(all(v["same"] for v in self.data["visits"]))

    def test_comes_and_goes_out_of_sight(self):
        for v in self.data["visits"]:
            hops = v["plan"]["hops"]
            self.assertGreater(len(hops), 3, v["seed"])
            self.assertTrue(out_of_frame(hops[0][2], hops[0][3]), f"seed {v['seed']} starts in sight at {hops[0][2:4]}")
            self.assertTrue(v["gone"], f"seed {v['seed']} ends in sight at {hops[-1][4:6]}")

    def test_never_comes_back_once_gone(self):
        # once out of sight on its way out it hops no more: a last little hop raised its eyes back over the frame's
        # bottom edge (the jungle temple's 10 h window)
        for v in self.data["visits"]:
            self.assertEqual(v["back"], [], f"seed {v['seed']}: hops from out of sight at {v['back']} s")

    def test_never_a_straight_line(self):
        # a hop's heading wanders off the straight way: never three plain hops in a row on one heading
        for v in self.data["visits"]:
            plain = [h for h in v["plan"]["hops"] if not h[9]]
            for a, b, c in zip(plain, plain[1:], plain[2:]):
                self.assertFalse(abs(b[7] - a[7]) < 1.5 and abs(c[7] - b[7]) < 1.5,
                                 f"seed {v['seed']}: three hops in a row heading {a[7]}, {b[7]}, {c[7]}")

    def test_hops_are_short_and_take_turns(self):
        for v in self.data["visits"]:
            hops = v["plan"]["hops"]
            for h in hops:
                self.assertLess(h[1], 0.5, f"seed {v['seed']}: a hop of {h[1]} s")
                self.assertLess(h[8], 0.65, f"seed {v['seed']}: a hop {h[8]} body lengths high")
            t_end = [h[0] + h[1] for h in hops]
            self.assertTrue(all(b[0] >= e - 1e-3 for e, b in zip(t_end, hops[1:])), f"seed {v['seed']}: hops overlap")
        self.assertTrue(any(h[9] for v in self.data["visits"] for h in v["plan"]["hops"]), "no turning hops at all")

    def test_fits_its_time_and_croaks_while_it_sits(self):
        for v in self.data["visits"]:
            p = v["plan"]
            self.assertLessEqual(p["dur"], v["durMax"] + 1.0, f"seed {v['seed']}: {p['dur']} s for a {v['durMax']} s slot")
            for c in p["croaks"]:
                self.assertFalse(any(h[0] - 0.05 < c < h[0] + h[1] + 0.05 for h in p["hops"]), f"seed {v['seed']}: a croak mid-hop at {c}")


if __name__ == "__main__":
    unittest.main()
