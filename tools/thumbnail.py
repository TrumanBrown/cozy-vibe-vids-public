"""YouTube thumbnails for a scene: a chosen frame, graded to pop at small sizes, with pixel-font text.

  .venv\\Scripts\\python tools\\thumbnail.py assets\\thumbnails\\<scene>.json [--only name] [--refresh]

The spec (JSON) lists variants (YouTube's "Test & compare" takes up to 3):
  {"scene": "scenes/<scene>", "out": "out/<scene>/thumbnails",
   "variants": [{"name": "let-it-rain", "frame": 875981,
                 "zoom": 1.0, "center": [0.5, 0.5],             # optional crop (zoom > 1 = closer)
                 "grade": {"sat": 1.2, ...},                     # optional overrides of GRADE below
                 "bands": [{"y0": 0, "y1": 0.14, "color": "#0a070d", "alpha": 1, "feather": 0}],
                 "text": [{"text": "let it rain", "px": 42, "x": 0.5, "y": 0.4, "style": "title", "bold": true},
                          {"text": "distant thunder", "px": 18, "y": 0.28, "style": "kicker"}]}]}
  frame: a frame index of the full video timeline (rendered once with `node src/cli.mjs still`, cached in
         out/<scene>/stills/thumb_4k_f<frame>.png; --refresh re-renders) or a path to an image.
  bands: horizontal color bars over the graded frame (letterbox bars, or a scrim under text with a
         feathered edge); y0, y1, feather as fractions of the height.
  mat:   {"color", "margin": [l, t, r, b]}: the frame becomes a photo on a paper mat (a polaroid).
  panels: pixel-cornered rectangles {x0, y0, x1, y1, fill, alpha, border} behind text (a player card).
  insets: picture-in-picture, a magnified part of a frame in a pixel-bordered rectangle or circle,
         optionally boxed and connected to its place in the main image ("callout"); see draw_inset.
  chips: rows of tags laid out left to right: {x, y, px, gap, items: [{text, style}]}.
  badges: the same rows at the spec's top level, drawn on every variant (a variant's own "badges" replaces them).
  text:  px = size of one font pixel at 4K (a multiple of 3 keeps the 1280x720 copy pixel-sharp);
         "\\n" stacks lines; x = anchor of the block (align: center | left | right); y = middle of the
         block's capital height; style = a key of STYLES, plus any style field overridden inline:
         fill, fill2 (vertical gradient), shadow, glow, bold, italic, tracking, leading, opacity,
         rules [length, gap] (lines either side of a one-line title, in font pixels),
         box {fill, alpha, border, border_alpha, pad [x, y], planks (seam every n rows), hang (chains up
         to this frame fraction)} (a pixel-cornered panel behind the text). Styles: title, kicker, amber,
         label, badge (dark on a warm tag), chip (light on a dark tag), ink (on paper), sign (wooden sign).
  Smooth text (user 2026-10-20: thumbnails fit the video's look; the pixel font is for Minecraft and pixel looks):
         an item (or a badges/chips row) with "font" = a config/fonts.json id is drawn in that font: size =
         font size in px at 4K, y = the ink's middle; style = a key of TSTYLES (soft, neon, neon_warm,
         neon_cyan, chip, tag, ink, brush, gold, stamp), overridable inline: fill, fill2, opacity, shadow,
         shadow_alpha, shadow_blur, shadow_off, glow [{color, blur, alpha, mode: over | screen, grow}], neon
         (a color: a lit tube), stroke, stroke_w, tracking, leading, vertical (columns of characters, right to
         left), rotate (degrees), weight, box {fill, alpha, border, border_w, radius, pad [x, y], shadow}
         (effect sizes in em). A row of smooth tags: {x, y, font, size, gap (px), style, items}.
  cards: flat things in the picture with text on them (a paper ticket, a sign board, a noren with slits):
         see draw_card. scrims: soft elliptical shades behind text [{x, y, rx, ry, alpha, color}].
         insets with "smooth": true get a plain anti-aliased frame (border_px, radius_px, border).
  Painterly pieces, for looks painted by hand (user 2026-10-26: a nature look in a pastel, painted style needs
  thumbnails in that style):
  page:  {color, color2, grain, mottle}: the canvas is a sheet of paper or cloth instead of the frame; "pictures" lay
         parts of the frame on it (draw_picture: a print with a margin, a painting with a torn edge, an arched window,
         ruled like a naturalist's plate, turned, with a soft shadow).
  washes: watercolor blobs behind words (draw_wash); "under": true paints one on the page under the pictures.
  strokes: hand-drawn ink lines and arrows through points (draw_stroke): leader lines to a label, a note's arrow.

Writes <name>.jpg (3840x2160, YouTube's recommended size; desktop upload limit 50 MB), <name>_1280.jpg
(1280x720, under the 2 MB mobile limit) and preview.png (the variants at YouTube's display sizes on its
dark page, with the duration badge, to judge readability). --feed <list.json> also writes
_feed_compare.png: each variant in a row of real competitor thumbnails, to judge whether it stands out.
"""
import argparse
import json
import pathlib
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from cozy.paths import ROOT
from cozy.images import lum
import pixelfont as pf  # noqa: E402

W, H = 3840, 2160

GRADE = {
    "bloom": 0.55, "bloom_thr": 0.62,   # glow around lanterns and lit windows
    "soft": 0.18,                       # dreamy full-frame glow (screen blend of a wide blur)
    "gamma": 0.9,                       # < 1 lifts the midtones (dusk scenes read dark at small sizes)
    "contrast": 0.25,                   # S-curve amount
    "sat": 1.12, "vib": 0.35,           # saturation, plus extra for muted colors
    "vignette": 0.35,                   # corner darkening
    "sharpen": 0.35,                    # unsharp mask on the final image
}

_BASE = {"fill": "#ffffff", "fill2": "#f3ecff", "tracking": 1, "space": 3, "leading": 2, "bold": False,
         "italic": False, "opacity": 1.0, "shadow": "#1b1226", "shadow_alpha": 0.9, "shadow_off": [1, 1],
         "glow": "#0b0710", "glow_alpha": 0.55, "glow_sigma": 1.1, "glow_grow": 1, "rules": None, "box": None}
STYLES = {
    "title": dict(_BASE),
    "kicker": {**_BASE, "fill": "#ffd88a", "fill2": "#ffc46b", "bold": True, "glow_alpha": 0.6, "glow_sigma": 1.2},
    # lantern-colored text
    "amber": {**_BASE, "fill": "#ffdc94", "fill2": "#ffa94a", "shadow": "#2a1206", "shadow_alpha": 0.95,
              "glow": "#140803", "glow_alpha": 0.5, "glow_sigma": 1.2},
    # on a panel or a bar: crisp, no glow
    "label": {**_BASE, "glow_alpha": 0.0, "shadow": "#000000", "shadow_alpha": 0.6},
    # dark letters on a solid warm badge (the music tag)
    "badge": {**_BASE, "fill": "#24150a", "fill2": "#24150a", "bold": True, "glow_alpha": 0.0, "shadow_alpha": 0.0,
              "box": {"fill": "#ffd88a", "alpha": 1.0, "border": "#7a4a12", "pad": [3, 2]}},
    # light letters on a dark translucent chip
    "chip": {**_BASE, "bold": True, "glow_alpha": 0.0, "shadow": "#000000", "shadow_alpha": 0.5,
             "box": {"fill": "#120b18", "alpha": 0.8, "border": "#ffd88a", "border_alpha": 0.9, "pad": [3, 2]}},
    # dark ink, for paper (a mat)
    "ink": {**_BASE, "fill": "#2a1a10", "fill2": "#3a2414", "glow_alpha": 0.0, "shadow_alpha": 0.0},
    # cream letters on a hanging wooden sign
    "sign": {**_BASE, "fill": "#ffe9c2", "fill2": "#f6d9a4", "bold": True, "glow_alpha": 0.0, "shadow": "#2a1408",
             "shadow_alpha": 0.85, "box": {"fill": "#7a5230", "alpha": 1.0, "border": "#3a2414", "planks": 4,
                                           "pad": [4, 3], "hang": 0.0}},
}
_ITEM_KEYS = ("text", "px", "x", "y", "style", "align")


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255


def blur(x, sigma):
    """Gaussian blur; wide ones run at reduced resolution (same look, much faster)."""
    if sigma < 12:
        return cv2.GaussianBlur(x, (0, 0), sigma)
    f = int(sigma // 6)
    h, w = x.shape[:2]
    s = cv2.resize(x, (w // f, h // f), interpolation=cv2.INTER_AREA)
    s = cv2.GaussianBlur(s, (0, 0), sigma / f)
    return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR)


def frame_image(spec, v, refresh):
    f = v["frame"]
    if isinstance(f, str):
        p = (ROOT / f) if not pathlib.Path(f).is_absolute() else pathlib.Path(f)
    else:
        scene = spec["scene"]
        d = ROOT / "out" / pathlib.Path(scene).name / "stills"
        p = d / f"thumb_4k_f{int(f):06d}.png"     # the renderer pads frame numbers to 6 digits
        if refresh or not p.exists():
            d.mkdir(parents=True, exist_ok=True)
            subprocess.run(["node", str(ROOT / "src" / "cli.mjs"), "still", scene, "--frames", str(int(f)),
                            "--out", str(d), "--name", "thumb"], cwd=ROOT, check=True)
    img = cv2.cvtColor(cv2.imread(str(p), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if img.shape[:2] != (H, W):
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_LANCZOS4)
    return img


def snap(v, step=3):
    return int(round(v / step)) * step


def region(img, zoom, center, out_w, out_h):
    """The part of a 4K frame W/zoom wide (aspect out_w:out_h) around center, scaled to out_w x out_h.
    Returns it and the transform (x0, y0, s): output = (source - (x0, y0)) * s."""
    if (out_w, out_h) == (W, H) and zoom <= 1:
        return img, (0.0, 0.0, 1.0)
    aspect = out_w / out_h
    rw = W / zoom
    rh = rw / aspect
    if rh > H:
        rh = H
        rw = rh * aspect
    x0 = min(max(center[0] * W - rw / 2, 0), W - rw)
    y0 = min(max(center[1] * H - rh / 2, 0), H - rh)
    s = out_w / rw
    m = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
    return cv2.warpAffine(img, m, (out_w, out_h), flags=cv2.INTER_LANCZOS4), (x0, y0, s)


def grade(img, g):
    h, w = img.shape[:2]
    x = img.astype(np.float32) / 255
    # Bloom from the bright light sources, a tight and a wide halo.
    hi = np.clip((lum(x) - g["bloom_thr"]) / (1 - g["bloom_thr"]), 0, 1) ** 2
    b = x * hi[..., None]
    x = x + g["bloom"] * (0.55 * blur(b, w * 0.004) + 0.45 * blur(b, w * 0.02))
    # Soft glow: screen with a wide blur of the frame.
    s = blur(np.clip(x, 0, 1), w * 0.012)
    x = 1 - (1 - np.clip(x, 0, 1)) * (1 - g["soft"] * s)
    x = np.clip(x, 0, 1) ** g["gamma"]
    x = x + g["contrast"] * (x * x * (3 - 2 * x) - x)
    y = lum(x)[..., None]
    sat = (x.max(-1, keepdims=True) - x.min(-1, keepdims=True))
    x = y + (x - y) * (g["sat"] + g["vib"] * (1 - np.clip(sat * 2, 0, 1)))
    u = (np.arange(w, dtype=np.float32) / w - 0.5) * 2
    v = (np.arange(h, dtype=np.float32) / h - 0.5) * 2
    r = np.sqrt(u[None, :] ** 2 * 0.8 + v[:, None] ** 2)
    t = np.clip((r - 0.55) / 0.85, 0, 1)
    x = x * (1 - g["vignette"] * (t * t * (3 - 2 * t)))[..., None]
    return np.clip(x, 0, 1)


def comp(x, mask, color, alpha=1.0, at=(0, 0)):
    """Composite color (an RGB triple or an image the size of mask) over x through mask, placed with its
    top-left corner at frame pixel at = (top, left); clipped to the frame."""
    top, left = at
    h, w = mask.shape
    y0, x0, y1, x1 = max(top, 0), max(left, 0), min(top + h, x.shape[0]), min(left + w, x.shape[1])
    if y1 <= y0 or x1 <= x0:
        return
    a = mask[y0 - top:y1 - top, x0 - left:x1 - left, None] * alpha
    c = color if np.ndim(color) == 1 else color[y0 - top:y1 - top, x0 - left:x1 - left]
    x[y0:y1, x0:x1] = x[y0:y1, x0:x1] * (1 - a) + c * a


def shape_mask(w, h, shape, cell, radius=1):
    """Pixel-art mask w x h (multiples of cell): a circle/ellipse or a rectangle with stepped corners."""
    cw, ch = w // cell, h // cell
    if shape == "circle":
        yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
        m = ((xx + 0.5 - cw / 2) / (cw / 2)) ** 2 + ((yy + 0.5 - ch / 2) / (ch / 2)) ** 2 <= 1.0
    else:
        m = np.ones((ch, cw), bool)
        for i in range(radius):
            k = radius - i
            m[i, :k] = m[i, cw - k:] = m[ch - 1 - i, :k] = m[ch - 1 - i, cw - k:] = False
    return np.kron(m, np.ones((cell, cell), np.float32))


def draw_panel(x, p):
    """A pixel-cornered panel in frame coordinates: {x0, y0, x1, y1, fill, alpha, border, border_w, cell}."""
    cell = p.get("cell", 12)
    x0, y0, x1, y1 = (snap(p[k] * (W if k[0] == "x" else H), cell) for k in ("x0", "y0", "x1", "y1"))
    r, bw = p.get("radius", 1), p.get("border_w", 1) if p.get("border") else 0
    if bw:
        comp(x, shape_mask(x1 - x0, y1 - y0, "rect", cell, r + bw), rgb(p["border"]), p.get("border_alpha", 1.0), (y0, x0))
    m = shape_mask(x1 - x0 - 2 * bw * cell, y1 - y0 - 2 * bw * cell, "rect", cell, r)
    comp(x, m, rgb(p.get("fill", "#120b18")), p.get("alpha", 0.8), (y0 + bw * cell, x0 + bw * cell))


def line_mask(shape, p0, p1, thick):
    m = np.zeros(shape, np.uint8)
    cv2.line(m, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), 255, int(thick), cv2.LINE_AA)
    return m.astype(np.float32) / 255


def draw_inset(x, spec, v, ins, refresh, main):
    """Picture-in-picture: a magnified part of a frame in a pixel-bordered rectangle or circle.
    ins: {x, y (center, frame fractions), w (width fraction), aspect, span (fraction of the source frame's
    width shown), center (source point, fractions), frame, shape: rect | circle, radius, border, border_w,
    outline_color, outline (cells), cell, shadow, grade, callout (bool: box the region in the main image
    and connect it)}. main = (x0, y0, s, ox, oy): where the main image's source pixels land.
    With "smooth": true it is a plain rounded rectangle or circle with an anti-aliased border instead
    (border_px, radius_px, border, shadow), for looks that aren't pixel art."""
    if ins.get("smooth"):
        w = int(round(ins["w"] * W))
        h = int(round(w / ins.get("aspect", 1.0)))
        src = frame_image(spec, {"frame": ins.get("frame", v["frame"])}, refresh)
        img, _ = region(src, 1 / ins["span"], ins["center"], w, h)
        pic = grade(img, {**GRADE, **v.get("grade", {}), "vignette": 0.25, **ins.get("grade", {})})
        bw, shape, r = int(ins.get("border_px", 12)), ins.get("shape", "rect"), ins.get("radius_px", 36)
        left, top = int(round(ins["x"] * W - w / 2 - bw)), int(round(ins["y"] * H - h / 2 - bw))
        outer = rrect(w + 2 * bw, h + 2 * bw, r + bw, shape)
        if ins.get("shadow", 0.5):
            m = 72
            comp(x, cv2.GaussianBlur(np.pad(outer, m), (0, 0), 24), rgb("#000000"), ins.get("shadow", 0.5),
                 (top - m + 16, left - m + 10))
        comp(x, outer, rgb(ins.get("border", "#fff4e0")), 1.0, (top, left))
        comp(x, rrect(w, h, r, shape), pic, 1.0, (top + bw, left + bw))
        return
    cell = ins.get("cell", 12)
    w = snap(ins["w"] * W, cell)
    h = snap(w / ins.get("aspect", 1.0), cell)
    src = frame_image(spec, {"frame": ins.get("frame", v["frame"])}, refresh)
    img, (sx0, sy0, s) = region(src, 1 / ins["span"], ins["center"], w, h)
    pic = grade(img, {**GRADE, **v.get("grade", {}), "vignette": 0.25, **ins.get("grade", {})})
    shape, rad = ins.get("shape", "rect"), ins.get("radius", 2)
    ob, bw = ins.get("outline", 1), ins.get("border_w", 2)
    pad = (ob + bw) * cell
    left, top = snap(ins["x"] * W - w / 2 - pad, cell), snap(ins["y"] * H - h / 2 - pad, cell)
    border, dark = rgb(ins.get("border", "#ffd88a")), rgb(ins.get("outline_color", "#120b18"))
    if ins.get("callout") and ins.get("frame", v["frame"]) == v["frame"]:
        mx0, my0, ms, ox, oy = main
        rx0, ry0 = (sx0 - mx0) * ms + ox, (sy0 - my0) * ms + oy
        rx1, ry1 = rx0 + w / s * ms, ry0 + h / s * ms
        rx0, ry0, rx1, ry1 = (snap(c, cell) for c in (rx0, ry0, rx1, ry1))
        icx, icy = left + pad + w / 2, top + pad + h / 2
        rcx, rcy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
        d = np.array([icx - rcx, icy - rcy])
        n = d / (np.linalg.norm(d) + 1e-6)
        t_r = min((rx1 - rx0) / 2 / (abs(n[0]) + 1e-6), (ry1 - ry0) / 2 / (abs(n[1]) + 1e-6))
        if shape == "circle":
            t_i = (w / 2 + pad)
        else:
            t_i = min((w / 2 + pad) / (abs(n[0]) + 1e-6), (h / 2 + pad) / (abs(n[1]) + 1e-6))
        p0 = (rcx + n[0] * t_r, rcy + n[1] * t_r)
        p1 = (icx - n[0] * t_i, icy - n[1] * t_i)
        frame_box = shape_mask(rx1 - rx0 + 2 * cell, ry1 - ry0 + 2 * cell, "rect", cell, 1)
        hole = np.zeros_like(frame_box)
        hole[2 * cell:-2 * cell, 2 * cell:-2 * cell] = 1
        comp(x, line_mask(x.shape[:2], p0, p1, 3 * cell), dark, 0.9)
        comp(x, frame_box * (1 - hole), dark, 0.9, (ry0 - cell, rx0 - cell))
        comp(x, line_mask(x.shape[:2], p0, p1, cell), border)
        ring = np.zeros((ry1 - ry0, rx1 - rx0), np.float32)
        ring[:cell], ring[-cell:], ring[:, :cell], ring[:, -cell:] = 1, 1, 1, 1
        comp(x, ring, border, 1.0, (ry0, rx0))
    F = shape_mask(w + 2 * pad, h + 2 * pad, shape, cell, rad + ob + bw)
    if ins.get("shadow", 0.55):
        m = 4 * cell
        sh = cv2.GaussianBlur(np.pad(F, m), (0, 0), 1.5 * cell)
        dx, dy = ins.get("shadow_off", [1, 1])
        comp(x, sh, dark, ins.get("shadow", 0.55), (top - m + dy * cell, left - m + dx * cell))
    comp(x, F, dark, 1.0, (top, left))
    comp(x, shape_mask(w + 2 * bw * cell, h + 2 * bw * cell, shape, cell, rad + bw), border, 1.0,
         (top + ob * cell, left + ob * cell))
    comp(x, shape_mask(w, h, shape, cell, rad), pic, 1.0, (top + pad, left + pad))


def expand_chips(row):
    """A row of chips {x, y, px, gap, items: [{text, style, ...}]} -> text items laid out left to right."""
    P, cur, out = int(row["px"]), row["x"] * W, []
    for c in row["items"]:
        st = {**STYLES[c.get("style", "chip")], **{k: v for k, v in c.items() if k not in _ITEM_KEYS}}
        m, _ = text_mask({"text": c["text"], "align": "left"}, st)
        bx = st["box"].get("pad", [3, 2])[0] if st["box"] else 0
        out.append({"style": "chip", **c, "px": P, "x": (cur + bx * P) / W, "y": row["y"], "align": "left"})
        cur += (m.shape[1] + 2 * bx + row.get("gap", 4)) * P
    return out


def apply_bands(x, bands):
    yy = (np.arange(H, dtype=np.float32) + 0.5) / H
    for b in bands:
        f = b.get("feather", 0.0)
        if f > 0:
            a = np.clip(np.minimum((yy - b["y0"]) / f + 1, (b["y1"] - yy) / f + 1), 0, 1)
            a = a * a * (3 - 2 * a)
        else:
            a = ((yy >= b["y0"]) & (yy < b["y1"])).astype(np.float32)
        a = (a * b.get("alpha", 1.0))[:, None, None]
        x[:] = x * (1 - a) + rgb(b.get("color", "#000000")) * a


def text_mask(item, st):
    """Font-pixel mask of the item's lines (stacked with st['leading'] blank rows, aligned per item)."""
    kw = dict(tracking=st["tracking"], bold=st["bold"], italic=st["italic"], space=st["space"])
    ms = [pf.render(t, **kw) for t in item["text"].split("\n")]
    if st["rules"] and len(ms) == 1:
        m = ms[0]
        ink = np.where(m[:pf.BASE].any(1))[0]
        mid = (ink.min() + ink.max()) // 2 if len(ink) else pf.BASE // 2
        ln, gap = st["rules"][:2]
        side = np.zeros((pf.ROWS, ln + gap), bool)
        side[mid, :ln] = True
        ms = [np.concatenate([side, m, side[:, ::-1]], 1)]
    w = max(m.shape[1] for m in ms)
    align = item.get("align", "center")
    out = []
    for i, m in enumerate(ms):
        d = w - m.shape[1]
        lpad = 0 if align == "left" else d if align == "right" else d // 2
        out.append(np.pad(m, ((0, 0), (lpad, d - lpad))))
        if i < len(ms) - 1:
            out.append(np.zeros((st["leading"], w), bool))
    return np.concatenate(out, 0), len(ms)


def place_text(x, item):
    st = {**STYLES[item.get("style", "title")], **{k: v for k, v in item.items() if k not in _ITEM_KEYS}}
    P, op = int(item["px"]), st["opacity"]
    m, n = text_mask(item, st)
    block = (n - 1) * (pf.ROWS + st["leading"]) + pf.BASE       # first capital top .. last baseline, in rows
    box = st["box"]
    bx, by = box.get("pad", [3, 2]) if box else (0, 0)
    g = 2 + int(np.ceil(st["glow_sigma"] * 3)) + st["glow_grow"] + max(abs(o) for o in st["shadow_off"])
    padx, pady = max(g, bx + 2), max(g, by + 2)
    m = np.pad(m, ((pady, pady), (padx, padx)))
    mh, mw = m.shape
    ink_w = (mw - 2 * padx) * P
    align = item.get("align", "center")
    left = item.get("x", 0.5) * W - padx * P - {"left": 0, "right": ink_w}.get(align, ink_w / 2)
    left = int(round(left / 3)) * 3
    top = int(round((item["y"] * H - (pady + block / 2) * P) / 3)) * 3
    big = lambda a: np.kron(a.astype(np.float32), np.ones((P, P), np.float32))
    # Region of the frame the text covers (clipped to the frame).
    x0, y0, x1, y1 = max(left, 0), max(top, 0), min(left + mw * P, W), min(top + mh * P, H)
    sl = (slice(y0, y1), slice(x0, x1))
    cut = lambda a: a[y0 - top: y1 - top, x0 - left: x1 - left]
    reg = x[sl]

    def over(alpha, color):
        nonlocal reg
        alpha = alpha * op
        reg = reg * (1 - alpha[..., None]) + color * alpha[..., None]

    if box:
        desc = m[pady + block: pady + pf.ROWS - pf.BASE + block].any()   # last line has descenders
        br0, br1 = pady - by, pady + block - 1 + (pf.ROWS - pf.BASE if desc else 0) + by
        bc0, bc1 = padx - bx, mw - padx - 1 + bx
        panel = np.zeros_like(m)
        panel[br0:br1 + 1, bc0:bc1 + 1] = True
        for rr, cc in ((br0, bc0), (br0, bc1), (br1, bc0), (br1, bc1)):
            panel[rr, cc] = False                                     # pixel-rounded corners
        inner = cv2.erode(panel.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)),
                          borderValue=0).astype(bool)
        fill_c = rgb(box.get("fill", "#120b18"))
        over(cut(big(panel)) * box.get("alpha", 0.75), fill_c)
        if box.get("planks"):                                         # wooden sign: plank seams
            seams = np.zeros_like(m)
            seams[[r for r in range(br0 + 1, br1) if (r - br0) % box["planks"] == 0], bc0:bc1 + 1] = True
            over(cut(big(seams & inner)), fill_c * 0.72)
        if box.get("border"):
            over(cut(big(panel & ~inner)) * box.get("border_alpha", 1.0), rgb(box["border"]))
    if st["glow_alpha"] > 0:
        gm = m.copy()
        for _ in range(st["glow_grow"]):
            gm = cv2.dilate(gm.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        a = cut(blur(big(gm), st["glow_sigma"] * P))
        over(np.clip(a * st["glow_alpha"] * 1.4, 0, st["glow_alpha"]), rgb(st["glow"]))
    if st["shadow_alpha"] > 0:
        dx, dy = st["shadow_off"]
        sm = np.roll(np.roll(m, dy, 0), dx, 1)
        over(cut(big(sm)) * st["shadow_alpha"], rgb(st["shadow"]))
    fill = np.zeros((mh * P, mw * P, 3), np.float32)
    rows = np.where(m.any(1))[0]
    r0, r1 = (rows.min(), rows.max() + 1) if len(rows) else (0, mh)
    ty = np.clip((np.arange(mh * P) / P - r0) / max(r1 - r0, 1), 0, 1)[:, None, None]
    fill[:] = rgb(st["fill"]) * (1 - ty) + rgb(st.get("fill2") or st["fill"]) * ty
    a = cut(big(m)) * op
    reg = reg * (1 - a[..., None]) + cut(fill) * a[..., None]
    x[sl] = reg
    if box and box.get("hang") is not None:                          # chains up to y = hang (frame fraction)
        cw = max(snap(P / 2), 3)
        y_top, y_bot = max(int(box["hang"] * H), 0), top + br0 * P
        for cc in (bc0 + 2, bc1 - 2):
            cx = left + cc * P + (P - cw) // 2
            if y_bot > y_top:
                x[y_top:y_bot, max(cx, 0):max(cx + cw, 0)] = rgb(box.get("hang_color", "#2c2522"))


def sharpen(img8, amount):
    if amount <= 0:
        return img8
    b = cv2.GaussianBlur(img8, (0, 0), 1.2)
    return cv2.addWeighted(img8, 1 + amount, b, -amount, 0)


# ---- Smooth text, cards and scrims, for looks that aren't pixel art (user 2026-10-20: thumbnails fit the video's
# look, not always the Minecraft-like pixel style). An item with "font" (a config/fonts.json id other than "pixel")
# is drawn here; sizes are px at 4K, effect sizes are fractions of the font size (em).
TSTYLES = {
    # white, with a soft shadow below and a faint dark glow: readable on any part of the picture
    "soft": {"fill": "#ffffff", "shadow": "#05030a", "shadow_alpha": 0.6, "shadow_blur": 0.07, "shadow_off": [0.0, 0.05],
             "glow": [{"color": "#05030a", "blur": 0.35, "alpha": 0.35}]},
    # a lit neon tube: near-white core, the color in three widening halos, screened over the picture like light
    "neon": {"fill": "#fff3fb", "neon": "#ff3fa6"},
    "neon_warm": {"fill": "#fff6e8", "neon": "#ff8c1a"},
    "neon_cyan": {"fill": "#effdff", "neon": "#33d6ff"},
    # light letters on a dark rounded tag (4K, 10 HR)
    "chip": {"fill": "#ffffff", "box": {"fill": "#120c18", "alpha": 0.8, "border": "#ffd88a", "border_w": 0.07,
                                        "radius": 0.32, "pad": [0.42, 0.24]}},
    # dark letters on a warm rounded tag
    "tag": {"fill": "#2a1206", "box": {"fill": "#ffd88a", "alpha": 1.0, "radius": 0.32, "pad": [0.45, 0.22]}},
    # ink on paper, cloth or wood: no glow
    "ink": {"fill": "#2a1a10"},
    "brush": {"fill": "#fbf6ee", "shadow": "#120404", "shadow_alpha": 0.45, "shadow_blur": 0.03, "shadow_off": [0.02, 0.03]},
    "gold": {"fill": "#ffe7ad", "fill2": "#d6a043", "shadow": "#000000", "shadow_alpha": 0.6, "shadow_blur": 0.03,
             "shadow_off": [0.02, 0.03]},
    # a round red seal (hanko) around short text
    "stamp": {"fill": "#c8322a", "opacity": 0.92, "box": {"fill": "#000000", "alpha": 0.0, "border": "#c8322a",
                                                          "border_w": 0.09, "radius": 9, "pad": [0.34, 0.34]}},
    # warm cream lettering over a dark painting, with a soft shadow (labels on a naturalist's plate)
    "cream": {"fill": "#f5ecd8", "shadow": "#120c08", "shadow_alpha": 0.75, "shadow_blur": 0.08, "shadow_off": [0.0, 0.04],
              "glow": [{"color": "#120c08", "blur": 0.35, "alpha": 0.35}]},
    # a small paper tag in pastel colors (4K, 10 HR on the painterly concepts)
    "paper_tag": {"fill": "#3a3027", "box": {"fill": "#f3ead6", "alpha": 0.96, "border": "#8f9c7c", "border_w": 0.06,
                                              "radius": 0.18, "pad": [0.42, 0.2]}},
}
_TTF_KEYS = ("text", "size", "x", "y", "style", "align", "font")
ROTATE_V = set("ー－-〜～…‥―")                  # turned 90 degrees in vertical text
_FONTS = {}


def ttf_font(fid, size, weight=None):
    key = (fid, int(round(size)), weight)
    if key not in _FONTS:
        import intro_title as IT                     # fonts from config/fonts.json, fetched once and pinned by sha256
        path, entry = IT.font_file(fid)
        if path is None:
            sys.exit(f"thumbnail: {fid!r} is the pixel font: leave out \"font\" to draw an item in pixels")
        f = ImageFont.truetype(str(path), int(round(size)))
        w = weight or entry.get("weight")
        if w:
            try:
                f.set_variation_by_axes([w])
            except Exception:
                pass
        _FONTS[key] = f
    return _FONTS[key]


def ttf_mask(item, st):
    """The item's text as a float mask (lines stacked; columns right to left when vertical) and its ink box."""
    size = float(item["size"])
    f = ttf_font(item["font"], size, st.get("weight"))
    lines = item["text"].split("\n")
    import intro_title as IT
    miss = IT.missing_glyphs(f, item["text"].replace("\n", ""))
    if miss:
        sys.exit(f"thumbnail: font {item['font']} has no glyph for {''.join(sorted(miss))!r} in {item['text']!r}")
    align = item.get("align", "center")
    if st.get("vertical"):
        step, cell = size * (1.0 + st.get("tracking", 0.06)), int(size * 1.5)
        cols = []
        for ln in lines:
            col = np.zeros((int(step * len(ln)) + cell, cell), np.float32)
            for i, ch in enumerate(ln):
                g = Image.new("L", (cell, cell), 0)
                ImageDraw.Draw(g).text((cell / 2, cell / 2), ch, font=f, fill=255, anchor="mm")
                if ch in ROTATE_V:
                    g = g.rotate(-90)
                y0 = int(round(i * step))
                col[y0:y0 + cell] = np.maximum(col[y0:y0 + cell], np.asarray(g, np.float32) / 255)
            cols.append(col)
        gap = int(size * st.get("leading", 0.3))
        m = np.zeros((max(c.shape[0] for c in cols), sum(c.shape[1] for c in cols) + gap * (len(cols) - 1)), np.float32)
        xr = m.shape[1]
        for c in cols:
            m[:c.shape[0], xr - c.shape[1]:xr] = c
            xr -= c.shape[1] + gap
    else:
        track = st.get("tracking", 0.0) * size
        asc, desc = f.getmetrics()
        lead = st.get("leading", 0.18) * size
        widths = [(sum(f.getlength(ch) for ch in ln) + track * max(len(ln) - 1, 0)) if track else f.getlength(ln) for ln in lines]
        wmax, pad = max(widths), int(size * 0.5)
        img = Image.new("L", (int(wmax) + 2 * pad, int((asc + desc) * len(lines) + lead * (len(lines) - 1)) + 2 * pad), 0)
        d = ImageDraw.Draw(img)
        y = pad
        for ln, w in zip(lines, widths):
            x0 = pad + {"left": 0, "right": wmax - w}.get(align, (wmax - w) / 2)
            if track:
                for ch in ln:
                    d.text((x0, y), ch, font=f, fill=255)
                    x0 += f.getlength(ch) + track
            else:
                d.text((x0, y), ln, font=f, fill=255)
            y += asc + desc + lead
        m = np.asarray(img, np.float32) / 255
    ys, xs = np.where(m > 0.04)
    return m, ((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else (0, 0, m.shape[1], m.shape[0]))


def rrect(w, h, r, shape="rect"):
    """Anti-aliased rounded rectangle (or ellipse) mask, 2x supersampled."""
    s = 2
    im = Image.new("L", (max(w, 1) * s, max(h, 1) * s), 0)
    d = ImageDraw.Draw(im)
    if shape == "circle":
        d.ellipse((0, 0, w * s - 1, h * s - 1), fill=255)
    else:
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=max(0, int(r * s)), fill=255)
    return np.asarray(im.resize((max(w, 1), max(h, 1)), Image.LANCZOS), np.float32) / 255


def _dilate(m, r):
    k = max(int(round(r)), 1) * 2 + 1
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


def _shift(m, dx, dy):
    return cv2.warpAffine(m, np.float32([[1, 0, dx], [0, 1, dy]]), (m.shape[1], m.shape[0]))


def place_ttf(cv, item):
    """Draw a smooth-font item on cv (float RGB, the frame or a card); x, y are fractions of cv (y = the ink's
    middle), align picks which ink edge sits at x. Layers back to front: box, shadow, glows (neon screens like
    light), stroke, fill (fill -> fill2 top to bottom); "rotate" turns the whole item around its ink center."""
    st = {**TSTYLES.get(item.get("style", "soft"), {}), **{k: v for k, v in item.items() if k not in _TTF_KEYS}}
    size = float(item["size"])
    m, (ix0, iy0, ix1, iy1) = ttf_mask(item, st)
    box = st.get("box")
    bp = [p * size for p in box.get("pad", [0.4, 0.2])] if box else [0.0, 0.0]
    M = int(size * 1.3 + max(bp)) + 4                                   # room for the glows, shadow and box
    m = np.pad(m, M)
    ix0, iy0, ix1, iy1 = ix0 + M, iy0 + M, ix1 + M, iy1 + M
    h, w = m.shape
    layers = []                                                          # (alpha mask, color, mode)
    if box:
        bx0, by0 = int(round(ix0 - bp[0])), int(round(iy0 - bp[1]))
        bw_, bh_ = int(round(ix1 - ix0 + 2 * bp[0])), int(round(iy1 - iy0 + 2 * bp[1]))
        if box.get("radius", 0.3) >= 0.5:                                # a round seal: as wide as it is high
            bw_ = bh_ = max(bw_, bh_)
            bx0, by0 = int(round((ix0 + ix1) / 2 - bw_ / 2)), int(round((iy0 + iy1) / 2 - bh_ / 2))
        r = min(box.get("radius", 0.3) * size, min(bw_, bh_) / 2)
        outer = np.zeros_like(m)
        outer[by0:by0 + bh_, bx0:bx0 + bw_] = rrect(bw_, bh_, r)
        if box.get("shadow", 0):
            layers.append((_shift(blur(outer, size * 0.12), 0, size * 0.06) * box["shadow"], rgb("#000000"), "over"))
        b = int(round(box.get("border_w", 0) * size)) if box.get("border") else 0
        inner = outer
        if b:
            inner = np.zeros_like(m)
            inner[by0 + b:by0 + bh_ - b, bx0 + b:bx0 + bw_ - b] = rrect(bw_ - 2 * b, bh_ - 2 * b, max(r - b, 0))
        layers.append((inner * box.get("alpha", 1.0), rgb(box.get("fill", "#000000")), "over"))
        if b:
            layers.append((np.clip(outer - inner, 0, 1) * box.get("border_alpha", 1.0), rgb(box["border"]), "over"))
    if st.get("shadow_alpha", 0) > 0:
        dx, dy = (o * size for o in st.get("shadow_off", [0.0, 0.05]))
        sh = _shift(blur(m, max(st.get("shadow_blur", 0.06) * size, 0.6)), dx, dy)
        layers.append((np.clip(sh * 1.3, 0, 1) * st["shadow_alpha"], rgb(st.get("shadow", "#000000")), "over"))
    glows = list(st.get("glow") or [])                                  # dark halos first, then the neon's light over them
    if st.get("neon"):
        c = st["neon"]
        glows += [{"color": c, "blur": 0.6, "alpha": 0.5, "mode": "screen", "grow": 0.04},
                  {"color": c, "blur": 0.2, "alpha": 0.9, "mode": "screen", "grow": 0.03},
                  {"color": c, "blur": 0.05, "alpha": 1.0, "mode": "screen", "grow": 0.035}]
    for g in glows:
        gm = _dilate(m, g["grow"] * size) if g.get("grow") else m
        a = np.clip(blur(gm, max(g["blur"] * size, 0.6)) * g.get("gain", 1.8), 0, 1) * g.get("alpha", 0.5)
        layers.append((a, rgb(g["color"]), g.get("mode", "over")))
    if st.get("stroke") and st.get("stroke_w", 0) > 0:
        layers.append((_dilate(m, st["stroke_w"] * size), rgb(st["stroke"]), "over"))
    t = np.clip((np.arange(h, dtype=np.float32) - iy0) / max(iy1 - iy0, 1), 0, 1)[:, None, None]
    fill = np.broadcast_to(rgb(st.get("fill", "#ffffff")) * (1 - t) + rgb(st.get("fill2") or st.get("fill", "#ffffff")) * t, (h, w, 3))
    layers.append((m * st.get("opacity", 1.0), fill, "over"))
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    if st.get("rotate"):
        R = cv2.getRotationMatrix2D((cx, cy), st["rotate"], 1.0)
        turn = lambda a: cv2.warpAffine(np.ascontiguousarray(a, np.float32), R, (w, h), flags=cv2.INTER_LINEAR)
        layers = [(turn(a), c if np.ndim(c) == 1 else turn(c), md) for a, c, md in layers]
    ch, cw = cv.shape[:2]
    ax = {"left": ix0, "right": ix1}.get(item.get("align", "center"), cx)
    left, top = int(round(item.get("x", 0.5) * cw - ax)), int(round(item.get("y", 0.5) * ch - cy))
    y0, x0, y1, x1 = max(top, 0), max(left, 0), min(top + h, ch), min(left + w, cw)
    if y1 <= y0 or x1 <= x0:
        return
    reg = cv[y0:y1, x0:x1]
    for a, c, md in layers:
        a = a[y0 - top:y1 - top, x0 - left:x1 - left, None]
        c = c if np.ndim(c) == 1 else c[y0 - top:y1 - top, x0 - left:x1 - left]
        reg[:] = 1 - (1 - reg) * (1 - a * c) if md == "screen" else reg * (1 - a) + c * a


def expand_chips_ttf(row):
    """A row of smooth-font tags {x, y, font, size, gap (px), style, items: [{text, ...}]}, laid out left to right."""
    cur, out = row["x"] * W, []
    for c in row["items"]:
        it = {"font": row["font"], "size": row["size"], "style": row.get("style", "chip"), **c}
        st = {**TSTYLES.get(it["style"], {}), **{k: v for k, v in it.items() if k not in _TTF_KEYS}}
        _, (ix0, _, ix1, _) = ttf_mask(it, st)
        bp = st["box"].get("pad", [0.4, 0.2])[0] * it["size"] if st.get("box") else 0
        out.append({**it, "x": (cur + bp) / W, "y": row["y"], "align": "left"})
        cur += (ix1 - ix0) + 2 * bp + row.get("gap", 24)
    return out


def draw_card(x, c):
    """A flat thing in the picture with text on it: a paper ticket, a sign board, a noren with slits. Drawn at its
    own size, turned by "rotate" degrees, with a soft drop shadow. c: {x, y (its center, frame fractions), w, h (px),
    rotate, fill, fill2 (top to bottom), alpha, radius (px), border, border_w (px), grain (paper or cloth texture),
    shadow {alpha, blur, off: [dx, dy]} (px), slits {n, w (px), depth (fraction of h, from the bottom)},
    hem {h (px), color} (a band along the top), lines: [smooth-font items, x/y as fractions of the card]}."""
    w, h = int(c["w"]), int(c["h"])
    a = rrect(w, h, c.get("radius", 0))
    if c.get("slits"):
        s = c["slits"]
        for i in range(1, s["n"]):
            cx = int(round(i * w / s["n"]))
            sw = s.get("w", 14)
            a[int(h * (1 - s.get("depth", 0.75))):, cx - sw // 2: cx - sw // 2 + sw] = 0
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    col = np.ascontiguousarray(np.broadcast_to(rgb(c.get("fill", "#efe4cf")) * (1 - t)
                                               + rgb(c.get("fill2") or c.get("fill", "#efe4cf")) * t, (h, w, 3)))
    if c.get("grain"):
        rng = np.random.default_rng(7)
        n = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 1.2)
        col *= (1 + c["grain"] * n / max(float(n.std()), 1e-6))[..., None]
    if c.get("hem"):
        hh = int(c["hem"]["h"])
        col[:hh] = col[:hh] * 0.35 + rgb(c["hem"].get("color", "#000000")) * 0.65
    if c.get("cloth") and c.get("slits"):                        # a noren: soft folds, each panel's hem sagging a little
        n, cl = c["slits"]["n"], c["cloth"]
        u = (np.arange(w, dtype=np.float32) % (w / n)) / (w / n)
        shade = (1 - cl.get("folds", 0.14) * (1 - np.sin(np.pi * u))) * (1 + 0.035 * np.sin(2 * np.pi * u * 3 + 1.3))
        col *= shade[None, :, None]
        sag = cl.get("sag", 0)
        if sag:
            bottom = h - 1 - sag * (1 - np.sin(np.pi * u))
            a *= np.clip(bottom[None, :] - np.arange(h, dtype=np.float32)[:, None], 0, 1)
    if c.get("border") and c.get("border_w"):
        b = int(c["border_w"])
        inner = np.zeros_like(a)
        inner[b:h - b, b:w - b] = rrect(w - 2 * b, h - 2 * b, max(c.get("radius", 0) - b, 0))
        ring = np.clip(a - inner, 0, 1)[..., None]
        col = col * (1 - ring) + rgb(c["border"]) * ring
    col = np.clip(col, 0, 1)
    for ln in c.get("lines", []):
        place_ttf(col, ln)
    ang = c.get("rotate", 0)
    if ang:
        R = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        nw = int(abs(w * R[0, 0]) + abs(h * R[0, 1])) + 4
        nh = int(abs(w * R[0, 1]) + abs(h * R[0, 0])) + 4
        R[0, 2] += nw / 2 - w / 2
        R[1, 2] += nh / 2 - h / 2
        a = cv2.warpAffine(a, R, (nw, nh), flags=cv2.INTER_LINEAR)
        col = cv2.warpAffine(col, R, (nw, nh), flags=cv2.INTER_LINEAR)
        w, h = nw, nh
    a = a * c.get("alpha", 1.0)
    left, top = int(round(c["x"] * W - w / 2)), int(round(c["y"] * H - h / 2))
    sh = c.get("shadow", {"alpha": 0.5, "blur": 22, "off": [10, 18]})
    if sh:
        m = int(sh.get("blur", 22) * 3)
        s = cv2.GaussianBlur(np.pad(a, m), (0, 0), sh.get("blur", 22))
        dx, dy = sh.get("off", [10, 18])
        comp(x, s, rgb("#000000"), sh.get("alpha", 0.5), (top - m + int(dy), left - m + int(dx)))
    comp(x, a, col, 1.0, (top, left))


def apply_scrims(x, scrims):
    """Soft dark (or tinted) elliptical shades behind text, so it reads on a busy picture:
    [{x, y, rx, ry (frame fractions), alpha, color}]."""
    yy = ((np.arange(H, dtype=np.float32) + 0.5) / H)[:, None]
    xx = ((np.arange(W, dtype=np.float32) + 0.5) / W)[None, :]
    for s in scrims:
        d = ((xx - s["x"]) / s["rx"]) ** 2 + ((yy - s["y"]) / s["ry"]) ** 2
        comp(x, np.exp(-d * 1.6) * s.get("alpha", 0.4), rgb(s.get("color", "#05030a")))


def font(size):
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


# ---- Painterly pieces, for looks painted by hand (user 2026-10-26 on the Burdock Shelter: more variety; they still
# defaulted to blocky, similar text, and a nature look in a pastel, painted style needs thumbnails to match): a sheet
# of paper, the picture laid on it (a print with a margin, a painting with a torn edge, an arched
# window, ruled like a naturalist's plate), watercolor washes behind words, and hand-drawn ink lines and arrows.

def noise_field(h, w, scale, seed):
    """A smooth random field (zero mean, unit spread) with features about `scale` px across."""
    rng = np.random.default_rng(seed)
    n = rng.standard_normal((max(2, int(h / scale) + 2), max(2, int(w / scale) + 2))).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    return n / max(float(n.std()), 1e-6)


def paper(h, w, p):
    """A sheet of paper or cloth: color (to color2, top to bottom), a fine grain and a large soft mottling."""
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    col = np.broadcast_to(rgb(p.get("color", "#f1e9d8")) * (1 - t) + rgb(p.get("color2") or p.get("color", "#f1e9d8")) * t,
                          (h, w, 3)).copy()
    seed = p.get("seed", 3)
    if p.get("grain", 0.035):
        col *= (1 + p.get("grain", 0.035) * noise_field(h, w, 1.6, seed))[..., None]
    if p.get("mottle", 0.025):
        col *= (1 + p.get("mottle", 0.025) * noise_field(h, w, 260, seed + 1))[..., None]
    return np.clip(col, 0, 1)


def deckle(a, amp, seed, scale=6.0):
    """The mask's edge moved in and out by up to about amp px, coarse and fine together: a torn sheet, or paint that
    stops unevenly. The edge stays about a pixel soft."""
    if amp <= 0:
        return a
    h, w = a.shape
    inside = (a > 0.5).astype(np.uint8)
    sd = cv2.distanceTransform(inside, cv2.DIST_L2, 5) - cv2.distanceTransform(1 - inside, cv2.DIST_L2, 5)
    n = 0.75 * noise_field(h, w, amp * scale, seed) + 0.25 * noise_field(h, w, max(amp * 1.1, 1.5), seed + 5)
    return np.clip((sd + amp * 0.55 * n) / 1.3 + 0.5, 0, 1).astype(np.float32)


def arch(w, h, r):
    """A window with a round top (a quarter-ellipse r px high at each corner meeting in the middle), 2x supersampled."""
    s = 2
    im = Image.new("L", (w * s, h * s), 0)
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, w * s - 1, 2 * r * s), fill=255)
    d.rectangle((0, r * s, w * s - 1, h * s - 1), fill=255)
    return np.asarray(im.resize((w, h), Image.LANCZOS), np.float32) / 255


def outline(w, h, shape, r, off, width):
    """A thin line off px outside a w x h shape (rect, rounded by r, or an arch with an r px top), width px wide."""
    def solid(dw, dh, grow):
        ww, hh = w + 2 * grow, h + 2 * grow
        m = arch(int(ww), int(hh), int(r + grow)) if shape == "arch" else rrect(int(ww), int(hh), max(r + grow, 0) if r else 0)
        out = np.zeros((dh, dw), np.float32)
        y0, x0 = (dh - m.shape[0]) // 2, (dw - m.shape[1]) // 2
        out[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = m
        return out
    dw, dh = int(w + 2 * (off + width) + 4), int(h + 2 * (off + width) + 4)
    return np.clip(solid(dw, dh, off + width) - solid(dw, dh, off), 0, 1), dw, dh


def turn(a, col, ang):
    """A layer (alpha, color) turned ang degrees about its middle, grown to hold its corners."""
    h, w = a.shape
    R = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    nw, nh = int(abs(w * R[0, 0]) + abs(h * R[0, 1])) + 4, int(abs(w * R[0, 1]) + abs(h * R[0, 0])) + 4
    R[0, 2] += nw / 2 - w / 2
    R[1, 2] += nh / 2 - h / 2
    warp = lambda m: cv2.warpAffine(np.ascontiguousarray(m, np.float32), R, (nw, nh), flags=cv2.INTER_LINEAR)  # noqa: E731
    return warp(a), warp(col)


def draw_picture(x, src, pic, g):
    """A part of the frame laid on the page, like a print, a painting or a window: {zoom, center (of the crop in the
    frame), x, y (its middle on the page, fractions), w, h (px), rotate (degrees), radius (px) or arch (px: a round top
    that high), deckle (px: an uneven edge), margin {width (px), color, deckle (px)} (paper around it, like a print's
    white edge), rules [{offset (px out from its edge), width (px), color, alpha}] (thin ink lines around it, like a
    naturalist's plate), shadow {alpha, blur, off} (px; null for none), grade (overrides), seed}."""
    w, h = int(pic["w"]), int(pic["h"])
    img, _ = region(src, pic.get("zoom", 1.0), pic.get("center", [0.5, 0.5]), w, h)
    col = grade(img, {**g, **pic.get("grade", {})})
    shape, r = ("arch", int(pic["arch"])) if pic.get("arch") else ("rect", int(pic.get("radius", 0)))
    a = arch(w, h, r) if shape == "arch" else rrect(w, h, r)
    seed = pic.get("seed", 11)
    a = deckle(a, pic.get("deckle", 0), seed)
    mg = pic.get("margin") or {}
    rules = pic.get("rules") or []
    pad = int(max([mg.get("width", 0) + mg.get("deckle", 0) * 2] + [q["offset"] + q["width"] for q in rules] + [0])) + 8
    H2, W2 = h + 2 * pad, w + 2 * pad
    A, C = np.zeros((H2, W2), np.float32), np.zeros((H2, W2, 3), np.float32)
    if mg:
        mw = int(mg.get("width", 30))
        mm, _, _ = outline(w, h, shape, r, -1, mw + 1)
        body = np.zeros((H2, W2), np.float32)
        y0, x0 = (H2 - mm.shape[0]) // 2, (W2 - mm.shape[1]) // 2
        body[y0:y0 + mm.shape[0], x0:x0 + mm.shape[1]] = mm
        body[pad:pad + h, pad:pad + w] = np.maximum(body[pad:pad + h, pad:pad + w], a)
        body = deckle(np.clip(body, 0, 1), mg.get("deckle", 0), seed + 2)
        A = body
        C[:] = paper(H2, W2, {"color": mg.get("color", "#f7f1e3"), "grain": 0.03, "mottle": 0.0, "seed": seed + 3})
    A_pic = np.zeros((H2, W2), np.float32)
    A_pic[pad:pad + h, pad:pad + w] = a
    C[pad:pad + h, pad:pad + w] = C[pad:pad + h, pad:pad + w] * (1 - a[..., None]) + col * a[..., None]
    A = np.maximum(A, A_pic)
    body = A.copy()                                            # what casts the shadow (the rules are ink on the page)
    for q in rules:
        m, dw, dh = outline(w, h, shape, r, q["offset"], q["width"])
        ring = np.zeros((H2, W2), np.float32)
        y0, x0 = (H2 - dh) // 2, (W2 - dw) // 2
        ring[max(y0, 0):y0 + dh, max(x0, 0):x0 + dw] = m[max(-y0, 0):H2 - y0, max(-x0, 0):W2 - x0]
        ring *= q.get("alpha", 0.85)
        C = C * (1 - ring[..., None]) + rgb(q.get("color", "#3a3027")) * ring[..., None]
        A = np.maximum(A, ring)
    if pic.get("rotate"):
        A, C = turn(A, C, pic["rotate"])
        body, _ = turn(body, np.zeros((*body.shape, 3), np.float32), pic["rotate"])
    left, top = int(round(pic["x"] * x.shape[1] - A.shape[1] / 2)), int(round(pic["y"] * x.shape[0] - A.shape[0] / 2))
    sh = pic.get("shadow", {"alpha": 0.35, "blur": 26, "off": [10, 18]})
    if sh:
        m = int(sh.get("blur", 26) * 3)
        s = cv2.GaussianBlur(np.pad(body, m), (0, 0), sh.get("blur", 26))
        dx, dy = sh.get("off", [10, 18])
        comp(x, s, rgb(sh.get("color", "#2a2016")), sh.get("alpha", 0.35), (top - m + int(dy), left - m + int(dx)))
    comp(x, A, C, 1.0, (top, left))


def draw_wash(x, s):
    """A watercolor wash: a soft blob of paint behind words, with an uneven edge, the pigment pooled darker along its rim,
    an uneven density and the paper's grain. {x, y (its middle, fractions), w, h (px), color, alpha, rim (how much darker
    the rim is, 0..1), rough (px: how far the edge wanders), round (0..1 of the short side), rotate (degrees), seed}."""
    w, h = int(s["w"]), int(s["h"])
    seed = s.get("seed", 21)
    rough = s.get("rough", 0.06 * min(w, h))
    pad = int(rough * 2.5) + 8
    base = np.zeros((h + 2 * pad, w + 2 * pad), np.float32)
    base[pad:pad + h, pad:pad + w] = rrect(w, h, s.get("round", 0.5) * min(w, h))
    a = deckle(base, rough, seed, scale=9.0)
    a = blur(a, 1.2)
    rim = np.clip(a - cv2.erode(a, np.ones((int(rough * 0.5) * 2 + 3,) * 2, np.uint8)), 0, 1)
    rim = blur(rim, max(rough * 0.25, 1.0))
    hh, ww = a.shape
    col = np.broadcast_to(rgb(s.get("color", "#d9e0c8")), (hh, ww, 3)).copy()
    col *= (1 + 0.05 * noise_field(hh, ww, 140, seed + 2))[..., None]
    col *= (1 + s.get("grain", 0.03) * noise_field(hh, ww, 1.6, seed + 3))[..., None]
    col *= (1 - s.get("rim", 0.18) * np.clip(rim * 2.2, 0, 1))[..., None]
    a = a * s.get("alpha", 0.92) * (0.94 + 0.06 * noise_field(hh, ww, 90, seed + 4))
    col = np.clip(col, 0, 1)
    if s.get("rotate"):
        a, col = turn(a, col, s["rotate"])
    left, top = int(round(s["x"] * x.shape[1] - a.shape[1] / 2)), int(round(s["y"] * x.shape[0] - a.shape[0] / 2))
    comp(x, np.clip(a, 0, 1), col, 1.0, (top, left))


def draw_stroke(x, s):
    """A hand-drawn ink line through points (fractions of the picture): a smooth curve with a slight wobble, thinner at
    its ends, with an arrowhead at the last point when "arrow" (px) is set. {points, width (px), color, alpha, wobble
    (px), seed}."""
    hh, ww = x.shape[:2]
    p = np.array([[q[0] * ww, q[1] * hh] for q in s["points"]], np.float32)
    if len(p) == 2:
        p = np.stack([p[0], (2 * p[0] + p[1]) / 3, (p[0] + 2 * p[1]) / 3, p[1]])
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    pts = []
    for i in range(1, len(ext) - 2):                           # Catmull-Rom through every point
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        n = max(int(np.linalg.norm(p2 - p1) / 3), 2)
        for t in np.linspace(0, 1, n, endpoint=False):
            t2, t3 = t * t, t * t * t
            pts.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    pts.append(p[-1])
    c = np.array(pts, np.float32)
    tan = np.gradient(c, axis=0)
    tan /= np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-6)
    nrm = np.stack([-tan[:, 1], tan[:, 0]], 1)
    rng = np.random.default_rng(s.get("seed", 5))
    k = np.interp(np.linspace(0, 1, len(c)), np.linspace(0, 1, 7), rng.standard_normal(7))
    c = c + nrm * (k * s.get("wobble", 2.5))[:, None]
    t = np.linspace(0, 1, len(c))
    wid = s.get("width", 6) * (0.45 + 0.55 * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.35)
    m = np.zeros((hh, ww), np.uint8)
    for i in range(len(c) - 1):
        cv2.line(m, tuple(int(round(v)) for v in c[i]), tuple(int(round(v)) for v in c[i + 1]), 255,
                 max(1, int(round(wid[i]))), cv2.LINE_AA)
    if s.get("arrow"):
        d = c[-1] - c[max(len(c) - 8, 0)]
        d /= max(float(np.linalg.norm(d)), 1e-6)
        for ang in (26, -26):
            r = np.deg2rad(180 + ang)
            v = np.array([d[0] * np.cos(r) - d[1] * np.sin(r), d[0] * np.sin(r) + d[1] * np.cos(r)])
            q = c[-1] + v * s["arrow"]
            cv2.line(m, tuple(int(round(z)) for z in c[-1]), tuple(int(round(z)) for z in q), 255,
                     max(1, int(round(s.get("width", 6) * 0.9))), cv2.LINE_AA)
    comp(x, m.astype(np.float32) / 255, rgb(s.get("color", "#3a3027")), s.get("alpha", 0.9))


def preview(items, path):
    """The variants as YouTube shows them: desktop grid, phone feed and the sidebar."""
    sizes = [(560, 315, "desktop home"), (360, 202, "phone feed"), (168, 94, "sidebar")]
    gap, pad = 28, 30
    width = pad * 2 + sum(s[0] for s in sizes) + gap * (len(sizes) - 1)
    row_h = sizes[0][1] + 70
    sheet = Image.new("RGB", (width, pad + row_h * len(items) + 10), (15, 15, 15))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(items):
        y = pad + i * row_h
        x = pad
        for w, h, label in sizes:
            t = im.resize((w, h), Image.LANCZOS)
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=max(6, w // 40), fill=255)
            sheet.paste(t, (x, y), mask)
            badge(d, x, y, w, h)
            d.text((x, y + h + 8), f"{name} - {label} {w}x{h}", font=font(15), fill=(170, 170, 170))
            x += w + gap
    sheet.save(path)


def badge(d, x, y, w, h):
    fs = max(9, h // 14)
    tf = font(fs)
    label_w = d.textlength("10:00:00", font=tf)
    bx1, by1 = x + w - 6, y + h - 6
    d.rounded_rectangle((bx1 - label_w - 8, by1 - fs - 6, bx1, by1), radius=4, fill=(0, 0, 0))
    d.text((bx1 - label_w - 4, by1 - fs - 4), "10:00:00", font=tf, fill=(255, 255, 255))


def feed(items, ref, out):
    """Each variant in a row of real competitor thumbnails at phone-feed size, to judge if it stands out.

    ref: JSON list [{"id": <YouTube video id>, "title": ..., "views": ...}]. Their thumbnails are downloaded
    once into out/_feed_cache/ (gitignored) and only ever used for this comparison sheet."""
    import requests
    cache = out / "_feed_cache"
    cache.mkdir(exist_ok=True)

    def comp(e):
        p = cache / f"{e['id']}.jpg"
        if not p.exists():
            for v in ("maxresdefault", "hq720", "hqdefault"):
                try:
                    r = requests.get(f"https://i.ytimg.com/vi/{e['id']}/{v}.jpg", timeout=30)
                except requests.exceptions.RequestException:
                    break
                if r.ok and len(r.content) > 5000:
                    p.write_bytes(r.content)
                    break
        if not p.exists():                     # no network, or the video is gone: a grey tile keeps the sheet's layout
            print(f"feed: no thumbnail for {e['id']}; a grey tile stands in", flush=True)
            return Image.new("RGB", (1280, 720), (60, 60, 60))
        im = Image.open(p).convert("RGB")
        w, h = im.size
        th = round(w * 9 / 16)
        return im.crop((0, (h - th) // 2, w, (h - th) // 2 + th)) if h > th else im

    tw, th, gap, cols = 360, 202, 16, 4
    row_h = th + 62
    sheet = Image.new("RGB", (gap + cols * (tw + gap), gap + len(items) * row_h), (15, 15, 15))
    d = ImageDraw.Draw(sheet)
    k = 0
    for r, (name, im) in enumerate(items):
        pos = (r * 3 + 1) % cols
        for c in range(cols):
            x, y = gap + c * (tw + gap), gap + r * row_h
            if c == pos:
                t, title, meta, col = im, f"[ours: {name}]", "", (255, 214, 120)
            else:
                e = ref[k % len(ref)]
                k += 1
                t, title, meta, col = comp(e), e.get("title", ""), e.get("views", ""), (241, 241, 241)
            t = t.resize((tw, th), Image.LANCZOS)
            mask = Image.new("L", (tw, th), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=10, fill=255)
            sheet.paste(t, (x, y), mask)
            badge(d, x, y, tw, th)
            d.text((x, y + th + 8), title[:50] + ("..." if len(title) > 50 else ""), font=font(14), fill=col)
            d.text((x, y + th + 28), meta, font=font(12), fill=(170, 170, 170))
    sheet.save(out / "_feed_compare.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--only", help="comma-separated variant names")
    ap.add_argument("--refresh", action="store_true", help="re-render the cached frames")
    ap.add_argument("--feed", help="competitor list JSON (docs/reference/thumbnail-feed-*.json): also write "
                                   "_feed_compare.png, each variant among real thumbnails of the niche")
    a = ap.parse_args()
    spec = json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8-sig"))
    out = ROOT / spec.get("out", f"out/{pathlib.Path(spec['scene']).name}/thumbnails")
    out.mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    for v in spec["variants"]:
        if only and v["name"] not in only:
            continue
        src = frame_image(spec, v, a.refresh)
        g = {**GRADE, **v.get("grade", {})}
        mat = v.get("mat")
        if v.get("page"):                                             # a sheet of paper; "pictures" lay the frame on it
            x = paper(H, W, v["page"])
            main_xf = (0.0, 0.0, 1.0, 0, 0)
        elif mat:                                                     # a photo on a paper mat (polaroid)
            ml, mt, mr, mb = mat["margin"]
            ix0, iy0 = snap(ml * W), snap(mt * H)
            iw, ih = snap(W * (1 - ml - mr)), snap(H * (1 - mt - mb))
            inner, xf = region(src, v.get("zoom", 1.0), v.get("center", [0.5, 0.5]), iw, ih)
            x = np.empty((H, W, 3), np.float32)
            x[:] = rgb(mat.get("color", "#efe5d2"))
            x[iy0:iy0 + ih, ix0:ix0 + iw] = grade(inner, g)
            edge = np.zeros((ih, iw), np.float32)
            e = mat.get("edge_px", 9)
            edge[:e], edge[-e:], edge[:, :e], edge[:, -e:] = 1, 1, 1, 1
            comp(x, edge, rgb("#000000"), mat.get("edge", 0.3), (iy0, ix0))
            main_xf = (*xf, ix0, iy0)
        else:
            img, xf = region(src, v.get("zoom", 1.0), v.get("center", [0.5, 0.5]), W, H)
            x = grade(img, g)
            main_xf = (*xf, 0, 0)
        for s in v.get("washes", []):
            if s.get("under"):                                        # paint on the page, under the pictures
                draw_wash(x, s)
        for pic in v.get("pictures", []):
            draw_picture(x, src, pic, g)
        apply_bands(x, v.get("bands", []))
        apply_scrims(x, v.get("scrims", []))
        for s in v.get("washes", []):
            if not s.get("under"):
                draw_wash(x, s)
        for p in v.get("panels", []):
            draw_panel(x, p)
        for ins in v.get("insets", []):
            draw_inset(x, spec, v, ins, a.refresh, main_xf)
        for c in v.get("cards", []):
            draw_card(x, c)
        for s in v.get("strokes", []):
            draw_stroke(x, s)
        items = list(v.get("text", []))
        for row in v.get("badges", spec.get("badges", [])) + v.get("chips", []):
            items += expand_chips_ttf(row) if row.get("font") else expand_chips(row)
        for item in items:
            if item.get("font") not in (None, "pixel"):
                place_ttf(x, item)
            else:
                place_text(x, item)
        img8 = sharpen((x * 255 + 0.5).astype(np.uint8), g["sharpen"])
        im = Image.fromarray(img8)
        p4k, p720 = out / f"{v['name']}.jpg", out / f"{v['name']}_1280.jpg"
        im.save(p4k, quality=93, subsampling=0, optimize=True)
        small = Image.fromarray(cv2.resize(img8, (1280, 720), interpolation=cv2.INTER_AREA))
        for q in (92, 88, 82, 75):
            small.save(p720, quality=q, subsampling=0, optimize=True)
            if p720.stat().st_size < 1_950_000:
                break
        print(f"{v['name']}: {p4k} ({p4k.stat().st_size / 1e6:.1f} MB), {p720.name} ({p720.stat().st_size / 1e3:.0f} kB)")
    # The preview always shows every variant made so far (also after --only), in spec order.
    shown = [(v["name"], Image.open(out / f"{v['name']}_1280.jpg").convert("RGB")) for v in spec["variants"]
             if (out / f"{v['name']}_1280.jpg").exists()]
    if shown:
        preview(shown, out / "preview.png")
        print(f"preview: {out / 'preview.png'}")
        if a.feed:
            feed(shown, json.loads(pathlib.Path(a.feed).read_text(encoding="utf-8-sig")), out)
            print(f"feed: {out / '_feed_compare.png'}")


if __name__ == "__main__":
    main()
