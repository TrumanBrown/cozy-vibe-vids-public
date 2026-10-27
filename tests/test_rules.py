"""Standing rules from AGENTS.md that the code itself must keep (free, offline, a few seconds).

  .venv\\Scripts\\python -m unittest discover -s tests -p test_rules.py -v
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def node_json(script):
    r = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't on PATH")
class PaintedPet(unittest.TestCase):
    def test_a_pet_without_rates_only_sighs(self):
        """A painted pet only breathes (2026-10-18): a scene that gives no ear, tail or thunderEar rates gets sighs only,
        even through a storm (TASKS.md T7)."""
        pet = node_json(
            "import { buildTimeline } from './src/library/timeline.js';"
            "const tl = buildTimeline({ pet: { sigh: 8, minGap: 30 }, lightning: { perHour: 30, cluster: [3, 4], minGap: 70 } },"
            " { seed: 7, duration: 7200, fps: 30, plate: null, loopSeconds: 120 });"
            "const pet = Array.isArray(tl.pet) ? tl.pet : (tl.pet?.events ?? []);"
            "console.log(JSON.stringify({ kinds: [...new Set(pet.map((e) => e.type))], n: pet.length,"
            " strikes: tl.events.filter((e) => e.type === 'lightning').length }));")
        self.assertGreater(pet["strikes"], 0, "the storm drew no lightning, so the thunder ear wasn't tested")
        self.assertGreater(pet["n"], 0, "no sighs at all")
        self.assertEqual(pet["kinds"], ["sigh"])


if __name__ == "__main__":
    unittest.main()
