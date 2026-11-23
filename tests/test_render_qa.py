r"""The render QA's frame alignment on a calm scene (tools/render_qa.py compare; free, offline, about a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_render_qa.py -v

A decoded frame must match its own fresh render better than its neighbors (a dropped or doubled frame at a segment
join matches a neighbor instead). Over the whole frame, the encoding noise of the jungle temple's clear night swamped
the little that changes from one frame to the next, and its sample failed QA with margins of 0.1-0.2 dB (2026-10-27,
L164). Alignment is now decided on the pixels that move: a calm frame passes, and an off-by-one frame still fails.
"""
import contextlib
import io
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import render_qa  # noqa: E402


def frame(k, bg):
    """A still textured scene with one faint patch (15 levels brighter, a firefly's glow or a vine's edge) moving 6 px
    a frame: over the whole frame that change is far below the encoding noise, as on the jungle temple's clear night."""
    f = bg.astype(np.int16)
    x = 100 + 6 * k
    f[80:100, x:x + 20] += 15
    return np.clip(f, 0, 255).astype(np.uint8)


class Alignment(unittest.TestCase):
    def setUp(self):
        self.dir = ROOT / "cache" / "test_render_qa"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        rng = np.random.default_rng(1)
        self.bg = rng.integers(20, 90, (360, 640, 3), dtype=np.uint8)
        self.rng = rng

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def compare(self, decoded_k):
        """Decode frame decoded_k (with encoding-like noise) and compare it with fresh frame 5 and its neighbors."""
        p = {}
        for k in (4, 5, 6):
            p[k] = str(self.dir / f"fresh_{k}.png")
            cv2.imwrite(p[k], frame(k, self.bg))
        noise = self.rng.normal(0, 3.0, self.bg.shape)
        dec = np.clip(frame(decoded_k, self.bg).astype(np.float32) + noise, 0, 255).astype(np.uint8)
        cv2.imwrite(str(self.dir / "dec_5.png"), dec)
        pairs = [{"id": 5, "a": str(self.dir / "dec_5.png"), "b": p[5], "near": [p[4], p[6]]}]
        (self.dir / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
        with mock.patch.object(sys, "argv", ["render_qa.py", "compare", str(self.dir / "pairs.json"), str(self.dir / "out.json")]), \
                contextlib.redirect_stdout(io.StringIO()):
            render_qa.main()
        return json.loads((self.dir / "out.json").read_text(encoding="utf-8"))[0]

    def test_a_calm_frame_is_aligned(self):
        r = self.compare(5)
        # over the whole frame the neighbors match almost as well: the old test's margin was under 0.5 dB
        self.assertLess(r["psnr"] - max(r["near"]), 0.5)
        self.assertTrue(r["aligned"], r)
        self.assertGreater(r["margin_db"], 3.0)

    def test_an_off_by_one_frame_is_caught(self):
        for k in (4, 6):
            r = self.compare(k)
            self.assertFalse(r["aligned"], (k, r))

    def test_a_held_frame_says_nothing(self):
        """Pixel art holds a picture for 2-3 frames: identical neighbors are left out, as before."""
        p = str(self.dir / "same.png")
        cv2.imwrite(p, frame(5, self.bg))
        cv2.imwrite(str(self.dir / "dec.png"), frame(5, self.bg))
        (self.dir / "pairs.json").write_text(json.dumps([{"id": 1, "a": str(self.dir / "dec.png"), "b": p, "near": [p, p]}]),
                                             encoding="utf-8")
        with mock.patch.object(sys, "argv", ["render_qa.py", "compare", str(self.dir / "pairs.json"), str(self.dir / "out.json")]), \
                contextlib.redirect_stdout(io.StringIO()):
            render_qa.main()
        r = json.loads((self.dir / "out.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(r["held"], 2)
        self.assertTrue(r["aligned"])


if __name__ == "__main__":
    unittest.main()
