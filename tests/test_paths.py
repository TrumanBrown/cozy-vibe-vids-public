"""tools/cozy/paths.py (TASKS.md T10): the one scene.json format, writes that never leave half a file, config read
fresh. Free, offline, under a second. Its scratch folder is cache/test_paths/ (gitignored), removed after.

  .venv\\Scripts\\python -m unittest discover -s tests -p test_paths.py -v
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import cozy.paths as P  # noqa: E402


class Paths(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "cache" / "test_paths"
        shutil.rmtree(self.root, ignore_errors=True)
        (self.root / "scenes" / "s").mkdir(parents=True)
        (self.root / "config").mkdir()
        self.patch = mock.patch.object(P, "ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_root_and_folders(self):
        self.patch.stop()
        try:
            self.assertEqual(P.ROOT, ROOT)
            self.assertTrue(Path(P.PY).exists(), P.PY)
            self.assertEqual(P.scene_dir("a"), ROOT / "scenes" / "a")
            self.assertEqual(P.plate_dir("a"), ROOT / "out" / "plates" / "a")
            self.assertEqual(P.keyart_dir(), ROOT / "assets" / "keyart")
            self.assertEqual(P.out_dir("a"), ROOT / "out" / "a")
        finally:
            self.patch.start()

    def test_scene_json_format(self):
        spec = {"title": "Café ☔", "layers": [{"type": "rain", "z": 1.5}], "events": {}}
        p = P.save_scene("s", spec)
        self.assertEqual(p, self.root / "scenes" / "s" / "scene.json")
        raw = p.read_bytes()
        self.assertEqual(raw, (json.dumps(spec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(P.load_scene("s"), spec)
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["scene.json"], "a temp file was left behind")

    def test_failed_write_keeps_the_old_file(self):
        p = P.save_scene("s", {"seed": 1})
        before = p.read_bytes()
        with mock.patch.object(P.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                P.save_scene("s", {"seed": 2})
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(sorted(x.name for x in p.parent.iterdir()), ["scene.json"], "a temp file was left behind")

    def test_config_is_read_fresh(self):
        c = self.root / "config" / "x.json"
        c.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 1})
        c.write_text('{"a": 2}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 2})

    def test_a_local_config_goes_over_the_shared_one(self):
        """The Azure account and a music library's folder live in config/<name>.local.json, which git ignores (security
        review 2026-11-22: both were public in config/azure.json and config/skyrim_music.json)."""
        (self.root / "config" / "x.json").write_text('{"a": 1, "endpoint": null, "keep": [1]}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 1, "endpoint": None, "keep": [1]})
        (self.root / "config" / "x.local.json").write_text('{"endpoint": "https://e/"}', encoding="utf-8")
        self.assertEqual(P.config("x"), {"a": 1, "endpoint": "https://e/", "keep": [1]})
        for name in ("config/azure.local.json", "config/skyrim_music.local.json"):
            ignored = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode
            self.assertEqual(ignored, 0, f"{name} must be ignored (.gitignore config/*.local.json)")

    def test_has_weather(self):
        """A clear night draws no weather, so the weather checks skip it (the jungle temple, 2026-10-27, L162)."""
        clear = {"layers": [{"type": "birds"}, {"type": "particles", "kind": "fireflies"}, {"type": "moth"}]}
        self.assertFalse(P.has_weather(clear))
        self.assertFalse(P.has_weather({}))
        self.assertTrue(P.has_weather({"layers": [{"type": "rain"}]}))
        self.assertTrue(P.has_weather({"layers": [{"type": "drips"}]}))
        self.assertTrue(P.has_weather({"layers": [{"type": "particles", "kind": "snow"}]}))
        self.assertTrue(P.has_weather({"layers": [], "plate_fx": {"ground": {"rings": 1}}}))
        self.assertFalse(P.has_weather({"layers": [{"type": "rain", "enabled": False}]}))

    def test_wet_weather_reads_words_not_letters(self):
        """"fog, no rain" gave the tide pool a rain bed in autopilot's setup (2026-11-05, L176): the old test was the
        substring "rain", which a negation, "terrain" or "train" also hold."""
        for wet in ("rain", "steady rain", "a rainy night", "light drizzle", "thunderstorm", "spring showers",
                    "a heavy downpour", "stormy", "no fog, just rain"):
            self.assertTrue(P.wet_weather(wet), wet)
        for dry in ("fog, no rain", "clear night with fireflies", "rough terrain", "a train at night", "without any rain",
                    "rain-free", "first snow", "a brainstorm", "", None):
            self.assertFalse(P.wet_weather(dry), dry)
        self.assertTrue(P.wet_weather("first snow", ("snow", "blizzard")))
        self.assertFalse(P.wet_weather("fog, no snow", ("snow", "blizzard")))

    def test_the_bed_for_fog_without_rain_is_dry(self):
        from cozy.audio.ambience import choose_bed
        self.assertEqual(choose_bed("cottage_rain", "fog, no rain", False, False)[0], "quiet_night")
        self.assertEqual(choose_bed("cottage_rain", "light rain", False, False)[0], "cottage_rain")


class WeatherAuditSkipsClearScenes(unittest.TestCase):
    def test_a_scene_without_weather_is_not_audited(self):
        """weather_audit used to measure rain coverage on the jungle temple's clear night and fail on its dry pockets.
        It now stops before reading any plate file (none exist in this scratch root)."""
        import contextlib
        import io
        import weather_audit as WA
        root = ROOT / "cache" / "test_paths_audit"
        shutil.rmtree(root, ignore_errors=True)
        (root / "scenes" / "clear").mkdir(parents=True)
        (root / "scenes" / "clear" / "scene.json").write_text(json.dumps({"layers": [{"type": "birds"}]}), encoding="utf-8")
        out = io.StringIO()
        try:
            with mock.patch.object(WA, "ROOT", root), mock.patch.object(sys, "argv", ["weather_audit.py", "clear"]), \
                    contextlib.redirect_stdout(out):
                code = WA.main()
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(code, 0)
        self.assertIn("draws no weather; nothing to audit", out.getvalue())

    def test_a_scene_without_weather_has_nothing_to_leak(self):
        """leak_check failed the tide pool's foggy evening on a kelp strip "under the weather" it never draws
        (2026-11-05); like weather_audit, it now stops before reading any plate file."""
        import contextlib
        import io
        import leak_check as LC
        root = ROOT / "cache" / "test_paths_leak"
        shutil.rmtree(root, ignore_errors=True)
        (root / "scenes" / "fog").mkdir(parents=True)
        (root / "scenes" / "fog" / "scene.json").write_text(json.dumps({"layers": [{"type": "birds"}]}), encoding="utf-8")
        out = io.StringIO()
        try:
            with mock.patch.object(LC, "ROOT", root), mock.patch.object(sys, "argv", ["leak_check.py", "fog"]), \
                    contextlib.redirect_stdout(out):
                code = LC.main()
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(code, 0)
        self.assertIn("draws no weather; nothing to check", out.getvalue())


if __name__ == "__main__":
    unittest.main()
