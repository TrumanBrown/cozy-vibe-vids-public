"""The music planner's per-track cache gives the same numbers as measuring afresh, and refit measures each track's
two edges once (the Spruce Clock Cabin's sample, 2026-11-06: 7 minutes of planning before the first frame).

  .venv\\Scripts\\python -m unittest discover -s tests -p test_music_cache.py -v
"""
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import music  # noqa: E402


def write_track(path, seconds=60, seed=3):
    """A stereo 48 kHz test track: 2 s of silence, a tone with a slow swell and noise, a fade out."""
    r = np.random.default_rng(seed)
    n = int(seconds * music.SR)
    t = np.arange(n) / music.SR
    env = np.clip((t - 2.0) / 4.0, 0, 1) * np.clip((seconds - t) / 8.0, 0, 1) * (0.7 + 0.3 * np.sin(2 * np.pi * t / 17))
    x = env[:, None] * (0.2 * np.sin(2 * np.pi * 220 * t)[:, None] + 0.05 * r.standard_normal((n, 2)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(music.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(music, "CACHE", Path(self.tmp.name) / "cache")
        p.start()
        self.addCleanup(p.stop)
        self.track = Path(self.tmp.name) / "a.wav"
        write_track(self.track)

    def test_analysis_edges_and_peak_match_a_fresh_measure(self):
        cfg = {**music.DEFAULTS, "body_db": 6}
        h, x = music.decoded(str(self.track))
        fresh = music._measure(h, x, cfg)
        cold = music.analyze({"path": str(self.track)}, cfg)
        warm = music.analyze({"path": str(self.track)}, cfg)
        self.assertEqual(fresh, cold)
        self.assertEqual(fresh, warm)
        self.assertEqual([type(v) for v in fresh.values()], [type(v) for v in warm.values()])
        tr = {"path": str(self.track), **warm}
        for side in ("head", "tail"):
            with self.subTest(side=side):
                a = music._edge_env(tr, side, 30.0)
                np.testing.assert_array_equal(a, music.edge_env(tr, side))
                np.testing.assert_array_equal(a, music.edge_env(tr, side))
        tp = music.true_peak(np.asarray(x[warm["in"]: warm["out"]], np.float64))
        self.assertEqual(tp, music.track_peak(tr))
        self.assertEqual(tp, music.track_peak(tr))

    def test_settings_the_analysis_reads_are_part_of_its_key(self):
        a = music.analyze({"path": str(self.track)}, {**music.DEFAULTS})
        b = music.analyze({"path": str(self.track)}, {**music.DEFAULTS, "lufs": -20.0})
        self.assertNotEqual(a["gain_db"], b["gain_db"])
        self.assertEqual(music.analyze({"path": str(self.track)}, {**music.DEFAULTS}), a)


class Refit(unittest.TestCase):
    def test_each_edge_is_measured_once(self):
        calls = []

        def fake(tr, side, secs=30.0):
            calls.append((tr["i"], side))
            return np.ones(300) * (1.0 + tr["i"])
        T = [{"i": i, "dur": 100.0} for i in range(3)]
        doc = {"tracks": T, "entries": [{"track": i} for i in (0, 1, 2)], "duration": 600.0}
        with mock.patch.object(music, "edge_env", side_effect=fake):
            music.refit(doc)
        self.assertGreater(len(doc["entries"]), 6)
        self.assertEqual(sorted(calls), sorted({(i, s) for i in range(3) for s in ("tail", "head")}))


if __name__ == "__main__":
    unittest.main()
