r"""The loop's seam repair and a stream's opening (free, offline, a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_loop_opening.py -v

The tide pool (2026-11-05, L179): the hermit crab, the signature detail, first came at 4:27 of every 20 minute loop. Its
opening visit at 0:08 fell within 120 s of the loop's own last visit, and the seam repair dropped the opening one. With
`keepFirst` on the stream (autopilot's setup sets it for new scenes) the last visits give way instead; without it the
timeline is as before, so approved scenes keep theirs.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JS = r"""
import { pathToFileURL } from 'node:url';
const { buildTimeline } = await import(pathToFileURL(process.argv[2]).href);
const out = {};
for (const keep of [false, true]) {
  const critter = [{ perHour: 4, dur: [228, 308], startAfter: 4, first: 6 }, { perHour: 16, dur: [45, 75], startAfter: 4, first: 8, ...(keep ? { keepFirst: true } : {}) }];
  const tl = buildTimeline({ critter, loop: { period: 1200 } }, { seed: 7, duration: 3600, fps: 30, loopSeconds: 120 });
  out[keep] = tl.events.filter((e) => e.type === 'critter' && e.track === 1 && e.t >= 0 && e.t < 1200).map((e) => [e.t, e.dur]);
}
console.log(JSON.stringify(out));
"""


class KeepFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "probe.mjs"
            f.write_text(JS, encoding="utf-8")
            r = subprocess.run(["node", str(f), str(ROOT / "src" / "library" / "timeline.js")], capture_output=True, text=True, check=True)
        cls.v = json.loads(r.stdout)

    def test_the_opening_visit_stays(self):
        keep = self.v["true"]
        self.assertLess(keep[0][0], 20, "the stream's opening visit was dropped")
        last_end = keep[-1][0] + keep[-1][1] - 1200
        self.assertLessEqual(last_end + 120, keep[0][0] + 1e-6, "the loop's last visit still crowds the opening one")

    def test_without_it_the_timeline_is_as_before(self):
        """The tide pool's crab without keepFirst: the opening visit dropped, as the approved scenes' timelines have it."""
        self.assertGreater(self.v["false"][0][0], 120)
        self.assertEqual(len(self.v["true"]), len(self.v["false"]))


if __name__ == "__main__":
    unittest.main()
