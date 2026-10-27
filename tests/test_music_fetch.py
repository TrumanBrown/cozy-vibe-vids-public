"""tools/music_fetch.py against hostile or broken sources, with the network mocked: nothing is downloaded.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_music_fetch.py -v

Only https is fetched, FMA links stay on FMA's hosts, a name from a remote list writes only a plain file in --to (a
compromised catalog could otherwise write anywhere), one track that fails doesn't end the album and leaves no half
file, and a mistyped category stops before the 554 MB zip (security review 2026-10-26).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import music_fetch as MF  # noqa: E402

LICENSE = 'is licensed under a <a rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0 Universal License</a>'
ALBUM = "".join(
    f"<div data-track-info='{json.dumps({'title': t, 'url': f'https://freemusicarchive.org/music/art/alb/{t.lower()}/', 'artistName': 'Art', 'fileUrl': f'https://files.freemusicarchive.org/{t.lower()}.mp3'})}'></div>"
    for t in ("A", "B"))


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Addresses(unittest.TestCase):
    def test_only_https_is_fetched(self):
        for url in ("http://freemusicarchive.org/x", "file:///C:/Windows/win.ini", "ftp://x/y"):
            with self.subTest(url=url), mock.patch.object(MF.urllib.request, "urlopen", side_effect=AssertionError("fetched")):
                with self.assertRaisesRegex(RuntimeError, "only https"):
                    MF.get(url)

    def test_fma_links_stay_on_fma(self):
        for url in ("https://files.freemusicarchive.org/storage/a.mp3", "https://freemusicarchive.org/music/a/b/"):
            self.assertEqual(MF.on_fma(url), url)
        for url in ("https://evil.example/a.mp3", "https://freemusicarchive.org.evil.com/a.mp3", "file:///C:/x"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                MF.on_fma(url)

    def test_a_dropped_connection_is_retried_a_404_is_not(self):
        seq = []

        def flaky(req, timeout=0):
            seq.append(req.full_url)
            if len(seq) < 3:
                raise urllib.error.URLError("getaddrinfo failed")
            return io.BytesIO(b"hello")

        with mock.patch.object(MF.urllib.request, "urlopen", flaky), mock.patch.object(MF.time, "sleep"), quiet():
            self.assertEqual(MF.get("https://example.invalid/x"), "hello")
        self.assertEqual(len(seq), 3)

        def h404(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        with mock.patch.object(MF.urllib.request, "urlopen", h404):
            with self.assertRaisesRegex(RuntimeError, r"https://example\.invalid/y: HTTP 404"):
                MF.get("https://example.invalid/y")


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_write_takes_only_a_plain_name_inside_the_folder(self):
        dst = self.root / "to"
        for bad in ("..\\evil.mp3", "openlofi_..\\..\\evil.mp3", "../evil.mp3", "C:\\evil.mp3", ".."):
            with self.subTest(name=bad), self.assertRaisesRegex(RuntimeError, "not a plain file name"):
                MF.write(dst, bad, b"x", {})
        self.assertEqual([p.name for p in self.root.rglob("*") if p.is_file()], [])
        self.assertEqual(MF.write(dst, "openlofi_good-track.mp3", b"x", {}).parent, dst)

    def test_a_hostile_catalog_name_is_skipped(self):
        cache = self.root / "cache" / "openlofi"
        cache.mkdir(parents=True)
        with zipfile.ZipFile(cache / "openlofi.zip", "w") as z:
            z.writestr("tracks/good-track.mp3", b"ID3good")
            z.writestr("..\\..\\..\\evil.mp3", b"ID3evil")
        cat = {"license": "CC0-1.0", "categories": [{"slug": "jazzhop", "label": "Jazzhop"}],
               "tracks": [{"filename": "good-track.mp3", "title": "Good", "category": "jazzhop"},
                          {"filename": "..\\..\\..\\evil.mp3", "title": "Evil", "category": "jazzhop"}]}

        def get(url, binary=False, tries=3):
            if url == MF.OPENLOFI["catalog"]:
                return json.dumps(cat)
            raise AssertionError(f"downloaded {url}")

        to = self.root / "music" / "_candidates" / "jazz"
        out = io.StringIO()
        with mock.patch.object(MF, "ROOT", self.root), mock.patch.object(MF, "get", get), \
                mock.patch.dict(MF.OPENLOFI, {"zip_sha256": MF.sha256_of(cache / "openlofi.zip")}), contextlib.redirect_stdout(out):
            n = MF.openlofi(["jazzhop"], str(to), 0)
        self.assertEqual(n, 1)
        self.assertIn("not a plain audio file name", out.getvalue())
        self.assertEqual(sorted(p.name for p in self.root.rglob("*.mp3")), ["openlofi_good-track.mp3"])

    def test_a_mistyped_category_stops_before_the_zip(self):
        cat = {"license": "CC0-1.0", "categories": [{"slug": "jazzhop", "label": "Jazzhop"}], "tracks": []}

        def get(url, binary=False, tries=3):
            if url == MF.OPENLOFI["catalog"]:
                return json.dumps(cat)
            raise AssertionError(f"downloaded {url}")

        with mock.patch.object(MF, "ROOT", self.root), mock.patch.object(MF, "get", get):
            with self.assertRaises(SystemExit) as cm:
                MF.openlofi(["jazzhopp"], str(self.root / "to"), 0)
        self.assertIn("no category jazzhopp", str(cm.exception.code))

    def fma(self, mp3_ok):
        def get(url, binary=False, tries=3):
            if url.endswith("/music/art/alb"):
                return ALBUM
            if url.endswith("/alb/a/"):
                raise RuntimeError(f"{url}: HTTP 500")
            if url.endswith("/alb/b/"):
                return LICENSE
            if url.endswith("/b.mp3") and mp3_ok:
                return b"ID3"
            raise RuntimeError(f"{url}: timed out (network)")

        out = io.StringIO()
        with mock.patch.object(MF, "get", get), contextlib.redirect_stdout(out):
            n = MF.fma("art/alb", str(self.root / "to"), [], 0)
        return n, out.getvalue(), sorted(p.name for p in (self.root / "to").glob("*")) if (self.root / "to").exists() else []

    def test_a_track_that_fails_is_skipped_and_the_album_goes_on(self):
        n, log, files = self.fma(mp3_ok=True)
        self.assertEqual((n, files), (1, ["art_b.mp3", "art_b.mp3.json"]))
        self.assertIn("skip A", log)

    def test_a_failed_download_leaves_no_file_or_sidecar(self):
        n, log, files = self.fma(mp3_ok=False)
        self.assertEqual((n, files), (0, []))
        self.assertIn("skip B: the download failed", log)

    def test_a_bad_album_name(self):
        with self.assertRaises(SystemExit) as cm:
            MF.fma("justone", str(self.root / "to"), [], 0)
        self.assertIn("give <artist>/<album>", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
