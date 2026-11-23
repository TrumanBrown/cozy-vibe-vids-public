r"""The sound follows the picture's formulas (TASKS.md T14): free, offline, about 15 s.

  .venv\Scripts\python -m unittest discover -s tests -p test_parity.py -v

The wind, the roof runoff and the gust flurries are drawn by JS and GLSL and heard through tools/audio.py, so each
formula is written twice. For each of PARITY_SCENES, both sides read the scene's timeline (node src/cli.mjs timeline)
and are evaluated at the same times (a grid over the video, each gust, a dense stretch, the loop joins):
tests/js_parity.mjs for the JS and audio.Ambience, built as tests/test_goldens.py builds it, for the Python. They must
agree to 1e-9.
  wind    Ambience.gust() against timeline.js windAt at 0.45 of the width, with the weather track's gust factor, as
          |wind| / (|mean| + gust). audio.py and rain.js round gustCycles to a whole number and windAt doesn't; every
          scene uses 5, so that never shows.
  runoff  Ambience.flow() for every stream against rain.js flowAt, the JS twin of the shader's (both built from FLOW),
          at the loop time, times the track's stream strength
  flurry  Ambience.flurry_env() against timeline.js flurryWind (its |value| / 2, capped at 1: audio.py's definition)
          and flurryEnv, the vines' sway in plate.js, which is now the same definition

Until 2026-10-27 flurryEnv capped each gust before its raised cosine, min(1, |amp| / 2) * env, and audio.py after it,
min(|amp| * env / 2, 1), so they parted while a gust passed 2 m/s. Only the snowy cottage, a 2026-10-16 mock, has such
gusts (2.13 m/s, up to 0.06 apart); every other scene was bit-identical either way. The picture now follows the sound,
and test_flurry_env_strong_gusts holds the gusts past 2 m/s to the same 1e-9.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
PARITY_SCENES = ("treetop-plate", "ramen-alley", "snowy-cottage", "blossom-teahouse-rain")
TOL = 1e-9


def run(args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))} failed ({r.returncode}):\n{(r.stderr or r.stdout)[-2000:]}")


def times_for(tl):
    """A grid over the video, a dense 10 s (the 2-3 Hz runoff packets), the loop joins and every gust's rise and fall."""
    D, L = float(tl["duration"]), float(tl["loopSeconds"])
    ts = list(np.linspace(0.0, D, 3001)) + list(np.arange(100.0, 110.0, 0.01))
    for k in (1, 2, 50, int(D // L) - 1):
        ts += [k * L - 1e-3, k * L, k * L + 1e-3]
    for e in [e for e in tl["events"] if e["type"] == "flurry" and 0 <= e["t"] < D - 60][:40]:
        ts += [e["t"] - 0.5, e["t"] + e["dur"] + 0.5] + [e["t"] + e["dur"] * k / 20 for k in range(21)]
    return np.array(sorted({round(float(t), 6) for t in ts if 0 <= t <= D}))


def strong_gusts(tl, t):
    """The times a gust past 2 m/s is blowing."""
    m = np.zeros(len(t), bool)
    for e in tl["events"]:
        if e["type"] == "flurry" and abs(e["amp"]) > 2:
            m |= (t >= e["t"]) & (t < e["t"] + e["dur"])
    return m


@unittest.skipUnless(NODE, "node isn't on PATH")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import audio as A
        cls.data = {}
        with tempfile.TemporaryDirectory() as tmp:
            for scene in PARITY_SCENES:
                tlp, tsp, out = (Path(tmp) / f"{scene}_{k}.json" for k in ("timeline", "times", "js"))
                run([NODE, "src/cli.mjs", "timeline", f"scenes/{scene}", "--out", str(tlp)])
                tl = json.loads(tlp.read_text(encoding="utf-8"))
                t = times_for(tl)
                tsp.write_text(json.dumps(t.tolist()), encoding="utf-8")
                run([NODE, str(ROOT / "tests" / "js_parity.mjs"), str(ROOT / "scenes" / scene), str(tlp), str(tsp), str(out)])
                js = json.loads(out.read_text(encoding="utf-8"))
                amb = A.Ambience(tl, A.make_cfg(tl))
                py = {"wind": amb.gust(t), "flow": [amb.flow(s, t) for s in tl["weather"]["runoff"]], "flurry_env": amb.flurry_env(t)}
                cls.data[scene] = (tl, t, js, py)

    def close(self, t, js, py, what):
        js, py = np.asarray(js, float), np.asarray(py, float)
        self.assertEqual(js.shape, py.shape, what)
        d = np.abs(js - py)
        i = int(np.argmax(d))
        self.assertLessEqual(float(d[i]), TOL, f"{what}: JS {js[i]!r} and Python {py[i]!r} at t = {t[i]} s "
                                               f"({int((d > TOL).sum())} of {len(d)} times differ)")

    def test_same_inputs(self):
        """Both sides read the same scene: the wind, the loop and the runoff streams the timeline carries."""
        for scene, (tl, t, js, py) in self.data.items():
            with self.subTest(scene=scene):
                self.assertEqual(js["scene"]["loopSeconds"], tl["loopSeconds"])
                self.assertEqual(js["scene"]["wind"], tl["weather"]["wind"])
                self.assertEqual(js["scene"]["runoff"], tl["weather"]["runoff"])

    def test_wind(self):
        for scene, (tl, t, js, py) in self.data.items():
            with self.subTest(scene=scene):
                self.close(t, js["wind"], py["wind"], f"{scene} wind (audio.py gust, timeline.js windAt)")

    def test_runoff_flow(self):
        n = 0
        for scene, (tl, t, js, py) in self.data.items():
            for i, (a, b) in enumerate(zip(js["flow"], py["flow"])):
                with self.subTest(scene=scene, stream=i):
                    self.close(t, a, b, f"{scene} runoff stream {i} (audio.py flow, rain.js flowAt)")
                    n += 1
        self.assertGreater(n, 10, "almost no runoff streams compared")

    def test_flurry_envelope(self):
        gusts = 0
        for scene, (tl, t, js, py) in self.data.items():
            with self.subTest(scene=scene):
                gusts += int((py["flurry_env"] > 0.05).sum())
                self.close(t, np.minimum(np.abs(js["flurry_wind"]) / 2.0, 1.0), py["flurry_env"],
                           f"{scene} gust flurries (audio.py flurry_env, |timeline.js flurryWind| / 2)")
                m = ~strong_gusts(tl, t)
                self.close(t[m], np.asarray(js["flurry_env"])[m], py["flurry_env"][m],
                           f"{scene} gust flurries (audio.py flurry_env, timeline.js flurryEnv)")
        self.assertGreater(gusts, 100, "almost no times inside a gust")

    # The gusts past 2 m/s, where the two used to part (the snowy cottage's strongest are 2.13 m/s).
    def test_flurry_env_strong_gusts(self):
        strong = 0
        for scene, (tl, t, js, py) in self.data.items():
            m = strong_gusts(tl, t)
            strong += int(m.sum())
            if m.any():
                self.close(t[m], np.asarray(js["flurry_env"])[m], py["flurry_env"][m],
                           f"{scene} gusts past 2 m/s (audio.py flurry_env, timeline.js flurryEnv)")
        self.assertGreater(strong, 50, "no gust past 2 m/s in PARITY_SCENES to compare (the snowy cottage had 5)")


if __name__ == "__main__":
    unittest.main()
