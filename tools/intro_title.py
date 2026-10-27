"""The intro title: a small line of text at the very start of a video, specific to it, in a font that fits the look
(user 2026-10-19: a short line made for each video, for the ramen alley 'welcome, have some ramen and relax', in a font
unique to each video that fits its look, the way the Minecraft-style video would use a pixel or blocky font).

  .venv\\Scripts\\python tools\\intro_title.py <scene> [--font <id>] [--pos x,y] [--size px]

Reads scenes/<scene>/scene.json `intro`:
  {"lines": ["main line", {"text": "smaller line above", "scale": 0.6}, ...] (top to bottom), "font": id (default: the
   look's title_font in config/aesthetics.json; ids in config/fonts.json), "size": px at 4K of a scale-1 line (72),
   "pos": [x, y] (block center, 0..1; default [0.5, 0.5], the middle of the screen) or "auto", "color": "#fff1df", "at": s after the video starts (1.0),
   "fade_in": 1.8, "hold": 6.5, "fade_out": 2.2,
   "panel": a comic caption box behind the lines (the comic look, 2026-10-25): true, or {"fill": "#fff3c4", "ink":
   "#221f1b", "outline": 0.08, "shadow": [0.13, 0.13], "pad": [0.55, 0.38], "radius": 0.1} (sizes as fractions of
   "size"); the text is drawn in the ink color, without glow or soft shadow}
Writes out/plates/<plate>/intro.png (the block, RGBA, 1:1 at 4K), intro.json (box at 4K, timing, lines, font) and
intro_preview.jpg (the plate with the title, the box outlined, and the block at 1:1) for the eye check;
src/library/title.js fades it in and out over the picture.

The text is checked first: Truman's voice rules (tools/cozy/voice.py voice_problems: no dashes, emoji,
exclamation marks or stock AI words), no AI words, no brand names in the picture (AGENTS.md), every character in the
font. Placement: the middle of the screen, each line centered (user 2026-10-21 on the pixel greenhouse: centered, not
at the bottom). "auto" still finds, of boxes in the
upper and lower bands of the plate, the calmest and darkest that covers no pet, food, lamp, lantern, neon, fire or
candle (the title must not sit on what moves or glows).
"""
import argparse
import hashlib
import http.client
import io
import json
import re
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from cozy.paths import ROOT, config
import pixelfont as pf  # noqa: E402
from cozy.voice import AI_WORDS, BRANDS, voice_problems  # noqa: E402

FONTS = ROOT / "cache" / "fonts"
AVOID = {"pet", "steam", "lamp", "lantern", "neon", "fire", "candle", "bob", "screen"}
DEFAULTS = {"size": 72, "pos": [0.5, 0.5], "color": "#fff1df", "at": 1.0, "fade_in": 1.8, "hold": 6.5, "fade_out": 2.2}
VERSION = 4   # bump when the drawing or placement changes, so every intro.png is drawn again (2: the pixel font's dark outline; 3: a set position slides clear of characters, L147; 4: no light glow around the text, L154)


def spec_key(sc, font=None, pos=None, size=None):
    """A key of everything intro.png is drawn from (the scene's intro with its defaults, the font, this code's
    VERSION, and for a pixel font on a scene drawn on its art's grid the grid: since 2026-10-21 it is drawn onto that
    grid). intro.json stores it, so a changed line, font, size, position or timing is noticed (stale())."""
    I = {**DEFAULTS, **(sc.get("intro") or {})}
    aes = config("aesthetics")["aesthetics"].get(sc.get("aesthetic"), {})
    I["font"] = font or I.get("font") or aes.get("title_font") or "pixel"
    if pos:
        I["pos"] = pos
    if size:
        I["size"] = size
    k = {"intro": I, "v": VERSION}
    # where the little life goes moves the title too (path_mask; clear_of and place)
    ev = sc.get("events") or {}
    k["life"] = [L for L in sc.get("layers", []) if L.get("type") in ("ant", "critter", "perch", "moth") and L.get("enabled") is not False] + [
        ((ev.get("boat") or {}).get("route") or {}).get("path"), (ev.get("birds") or {}).get("band"), ((ev.get("petals") or {}).get("tree") or {}).get("box")]
    grid = (sc.get("render") or {}).get("pixel")
    if grid and I["font"] == "pixel":
        k["grid"] = grid
    return hashlib.sha1(json.dumps(k, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def stale(scene):
    """Why the scene's intro.png must be drawn again (none yet, or the scene's intro or font changed since), or None
    (also None for a scene without an intro)."""
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    if not sc.get("intro"):
        return None
    ij = ROOT / "out" / "plates" / sc.get("plate", scene) / "intro.json"
    if not ij.exists() or not (ij.parent / "intro.png").exists():
        return "no intro.png yet"
    if json.loads(ij.read_text(encoding="utf-8")).get("key") != spec_key(sc):
        return "the scene's intro (lines, font, size, position or timing) changed since intro.png was drawn"
    return None


def font_file(fid):
    """The font's file in cache/fonts/ (fetched on first use), and its entry. The file must match the font's sha256 in
    config/fonts.json, so a first fetch on a new machine gets the font every video so far used, not whatever the URL
    serves that day; a font without one is pinned next to its file on first use."""
    cat = config("fonts")["fonts"]
    if fid not in cat:
        sys.exit(f"intro: unknown font {fid!r} (config/fonts.json has {', '.join(cat)})")
    f = cat[fid]
    if f.get("kind") == "pixel":
        return None, f
    FONTS.mkdir(parents=True, exist_ok=True)
    p = FONTS / f["file"]
    want = f.get("sha256")
    if not p.exists():
        print(f"intro: fetching {f['title']} ({f['url']})")
        lic_path = FONTS / (f["file"] + ".OFL.txt")
        try:
            font = urllib.request.urlopen(urllib.request.Request(f["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
            lic = urllib.request.urlopen(urllib.request.Request(f["license_url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        except (OSError, http.client.HTTPException) as e:     # nothing written yet, so the next run fetches both again
            sys.exit(f"intro: couldn't fetch {f['title']} ({getattr(e, 'reason', None) or e}): check the connection, or put the "
                     f"font at {p} and its license at {lic_path} by hand")
        if want and hashlib.sha256(font).hexdigest() != want:
            sys.exit(f"intro: {f['url']} isn't the {f['title']} vetted in config/fonts.json (its SHA-256 differs), so nothing "
                     "was saved. Look at the new file, then update its sha256 there if it's fine")
        lic_path.write_bytes(lic)
        p.write_bytes(font)                                    # last: the font's file is what marks the fetch done
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if want and h != want:
        sys.exit(f"intro: {p} isn't the {f['title']} vetted in config/fonts.json (its SHA-256 differs): delete it to fetch "
                 "it again")
    pin = FONTS / (f["file"] + ".sha256")
    if pin.exists() and pin.read_text().strip() != h:
        sys.exit(f"intro: {p.name} changed since it was first fetched (sha256 {h[:12]} vs {pin.read_text()[:12]})")
    pin.write_text(h)
    return p, f


LATIN = re.compile(r"[A-Za-z]")


def sentences(lines):
    """Two lines of one welcome as two sentences: each starts with a capital and ends with a period unless it already
    ends with . ! or ?, a comma left at a line's end goes (autopilot breaks one long line at its comma or sentence
    break; "Welcome to Seedling House / come listen to the morning rain" read as badly punctuated to Truman,
    2026-10-21)."""
    out = []
    for ln in lines:
        t = ln.strip().rstrip(",;:").rstrip()
        if t and LATIN.match(t[0]):
            t = t[0].upper() + t[1:]
        if t and LATIN.search(t) and t[-1] not in ".!?":
            t += "."
        out.append(t)
    return out


def punctuation_problems(lines):
    """Lines that disagree: with two or more lines in Latin letters, each one after the first starts with a capital
    unless the line before ends with a comma, and they all end with . ! or ? or none does. One line alone keeps his
    published lowercase style ("welcome in, have some ramen and relax")."""
    lat = [ln.strip() for ln in lines if LATIN.search(ln)]
    if len(lat) < 2:
        return []
    bad = []
    for prev, ln in zip(lat, lat[1:]):
        if LATIN.match(ln[0]) and ln[0].islower() and not prev.endswith(","):
            bad.append(f"{ln!r} starts lowercase after a line that ends without a comma (make each line a sentence)")
    ends = {ln[-1] in ".!?" for ln in lat if not ln.endswith(",")}
    if len(ends) > 1:
        bad.append("some lines end with a period and some don't")
    return bad


def check_text(lines):
    text = " ".join(lines)
    bad = voice_problems(text) + punctuation_problems(lines)
    if AI_WORDS.search(text):
        bad.append("mentions AI")
    if m := BRANDS.search(text):
        bad.append(f"a brand name in the picture ({m.group(0)!r})")
    if bad:
        sys.exit("intro: the text breaks the rules: " + "; ".join(bad))


def missing_glyphs(font, text):
    """Characters the font draws as its .notdef box."""
    ref = np.asarray(font.getmask("\uffff"))
    out = []
    for ch in set(text) - {" "}:
        m = np.asarray(font.getmask(ch))
        if m.shape == ref.shape and np.array_equal(m, ref):
            out.append(ch)
    return out


def block_ttf(lines, scales, path, entry, size, color, panel=None):
    """The block as RGBA: lines centred, a soft dark shadow below and around them (no light glow: L154; sizes follow the
    text); with `panel`, a comic caption box instead (block_panel)."""
    fonts = []
    for s in scales:
        f = ImageFont.truetype(str(path), max(8, int(round(size * s))))
        if entry.get("weight"):
            try:
                f.set_variation_by_axes([entry["weight"]])
            except Exception:
                pass
        fonts.append(f)
    for ln, f in zip(lines, fonts):
        miss = missing_glyphs(f, ln)
        if miss:
            sys.exit(f"intro: {entry['title']} has no glyph for {''.join(sorted(miss))!r}")
    track = [0.04 * size * s if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ln) else 0.0 for ln, s in zip(lines, scales)]
    widths = [sum(f.getlength(ch) for ch in ln) + t * max(len(ln) - 1, 0) for ln, f, t in zip(lines, fonts, track)]
    asc = [f.getmetrics()[0] for f in fonts]
    desc = [f.getmetrics()[1] for f in fonts]
    gap = 0.32 * size
    pad = int(0.75 * size)
    W = int(max(widths)) + 2 * pad
    H = int(sum(a + d for a, d in zip(asc, desc)) + gap * (len(lines) - 1)) + 2 * pad
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    y = pad
    for ln, f, w, t, a, ds in zip(lines, fonts, widths, track, asc, desc):
        x = (W - w) / 2
        for ch in ln:
            d.text((x, y), ch, font=f, fill=255)
            x += f.getlength(ch) + t
        y += a + ds + gap
    if panel:
        return block_panel(mask, size, panel)
    return effects(mask, size, color, soft=True), (int(max(widths)), H - 2 * pad)


PANEL = {"fill": "#fff3c4", "ink": "#221f1b", "outline": 0.08, "shadow": [0.13, 0.13], "pad": [0.55, 0.38], "radius": 0.1}


def block_panel(mask, size, panel):
    """A comic caption box (the comic look the user asked for, 2026-10-25): the lines in ink on a
    flat panel with an ink outline and a hard offset shadow, the panel's edges drawn at 4x and brought down so its
    corners are smooth. Returns (RGBA block, the panel's size): the panel is what must sit clear of the pet and lamps."""
    P = {**PANEL, **(panel if isinstance(panel, dict) else {})}
    rgb = lambda h: tuple(int(h.lstrip("#")[i: i + 2], 16) for i in (0, 2, 4))   # noqa: E731
    fill, ink = rgb(P["fill"]), rgb(P["ink"])
    bb = mask.getbbox()
    text = mask.crop(bb)
    ol = max(2, int(round(P["outline"] * size)))
    sx, sy = (int(round(v * size)) for v in P["shadow"])
    px, py = (int(round(v * size)) for v in P["pad"])
    pw, ph = text.width + 2 * (px + ol), text.height + 2 * (py + ol)
    m = 4
    W, H = pw + 2 * m + abs(sx), ph + 2 * m + abs(sy)
    ox, oy = m + max(0, -sx), m + max(0, -sy)
    k = 4
    r = int(round(P["radius"] * size * k))

    def rect(x, y, w, h, rad):
        big = Image.new("L", (W * k, H * k), 0)
        ImageDraw.Draw(big).rounded_rectangle([x * k, y * k, (x + w) * k - 1, (y + h) * k - 1], radius=max(0, rad), fill=255)
        return np.asarray(big.resize((W, H), Image.BOX), np.float32) / 255

    shadow = rect(ox + sx, oy + sy, pw, ph, r)
    outer = rect(ox, oy, pw, ph, r)
    inner = rect(ox + ol, oy + ol, pw - 2 * ol, ph - 2 * ol, max(0, r - ol * k))
    t = np.zeros((H, W), np.float32)
    t[oy + ol + py: oy + ol + py + text.height, ox + ol + px: ox + ol + px + text.width] = np.asarray(text, np.float32) / 255
    # over: the shadow (ink), the outline (ink), the panel (fill), the text (ink)
    a = np.maximum(shadow * 0.85, outer)
    col = np.zeros((H, W, 3), np.float32) + np.asarray(ink, np.float32)
    col = np.where(inner[..., None] > 0, np.asarray(fill, np.float32) * inner[..., None] + col * (1 - inner[..., None]), col)
    col = np.asarray(ink, np.float32) * t[..., None] + col * (1 - t[..., None])
    a = np.maximum(a, t)
    out = np.dstack([np.clip(col + 0.5, 0, 255), np.clip(a * 255 + 0.5, 0, 255)]).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), (pw, ph)


def block_pixel(lines, scales, size, color, cell=None):
    """The block in the channel's pixel font: whole pixels scaled up, a hard shadow one pixel down and right. With
    `cell` (a scene drawn on its art's pixel grid) the block is built in grid cells, one font pixel per cell or a whole
    number of them, and the caller maps the cells onto the grid: font pixels of 8 px on an 8.5 px grid lost a stroke
    every so often, the output pass sampling each cell's center ("the norning ran", the pixel greenhouse 2026-10-21)."""
    unit = cell or 1.0
    cells = []
    for ln, s in zip(lines, scales):
        bits = pf.render(ln, tracking=1)
        k = max(1, int(round(size * s / pf.ROWS / unit)))
        cells.append(np.kron(bits.astype(np.uint8), np.ones((k, k), np.uint8)) * 255)
    gap = max(1, int(round(0.4 * size / unit)))
    pad = max(1, int(round(0.5 * size / unit)))
    W = max(c.shape[1] for c in cells) + 2 * pad
    H = sum(c.shape[0] for c in cells) + gap * (len(cells) - 1) + 2 * pad
    mask = np.zeros((H, W), np.uint8)
    y = pad
    for c in cells:
        x = (W - c.shape[1]) // 2
        mask[y: y + c.shape[0], x: x + c.shape[1]] = c
        y += c.shape[0] + gap
    step = max(1, int(round(size / pf.ROWS / unit)))
    core = (W - 2 * pad, H - 2 * pad)
    return effects(Image.fromarray(mask), size / unit, color, soft=False, step=step), (int(round(core[0] * unit)), int(round(core[1] * unit)))


def to_grid(block, cx, cy, grid):
    """A block built in grid cells, mapped onto the art's grid around (cx, cy) px: each cell fills exactly the 4K pixels
    of its grid cell, so the output pass (each cell's center pixel) shows every font pixel. Returns (image, x0, y0)."""
    cell, (ox, oy) = float(grid["cell"]), grid["origin"]
    a = np.asarray(block)
    hc, wc = a.shape[:2]
    i0, j0 = int(round((cx - ox) / cell - wc / 2)), int(round((cy - oy) / cell - hc / 2))
    xs = np.round(ox + (i0 + np.arange(wc + 1)) * cell).astype(int)
    ys = np.round(oy + (j0 + np.arange(hc + 1)) * cell).astype(int)
    a = np.repeat(np.repeat(a, np.diff(ys), axis=0), np.diff(xs), axis=1)
    return Image.fromarray(a, "RGBA"), int(xs[0]), int(ys[0])


def scene_grid(sc, pd):
    """The pixel-art grid {cell, origin} (px at 4K) the scene is rendered on (scene.json render.pixel), else None."""
    px = (sc.get("render") or {}).get("pixel")
    if not px:
        return None
    if isinstance(px, dict) and px.get("cell"):
        return {"cell": float(px["cell"]), "origin": px.get("origin") or [0, 0]}
    pj = pd / "plate.json"
    g = (json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}).get("pixel")
    return {"cell": float(g["cell"]), "origin": g.get("origin") or [0, 0]} if g and g.get("cell") else None


def effects(mask, size, color, soft=True, step=1):
    rgb = tuple(int(color.lstrip("#")[i: i + 2], 16) for i in (0, 2, 4))
    m = np.asarray(mask, np.float32) / 255
    if soft:
        # a soft dark shadow only: the faint glow in the text's own color (a 0.38-size blur) showed as a white blur
        # around the Burdock Shelter's line over the dark forest (user 2026-10-25: the white haze around the title
        # looked wrong, L154). A second, wider shadow keeps the line readable over a bright painted leaf instead.
        sh = np.asarray(mask.filter(ImageFilter.GaussianBlur(max(2.0, 0.10 * size))), np.float32) / 255
        dy = max(1, int(round(0.045 * size)))
        wide = np.asarray(mask.filter(ImageFilter.GaussianBlur(0.22 * size)), np.float32) / 255
        sh = np.clip(np.roll(sh, dy, axis=0) * 0.62 + wide * 0.28, 0, 1)
        glow = np.zeros_like(m)
    else:
        # a dark outline one font pixel wide around every glyph and the hard shadow: centered over a busy middle (the
        # greenhouse's lettuce, 2026-10-21) the shadow alone let some strokes melt into the leaves
        ol = np.asarray(mask.filter(ImageFilter.MaxFilter(2 * step + 1)), np.float32) / 255 * 0.6
        sh = np.maximum(np.roll(np.roll(m, step, axis=0), step, axis=1) * 0.75, ol)
        glow = np.zeros_like(m)
    # over: glow (the text's color), then the shadow (black), then the text
    a = glow
    c = np.zeros(m.shape + (3,), np.float32) + np.asarray(rgb, np.float32) / 255
    col = c * glow[..., None]
    a = sh + a * (1 - sh)
    col = col * (1 - sh[..., None])
    col = c * m[..., None] + col * (1 - m[..., None])
    a = m + a * (1 - m)
    rgb_out = np.where(a[..., None] > 1e-4, col / np.maximum(a[..., None], 1e-4), 0)
    out = np.dstack([np.clip(rgb_out * 255 + 0.5, 0, 255), np.clip(a * 255 + 0.5, 0, 255)]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def path_mask(sc, W, H, width=0.05):
    """Where the scene's small moving things go (the ant's paths, the snails', the perches, the moth's lamp, the boat
    route), as thick bands at (W, H): the title must not cover the signature detail or any other little life."""
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    lw = max(2, int(width * H))
    polys = []
    for L in sc.get("layers", []):
        if L.get("enabled") is False:
            continue
        if L["type"] == "ant":
            polys += L.get("paths") or []
        if L["type"] == "critter" and L.get("path"):
            polys.append(L["path"])
        if L["type"] == "perch":
            polys += [p["pts"] for p in L.get("perches", [])]
        if L["type"] == "moth" and L.get("center"):
            cx, cy = L["center"]
            r = 0.06 * H
            d.ellipse([cx * W - r, cy * H - r, cx * W + r, cy * H + r], fill=255)
    route = ((sc.get("events") or {}).get("boat") or {}).get("route") or {}
    if route.get("path"):
        polys.append(route["path"])
    ev = sc.get("events") or {}
    for box in [(ev.get("birds") or {}).get("band"), ((ev.get("petals") or {}).get("tree") or {}).get("box")]:
        if box:
            d.rectangle([box[0] * W, box[1] * H, box[2] * W, box[3] * H], fill=255)
    for p in polys:
        pts = [(x * W, y * H) for x, y in p]
        if len(pts) > 1:
            d.line(pts, fill=255, width=lw, joint="curve")
        for x, y in pts:
            d.ellipse([x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2], fill=255)
    return np.asarray(m, np.float32) / 255


def avoid_map(regions_png, regs, sc, W4, H4, s=4):
    """Where the title must not sit, at 1/s scale: things that move or glow (regions of an AVOID kind, grown a little)
    and where the scene's little life goes (path_mask)."""
    ids = np.asarray(Image.open(regions_png).convert("RGB"))[..., 0]
    bad_ids = [g["id"] for g in regs if g.get("kind") in AVOID]
    av = np.isin(ids, bad_ids).astype(np.uint8)
    av = np.asarray(Image.fromarray(av * 255).resize((W4 // s, H4 // s), Image.BILINEAR).filter(ImageFilter.MaxFilter(21)), np.float32) / 255
    return np.maximum(av, path_mask(sc, W4 // s, H4 // s))


def clear_of(regions_png, regs, sc, core, cx, cy, W4=3840, H4=2160, ok=0.02):
    """A set position keeps its x and moves up or down only as far as it takes for the text (core, w x h px) to cover
    no character, food, lamp, fire or little life's path (L147: the Burdock Shelter's line sat on the garter snake
    coiled in the middle of the frame, 2026-10-25). Ties go up. Returns (cx, cy), and the share covered before and
    after."""
    s = 4
    av = avoid_map(regions_png, regs, sc, W4, H4, s)
    bw, bh = max(1, core[0] // s), max(1, core[1] // s)
    x0 = int(min(max(cx / s - bw / 2, 0), W4 // s - bw))

    def share(y):
        y0 = int(round(y / s - bh / 2))
        return float(av[y0:y0 + bh, x0:x0 + bw].mean())

    lo, hi = 0.04 * H4 + core[1] / 2, 0.96 * H4 - core[1] / 2
    y_set = min(max(cy, lo), hi)
    before = share(y_set)
    if before <= ok:
        return (cx, y_set), round(before, 3), round(before, 3)
    best = (before, y_set)
    for k in range(1, int(0.45 * H4 / 8) + 1):
        for y in (y_set - 8 * k, y_set + 8 * k):
            if lo <= y <= hi:
                sh = share(y)
                if sh <= ok:
                    return (cx, y), round(before, 3), round(sh, 3)
                best = min(best, (sh, y))
    return (cx, best[1]), round(before, 3), round(best[0], 3)


def place(plate, block, regions_png, regs, sc, core):
    """Block centre (px at 4K) on the calmest, darkest, most even spot of the upper or lower band that covers nothing
    to avoid: things that move or glow (regions) and where the scene's little life goes (path_mask: paths, the birds'
    band, the petal tree). Scored on the text itself (`core`, w x h px), not its glow; the lower band, where lofi
    captions sit, is slightly preferred."""
    im = Image.open(plate).convert("L")
    W4, H4 = im.size
    s = 4
    L = np.asarray(im.resize((W4 // s, H4 // s), Image.BILINEAR), np.float32) / 255
    gx = np.abs(np.diff(L, axis=1, prepend=L[:, :1]))
    gy = np.abs(np.diff(L, axis=0, prepend=L[:1]))
    busy = gx + gy
    av = avoid_map(regions_png, regs, sc, W4, H4, s)
    ii = lambda a: np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    IB, IL, IL2, IA = ii(busy), ii(L), ii(L * L), ii(av)
    bw, bh = max(1, core[0] // s), max(1, core[1] // s)
    mean = lambda I, x0, y0: (I[y0 + bh, x0 + bw] - I[y0, x0 + bw] - I[y0 + bh, x0] + I[y0, x0]) / (bw * bh)
    cands = []
    for yc in list(np.arange(0.07, 0.31, 0.01)) + list(np.arange(0.69, 0.96, 0.01)):
        for xc in np.arange(0.06, 0.95, 0.01):
            x0, y0 = int(xc * W4 / s - bw / 2), int(yc * H4 / s - bh / 2)
            if x0 < W4 / s * 0.03 or y0 < H4 / s * 0.03 or x0 + bw > W4 / s * 0.97 or y0 + bh > H4 / s * 0.975:
                continue
            b, lum, avoid = mean(IB, x0, y0), mean(IL, x0, y0), mean(IA, x0, y0)
            sd = max(0.0, mean(IL2, x0, y0) - lum * lum) ** 0.5
            score = b / 0.05 + 0.9 * lum / 0.3 + 1.2 * sd / 0.1 + 25 * avoid + 0.6 * abs(xc - 0.5) + (0.4 if yc < 0.5 else 0.0)
            cands.append((score, xc, yc, b, lum, sd, avoid))
    cands.sort()
    _, xc, yc, b, lum, sd, avoid = cands[0]
    return (xc * W4, yc * H4), {"busy": round(float(b), 4), "lum": round(float(lum), 3), "spread": round(float(sd), 3), "avoid": round(float(avoid), 3)}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Japanese lines on a Windows console
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene")
    ap.add_argument("--font")
    ap.add_argument("--pos", help="block centre x,y (0..1), overrides the scene")
    ap.add_argument("--size", type=float)
    a = ap.parse_args()
    sd = ROOT / "scenes" / a.scene
    sc = json.loads((sd / "scene.json").read_text(encoding="utf-8"))
    I = {**DEFAULTS, **(sc.get("intro") or {})}
    if not I.get("lines"):
        sys.exit(f"intro: scenes/{a.scene}/scene.json has no intro.lines")
    aes = config("aesthetics")["aesthetics"].get(sc.get("aesthetic"), {})
    fid = a.font or I.get("font") or aes.get("title_font") or "pixel"
    lines = [x if isinstance(x, str) else x["text"] for x in I["lines"]]
    scales = [1.0 if isinstance(x, str) else float(x.get("scale", 1.0)) for x in I["lines"]]
    check_text(lines)
    size = a.size or I["size"]
    path, entry = font_file(fid)
    plate = sc.get("plate", a.scene)
    pd = ROOT / "out" / "plates" / plate
    grid = scene_grid(sc, pd) if entry.get("kind") == "pixel" else None
    block, core = (block_pixel(lines, scales, size, I["color"], cell=grid["cell"] if grid else None) if entry.get("kind") == "pixel"
                   else block_ttf(lines, scales, path, entry, size, I["color"], panel=I.get("panel")))
    regs = json.loads((pd / "regions.json").read_text(encoding="utf-8"))
    regs = regs["regions"] if isinstance(regs, dict) else regs
    pos = [float(v) for v in a.pos.split(",")] if a.pos else I["pos"]
    if pos == "auto":
        (cx, cy), why = place(pd / "plate.png", block, pd / "regions.png", regs, sc, core)
    else:
        (cx, cy), before, after = clear_of(pd / "regions.png", regs, sc, core, pos[0] * 3840, pos[1] * 2160)
        why = {"pos": "set"} if cy == pos[1] * 2160 else {"pos": "set", "moved_to": round(cy / 2160, 3), "covered": before, "now": after}
    if grid:
        block, x0, y0 = to_grid(block, cx, cy, grid)
    else:
        x0, y0 = int(round(cx - block.width / 2)), int(round(cy - block.height / 2))
    box = [x0, y0, x0 + block.width, y0 + block.height]
    buf = io.BytesIO()
    block.save(buf, "PNG")
    if not (pd / "intro.png").exists() or (pd / "intro.png").read_bytes() != buf.getvalue():
        (pd / "intro.png").write_bytes(buf.getvalue())          # untouched when identical: renders made after it stay valid
    meta = {"lines": lines, "scales": scales, "font": fid, "font_title": entry["title"], "size": size, "color": I["color"], "box": box,
            "timing": {k: I[k] for k in ("at", "fade_in", "hold", "fade_out")}, "placement": why,
            "key": spec_key(sc, a.font, [float(v) for v in a.pos.split(",")] if a.pos else None, a.size)}
    (pd / "intro.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    # preview: the plate with the title (and its box outlined), and the block at 1:1 beside it
    bg = Image.open(pd / "plate.png").convert("RGB")
    comp = bg.copy()
    comp.paste(block, (x0, y0), block)
    out = comp.resize((1920, 1080), Image.LANCZOS)
    ImageDraw.Draw(out).rectangle([x0 / 2, y0 / 2, box[2] / 2, box[3] / 2], outline=(255, 200, 0))
    crop = comp.crop((max(0, x0 - 60), max(0, y0 - 60), min(3840, box[2] + 60), min(2160, box[3] + 60)))
    sheet = Image.new("RGB", (1920, 1080 + crop.height), (20, 20, 20))
    sheet.paste(out, (0, 0))
    sheet.paste(crop, (0, 1080))
    sheet.save(pd / "intro_preview.jpg", quality=90)
    print(f"intro: {' / '.join(lines)} | {entry['title']} | box {box} ({block.width}x{block.height} px at 4K) | {why}")
    print(f"  -> {pd / 'intro.png'}, intro.json, intro_preview.jpg")


if __name__ == "__main__":
    main()
