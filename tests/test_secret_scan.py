r"""tools/secret_scan.py's private terms (free, offline, under a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_secret_scan.py -v

Besides .git/info/private-terms, every value this machine keeps in config/*.local.json is a private term by itself
(security review 2026-11-22): the Azure account and endpoint, which the first Azure call on a new machine writes there,
and a music library's folder. So the commit hook and go_public refuse them on any machine, and nobody copies them into
private-terms by hand. Short values and numbers aren't terms (they'd match ordinary words).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import secret_scan as S  # noqa: E402


class LocalTerms(unittest.TestCase):
    def test_local_config_values_are_private_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            (repo / ".git" / "info").mkdir(exist_ok=True)
            (repo / ".git" / "info" / "private-terms").write_text("# a comment\nfile-term-1\n", encoding="utf-8")
            (repo / "config").mkdir()
            (repo / "config" / "azure.local.json").write_text(json.dumps(
                {"account": "acct-123456", "endpoint": "https://acct-123456.example.net/"}), encoding="utf-8")
            (repo / "config" / "music.local.json").write_text(json.dumps(
                {"source_dir": "C:/Lib-Media/Album One", "short": "abc", "n": 3, "on": True}), encoding="utf-8")
            (repo / "config" / "shared.json").write_text(json.dumps({"account": "not-a-local-value"}), encoding="utf-8")
            (repo / "config" / "broken.local.json").write_text("{not json", encoding="utf-8")
            terms = S.private_terms(cwd=repo)
            self.assertEqual(terms, ["file-term-1", "acct-123456", "https://acct-123456.example.net/",
                                     "acct-123456.example.net", "C:/Lib-Media/Album One", "C:\\Lib-Media\\Album One"])
            rules = S.checks(cwd=repo)
            hits = S.scan_text("ok line\nthe account acct-123456 is ours\nC:\\Lib-Media\\Album One\\track.mp3\n"
                               "acct-1234567 is another one\n", rules)
            self.assertEqual([n for n, kind in hits if "private term" in kind], [2, 3])

    def test_this_repo_reads_its_own_local_files(self):
        local = ROOT / "config" / "azure.local.json"
        if not local.exists():
            self.skipTest("no config/azure.local.json on this machine yet")
        account = json.loads(local.read_text(encoding="utf-8")).get("account")
        self.assertIn(account, S.private_terms(cwd=ROOT))


if __name__ == "__main__":
    unittest.main()
