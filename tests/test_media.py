"""tools/cozy/media.py (TASKS.md T11): the frame-grab command keeps its order, and failures share one error. Free,
offline, about a second (ffmpeg makes a 3-frame test clip in cache/test_media/, removed after).

  .venv\\Scripts\\python -m unittest discover -s tests -p test_media.py -v
"""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cozy.media as M  # noqa: E402


class Commands(unittest.TestCase):
    def cmd(self, *a, **kw):
        with mock.patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
            M.grab_frame(*a, **kw)
        return run.call_args.args[0]

    def test_grab_frame_order(self):
        # a QA number made from a grab stays the same only if the command does: -ss and -t before -i, then the rest
        self.assertEqual(self.cmd("v.mp4", "1.250", t="4", frames=12, vf="crop=8:8:0:0", pix_fmt="gray"),
                         ["ffmpeg", "-v", "error", "-ss", "1.250", "-t", "4", "-i", "v.mp4", "-frames:v", "12",
                          "-vf", "crop=8:8:0:0", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        self.assertEqual(self.cmd("v.mp4"), ["ffmpeg", "-v", "error", "-i", "v.mp4", "-f", "rawvideo", "-"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg isn't on PATH")
class RealFiles(unittest.TestCase):
    def setUp(self):
        self.d = ROOT / "cache" / "test_media"
        shutil.rmtree(self.d, ignore_errors=True)
        self.d.mkdir(parents=True)
        self.clip = self.d / "clip.mp4"
        M.run_ffmpeg(["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10", "-frames:v", "3",
                      "-pix_fmt", "yuv420p", str(self.clip)])

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_probe_and_grab(self):
        s = M.probe(self.clip, "stream=width,height,nb_frames", streams="v:0")["streams"][0]
        self.assertEqual((s["width"], s["height"], s["nb_frames"]), (64, 36, "3"))
        self.assertEqual(len(M.grab_frame(self.clip, "0.000", frames=2, pix_fmt="rgb24")), 2 * 64 * 36 * 3)

    def test_one_error(self):
        missing = self.d / "missing.mp4"
        for call in (lambda: M.run_ffmpeg(["-v", "error", "-i", str(missing), "-f", "null", "-"]),
                     lambda: M.probe(missing, "format=duration"), lambda: M.grab_frame(missing, "0")):
            with self.assertRaises(subprocess.CalledProcessError) as e:
                call()
            self.assertIsInstance(e.exception, M.MediaError)
            self.assertRegex(str(e.exception), r"^ff(mpeg|probe) exited \d+: .*missing\.mp4")
        self.assertEqual(M.probe(missing, "format=duration", check=False), {})
        self.assertEqual(M.grab_frame(missing, "0", check=False), b"")


if __name__ == "__main__":
    unittest.main()
