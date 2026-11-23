"""Steam off a hot spring's pool (tools/pool_steam.py, src/library/poolsteam.js; the Yuzu Spring, 2026-11-12): the slices
stand on the water from the far waterline to the near one, each at its distance on the ground plane, and the maps hide
each slice behind what stands in front of it. Free, offline, a second.

  .venv\\Scripts\\python -m unittest tests.test_pool_steam -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pool_steam as P  # noqa: E402

W, H = 960, 540


def frac(a, b, n):
    return slice(int(a * n), int(b * n))


class PoolSlices(unittest.TestCase):
    """A synthetic pool: water from row 0.58 to 0.90; a monkey soaking in it (its foot in the water at 0.70); a stoat
    lying on the far rim right above the monkey's head (0.40 to 0.45); a critter on a rock ledge in the middle of the
    water (0.60 to 0.64, rock under it); a near rock along the bottom, much nearer than the water."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        ids = np.zeros((H, W), np.uint8)
        ids[frac(0.58, 0.90, H), frac(0.10, 0.90, W)] = 1                     # the pool
        ids[frac(0.60, 0.68, H), frac(0.55, 0.65, W)] = 0                     # a rock ledge in it
        ids[frac(0.60, 0.64, H), frac(0.55, 0.65, W)] = 4                     # a critter lying on the ledge
        ids[frac(0.45, 0.70, H), frac(0.20, 0.30, W)] = 2                     # the monkey, soaking
        ids[frac(0.40, 0.45, H), frac(0.20, 0.30, W)] = 3                     # the stoat, on the far rim above it
        rg = np.stack([ids, np.full_like(ids, 255), np.zeros_like(ids)], -1)
        Image.fromarray(rg, "RGB").save(d / "regions.png")
        y = (np.arange(H) / H)[:, None] * np.ones((1, W))
        disp = np.clip((y - 0.5) * 1.6, 0, 1)
        disp[frac(0.92, 1.0, H), :] = 0.95                                   # the near rock
        Image.fromarray((disp * 255 + 0.5).astype(np.uint8), "L").save(d / "depth8.png")
        Image.fromarray(np.full((H, W, 3), 60, np.uint8)).save(d / "plate.png")
        (d / "regions.json").write_text(json.dumps([
            {"id": 1, "name": "pool", "kind": "water"}, {"id": 2, "name": "monkey", "kind": "pet"},
            {"id": 3, "name": "stoat", "kind": "pet"}, {"id": 4, "name": "critter", "kind": "pet"}]))
        # "near" is a render setting of the layer (how much fainter a near slice is): it must not move the waterlines
        cls.L = {"type": "poolsteam", "region": "pool", "horizon": 0.47, "camHeight": 0.4, "focal": 2700, "sheets": 8,
                 "near": 1.4}
        cls.sheets, cls.cam = P.sheet_table("x", cls.L, dict(P.DEFAULTS), 11, pdir=d)
        cls.out = d / "out"
        cls.out.mkdir()
        P.sheet_maps("x", cls.sheets, cls.cam, cls.out, pdir=d)
        cls.front = np.asarray(Image.open(cls.out / "front.png").convert("L"), np.float32) / P.FRONT_SCALE
        cls.rows = np.asarray(Image.open(cls.out / "rows.png").convert("L"), np.float32) / 255

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_slices_run_from_the_far_waterline_to_the_near_one(self):
        ys = [s["y"] for s in self.sheets]
        self.assertEqual(len(ys), 8)
        self.assertAlmostEqual(ys[0], int(0.58 * H) / H + 0.004, places=3)
        self.assertAlmostEqual(ys[-1], (int(0.90 * H) - 1) / H - 0.004, places=3)
        self.assertTrue(np.allclose(np.diff(ys), np.diff(ys)[0], atol=2e-4), "evenly spaced on screen")

    def test_each_slice_stands_at_its_distance_on_the_ground_plane(self):
        for s in self.sheets:
            z = 2700 * 0.4 / ((s["y"] - 0.47) * 2160)       # the focal length is in px at 4K, whatever the maps' size
            self.assertLess(abs(s["z"] / z - 1), 2e-3)
            self.assertLess(abs(s["ppm"] * s["z"] / 2700 - 1), 2e-3)
        zs = [s["z"] for s in self.sheets]
        self.assertTrue(all(a > b for a, b in zip(zs, zs[1:])), "nearer down the frame")

    def test_no_two_neighbours_show_the_same_steam(self):
        for a, b in zip(self.sheets, self.sheets[1:]):
            self.assertNotEqual(a["mirror"], b["mirror"])
            self.assertNotEqual(a["toff"], b["toff"])
        self.assertEqual(len({s["offset"] for s in self.sheets}), len(self.sheets))
        self.assertLessEqual(len({s["toff"] for s in self.sheets}), 3, "the layer loads at most three times a frame")

    def at(self, img, x, y):
        return float(img[int(y * img.shape[0]), int(x * img.shape[1])])

    def test_a_soaking_character_hides_the_slices_behind_its_waterline(self):
        behind = sum(s["y"] < int(0.70 * H) / H - 0.004 for s in self.sheets)
        self.assertGreater(behind, 0)
        self.assertAlmostEqual(self.at(self.front, 0.25, 0.60), behind, delta=0.1)
        self.assertAlmostEqual(self.at(self.front, 0.25, 0.50), behind, delta=0.1, msg="its head too, above the water")

    def test_one_lying_on_the_far_rim_keeps_its_own_waterline(self):
        # merged with the monkey below it, the stoat took the monkey's waterline and cut a straight edge into the steam
        self.assertAlmostEqual(self.at(self.front, 0.25, 0.42), 0, delta=0.1)

    def test_the_near_rock_hides_every_slice(self):
        self.assertAlmostEqual(self.at(self.front, 0.50, 0.96), len(self.sheets), delta=0.1)

    def test_steam_rises_over_the_water_and_what_soaks_in_it_only(self):
        k = next(i for i, s in enumerate(self.sheets) if 0.615 < s["y"] < 0.64)
        row = self.rows[k]
        self.assertGreater(row[int(0.40 * len(row))], 0.95, "open water")
        self.assertGreater(row[int(0.25 * len(row))], 0.95, "the monkey soaking: steam rises in front of it")
        self.assertLess(row[int(0.60 * len(row))], 0.05, "the critter lying on its rock: no steam off it")
        self.assertLess(row[int(0.05 * len(row))], 0.05, "the rocks beside the pool")


if __name__ == "__main__":
    unittest.main()
