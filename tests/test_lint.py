"""The bug-finding linter (TASKS.md T23): ruff with pyflakes' checks and bare except only (ruff.toml), on tools/ and
tests/. Free, offline, about a second. Skipped where ruff isn't installed (requirements-dev.txt).

  .venv\\Scripts\\python -m unittest discover -s tests -p test_lint.py -v
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("ruff"), "ruff isn't installed: pip install -r requirements-dev.txt")
class Lint(unittest.TestCase):
    def test_no_bugs_found(self):
        r = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "tools", "tests"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"ruff found something:\n{r.stdout[-3000:]}{r.stderr[-1000:]}")


if __name__ == "__main__":
    unittest.main()
