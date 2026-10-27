"""Weather-leak check for analyzed scenes: how much of each solid region (pet, cup, lanterns, plants, the
glass frame) the outdoor mask covers (rain, snow and car lights only draw where outdoors), plus a tinted overlay.

  .venv/Scripts/python tools/leak_check.py <scene> [--kinds pet,steam,lantern,candle,lamp,bob,fire]

A solid region inside the outdoors gets weather drawn on it. Fix with "cover" polygons / not_outdoor in the
masks json, "dry": true on a hand region (plate_prep cuts it out of the outdoors), or a different outdoor_disp.
Lanterns, curtains and the like out in the view (at about the depth of the outdoors around them, as
tools/analyze_plate.py judges it: not nearer by 0.08 in disparity) are in the weather and may have rain in front
of them; regions marked "near" or "dry" are always checked. Writes out/<scene>/leak_check.png.
"""
import argparse
import json

import cv2
import numpy as np
from PIL import Image

from cozy.paths import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--kinds", default="pet,steam,lantern,candle,lamp,bob,fire,plant,curtain,neon")
    ap.add_argument("--max", type=float, default=0.02, help="largest allowed outdoor share of a solid region")
    a = ap.parse_args()
    pdir = ROOT / "out" / "plates" / a.scene
    outdoor = np.asarray(Image.open(pdir / "lights.png"))[..., 1].astype(np.float32) / 255
    rid = np.asarray(Image.open(pdir / "regions.png"))
    disp = np.asarray(Image.open(pdir / "depth.png"), np.float32) / 65535
    meta = json.loads((pdir / "regions.json").read_text(encoding="utf-8"))
    kinds = set(a.kinds.split(","))
    near_kinds = {"pet", "steam", "candle", "bob", "fire", "lantern", "chime", "curtain", "screen"}
    bad = 0
    for g in meta:
        if g["kind"] not in kinds:
            continue
        m = (rid[..., 0] == g["id"]) & (rid[..., 1] > 128)
        if not m.any():
            continue
        share = float((outdoor[m] > 0.5).mean())
        # lamps, neon, plants out in the view (beyond the glass) legitimately get weather in front of them, and so
        # does anything at about the depth of the outdoors around it (a lantern hanging over the far street)
        ring = cv2.dilate(m.astype(np.uint8), np.ones((61, 61), np.uint8)).astype(bool) & ~m & (outdoor > 0.5)
        in_view = ring.sum() > 50 and float(np.median(disp[m])) <= float(np.median(disp[ring])) + 0.08
        must_be_dry = bool(g.get("near") or g.get("dry")) or (g["kind"] in near_kinds and not in_view) or (g["kind"] == "plant" and g.get("outdoor") is False)
        flag = share > a.max and must_be_dry
        bad += flag
        why = "" if must_be_dry else (" (out in the view)" if in_view and g["kind"] in near_kinds else " (outdoors allowed)")
        print(f"  {'LEAK' if flag else 'ok  '} {g['name']:28s} {g['kind']:8s} outdoor share {share:.3f}{why}")
    plate = np.asarray(Image.open(pdir / "plate.png").convert("RGB"), np.float32) / 255
    over = plate * 0.55 + np.stack([outdoor * 0.45, np.zeros_like(outdoor), outdoor * 0.45], -1)
    Image.fromarray((np.clip(over, 0, 1) * 255).astype(np.uint8)).resize((1920, 1080)).save(ROOT / "out" / a.scene / "leak_check.png")
    print(f"{'FAIL' if bad else 'PASS'}: {bad} solid region(s) under the weather; overlay out/{a.scene}/leak_check.png")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
