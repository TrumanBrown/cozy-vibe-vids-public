r"""The public copy never repeats Truman's own words or carries private details inside a binary (free, offline, a few
seconds):

  .venv\Scripts\python -m unittest discover -s tests -p test_go_public.py -v

tools/go_public.py refuses a snapshot where a public file has six of his words in a row, in order, from the chat
archives or the lessons' quotes of him, quoted or not (2026-10-27: nobody reads his chats word for word in public). The
third test runs that check on every tracked file here, so a quote in a new comment fails the suite before the next
snapshot does. On a machine without the private notes there is nothing to compare with, and it passes. It also refuses
an image or other binary with a private term in its bytes (a text chunk, a path a tool wrote in) or a GPS position in
its EXIF, which the text checks can't see, and it reads git archive's output to the end (the tar's padding, left
unread, filled the pipe and a run hung, 2026-10-27).
"""
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import go_public as G  # noqa: E402


class HisWords(unittest.TestCase):
    def test_runs_and_repeats(self):
        runs = G.word_runs(["The snow is drifting onto the chairs on the porch by the door, move it."])
        text = 'ok\n# user 2026-10-21: "the snow is drifting ONTO the chairs on the porch" (L100)\n'
        self.assertEqual(G.repeats(text, runs), [(2, "the snow is drifting ONTO the chairs on the porch")])
        self.assertEqual(G.repeats("the snow is drifting onto a bench", runs), [])              # five in a row only
        self.assertEqual(G.repeats("see docs/the/snow/is/drifting/onto/the/chairs.md", runs), [])  # a path

    def test_sources_and_exceptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "history" / "s1").mkdir(parents=True)
            (root / "docs" / "history" / "s1" / "truman-messages.md").write_text(
                "make the steam a lot softer please and keep it subtle\n"
                "I put videos like these on the TV while I work from home\n"
                "tomorrow: generate me a new youtube video sample for minecraft style\n", encoding="utf-8")
            (root / ".agents" / "skills" / "new-video" / "references").mkdir(parents=True)
            (root / ".agents" / "skills" / "new-video" / "references" / "lessons.md").write_text(
                "| L1 | 2026-10-19 | the cat: \"the cat should breathe a bit slower than now\" | fix | check |\n",
                encoding="utf-8")
            (root / "docs" / "records" / "v1").mkdir(parents=True)
            (root / "docs" / "records" / "v1" / "published.md").write_text(
                "I put videos like these on the TV while I work from home, so I started making my own.", encoding="utf-8")
            runs = G.his_runs(root)
        self.assertTrue(G.repeats("make the steam a lot softer please", runs))
        self.assertTrue(G.repeats("the cat should breathe a bit slower", runs))
        self.assertFalse(G.repeats("I put videos like these on the TV while I work from home", runs))   # published
        self.assertFalse(G.repeats("generate me a new youtube video sample for <idea>", runs))           # ALLOWED

    def test_tracked_files_hold_none(self):
        runs = G.his_runs()
        if not runs:
            self.skipTest("no private notes on this machine")
        names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        found = []
        for name in names:
            if G.private(name, []) or name in G.PRIVATE_FILES:
                continue
            data = (ROOT / name).read_bytes() if (ROOT / name).is_file() else b""
            if not data or b"\0" in data[:8192]:
                continue
            found += [f"{name}:{i}  {s[:70]}" for i, s in G.repeats(data.decode("utf-8", "replace"), runs)]
        self.assertEqual(found, [], "his words in a public file; say what he asked in our own words (AGENTS.md)")


class Binaries(unittest.TestCase):
    def test_terms_and_gps(self):
        from PIL import Image, PngImagePlugin
        term = "someone.private@example.org"
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            clean, tagged, photo = d / "clean.png", d / "tagged.png", d / "photo.jpg"
            Image.new("RGB", (8, 8)).save(clean)
            info = PngImagePlugin.PngInfo()
            info.add_text("Author", f"made by {term.upper()}")
            Image.new("RGB", (8, 8)).save(tagged, pnginfo=info)
            exif = Image.Exif()
            exif[0x8825] = {1: "N", 2: (47.0, 36.0, 0.0), 3: "W", 4: (122.0, 20.0, 0.0)}
            Image.new("RGB", (8, 8)).save(photo, exif=exif)
            check = lambda p: G.binary_problems(p, p.read_bytes(), [term])  # noqa: E731
            self.assertEqual(check(clean), [])
            self.assertEqual(check(tagged), ["a private term or this PC's user folder inside the file"])
            self.assertEqual(check(photo), ["a GPS position in its EXIF"])
        utf16 = b"\0\x01" + f"saved by {term}".encode("utf-16-le")
        self.assertEqual(G.binary_problems(Path("x.bin"), utf16, [term]),
                         ["a private term or this PC's user folder inside the file"])
        self.assertEqual(G.binary_problems(Path("x.bin"), b"\0\x01 nothing here", [term]), [])


class Export(unittest.TestCase):
    def test_reads_the_archive_to_the_end(self):
        class Pipe(io.BytesIO):
            left = None

            def close(self):
                self.left = len(self.getvalue()) - self.tell()
                super().close()

        buf = io.BytesIO()
        readme = (b"gh repo clone someone/private-thing C:\\dev\\x\n"
                  b"git clone https://github.com/someone/private-thing.git\n"
                  b"someone/private-thing-public and someone/private-things stay as they are\n")
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name, body in (("docs/a.txt", b"hello\n"), ("README.md", readme)):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        pipe = Pipe(buf.getvalue() + b"\0" * 40960)              # git archive pads past the end marker
        proc = mock.Mock(stdout=pipe, returncode=0)
        proc.wait.side_effect = lambda: self.assertEqual(pipe.left, 0, "the tail was left in the pipe") or 0
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G.subprocess, "Popen", return_value=proc), \
                mock.patch.object(G, "PUBLIC_REPO", "someone/private-thing-public"):
            files, stubs, scrubbed, execs = G.export(Path(tmp), "main", [], [], own="someone/private-thing")
            self.assertEqual((Path(tmp) / "docs" / "a.txt").read_bytes(), b"hello\n")
            self.assertEqual((Path(tmp) / "README.md").read_bytes(),          # the copy points people at the public repo
                             b"gh repo clone someone/private-thing-public C:\\dev\\x\n"
                             b"git clone https://github.com/someone/private-thing-public.git\n"
                             b"someone/private-thing-public and someone/private-things stay as they are\n")
        self.assertEqual((files, stubs, scrubbed, execs), (2, [], 0, []))
        proc.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
