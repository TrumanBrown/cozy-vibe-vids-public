"""The jungle temple's event sounds (lessons L166, L170): the frog's call as its sac swells, and a leaping fish's
re-entry plop at the leap's own time in the air (Treetop's hop keeps its 0.45 s and its length)."""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cozy.audio.dsp import SR  # noqa: E402
from cozy.audio.events import fish_plop, frog_call  # noqa: E402


def onset(x, after=0.0, frac=0.3):
    """The first time (s) after `after` the 5 ms envelope reaches frac of its peak there."""
    e = np.convolve(np.abs(x), np.ones(int(0.005 * SR)) / (0.005 * SR), "same")
    i0 = int(after * SR)
    return (i0 + int(np.argmax(e[i0:] > frac * e[i0:].max()))) / SR


class EventSounds(unittest.TestCase):
    def test_frog_call_is_a_short_note_near_2_khz(self):
        x = frog_call(np.random.default_rng(5))
        self.assertTrue(np.isfinite(x).all())
        self.assertLess(len(x) / SR, 0.4)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        peak = np.fft.rfftfreq(len(x), 1 / SR)[np.argmax(spec)]
        self.assertTrue(1500 < peak < 2600, peak)

    def test_treetop_hop_keeps_its_length(self):
        self.assertEqual(len(fish_plop(np.random.default_rng(1), 1, 1.0)), int(1.6 * SR))

    def test_a_leap_dives_back_in_when_the_fish_does(self):
        x = fish_plop(np.random.default_rng(2), 1, 1.2, air=0.9)
        self.assertAlmostEqual(onset(x, after=0.6, frac=0.5), 0.9, delta=0.05)


if __name__ == "__main__":
    unittest.main()
