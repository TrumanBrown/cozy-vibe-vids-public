"""Revise a key-art candidate before its plate is built (Truman 2026-10-25 on the Burdock Shelter: candidate 4, with
revisions: the lizard a touch more distinct, the mothling and its lantern farther from the fire, the salamander out
in the rain holding its leaf high and looking away). Masked image edits with the look's own model, composited back
only inside the mask so nothing else changes, and a code-only lift of one subject (a touch more value, contrast and
color, so it stands out from what is behind it without being redrawn). Each revision is a new PNG beside the candidate
with a sidecar listing every step (prompt, mask, model, usage), so `new_video.py pick <scene> <png>` can name it.

  .venv\\Scripts\\python tools\\keyart_revise.py <scene> --src <png> --tag <name>
      [--lift "x,y;x,y" [--lift-amount 0.12]]       the subject under the points (SAM 2), lifted in value, contrast and color
      [--edit "x,y,x,y,..." ...] [--keep "x,y;x,y"] [--prompt "..."]
                                                     repaint inside the polygon(s), except the things under --keep (SAM 2)
      [--model gpt-image-2] [--dry]                  --dry: the masks and their preview only (free)

Points and polygons are fractions of the image (x, y; 0, 0 top left). The edit prompt should say the style to keep,
what goes where in the masked area, what fills the place a moved thing left, and that every character is drawn
complete (no clipped antennae or straps through arms: lessons L138). Writes out/<scene>/revise/<tag>_preview.jpg (the
masks on the picture, then before and after) and assets/keyart/<scene>/<src stem>_<tag>.png with its .json.
"""
import argparse
import base64
import datetime
import io
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT


def pts(s):
    v = [float(x) for x in s.replace(";", ",").split(",") if x.strip()]
    return [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]


def poly_mask(p, W, H):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([(x * W, y * H) for x, y in pts(p)], fill=255)
    return np.asarray(m) > 127


def sam_union(img, points, max_frac=0.06, grow=3):
    """One SAM 2 mask per point, the best scored candidate under max_frac of the frame, grown by `grow` px."""
    if not points:
        return np.zeros((img.height, img.width), bool)
    from cozy.segment import Segmenter
    W, H = img.size
    seg = Segmenter()
    m = np.zeros((H, W), bool)
    for cands in seg.point_candidates(img, [(x * W, y * H) for x, y in points]):
        ok = [(mk, s) for mk, s in cands if 0 < mk.sum() < max_frac * W * H]
        if ok:
            m |= max(ok, key=lambda c: c[1])[0]
    k = 2 * max(1, grow) + 1
    return cv2.dilate(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0


def feather(m, r):
    return np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), r), 0, 1)


def lift(a, m, amount):
    """A touch more value, contrast and color inside the subject's soft mask (Lab), nothing redrawn."""
    lab = cv2.cvtColor(a.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    L = lab[..., 0]
    sel = m > 0.5
    mean = float(L[sel].mean()) if sel.any() else 50.0
    lab2 = lab.copy()
    lab2[..., 0] = np.clip(mean + (L - mean) * (1 + amount) + 40 * amount, 0, 100)
    lab2[..., 1:] *= 1 + 0.8 * amount
    out = np.clip(cv2.cvtColor(lab2, cv2.COLOR_LAB2RGB) * 255, 0, 255)
    w = feather(m, 1.5)[..., None]
    return (a * (1 - w) + out * w).astype(np.float32)


def preview(before, after, masks, path):
    W = 1280
    s = W / before.width
    H = round(before.height * s)
    ov = np.asarray(before.resize((W, H), Image.LANCZOS)).astype(np.float32)
    for m, col in masks:
        mm = cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        ov[mm] = ov[mm] * 0.5 + np.array(col, np.float32) * 0.5
    rows = [Image.fromarray(ov.astype(np.uint8))]
    if after is not None:
        rows += [before.resize((W, H), Image.LANCZOS), after.resize((W, H), Image.LANCZOS)]
    S = Image.new("RGB", (W, H * len(rows)), (0, 0, 0))
    for i, r in enumerate(rows):
        S.paste(r, (0, i * H))
    path.parent.mkdir(parents=True, exist_ok=True)
    S.save(path, quality=88)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--src", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--lift", default="")
    ap.add_argument("--lift-amount", type=float, default=0.12)
    ap.add_argument("--edit", action="append", default=[])
    ap.add_argument("--keep", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--model", default="gpt-image-2")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    src = pathlib.Path(a.src)
    if not src.is_absolute():
        src = ROOT / src
    img = Image.open(src).convert("RGB")
    W, H = img.size
    arr = np.asarray(img).astype(np.float32)
    steps, masks_shown = [], []
    if a.lift:
        lm = sam_union(img, pts(a.lift), grow=1)
        masks_shown.append((lm, (255, 220, 0)))
        steps.append({"kind": "lift", "points": pts(a.lift), "amount": a.lift_amount, "px": int(lm.sum())})
        if not a.dry:
            arr = lift(arr, lm, a.lift_amount)
    em = np.zeros((H, W), bool)
    for p in a.edit:
        em |= poly_mask(p, W, H)
    if em.any():
        keep = sam_union(img, pts(a.keep)) if a.keep else np.zeros((H, W), bool)
        em &= ~keep
        masks_shown += [(em, (255, 0, 255)), (keep, (0, 255, 255))]
        steps.append({"kind": "edit", "polygons": a.edit, "keep": pts(a.keep), "model": a.model, "prompt": a.prompt,
                      "px": int(em.sum())})
    out_dir = ROOT / "out" / a.scene / "revise"
    if a.dry:
        preview(img, None, masks_shown, out_dir / f"{a.tag}_masks.jpg")
        print(f"dry: masks -> {out_dir / f'{a.tag}_masks.jpg'}; steps {[s['kind'] for s in steps]}, edit area {int(em.sum())} px")
        return 0
    usage = None
    if em.any():
        if not a.prompt:
            sys.exit("--edit needs --prompt")
        from azure_ai import edit_image
        cur = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        # the API repaints where the mask's alpha is 0; grown a little so the composite's feather has new pixels to use
        grown = cv2.dilate(em.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        mk = np.dstack([np.zeros((H, W, 3), np.uint8), np.where(grown, 0, 255).astype(np.uint8)])
        res = edit_image(cur, a.prompt, mask=Image.fromarray(mk, "RGBA"), deployment=a.model, size=f"{W}x{H}",
                         purpose=f"keyart_revise:{a.scene}:{a.tag}")
        usage = res.get("usage")
        new = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGB")
        if new.size != (W, H):
            new = new.resize((W, H), Image.LANCZOS)
        w = feather(em, 2.5)[..., None]
        arr = arr * (1 - w) + np.asarray(new).astype(np.float32) * w
    after = Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8))
    dst = src.with_name(f"{src.stem}_{a.tag}.png")
    after.save(dst)
    side = {"src": str(src.relative_to(ROOT)).replace("\\", "/"), "tag": a.tag, "steps": steps, "usage": usage,
            "made": datetime.datetime.now().isoformat(timespec="seconds"),
            "note": "tools/keyart_revise.py: only the masked pixels changed (edits feathered 2.5 px); the lift is a code adjustment"}
    dst.with_suffix(".json").write_text(json.dumps(side, indent=2, ensure_ascii=False), encoding="utf-8")
    preview(img, after, masks_shown, out_dir / f"{a.tag}_preview.jpg")
    print(f"-> {dst.relative_to(ROOT)}; preview {out_dir / f'{a.tag}_preview.jpg'}")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
