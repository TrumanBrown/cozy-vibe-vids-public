"""The spruce cabin's rabbit hops (lessons L166, L190): src/library/timeline/rabbit.js plans each visit and
src/library/rabbit3d.js poses it. A rabbit never glides or goes in a straight line, comes and goes out of sight and
never comes back once gone, hops in bursts with stops between them, acts only while it sits, and every paw on the floor
stays where it was planted through a hop (on the floor exactly, on screen within a few px)."""
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
class RabbitPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rabbit.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_rabbit.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise RuntimeError(f"tests/js_rabbit.mjs failed:\n{r.stderr[-2000:]}")
            cls.data = json.loads(out.read_text(encoding="utf-8"))

    def test_same_seed_same_visit(self):
        self.assertTrue(all(v["same"] for v in self.data["visits"]))

    def test_comes_and_goes_out_of_sight(self):
        for v in self.data["visits"]:
            hops = v["plan"]["hops"]
            self.assertGreater(len(hops), 5, v["seed"])
            self.assertTrue(out_of_frame(hops[0][2], hops[0][3]), f"seed {v['seed']} starts in sight at {hops[0][2:4]}")
            self.assertTrue(v["gone"], f"seed {v['seed']} ends in sight at {hops[-1][4:6]}")

    def test_never_comes_back_once_gone(self):
        for v in self.data["visits"]:
            self.assertEqual(v["back"], [], f"seed {v['seed']}: hops from out of sight at {v['back']} s")

    def test_never_a_straight_line(self):
        for v in self.data["visits"]:
            plain = [h for h in v["plan"]["hops"] if not h[9]]
            for a, b, c in zip(plain, plain[1:], plain[2:]):
                self.assertFalse(abs(b[7] - a[7]) < 1.5 and abs(c[7] - b[7]) < 1.5,
                                 f"seed {v['seed']}: three hops in a row heading {a[7]}, {b[7]}, {c[7]}")

    def test_hops_are_short_and_come_in_bursts(self):
        quick = slow = 0
        for v in self.data["visits"]:
            hops = v["plan"]["hops"]
            for h in hops:
                self.assertLess(h[1], 0.5, f"seed {v['seed']}: a hop of {h[1]} s")
                self.assertLess(h[8], 0.4, f"seed {v['seed']}: a hop {h[8]} body lengths high")
                self.assertLess(h[10], 1.6, f"seed {v['seed']}: a hop {h[10]} body lengths long")
            gaps = [b[0] - (a[0] + a[1]) for a, b in zip(hops, hops[1:])]
            self.assertTrue(all(g >= -1e-3 for g in gaps), f"seed {v['seed']}: hops overlap")
            quick += sum(g < 0.5 for g in gaps)
            slow += sum(g > 1.1 for g in gaps)
        # bursts of hops a moment apart, and stops between them
        self.assertGreater(quick, slow, "no bursts: hops never follow each other quickly")
        self.assertGreater(slow, 0, "no stops between bursts")
        self.assertTrue(any(h[9] for v in self.data["visits"] for h in v["plan"]["hops"]), "no turning hops at all")

    def test_fits_its_time_and_acts_only_while_it_sits(self):
        kinds = set()
        for v in self.data["visits"]:
            p = v["plan"]
            self.assertLessEqual(p["dur"], v["durMax"] + 1.0, f"seed {v['seed']}: {p['dur']} s for a {v['durMax']} s slot")
            for a0, ad, kind, side in p["acts"]:
                kinds.add(kind)
                self.assertIn(side, (-1, 1))
                self.assertFalse(any(h[0] - 0.05 < a0 + ad and a0 < h[0] + h[1] + 0.05 for h in p["hops"]),
                                 f"seed {v['seed']}: a {kind} at {a0} s overlaps a hop")
        self.assertEqual(kinds, {"groom", "up", "look", "sniff"})

    def test_planted_paws_never_slide(self):
        s = self.data["slide"]
        self.assertLess(max(s["front"], s["hind"]), 1e-6, f"a planted paw moves on the floor: {s['worst']}")
        self.assertLess(s["px"], 6.0, f"a planted paw slides {s['px']:.1f} px on screen: {s['worstPx']}")

    def test_critic_sees_the_arrival_and_the_last_hop_in_frame(self):
        """critic.py hopper_moments: a visit starts and ends out of sight, so its arrival and last-hop crops come from the
        first hop that lands in the frame and the last that starts in it (v2's crop at the end of the first hop was floor)."""
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import critic
        for v in self.data["visits"]:
            e = {**v["plan"], "t": 10.0, "type": "rabbit"}
            rows = critic.hopper_moments(e, 0.0, 1e6, None)
            when = {name: t for name, t, _ in rows[1]}
            for name in ("arriving", "last hop"):
                with self.subTest(seed=v["seed"], moment=name):
                    (x, y), _ = critic.hop_at(e, when[name] - 10.0)
                    self.assertFalse(out_of_frame(x, y), f"seed {v['seed']}: the {name} crop is at {x:.3f}, {y:.3f}")

    def test_critic_sees_it_in_its_strongest_light(self):
        """Given the plate's light, the critic also crops the sit where the floor is brightest (v3 glowed in the fire's
        pool of light, which no other crop showed)."""
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import critic
        for v in self.data["visits"]:
            e = {**v["plan"], "t": 10.0, "type": "rabbit"}
            light = lambda x, y: -abs(x - 0.3)
            rows = critic.hopper_moments(e, 0.0, 1e6, None, light=light)
            when = {name: t for name, t, _ in rows[1]}
            with self.subTest(seed=v["seed"]):
                self.assertIn("in its brightest light", when)
                (x, y), hop = critic.hop_at(e, when["in its brightest light"] - 10.0)
                self.assertIsNone(hop, "it should be sitting")
                inside = lambda p: 0.04 < p[0] < 0.96 and p[1] < 0.96
                sits = [critic.hop_at(e, k * 0.5)[0][0] for k in range(int(e["dur"] * 2)) if critic.hop_at(e, k * 0.5)[1] is None
                        and inside(critic.hop_at(e, k * 0.5)[0])]
                self.assertAlmostEqual(abs(x - 0.3), min(abs(s - 0.3) for s in sits), places=6)


if __name__ == "__main__":
    unittest.main()
