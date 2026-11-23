r"""The static check's hand-declared still things (free, offline, no model call):

  .venv\Scripts\python -m unittest discover -s tests -p test_static_still.py -v

The tide pool (2026-11-05): the vision model read the mussel beds along the bottom left as "kelp-like leaves" on its
downscaled frame, and the review gate's repair gave the rigid shells a sway. hand.json "still" lists what is rigid in
real life, with why; a flag whose box lies mostly inside one is overruled, and any other flag is judged as before.
"""
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import motion_review as MR  # noqa: E402


class DeclaredStill(unittest.TestCase):
    def test_overlap(self):
        self.assertAlmostEqual(MR.overlap([0, 0.8, 0.3, 1], [0.12, 0.81, 0.26, 1.0]), 1.0)
        self.assertAlmostEqual(MR.overlap([0, 0.8, 0.3, 1], [0.2, 0.9, 0.4, 1.0]), 0.5)
        self.assertEqual(MR.overlap([0, 0.8, 0.3, 1], [0.5, 0.1, 0.6, 0.2]), 0.0)

    def test_a_flag_inside_a_declared_still_box_is_overruled(self):
        root = ROOT / "cache" / "test_static_still"
        shutil.rmtree(root, ignore_errors=True)
        pd, kd = root / "out" / "plates" / "probe", root / "assets" / "keyart"
        pd.mkdir(parents=True)
        kd.mkdir(parents=True)
        (kd / "probe.hand.json").write_text(json.dumps({"still": [
            {"what": "mussel beds", "box": [0.0, 0.78, 0.3, 1.0], "why": "rigid shells on the rock"},
            {"what": "no reason given", "box": [0.6, 0.0, 1.0, 0.3]}]}), encoding="utf-8")
        issues = {"issues": [
            {"what": "kelp-like leaves in the lower left", "box": [0.12, 0.81, 0.26, 1.0], "severity": "high"},
            {"what": "a tree's leaves at the top right", "box": [0.7, 0.05, 0.9, 0.25], "severity": "high"}]}
        h, w = 54, 96
        sd = np.zeros((h, w), np.float32)
        first = np.zeros((h, w, 3), np.float32)
        mot = Image.new("RGB", (w, h))
        clip = root / "clip.mp4"
        try:
            with mock.patch.object(MR, "ROOT", root), mock.patch("azure_ai.vision_json", return_value=(issues, {"usd_est": 0.0})):
                code = MR.static_check(clip, "probe", sd, first, mot, np.zeros((h, w), np.float32))
            res = json.loads((root / "clip_static.json").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        by = {f["where"]: f for f in res["flagged"]}
        self.assertEqual(by["kelp-like leaves in the lower left"]["severity"], "overruled")
        self.assertIn("rigid shells on the rock", by["kelp-like leaves in the lower left"]["problem"])
        # a declared still thing without a reason doesn't count, and a flag elsewhere is judged as before
        self.assertEqual(by["a tree's leaves at the top right"]["severity"], "high")
        self.assertEqual(code, 2)

    def test_a_flag_over_a_character_is_judged_where_it_breathes(self):
        """"The otter's head remains still while its scarf moves": the head holds still by design, so the flag is judged
        on the part that rises with a breath (pet.png), not on the head (the tide pool's sample v4, 2026-11-05)."""
        root = ROOT / "cache" / "test_static_pet"
        shutil.rmtree(root, ignore_errors=True)
        pd = root / "out" / "plates" / "probe"
        pd.mkdir(parents=True)
        h, w = 54, 96
        ids = np.zeros((h, w, 3), np.uint8)
        ids[10:40, 20:50, 0] = 1
        Image.fromarray(ids).save(pd / "regions.png")
        (pd / "regions.json").write_text(json.dumps([{"id": 1, "name": "otter", "kind": "pet"}]), encoding="utf-8")
        rise = np.zeros((h, w, 3), np.uint8)
        rise[34:40, 20:50, 0] = 255                      # the chest rises; the head and the rest hold still
        Image.fromarray(rise).save(pd / "pet.png")
        pm = np.zeros((h, w), np.float32)
        pm[34:40, 20:50] = 0.005
        issues = {"issues": [{"what": "the otter's head remains still while its scarf moves", "box": [20 / w, 10 / h, 50 / w, 40 / h],
                              "severity": "high"}]}
        try:
            sd = np.zeros((h, w), np.float32)
            sd[10:40, 20:50] = 0.001                     # the region's own breathing, as measured over the clip
            with mock.patch.object(MR, "ROOT", root), mock.patch("azure_ai.vision_json", return_value=(issues, {"usd_est": 0.0})):
                code = MR.static_check(root / "clip.mp4", "probe", sd, np.zeros((h, w, 3), np.float32),
                                       Image.new("RGB", (w, h)), pm)
            res = json.loads((root / "clip_static.json").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        f = next(f for f in res["flagged"] if f["source"] == "vision")
        self.assertEqual(f["severity"], "overruled", f["problem"])
        self.assertEqual(code, 0)

    def test_the_repair_leaves_a_character_alone(self):
        import hand_region as HR
        self.assertGreaterEqual(HR.covered([0.147, 0.322, 0.251, 0.469], [0.0699, 0.1625, 0.344, 0.6958]), 0.99)
        self.assertEqual(HR.covered([0.5, 0.1, 0.6, 0.2], [0.0, 0.5, 0.3, 1.0]), 0.0)

    def test_the_repair_knows_plants_by_their_plurals(self):
        """The Sleeping Hound Inn's sample v9 flagged the shrubs on the riverbank as still, and the repair left it for the
        agent: its word list had `shrub` but not `shrubs` (2026-11-15)."""
        import hand_region as HR
        for where in ("Frosted shrubs by the river are still.", "The hedges by the gate are still",
                      "ferns under the bench", "two palms on the beach", "the pines on the ridge", "weeds between the stones"):
            self.assertTrue(HR.FOLIAGE.search(where), where)
        for where in ("Smoke rising from the inn's chimney is frozen.", "The river is still", "the stone wall"):
            self.assertFalse(HR.FOLIAGE.search(where), where)

    def test_twigs_leave_the_rock_behind_them_out(self):
        """--twigs: frosted twigs in front of a smooth rock keep their strokes; the rock's open face stays out of the
        region, so the sway can't wobble it (the Sleeping Hound Inn's riverbank shrubs, 2026-11-15)."""
        import cv2
        import hand_region as HR
        img = np.full((200, 300, 3), 20, np.uint8)
        cv2.circle(img, (150, 120), 80, (70, 72, 80), -1)                     # the rock: smooth, a little lighter
        img = cv2.GaussianBlur(img, (0, 0), 3)
        for x in range(60, 260, 25):                                          # frosted twigs, 2 px, across it
            cv2.line(img, (x, 190), (x + 30, 60), (200, 205, 215), 2)
        m = HR.twigs(img, np.ones(img.shape[:2], bool))
        lines = np.zeros(img.shape[:2], np.uint8)
        for x in range(60, 260, 25):
            cv2.line(lines, (x, 190), (x + 30, 60), 1, 2)
        self.assertGreater(m[lines > 0].mean(), 0.95)
        far = cv2.distanceTransform((1 - lines).astype(np.uint8), cv2.DIST_L2, 5) > 8
        rock = np.zeros(img.shape[:2], np.uint8)
        cv2.circle(rock, (150, 120), 70, 1, -1)
        self.assertLess(m[(rock > 0) & far].mean(), 0.02)


if __name__ == "__main__":
    unittest.main()
