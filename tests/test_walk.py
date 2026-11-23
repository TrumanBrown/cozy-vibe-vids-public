r"""A creature on legs walks (the tide pool's hermit crab, 2026-11-05: it glided along a near-straight line at one pace and
came into view under the decorator crab's raised body): free, offline, a few seconds.

  .venv\Scripts\python -m unittest discover -s tests -p test_walk.py -v

The timeline gives a walker short bursts with stops between them (timeline/ambient.js walkStops), critters.js walks it
through them with eased starts and stops and a step that lifts and rocks it (gaitFor, walkPose), the critic crops it where
it really is (critic.critter_progress), and review fails a walker drawn as a glider (L182) or hidden in water it doesn't
live in.
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


def probe():
    r = subprocess.run([NODE, str(ROOT / "tests" / "js_walk_surf.mjs")], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(f"tests/js_walk_surf.mjs failed:\n{r.stderr[-2000:]}")
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't on PATH")
class Walk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = probe()

    def test_stops_are_ordered_and_leave_most_of_the_visit_walking(self):
        for st in self.p["stops"]:
            self.assertTrue(st)
            ends = 0.0
            for at, ln in st:
                self.assertGreater(at, ends - 1e-9, "stops overlap or run backwards")
                self.assertGreater(ln, 0)
                ends = at + ln
            self.assertLess(ends, 1.0, "the last stop runs past the visit: it must walk out of sight")
            self.assertLessEqual(sum(ln for _, ln in st), 0.55 + 1e-3)
        self.assertTrue(4 <= len(self.p["stops"][0]) <= 7)
        self.assertEqual(self.p["stops"][0], self.p["stops"][1], "the same seed walks the same way")
        self.assertNotEqual(self.p["stops"][0], self.p["stops"][3])

    def test_it_stands_still_in_a_stop_and_eases_into_each_burst(self):
        prog, taus, ev = self.p["progress"], self.p["taus"], self.p["ev"]
        self.assertEqual(prog[0], 0)
        self.assertAlmostEqual(prog[-1], 1.0, places=6)
        self.assertTrue(all(b >= a - 1e-12 for a, b in zip(prog, prog[1:])), "it walks backwards")
        T = ev["dur"]
        for at, ln in ev["stops"]:
            inside = [p for t, p in zip(taus, prog) if at * T + 0.05 < t < (at + ln) * T - 0.05]
            if len(inside) > 1:
                self.assertAlmostEqual(min(inside), max(inside), places=9, msg="it moves during a stop")
        # just after a stop it goes slower than in the middle of the next burst (no dead start)
        at, ln = ev["stops"][1]
        t0 = (at + ln) * T
        i0 = next(i for i, t in enumerate(taus) if t >= t0)
        nxt = ev["stops"][2][0] * T
        im = next(i for i, t in enumerate(taus) if t >= (t0 + nxt) / 2)
        self.assertLess(prog[i0 + 1] - prog[i0], prog[im + 1] - prog[im])

    def test_the_critic_crops_it_where_it_is(self):
        """critic.critter_progress is critters.js critterProgress (the crops along a straight share of the time missed a
        walker by a quarter of its way)."""
        from critic import critter_progress
        ev = self.p["ev"]
        for t, want in zip(self.p["taus"], self.p["progress"]):
            self.assertAlmostEqual(critter_progress(ev, t), want, places=6)
        old = {"dur": 100, "pauses": [0.2, 0.6], "pauseLen": 0.05}
        self.assertAlmostEqual(critter_progress(old, 50), (50 - 5) / 90, places=6)

    def test_gaits(self):
        g = self.p["gaits"]
        self.assertGreater(g["crab"]["bob"], 0)
        self.assertGreater(g["crab"]["rock"], 0)
        self.assertIsNone(g["snail"], "a snail glides")
        self.assertIsNone(g["off"])
        self.assertLess(g["beetle"]["bob"], g["crab"]["bob"])
        self.assertNotEqual(g["mouse"], g["beetle"], "a mouse scurries on its own gait, not an insect's")
        self.assertGreater(g["mouse"]["legTop"], g["beetle"]["legTop"], "its legs begin low in the sprite, under its tail")
        self.assertEqual(g["over"]["bob"], 0.08)
        self.assertEqual(g["over"]["rock"], g["crab"]["rock"])

    def test_each_step_lifts_and_rocks_it_and_it_never_steps_back(self):
        G, size = self.p["gaits"]["crab"], 56
        lifts = [q["lift"] for q in self.p["pose"]]
        self.assertGreater(max(lifts), 0.8 * G["bob"] * size)
        self.assertGreaterEqual(min(lifts), 0)
        self.assertLessEqual(max(lifts), G["bob"] * size + 1e-9)
        self.assertGreater(max(abs(q["rock"]) for q in self.p["pose"]), 0.5 * G["rock"] * 3.14159 / 180)
        # its surge stays under a third of a step, so the way walked plus it only ever goes forward
        self.assertLess(max(abs(q["surge"]) for q in self.p["pose"]), G["stride"] * size / 3)
        self.assertLess(G["lurch"], 1.0)
        st = self.p["still"]
        self.assertEqual((st["lift"], st["rock"]), (0, 0), "standing, it doesn't bob")

    def test_the_moth_starts_and_ends_behind_its_lamp_and_never_cuts_through_it(self):
        """timeline/ambient.js mothBehind + moth.js mothAt, lamp units (z away from the camera): it starts and ends
        behind the lamp's middle, where the lamp hides it, and wherever it passes from behind the lamp to in front of it
        (or back) it is beside the lamp, clear of its outline (about 1.7 units across its middle): it never pops into
        view on the lamp's face."""
        for m in self.p["moths"]:
            for x, y, z in (m["start"], m["end"]):
                self.assertGreater(z, 1.0)
                self.assertLess(abs(x), 0.5)
                self.assertLess(abs(y), 0.5)
            for path in (m["entry"], m["exit"]):
                for (x0, _y0, z0), (x1, _y1, z1) in zip(path, path[1:]):
                    if (z0 > 0) != (z1 > 0):
                        xc = x0 + (x1 - x0) * z0 / (z0 - z1)
                        self.assertGreater(abs(xc), 1.7, f"crossed from behind to in front of the lamp at x {xc:.2f}")
            self.assertTrue(any(abs(x) > 1.8 for x, _y, _z in m["entry"]), "it comes out round the side")
        self.assertEqual(self.p["mothAgain"], {k: self.p["moths"][0]["ev"][k] for k in ("from", "to", "viaIn", "viaOut")})


class Lints(unittest.TestCase):
    def test_a_clip_is_a_bump_and_coming_or_going_is_not(self):
        """critter_ends.bumps: the hidden share may fall as it comes out and rise as it goes, never rise and fall again."""
        from critter_ends import bumps
        self.assertEqual(bumps([1, 0.6, 0.2, 0, 0, 0, 0.3, 1]), [], "out from behind a cover and in behind another")
        self.assertEqual(bumps([1, 0.5, 0, 0, 0.17, 0.15, 0, 0, 0.4, 1]), [4, 5], "cut off on the way")
        self.assertEqual(bumps([0, 0, 0.03, 0, 0]), [], "a sliver under the threshold")

    def test_the_tide_pool_crab_is_whole_all_along(self):
        """With the plate at hand: the hermit crab walks in front of the decorator crab's feet; a character's dry cutout
        from the outdoors hid a fifth of it as if indoors (the v6 clip), and the check finds that without the rule."""
        import numpy as np
        import critter_ends as CE
        from cozy.paths import ROOT
        if not (ROOT / "out" / "plates" / "tidepool-fog" / "regions.png").exists():
            self.skipTest("no tide pool plate on this machine")
        spec = json.loads((ROOT / "scenes" / "tidepool-fog" / "scene.json").read_text(encoding="utf-8"))
        L = next(x for x in spec["layers"] if x.get("creature") == "hermitcrab")
        self.assertEqual(CE.clipped_along("tidepool-fog", L), [])
        orig = CE.dry_mask
        try:
            CE.dry_mask = lambda pd, shape: np.zeros(shape, np.float32)
            self.assertTrue(CE.clipped_along("tidepool-fog", L), "without the dry rule it is cut off at the decorator crab")
        finally:
            CE.dry_mask = orig

    def test_the_moth_comes_from_behind_its_lamp(self):
        import review
        out = []
        review._lint_moth(out, [{"type": "moth"}], {"moth": {"perHour": 24}})
        self.assertEqual([o[:2] for o in out], [("L185", False)])
        out = []
        review._lint_moth(out, [{"type": "moth"}], {"moth": {"perHour": 24, "hide": "lamp"}})
        self.assertTrue(out[0][1])

    def test_a_painted_moon_crosses_the_sky(self):
        """L168 for every scene: the Sleeping Hound Inn's two painted moons sat still through ten samples while the
        analysis named them in a note (2026-11-15)."""
        import json
        import tempfile
        import review
        with tempfile.TemporaryDirectory() as tmp:
            pd = Path(tmp)

            def run(note, spec):
                (pd / "analysis.json").write_text(json.dumps({"regions": [{"kind": "sky", "note": note}]}), encoding="utf-8")
                out = []
                review._lint_moon(out, spec, pd)
                return [o[:2] for o in out]

            self.assertEqual(run("Visible sky with rippling northern lights and two moons", {}), [("L168", False)])
            self.assertEqual(run("Starry sky with a square moon", {"plate_fx": {"moon": {"path": [[0, 0], [1, 1]]}}}), [("L168", True)])
            self.assertEqual(run("A moonlit snowy field, moonlight on the roofs", {}), [])
            self.assertEqual(run("Clear night sky without a moon", {}), [])
            (pd / "analysis.json").unlink()
            out = []
            review._lint_moon(out, {}, pd)
            self.assertEqual(out, [], "no analysis: nothing to check")

    def test_the_mist_reaches_the_characters_outlines(self):
        import review
        chars = [{"name": "otter", "kind": "pet", "dry": True, "dry_why": "a character"}]
        out = []
        review._lint_mist_outlines(out, {"plate_fx": {"mist": 0.3}}, chars)
        self.assertEqual([o[:2] for o in out], [("L187", False)])
        out = []
        review._lint_mist_outlines(out, {"plate_fx": {"mist": 0.3, "mistDry": True}}, chars)
        self.assertTrue(out[0][1])
        for spec, regs in (({"plate_fx": {"mist": 0}}, chars), ({"plate_fx": {"mist": 0.3}}, [{"name": "pond", "kind": "water"}])):
            out = []
            review._lint_mist_outlines(out, spec, regs)
            self.assertEqual(out, [], "no mist, or no characters: nothing to check")

    def test_hand_marked_dry_scenery_still_hides_a_critter(self):
        """Only the character rule's regions (dry_why) are no indoors to a critter: a noren marked dry by hand hangs in
        front of the street and still hides a snail behind it (the ramen alley's are unchanged)."""
        import cv2
        import numpy as np
        from critter_ends import dry_mask
        with tempfile.TemporaryDirectory() as tmp:
            pd = Path(tmp)
            ids = np.zeros((216, 384), np.uint8)
            ids[50:80, 50:80] = 1
            ids[50:80, 200:230] = 2
            cv2.imwrite(str(pd / "regions.png"), ids)
            (pd / "regions.json").write_text(json.dumps([{"id": 1, "name": "otter", "kind": "pet", "dry": True, "dry_why": "a character"},
                                                         {"id": 2, "name": "noren_1", "kind": "curtain", "dry": True}]), encoding="utf-8")
            m = dry_mask(pd, (216, 384))
        self.assertEqual(float(m[65, 65]), 1.0)
        self.assertEqual(float(m[65, 215]), 0.0)

    def _walkers(self, layers, ev):
        import review
        out = []
        review._lint_walkers(out, "no-such-scene", "no-such-plate", layers, ev)
        return [o for o in out if o[0] == "L182"]

    def test_a_walker_drawn_as_a_glider_fails(self):
        L = {"type": "critter", "creature": "hermitcrab", "track": 1, "path": [[0, 0], [1, 1]]}
        ev = {"critter": [{"perHour": 4}, {"perHour": 16}]}
        self.assertFalse(self._walkers([L], ev)[0][1])
        self.assertFalse(self._walkers([{**L, "gait": True}], ev)[0][1], "its visits need their stops too")
        ok = self._walkers([{**L, "gait": True}], {"critter": [{"perHour": 4}, {"perHour": 16, "walk": {"stops": [3, 6]}}]})
        self.assertTrue(ok[0][1], ok)
        self.assertEqual(self._walkers([{"type": "critter", "creature": "periwinklesnail"}], ev), [], "a snail glides")

    def test_water_hides_only_what_lives_in_it(self):
        from critter_ends import lives_in_water
        self.assertTrue(lives_in_water("hermitcrab"))
        self.assertTrue(lives_in_water("treefrog"))
        self.assertFalse(lives_in_water("ladybug"))
        self.assertFalse(lives_in_water("gecko"))

    def test_waves_that_are_heard_are_seen(self):
        import review
        with tempfile.TemporaryDirectory() as tmp:
            pd = Path(tmp)
            spec = {"events": {"surf": {"perHour": 330}}}
            out = []
            review._lint_surf(out, spec, [], pd)
            self.assertEqual([o[:2] for o in out], [("L181", False)])
            out = []
            review._lint_surf(out, spec, [{"type": "surf"}], pd)
            self.assertFalse(out[0][1], "no surf_fx.png or surf.json yet")
            (pd / "surf_fx.png").write_bytes(b"")
            (pd / "surf.json").write_text(json.dumps({"spots": [{"x": 0.5, "y": 0.5, "w": 100, "h": 60}], "edges": {"step": 8}}), encoding="utf-8")
            out = []
            review._lint_surf(out, spec, [{"type": "surf"}], pd)
            self.assertTrue(out[0][1], out)
            out = []
            review._lint_surf(out, {"events": {}}, [], pd)
            self.assertEqual(out, [], "no surf, nothing to see")


if __name__ == "__main__":
    unittest.main()
