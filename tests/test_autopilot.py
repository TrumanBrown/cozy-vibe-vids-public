r"""Autopilot reads a tool stopped at the daily Azure cap as a stop, not a gate, and names a scene only with the weather
Truman chose (free, offline, about a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_autopilot.py -v

tools/azure_ai.py ends a tool with "daily cap: ..." once today's logged estimate reaches config/azure.json
daily_cap_usd, sending nothing. critic.py and outdoor_check.py then exit 1 without a traceback, and autopilot read that
as a gate with no reason ("NEEDS FIX at critic:", resume --from render), or at the music stage as music skipped (found in
review, 2026-10-27). sh() now raises DailyCap, and the run stops with exit 3 as at its own budget.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import autopilot  # noqa: E402

CAP = "daily cap: today's estimated Azure spend $40.12 has reached $40.00. Nothing was sent."


class FakeRun:
    def __init__(self, d):
        self.dir = Path(d)

    def log(self, s):
        pass


class DailyCapStop(unittest.TestCase):
    def sh(self, code):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            return autopilot.sh([sys.executable, "-c", code], FakeRun(tmp), "probe")

    def test_a_tool_at_the_cap_stops_the_run(self):
        with self.assertRaises(autopilot.DailyCap) as e:
            self.sh(f"import sys; print('critic: 3 of 12 checks'); sys.exit({CAP!r})")
        self.assertEqual(str(e.exception), CAP)

    def test_a_child_at_the_cap_inside_a_tool_stops_it_too(self):
        # new_video.py runs keyart.py without capturing it: the child's line reaches autopilot's pipe the same way
        inner = f"import sys; sys.exit({CAP!r})"
        with self.assertRaises(autopilot.DailyCap):
            self.sh(f"import subprocess, sys; r = subprocess.run([sys.executable, '-c', {inner!r}]); sys.exit(r.returncode)")

    def test_other_failures_stay_failures(self):
        rc, out = self.sh("import sys; print('- L112: the signature detail is not in the scene'); sys.exit(1)")
        self.assertEqual(rc, 1)
        self.assertIn("- L112: the signature detail is not in the scene", out)

    def test_a_tool_that_succeeds_is_never_read_as_capped(self):
        rc, out = self.sh(f"print({CAP!r})")
        self.assertEqual(rc, 0)


class RunStops(unittest.TestCase):
    def test_the_run_stops_with_exit_3_and_the_stage_marked_stopped(self):
        """cmd_run in a scratch ROOT with every stage faked: all pass until critic, which meets the cap."""
        from types import SimpleNamespace

        def done(run, a):
            return "done", "faked"

        def capped(run, a):
            raise autopilot.DailyCap(CAP)

        saved = autopilot.ROOT, dict(autopilot.FUNCS), autopilot.spend_breakdown
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            try:
                autopilot.ROOT = Path(tmp)
                autopilot.FUNCS.update({s: done for s in autopilot.STAGES})
                autopilot.FUNCS["critic"] = capped
                autopilot.spend_breakdown = lambda run: (0.0, {})
                a = SimpleNamespace(scene="probe-scene", idea="a probe", look=None, pick=None, from_stage=None, budget=None)
                code = autopilot.cmd_run(a)
                state = autopilot.Run("probe-scene").s
            finally:
                autopilot.ROOT = saved[0]
                autopilot.FUNCS.clear()
                autopilot.FUNCS.update(saved[1])
                autopilot.spend_breakdown = saved[2]
        self.assertEqual(code, 3)
        self.assertEqual(state["stages"]["critic"]["status"], "stopped")
        self.assertEqual(state["stages"]["critic"]["note"], CAP)
        self.assertEqual(state["stages"]["review"]["status"], "done")
        self.assertIn("STOPPED at critic", printed.getvalue())
        self.assertNotIn("NEEDS FIX", printed.getvalue())


class ResolverKnowsTheWeather(unittest.TestCase):
    """The look resolver names the scene before the plan stage. It named the jungle temple jungle-temple-rain, with a
    "rainy dawn" hint, while Truman had chosen a clear night (2026-10-27, L161): it must get his weather, or leave the
    weather out of the name while he hasn't chosen."""

    def run_idea(self, idea, weather):
        import json
        from types import SimpleNamespace
        from unittest import mock
        import azure_ai
        prompts = []

        def fake_chat(messages, **kw):
            prompts.append(messages[0]["content"])
            return json.dumps({"look": "minecraft-voxel", "new": False, "why": "fits", "setting_hint": "a jungle temple",
                               "scene": "jungle-temple-night"}), {"usd_est": 0.0}

        def done(run, a):
            return "done", "faked"

        saved = autopilot.ROOT, dict(autopilot.FUNCS), autopilot.spend_breakdown
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(azure_ai, "chat", fake_chat):
            try:
                autopilot.ROOT = Path(tmp)
                autopilot.FUNCS.update({s: done for s in autopilot.STAGES})
                autopilot.spend_breakdown = lambda run: (0.0, {})
                a = SimpleNamespace(scene=None, idea=idea, look=None, pick=None, from_stage=None, budget=None, weather=weather)
                self.assertEqual(autopilot.cmd_run(a), 0)
                made = sorted(p.name for p in (Path(tmp) / "out").iterdir())
            finally:
                autopilot.ROOT = saved[0]
                autopilot.FUNCS.clear()
                autopilot.FUNCS.update(saved[1])
                autopilot.spend_breakdown = saved[2]
        self.assertEqual(made, ["jungle-temple-night"])
        return prompts[0]

    def test_his_answer_reaches_the_resolver(self):
        p = self.run_idea("a minecraft jungle with swinging vines", "clear night with fireflies")
        self.assertIn("The weather is decided: clear night with fireflies.", p)
        self.assertNotIn("isn't chosen yet", p)

    def test_weather_named_in_his_line_counts(self):
        p = self.run_idea("a minecraft jungle on a clear night", None)
        self.assertIn("The weather is decided: clear night.", p)

    def test_no_weather_yet_stays_out_of_the_name(self):
        p = self.run_idea("a minecraft jungle with swinging vines", None)
        self.assertIn("isn't chosen yet: leave the weather out of the setting_hint and the scene name", p)
        self.assertNotIn("The weather is decided", p)


if __name__ == "__main__":
    unittest.main()
