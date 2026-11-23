"""Fonts are fetched once and must be the files every video so far used (config/fonts.json sha256), with the network
mocked: nothing is downloaded and cache/fonts is left alone.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_fonts.py -v
"""
import contextlib
import hashlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import intro_title as IT  # noqa: E402
from cozy.paths import config  # noqa: E402

FONTS = config("fonts")["fonts"]
FID = "comic-neue"


class Fonts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        p = mock.patch.object(IT, "FONTS", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def serve(self, font):
        """urlopen answering the font's URL with `font` and its license URL with a license."""
        def urlopen(req, timeout=0):
            return io.BytesIO(font if req.full_url == FONTS[FID]["url"] else b"SIL OPEN FONT LICENSE")
        return mock.patch.object(IT.urllib.request, "urlopen", urlopen)

    def test_every_font_is_pinned(self):
        for fid, f in FONTS.items():
            if f.get("kind") == "pixel":
                continue
            with self.subTest(font=fid):
                self.assertRegex(f.get("sha256", ""), r"^[0-9a-f]{64}$")

    def test_a_download_that_isnt_the_vetted_file_is_refused_and_not_saved(self):
        with self.serve(b"not the vetted font"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                IT.font_file(FID)
        self.assertIn("isn't the", str(cm.exception.code))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_the_vetted_file_is_saved_with_its_license(self):
        font = b"the vetted font"
        vetted = {**FONTS, FID: {**FONTS[FID], "sha256": hashlib.sha256(font).hexdigest()}}
        with self.serve(font), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(IT, "config", lambda name: {"fonts": vetted} if name == "fonts" else config(name)):
            p, _ = IT.font_file(FID)
        self.assertEqual(p.read_bytes(), font)
        self.assertTrue((self.dir / (FONTS[FID]["file"] + ".OFL.txt")).exists())

    def test_a_cached_file_that_changed_is_caught(self):
        (self.dir / FONTS[FID]["file"]).write_bytes(b"changed on disk")
        with self.assertRaises(SystemExit) as cm:
            IT.font_file(FID)
        self.assertTrue(re.search(r"isn't the .* vetted", str(cm.exception.code)))


if __name__ == "__main__":
    unittest.main()
