"""Straight lines in the weather masks where the picture has none (lessons L151).

Found on the Burdock Shelter (2026-10-25, Truman on v10: the rain stopped mid-frame along a hard line): the
analysis's opening was a box from x 0.589 to the frame's right edge, and the rain stopped along the box's left side,
a straight vertical line through the moss and the wet ground. Nothing in the painting runs there. A window frame, a
wall's corner or a roof's eave are straight too, but the plate has an edge along them; a box edge through open
ground or foliage has none.

  .venv\\Scripts\\python tools\\mask_edges.py <scene>        # prints the lines; out/plates/<plate>/mask_edges.jpg

Checks the rain (lights.png G) and the rings (masks.png G) at 1920 px wide: every vertical or horizontal run of the
mask's boundary at least 6% of the frame along it (its height for a vertical line, its width for a horizontal one;
2 px of wander allowed), not on the frame's border, with the same colors on both sides of it along more than half
the run (no edge in the picture there; a curtain's hem or a step's nose differ in color across). review.py's lint
fails on a line in the rain and lists the rings' lines to look at (a far shore or a step can end the rings straight).
"""
import argparse
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image

from cozy.paths import ROOT
MIN_RUN = 0.06     # of the frame's height
EDGE_SHARE = 0.5   # a run is excused when the plate has its own edge along more than this share of it


def _runs(on, min_len):
    """Runs of True in a 1D bool array: [(start, end_exclusive)] at least min_len long."""
    d = np.diff(np.concatenate([[0], on.astype(np.int8), [0]]))
    s, e = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    return [(int(a), int(b)) for a, b in zip(s, e) if b - a >= min_len]


def straight_lines(mask, lab, min_run=MIN_RUN, edge_share=EDGE_SHARE, de=6.0, soft=None, sharp=0.6):
    """Straight boundary runs of `mask` (bool HxW) that the plate (`lab`, float HxWx3 CIELAB) has no edge along.
    The plate's edge is judged by color across the line, row by row: the mean of a 6 px band on each side (over 11 px
    along the line) differ by more than `de` (Lab units). A curtain's hem or a step's nose are faint in brightness
    but differ in color across; a box edge through moss or water has the same texture on both sides.
    With `soft` (the mask's own 0..1 values), only a sharp edge counts: the mask must change by `sharp` or more within
    5 px across the line (median along it). A rain shadow that fades over tens of px is no harsh line (L156).
    Returns [(axis, at, start, end, edge share)]: axis "x" = a vertical line at column `at` from row start to end."""
    H, W = mask.shape
    Lv, Lh = max(8, int(min_run * H)), max(8, int(min_run * W))   # 6% of the frame along the line
    m = mask.astype(np.int8)
    mv = cv2.blur(lab, (6, 11))           # band means for vertical lines (6 wide, 11 tall)
    mh = cv2.blur(lab, (11, 6))
    out = []
    # vertical lines: a change between columns c and c+1 (2 px of wander allowed) row after row; each line is
    # reported once, at the column within 2 px that holds most of it
    tx = np.abs(np.diff(m, axis=1)) > 0                       # H x (W-1)
    txw = cv2.dilate(tx.astype(np.uint8), np.ones((1, 5), np.uint8)) > 0
    for c in range(8, W - 9):
        for a, b in _runs(txw[:, c], Lv):
            if int(np.argmax(tx[a:b, c - 2:c + 3].sum(0))) != 2:
                continue
            if soft is not None and float(np.median(np.abs(soft[a:b, c - 4] - soft[a:b, c + 5]))) < sharp:
                continue
            e = np.linalg.norm(mv[a:b, c - 5] - mv[a:b, c + 6], axis=1) > de
            if e.mean() <= edge_share:
                out.append(("x", c, a, b, round(float(e.mean()), 2)))
    ty = np.abs(np.diff(m, axis=0)) > 0                       # (H-1) x W
    tyw = cv2.dilate(ty.astype(np.uint8), np.ones((5, 1), np.uint8)) > 0
    for r in range(8, H - 9):
        for a, b in _runs(tyw[r], Lh):
            if int(np.argmax(ty[r - 2:r + 3, a:b].sum(1))) != 2:
                continue
            if soft is not None and float(np.median(np.abs(soft[r - 4, a:b] - soft[r + 5, a:b]))) < sharp:
                continue
            e = np.linalg.norm(mh[r - 5, a:b] - mh[r + 6, a:b], axis=1) > de
            if e.mean() <= edge_share:
                out.append(("y", r, a, b, round(float(e.mean()), 2)))
    return out


def check_plate(plate_dir, width=1920):
    """{"rain": [...], "rings": [...]} straight lines with no plate edge, in frame fractions
    [axis, at, start, end, edge share]."""
    pd = pathlib.Path(plate_dir)
    if not (pd / "plate.png").exists() or not (pd / "lights.png").exists():
        return {}
    plate = Image.open(pd / "plate.png").convert("RGB")
    h = int(round(width * plate.height / plate.width))
    lab = cv2.cvtColor(np.asarray(plate.resize((width, h), Image.BOX), np.float32) / 255, cv2.COLOR_RGB2LAB)
    res = {}
    for name, f in (("rain", "lights.png"), ("rings", "masks.png")):
        if not (pd / f).exists():
            continue
        g = np.asarray(Image.open(pd / f).convert("RGB").resize((width, h), Image.BOX), np.float32)[..., 1] / 255
        lines = straight_lines(g > 0.5, lab, soft=g)
        res[name] = [[ax, round(at / (width if ax == "x" else h), 4), round(a / (h if ax == "x" else width), 4),
                      round(b / (h if ax == "x" else width), 4), es] for ax, at, a, b, es in lines]
    return res


def preview(plate_dir, res, out):
    pd = pathlib.Path(plate_dir)
    im = Image.open(pd / "plate.png").convert("RGB").resize((1920, 1080), Image.BOX)
    a = np.asarray(im, np.float32)
    for f, col in (("lights.png", (255, 0, 255)), ("masks.png", (0, 255, 255))):
        g = np.asarray(Image.open(pd / f).convert("RGB").resize((1920, 1080), Image.BOX), np.float32)[..., 1:2] / 255
        a = a * (1 - 0.3 * g) + np.array(col, np.float32) * 0.3 * g
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for name, lines in res.items():
        for ax, at, s, e, _ in lines:
            if ax == "x":
                d.line((at * 1920, s * 1080, at * 1920, e * 1080), fill=(255, 40, 40), width=5)
            else:
                d.line((s * 1920, at * 1080, e * 1920, at * 1080), fill=(255, 40, 40), width=5)
    im.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    a = ap.parse_args()
    sj = ROOT / "scenes" / a.scene / "scene.json"
    plate = json.loads(sj.read_text(encoding="utf-8")).get("plate", a.scene) if sj.exists() else a.scene
    pd = ROOT / "out" / "plates" / plate
    res = check_plate(pd)
    n = sum(len(v) for v in res.values())
    for name, lines in res.items():
        for ax, at, s, e, es in lines:
            kind = "vertical" if ax == "x" else "horizontal"
            span = f"y {s:.3f}..{e:.3f}" if ax == "x" else f"x {s:.3f}..{e:.3f}"
            print(f"  {name}: a straight {kind} line at {ax} {at:.3f}, {span}, the plate's own edge along {es:.0%} of it")
    if res:
        preview(pd, res, pd / "mask_edges.jpg")
    print(f"mask_edges: {n} straight line(s) with no edge in the picture -> {pd / 'mask_edges.jpg'}")
    return 1 if res.get("rain") else 0


if __name__ == "__main__":
    sys.exit(main())
