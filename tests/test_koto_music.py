"""The Yuzu Spring's koto music (tools/koto_music.py, 2026-11-12): the channel plays it in code, so it is the channel's
own. Its sidecars say so ("original", as for the ambience made in code) and never dedicate it to the public domain, and
the description's credits give it no line, as for CC0 music. Free, offline, instant.

  .venv\\Scripts\\python -m unittest tests.test_koto_music -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import koto_music as K  # noqa: E402
import music as M  # noqa: E402

STATS = {"length_s": 190.0, "lufs": -20.0, "true_peak_dbtp": -3.0}


class KotoMusic(unittest.TestCase):
    def test_the_channels_own_tracks_are_not_given_away(self):
        cat = K.catalog()
        for slug, c in cat.items():
            s = K.sidecar(slug, c, STATS, None)
            self.assertEqual((s["license"], s["license_url"]), ("original", ""), slug)
            self.assertFalse(s["ai_made"])
            self.assertNotRegex(s["composition_pd"] + s["source"], r"(?i)dedicat", slug)
        songs = [k for k, c in cat.items() if c["kind"] == "song"]
        self.assertTrue(songs)
        for slug in songs:
            self.assertIn("public domain", K.sidecar(slug, cat[slug], STATS, None)["source"], "an old melody is public domain")

    def test_no_credit_line_for_the_channels_own_or_cc0_music(self):
        tracks = [{"title": "Kojo no Tsuki (koto)", "artist": K.ARTIST, "license": "original", "source": "code"},
                  {"title": "Rain Lofi", "artist": "open-lofi", "license": "CC0 1.0 Universal", "source": "repo"},
                  {"title": "Someone's Song", "artist": "Someone", "license": "CC BY 4.0", "source": "page"}]
        doc = {"minecraft": False, "entries": [{"track": i, "start": 10 * i} for i in range(3)], "tracks": tracks}
        c = M.credits(doc, ledger_path=ROOT / "nonexistent.csv")
        self.assertNotIn("Kojo", c)
        self.assertNotIn("Rain Lofi", c)
        self.assertIn("Someone's Song - Someone", c, "a license that asks for credit still gets it")


if __name__ == "__main__":
    unittest.main()
