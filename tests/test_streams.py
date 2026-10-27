r"""Every ambient event stream, pinned (free, offline, about a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_streams.py -v

The scene goldens (test_scenes.py) hold each scene's timeline, but no scene uses every stream and option: nothing draws a
shooting star or a pet act, ramen alley's birds and boat already out at the start fold away in its loop, and no scene
has a gust past 2.4 m/s from the other side. tests/js_streams.mjs runs buildTimeline on two synthetic specs that switch
on all 16 event types with every option, at two seeds, and this test holds each 10 h timeline to
tests/goldens/streams.json (recorded 2026-10-27, before src/library/timeline/ambient.js was split into one function per
stream). The specs are in the .mjs and don't depend on any scene. Record again only after a deliberate change to what a
stream draws:

  $env:UPDATE_GOLDENS = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_streams.py; Remove-Item Env:UPDATE_GOLDENS
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "goldens" / "streams.json"
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"
TYPES = {"lightning", "farflash", "boat", "fish", "flurry", "neon", "gutter", "car", "ember", "star", "birds", "critter",
         "ant", "perch", "moth", "petact"}


@unittest.skipUnless(NODE, "node isn't on PATH")
class Streams(unittest.TestCase):
    def test_every_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "streams.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_streams.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True,
                               timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            got = json.loads(out.read_text(encoding="utf-8"))
        seen = set().union(*(set(v["types"]) for v in got.values()))
        self.assertEqual(TYPES - seen, set(), "the synthetic specs no longer draw every event type")
        if UPDATE:
            GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            return
        want = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(sorted(got), sorted(want))
        for k in sorted(want):
            with self.subTest(timeline=k):
                self.assertEqual(got[k]["types"], want[k]["types"], f"{k}: the event counts changed")
                self.assertEqual(got[k]["sha256"], want[k]["sha256"], f"{k}: same counts, different events")


if __name__ == "__main__":
    unittest.main()
