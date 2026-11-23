"""What critic.py's key-art check is told is animated where it is painted (lessons L172): every flame, fire, candle, lamp
and lantern region, since plate.js flickers each in place, and none the scene turns off. Hanging kelp, cloth and plants
sway in place: their ragged ends are not drops, while a clear or bright drop still fails (the tide pool's kelp strip,
2026-11-05)."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import critic  # noqa: E402


class AnimatedInPlace(unittest.TestCase):
    def ctx(self, regions, off=()):
        return types.SimpleNamespace(regions=[{"name": n, "kind": k} for n, k in regions],
                                     spec={"regions": {n: None for n in off}})

    def test_lights_that_flicker_in_place(self):
        note = critic.animated_in_place(self.ctx([("stair_lantern", "lamp"), ("hanging_lantern", "lantern"), ("wick", "candle"),
                                                   ("hearth", "fire"), ("vines", "plant")]))
        lights, _, sway = note.partition("These hang and sway")
        for n in ("stair lantern", "hanging lantern", "wick", "hearth"):
            self.assertIn(n, lights)
        self.assertNotIn("vines", lights, "a plant is no light that flickers in place")
        self.assertIn("vines", sway)

    def test_hanging_things_sway_and_a_real_drop_still_fails(self):
        note = critic.animated_in_place(self.ctx([("kelp_strip_ridge", "curtain"), ("pond", "water")]))
        self.assertIn("kelp strip ridge", note)
        self.assertIn("clear, glassy or bright like water", note)
        self.assertNotIn("do not fail", note)
        self.assertNotIn("pond", note)

    def test_a_region_turned_off_is_not_animated(self):
        note = critic.animated_in_place(self.ctx([("stair_lantern", "lamp"), ("desk_lamp", "lamp"), ("drape", "curtain")],
                                                 off=("desk_lamp", "drape")))
        self.assertIn("stair lantern", note)
        self.assertNotIn("desk lamp", note)
        self.assertNotIn("drape", note)

    def test_nothing_to_say(self):
        self.assertEqual(critic.animated_in_place(self.ctx([("pond", "water")])), "")


class EventNotes(unittest.TestCase):
    """An ant whose walk ends behind a thing on its surface (ant.js `behind`) is judged as going out of sight there: the
    Sleeping Hound Inn's ants failed for not going over the far edge after walking behind the sweetroll (2026-11-15)."""

    def test_an_ant_that_goes_behind_the_sweetroll(self):
        c = types.SimpleNamespace(spec={"layers": [{"type": "ant", "behind": ["sweetroll"]}]})
        note = critic.event_notes(c)["ant"]
        self.assertIn("behind the sweetroll", note)
        self.assertIn("counts as going out of sight", note)

    def test_the_judge_is_told(self):
        from unittest import mock
        seen = []

        def fake(prompt, **kw):
            seen.append(prompt)
            return {"pass": True, "confidence": 0.9}, {"usd_est": 0.0}

        with mock.patch.object(critic, "EVENT_NOTE", {"ant": "ON PURPOSE BEHIND. "}), mock.patch("azure_ai.vision_json", fake), \
                mock.patch.object(critic, "lesson_lines", lambda ids: ""):
            critic.judge("event: ant", [], None, "events", [], "probe")
            critic.judge("event: birds", [], None, "events", [], "probe")
        self.assertIn("ON PURPOSE BEHIND. one kind of event", seen[0])
        self.assertNotIn("ON PURPOSE BEHIND", seen[1])

    def test_an_ant_at_the_far_edge_gets_no_note(self):
        c = types.SimpleNamespace(spec={"layers": [{"type": "ant", "paths": []}]})
        self.assertEqual(critic.event_notes(c), {})


class OwnerApproved(unittest.TestCase):
    """The key-art check is told what Truman approved about the painting (the brief's keyart_note): it flipped on the
    Sleeping Hound Inn's husky at the frame's edge after he had okayed the sample (2026-11-15)."""

    def test_the_note_reaches_the_key_art_question(self):
        note = critic.owner_approved({"keyart_note": "the husky's back end runs off the left edge, as painted."})
        self.assertIn("approved this painting as it is, including: the husky's back end runs off the left edge, as painted. Do not fail", note)
        self.assertEqual(critic.owner_approved({}), "")
        self.assertEqual(critic.owner_approved(None), "")


if __name__ == "__main__":
    unittest.main()
