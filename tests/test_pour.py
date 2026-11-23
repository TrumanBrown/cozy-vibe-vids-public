"""Falling water pours (L220; the Yuzu Spring's bamboo spout sat frozen through sample v2, 2026-11-12): tools/pour_map.py
measures a fall from the lip to the water in meters and seconds, analyze drafts a pour layer for every traced fall,
review fails a fall nothing moves, and the static check measures a fall against what drifts in front of it. Free,
offline, a second.

  .venv\\Scripts\\python -m unittest tests.test_pour -v
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pour_map as P  # noqa: E402

CAM = {"horizon": 0.47, "camHeight": 0.4, "focal": 2700.0}


def plate_with_stream(x0=0.495, x1=0.505, y0=0.5, y1=0.7):
    img = np.full((P.H4, P.W4, 3), 0.1, np.float32)
    ys, xs = slice(int(y0 * P.H4), int(y1 * P.H4)), slice(int(x0 * P.W4), int(x1 * P.W4))
    img[ys, xs] = 0.55
    img[ys, xs][:, ::3] = 0.9                    # lit strokes down the stream
    return img, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class Measure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img, cls.poly = plate_with_stream()
        cls.rec, cls.mask = P.measure(img, cls.poly, CAM, v0=0.45)

    def test_the_scale_is_the_water_planes_at_the_foot(self):
        foot = self.rec["foot"][1]
        self.assertAlmostEqual(foot, 0.7 * P.H4, delta=1.5)
        z = CAM["focal"] * CAM["camHeight"] / (foot - CAM["horizon"] * P.H4)
        self.assertAlmostEqual(self.rec["z"], z, places=2)
        self.assertAlmostEqual(self.rec["ppm"], CAM["focal"] / z, delta=0.2)
        self.assertAlmostEqual(self.rec["aspect"], 0.4 / math.hypot(0.4, z), places=3)

    def test_it_falls_from_the_lip_in_the_time_gravity_takes(self):
        h = self.rec["fall_m"]
        self.assertAlmostEqual(h, 0.2 * P.H4 / self.rec["ppm"], delta=0.003)
        want = (math.sqrt(0.45 ** 2 + 2 * P.G * h) - 0.45) / P.G         # straight down from v0
        self.assertAlmostEqual(self.rec["tau"], want, delta=0.004)
        self.assertAlmostEqual(self.rec["v_foot"], math.sqrt(0.45 ** 2 + 2 * P.G * h), delta=0.01)
        taus = [r[3] for r in self.rec["rows"]]
        self.assertEqual(taus[0], 0.0)
        self.assertTrue(all(b > a for a, b in zip(taus, taus[1:])), "later down the stream")
        # the water speeds up: a row takes less time near the foot than near the lip
        self.assertLess(taus[-1] - taus[-2], (taus[1] - taus[0]) / 3)

    def test_rows_follow_the_stream(self):
        rows = self.rec["rows"]
        self.assertEqual(len(rows), round(self.rec["foot"][1] - self.rec["lip"][1]))
        for y, cx, hw, _ in rows[10:-10]:
            self.assertAlmostEqual(cx, 0.5 * P.W4, delta=1.0)
            self.assertAlmostEqual(hw, 0.005 * P.W4, delta=1.0)
        self.assertAlmostEqual(self.rec["lip"][1], 0.5 * P.H4, delta=1.0)
        self.assertAlmostEqual(self.rec["foot"][1], 0.7 * P.H4, delta=1.5)

    def test_its_own_light_and_dark(self):
        lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        self.assertGreater(lum(self.rec["light"]), 0.85)
        self.assertLess(lum(self.rec["dark"]), 0.6)

    def test_the_mask_covers_its_box(self):
        x0, y0, x1, y1 = self.rec["box"]
        self.assertEqual(self.mask.shape, (round(y1 - y0), round(x1 - x0)))
        self.assertGreater(self.mask.max(), 250)
        self.assertEqual(int(self.mask[0, 0]), 0)

    def test_a_foot_above_the_horizon_needs_a_scale(self):
        img, poly = plate_with_stream(y0=0.2, y1=0.4)
        with self.assertRaises(SystemExit):
            P.measure(img, poly, CAM)
        rec, _ = P.measure(img, poly, CAM, ppm=600)
        self.assertEqual(rec["ppm"], 600)


class Jet(unittest.TestCase):
    """A dry spout's pour (L223): solved from where it leaves the lip to where it lands, under gravity."""

    @classmethod
    def setUpClass(cls):
        cls.img = np.full((P.H4, P.W4, 3), 0.2, np.float32)
        cls.lip, cls.lands = [0.829 * P.W4, 0.524 * P.H4], [0.81 * P.W4, 0.70 * P.H4]
        cls.rec, cls.mask = P.jet(cls.img, cls.lip, cls.lands, CAM, angle=25, width=0.04, colors=([0.9, 0.8, 0.7], [0.2, 0.2, 0.2]))

    def test_it_runs_from_the_lip_to_where_it_lands(self):
        rows = self.rec["rows"]
        self.assertAlmostEqual(rows[0][1], self.lip[0], delta=0.5)
        self.assertAlmostEqual(rows[-1][1], self.lands[0], delta=1.0)
        self.assertEqual(self.rec["foot"][1], round(self.lands[1], 1))
        self.assertFalse(self.rec["painted"], "pour.js draws all of it")

    def test_it_falls_as_a_thrown_thing_does(self):
        r = self.rec
        z = CAM["focal"] * CAM["camHeight"] / (self.lands[1] - CAM["horizon"] * P.H4)
        self.assertAlmostEqual(r["z"], z, places=2)
        ppm = CAM["focal"] / z
        dx, dy, a = abs(self.lands[0] - self.lip[0]) / ppm, (self.lands[1] - self.lip[1]) / ppm, math.radians(25)
        v0 = math.sqrt(P.G * dx ** 2 / (2 * math.cos(a) ** 2 * (dy - dx * math.tan(a))))
        self.assertAlmostEqual(r["v0"], v0, delta=0.002)
        t = dx / (v0 * math.cos(a))
        self.assertAlmostEqual(r["tau"], t, delta=0.003)
        taus = [q[3] for q in r["rows"]]
        self.assertTrue(all(b > a for a, b in zip(taus, taus[1:])))
        widths = [q[2] for q in r["rows"]]
        self.assertGreater(widths[len(widths) // 4], widths[-1], "it thins as it speeds up")

    def test_a_spout_too_steep_for_where_it_lands_aims_lower(self):
        rec, _ = P.jet(self.img, self.lip, [0.70 * P.W4, 0.60 * P.H4], CAM, angle=60)
        self.assertLess(rec["angle"], 60)
        self.assertGreater(rec["v0"], 0)

    def test_its_mask(self):
        x0, y0, x1, y1 = self.rec["box"]
        self.assertEqual(self.mask.shape, (int(y1 - y0), int(x1 - x0)))
        self.assertGreater(self.mask.max(), 250)


class Mouth(unittest.TestCase):
    """The water comes out of the spout's opening, seen running in the tube first (Truman 2026-11-12, after v6: the pour
    looked like it appeared out of the tube's tip): pour_map finds the opening, a dark ellipse ringed by a lit rim."""

    @classmethod
    def setUpClass(cls):
        import cv2
        img = np.full((P.H4, P.W4, 3), 0.25, np.float32)
        cls.c = (2000, 1000)
        cv2.ellipse(img, cls.c, (60, 70), 20, 0, 360, (0.7, 0.6, 0.45), -1)     # the lit rim of the tube
        cv2.ellipse(img, cls.c, (40, 50), 20, 0, 360, (0.03, 0.03, 0.03), -1)   # the dark opening
        cls.img = img
        cls.m = P.mouth(img, [1990, 1055])

    def test_it_finds_the_opening(self):
        m = self.m
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m["c"][0], self.c[0], delta=3)
        self.assertAlmostEqual(m["c"][1], self.c[1], delta=3)
        axes = sorted([np.hypot(*m["A"]), np.hypot(*m["B"])])
        self.assertAlmostEqual(axes[0], 40, delta=4)
        self.assertAlmostEqual(axes[1], 50, delta=4)
        self.assertGreater(m["low"][1], self.c[1] + 40, "its lowest point")

    def test_none_without_one(self):
        self.assertIsNone(P.mouth(np.full((P.H4, P.W4, 3), 0.25, np.float32), [1990, 1055]))

    def test_it_pours_over_the_rim_under_its_water_and_pulls_into_a_stream(self):
        """Truman 2026-11-15: started at the opening's lowest point it looked like it came out of one spot. The water in the
        tube pours over the whole stretch of rim under its surface (the chord at its level), and that tongue pulls into a
        round stream within about a pipe radius, its section the flow over its speed."""
        import math
        depth = 0.2
        rec, _ = P.jet(self.img, [1990, 1055], [1950, 1500], CAM, angle=25, depth=depth)
        m = rec["mouth"]
        self.assertIsNotNone(m)
        rows = rec["rows"]
        chord = 2 * math.sqrt(1 - (1 - 2 * depth) ** 2) * m["across"]
        self.assertAlmostEqual(2 * rows[0][2], chord, delta=2.0, msg="at the brink it spans the chord at the water's level")
        self.assertAlmostEqual(rows[0][0], m["top"][1], delta=1.0)
        self.assertGreater(2 * rows[0][2], 0.6 * 2 * m["across"], "most of the opening's width, not one spot")
        # a pipe radius below the brink it is nearly round: within a quarter of the tongue's extra width
        r_px = m["radius"] * rec["ppm"]
        k = next(i for i, q in enumerate(rows) if q[0] - rows[0][0] >= r_px)
        rope = math.sqrt(m["flow_lpm"] / 60000 / (math.pi * 1.0)) * rec["ppm"]      # its radius at about 1 m/s
        self.assertLess(rows[k][2], rope + 0.25 * (rows[0][2] - rope) + 3)
        self.assertLess(rows[-1][2], rows[k][2], "and thins as it speeds up")
        self.assertAlmostEqual(rec["width"], 2 * math.sqrt(m["flow_lpm"] / 60000 / (math.pi * rec["v0"])), delta=0.002)
        # deeper water: a wider brink and a thicker stream
        deep, _ = P.jet(self.img, [1990, 1055], [1950, 1500], CAM, angle=25, depth=0.3)
        self.assertGreater(deep["rows"][0][2], rows[0][2])
        self.assertGreater(deep["mouth"]["flow_lpm"], m["flow_lpm"])
        a, b = np.array(m["inv"]).reshape(2, 2), np.array(m["low"]) - np.array(m["c"])
        self.assertAlmostEqual(float(np.hypot(*(a @ b))), 1.0, delta=0.005, msg="its lowest point is on the opening's edge")
        far, _ = P.jet(self.img, [1700, 1055], [1650, 1500], CAM, angle=25)
        self.assertIsNone(far["mouth"], "an opening far from the given lip isn't this spout's")


class Pipeline(unittest.TestCase):
    def test_analyze_drafts_a_pour_for_every_traced_fall(self):
        import analyze_plate as A
        spec = A.draft_scene("no-such-scene", {"aesthetic": "x"}, {}, {}, [], None, None, False, P.W4, P.H4, falls=2)
        self.assertEqual([L.get("fall") for L in spec["layers"] if L["type"] == "pour"], [0, 1])
        self.assertEqual(spec["plate_fx"]["waterfall"], 0)
        none = A.draft_scene("no-such-scene", {"aesthetic": "x"}, {}, {}, [], None, None, False, P.W4, P.H4)
        self.assertFalse([L for L in none["layers"] if L["type"] == "pour"])
        self.assertNotIn("waterfall", none["plate_fx"])

    def test_review_fails_a_fall_nothing_moves(self):
        import review as R
        import pour_map
        poly = [[0.5, 0.5], [0.51, 0.5], [0.51, 0.7], [0.5, 0.7]]
        real_falls, real_root = pour_map.falls_of, R.ROOT
        try:
            with tempfile.TemporaryDirectory() as td:
                R.ROOT = Path(td)
                pd = Path(td) / "plate"
                pour_map.falls_of = lambda plate: [poly]
                spec = {"plate_fx": {}}
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [])
                self.assertEqual([o[1] for o in out], [False], out)
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [{"type": "pour", "fall": 0}])
                self.assertEqual([o[1] for o in out], [False], "a pour layer without its measure")
                (pd / "pour").mkdir(parents=True)
                (pd / "pour" / "pour.json").write_text(json.dumps({"falls": [{"fall": 0}]}))
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [{"type": "pour", "fall": 0}])
                self.assertEqual([o[1] for o in out], [True])
                out = []
                R._lint_falls(out, "s", {"plate_fx": {"waterfall": 0.55}}, "p", pd, [])
                self.assertEqual([o[1] for o in out], [True], "a far fall's shimmer that reads (the jungle temple's)")
                # a dry spout the analysis found (key art draws no moving water, L223): it must pour, drawn whole
                pour_map.falls_of = lambda plate: []
                (Path(td) / "assets" / "keyart").mkdir(parents=True)
                (Path(td) / "assets" / "keyart" / "p.masks.json").write_text(json.dumps(
                    {"spouts": [{"name": "spout", "lip": [0.83, 0.52], "lands": [0.81, 0.7]}]}))
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [])
                self.assertEqual([(o[0], o[1]) for o in out], [("L223", False)], out)
                sp = {"type": "pour", "spout": "spout", "lip": [0.83, 0.52], "lands": [0.81, 0.7]}
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [sp])
                self.assertEqual([(o[0], o[1]) for o in out], [("L223", False), ("L223", True)], "poured, but not measured yet")
                (pd / "pour" / "pour.json").write_text(json.dumps({"falls": [{"key": "spout:spout"}]}))
                out = []
                R._lint_falls(out, "s", spec, "p", pd, [sp])
                self.assertEqual([(o[0], o[1]) for o in out], [("L223", True), ("L223", True)])
        finally:
            pour_map.falls_of, R.ROOT = real_falls, real_root

    def test_analyze_drafts_a_pour_for_a_dry_spout(self):
        import analyze_plate as A
        sp = {"name": "bamboo_spout", "lip": [0.83, 0.52], "lands": [0.81, 0.7]}
        spec = A.draft_scene("no-such-scene", {"aesthetic": "x"}, {}, {}, [], None, None, False, P.W4, P.H4, spouts=[sp])
        self.assertEqual([L for L in spec["layers"] if L["type"] == "pour"],
                         [{"type": "pour", "spout": "bamboo_spout", "lip": [0.83, 0.52], "lands": [0.81, 0.7]}])
        self.assertEqual(spec["plate_fx"]["waterfall"], 0)
        self.assertIn("spout", A.KINDS)

    def test_a_fall_moves_more_than_what_drifts_in_front_of_it(self):
        import motion_review as M
        self.assertFalse(M.fall_moves(0.0070, 0.0148), "sample v2: steam and snow over a frozen pour")
        self.assertTrue(M.fall_moves(0.2766, 0.0168), "the pour layer")
        self.assertFalse(M.fall_moves(0.04, 0.03), "no more than its surroundings")
        self.assertIn("pour", " ".join(M.FALL_WORDS))
        mask = np.zeros((40, 40), bool)
        mask[10:30, 18:22] = True
        pm = np.full((40, 40), 0.01, np.float32)
        pm[mask] = 0.2
        mv, around = M.fall_motion(pm, mask)
        self.assertAlmostEqual(mv, 0.2, places=5)
        self.assertAlmostEqual(around, 0.01, places=5)


if __name__ == "__main__":
    unittest.main()
