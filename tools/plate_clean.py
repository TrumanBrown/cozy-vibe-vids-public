"""Remove painted transients from a scene's key art before it is animated.

Things that move in reality but are painted into the key art (steam plumes, flames, water drops hanging
from an awning, thin streams of drip water) look frozen under the animation, and an animated version on
top of a painted one looks doubled. Each item is repainted by the image model (Azure gpt-image edit) on a
crop around it, with a mask, and only the masked area is blended back (feathered, color-fitted to the
untouched surroundings), so the rest of the key art stays pixel-exact. The animation then adds the moving
version (steam.js, fire.js, beads in drips.js).

Usage (repo root):
  .venv/Scripts/python tools/plate_clean.py <scene> [--only name] [--dry] [--force]

Reads assets/keyart/<scene>.clean.json (tools/analyze_plate.py writes it; edit freely):
  {"source": "assets/keyart/<scene>/hero_....png",
   "items": [{"name": "steam_plume", "kind": "steam" | "fire" | "candle" | "drips" | "other",
              "box": [x0, y0, x1, y1] | "poly": [[x, y], ...]   (0..1 of the image, y down),
              "shape": "ellipse" | "rect" (box only, default ellipse),
              "what": "what to remove", "behind": "what shows instead", "protect": [region names]}]}
  kind "drips": no box needed. The mask is a band under every cover edge that hangs over the opening (the
  top edge of the plate's outdoor region: awning hems, eaves, lantern bottoms) plus thin bright strands
  hanging from it. Needs a plate_prep run of the source first (out/plates/<scene>/lights.png). With
  "under": [region names] the band follows those regions' lower edges instead (a hanging curtain or sign).
  kind "strands": painted drops and strings of drops hanging anywhere else (eaves across the street, signs,
  wires). Without "boxes" the vision model scans the key art in zoomed tiles and the boxes it finds are
  written back here (edit freely); the mask is the thin lines and beads inside each box. Each strand's top
  becomes a live drip source (clean.json "drips": [x, y, length], 0..1; tools/new_video.py clean adds them
  to the scene as a drips layer), so the water keeps dripping where it was painted.
  "protect": regions (assets/keyart/<scene>.masks.json) cut out of the mask, e.g. the bowl under the steam.

Writes assets/keyart/<scene>/clean.png (committed: it is the source of the plate from now on) with
clean.json (provenance: model, prompts, masks, usage) and out/plates/<scene>/clean_preview.jpg (before /
after of every item). tools/new_video.py prep and analyze use clean.png when it exists.
"""
import argparse
import base64
import datetime as dt
import io
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT, config, load_json

EDIT_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]
KEEP = ("Keep everything else exactly as it is: the same painting style, lighting, colors, perspective and level of detail. "
        "Do not add any new objects.")
PROMPTS = {
    "steam": ("Remove the {what}. Where it was, show what is behind it, continuing the surroundings naturally: {behind}. "
              "No steam, smoke, vapour or mist there. " + KEEP),
    "fire": ("Remove the flames of the {what}. Show the fuel without flames: {behind}, as dark logs with a few glowing orange "
             "embers, lit warmly from within, with the same warm light on the surroundings. No flames, no smoke, no grey haze "
             "or ash cloud, nothing white. Any pot, kettle or creature stays exactly as it is. " + KEEP),
    "candle": ("Remove the flame of the {what}: leave the candle with its wick, unlit tip only. " + KEEP),
    "drips": ("Remove every water drop and drip hanging from the edge of the {what}, and the thin streams of water running down "
              "from them. The edge itself stays, wet but with no hanging drops. Behind them show the scene as it continues: {behind}. " + KEEP),
    "strands": ("Remove the thin strings of water drops hanging from the {what}. Where they were, show what is behind them, "
                "continuing the surroundings: {behind}. The edges they hung from stay, wet but with no hanging drops. " + KEEP),
    "other": ("Remove the {what}. Where it was, show what is behind it: {behind}. " + KEEP),
}
SCAN_PROMPT = """This is one zoomed tile of a painting that will be animated (rain, water and light move in code).
Find every PAINTED WATER DRIP in it that would look frozen in the animation: drops HANGING IN THE AIR from an
overhanging edge (a roof eave, awning, gutter, sign, lantern, wire, branch, leaf or cloth), strings of drops, and
thin streams of water falling through the air from such an edge. Not drips: rain streaks in the air, water
sitting on a surface (beads on wood, stone or leaves), lit corners and edges of steps, stones, posts or planters,
reflections, wet shine, window light, poles, wires, ropes, chains and other solid lines.
Return JSON {"drips": [{"box": [x0, y0, x1, y1], "top": [x, y], "on": "what it hangs from", "sure": true}]} with
coordinates 0..1 of THIS tile (y down). The box tightly encloses the drop or the whole string of drops, from the
edge it hangs on to its lowest drop; "top" is the point where the water hangs from the edge; "sure" is false if
it might be something else. {"drips": []} if there are none."""


def poly_mask(size, polys):
    W, H = size
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for poly in polys:
        if len(poly) >= 3:
            d.polygon([(x * W, y * H) for x, y in poly], fill=255)
    return np.asarray(m, np.float32) / 255


def region_polys(masks, names):
    out = []
    for g in masks.get("regions", []):
        if g.get("name") in names:
            out += g.get("polys") or []
            if g.get("box") and not g.get("polys"):
                x0, y0, x1, y1 = g["box"]
                out.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    return out


def item_mask(it, size, masks):
    W, H = size
    if it.get("poly"):
        m = poly_mask(size, [it["poly"]])
    else:
        x0, y0, x1, y1 = it["box"]
        im = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(im)
        (d.rectangle if it.get("shape") == "rect" else d.ellipse)([x0 * W, y0 * H, x1 * W, y1 * H], fill=255)
        m = np.asarray(im, np.float32) / 255
    protect = list(it.get("protect") or [])
    if it.get("kind") in ("fire", "steam"):
        # a pot over the fire, the vessel under its painted steam, a character or a lantern beside them is never
        # repainted with them: the Burdock Shelter's flames came out with the pot's bottom see-through and the "plume"
        # (there was none) with its handle redrawn (2026-10-25)
        protect += [g["name"] for g in masks.get("regions", []) if g.get("kind") in ("steam", "pet", "lantern", "candle") and g.get("name") not in protect]
    if protect:
        p = poly_mask(size, region_polys(masks, protect))
        k = max(3, int(round(6 * W / 2560))) | 1
        p = cv2.dilate(p, np.ones((k, k), np.uint8))
        m = m * (1 - p)
    return m


def has_haze(arr, m):
    """Whether the masked area holds painted steam or smoke to remove: light, low-color haze over at least 6% of it,
    lighter than the ring around it. The analysis can list a plume that isn't painted (the Burdock Shelter's pot)."""
    sel = m > 0.5
    if sel.sum() < 200:
        return False
    lab = cv2.cvtColor(arr.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)
    L, C = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
    ring = (cv2.dilate(sel.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0) & ~sel
    light = sel & (L > float(np.median(L[ring])) + 8) & (C < 25)
    return light.sum() / sel.sum() > 0.06


def edge_line(outdoor, top_frac=0.6):
    """Per column: the first outdoor row under something solid (a cover edge), or -1."""
    H, W = outdoor.shape
    lim = int(H * top_frac)
    o = outdoor[:lim] > 0.5
    first = np.where(o.any(0), o.argmax(0), -1)
    first[first == 0] = -1          # open to the frame top: no edge there
    return first


def drips_mask(scene, size, band_frac=0.03, under=None, masks=None):
    """Band under the cover edges over the opening + thin bright strands hanging from it (key-art px).
    With `under` (region names): the band under those regions' lower edges instead (hanging cloth, signs)."""
    W, H = size
    if under:
        reg = poly_mask(size, region_polys(masks or {}, under)) > 0.5
        y0 = np.full(W, -1, np.int64)
        cols = np.flatnonzero(reg.any(0))
        y0[cols] = H - 1 - np.argmax(reg[::-1, cols], 0) + 1
    else:
        lp = ROOT / "out" / "plates" / scene / "lights.png"
        if not lp.exists():
            sys.exit(f"drips: run plate_prep on the source first ({lp} missing)")
        outdoor = np.asarray(Image.open(lp).convert("RGB").resize((W, H), Image.BILINEAR), np.float32)[..., 1] / 255
        y0 = edge_line(outdoor)
    band = np.zeros((H, W), np.float32)
    up, dn = int(0.006 * H), int(band_frac * H)
    for x in np.flatnonzero((y0 > 0) & (y0 < H - 1)):
        band[max(0, y0[x] - up): min(H, y0[x] + dn), x] = 1
    # ignore isolated columns (noise) and smooth the band edge
    band = cv2.morphologyEx(band, cv2.MORPH_OPEN, np.ones((1, 9), np.uint8))
    return band, y0


def strands_mask(img, band, y0, strand_frac=0.16):
    """Thin bright near-vertical lines that hang from the band (painted drip streams)."""
    a = np.asarray(img, np.float32) / 255
    H, W = band.shape
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    k = max(5, int(9 * W / 2560)) | 1
    th = lum - cv2.morphologyEx(lum, cv2.MORPH_OPEN, np.ones((1, k), np.uint8))   # thinner than k px across
    vert = cv2.morphologyEx((th > 0.035).astype(np.uint8), cv2.MORPH_OPEN, np.ones((int(0.012 * H) | 1, 1), np.uint8))
    lim = np.zeros((H, W), np.uint8)
    for x in np.flatnonzero(y0 > 0):
        lim[y0[x]: min(H, y0[x] + int(strand_frac * H)), max(0, x - 2): x + 3] = 1
    vert = vert & lim
    n, lab, st, _ = cv2.connectedComponentsWithStats(vert, 8)
    keep = np.zeros((H, W), np.float32)
    bandd = cv2.dilate(band, np.ones((int(0.01 * H) | 1, 3), np.uint8)) > 0
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if h < 3 * w or h < 0.012 * H:
            continue
        comp = lab == i
        if (comp & bandd).any():
            keep[comp] = 1
    return cv2.dilate(keep, np.ones((5, 5), np.uint8))


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def scan_strands(img, purpose, grids=((3, 2, 1.5), (4, 3, 2.0)), overlap=0.12, save=None):
    """Painted drips anywhere in the key art. A whole-image view is too coarse for a 3 px string of drops, so
    the vision model looks at overlapping zoomed tiles, in two tilings (its recall varies per view: the union
    finds more), then confirms each candidate on a contact sheet of close-ups (verify_strands).
    Returns [{"box", "top", "on"}] in 0..1 of the image."""
    from azure_ai import vision_json
    W, H = img.size
    found = []
    for cols, rows, zoom in grids:
        tw, th = W / (cols - (cols - 1) * overlap), H / (rows - (rows - 1) * overlap)
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * tw * (1 - overlap), r * th * (1 - overlap)
                box = (int(x0), int(y0), int(min(W, x0 + tw)), int(min(H, y0 + th)))
                bw, bh = box[2] - box[0], box[3] - box[1]
                tile = img.crop(box).resize((round(bw * zoom), round(bh * zoom)), Image.LANCZOS)
                res, _ = vision_json(SCAN_PROMPT, [tile], purpose=purpose, max_side=2048)
                for d in res.get("drips") or []:
                    b = d.get("box")
                    if not b or len(b) != 4 or d.get("sure") is False:
                        continue
                    t = d.get("top") if d.get("top") and len(d["top"]) == 2 else [(b[0] + b[2]) / 2, b[1]]
                    found.append({"box": [round((box[0] + b[0] * bw) / W, 4), round((box[1] + b[1] * bh) / H, 4),
                                          round((box[0] + b[2] * bw) / W, 4), round((box[1] + b[3] * bh) / H, 4)],
                                  "top": [round((box[0] + t[0] * bw) / W, 4), round((box[1] + t[1] * bh) / H, 4)], "on": d.get("on", "")})
    out = []
    for f in found:      # overlapping tiles and the two tilings see the same drip more than once
        if not any(_iou(f["box"], g["box"]) > 0.2 or (abs(f["top"][0] - g["top"][0]) < 0.004 and abs(f["top"][1] - g["top"][1]) < 0.01)
                   for g in out):
            out.append(f)
    return verify_strands(img, out, purpose, save=save)


def verify_strands(img, found, purpose, cell=320, save=None):
    """Second look at each candidate: a numbered close-up with its box drawn in, all on one sheet, and the
    model says which are really drops hanging in the air (lit step corners and wet surfaces get reported too)."""
    from azure_ai import vision_json
    from PIL import ImageFont
    if not found:
        return []
    W, H = img.size
    cols = min(6, len(found))
    sheet = Image.new("RGB", (cols * cell, -(-len(found) // cols) * cell), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    for i, f in enumerate(found):
        x0, y0, x1, y1 = f["box"]
        cx, cy = 0.5 * (x0 + x1) * W, 0.5 * (y0 + y1) * H
        s = max((x1 - x0) * W, (y1 - y0) * H, 0.035 * W) * 1.8
        crop = img.crop((int(cx - s / 2), int(cy - s / 2), int(cx + s / 2), int(cy + s / 2))).resize((cell - 4, cell - 4), Image.LANCZOS)
        cd = ImageDraw.Draw(crop)
        k = (cell - 4) / s
        cd.rectangle([(x0 * W - cx + s / 2) * k - 3, (y0 * H - cy + s / 2) * k - 3, (x1 * W - cx + s / 2) * k + 3, (y1 * H - cy + s / 2) * k + 3],
                     outline=(0, 255, 0), width=2)
        px, py = (i % cols) * cell, (i // cols) * cell
        sheet.paste(crop, (px + 2, py + 2))
        d.text((px + 8, py + 6), str(i), fill=(255, 255, 0), font=font)
    res, _ = vision_json(
        "Each numbered cell is a close-up of a painting with a green box. Is the thing inside the green box a painted water drop, "
        "string of drops or thin stream of water HANGING IN THE AIR from an edge above it (eave, awning, sign, lantern, wire, leaf, "
        "cloth)? Answer no for a lit corner or edge of a step, stone, post or planter, water lying on a surface, a reflection, "
        'a pole, wire or any other solid line. JSON {"yes": [numbers], "no": [numbers]}.', [sheet], purpose=purpose + ":verify", max_side=2048)
    yes = {int(v) for v in res.get("yes") or [] if str(v).lstrip("-").isdigit()}
    if save:
        pathlib.Path(save).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(save, quality=88)
        print(f"  drip candidates: {len(found)}, confirmed {sorted(yes)} ({save})")
    return [f for i, f in enumerate(found) if i in yes]


def strand_mask(arr, box, W, H, reach=0.06, gap=0.012):
    """The painted drip in a box, traced down its strand: thin bright lines (narrower than ~9 px at 2560 wide)
    and small bright beads in a narrow column from the box top (so the drop is cut off the lit edge it hangs
    from) down, kept when near-vertical or bead-sized and not running out of the column sideways (wires,
    posts, edges), chained downward past the box while the gaps stay under `gap` (0..1 of H), at most `reach`
    below it. Returns (mask, top (x, y) px, length px), or (None, None, 0) if nothing is drip-like."""
    x0, y0, x1, y1 = box
    s = W / 2560
    k = max(5, int(9 * s)) | 1
    xc, hw = 0.5 * (x0 + x1) * W, max(4 * s, 0.5 * (x1 - x0) * W + 2 * s)
    X0, X1 = int(max(0, xc - hw - k)), int(min(W, xc + hw + k))
    Y0, Y1 = int(max(0, y0 * H + 1)), int(min(H, y1 * H + reach * H))
    if X1 - X0 < 4 or Y1 - Y0 < 4:
        return None, None, 0
    lum = arr[Y0:Y1, X0:X1].astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32) / 255
    thb = lum - cv2.morphologyEx(lum, cv2.MORPH_OPEN, np.ones((1, k), np.uint8))
    bead = lum - cv2.morphologyEx(lum, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    raw = ((thb > 0.04) | (bead > 0.06)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(raw, 8)
    w = raw.shape[1]
    comps = []
    for i in range(1, n):
        x, y, cw, ch, area = st[i]
        if area < 3 or x == 0 or x + cw >= w:
            continue
        if ch >= 1.5 * cw or (cw <= k + 2 and ch <= 2.5 * k):
            comps.append((y, y + ch, i))
    in_box = int(y1 * H) - Y0
    chain = [c for c in comps if c[0] <= in_box]
    if not chain:
        return None, None, 0
    # below the box only bead-sized pieces right under the strand continue it (the dots of a falling string;
    # long lines there are window bars or lit seams)
    cxs = np.array([st[c[2]][0] + 0.5 * st[c[2]][2] for c in chain], np.float32)
    sx = float(np.average(cxs, weights=[st[c[2]][4] for c in chain]))
    bottom = max(c[1] for c in chain)
    for c in sorted(comps):
        if c[0] <= in_box:
            continue
        if c[0] - bottom > gap * H:
            break
        x, _, cw, ch, _ = st[c[2]]
        if cw > k + 2 or ch > 2.5 * k or abs(x + 0.5 * cw - sx) > 4 * s:
            continue
        chain.append(c)
        bottom = max(bottom, c[1])
    keep = np.isin(lab, [c[2] for c in chain]).astype(np.uint8)
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    full = np.zeros((H, W), np.float32)
    full[Y0:Y1, X0:X1] = keep
    ys, xs = np.nonzero(keep)
    top = (float(xs[ys <= ys.min() + 2].mean() + X0), float(ys.min() + Y0 + 2))
    return full, top, float(ys.max() - ys.min())


def tiles_for(mask, size, margin=0.06):
    """Edit windows (x, y, w, h) covering the mask's bounding box: one if it fits, else a row of overlapping
    1536x1024 windows centered on the mask's rows (or 1024x1536 columns for tall masks)."""
    W, H = size
    ys, xs = np.nonzero(mask > 0.02)
    if not len(xs):
        return []
    mx, my = int(margin * W), int(margin * H)
    x0, x1, y0, y1 = int(max(0, xs.min() - mx)), int(min(W, xs.max() + mx)), int(max(0, ys.min() - my)), int(min(H, ys.max() + my))
    bw, bh = x1 - x0, y1 - y0
    for tw, th in EDIT_SIZES:
        if bw <= tw and bh <= th and tw <= W and th <= H:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            return [(min(max(0, cx - tw // 2), W - tw), min(max(0, cy - th // 2), H - th), tw, th)]
    tw, th = (1536, 1024) if bw >= bh else (1024, 1536)
    out = []
    if bw >= bh:
        n = int(np.ceil((bw - 160) / (tw - 160)))
        cy = (y0 + y1) // 2
        for i in range(n):
            tx = min(x0 + i * (tw - 160), W - tw) if n > 1 else (x0 + x1) // 2 - tw // 2
            out.append((max(0, min(tx, W - tw)), min(max(0, cy - th // 2), H - th), tw, th))
    else:
        n = int(np.ceil((bh - 160) / (th - 160)))
        cx = (x0 + x1) // 2
        for i in range(n):
            ty = min(y0 + i * (th - 160), H - th)
            out.append((min(max(0, cx - tw // 2), W - tw), max(0, ty), tw, th))
    return out


MODEL = None   # the look's own image model (config/aesthetics.json keyart_model), set in main; None: the default


def look_model(scene):
    """A look painted in a hand-made medium repaints with the model that follows it (gpt-image-2, 2026-10-25): the
    default model would patch its own house style into the picture."""
    bp = ROOT / "scenes" / scene / "brief.json"
    if not bp.exists():
        return None
    look = json.loads(bp.read_text(encoding="utf-8")).get("aesthetic")
    aes = config("aesthetics")["aesthetics"].get(look) or {}
    return aes.get("keyart_model")


def edit_tile(img, mask, tile, prompt, purpose):
    from azure_ai import edit_image
    x, y, w, h = tile
    crop = img.crop((x, y, x + w, y + h))
    m = mask[y: y + h, x: x + w]
    k = max(3, int(round(5 * img.width / 2560))) | 1
    hard = cv2.dilate((m > 0.02).astype(np.uint8), np.ones((k, k), np.uint8))
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 3] = np.where(hard > 0, 0, 255)       # transparent = repaint
    res = edit_image(crop, prompt, mask=Image.fromarray(rgba, "RGBA"), deployment=MODEL, size=f"{w}x{h}", quality="high", purpose=purpose)
    out = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGB")
    if out.size != (w, h):
        out = out.resize((w, h), Image.LANCZOS)
    return out, hard, res.get("usage") or {}


def blend(img, edited, hard, tile):
    """Paste the repainted area back: per-channel affine color fit on a ring just outside the mask (where
    the edit should equal the original), then a feathered blend inside the mask only."""
    x, y, w, h = tile
    a = np.asarray(img, np.float32)
    o = a[y: y + h, x: x + w]
    e = np.asarray(edited, np.float32)
    r = max(4, int(round(18 * img.width / 2560)))
    ring = (cv2.dilate(hard, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0) & (hard == 0)
    if ring.sum() > 200:
        for c in range(3):
            A = np.stack([e[..., c][ring], np.ones(int(ring.sum()), np.float32)], 1)
            g, b = np.linalg.lstsq(A, o[..., c][ring], rcond=None)[0]
            e[..., c] = e[..., c] * float(np.clip(g, 0.8, 1.25)) + float(np.clip(b, -25, 25))
    f = max(2, int(round(4 * img.width / 2560)))
    alpha = cv2.GaussianBlur(hard.astype(np.float32), (0, 0), f)
    alpha = np.clip(alpha * (cv2.dilate(hard, np.ones((2 * f + 1, 2 * f + 1), np.uint8)) > 0), 0, 1)[..., None]
    a[y: y + h, x: x + w] = e * alpha + o * (1 - alpha)
    return Image.fromarray(np.clip(a, 0, 255).round().astype(np.uint8))


def preview(before, after, boxes, out):
    tiles = []
    for (x, y, w, h) in boxes:
        s = 640 / max(w, h)
        b = before.crop((x, y, x + w, y + h)).resize((round(w * s), round(h * s)), Image.LANCZOS)
        c = after.crop((x, y, x + w, y + h)).resize((round(w * s), round(h * s)), Image.LANCZOS)
        t = Image.new("RGB", (b.width * 2 + 8, b.height), (30, 30, 30))
        t.paste(b, (0, 0))
        t.paste(c, (b.width + 8, 0))
        tiles.append(t)
    if not tiles:
        return
    W = max(t.width for t in tiles)
    sheet = Image.new("RGB", (W, sum(t.height + 8 for t in tiles)), (30, 30, 30))
    yy = 0
    for t in tiles:
        sheet.paste(t, (0, yy))
        yy += t.height + 8
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--only", action="append", help="item name (repeatable)")
    ap.add_argument("--dry", action="store_true", help="write the masks preview only (no API calls)")
    ap.add_argument("--force", action="store_true", help="start from the source even if clean.png exists")
    a = ap.parse_args()
    global MODEL
    MODEL = look_model(a.scene)
    spec = load_json(ROOT / "assets" / "keyart" / f"{a.scene}.clean.json")
    if not spec:
        sys.exit(f"no assets/keyart/{a.scene}.clean.json")
    masks = load_json(ROOT / "assets" / "keyart" / f"{a.scene}.masks.json", {})
    src = ROOT / spec["source"]
    dst = ROOT / "assets" / "keyart" / a.scene / "clean.png"
    meta_p = dst.with_suffix(".json")
    meta = load_json(meta_p, {}) if not a.force else {}
    base = Image.open(dst if dst.exists() and not a.force and a.only else src).convert("RGB")
    before = Image.open(src).convert("RGB")
    W, H = base.size
    done = {r["name"]: r for r in meta.get("items", [])}
    boxes = []
    dbg = np.zeros((H, W), np.float32)
    spec_dirty = False
    for it in spec["items"]:
        if a.only and it["name"] not in a.only:
            continue
        kind = it.get("kind", "other")
        drips = None
        if kind == "drips":
            band, y0 = drips_mask(a.scene, (W, H), it.get("band", 0.03), it.get("under"), masks)
            m = np.maximum(band, strands_mask(before, band, y0, it.get("strands", 0.16)))
            if it.get("box"):
                m = m * item_mask({**it, "shape": "rect"}, (W, H), masks)
        elif kind == "strands":
            if it.get("boxes") is None:
                if a.dry:
                    print(f"{it['name']} (strands): no boxes yet, the scan needs the vision model (skipped in --dry)")
                    continue
                found = scan_strands(base, f"clean-scan:{a.scene}", save=ROOT / "out" / "plates" / a.scene / "strands_verify.jpg")
                it["boxes"] = [f["box"] for f in found]
                it["found"] = found
                spec_dirty = True
                print(f"{it['name']}: the scan found {len(found)} painted drip(s): " + "; ".join(f["on"] for f in found))
            # the masks come from the source (on a re-run the base may already lack the drip's top)
            arr = np.asarray(before)
            m, drips = np.zeros((H, W), np.float32), []
            for b in it["boxes"]:
                sm, top, ln = strand_mask(arr, b, W, H)
                if sm is None:
                    print(f"  nothing drip-like in {b}")
                    continue
                m = np.maximum(m, sm)
                drips.append([round(top[0] / W, 4), round(top[1] / H, 4), round(ln / H, 4)])
            if it.get("protect"):
                m = m * item_mask({"box": [0, 0, 1, 1], "shape": "rect", "protect": it["protect"]}, (W, H), masks)
        else:
            m = item_mask(it, (W, H), masks)
            if kind == "steam" and not has_haze(np.asarray(before), m):
                print(f"{it['name']} (steam): no painted steam under its mask; left as it is")
                continue
        dbg = np.maximum(dbg, m)
        prompt = PROMPTS.get(kind, PROMPTS["other"]).format(what=it.get("what", it["name"]), behind=it.get("behind", "the surroundings"))
        tiles = tiles_for(m, (W, H))
        print(f"{it['name']} ({kind}): {int((m > 0.02).sum())} px, {len(tiles)} edit window(s)")
        boxes += tiles
        if a.dry:
            continue
        usage = []
        for tile in tiles:
            edited, hard, u = edit_tile(base, m, tile, prompt, f"clean:{a.scene}:{it['name']}")
            base = blend(base, edited, hard, tile)
            usage.append(u)
        done[it["name"]] = {"name": it["name"], "kind": kind, "prompt": prompt, "tiles": [[int(v) for v in t] for t in tiles], "usage": usage,
                            "date": dt.date.today().isoformat(), **({"drips": drips} if drips else {})}
    if spec_dirty:
        (ROOT / "assets" / "keyart" / f"{a.scene}.clean.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    ov = ROOT / "out" / "plates" / a.scene
    ov.mkdir(parents=True, exist_ok=True)
    if a.dry:
        vis = np.asarray(before, np.float32) * 0.6
        vis[..., 0] = np.maximum(vis[..., 0], dbg * 255)
        Image.fromarray(vis.astype(np.uint8)).save(ov / "clean_masks.jpg", quality=88)
        print(f"masks: {ov / 'clean_masks.jpg'}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    base.save(dst)
    from azure_ai import CFG
    meta = {"source": spec["source"], "deployment": MODEL or CFG["default_deployment"], "endpoint": CFG["endpoint"],
            "items": list(done.values()), "_note": "AI edit of the key art (painted transients removed); see tools/plate_clean.py"}
    meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    preview(before, base, boxes, ov / "clean_preview.jpg")
    print(f"wrote {dst.relative_to(ROOT)} and {ov / 'clean_preview.jpg'}")


if __name__ == "__main__":
    main()
