r"""Which plants hang and which water falls, and a region's hold (tools/cozy/plate/regions.py; free, offline, instant):

  .venv\Scripts\python -m unittest discover -s tests -p test_regions.py -v

The jungle temple's seven strands of vines came out pinned at their tips like potted plants, and its waterfall as a
river with rain rings (2026-10-27, L163). The model now answers "hangs" and "falls"; an answer cached before it was
asked is read by its words, and nothing rooted below may hang. A swaying region's "hold" (the pole the tide pool's kelp
hangs against) keeps the sway off it.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.plate.regions import falls, hangs  # noqa: E402


class Hangs(unittest.TestCase):
    def test_the_models_answer_wins(self):
        self.assertTrue(hangs({"name": "fern", "note": "a fern", "hangs": True}))
        self.assertFalse(hangs({"name": "left_hanging_vines", "note": "vines hanging down", "hangs": False}))

    def test_the_jungle_temples_vines_by_their_words(self):
        for name, note in [("left_hanging_vines", "Leafy vines hanging against the left wall"),
                           ("support_vines", "Vines trailing down the stone support"),
                           ("long_waterfall_vines", "Prominent long vines silhouetted against the distant water"),
                           ("thin_opening_vines", "Thin hanging strands beyond the overhang")]:
            self.assertTrue(hangs({"name": name, "note": note}), name)

    def test_rooted_plants_stay_pinned_below(self):
        for name, note in [("tomato_vine", "a tomato vine climbing its stake"),
                           ("willow", "a tree with drooping branches over the pond"),
                           ("potted_ivy", "potted ivy on the sill"),
                           ("bush", "a flowering bush by the gate"),
                           ("fern", "a potted fern by the window")]:
            self.assertFalse(hangs({"name": name, "note": note}), name)


class Falls(unittest.TestCase):
    def test_the_models_answer_wins(self):
        self.assertTrue(falls({"name": "spill", "note": "water", "flow": [0, 0], "falls": True}))
        self.assertFalse(falls({"name": "waterfall_pool", "note": "pool under the falls", "flow": [0, 1], "falls": False}))

    def test_a_fall_by_its_words_and_its_flow(self):
        self.assertTrue(falls({"name": "distant_waterfall", "note": "Water falling down the distant cliff", "flow": [0.0, 1.0]}))
        # the pool under it is still; a river named for the falls runs across the frame
        self.assertFalse(falls({"name": "waterfall_pool", "note": "Moonlit pool with rippling reflections", "flow": [0, 0]}))
        self.assertFalse(falls({"name": "falls_river", "note": "the river below the falls", "flow": [1.0, 0.1]}))


class Hold(unittest.TestCase):
    """The tide pool's kelp strands hang against the lean-to's pole at the pole's own depth: an outward feather and a
    sample offset would have pulled the pole's edge into the sway (2026-11-05). A region's "hold" stays out of it."""

    def regions(self, rg):
        import json
        import tempfile

        import numpy as np
        from PIL import Image

        from cozy.plate.regions import render_regions
        W, H = 1920, 1080
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            meta = render_regions([rg], np.full((H, W), 0.5, np.float32), W, H, out)
            reg = np.asarray(Image.open(out / "regions.png").convert("RGB"))
            saved = json.loads((out / "regions.json").read_text())
        return meta, reg[..., 0], reg[..., 1] / 255.0, saved

    def test_the_sway_fades_out_beside_what_it_holds_and_never_reaches_into_it(self):
        import numpy as np
        strand = {"name": "kelp", "kind": "curtain", "feather": 5, "polys": [[[0.10, 0.20], [0.20, 0.20], [0.20, 0.60], [0.10, 0.60]]]}
        pole = [[[0.20, 0.10], [0.30, 0.10], [0.30, 0.70], [0.20, 0.70]]]
        _, ids0, w0, _ = self.regions(strand)
        meta, ids, w, saved = self.regions({**strand, "hold": pole})
        rid = meta[0]["id"]
        x_pole = int(0.20 * 1920) + 2
        rows = slice(int(0.3 * 1080), int(0.5 * 1080))
        self.assertTrue((ids0[rows, x_pole] == rid).all())       # without it the feather spills onto the pole
        self.assertFalse((ids[rows, x_pole:int(0.30 * 1920)] == rid).any())
        reach = 16 * 1920 / 3840
        for d in (1, 3, 6):
            x = int(0.20 * 1920) - d
            self.assertLessEqual(float(w[rows, x].max()), (d + 1) / reach + 1e-6, d)
        x_far = int(0.10 * 1920) + 1                              # the other side is as before
        np.testing.assert_allclose(w[rows, x_far - 4:x_far + 4], w0[rows, x_far - 4:x_far + 4])
        self.assertNotIn("hold", saved[0])


class InTheWater(unittest.TestCase):
    """Whatever floats or stands in the water is in front of it (2026-11-12): the Yuzu Spring's pool, nearer by its median
    depth than the yuzu sprite floating in it, took most of the fruit's face and laid its ripples' glints on it."""

    def test_a_floating_thing_owns_its_pixels_whatever_the_waters_depth(self):
        import tempfile

        import numpy as np
        from PIL import Image

        from cozy.plate.regions import render_regions
        W, H = 960, 540
        disp = np.tile(np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None], (1, W))   # nearer down the frame
        pool = {"name": "pool", "kind": "water", "through": False, "polys": [[[0.1, 0.4], [0.9, 0.4], [0.9, 1.0], [0.1, 1.0]]]}
        fruit = {"name": "fruit", "kind": "bob", "polys": [[[0.45, 0.42], [0.55, 0.42], [0.55, 0.55], [0.45, 0.55]]]}
        with tempfile.TemporaryDirectory() as td:
            meta = render_regions([fruit, pool], disp, W, H, Path(td))
            ids = np.asarray(Image.open(Path(td) / "regions.png").convert("RGB"))[..., 0]
        fid = next(g["id"] for g in meta if g["name"] == "fruit")
        pid = next(g["id"] for g in meta if g["name"] == "pool")
        self.assertLess(next(g["disp"] for g in meta if g["name"] == "fruit"), next(g["disp"] for g in meta if g["name"] == "pool"),
                        "the case: the pool is nearer by its median depth")
        self.assertEqual(int(ids[int(0.5 * H), int(0.5 * W)]), fid)
        self.assertEqual(int(ids[int(0.8 * H), int(0.5 * W)]), pid)


if __name__ == "__main__":
    unittest.main()
