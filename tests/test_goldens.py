r"""Sound and picture goldens (TASKS.md T2): proof that a refactor changed not one sample or pixel.

  .venv\Scripts\python -m unittest discover -s tests -v                            sound (CPU, about 30 s)
  $env:COZY_SLOW = "1"; .venv\Scripts\python -m unittest discover -s tests -v       + pictures (GPU, Electron, ~2 min)

Sound: the ambience stems from tools/audio.py's Ambience (the code a render runs) for 3 s at two starts in each of
SOUND_SCENES, from the scene's own timeline: 5 minutes in, and just before its first sound event (thunder, a boat, a
car, a neon buzz, ...). Each stem's RMS per 50 ms must match to 1e-6, so numpy's last bits on another machine don't
fail it. On the machine and numpy that recorded it, the stems must also match to the bit.

Pictures (COZY_SLOW=1): stills of every scene at 1920x1080 (node src/cli.mjs still) at three frames: 3 s in (the
opening line), the first lightning's peak (else 10 minutes in) and the busiest second of the first 20 minutes. Each
frame's RGB is hashed. When a hash differs and the reference frame recorded on this machine exists (out/goldens/,
gitignored), the two are compared: at most 1 level on at most 0.001% of the pixels passes (the GPU's rare rounding
tie, docs/decisions/0001-tech-stack.md); anything more fails and says where.

Both are keyed by their inputs, like the timelines: the scene's files (test_scenes.scene_inputs) and, for pictures,
the plate folder's content (src/render/inputs.mjs). A golden whose inputs changed is skipped, never blamed on the code.

Record on code you trust, before a refactor and after a deliberate change:
  $env:UPDATE_GOLDENS = "1"; $env:COZY_SLOW = "1"; .venv\Scripts\python -m unittest discover -s tests -p test_goldens.py
  Remove-Item Env:UPDATE_GOLDENS, Env:COZY_SLOW
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from test_scenes import NODE, scene_inputs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
GOLD = Path(__file__).resolve().parent / "goldens"
SOUND_FILE, STILLS_FILE = GOLD / "sound.json", GOLD / "stills.json"
LOCAL = ROOT / "out" / "goldens"          # calibration caches and reference frames (gitignored)
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"
SLOW = os.environ.get("COZY_SLOW") == "1"
SOUND_SCENES = ("ramen-alley", "leaf-campfire-rain", "treetop-plate", "snowy-cottage")
SOUND_EVENTS = {"boat", "lantern", "fish", "car", "train", "ember", "neon", "gutter"}
CLIP_S, WIN_S = 3.0, 0.05
STILL_W, STILL_H = 1920, 1080


def run(args, timeout=600):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args))} failed ({r.returncode}):\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def scenes_and_plates(tmp):
    out = Path(tmp) / "imports.json"
    run([NODE, str(ROOT / "tests" / "js_scenes.mjs"), str(out)], timeout=300)
    return {k: v["plate"] for k, v in json.loads(out.read_text(encoding="utf-8"))["scenes"].items() if not v["error"]}


def timeline(tmp, scene):
    p = Path(tmp) / f"timeline_{scene}.json"
    if not p.exists():
        run([NODE, "src/cli.mjs", "timeline", f"scenes/{scene}", "--out", str(p)])
    return p


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def sound_starts(tl):
    """5 minutes in, and half a second before the first sound event (else 15 minutes in)."""
    ts = []
    for e in tl["events"]:
        if e["type"] in ("lightning", "farflash") and e.get("thunder"):
            ts.append(e["thunder"]["t"])
        elif e["type"] in SOUND_EVENTS:
            ts.append(e["t"])
    first = min(ts) if ts else 900.0
    return [300.0, round(max(0.0, first - 0.5), 3)]


def rms_windows(x, sr):
    n = int(round(WIN_S * sr))
    m = len(x) // n
    return np.sqrt((x[: m * n].reshape(m, n, -1) ** 2).mean(axis=(1, 2)))


def still_frames(tl, fps):
    """3 s in, the first lightning's peak (else 10 minutes in) and the busiest second of the first 20 minutes."""
    # a looped timeline also holds the period before the video starts (negative times): only what the video shows
    early = [e for e in tl["events"] if 0 <= e["t"] < 1200]
    lt = [e["t"] for e in early if e["type"] == "lightning"]
    best, busiest = -1, 600
    for s in range(5, 1200):
        n = sum(1 for e in early if e["t"] <= s < e["t"] + max(float(e.get("dur") or 0), 2.0))
        if n > best:
            best, busiest = n, s
    frames = sorted({round(3.0 * fps), round((lt[0] + 0.15 if lt else 600.0) * fps), round(busiest * fps)})
    if len(frames) < 3:
        frames = sorted(set(frames) | {round(900 * fps)})
    return frames


def rgb(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


class Sound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NODE:
            raise unittest.SkipTest("node isn't on PATH")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.plates = scenes_and_plates(cls.tmp.name)
        cls.goldens = load(SOUND_FILE)
        cls.fresh = {}

    @classmethod
    def tearDownClass(cls):
        if UPDATE and cls.fresh:
            save(SOUND_FILE, cls.fresh)
        cls.tmp.cleanup()

    def test_ambience(self):
        import audio as A
        env = {"numpy": np.__version__, "platform": sys.platform, "machine": platform.machine()}
        for scene in SOUND_SCENES:
            with self.subTest(scene=scene):
                if scene not in self.plates:
                    self.skipTest(f"{scene} doesn't import")
                tl = json.loads(timeline(self.tmp.name, scene).read_text(encoding="utf-8"))
                amb = A.Ambience(tl, A.make_cfg(tl))
                master = amb.calibrate(LOCAL / "audio_cal" / scene)
                rec = {"inputs": scene_inputs(scene, self.plates[scene]), "env": env, "master_db": master, "clips": {}}
                for start in sound_starts(tl):
                    stems = amb.render(start, CLIP_S)
                    bits = hashlib.sha256(b"".join(stems[k].tobytes() for k in sorted(stems))).hexdigest()[:16]
                    rec["clips"][f"{start:.3f}"] = {"bits": bits, "rms": {k: [float(f"{v:.9g}") for v in rms_windows(stems[k], A.SR)]
                                                                         for k in sorted(stems)}}
                self.fresh[scene] = rec
                if UPDATE:
                    continue
                g = self.goldens.get(scene)
                if g is None:
                    self.skipTest(f"{scene}: no sound golden yet (record with UPDATE_GOLDENS=1)")
                if g["inputs"] != rec["inputs"]:
                    self.skipTest(f"{scene}: its scene or plate changed since the golden was recorded")
                self.assertAlmostEqual(master, g["master_db"], places=6, msg=f"{scene}: loudness calibration moved")
                self.assertEqual(sorted(rec["clips"]), sorted(g["clips"]), f"{scene}: the clip starts moved (its timeline changed)")
                same_env = g["env"] == env
                for start, c in rec["clips"].items():
                    gc = g["clips"][start]
                    for stem, v in c["rms"].items():
                        a, b = np.asarray(v), np.asarray(gc["rms"][stem])
                        self.assertEqual(a.shape, b.shape, f"{scene} at {start} s, {stem}: length changed")
                        bad = np.flatnonzero(~np.isclose(a, b, rtol=1e-6, atol=1e-9))
                        self.assertEqual(bad.size, 0, f"{scene} at {start} s, {stem}: RMS differs from {float(start) + bad[0] * WIN_S if bad.size else 0:.2f} s "
                                                      f"({b[bad[0]] if bad.size else 0:.6g} then, {a[bad[0]] if bad.size else 0:.6g} now)")
                    if same_env:
                        self.assertEqual(c["bits"], gc["bits"], f"{scene} at {start} s: same machine and numpy, but the samples changed")


@unittest.skipUnless(SLOW, "pictures render on the GPU: set COZY_SLOW=1")
class Pictures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not NODE:
            raise unittest.SkipTest("node isn't on PATH")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.plates = scenes_and_plates(cls.tmp.name)
        cls.goldens = load(STILLS_FILE)
        cls.fresh = {}

    @classmethod
    def tearDownClass(cls):
        if UPDATE and cls.fresh:
            save(STILLS_FILE, cls.fresh)
        cls.tmp.cleanup()

    def inputs(self, scene, plate):
        ph = json.loads(run([NODE, "src/render/inputs.mjs", plate]))["hash"] if plate else None
        return hashlib.sha256(f"{scene_inputs(scene, plate)}\n{ph}".encode()).hexdigest()[:16]

    def test_stills(self):
        for scene, plate in sorted(self.plates.items()):
            with self.subTest(scene=scene):
                if plate and not (ROOT / "out" / "plates" / plate / "plate.json").exists():
                    self.skipTest(f"{scene}: no plate {plate} on this machine")
                tl = json.loads(timeline(self.tmp.name, scene).read_text(encoding="utf-8"))
                frames = still_frames(tl, tl.get("fps", 30))
                key = self.inputs(scene, plate)
                g = self.goldens.get(scene)
                if not UPDATE:
                    if g is None:
                        self.skipTest(f"{scene}: no picture golden yet (record with UPDATE_GOLDENS=1 COZY_SLOW=1)")
                    if g["inputs"] != key:
                        self.skipTest(f"{scene}: its scene or plate changed since the golden was recorded")
                    frames = [int(f) for f in g["frames"]]
                out = Path(self.tmp.name) / scene
                run([NODE, "src/cli.mjs", "still", f"scenes/{scene}", "--frames", ",".join(map(str, frames)), "--width", str(STILL_W),
                     "--height", str(STILL_H), "--out", str(out), "--name", "g"])
                rec = {"inputs": key, "frames": {}}
                for f in frames:
                    png = out / f"g_{STILL_W}x{STILL_H}_f{f:06d}.png"
                    rec["frames"][str(f)] = hashlib.sha256(rgb(png).tobytes()).hexdigest()[:16]
                    ref = LOCAL / "stills" / scene / f"f{f:06d}.png"
                    if UPDATE:
                        ref.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(png, ref)
                        continue
                    if rec["frames"][str(f)] == g["frames"][str(f)]:
                        continue
                    if not ref.exists():
                        self.fail(f"{scene} frame {f}: the picture changed (no local reference to say how much)")
                    a, b = rgb(png).astype(np.int16), rgb(ref).astype(np.int16)
                    d = np.abs(a - b).max(axis=2)
                    ys, xs = np.nonzero(d)
                    if d.max() <= 1 and len(ys) <= 1e-5 * d.size:
                        continue
                    self.fail(f"{scene} frame {f}: {len(ys)} pixels differ, by up to {d.max()} levels, in x {xs.min()}-{xs.max()}, "
                              f"y {ys.min()}-{ys.max()} (reference: {ref})")
                self.fresh[scene] = rec


if __name__ == "__main__":
    unittest.main()
