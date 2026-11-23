r"""The Enchanter's Tower's movers (src/library/enchant.js, aquarium.js, ghast.js): free, offline, a few seconds.

  .venv\Scripts\python -m unittest discover -s tests -p test_enchanter.py -v

Movers asked for on the Enchanter's Tower (2026-11-22): the enchanting table's book floating and turning its pages, a
wall tank with blocky fish and an axolotl, and a happy ghast drifting past the window. Each is a pure function of time
over the 20 minute loop. These hold them to what was looked at: nothing jumps between two frames (a page that snapped
back to its stack after turning, an axolotl that turned on the spot as it settled), the loop joins (the 10 h video is
the window played back to back), the fish stay in their tank, and the ghast comes once a loop, early, from behind the
window's walls, hovers to look in, and is cropped by the critic where it really is.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "scenes" / "enchanter-tower-goldenhour" / "scene.json"
sys.path.insert(0, str(ROOT / "tools"))


@unittest.skipUnless(NODE and SCENE.exists(), "node isn't on PATH, or the scene is gone")
class EnchanterTower(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "enchanter.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_enchanter.mjs"), str(SCENE), str(out)], cwd=ROOT,
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(f"tests/js_enchanter.mjs failed:\n{r.stderr[-2000:]}")
            cls.js = json.loads(out.read_text(encoding="utf-8"))

    def test_book_pages_never_jump(self):
        b = self.js["book"]
        self.assertEqual(b["missing"], 0, "a loose page went missing from the book")
        # a turn takes 0.62 s through pi minus twice the covers' fold: at most ~0.27 rad a frame at its fastest
        self.assertLess(b["worstPsi"], 0.3, f"a page turned {b['worstPsi']:.2f} rad in one frame: it snapped")
        self.assertLess(b["worstLift"], 0.05, f"a page moved {b['worstLift']:.3f} units off its stack in one frame")

    def test_book_loop_joins(self):
        b = self.js["book"]
        self.assertEqual(b["forward"], b["back"], "as many turns back as forward, or the pages end the loop elsewhere")
        self.assertGreater(b["first"], 1.0)
        self.assertLess(b["last"], 1200 - 4, "a page still turning at the loop's end")
        self.assertLess(b["join"], 1e-6, f"the book jumps {b['join']:.3g} at the loop's join")
        self.assertGreater(b["flips"], 100, "pages turn every few seconds")

    def test_fish_swim_smoothly_inside_the_tank(self):
        for i, f in enumerate(self.js["fish"]):
            with self.subTest(fish=i):
                self.assertLess(f["worstMove"], 6.0, f"moved {f['worstMove']:.1f} px in one frame")
                self.assertLess(f["worstTurn"], 0.2, f"turned {f['worstTurn']:.2f} rad in one frame")
                self.assertGreaterEqual(f["lo"][0], 0.03)
                self.assertLessEqual(f["hi"][0], 0.97)
                self.assertGreaterEqual(f["lo"][2], 0.0)
                self.assertLessEqual(f["hi"][2], 1.0)
                self.assertGreater(f["minClear"], 0.05, "a fish swam into the sand")
                self.assertLess(f["join"], 0.01, f"a fish jumps {f['join']:.2f} px at the loop's join")

    def test_axolotl_rests_and_swims_without_jumps(self):
        a = self.js["axolotl"]
        self.assertLess(a["worstMove"], 6.0, f"moved {a['worstMove']:.1f} px in one frame")
        self.assertLess(a["worstTurn"], 0.12, f"turned {a['worstTurn']:.2f} rad in one frame: it spun on the spot")
        self.assertLess(a["join"], 1.0)
        self.assertLess(a["joinTurn"], 0.05)
        self.assertTrue(0.05 < a["swimming"] < 0.4, f"it should rest most of the time and swim now and then ({a['swimming']:.0%})")

    def test_ghast_drifts_hovers_and_turns_smoothly(self):
        g = self.js["ghast"]
        ev, fr = g["ev"], g["frames"]
        worst = max(((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5 for a, b in zip(fr, fr[1:]))
        self.assertLess(worst, 3.0, f"moved {worst:.1f} px in one frame")
        turn = max(abs(b["yaw"] - a["yaw"]) for a, b in zip(fr, fr[1:]))
        self.assertLess(turn, 0.05, f"turned {turn:.2f} rad in one frame")
        hover = [f for f in fr if f["speed"] == 0]
        self.assertGreater(len(hover), 30 * (ev["hold"] - 0.1), "it should hover a few seconds")
        self.assertTrue(all(f["look"] > 0.9 for f in hover[len(hover) // 4: 3 * len(hover) // 4]), "it should face the tower while it hovers")
        # its ends are behind the window's walls (the opening runs from x 1430 to 2489 at 4K below the arch's steps)
        self.assertLess(fr[0]["x"] + 0.5 * ev["span"], 1430)
        self.assertGreater(fr[-1]["x"] - 0.5 * ev["span"], 2489) if ev["x1"] > ev["x0"] else self.assertLess(fr[-1]["x"] + 0.5 * ev["span"], 1430)

    def test_one_ghast_a_loop_early_in_it(self):
        ps = [p for p in self.js["ghast"]["passes"] if 0 <= p["t"] < 36000]
        self.assertEqual(len(ps), 30)
        for p in ps:
            self.assertLess(p["t"] % 1200, 120, "early in the loop: the opening shows it")
            self.assertTrue(6 <= p["hold"] <= 10 and 80 <= p["dur"] <= 100)

    def test_critic_crops_the_ghast_where_it_is(self):
        import critic
        ev, fr = self.js["ghast"]["ev"], self.js["ghast"]["frames"]
        bob = 1.25 * ev["span"] / 16 / 2160
        for f in fr[::15]:
            x, y = critic.ghast_xy(ev, f["tau"])
            self.assertAlmostEqual(x, f["x"] / 3840, places=4)
            self.assertLess(abs(y - f["y"] / 2160), bob, "the critic's copy of ghastAt drifted from the real one")


if __name__ == "__main__":
    unittest.main()
