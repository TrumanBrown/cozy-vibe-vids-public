"""Lifting things off the plate so they can move (lessons L167, L168), on small synthetic pictures: a strand's matte
against the sky, a curtain's leaves against ruins seen through its gaps, the moon and its glow measured, where the moon
shows snapped to the real treetops, and the step at a repainted sky's edge taken out."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import vine_layers  # noqa: E402
import plate_clean  # noqa: E402
from cozy.plate import moon  # noqa: E402

SKY = np.array([30, 55, 105], np.float32)


def sky_img(h=200, w=240):
    a = np.zeros((h, w, 3), np.float32) + SKY
    a += np.linspace(0, 10, h)[:, None, None]          # lighter toward the horizon
    return a


class StrandMatte(unittest.TestCase):
    def test_a_strand_against_the_sky(self):
        a = sky_img()
        a[:, 110:130] = [90, 110, 30]                     # a green strand hanging down the middle
        hard = np.zeros(a.shape[:2], bool)
        hard[:, 95:145] = True                            # traced loosely: sky on both sides of it
        al, _ = vine_layers.alpha_of(Image.fromarray(a.astype(np.uint8)), hard)
        self.assertGreater(al[:, 114:126].mean(), 0.9)
        self.assertLess(al[:, 96:104].mean(), 0.05)
        self.assertLess(al[:, 136:144].mean(), 0.05)

    def test_a_curtain_keeps_its_leaves_not_the_ruins_behind(self):
        rng = np.random.default_rng(3)
        a = np.zeros((220, 200, 3), np.float32) + [70, 72, 80]       # grey stone ruins behind
        a[60:90, 40:70] = [210, 130, 45]                             # a lit window
        leaf = np.zeros(a.shape[:2], bool)
        for y in range(0, 220, 16):                                   # blocky leaves with gaps between them
            for x in range(20, 180, 16):
                if rng.random() < 0.6:
                    leaf[y:y + 14, x:x + 14] = True
        a[leaf] = [150, 160, 40]
        hard = np.zeros(a.shape[:2], bool)
        hard[:, 15:185] = True                                        # the whole curtain traced as one
        al, _ = vine_layers.alpha_of(Image.fromarray(a.astype(np.uint8)), hard, "leaves")
        inner = np.zeros_like(leaf)
        inner[3:-3, 3:-3] = True
        core_leaf = leaf & ~np.roll(~leaf, 3, 0) & ~np.roll(~leaf, -3, 0) & ~np.roll(~leaf, 3, 1) & ~np.roll(~leaf, -3, 1) & inner
        core_gap = ~leaf & np.roll(~leaf, 3, 0) & np.roll(~leaf, -3, 0) & np.roll(~leaf, 3, 1) & np.roll(~leaf, -3, 1) & hard & inner
        self.assertGreater(al[core_leaf].mean(), 0.85)
        self.assertLess(al[core_gap].mean(), 0.1, "the ruins in the gaps would swing with the leaves")


class Moon(unittest.TestCase):
    def picture(self):
        a = sky_img(240, 320)
        yy, xx = np.mgrid[0:240, 0:320]
        d = np.maximum(np.abs(xx - 200.0) - 18, 0) + np.maximum(np.abs(yy - 90.0) - 22, 0)
        a += 60 * np.exp(-d / 25.0)[..., None] * (d > 0)[..., None]  # its glow on the sky
        a[68:113, 182:219] = [235, 240, 255]                          # a 37 x 45 px moon
        return a

    def test_measures_the_moon_and_its_glow(self):
        a = self.picture()
        sky = np.ones(a.shape[:2], np.float32)
        out, sprite, meta = moon.lift_moon(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), sky, [0.5, 0.2, 0.75, 0.6])
        self.assertAlmostEqual(meta["center"][0], 200.0, delta=1.5)
        self.assertAlmostEqual(meta["center"][1], 90.5, delta=1.5)
        self.assertAlmostEqual(meta["half"][0] * 2, 37, delta=4)
        self.assertGreater(meta["halo"]["rgb"][0][2], meta["halo"]["rgb"][-1][2])    # the glow falls off outward
        self.assertLess(np.asarray(out, np.float32)[90, 200].mean(), 120, "the moon is still on the plate")

    def test_two_moons_each_in_its_own_box_make_one_sprite(self):
        """The Sleeping Hound Inn's Masser (big, dim, red) and Secunda (small, bright, white) move together as one sprite;
        one threshold over both found only the bright one (2026-11-15)."""
        a = sky_img(240, 320)
        yy, xx = np.mgrid[0:240, 0:320]
        big = (xx - 110.0) ** 2 + (yy - 120.0) ** 2 <= 40 ** 2
        a[big] = [120, 85, 80]                                        # dim red, under 0.55 of the white one's light
        small = (xx - 190.0) ** 2 + (yy - 70.0) ** 2 <= 12 ** 2
        a[small] = [240, 242, 250]
        sky = np.ones(a.shape[:2], np.float32)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        one = moon.lift_moon(img, sky, [0.2, 0.2, 0.7, 0.75])[2]
        self.assertLess(one["half"][0] * 2, 30, "one box over both: only the bright one")
        out, sprite, meta = moon.lift_moon(img, sky, [[0.2, 0.3, 0.5, 0.75], [0.53, 0.18, 0.68, 0.42]])
        x0, y0 = meta["sprite"][:2]
        al = np.asarray(sprite)[..., 3]
        self.assertGreater(al[120 - y0, 110 - x0], 200, "the dim moon is in the sprite")
        self.assertGreater(al[70 - y0, 190 - x0], 200, "the bright one too")
        self.assertLess(al[150 - y0, 185 - x0], 30, "the sky between them isn't")
        self.assertAlmostEqual(meta["half"][0] * 2, (202 - 70) + 3, delta=4)
        self.assertLess(np.asarray(out, np.float32)[120, 110].mean(), 80, "the dim moon is still on the plate")

    def test_an_outline_takes_the_unlit_side_too(self):
        """Masser's unlit side shows as a dim disk a little darker than the sky beside its lit side: no brightness
        threshold takes it, its outline measured by hand does (hand.json moon polys, 2026-11-15)."""
        a = sky_img(240, 320)
        yy, xx = np.mgrid[0:240, 0:320]
        disk = (xx - 160.0) ** 2 + (yy - 120.0) ** 2 <= 50 ** 2
        a[disk & (xx >= 160)] = [200, 170, 160]                       # the lit half
        a[disk & (xx < 160)] -= 6                                     # the unlit half, darker than the sky
        sky = np.ones(a.shape[:2], np.float32)
        img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        box = [0.4, 0.2, 0.75, 0.8]
        found = moon.lift_moon(img, sky, box)[2]
        self.assertLess(found["half"][0], 30, "by brightness: the lit half only")
        poly = [[(160 + 50 * np.cos(t)) / 320, (120 + 50 * np.sin(t)) / 240] for t in np.linspace(0, 2 * np.pi, 48, endpoint=False)]
        out, sprite, meta = moon.lift_moon(img, sky, box, polys=[poly], grow=2)
        x0, y0 = meta["sprite"][:2]
        al = np.asarray(sprite)[..., 3]
        self.assertGreater(al[120 - y0, 125 - x0], 200, "the unlit half is in the sprite")
        self.assertAlmostEqual(meta["center"][0], 160, delta=2)
        self.assertAlmostEqual(meta["half"][0], 53, delta=3)

    def test_the_moon_shows_only_where_the_sky_really_is(self):
        a = sky_img(240, 320)
        a[170:, :] = [18, 30, 22]                         # the treetops' real edge at row 170
        sky = np.zeros(a.shape[:2], np.float32)
        sky[:150] = 1                                     # the analysis's outline 20 px higher
        m = moon.air_matte(Image.fromarray(a.astype(np.uint8)), sky, box=(0, 0, 1, 1), band=40)
        col = m[:, 160]
        self.assertGreater(col[160:166].mean(), 0.8, "the sky between the outline and the treetops")
        self.assertLess(col[176:200].mean(), 0.1, "the treetops")


class RepaintEdge(unittest.TestCase):
    def test_a_lighter_repaint_meets_the_sky_around_it(self):
        a = sky_img(300, 300)
        yy, xx = np.mgrid[0:300, 0:300]
        disk = (xx - 150) ** 2 + (yy - 120) ** 2 <= 90 ** 2
        a[disk] += 7                                      # the model's sky came out lighter
        mask = disk.astype(np.float32)
        out = np.asarray(plate_clean.match_edge(Image.fromarray(a.astype(np.uint8)), mask, np.ones_like(disk)), np.float32)
        r = np.hypot(xx - 150, yy - 120)
        step = lambda img: img[(r > 70) & (r < 85)][:, 2].mean() - img[(r > 96) & (r < 110)][:, 2].mean()  # noqa: E731
        self.assertGreater(step(a), 6)
        self.assertLess(abs(step(out)), 2.0)


if __name__ == "__main__":
    unittest.main()
