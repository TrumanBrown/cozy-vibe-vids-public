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

    def test_until_stops_once_that_stage_is_done(self):
        """--until setup runs the stages up to setup and stops before music (the tide pool, 2026-11-05: its surf layer
        was built before the first render); a second run without it goes on from there."""
        from types import SimpleNamespace
        ran = []

        def done(run, a):
            ran.append(run.scene)
            return "done", "faked"

        saved = autopilot.ROOT, dict(autopilot.FUNCS), autopilot.spend_breakdown
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as printed:
            try:
                autopilot.ROOT = Path(tmp)
                autopilot.FUNCS.update({s: done for s in autopilot.STAGES})
                autopilot.spend_breakdown = lambda run: (0.0, {})
                a = SimpleNamespace(scene="probe-scene", idea="a probe", look=None, pick=None, from_stage=None, budget=None,
                                    until="setup")
                code = autopilot.cmd_run(a)
                first = dict(autopilot.Run("probe-scene").s["stages"])
                a.until = None
                code2 = autopilot.cmd_run(a)
                second = dict(autopilot.Run("probe-scene").s["stages"])
            finally:
                autopilot.ROOT = saved[0]
                autopilot.FUNCS.clear()
                autopilot.FUNCS.update(saved[1])
                autopilot.spend_breakdown = saved[2]
        self.assertEqual(code, 0)
        self.assertEqual(list(first), autopilot.STAGES[:autopilot.STAGES.index("setup") + 1])
        self.assertIn("stopped after setup (--until)", printed.getvalue())
        self.assertEqual(code2, 0)
        self.assertEqual(list(second), autopilot.STAGES)
        self.assertEqual(len(ran), len(autopilot.STAGES))

    def test_overrule_resumes_past_a_gate_the_agent_is_sure_is_wrong(self):
        """The critic's fix hint said "write why in progress.md and --from report", but the gated critic just ran again
        (the Sleeping Hound Inn, 2026-11-15). --overrule marks it overruled, logs why, and the run goes on; without it a
        gated stage before --from runs again."""
        from types import SimpleNamespace
        calls = []

        def done(run, a):
            return "done", "faked"

        def critic(run, a):
            calls.append(1)
            return "gate", "key art: the dog is cut off"

        saved = autopilot.ROOT, dict(autopilot.FUNCS), autopilot.spend_breakdown
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            try:
                autopilot.ROOT = Path(tmp)
                autopilot.FUNCS.update({s: done for s in autopilot.STAGES})
                autopilot.FUNCS["critic"] = critic
                autopilot.spend_breakdown = lambda run: (0.0, {})
                a = SimpleNamespace(scene="probe-scene", idea="a probe", look=None, pick=None, from_stage=None, budget=None)
                self.assertEqual(autopilot.cmd_run(a), 2)
                a.from_stage = "report"
                self.assertEqual(autopilot.cmd_run(a), 2)            # no --overrule: the critic runs again
                a.overrule = "the dog's rump runs off the edge as painted; head, ears, paws and tail in view"
                self.assertEqual(autopilot.cmd_run(a), 0)
                s = autopilot.Run("probe-scene").s
                log = (Path(tmp) / "out" / "probe-scene" / "auto" / "progress.md").read_text(encoding="utf-8")
                a.overrule, a.from_stage = "again", "report"
                with self.assertRaises(SystemExit):
                    autopilot.cmd_run(a)                             # nothing at a gate any more
            finally:
                autopilot.ROOT = saved[0]
                autopilot.FUNCS.clear()
                autopilot.FUNCS.update(saved[1])
                autopilot.spend_breakdown = saved[2]
        self.assertEqual(len(calls), 2)
        self.assertEqual(s["stages"]["critic"]["status"], "overruled")
        self.assertEqual(s["overruled"]["critic"], "the dog's rump runs off the edge as painted; head, ears, paws and tail in view")
        self.assertEqual(s["stages"]["report"]["status"], "done")
        self.assertIn("critic: overruled: the dog's rump", log)


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


class LedgerSaysWhoPicked(unittest.TestCase):
    """The key-art row in docs/asset-ledger.csv says who picked as the sample report does (L210) and names every
    candidate's model. It said "autopilot picked" over the agent's own --pick of the Sleeping Hound Inn, whose six
    candidates came from two models while the row named only the first's (2026-11-15)."""

    def row(self, brief, models):
        import csv
        import json
        from types import SimpleNamespace
        saved = autopilot.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                autopilot.ROOT = Path(tmp)
                (Path(tmp) / "docs").mkdir()
                (Path(tmp) / "docs" / "asset-ledger.csv").write_text(
                    "path,kind,title,author,source_url,license,license_url,attribution,modified,date_retrieved,notes\n", encoding="utf-8")
                (Path(tmp) / "scenes" / "probe").mkdir(parents=True)
                (Path(tmp) / "scenes" / "probe" / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
                kd = Path(tmp) / "assets" / "keyart" / "probe"
                kd.mkdir(parents=True)
                for i, m in enumerate(models):
                    (kd / f"hero_{m}_{i}.png").write_bytes(b"")
                    (kd / f"hero_{m}_{i}.json").write_text(json.dumps({"deployment": m}), encoding="utf-8")
                autopilot.ledger(SimpleNamespace(scene="probe", s={"look": "probe-look"}))
                with open(Path(tmp) / "docs" / "asset-ledger.csv", encoding="utf-8", newline="") as f:
                    rows = list(csv.reader(f))
            finally:
                autopilot.ROOT = saved
        self.assertEqual(len(rows), 2)
        return rows[1]

    def test_a_hand_pick_is_not_credited_to_autopilot(self):
        r = self.row({"hero": "assets/keyart/probe/hero_a_0.png"}, ["gpt-image-2-5-sunburst"] * 4 + ["gpt-image-2"] * 2)
        self.assertEqual(r[1], "AI key art (Azure OpenAI gpt-image-2-5-sunburst x4, gpt-image-2 x2)")
        self.assertIn("picked by hand (autopilot --pick), not by the vision model: assets/keyart/probe/hero_a_0.png", r[10])
        self.assertNotIn("autopilot picked", r[10])

    def test_the_vision_models_pick_and_his_pick(self):
        r = self.row({"hero": "h.png", "pick_scores": [{"index": 1}]}, ["gpt-image-2"] * 2)
        self.assertEqual(r[1], "AI key art (Azure OpenAI gpt-image-2)")
        self.assertIn("the vision model picked h.png", r[10])
        r = self.row({"hero": "h.png", "hero_note": "Truman picked candidate 3"}, ["gpt-image-2"])
        self.assertIn("Truman picked (how: the brief's hero_note) h.png", r[10])


class ReportAsAPage(unittest.TestCase):
    """sample.md also goes out as sample.html: a report he reads gets an HTML version (his standing rule)."""

    def test_headings_bullets_bold_and_code(self):
        page = autopilot.md_html(["# Sample: probe", "", "**Watch:** `C:\\out\\a.mp4` (5:00).", "",
                                  "- **Key art:** a <b> tag & more", "- two", "", "## Next", "", "- ok"], "Sample: probe")
        self.assertIn("<h1>Sample: probe</h1>", page)
        self.assertIn("<p><strong>Watch:</strong> <code>C:\\out\\a.mp4</code> (5:00).</p>", page)
        self.assertIn("<ul>\n<li><strong>Key art:</strong> a &lt;b&gt; tag &amp; more</li>\n<li>two</li>\n</ul>", page)
        self.assertIn("<h2>Next</h2>\n<ul>\n<li>ok</li>\n</ul>", page)
        self.assertTrue(page.startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
