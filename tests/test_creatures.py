r"""Creature names agree everywhere (free, offline, under a second):

  .venv\Scripts\python -m unittest discover -s tests -p test_creatures.py -v

A critter's creature is a name a model or a person wrote ("shield bug"), and it is looked up in four tables (its pace
in plate_features PACE, its body length in cozy.segment CRITTER_M, its look and lift in critter.py), named in its
sprite's file (critter_<creature>.png, which critters.js loads) and compared with the brief's signature by review's
L112. cozy.paths.creature_id() is the one form all of them use. On 2026-10-26 the model's names went through
safe_name() instead, which made "shield bug" into "shield_bug": no table knew it, the bug was drafted at a snail's pace
and review failed its own signature check, so autopilot would have stopped at the checks gate (found in review,
2026-10-27).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.paths import creature_id  # noqa: E402


class Creatures(unittest.TestCase):
    def test_one_form(self):
        for s in ("shield bug", "shield_bug", "Shield-Bug", " SHIELDBUG ", "shield  bug"):
            self.assertEqual(creature_id(s), "shieldbug", s)
        self.assertEqual(creature_id(None), "snail")
        self.assertEqual(creature_id("", "beetle"), "beetle")
        for hostile in ("../x", "a/b", "..\\..\\x", "x.png", "c:\\y"):
            got = creature_id(hostile)
            self.assertRegex(got, r"^[a-z0-9]{1,40}$", f"{hostile!r} gave {got!r}: not a plain file name")

    def tables(self):
        import critter
        import plate_features
        from cozy.segment import CRITTER_M
        return {"plate_features PACE": plate_features.PACE, "cozy.segment CRITTER_M": CRITTER_M,
                "critter.py LOOKS": critter.LOOKS, "critter.py LIFT": critter.LIFT}

    def test_tables_are_keyed_by_creature_id(self):
        for name, table in self.tables().items():
            for k in table:
                with self.subTest(table=name, key=k):
                    self.assertEqual(creature_id(k), k, f"{name} key {k!r} can never be found: use {creature_id(k)!r}")

    def test_every_offered_creature_has_a_pace_a_size_and_a_look(self):
        import plate_features
        t = self.tables()
        for c in plate_features.OFFERED:
            for name in ("plate_features PACE", "cozy.segment CRITTER_M", "critter.py LOOKS"):
                with self.subTest(creature=c, table=name):
                    self.assertIn(creature_id(c), t[name], f"the feature look offers {c!r}, which {name} doesn't know")

    def test_every_scene_critter_is_known(self):
        t = self.tables()
        n = 0
        for sj in sorted(ROOT.glob("scenes/*/scene.json")):
            for L in json.loads(sj.read_text(encoding="utf-8")).get("layers") or []:
                if L.get("type") != "critter":
                    continue
                c = L.get("creature", "snail")
                n += 1
                with self.subTest(scene=sj.parent.name, creature=c):
                    self.assertEqual(creature_id(c), c, "a scene stores the creature's id, the sprite's file name")
                    self.assertIn(c, t["plate_features PACE"])
                    self.assertIn(c, t["cozy.segment CRITTER_M"])
        self.assertGreater(n, 5, "almost no critters found in scenes/")

    def test_review_finds_a_signature_critter_however_it_was_written(self):
        import review
        with tempfile.TemporaryDirectory() as tmp:
            sd, pd = Path(tmp) / "scene", Path(tmp) / "plate"
            sd.mkdir()
            pd.mkdir()
            (sd / "brief.json").write_text(json.dumps({"signature_detail": "a shield bug on the seed tray"}), encoding="utf-8")
            (pd / "features.json").write_text(json.dumps({"signature": "critter:shield bug"}), encoding="utf-8")
            for layers, want in (([{"type": "critter", "creature": "shieldbug"}], True),
                                 ([{"type": "critter", "creature": "snail"}], False)):
                out = []
                review._lint_signature(out, sd, {}, pd, layers, {L["type"] for L in layers})
                l112 = [o for o in out if o[0] == "L112"]
                with self.subTest(critters=[L["creature"] for L in layers]):
                    self.assertEqual(len(l112), 1, out)
                    self.assertIs(l112[0][1], want, l112[0][2])


if __name__ == "__main__":
    unittest.main()
