r"""Surf on a painted sea (the tide pool, 2026-11-05): the waves on the timeline, the surf map, and the surf's sound
following the same waves (free, offline, a few seconds):

  .venv\Scripts\python -m unittest discover -s tests -p test_surf.py -v

The painted foam of the far surf would have sat frozen (nothing that moves in reality may, L01): the timeline has a wave
every ~11 s (src/library/timeline/ambient.js surf), plate.js brings the painted foam in with each (cozy/plate/surf.py
writes its map) and the coast_fog bed's surf layer swells with the same waves (cozy/audio/ambience.py).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

JS = r"""
import { pathToFileURL } from 'node:url';
const { buildTimeline } = await import(pathToFileURL(process.argv[2]).href);
const tl = buildTimeline({ surf: { perHour: 330, first: 2 }, loop: { period: 1200 } }, { seed: 7, duration: 3600, fps: 30, loopSeconds: 120 });
console.log(JSON.stringify(tl.events.filter((e) => e.type === 'surf').map((e) => [e.t, e.amp, e.peel])));
"""


def surf_waves():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "probe.mjs"
        f.write_text(JS, encoding="utf-8")
        out = subprocess.run(["node", str(f), str(ROOT / "src" / "library" / "timeline.js")], capture_output=True, text=True, check=True)
    return np.array(json.loads(out.stdout))


class Waves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = surf_waves()

    def test_a_wave_every_eleven_seconds_or_so_and_none_crowded(self):
        t = self.w[:, 0]
        one = t[(t >= 0) & (t < 1200)]
        self.assertEqual(len(one), 110)
        g = np.diff(np.sort(t))
        self.assertGreaterEqual(g.min(), 5.9, "two waves on top of each other")
        self.assertLess(g.max(), 40, "a long quiet stretch")

    def test_the_opening_and_the_loop_join(self):
        """The first wave breaks at 2 s of every period (the opening), and the gap across the join is like the others:
        the loop's repair dropped the stream's first waves before (16 s without a wave at the start)."""
        t = np.sort(self.w[:, 0])
        for k in (0, 1, 2):
            first = t[t >= 1200 * k][0] - 1200 * k
            self.assertAlmostEqual(first, 2.0, places=2)
        join = t[t >= 1200][0] - t[t < 1200][-1]
        self.assertLess(join, 30)
        self.assertGreater(join, 5.9)

    def test_strengths_and_peel(self):
        a, p = self.w[:, 1], self.w[:, 2]
        self.assertTrue(((a > 0.3) & (a <= 1)).all())
        self.assertTrue(set(p) <= {-1, 1} and len(set(p)) == 2)


class SurfMap(unittest.TestCase):
    def test_a_painted_sea(self):
        """A dark sea with two bright foam lines and a dark rock: the foam is found on the lines only (never the rock), the
        water under it is darker than the foam, and shoreward runs 0.02 at the zone's far edge to 1 at its near edge."""
        from cozy.plate.surf import surf_maps
        W, H = 640, 360
        img = np.full((H, W, 3), (70, 84, 104), np.uint8)
        img[120:126, 100:500] = (212, 218, 226)
        img[200:205, 150:450] = (205, 212, 222)
        img[150:190, 520:600] = (40, 40, 42)
        zone = [[0.1, 0.25], [0.97, 0.25], [0.97, 0.75], [0.1, 0.75]]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            surf_maps(Image.fromarray(img), {"zone": zone, "foam": [70, 99]}, None, out)
            m = np.asarray(Image.open(out / "surf.png")).astype(np.float32) / 255
            self.assertTrue((out / "surf_preview.jpg").exists())
        foam, share, s = m[..., 3], m[..., 2], m[..., 0]
        self.assertGreater(foam[123, 300], 0.8)
        self.assertGreater(foam[202, 300], 0.8)
        self.assertLess(foam[170, 560], 0.05, "a rock taken for foam")
        self.assertLess(foam[160, 300], 0.05)
        self.assertLess(share[123, 300], 0.6, "the water under the foam must be darker than the foam")
        self.assertAlmostEqual(float(share[160, 300]), 1.0, places=2)
        self.assertEqual(float(s[30, 300]), 0.0, "outside the zone")
        self.assertAlmostEqual(float(s[91, 300]), 0.02, delta=0.02)
        self.assertGreater(float(s[268, 300]), 0.95)
        self.assertGreater(s[200, 300], s[130, 300])

    def test_the_layer_maps_rock_open_water_and_spray_spots(self):
        """surf_fx.png: rock where the dark rock is, the wash on the open water and never on the rock; surf.json: a spray
        spot on the rock's seaward top edge, and the zone's edges that time it like the shader (shoreward from surf.png)."""
        from cozy.plate.surf import surf_maps
        W, H = 640, 360
        img = np.full((H, W, 3), (70, 84, 104), np.uint8)
        img[120:126, 100:500] = (212, 218, 226)
        img[150:190, 520:600] = (40, 40, 42)
        zone = [[0.1, 0.25], [0.97, 0.25], [0.97, 0.75], [0.1, 0.75]]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            surf_maps(Image.fromarray(img), {"zone": zone}, None, out)
            fx = np.asarray(Image.open(out / "surf_fx.png")).astype(np.float32) / 255
            meta = json.loads((out / "surf.json").read_text(encoding="utf-8"))
            s = np.asarray(Image.open(out / "surf.png")).astype(np.float32)[..., 0] / 255
            self.assertTrue((out / "surf_fx_preview.jpg").exists())
        wash, rock = fx[..., 0], fx[..., 1]
        self.assertGreater(rock[170, 560], 0.9)
        self.assertLess(rock[170, 300], 0.1)
        self.assertGreater(wash[170, 300], 0.9)
        self.assertLess(wash[170, 560], 0.1, "white water drawn over the rock")
        self.assertLess(wash[30, 300], 0.05, "outside the zone")
        spots = meta["spots"]
        on = [p for p in spots if 520 / W <= p["x"] <= 600 / W]
        self.assertTrue(on, spots)
        self.assertTrue(all(abs(p["y"] - 150 / H) < 4 / H for p in on), on)
        self.assertTrue(all(0 < p["min"] < 1 and p["h"] > 0 for p in on))
        e = meta["edges"]
        r = W / 3840
        i = round(300 / r / e["step"])
        sh = (170 / r - e["top"][i]) / (e["bot"][i] - e["top"][i])
        self.assertAlmostEqual(sh, (s[170, 300] - 0.02) / 0.98, delta=0.02)

    def test_a_character_in_the_sea_is_masked_to_its_outline(self):
        """A character standing in the sea is no sea (surf.png R 0: the foam skips it and never pulls it into the
        water), and the masks stop at its outline: grown 9 and then 7 px, the white water stopped short of the
        oystercatcher all around it (2026-11-05)."""
        import cv2
        from cozy.plate.surf import surf_maps
        W, H = 640, 360
        img = np.full((H, W, 3), (70, 84, 104), np.uint8)
        img[120:126, 100:500] = (212, 218, 226)
        held = np.zeros((H, W), bool)
        cv2.circle(held.view(np.uint8), (300, 180), 20, 1, -1)
        img[held] = (20, 20, 22)
        zone = [[0.1, 0.25], [0.97, 0.25], [0.97, 0.75], [0.1, 0.75]]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            surf_maps(Image.fromarray(img), {"zone": zone}, held, out)
            s = np.asarray(Image.open(out / "surf.png")).astype(np.float32)[..., 0] / 255
            fx = np.asarray(Image.open(out / "surf_fx.png")).astype(np.float32) / 255
        self.assertEqual(float(s[180, 300]), 0.0)
        self.assertGreater(float(s[180, 300 + 24]), 0.1, "the sea right outside it")
        self.assertGreater(float(fx[180, 300, 2]), 0.9, "it stands in front")
        self.assertLess(float(fx[180, 300 + 24, 2]), 0.1, "the front mask reaches past its outline")

    def test_the_trace_hugs_the_painted_outline(self):
        """The character mask comes from the traced polygons (regions.png holds each grown by its feather, ~6 px), and
        the trace's slack that shows the sea goes back to the sea (tighten): the white water stopped in straight lines
        8 px off the oystercatcher's legs, a box between them (2026-11-05)."""
        import cv2
        from cozy.plate.regions import render_regions
        from cozy.plate.surf import held_mask
        W, H = 3840, 800
        img = np.full((H, W, 3), (120, 135, 150), np.uint8)
        cv2.rectangle(img, (1900, 300), (1909, 500), (200, 110, 90), -1)        # a painted leg 10 px wide
        leg = [[[1895 / W, 290 / H], [1915 / W, 290 / H], [1915 / W, 510 / H], [1895 / W, 510 / H]]]   # traced 5 px wide of it
        regs = [{"name": "bird", "kind": "pet", "polys": leg}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            meta = render_regions(regs, np.full((H, W), 0.5, np.float32), W, H, out)
            loose = held_mask(out, meta)
            tight = held_mask(out, meta, polys=regs, plate=Image.fromarray(img))
        row = 400
        lw, tw = np.nonzero(loose[row])[0], np.nonzero(tight[row])[0]
        self.assertLessEqual(int(lw[0]), 1889)                     # feathered and grown: about 8 px past the trace
        self.assertGreaterEqual(int(tw[0]), 1897)                  # the leg's own edge (1900) and its 2 px grow
        self.assertLessEqual(int(tw[-1]), 1912)
        self.assertTrue(tight[row, 1900:1910].all(), "the painted leg stays in front")

    def test_the_room_the_foam_comes_from(self):
        """surf_room.png: how far the plate's foam may come from (straight up the frame) at each pixel, half the way to
        a character or past the zone's far edge, less 3 px; smooth, never jumping (a hard fallback left boxes under the
        oystercatcher's belly, 2026-11-05). The near shore below the zone is never looked toward."""
        from cozy.plate.surf import ROOM_SCALE, room_map, surf_maps
        W, H = 3840, 600
        zone = np.zeros((H, W), bool)
        zone[100:500, 200:3600] = True
        held = np.zeros((H, W), bool)
        held[250:300, 1000:1040] = True                                # a character in the sea
        room = room_map(zone, held)
        self.assertEqual(float(room[275, 1020]), 0.0)
        self.assertEqual(float(room[50, 2000]), 0.0, "outside the zone")
        self.assertAlmostEqual(float(room[300 + 13, 1020]), 0.5 * (14 - 3), delta=0.6)   # 14 px below the character
        self.assertAlmostEqual(float(room[100 + 23, 2000]), 0.5 * (24 - 3), delta=0.6)   # 24 px below the far edge
        self.assertEqual(float(room[499, 2000]), 255 / ROOM_SCALE, "the near edge is no limit")
        col = room[300:360, 1020]
        self.assertLessEqual(float(np.abs(np.diff(col)).max()), 0.51, "no jumps down the column")
        across = room[320, 960:1080]
        self.assertLessEqual(float(np.abs(np.diff(across)).max()), 0.51, "nor across it")
        img = np.full((H, W, 3), (70, 84, 104), np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            surf_maps(Image.fromarray(img), {"zone": [[200 / W, 100 / H], [3600 / W, 100 / H], [3600 / W, 500 / H], [200 / W, 500 / H]]},
                      held, out)
            saved = np.asarray(Image.open(out / "surf_room.png")).astype(np.float32) / ROOM_SCALE
        self.assertAlmostEqual(float(saved[313, 1020]), float(room[313, 1020]), delta=0.2)


@unittest.skipUnless(shutil.which("node"), "node isn't on PATH")
class Spray(unittest.TestCase):
    """The spray a wave throws off a rock (src/library/surf.js plume) and when (arrival, shoreAt)."""

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", str(ROOT / "tests" / "js_walk_surf.mjs")], cwd=ROOT, capture_output=True, text=True, check=True)
        cls.p = json.loads(r.stdout)

    def test_only_a_wave_big_enough_throws_spray_and_only_for_a_while(self):
        pl = self.p["plume"]
        self.assertEqual((pl["before"], pl["after"], pl["small"]), (0, 0, 0))
        self.assertTrue(pl["rise"])
        self.assertEqual(pl["rise"], pl["again"], "the same wave throws the same spray")

    def test_it_rises_from_the_rock_and_leaves_mist(self):
        sp = self.p["spot"]
        body = [b for b in self.p["plume"]["rise"] if b[6] == 0]
        self.assertTrue(body)
        for x, y, r, a, tx, ty, _k in body:
            self.assertLessEqual(y, sp["y"] + 1, "spray below the rock's top edge")
            self.assertLessEqual(ty, sp["y"] + 1)
            self.assertLess(abs(x - sp["x"]), 1.5 * sp["w"], "spray thrown far off its rock")
            self.assertGreater(y, sp["y"] - 1.6 * sp["h"], "spray higher than the biggest wave's")
            self.assertTrue(0 < a <= 1 and r > 0)
        late = self.p["plume"]["late"]
        self.assertTrue(late and all(b[6] == 1 for b in late), "by 3.5 s the spray has fallen and only its mist drifts")

    def test_timing_and_the_zone_coordinates(self):
        a, b = self.p["arrival"]
        self.assertAlmostEqual(a, 10 - 1 + 0.5 * 2.6 + 0.25 * 1.6)
        self.assertAlmostEqual(b, 10 - 1 + 0.5 * 2.6 + 0.75 * 1.6)
        near, off = self.p["shore"]
        self.assertAlmostEqual(near["s"], (1000 - self.p["edges"]["top"]) / (self.p["edges"]["bot"] - self.p["edges"]["top"]), places=6)
        self.assertAlmostEqual(near["along"], (2000 - 1400) / (3839 - 1400), places=6)
        self.assertEqual((off["s"], off["along"]), (1, 0), "clamped outside the zone")


class Sound(unittest.TestCase):
    def test_the_surf_swells_with_each_wave(self):
        """The coast bed's surf layer is loudest a second or two after each wave breaks and quietest just before the next."""
        from cozy.audio.ambience import Ambience, make_cfg
        tl = {"seed": 7, "loopSeconds": 120, "duration": 600, "audio": {"bed": "coast_fog"},
              "events": [{"type": "surf", "t": 4.0, "amp": 0.9, "peel": 1, "pan": 0.0, "id": 0},
                         {"type": "surf", "t": 16.0, "amp": 0.6, "peel": -1, "pan": 0.3, "id": 1}]}
        amb = Ambience(tl, make_cfg(tl))
        layers = amb.block(0, layers=True)
        x = layers["surf"]
        sr = x.shape[0] // 15
        rms = lambda a, b: float(np.sqrt((x[int(a * sr): int(b * sr)] ** 2).mean()))  # noqa: E731
        self.assertGreater(rms(4.5, 6.0), 2.0 * rms(2.5, 3.8), "no swell as the wave breaks")
        self.assertGreater(rms(4.5, 6.0), 1.3 * rms(13.0, 14.5), "the swell never settles before the next wave")
        self.assertNotIn("wash", layers, "the coast bed has no rain")


if __name__ == "__main__":
    unittest.main()
