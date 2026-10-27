"""SAM 2 segmentation and the plate helpers several tools share (TASKS.md T12), moved verbatim from analyze_plate.py.

  Segmenter()                 SAM 2.1 on the GPU: masks from boxes, points, or a box with points
  box_px, contours            a box in plate fractions to px; a bool mask to normalized polygons
  critter_cover, critter_size what a crawling critter hides behind at its path ends; its body length at 4K
  grid_image                  the image with a labeled 10% grid, for a vision model to read coordinates off
  SAM_MODEL                   the SAM 2.1 checkpoint (pinned in cozy/models.py)

Importing this sets the Hugging Face cache to cache/hf as analyze_plate did: tools that build a Segmenter got that
setting from importing analyze_plate, and the pinned model is only there. torch and transformers load with the first
Segmenter, not at import.
"""
import os

from cozy.paths import ROOT, creature_id
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

from cozy.models import revision  # noqa: E402


SAM_MODEL = "facebook/sam2.1-hiera-large"


def grid_image(img, step=0.1):
    """Copy of the image with a labeled 10% grid (helps the model read coordinates)."""
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    W, H = im.size
    try:
        font = ImageFont.truetype("arial.ttf", max(14, W // 90))
    except OSError:
        font = ImageFont.load_default()
    for i in range(1, 10):
        x, y = int(W * i * step), int(H * i * step)
        d.line([(x, 0), (x, H)], fill=(255, 255, 0), width=1)
        d.line([(0, y), (W, y)], fill=(255, 255, 0), width=1)
        d.text((x + 3, 3), f"{i * step:.1f}", fill=(255, 255, 0), font=font)
        d.text((3, y + 3), f"{i * step:.1f}", fill=(255, 255, 0), font=font)
    return im


class Segmenter:
    def __init__(self):
        import torch
        from transformers import Sam2Model, Sam2Processor
        self.torch = torch
        self.proc = Sam2Processor.from_pretrained(SAM_MODEL, revision=revision(SAM_MODEL))
        self.model = Sam2Model.from_pretrained(SAM_MODEL, revision=revision(SAM_MODEL)).to("cuda").eval()

    def masks(self, img, boxes_px, keep_area=(0.08, 1.4)):
        """One mask per box (bool HxW at the image size): best of 3 candidates by predicted IoU among those whose
        area is plausible for the box."""
        torch = self.torch
        out = []
        W, H = img.size
        for i in range(0, len(boxes_px), 6):
            chunk = boxes_px[i:i + 6]
            inp = self.proc(images=img, input_boxes=[[list(map(float, b)) for b in chunk]], return_tensors="pt").to("cuda")
            with torch.no_grad():
                res = self.model(**inp, multimask_output=True)
            ms = self.proc.post_process_masks(res.pred_masks.cpu(), inp["original_sizes"])[0]   # (n, 3, H, W)
            sc = res.iou_scores.cpu().numpy()[0]
            for j, b in enumerate(chunk):
                barea = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
                best, bs = None, -1
                for k in range(ms.shape[1]):
                    m = ms[j, k].numpy().astype(bool)
                    frac = m.sum() / barea
                    s = float(sc[j, k]) - (0.5 if not (keep_area[0] <= frac <= keep_area[1]) else 0)
                    if s > bs:
                        best, bs = m, s
                out.append(best)
        return out

    def point_candidates(self, img, points_px):
        """SAM's 3 candidate masks (bool HxW) and predicted IoUs for each single-point prompt."""
        torch = self.torch
        out = []
        for i in range(0, len(points_px), 6):
            chunk = points_px[i:i + 6]
            inp = self.proc(images=img, input_points=[[[[float(x), float(y)]] for x, y in chunk]], input_labels=[[[1] for _ in chunk]],
                            return_tensors="pt").to("cuda")
            with torch.no_grad():
                res = self.model(**inp, multimask_output=True)
            ms = self.proc.post_process_masks(res.pred_masks.cpu(), inp["original_sizes"])[0]   # (n, 3, H, W)
            sc = res.iou_scores.cpu().numpy()[0]
            for j in range(len(chunk)):
                out.append([(ms[j, k].numpy().astype(bool), float(sc[j, k])) for k in range(ms.shape[1])])
        return out

    def prompt_candidates(self, img, box_px, points_px, labels):
        """SAM's 3 candidate masks (bool HxW) and predicted IoUs for one object prompted with a box and points
        (labels 1 = on the object, 0 = not on it: the view beside a plant in front of a window)."""
        torch = self.torch
        inp = self.proc(images=img, input_boxes=[[list(map(float, box_px))]],
                        input_points=[[[[float(x), float(y)] for x, y in points_px]]], input_labels=[[list(map(int, labels))]],
                        return_tensors="pt").to("cuda")
        with torch.no_grad():
            res = self.model(**inp, multimask_output=True)
        ms = self.proc.post_process_masks(res.pred_masks.cpu(), inp["original_sizes"])[0]   # (1, 3, H, W)
        sc = res.iou_scores.cpu().numpy()[0]
        return [(ms[0, k].numpy().astype(bool), float(sc[0, k])) for k in range(ms.shape[1])]


def critter_cover(seg, img, path, size, body_h=0.48, depth=None):
    """What the crawling critter goes behind at its path ends (bool HxW, or None): SAM objects at points just past
    each end (0.3-1.8 body lengths out along the path, at mid-body height), so it comes out from behind and goes
    out of sight behind real things (critters.js pushes the ends in until it is covered; plate_prep writes
    occ.png). A candidate that also covers the middle of the path (the surface it crawls on) or more than 5% of
    the frame is skipped, and with the depth (float, nearer is larger) so is one farther than the ground at its end:
    a patch of the same ground, which the creature would melt into (critter_ends.cover_ok; the Burdock Shelter's
    flat wet stone and leaf litter, 2026-10-25, L144)."""
    from critter_ends import cover_ok
    W, H = img.size
    P = [(float(x) * W, float(y) * H) for x, y in path]
    seglen = [np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(P, P[1:])]
    L = float(sum(seglen))
    # the band the creature fills along the middle of the path (1.5 body lengths in from each end)
    band = np.zeros((H, W), bool)
    acc = 0.0
    for (a, b), l in zip(zip(P, P[1:]), seglen):
        for t in np.arange(0, l, 4.0):
            d = acc + t
            if 1.5 * size <= d <= L - 1.5 * size:
                x, y = a[0] + (b[0] - a[0]) * t / l, a[1] + (b[1] - a[1]) * t / l
                band[int(max(0, y - body_h * size)):int(min(H, y + 1)), int(max(0, x - 0.3 * size)):int(min(W, x + 0.3 * size))] = True
        acc += l
    pts, ends = [], []
    for b, a in ((P[0], P[1]), (P[-1], P[-2])):
        l = max(1e-6, float(np.hypot(b[0] - a[0], b[1] - a[1])))
        ux, uy = (b[0] - a[0]) / l, (b[1] - a[1]) / l
        for k in (0.3, 0.8, 1.3, 1.8):
            x, y = b[0] + ux * k * size, b[1] + uy * k * size - 0.5 * body_h * size
            if 0 <= x < W and 0 <= y < H:
                pts.append((x, y))
                ends.append((b[0] * 3840 / W, b[1] * 2160 / H))
    if not pts:
        return None
    cover = np.zeros((H, W), bool)
    nb = max(1, int(band.sum()))
    for (x, y), e, cands in zip(pts, ends, seg.point_candidates(img, pts)):
        ok = [(s, m) for m, s in cands if m[int(y), int(x)] and m.mean() < 0.05 and (m & band).sum() / nb < 0.02
              and (depth is None or cover_ok(m, depth, e))]
        if ok:
            cover |= max(ok, key=lambda t: t[0])[1]
    return cover if cover.any() else None


CRITTER_M = {"snail": 0.06, "ladybug": 0.008, "beetle": 0.025, "shieldbug": 0.014, "gecko": 0.12, "frog": 0.07, "mouse": 0.09}   # body length, m; keyed by creature_id()


def critter_size(crit, horizon=0.45, cam_h=1.1, readable=2.2):
    """The critter's body length at 4K px: about twice life at the depth of its path. On a surface below eye level
    a meter there spans (row - horizon) / camera height px (a seated eye ~1.1 m above it); above eye level (a sill,
    a shelf) the model's estimate is used. Kept to 18-60 px. An 80 px snail on the ramen alley's steps (8x life)
    covered the riser behind it and read as floating in front of the step (user 2026-10-19)."""
    ys = [float(p[1]) for p in crit.get("path") or []]
    y = sum(ys) / len(ys) if ys else 0.6
    if y > horizon + 0.03:
        px = CRITTER_M.get(creature_id(crit.get("creature")), 0.05) * readable * (y - horizon) * 2160 / cam_h
    else:
        px = float(crit.get("size") or 0.01) * 3840
    return float(min(max(px, 18.0), 60.0))


def contours(mask, W, H, eps=1.5, min_area=40):
    """Polygons (normalized, y down) of a bool mask; computed at 1920 px wide."""
    s = 1920 / W
    small = cv2.resize(mask.astype(np.uint8) * 255, (1920, round(H * s)), interpolation=cv2.INTER_AREA)
    cs, _ = cv2.findContours((small > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    polys = []
    for c in cs:
        if cv2.contourArea(c) < min_area:
            continue
        a = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(a) >= 3:
            polys.append([[round(float(x) / 1920, 5), round(float(y) / small.shape[0], 5)] for x, y in a])
    return polys


def box_px(box, W, H, grow=0.06):
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * grow, (y1 - y0) * grow
    return [max(0, (x0 - dx) * W), max(0, (y0 - dy) * H), min(W - 1, (x1 + dx) * W), min(H - 1, (y1 + dy) * H)]
