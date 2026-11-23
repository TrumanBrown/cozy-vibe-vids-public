"""The hot spring's sound bed (2026-11-12): hotspring_snow, the Yuzu Spring's bamboo spout pouring into the pool (a CC0
recording looped seamlessly, cozy/audio/recorded.py), a faint breeze and a quiet night, kept by choose_bed in snow while
every other look still gets the snowy cabin. Free, offline (ffmpeg decodes the recording), a few seconds.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_hotspring_bed.py -v
"""
import csv
import hashlib
import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.audio.ambience import BEDS, LAYER, Ambience, choose_bed, make_cfg  # noqa: E402
from cozy.audio.dsp import SR  # noqa: E402
from cozy.audio.recorded import RECORDINGS, seamless_loop  # noqa: E402
from cozy.publish.words import RECORDED  # noqa: E402


def spring_tl(seed=7):
    return {"seed": seed, "loopSeconds": 120, "duration": 3600, "events": [], "audio": {"bed": "hotspring_snow"}}


def amb(seed=7):
    tl = spring_tl(seed)
    a = Ambience(tl, make_cfg(tl))
    a.master = 0.0
    return a


def rms_db(x):
    return 20 * np.log10(np.sqrt((np.asarray(x) ** 2).mean()) + 1e-12)


class Bed(unittest.TestCase):
    def test_the_spring_keeps_its_own_bed_in_snow(self):
        self.assertEqual(choose_bed("hotspring_snow", "gentle snow", False, False), ("hotspring_snow", {}))
        self.assertEqual(choose_bed("hotspring_snow", "light snow at night", True, False), ("hotspring_snow", {"fire": -2.0}))
        # rain or a clear night: what any look without a bed for that weather gets
        self.assertEqual(choose_bed("hotspring_snow", "light rain", False, False)[0], "porch_rain")
        self.assertEqual(choose_bed("hotspring_snow", "clear night", False, False)[0], "quiet_night")

    def test_every_other_bed_still_gets_the_snowy_cabin(self):
        for bed in BEDS:
            if BEDS[bed].get("snow"):
                continue
            for fire in (True, False):
                with self.subTest(bed=bed, fire=fire):
                    self.assertEqual(choose_bed(bed, "heavy snow", fire, False), ("cabin_snow", {} if fire else {"fire": None}))
        self.assertEqual([k for k, v in BEDS.items() if v.get("snow")], ["hotspring_snow"])

    def test_the_bed_is_the_spout_a_breeze_and_the_night(self):
        b = BEDS["hotspring_snow"]
        self.assertEqual(b["rain"], [])
        self.assertEqual(set(b["extra"]), {"spout", "howl", "room"})
        self.assertEqual(LAYER["spout"], 39)
        self.assertEqual(len(set(LAYER.values())), len(LAYER), "a layer id used twice")
        self.assertNotIn(35, LAYER.values(), "35 is retired (the river's bubbles)")
        lay = amb().block(5, layers=True)
        p = {k: float((v ** 2).mean()) for k, v in lay.items()}
        self.assertGreater(p["spout"] / sum(p.values()), 0.85, "the pour carries the bed")
        self.assertNotIn("fire", lay)

    def test_the_recording_is_logged_before_use(self):
        """AGENTS.md: every external asset has its ledger row (CC0) and its file is the one logged (pinned sha1)."""
        for layer, spec in RECORDINGS.items():
            with self.subTest(layer=layer):
                p = ROOT / spec["path"]
                self.assertEqual(hashlib.sha1(p.read_bytes()).hexdigest(), spec["sha1"])
                side = json.loads(Path(f"{p}.json").read_text(encoding="utf-8"))
                self.assertIn("CC0", side["license"])
                self.assertEqual(side["sha1"], spec["sha1"])
                with open(ROOT / "docs" / "asset-ledger.csv", newline="", encoding="utf-8") as f:
                    row = next((r for r in csv.DictReader(f) if r["path"] == spec["path"]), None)
                self.assertIsNotNone(row, f"{spec['path']} isn't in docs/asset-ledger.csv")
                self.assertIn("CC0", row["license"])
                self.assertTrue(row["attribution"].lower().startswith("none"), "credits.txt would carry it on every video")
        self.assertEqual(set(RECORDED), set(RECORDINGS), "a recorded layer without its words for the blurb, or the other way")


class Spout(unittest.TestCase):
    def test_a_block_is_the_same_alone_or_in_sequence(self):
        a = amb()
        seq = [a.block(b, layers=True)["spout"] for b in (3, 4, 5)]
        alone = amb().block(4, layers=True)["spout"]
        self.assertTrue(np.array_equal(seq[1], alone))
        self.assertTrue(np.array_equal(amb().block(4, layers=True)["spout"], alone), "not deterministic")

    def test_any_range_is_a_slice_of_a_longer_render(self):
        a = amb()
        long = a.render(100.0, 25.0)["rain"]
        part = amb().render(107.5, 10.0)["rain"]
        i = int(round(7.5 * SR))
        self.assertTrue(np.allclose(part, long[i: i + len(part)], rtol=0, atol=1e-12))

    def test_the_loops_join_without_a_click_or_a_bump(self):
        """Each loop's end runs into its start: the jump there is an ordinary step, and the 20 ms windows across the
        join are as loud as the loop's own (no dip or swell from the crossfade)."""
        r = amb().rec["spout"]
        for lp in r.loops:
            with self.subTest(n=len(lp)):
                d = np.abs(np.diff(lp, axis=0)).max(1)
                jump = float(np.abs(lp[0] - lp[-1]).max())
                self.assertLessEqual(jump, float(np.percentile(d, 99.5)), "a click at the join")
                w = int(0.02 * SR)
                ring = np.concatenate([lp, lp[: 4 * w]])
                e = np.sqrt((ring[: len(ring) // w * w].reshape(-1, w, 2) ** 2).mean(axis=(1, 2)))
                k = len(lp) // w
                across = e[k - 2: k + 3]
                lo, hi = np.percentile(e[: k - 3], [1, 99])
                self.assertTrue(np.all((across >= lo * 0.9) & (across <= hi * 1.1)), f"{across} outside {lo:.3f}-{hi:.3f}")
                self.assertTrue(np.array_equal(r.read(np.arange(5, dtype=np.int64)), r.read(np.arange(5, dtype=np.int64) + len(r.loops[0]) * len(r.loops[1]))))

    def test_the_level_breathes_but_never_surges(self):
        a = amb()
        x = np.concatenate([a.block(b, layers=True)["spout"] for b in range(4, 8)])
        n = 3 * SR
        st = np.array([rms_db(x[i: i + n]) for i in range(0, len(x) - n, SR // 2)])
        self.assertLess(float(st.max() - st.min()), 6.0)
        self.assertLess(float(np.abs(np.diff(st)).max()), 1.5, "a jump in level between half-second steps")

    def test_two_unequal_loops_from_two_halves(self):
        r = amb().rec["spout"]
        (a0, L0), (a1, L1) = r.cuts
        self.assertNotEqual(L0, L1)
        self.assertLessEqual(a0 + L0, a1 - int(RECORDINGS["spout"]["xf"] * SR) + int(0.5 * SR), "the loops share audio")
        self.assertGreater(min(L0, L1) / SR, 9.0)

    def test_a_scene_can_move_the_spout(self):
        tl = spring_tl()
        tl["audio"]["spout_pan"] = -0.5
        left = Ambience(tl, make_cfg(tl)).block(5, layers=True)["spout"]
        right = amb().block(5, layers=True)["spout"]
        self.assertGreater(rms_db(left[:, 0]), rms_db(left[:, 1]))
        self.assertGreater(rms_db(right[:, 1]), rms_db(right[:, 0]) + 3.0, "the spout sits right of center")

    def test_seamless_loop_finds_the_matching_join(self):
        """Noise that is loud in one stretch: the loop is cut where its two sides match, never across the loud part."""
        g = np.random.default_rng(3)
        x = g.standard_normal((30 * SR, 2)) * 0.1
        x[12 * SR: 14 * SR] *= 4.0
        loop, a, L = seamless_loop(x, 8.0, 10.0, 2.0)
        self.assertEqual(len(loop), L)
        self.assertTrue(8.0 * SR <= L <= 10.0 * SR)
        loud = (12 * SR, 14 * SR)
        xf = (a + L - 2 * SR, a + L)
        self.assertFalse(xf[0] < loud[1] and loud[0] < xf[1], "the crossfade lies on the loud stretch")
        self.assertFalse(a - 2 * SR < loud[1] and loud[0] < a, "the audio before the start lies on the loud stretch")


class Calibration(unittest.TestCase):
    def test_the_key_holds_the_recording_only_where_it_plays(self):
        """Other beds keep their calibration key (no recording in it, so no scene re-calibrates); the spring's holds the
        recording's file, its sha1 and the loops' version, so a new recording or new cuts re-calibrate it."""
        from cozy.audio.recorded import LOOP_V
        for bed in BEDS:
            if bed != "hotspring_snow":
                self.assertFalse(set(RECORDINGS) & set(BEDS[bed]["extra"]), bed)
        tl = {"seed": 7, "loopSeconds": 120, "duration": 3600, "events": [], "audio": {"bed": "quiet_night"}}
        self.assertEqual(Ambience(tl, make_cfg(tl)).rec, {})
        key = json.dumps(amb().rec["spout"].key)
        for part in (RECORDINGS["spout"]["sha1"], RECORDINGS["spout"]["path"], f'"spout", {LOOP_V}'):
            self.assertIn(part, key)


if __name__ == "__main__":
    unittest.main()
