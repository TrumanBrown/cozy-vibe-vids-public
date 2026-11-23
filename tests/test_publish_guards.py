"""What the publishing tools write and delete stays where it belongs (security review 2026-10-26): a ledger cell from
outside can't run as a spreadsheet formula, and upload_package's slug can't point its deletes at another folder.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_publish_guards.py -v
"""
import csv
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import music  # noqa: E402
import upload_package  # noqa: E402
from cozy.ledger import cell  # noqa: E402

HEAD = ["path", "kind", "title", "author", "source_url", "license", "license_url", "attribution", "modified", "date_retrieved", "notes"]


class LedgerCells(unittest.TestCase):
    def test_formula_starts_become_text(self):
        for s in ('=HYPERLINK("http://x","y")', "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"):
            with self.subTest(s=s):
                self.assertEqual(cell(s), "'" + s)
        for s in ("Lofi Rain", "loudness-normalized (-3.2 dB)", "", "'=already text"):
            with self.subTest(s=s):
                self.assertEqual(cell(s), s)
        self.assertEqual(cell(None), "")
        self.assertEqual(cell(cell("=1")), cell("=1"))

    def test_music_ledger_writes_a_hostile_title_as_text_and_twice_the_same(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "asset-ledger.csv"
            keep = ["assets/keyart/x/hero.png", "AI key art", "x", "us", "", "", "", "none", "", "2026-10-01", ""]
            with open(led, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, lineterminator="\n").writerows([HEAD, keep])
            track = {"file": "music/look/a.mp3", "title": '=HYPERLINK("http://evil.example","play")', "artist": "+Artist",
                     "source": "https://freemusicarchive.org/music/a/b/c/", "license": "CC0 1.0 Universal", "gain_db": -3.2,
                     "hash": "abc", "origin": "Free Music Archive"}
            music.ledger({"tracks": [track]}, ledger_path=led)
            first = led.read_bytes()
            music.ledger({"tracks": [track]}, ledger_path=led)
            self.assertEqual(led.read_bytes(), first)
            with open(led, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["path"], keep[0])
            self.assertEqual((rows[1]["title"], rows[1]["author"]), ("'" + track["title"], "'+Artist"))


class UploadSlug(unittest.TestCase):
    def spec(self, td, slug):
        t = Path(td) / "thumbs.json"
        t.write_text(json.dumps({"scene": "scenes/x", "out": str(Path(td) / "thumbs")}), encoding="utf-8")
        s = Path(td) / "spec.json"
        s.write_text(json.dumps({"slug": slug, "render": str(Path(td) / "render"), "video": "v.mp4", "thumbnails": str(t)}),
                     encoding="utf-8")
        return Namespace(spec=str(s))

    def test_a_slug_that_isnt_plain_words_is_refused(self):
        for slug in ("../../docs", "a/b", "..", "C:\\x", "Rainy-Alley", "", None, "a--b"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as td:
                with self.assertRaises(SystemExit) as cm:
                    upload_package._load_spec(self.spec(td, slug))
                self.assertIn("must be lowercase words", str(cm.exception.code))

    def test_every_published_slug_passes(self):
        for p in sorted((ROOT / "assets" / "publish").glob("*.json")):
            slug = json.loads(p.read_text(encoding="utf-8-sig"))["slug"]
            with self.subTest(spec=p.name), tempfile.TemporaryDirectory() as td:
                self.assertEqual(upload_package._load_spec(self.spec(td, slug))[1]["slug"], slug)


if __name__ == "__main__":
    unittest.main()
