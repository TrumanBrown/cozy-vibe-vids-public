"""The spruce cabin's pendulum clock (2026-11-06) and its snow: the clock ticks each time the pendulum the picture swings
(src/library/vines.js, a rigid strand) passes the middle of its arc, tick and tock in turn, repeating with the loop;
and the snow clean-up (cozy/plate/derain.py desnow) takes painted flakes hanging alone in the air but never the
painting's own bright detail: the moon's corners, the frost at a pane's edge, the highlights on snow-laden trees."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.audio.ambience import Ambience, make_cfg  # noqa: E402
from cozy.plate.derain import cleanup  # noqa: E402


def clock_tl(clock, period=1200):
    return {"seed": 7, "loopSeconds": 120, "duration": 3600, "loop": {"period": period}, "events": [],
            "audio": {"bed": "cabin_snow", **({"clock": clock} if clock else {})}}


class ClockTicks(unittest.TestCase):
    def test_a_tick_each_swing_through_the_middle(self):
        tl = clock_tl({"hz": 0.5, "phase": 0.0, "pan": 0.06, "db": -24})
        amb = Ambience(tl, make_cfg(tl))
        ts = [t for t, _w in amb.ticks(100.0, 110.0)]
        # vines.js: deg * sin(2 pi n t / P + phase), n = round(hz * P) = 600 swings a period: the middle every 1 s
        self.assertEqual(ts, [float(t) for t in range(100, 110)])

    def test_the_phase_moves_them_like_the_pendulum(self):
        tl = clock_tl({"hz": 0.5, "phase": np.pi / 2, "db": -24})
        ts = [t for t, _w in Ambience(tl, make_cfg(tl)).ticks(10.0, 13.0)]
        # sin(pi t + pi/2) is 0 at t = 0.5, 1.5, ...
        self.assertTrue(np.allclose(ts, [10.5, 11.5, 12.5]), ts)

    def test_tick_and_tock_take_turns_and_repeat_with_the_loop(self):
        tl = clock_tl({"hz": 0.5, "phase": 0.0, "db": -24})
        amb = Ambience(tl, make_cfg(tl))
        a = amb.ticks(0.0, 4.0)
        bank = amb._event_cache["clock"]
        kinds = [next(k for k in (0, 1) if any(w is v for v in bank[k])) for _t, w in a]
        self.assertEqual(kinds, [0, 1, 0, 1])
        b = Ambience(tl, make_cfg(tl)).ticks(1200.0, 1204.0)
        self.assertTrue(all(np.array_equal(x[1], y[1]) for x, y in zip(a, b)), "a loop period later the ticks differ")

    def test_the_tock_is_lower(self):
        from cozy.audio.events import clock_tick
        from cozy.audio.ambience import rng

        def centroid(x):
            s = np.abs(np.fft.rfft(x))
            f = np.fft.rfftfreq(len(x), 1 / 48000)
            return float((s * f).sum() / s.sum())
        tick = np.mean([centroid(clock_tick(rng(7, 32, v, 0), False)) for v in range(4)])
        tock = np.mean([centroid(clock_tick(rng(7, 32, v, 1), True)) for v in range(4)])
        self.assertLess(tock, tick)

    def test_no_clock_no_ticks(self):
        tl = clock_tl(None)
        self.assertIsNone(Ambience(tl, make_cfg(tl)).clock)


class Desnow(unittest.TestCase):
    def picture(self):
        # 4K wide: the filter's kernels are sized for a 4K plate
        a = np.full((400, 3840, 3), (20, 30, 70), np.uint8)      # a night sky
        a[100:180, 380:460] = (235, 240, 255)                    # a square moon
        a[300:400, 0:3840] = (225, 230, 240)                     # snow on the ground
        a[296:300, 200:204] = (250, 250, 255)                    # a highlight on the snow's edge
        for x, y in ((80, 60), (200, 150), (300, 220), (520, 250)):
            a[y:y + 3, x:x + 3] = (245, 245, 250)                # flakes hanging alone in the air
        a[40:46, 6:12] = (230, 235, 245)                         # frost at the view's edge
        return a

    def test_flakes_go_and_the_paintings_detail_stays(self):
        a = self.picture()
        view = np.ones(a.shape[:2], np.float32)
        view[:, :4] = 0                                          # a window frame: the view starts beside it
        out = np.asarray(cleanup(Image.fromarray(a), {"desnow": True}, view))
        for x, y in ((80, 60), (200, 150), (300, 220), (520, 250)):
            self.assertLess(out[y + 1, x + 1].mean(), 120, f"the flake at ({x}, {y}) is still there")
        self.assertTrue(np.array_equal(out[100:180, 380:460], a[100:180, 380:460]), "the moon changed (its corners)")
        self.assertTrue(np.array_equal(out[294:302, 196:208], a[294:302, 196:208]), "the highlight on the snow changed")
        self.assertTrue(np.array_equal(out[38:48, 4:14], a[38:48, 4:14]), "the frost at the view's edge changed")


class DesnowDraft(unittest.TestCase):
    """analyze_plate turns the snow clean-up on for a snowy plate, except on a look drawn by hand: on the Yuzu Spring's
    colored pencil (2026-11-12) it took 18% of the drawing's light strokes for painted flakes."""

    def flags(self, aes, weather="gentle snow"):
        import analyze_plate as AP
        ov = {}
        AP._mask_flags(aes, {}, [], ov, [], None, weather)
        return ov

    def test_a_blocky_snowy_plate_is_desnowed(self):
        self.assertTrue(self.flags({"style": "voxel"}).get("desnow"))

    def test_a_hand_drawn_snowy_plate_is_not(self):
        self.assertNotIn("desnow", self.flags({"thumb": {"painterly": {"why": "drawn by hand"}}}))

    def test_no_snow_no_desnow(self):
        self.assertNotIn("desnow", self.flags({"style": "voxel"}, "clear night"))


class SnowDraft(unittest.TestCase):
    """analyze_plate's scene draft: snow seen through a room's windows starts past the glass (L193) and is in focus,
    denser and whiter (the cabin's sample v4 was too faint to judge); snow around an outdoor camera keeps its near,
    soft flakes."""

    def snow(self, indoor):
        import analyze_plate as AP
        d = AP.draft_scene("x", {"weather": "snowing", "aesthetic": "minecraft-voxel"}, {}, {"weather_outside": "snow", "indoor": indoor},
                           [], None, None, True, 3840, 2160)
        return [L for L in d["layers"] if L.get("mode") == "snow"][0]

    def test_a_rooms_snow_is_in_focus_past_the_glass(self):
        s = self.snow(True)
        self.assertGreaterEqual(s["depth"][0], 4.0)
        self.assertLessEqual(s["focus"], 12)
        self.assertLessEqual(s["coc"], 10)
        self.assertGreaterEqual(s["count"], 12000)

    def test_outdoor_snow_keeps_the_defaults(self):
        s = self.snow(False)
        self.assertEqual(s["depth"][0], 1.5)
        self.assertNotIn("focus", s)


if __name__ == "__main__":
    unittest.main()
