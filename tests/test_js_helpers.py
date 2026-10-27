r"""One RNG and shared helpers in the JS (TASKS.md T20): free, offline, a few seconds.

  .venv\Scripts\python -m unittest discover -s tests -p test_js_helpers.py -v

tests/js_helpers.mjs keeps the copies src/ used to write more than once, as they were, and compares each with the one
version src/ uses now over many inputs.

mulberry32 was written three ways: engine/rng.js, the timeline's own, and one copy in fire.js, particles.js and rain.js
(another in petsprite.js). The layers' copies kept their state unsigned where rng.js keeps it signed; the bits are the
same, so they give rng.js's numbers for every seed. The timeline's copy left out rng.js's `seed >>> 0`, so it differs
where that matters: negative fractional seeds (-0.5 starts from 0x6d2b79f4, not 0x6d2b79f5), seeds near or past 2^53
(the sum rounds) and NaN, undefined and the infinities. Every timeline call site passes `x >>> 0`, a uint32, and there
the two are the same (test_timeline_copy_on_its_seeds), so the timeline uses rng.js's too. The timeline's hashStr is
rng.js's hashString for every string.

Shared helpers (src/library/util.js, overlay.js), each against the copies it replaced: smooth (timeline, title.js,
perch.js), toLin (leaves.js, moth.js, petals.js), hash (blink.js, perch.js), boxMean (avg in cat3d.js and dog3d.js),
imagePixels (pixelsOf there), instancedQuad (particles.js, steam.js, rain.js), dirLight (cat3d.js, dog3d.js) and loadTex
(boat.js, heron.js, fish.js, leaves.js, rain.js, with the image load left out). The shared hash takes b `| 0` like
perch.js; blink.js added b as it is, which differs only for a b that isn't an integer, and blink.js passes a character
index and slot numbers. Copies that do something else stay where they are: cat3d.js's smooth is a smootherstep,
effects.js's doesn't clamp, smoke.js's hash is another hash, ant.js's box mean takes 5 x 5 samples.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, "node isn't on PATH")
class JsHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "helpers.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_helpers.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True,
                               timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"tests/js_helpers.mjs failed:\n{r.stderr[-2000:]}")
            cls.js = json.loads(out.read_text(encoding="utf-8"))

    def same(self, rec, what):
        self.assertGreater(rec["seeds"], 0)
        self.assertEqual(rec["differ"], 0, f"{what}: {rec['differ']} of {rec['seeds']} seeds give other numbers, e.g. {rec['example']}")

    def test_layer_copies_are_rng_js_for_every_seed(self):
        """fire.js, particles.js and rain.js pass any number (scene seed times a constant plus an offset), petsprite.js a
        wag seed from scene.json."""
        for copy in ("fire_particles_rain", "petsprite"):
            for cls, rec in self.js["rng"][copy].items():
                with self.subTest(copy=copy, seeds=cls):
                    self.same(rec, f"{copy}'s copy against rng.js mulberry32, {cls} seeds")

    def test_timeline_copy_on_its_seeds(self):
        for cls in ("timeline_call_sites", "integer", "negative", "huge", "fractional"):
            with self.subTest(seeds=cls):
                self.same(self.js["rng"]["timeline"][cls], f"the timeline's mulberry32 against rng.js, {cls} seeds")

    def test_timeline_copy_differs_off_its_seeds(self):
        """The seed classes are sharp enough to tell the two apart: the timeline's copy differs where it skipped `>>> 0`."""
        rng = self.js["rng"]["timeline"]
        for cls in ("negative_fractional", "beyond_2_53", "not_a_number"):
            with self.subTest(seeds=cls):
                self.assertGreater(rng[cls]["differ"], 0, f"expected the timeline's copy to differ on {cls} seeds")

    def test_hash(self):
        h = self.js["hash"]
        self.assertGreater(h["strings"], 1000)
        self.assertEqual(h["differ"], 0, f"the timeline's hashStr differs from rng.js hashString, e.g. for {h['example']!r}")

    def test_one_rng(self):
        same = self.js["same"]
        self.assertTrue(same["timeline_mulberry32_is_rng_js"], "src/library/timeline/random.js has its own mulberry32 again")
        self.assertTrue(same["timeline_hashStr_is_rng_js"], "src/library/timeline/random.js has its own hashStr again")
        self.assertEqual(same["mulberry32_written_outside_rng_js"], [], "mulberry32 is written outside src/engine/rng.js again")

    def test_shared_helpers(self):
        shared = self.js["shared"]
        for name in ("smooth_timeline_title", "smooth_perch", "toLin_leaves_moth_petals", "hash_perch", "hash_blink_integer_b",
                     "avg_cat3d_dog3d", "quad_particles_steam", "quad_rain", "dirLight_cat3d_dog3d", "loadTex"):
            with self.subTest(helper=name):
                rec = shared[name]
                self.assertGreater(rec["inputs"], 0)
                self.assertEqual(rec["differ"], 0, f"{name}: {rec['differ']} of {rec['inputs']} inputs give something else, e.g. {rec['example']}")
        self.assertTrue(shared["pixelsOf_is_imagePixels_text"], "cat3d.js and dog3d.js's pixelsOf wasn't overlay.js imagePixels")
        self.assertTrue(shared["smooth_timeline_module"]["same"], "the timeline has its own smooth again")

    def test_blink_hash_differs_off_its_inputs(self):
        """The comparison can tell the two hashes apart: blink.js's differs for a negative fractional b."""
        self.assertGreater(self.js["shared"]["hash_blink_negative_fractional_b"]["differ"], 0)


if __name__ == "__main__":
    unittest.main()
