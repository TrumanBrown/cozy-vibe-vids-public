r"""The renderer fails fast when its page can't start (COZY_SLOW=1: it starts Electron three times, about 15 s).

  $env:COZY_SLOW = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_render_start.py -v

A module that stops page.js's import graph (a syntax error, a missing file) used to leave the renderer waiting for
window.cvv forever: `node src/cli.mjs still` hung, and so would an autopilot render stage, all night. page.html now
records what stopped the graph and electron-main.cjs ends the run with it. This copies src/ to a temporary folder
(node_modules linked, not copied), breaks one module of the graph there and starts that copy's renderer: it must exit 1
within a minute and say why. An unbroken copy is the control: its page starts. The repo's own files are never touched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("COZY_SLOW") == "1"
ELECTRON = ROOT / "node_modules" / "electron" / "dist" / ("electron.exe" if sys.platform == "win32" else "electron")


def link_dir(link, target):
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def unlink_dir(link):
    """Removes the link only, never what it points at."""
    if sys.platform == "win32":
        os.rmdir(link)
    else:
        os.unlink(link)


@unittest.skipUnless(SLOW and ELECTRON.exists(), "starts Electron: set COZY_SLOW=1 (and npm install)")
class RenderStart(unittest.TestCase):
    def start(self, break_it):
        """Copies src/, lets break_it(copy root) break it, starts the copy's renderer: (exit code, output, seconds)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(ROOT / "src", tmp / "src")
            link_dir(tmp / "node_modules", ROOT / "node_modules")
            try:
                break_it(tmp)
                t0 = time.time()
                r = subprocess.run([str(ELECTRON), str(tmp / "src" / "render" / "electron-main.cjs"),
                                    "--scene", str(ROOT / "scenes" / "ramen-alley"), "--width", "320", "--height", "180",
                                    "--stills", "0", "--pattern", str(tmp / "f{frame}.png")],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
                return r.returncode, r.stdout + r.stderr, time.time() - t0
            finally:
                unlink_dir(tmp / "node_modules")

    def tearDown(self):
        self.assertTrue((ROOT / "node_modules" / "three" / "package.json").exists(), "the link's cleanup touched node_modules")

    def test_a_module_that_wont_parse(self):
        def broken(tmp):
            with open(tmp / "src" / "engine" / "rng.js", "a", encoding="utf-8") as f:
                f.write("\nexport const = ;\n")
        code, out, sec = self.start(broken)
        self.assertEqual(code, 1, out[-3000:])
        self.assertIn("the render page didn't start", out)
        self.assertIn("SyntaxError", out)
        self.assertLess(sec, 60, "it waited for the time limit instead of the page's error")

    def test_a_missing_module(self):
        code, out, sec = self.start(lambda tmp: (tmp / "src" / "engine" / "rng.js").unlink())
        self.assertEqual(code, 1, out[-3000:])
        self.assertIn("the render page didn't start", out)
        self.assertLess(sec, 60, "it waited for the time limit instead of the page's error")

    def test_an_unbroken_copy_starts(self):
        # the page starts and init asks for the scene, which lives outside the copy and isn't served from it: that
        # failure comes after the start, and its exit code says so too (Electron used to end a failed run with 0)
        code, out, sec = self.start(lambda tmp: None)
        self.assertNotIn("the render page didn't start", out)
        self.assertIn("init failed", out)
        self.assertEqual(code, 1, out[-3000:])
        self.assertLess(sec, 60, out[-3000:])


if __name__ == "__main__":
    unittest.main()
