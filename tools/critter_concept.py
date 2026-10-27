"""Critter town concept (docs/IDEAS.md): the idea's look in one still per map style, made from AI maps and sprite sheets.

Only the map is generated; the creatures and kids are pixel sprites placed in code. This is the method the real look
would use (docs/IDEAS.md "What it needs"): every sprite is converted to the map's own art-pixel grid, so map and cast
share one pixel size, and the composite is drawn at art resolution and scaled up with nearest neighbor.

  .venv\\Scripts\\python tools\\critter_concept.py gen [map_modern map_handheld sheet_creatures sheet_trainers]
      ~$0.26 for all four (gpt-image, high) -> out/concepts/critter-town/<name>.png + .json (prompt, size, usage)
  .venv\\Scripts\\python tools\\critter_concept.py cut       cut the 20 sprites out of the two sheets -> sprites/
  .venv\\Scripts\\python tools\\critter_concept.py comp [cast handheld modern]
      the cast lineup and the two concepts -> out/concepts/critter-town/concept_*.png and docs/ideas/critter-town-*.png

The two sheets are kept in docs/ideas/critter-town/ (the cast's designs); `cut` reads them from there when out/ has
none. The maps stay in out/ (each video would get its own map). Placements in handheld() and modern() are measured on
these two maps (2560x1440 map pixels); new maps need new placements.

Art resolutions divide 4K exactly: the handheld map is 480x270 art pixels (x8 at 4K; measured 5.32 px cells at
2560), the modern one 768x432 (x5; it had no clean grid, so it is pixelized to that, plate_prep.pixelize).
to_pixel() is the sprite conversion: k-means palette from the sheet sprite, each art pixel takes its footprint's most
common color, dark lines win when they cover half of it (lower shares darken faces), and a 1 px dark outline.
"""
import base64
import json
import random
import sys
import time
import zlib

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT
from cozy.images import lum  # noqa: E402
from cozy.masks import pixelize  # noqa: E402

D = ROOT / "out" / "concepts" / "critter-town"
DOCS = ROOT / "docs" / "ideas"

NONE = ("Leave the paths, the square, the pier, the benches and the grass patches open and empty. No people, no characters, "
        "no creatures, no animals, no birds, no text, no letters, no numbers, no signs with writing, no logos, no symbols on "
        "roofs or signs, no balls, no user interface, no frame or border.")
JOBS = {
    "map_modern": dict(size="2560x1440", prompt=(
        "Top-down pixel art map of a cozy autumn village, in the style of modern indie pixel-art RPGs, seen from above at the "
        "slight three-quarter angle of classic overworld maps, one single screen, wide 16:9. Crisp pixel art with one consistent "
        "pixel size, chunky dark outlines, rich warm colors and soft shading. The village: a small cobblestone square with a "
        "round stone fountain in the middle; three cottages with red-brown tiled roofs, chimneys and wooden doors facing the "
        "paths; wooden benches by the square; flower boxes and pumpkins; low wooden fences; dirt and stone paths connecting the "
        "houses; several patches of tall wild grass; trees in full autumn color, orange, red and golden, with fallen leaves "
        "scattered on the grass; a calm blue lake along one side with a short wooden pier reaching into the water; a little "
        "stone bridge over a stream that runs into the lake; a few rocks. " + NONE)),
    "map_handheld": dict(size="2560x1440", prompt=(
        "Top-down pixel art map in the style of a 2000s handheld monster-collecting RPG overworld (Game Boy Advance era), seen "
        "from above at the slight three-quarter angle of those games, one single screen, wide 16:9. A small autumn route town: "
        "bright simple palette, flat colors with simple shading, clean 16x16 tile shapes, one consistent pixel size, crisp "
        "edges, no blur. Rows of round-topped autumn trees in orange, red and yellow framing the edges; a wide pond with gentle "
        "wave tiles and a short wooden pier; sandy paths; two small houses, one with a large red roof and a green door, one "
        "smaller with a blue roof and a brown door; wooden fences; a few wooden benches; a small vegetable garden; patches of "
        "tall grass; fallen leaves on the ground; flowers. " + NONE)),
    "sheet_creatures": dict(size="1536x1024", background="transparent", prompt=(
        "A sprite sheet of 12 small original creature characters as pixel art overworld sprites for a cozy top-down RPG, in a "
        "4 by 3 grid with lots of empty space between them, each one standing alone in its cell, seen from the front at the "
        "slight top-down angle of 2000s handheld RPG overworld sprites, each drawn about 24 pixels tall with large chunky "
        "square pixels, dark outlines, flat colors with simple shading, transparent background, no ground shadows, no text, no "
        "labels, no grid lines. Row 1: a red fox kit with a cream-tipped tail; a brown river otter; a fluffy yellow duckling; a "
        "green tree frog. Row 2: a squirrel whose tail is a big red maple leaf; a white bunny whose ears end in dandelion puffs; "
        "a small porcupine whose back is covered in pinecone scales; a raccoon kit wearing a little knitted orange scarf. Row 3: "
        "a barn owl flying with wings spread, seen from above; a moth with stained-glass wings, seen from above; a large gentle "
        "manatee-like water creature with moss and small flowers on its back, seen from above as it floats; a small round "
        "hedgehog wearing an acorn cap. All original designs that do not resemble any existing game or cartoon character.")),
    "sheet_trainers": dict(size="1536x1024", background="transparent", prompt=(
        "A sprite sheet of 8 small original human characters as pixel art overworld sprites for a cozy top-down RPG, in a 4 by "
        "2 grid with lots of empty space between them, each one alone in its cell, at the slight top-down angle of 2000s "
        "handheld RPG overworld sprites, each drawn about 24 pixels tall with large chunky square pixels, dark outlines, flat "
        "colors, simple cute proportions with a big head, transparent background, no ground shadows, no text, no labels. Row 1: "
        "a girl in a yellow raincoat with a small backpack walking, facing right; the same girl seen from behind, facing up; a "
        "boy in a green cap with a brown satchel walking, facing left; the same boy walking, facing down. Row 2: an old "
        "fisherman in a bucket hat and a vest holding a fishing rod out to the right, facing right; a kid in a red knitted "
        "scarf and a beanie sitting down, facing down; a teenager in a purple hoodie walking, facing down; a kid sitting "
        "cross-legged, facing down, as if riding on something. Original designs that do not resemble any existing game "
        "character.")),
}
SHEETS = {
    "sheet_creatures": (4, 3, ["fox", "otter", "duckling", "frog", "squirrel", "bunny", "porcupine", "raccoon", "owl", "moth",
                               "manatee", "hedgehog"]),
    "sheet_trainers": (4, 2, ["girl_r", "girl_up", "boy_l", "boy_d", "fisher_r", "kid_sit", "teen_d", "kid_ride"]),
}


def cmd_gen(names):
    from azure_ai import generate_image
    D.mkdir(parents=True, exist_ok=True)
    for name in names or list(JOBS):
        job = JOBS[name]
        t = time.time()
        res = generate_image(job["prompt"], size=job["size"], quality="high", n=1, purpose=f"concept:critter-town:{name}",
                             background=job.get("background"))
        (D / f"{name}.png").write_bytes(base64.b64decode(res["data"][0]["b64_json"]))
        (D / f"{name}.json").write_text(json.dumps({"prompt": job["prompt"], "size": job["size"],
                                                    "background": job.get("background"), "usage": res.get("usage"),
                                                    "date": time.strftime("%Y-%m-%d")}, indent=1) + "\n",
                                        encoding="utf-8", newline="\n")
        print(f"{name}: {D / name}.png ({time.time() - t:.0f} s)")


def cmd_cut():
    """Each sheet's sprites by alpha components, grouped into the grid cells of the prompt's order."""
    (D / "sprites").mkdir(parents=True, exist_ok=True)
    for sheet, (cols, rows, names) in SHEETS.items():
        src = D / f"{sheet}.png"
        if not src.exists():
            src = DOCS / "critter-town" / f"{sheet}.png"
        im = Image.open(src).convert("RGBA")
        a = np.asarray(im)
        H, W = a.shape[:2]
        m = (a[..., 3] > 128).astype(np.uint8)
        n, _, st, cen = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((9, 9), np.uint8)))
        boxes = {}
        for k in range(1, n):
            if st[k, cv2.CC_STAT_AREA] < 400:
                continue
            cx, cy = cen[k]
            cell = min(rows - 1, int(cy / (H / rows))) * cols + min(cols - 1, int(cx / (W / cols)))
            x, y, w, h = st[k, :4]
            b = boxes.get(cell)
            boxes[cell] = [x, y, x + w, y + h] if b is None else [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
        for cell, name in enumerate(names):
            if cell not in boxes:
                print(f"! {name}: nothing in its cell")
                continue
            im.crop(tuple(boxes[cell])).save(D / "sprites" / f"{name}.png")
        print(f"{sheet}: {len(boxes)} of {len(names)} sprites")


def sprites():
    if not (D / "sprites").is_dir():
        cmd_cut()
    return {p.stem: Image.open(p).convert("RGBA") for p in (D / "sprites").glob("*.png")}


def recolor(img, h_from, h_to, s_min=0.30):
    """Hue-shift the saturated pixels in a hue band (OpenCV hue 0..180): one sheet sprite becomes another kid."""
    a = np.asarray(img).copy()
    hsv = cv2.cvtColor(a[..., :3], cv2.COLOR_RGB2HSV)
    sel = (hsv[..., 0] >= h_from[0]) & (hsv[..., 0] <= h_from[1]) & (hsv[..., 1] >= s_min * 255)
    hsv[..., 0][sel] = h_to
    a[..., :3] = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return Image.fromarray(a, "RGBA")


def to_pixel(img, h_art, n=14, dark_share=0.5, flip=False):
    """Sheet sprite -> art-resolution sprite h_art pixels tall (see the module notes)."""
    a = np.asarray(img).astype(np.float32) / 255
    if flip:
        a = a[:, ::-1]
    H, W = a.shape[:2]
    w_art = max(1, round(W * h_art / H))
    op = a[..., 3] > 0.5
    px = a[..., :3][op].reshape(-1, 1, 3).astype(np.float32)
    lab = cv2.cvtColor(px, cv2.COLOR_RGB2Lab).reshape(-1, 3)
    n = min(n, len(lab))
    cv2.setRNGSeed(1)
    _, lbl, cen = cv2.kmeans(lab, n, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3,
                             cv2.KMEANS_PP_CENTERS)
    pal = cv2.cvtColor(cen.reshape(-1, 1, 3), cv2.COLOR_Lab2RGB).reshape(-1, 3)
    order = np.argsort(lum(pal))
    pal = pal[order]
    remap = np.empty(n, int)
    remap[order] = np.arange(n)
    idx = np.zeros((H, W), int)
    idx[op] = remap[lbl.ravel()]
    ty = np.minimum(np.arange(H) * h_art // H, h_art - 1)
    tx = np.minimum(np.arange(W) * w_art // W, w_art - 1)
    TY, TX = np.meshgrid(ty, tx, indexing="ij")
    hist = np.zeros((h_art, w_art, n))
    np.add.at(hist, (TY[op], TX[op], idx[op]), 1)
    cnt = np.zeros((h_art, w_art))
    np.add.at(cnt, (TY, TX), 1)
    mask = hist.sum(-1) / np.maximum(cnt, 1) >= 0.5
    choice = hist.argmax(-1)
    dark = np.where(lum(pal) < 0.20)[0]
    if len(dark):
        dh = hist[..., dark]
        use = dh.sum(-1) >= dark_share * np.maximum(hist.sum(-1), 1)
        choice[use] = dark[dh.argmax(-1)][use]
    out = pal[choice]
    m = np.pad(mask.astype(np.uint8), 1)
    er = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)))[1:-1, 1:-1]
    out[mask & (er == 0)] = pal[0]
    return Image.fromarray(np.dstack([np.clip(out * 255, 0, 255), mask * 255]).astype(np.uint8), "RGBA")


GLYPHS = {
    "!": ["..#..", "..#..", "..#..", ".....", "..#.."],
    "?": [".###.", "#...#", "..##.", ".....", "..#.."],
    "note": ["..##..", "..#.#.", "..#...", ".##...", "###...", ".#...."],
    "heart": [".#.#.", "#####", "#####", ".###.", "..#.."],
    "dots": [".....", ".....", "#.#.#", ".....", "....."],
}
INK = (40, 36, 52, 255)
PAPER = (250, 248, 240, 255)


def draw_bitmap(img, rows, x0, y0, col):
    for j, r in enumerate(rows):
        for i, ch in enumerate(r):
            if ch == "#":
                img.putpixel((x0 + i, y0 + j), col)


def bubble(img, cx, bottom, glyph):
    """An emote bubble (!, ?, note, heart, dots) with its tail at (cx, bottom)."""
    rows = GLYPHS[glyph]
    w, h = len(rows[0]) + 4, len(rows) + 4
    x0, y0 = cx - w // 2, bottom - h - 2
    d = ImageDraw.Draw(img)
    d.rectangle([x0 + 1, y0, x0 + w - 2, y0 + h - 1], fill=PAPER)
    d.rectangle([x0, y0 + 1, x0 + w - 1, y0 + h - 2], fill=PAPER)
    for x in range(x0 + 1, x0 + w - 1):
        img.putpixel((x, y0 - 1), INK)
        img.putpixel((x, y0 + h), INK)
    for y in range(y0 + 1, y0 + h - 1):
        img.putpixel((x0 - 1, y), INK)
        img.putpixel((x0 + w, y), INK)
    for p in ((x0, y0), (x0 + w - 1, y0), (x0, y0 + h - 1), (x0 + w - 1, y0 + h - 1)):
        img.putpixel(p, INK)
    for p in ((cx - 1, y0 + h), (cx, y0 + h), (cx - 1, y0 + h + 1)):
        img.putpixel(p, PAPER)
    for p in ((cx - 2, y0 + h), (cx - 2, y0 + h + 1), (cx - 1, y0 + h + 2), (cx, y0 + h + 1), (cx + 1, y0 + h)):
        img.putpixel(p, INK)
    draw_bitmap(img, rows, x0 + 2, y0 + 2, (214, 70, 70, 255) if glyph in ("!", "heart") else INK)


def zz(img, x, y):
    for rows, ox, oy in ((["####", "..#.", ".#..", "####"], 0, 0), (["###", ".#.", "###"], 5, -5)):
        for j, r in enumerate(rows):
            for i, ch in enumerate(r):
                if ch == "#":
                    img.putpixel((x + ox + i + 1, y + oy + j + 1), INK)
                    img.putpixel((x + ox + i, y + oy + j), PAPER)


def ellipse(img, cx, cy, rx, ry, col, ring=False, front_only=False):
    # its own layer: drawing RGBA onto an RGBA image replaces pixels instead of blending
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = [cx - rx, cy - ry, cx + rx, cy + ry]
    if ring and front_only:
        d.arc(box, 0, 180, fill=col)
    elif ring:
        d.ellipse(box, outline=col)
    else:
        d.ellipse(box, fill=col)
    img.alpha_composite(layer)


class Scene:
    def __init__(self, name, aw, ah, cell, ox, oy):
        im = Image.open(D / f"{name}.png").convert("RGB")
        px = np.asarray(pixelize(np.asarray(im), cell, ox, oy))
        cx = np.clip(np.round(ox + (np.arange(aw) + 0.5) * cell).astype(int), 0, im.width - 1)
        cy = np.clip(np.round(oy + (np.arange(ah) + 0.5) * cell).astype(int), 0, im.height - 1)
        self.art = Image.fromarray(px[cy][:, cx]).convert("RGBA")
        self.cell, self.ox, self.oy = cell, ox, oy
        self.items = []
        self.spr = sprites()

    def a(self, x, y):
        return round((x - self.ox) / self.cell), round((y - self.oy) / self.cell)

    def add(self, sprite, x, y, h, anchor="feet", flip=False, emote=None, water=None, grass=None, shadow=True,
            recolor_args=None, fly_shadow=None, zz_=False, under=False):
        """x, y in map pixels (feet, or the center for fliers); h in art pixels; water/grass: the share hidden below."""
        self.items.append(dict(sprite=sprite, x=x, y=y, h=h, anchor=anchor, flip=flip, emote=emote, water=water,
                               grass=grass, shadow=shadow, recolor=recolor_args, fly_shadow=fly_shadow, zz=zz_,
                               under=under))

    def render(self, leaves=30, seed=7, extra=None):
        img = self.art.copy()
        placed = []
        for it in sorted(self.items, key=lambda t: t["y"]):
            src = self.spr[it["sprite"]]
            if it["recolor"]:
                src = recolor(src, *it["recolor"])
            s = to_pixel(src, it["h"], flip=it["flip"])
            ax, ay = self.a(it["x"], it["y"])
            w, h = s.size
            x0, y0 = (ax - w // 2, ay - h) if it["anchor"] == "feet" else (ax - w // 2, ay - h // 2)
            if it["fly_shadow"]:
                sx, sy = self.a(*it["fly_shadow"])
                ellipse(img, sx, sy, max(3, w // 4), max(1, h // 7), (20, 24, 16, 42))
            elif it["shadow"] and not (it["water"] or it["grass"] or it["under"]):
                ellipse(img, ax, ay - 1, max(2, w // 3), 1, (20, 24, 16, 80))
            if it["under"]:
                arr = np.asarray(s).astype(np.float32)
                arr[..., :3] = arr[..., :3] * 0.55 + np.array([38, 104, 196]) * 0.45
                arr[..., 3] *= 0.8
                s = Image.fromarray(arr.astype(np.uint8), "RGBA")
                img.alpha_composite(s, (x0, y0))
                for rx, ry, al in ((w // 2 + 2, 2, 170), (w // 2 + 6, 4, 90)):
                    ellipse(img, ax, y0 + 2, rx, ry, (225, 240, 255, al), ring=True)
                placed.append((it, x0, y0, w, h, s))
                continue
            if it["water"]:
                keep = int(round(h * (1 - it["water"])))
                ellipse(img, ax, y0 + keep, w // 2 + 2, 2, (225, 240, 255, 150), ring=True)
                s = s.crop((0, 0, w, keep))
            if it["grass"]:
                keep = int(round(h * (1 - it["grass"])))
                rnd = random.Random(zlib.crc32(it["sprite"].encode()))
                arr = np.asarray(s).copy()
                for i in range(w):
                    arr[max(0, keep + rnd.choice((-1, 0, 0, 1))):, i, 3] = 0
                s = Image.fromarray(arr, "RGBA")
            img.alpha_composite(s, (x0, y0))
            if it["water"]:
                ellipse(img, ax, y0 + keep, w // 2 + 2, 2, (235, 246, 255, 220), ring=True, front_only=True)
                ellipse(img, ax, y0 + keep + 1, w // 2 + 5, 3, (200, 225, 250, 110), ring=True, front_only=True)
            placed.append((it, x0, y0, w, h, s))
        for it, x0, y0, w, h, s in placed:
            if it["emote"]:
                bubble(img, x0 + w // 2, y0 - 1, it["emote"])
            if it["zz"]:
                zz(img, x0 + w - 2, y0 - 6)
        if extra:
            extra(self, img, placed)
        rnd = random.Random(seed)
        cols = [((214, 92, 44), (150, 52, 30)), ((232, 150, 50), (170, 96, 30)), ((240, 196, 70), (180, 130, 40)),
                ((190, 60, 44), (120, 34, 28))]
        shapes = [[(0, 0, 0), (1, 0, 0), (1, 1, 1)], [(0, 0, 0), (1, 1, 0), (0, 1, 1)], [(0, 0, 0), (1, 0, 0), (2, 1, 1)],
                  [(1, 0, 0), (0, 1, 0), (1, 1, 1)]]
        W, H = img.size
        for _ in range(leaves):
            x, y = rnd.randrange(4, W - 4), rnd.randrange(4, H - 4)
            c = rnd.choice(cols)
            for dx, dy, k in rnd.choice(shapes):
                img.putpixel((x + dx, y + dy), c[k] + (255,))
        return img


def fishing(scene, img, placed, bob):
    """A sagging line from the rod tip to a bobber at bob (map pixels) with its rings."""
    for it, x0, y0, w, h, s in placed:
        if it["sprite"] != "fisher_r":
            continue
        a = np.asarray(s)[..., 3] > 0
        ys, xs = np.nonzero(a[:, w // 2:])
        k = np.argmin(ys * 1000 - xs)
        tx, ty = x0 + w // 2 + xs[k], y0 + ys[k]
        bx, by = scene.a(*bob)
        cx, cy = (tx + bx) / 2, max(ty, by) + 2
        line = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for i in range(41):
            u = i / 40
            line.putpixel((round((1 - u) ** 2 * tx + 2 * u * (1 - u) * cx + u * u * bx),
                           round((1 - u) ** 2 * ty + 2 * u * (1 - u) * cy + u * u * by)), (238, 238, 228, 190))
        img.alpha_composite(line)
        ellipse(img, bx, by + 1, 3, 1, (235, 246, 255, 210), ring=True)
        ellipse(img, bx, by + 1, 6, 2, (210, 230, 250, 120), ring=True)
        img.putpixel((bx, by - 1), (220, 60, 50, 255))
        img.putpixel((bx, by), (250, 250, 250, 255))


def wake(scene, img, placed):
    """A V of light pixels behind the kid riding across the water."""
    for it, x0, y0, w, h, s in placed:
        if it["sprite"] != "kid_ride":
            continue
        cx, wy = x0 + w // 2, y0 + s.size[1]
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        for k in range(1, 9):
            for sgn in (-1, 1):
                layer.putpixel((cx + sgn * (w // 2 + k), wy - 1 - k // 2), (230, 244, 255, 200 - k * 15))
        img.alpha_composite(layer)


CAST_H = dict(girl_r=20, girl_up=20, boy_l=20, boy_d=20, teen_d=21, fisher_r=22, kid_sit=17, kid_ride=19, fox=13, otter=13,
              duckling=10, frog=9, squirrel=14, bunny=14, porcupine=13, raccoon=13, hedgehog=11, owl=13, moth=12, manatee=16)


def cast(scale=6):
    spr = sprites()
    sp = [to_pixel(spr[k], h) for k, h in CAST_H.items()]
    W = sum(s.width + 4 for s in sp) + 4
    sheet = Image.new("RGBA", (W, 26), (112, 168, 88, 255))
    x = 4
    for s in sp:
        sheet.alpha_composite(s, (x, 24 - s.height))
        x += s.width + 4
    return sheet.resize((W * scale, 26 * scale), Image.NEAREST)


def handheld():
    sc = Scene("map_handheld", 480, 270, 5.3232, 1.75, 4.5)
    sc.add("girl_r", 690, 612, 20, emote="note")
    sc.add("fox", 612, 616, 13, flip=True)
    sc.add("boy_l", 815, 612, 20)
    sc.add("raccoon", 900, 616, 13, emote="heart")
    sc.add("teen_d", 1256, 305, 21)
    sc.add("squirrel", 1256, 170, 14)
    sc.add("fisher_r", 1325, 935, 22, emote="!")
    sc.add("kid_sit", 414, 728, 17)
    sc.add("hedgehog", 515, 738, 11, zz_=True)
    sc.add("girl_up", 456, 420, 20, recolor_args=((15, 40), 88))
    sc.add("kid_ride", 760, 1075, 21, water=0.08)
    sc.add("otter", 500, 935, 13, water=0.40)
    sc.add("duckling", 590, 962, 10, water=0.30)
    sc.add("manatee", 1900, 1165, 18, under=True)
    sc.add("bunny", 2200, 805, 15, grass=0.28)
    sc.add("porcupine", 2150, 385, 14, grass=0.35)
    sc.add("owl", 930, 175, 13, anchor="center", fly_shadow=(965, 330), shadow=False)
    sc.add("frog", 1760, 790, 9)
    sc.add("moth", 620, 405, 12, anchor="center", shadow=False)
    return sc.render(leaves=26, extra=lambda s, i, p: (fishing(s, i, p, (1432, 900)), wake(s, i, p)))


def modern():
    sc = Scene("map_modern", 768, 432, 2560 / 768, 0.0, 0.0)
    sc.add("girl_r", 1200, 750, 29, emote="note")
    sc.add("fox", 1112, 752, 18, flip=True)
    sc.add("boy_l", 1330, 750, 29)
    sc.add("raccoon", 1420, 752, 18, emote="heart")
    sc.add("teen_d", 1632, 292, 30)
    sc.add("squirrel", 1638, 172, 19)
    sc.add("fisher_r", 2240, 990, 31, emote="!")
    sc.add("kid_sit", 1093, 447, 24)
    sc.add("hedgehog", 1182, 457, 15, zz_=True)
    sc.add("girl_up", 731, 605, 29, recolor_args=((15, 40), 88))
    sc.add("kid_ride", 1900, 1238, 28, water=0.08)
    sc.add("otter", 1050, 1345, 18, water=0.40)
    sc.add("duckling", 1172, 1310, 14, water=0.30)
    sc.add("manatee", 2150, 1272, 24, under=True)
    sc.add("bunny", 860, 852, 19, grass=0.28)
    sc.add("porcupine", 2140, 338, 18, grass=0.35)
    sc.add("owl", 1440, 500, 19, anchor="center", fly_shadow=(1478, 628), shadow=False)
    sc.add("frog", 1460, 1137, 13)
    sc.add("moth", 2030, 465, 16, anchor="center", shadow=False)
    return sc.render(leaves=34, extra=lambda s, i, p: (fishing(s, i, p, (2350, 985)), wake(s, i, p)))


def cmd_comp(which):
    which = which or ["cast", "handheld", "modern"]
    DOCS.mkdir(parents=True, exist_ok=True)
    if "cast" in which:
        c = cast().convert("RGB")
        c.save(D / "concept_cast.png")
        c.save(DOCS / "critter-town-cast.png", optimize=True)
    for name, fn, doc_scale in (("handheld", handheld, 4), ("modern", modern, 2)):
        if name in which:
            art = fn().convert("RGB")
            art.save(D / f"concept_{name}_art.png")
            art.resize((2560, 1440), Image.NEAREST).save(D / f"concept_{name}.png")
            art.resize((art.width * doc_scale, art.height * doc_scale), Image.NEAREST).save(
                DOCS / f"critter-town-{name}.png", optimize=True)
            print(f"{name}: art {art.size} -> docs/ideas/critter-town-{name}.png")


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("comp", [])
    {"gen": lambda: cmd_gen(args), "cut": cmd_cut, "comp": lambda: cmd_comp(args)}.get(
        cmd, lambda: sys.exit(__doc__))()
