"""The thumbnail spec of a finished video (stage thumbs): ThumbSpec builds the channel's pixel close-up first, then
concepts in the look's own fonts and motifs, each line placed clear of the pet and the hero and colored against what's
behind it on the graded frame. Moved verbatim from finish_video.py (TASKS.md T15), which imports it from here.

  ThumbSpec(f, words, plan).build()   the spec tools/thumbnail.py draws (f: finish_video's Finish, plan: its thumb_plan())
"""
import datetime as dt
import re
import unicodedata

from cozy.paths import config

W, H = 3840, 2160
BADGES_BOX = [0.0, 0.0, 0.32, 0.16]          # where the 4K / 10 HR tags sit (top left), kept clear of other text
HALO = [{"color": "#06040c", "blur": 0.22, "alpha": 0.75, "grow": 0.06}]   # a dark backing under neon (lessons L65)
NEON = [("pink", "#fff3fb", "#ff3fa6"), ("cyan", "#effdff", "#33d6ff"), ("warm", "#fff6e8", "#ff8c1a"),
        ("violet", "#f6efff", "#b26bff"), ("green", "#effff4", "#3dff96")]
CARD_COLORS = {   # fill, fill2, border, border_w, ink, sub-line ink, the 4K seal
    "paper": ("#f7efdd", "#eadcbf", "#b49a6c", 7, "#2a1a10", "#5a3d24", "#c8322a"),
    "parchment": ("#efe0bd", "#dcc595", "#8a6a3a", 8, "#2a1a10", "#5a3d24", "#9e1b1b"),
    "chalk": ("#26332c", "#1b241f", "#6b4a2b", 26, "#f4f1e8", "#cfd9cf", "#e8c26a"),
    "wood": ("#6b4428", "#4e2f1a", "#2e1a0d", 12, "#ffe9c2", "#e8cfa2", "#ffcf6b"),
    "brass": ("#c9a24a", "#8a6a2a", "#5a4214", 10, "#2a1a08", "#3a2a10", "#7a1a12"),
    "sticky": ("#ffe680", "#f5d655", None, 0, "#2a2208", "#5a4a10", "#c8322a"),
    "console": ("#0b1a22", "#07121a", "#33d6ff", 8, "#bff7ff", "#7fd9e8", "#33d6ff"),
}


def crop_rect(zoom, center):
    """The part of the frame a variant shows (fractions x0, y0, w, h), clamped like thumbnail.region."""
    c = 1 / max(zoom, 1.0)
    return (min(max(center[0] - c / 2, 0.0), 1 - c), min(max(center[1] - c / 2, 0.0), 1 - c), c, c)


def to_crop(box, rect):
    x0, y0, cw, ch = rect
    return [(box[0] - x0) / cw, (box[1] - y0) / ch, (box[2] - x0) / cw, (box[3] - y0) / ch]


def overlap(a, b):
    """The share of box a (x0, y0, x1, y1) that box b covers."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-9)
    return max(w, 0) * max(h, 0) / area


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def pixel_safe(text):
    """Text the channel's pixel font can draw: accents dropped (Café -> Cafe), other missing glyphs left out."""
    import pixelfont as pf
    t = unicodedata.normalize("NFKD", text)
    return re.sub(r"\s+", " ", "".join(ch for ch in t if ch in " \n" or ch in pf.GLYPHS)).strip()


# ---- The thumbnail spec (stage thumbs).

class ThumbSpec:
    """Builds the thumbnail spec: the channel's pixel close-up first, then concepts in the look's own fonts and motifs. Each
    text line is placed clear of the pet and the hero, and colored against what's right behind it on the graded frame."""

    def __init__(self, f, words, plan):
        import cv2
        import numpy as np
        import intro_title as IT
        import pixelfont as pf
        import thumbnail as T
        self.cv2, self.np, self.IT, self.pf, self.T = cv2, np, IT, pf, T
        self.f, self.w, self.p = f, words, plan
        self.frame = plan["frame"]
        img = T.frame_image({"scene": f"scenes/{f.scene}"}, {"frame": self.frame}, False)   # rendered once, then cached
        self.small = cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)
        self.fonts = plan["fonts"]
        self.hr = f"{f.hours} HR"
        ww = words["weather_word"]
        self.music = f.has_music
        self.short = f"{words['music_word'].lower()} & {ww}" if self.music else words["weather_tag"]     # lofi & rain
        self.long = f"{words['music_tag']} & {ww}" if self.music else words["weather_tag"]               # chill lofi music & rain
        self.notes = []

    # -- measuring

    def view(self, zoom, center):
        """The variant's picture as a viewer sees it (graded, 960 x 540), to measure what's behind its text."""
        x0, y0, cw, ch = crop_rect(zoom, center)
        h, w = self.small.shape[:2]
        sub = self.small[int(round(y0 * h)):int(round((y0 + ch) * h)), int(round(x0 * w)):int(round((x0 + cw) * w))]
        sub = self.cv2.resize(sub, (960, 540), interpolation=self.cv2.INTER_LINEAR)
        return self.np.asarray(self.T.grade(sub, self.T.GRADE), self.np.float32)

    def bg(self, v, box):
        """Brightness (mean, 80th percentile), colorfulness and hue of the picture inside a box."""
        np, cv2 = self.np, self.cv2
        x0, y0, x1, y1 = (min(max(b, 0.0), 1.0) for b in box)
        h, w = v.shape[:2]
        sub = v[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)].reshape(-1, 3)
        lum = sub @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        chroma = sub.max(1) - sub.min(1)
        hsv = cv2.cvtColor(np.ascontiguousarray(sub.reshape(-1, 1, 3)), cv2.COLOR_RGB2HSV).reshape(-1, 3)
        a = np.deg2rad(hsv[:, 0])
        hue = float(np.degrees(np.arctan2((np.sin(a) * chroma).sum(), (np.cos(a) * chroma).sum())) % 360)
        return {"lum": float(lum.mean()), "p80": float(np.percentile(lum, 80)), "chroma": float(chroma.mean()), "hue": round(hue)}

    @staticmethod
    def bright(st):
        return st["p80"] > 0.42 or st["lum"] > 0.3

    def box(self, it):
        """A text item's box in its picture (fractions), from the masks thumbnail.py draws it with."""
        T, pf = self.T, self.pf
        if it.get("font") not in (None, "pixel"):
            st = {**T.TSTYLES.get(it.get("style", "soft"), {}), **{k: v for k, v in it.items() if k not in T._TTF_KEYS}}
            _, (ix0, iy0, ix1, iy1) = T.ttf_mask(it, st)
            w, h, size = ix1 - ix0, iy1 - iy0, float(it["size"])
            px, py = [p * size for p in st["box"].get("pad", [0.4, 0.2])] if st.get("box") else (0.0, 0.0)
            left = it.get("x", 0.5) * W - {"left": 0, "right": w}.get(it.get("align", "center"), w / 2)
            top = it["y"] * H - h / 2
            return [(left - px) / W, (top - py) / H, (left + w + px) / W, (top + h + py) / H]
        st = {**T.STYLES[it.get("style", "title")], **{k: v for k, v in it.items() if k not in T._ITEM_KEYS}}
        m, n = T.text_mask(it, st)
        P = it["px"]
        block = (n - 1) * (pf.ROWS + st["leading"]) + pf.BASE
        bx, by = st["box"].get("pad", [3, 2]) if st["box"] else (0, 0)
        ink = m.shape[1] * P
        left = it.get("x", 0.5) * W - {"left": 0, "right": ink}.get(it.get("align", "center"), ink / 2) - bx * P
        top = it["y"] * H - (block / 2 + by) * P
        return [left / W, top / H, (left + ink + 2 * bx * P) / W, (top + (block + 2 * by + pf.ROWS - pf.BASE) * P) / H]

    def fit(self, text, font, style, size, max_w):
        """The largest font size (px at 4K, at most size) at which a smooth line is at most max_w of the frame wide."""
        b = self.box({"text": text, "font": font, "size": size, "style": style, "x": 0.5, "y": 0.5})
        return int(max(40, min(size, size * max_w / max(b[2] - b[0], 1e-6))))

    def px_fit(self, it, max_w, px_max):
        """The largest pixel size (a multiple of 3, at most px_max) at which a pixel line is at most max_w wide."""
        b = self.box({**it, "px": 3, "x": 0.5})
        return max(9, min(px_max, int(max_w / max(b[2] - b[0], 1e-6) * 3) // 3 * 3))

    def safe(self, text, font):
        """The text with what the font lacks spelled out or dropped (& -> and, é -> e)."""
        fnt = self.T.ttf_font(font, 100)
        if not self.IT.missing_glyphs(fnt, text.replace("\n", "")):
            return text
        if "&" in self.IT.missing_glyphs(fnt, "&"):
            text = text.replace("&", "and")
        text = unicodedata.normalize("NFKD", text)
        miss = set(self.IT.missing_glyphs(fnt, text.replace("\n", "")))
        return "".join(ch for ch in text if ch not in miss)

    def avoid(self, rect, extra=()):
        """Boxes in the picture that text must not cover: the pet, steaming food with its plume, the fire."""
        out = []
        for g in self.f.regions():
            if g["kind"] in ("pet", "steam", "fire"):
                x0, y0, x1, y1 = g["bbox"]
                if g["kind"] == "steam":
                    y0 = max(0.0, y0 - (y1 - y0))
                out.append(to_crop([x0, y0, x1, y1], rect))
        return out + list(extra)

    @staticmethod
    def scrim(b, alpha):
        b = [float(x) for x in b]
        return {"x": round((b[0] + b[2]) / 2, 3), "y": round((b[1] + b[3]) / 2, 3), "rx": round((b[2] - b[0]) / 2 + 0.05, 3),
                "ry": round((b[3] - b[1]) / 2 + 0.06, 3), "alpha": alpha}

    def shade(self, v, items, view, alpha=0.5, always=False):
        """A soft dark shade under text whose spot is bright (lessons L65), or always (alpha then by brightness)."""
        b = union([self.box(it) for it in items])
        st = self.bg(view, b)
        add = always or self.bright(st)
        if add:
            v.setdefault("scrims", []).append(self.scrim(b, alpha if not always else (0.6 if self.bright(st) else 0.4)))
        self.notes.append(f"{v['name']}: behind {' / '.join(it['text'] for it in items)!r} brightness {st['lum']:.2f} "
                          f"(80th percentile {st['p80']:.2f}), hue {st['hue']}" + (", shaded" if add else ""))
        return st

    @staticmethod
    def hue(hexc):
        import colorsys
        return colorsys.rgb_to_hsv(*(int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)))[0] * 360

    def neon_for(self, view, box, taken=(), main=False):
        """The tube color for a neon line (lessons L65). Its masking: how much of the brightest fifth of the picture around
        the line (its box plus the halo) shares the tube's hue, chroma-weighted, 0 to 1. A tube shows when the bright
        things behind it have other colors (the warm lanterns hid an orange tube in the ramen alley; a cyan one showed).
        The main line keeps pink, like the alley's own signs, unless it is masked; the other line takes the least masked
        color at least 60 degrees from the first. Returns (color, maskings)."""
        np, cv2 = self.np, self.cv2

        def dist(a, b):
            d = abs(a - b) % 360
            return min(d, 360 - d)
        x0, y0, x1, y1 = (min(max(b, 0.0), 1.0) for b in (box[0] - 0.04, box[1] - 0.04, box[2] + 0.04, box[3] + 0.04))
        h, w = view.shape[:2]
        sub = view[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)]
        lab = cv2.cvtColor(np.ascontiguousarray(sub, np.float32), cv2.COLOR_RGB2Lab).reshape(-1, 3)
        top = lab[lab[:, 0] >= np.percentile(lab[:, 0], 80)]
        C = np.hypot(top[:, 1], top[:, 2])
        hab = np.degrees(np.arctan2(top[:, 2], top[:, 1])) % 360
        mask = {}
        for c in NEON:
            ref = cv2.cvtColor(np.array([[[int(c[2][i:i + 2], 16) / 255 for i in (1, 3, 5)]]], np.float32), cv2.COLOR_RGB2Lab).reshape(3)
            d = np.abs(hab - np.degrees(np.arctan2(ref[2], ref[1])) % 360) % 360
            d = np.minimum(d, 360 - d)
            mask[c[0]] = round(float((np.clip(1 - d / 60, 0, 1) * np.clip(C / 30, 0, 1)).mean()), 2)
        allowed = [c for c in NEON if all(dist(self.hue(c[2]), self.hue(t[2])) >= 60 for t in taken)] or list(NEON)
        if main and allowed[0][0] == "pink" and mask["pink"] <= 0.35:
            return allowed[0], mask
        return min(allowed, key=lambda c: (mask[c[0]], NEON.index(c))), mask

    def badges(self, x=0.035, y=0.08, size=190):
        """4K and the length on smooth tags in the look's tag font (about 190 px at 4K reads on a phone)."""
        return [{"x": x, "y": y, "font": self.fonts["tag"], "size": size, "gap": 40, "style": "chip",
                 "items": [{"text": "4K"}, {"text": self.hr}]}]

    def pixel_tag(self, px, y):
        # no symbols in the tags: no emoji since 2026-10-26 (the ramen alley's had a note and a rain cloud)
        if self.music:
            return {"text": pixel_safe(self.long), "px": px, "y": y, "style": "badge"}
        return {"text": pixel_safe(self.w["weather_tag"]), "px": px, "y": y, "style": "chip"}

    def band(self, view, avoid, make, ys):
        """The text block (make(y) -> items) at the y where it covers least of what to avoid, on the darkest spot."""
        best = None
        for y in ys:
            items = make(round(y, 3))
            boxes = [self.box(it) for it in items]
            if min(b[1] for b in boxes) < 0.03 or max(b[3] for b in boxes) > 0.95:
                continue
            ov = max([overlap(b, a) for b in boxes for a in avoid] or [0])
            lum = sum(self.bg(view, b)["lum"] for b in boxes) / len(boxes)
            score = 6 * ov + lum + 0.4 * abs(y - 0.4)
            if best is None or score < best[0]:
                best = (score, items, boxes)
        return best

    # -- concepts

    def pixel_hero(self, name, subj):
        """The channel's pixel concept (his pick on both published videos): the hero big, the place name in amber pixel
        letters and the music tag on the other side, the subject kept below the words."""
        title = {"text": pixel_safe(self.w["name"]), "px": 30, "y": 0.27, "style": "amber"}
        title["px"] = self.px_fit(title, 0.6, 30)
        tag = self.pixel_tag(15, 0.38)
        tag["px"] = self.px_fit(tag, 0.62, 15)
        bb = subj["bbox"]
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        zoom = min(max(min(0.5 / bh, 0.62 / bw), 1.6), 3.4)
        for _ in range(12):
            c = 1 / zoom
            rect = crop_rect(zoom, ((bb[0] + bb[2]) / 2 - 0.36 * c + c / 2, bb[3] - 0.97 * c + c / 2))
            hb = to_crop(bb, rect)
            left = (hb[0] + hb[2]) / 2 < 0.5                      # the hero on the left: the words go right
            for it in (title, tag):
                it["x"], it["align"] = (0.95, "right") if left else (0.05, "left")
            if all(overlap(self.box(it), hb) < 0.02 for it in (title, tag)) or zoom <= 1.6:
                break
            zoom = max(1.6, zoom * 0.92)
        center = [round(rect[0] + rect[2] / 2, 4), round(rect[1] + rect[3] / 2, 4)]
        v = {"name": name, "frame": self.frame, "zoom": round(zoom, 3), "center": center, "text": [title, tag]}
        self.shade(v, [title], self.view(zoom, center))
        return v

    def neon(self, name, _):
        """The place's name in neon tubes over a soft shade, the music and the weather in a second tube color."""
        nf = self.fonts["neon"]
        zoom, center = 1.05, [0.5, 0.47]
        rect, view = crop_rect(zoom, center), self.view(zoom, center)
        l1, l2 = self.safe(self.w["name"].lower(), nf), self.safe(self.short, nf)
        s1 = self.fit(l1, nf, "neon", 560, 0.62)
        s2 = self.fit(l2, nf, "neon", min(280, int(s1 * 0.55)), 0.5)
        h2 = self.box({"text": l2, "font": nf, "size": s2, "x": 0.5, "y": 0.5, "style": "neon"})

        def make(y):
            it1 = {"text": l1, "font": nf, "size": s1, "x": 0.5, "y": y, "style": "neon"}
            y2 = float(self.box(it1)[3] + 0.045 + (h2[3] - h2[1]) / 2)
            return [it1, {"text": l2, "font": nf, "size": s2, "x": 0.5, "y": round(y2, 3), "style": "neon"}]
        best = self.band(view, self.avoid(rect, [BADGES_BOX]), make, [0.26 + 0.02 * i for i in range(20)])
        if best is None:
            return None
        _, (it1, it2), (b1, b2) = best
        c1, sc1 = self.neon_for(view, b1, main=True)
        c2, sc2 = self.neon_for(view, b2, [c1])
        it1.update(fill=c1[1], neon=c1[2], glow=HALO)
        it2.update(fill=c2[1], neon=c2[2], glow=HALO)
        for it, c, sc in ((it1, c1, sc1), (it2, c2, sc2)):
            self.notes.append(f"{name}: {it['text']!r} in a {c[0]} tube (masking by the bright things behind it: "
                              + ", ".join(f"{k} {v:.2f}" for k, v in sc.items()) + ")")
        return {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "badges": self.badges(),
                "scrims": [self.scrim(b1, 0.5), self.scrim(b2, 0.45)], "text": [it1, it2]}

    def card(self, name, arg):
        """A flat thing from the look's motifs (a ticket, a label, a chalkboard, a sign) with the place name, the music and
        the weather, "10 HR" and a 4K seal, set on the side where it hides neither the pet nor the hero."""
        kind, motif = arg
        fill, fill2, border, bw, ink, sub, seal = CARD_COLORS[kind]
        hand, heavy = self.fonts["hand"], self.fonts["heavy"]
        zoom, center = 1.05, [0.5, 0.47]
        avoid = self.avoid(crop_rect(zoom, center))
        cw, chh = 1240, 780
        best = None
        for cx, rot in ((0.215, -6), (0.785, 5)):
            for cy in (0.43, 0.5, 0.37, 0.57):
                b = [cx - cw / W / 2 - 0.02, cy - chh / H / 2 - 0.03, cx + cw / W / 2 + 0.02, cy + chh / H / 2 + 0.03]
                ov = max([max(overlap(b, a), overlap(a, b)) for a in avoid] or [0])
                score = 6 * ov + abs(cy - 0.45) + (0.05 if cx > 0.5 else 0)
                if best is None or score < best[0]:
                    best = (score, cx, cy, rot)
        _, cx, cy, rot = best
        maxw = 0.84 * cw / W
        l1 = self.safe(self.w["name"].lower(), hand)
        l2 = self.safe(self.long if self.music else f"with {self.w['weather_tag']}", hand)
        lines = [{"text": l1, "font": hand, "size": self.fit(l1, hand, "ink", 175, maxw), "x": 0.5, "y": 0.37, "style": "ink", "fill": ink},
                 {"text": l2, "font": hand, "size": self.fit(l2, hand, "ink", 76, maxw), "x": 0.5, "y": 0.55, "style": "ink", "fill": sub},
                 {"text": self.hr, "font": heavy, "size": self.fit(self.hr, heavy, "ink", 160, 0.5 * cw / W), "x": 0.09, "y": 0.81,
                  "align": "left", "style": "ink", "fill": ink},
                 {"text": "4K", "font": heavy, "size": 110, "x": 0.81, "y": 0.79, "style": "stamp", "rotate": 14, "fill": seal,
                  "box": {"fill": "#000000", "alpha": 0.0, "border": seal, "border_w": 0.09, "radius": 9, "pad": [0.34, 0.34]}}]
        c = {"x": cx, "y": cy, "w": cw, "h": chh, "rotate": rot, "fill": fill, "fill2": fill2,
             "grain": 0.06 if kind == "wood" else 0.035, "radius": 22, "shadow": {"alpha": 0.6, "blur": 28, "off": [16, 26]}, "lines": lines}
        if border:
            c.update(border=border, border_w=bw)
        self.notes.append(f"{name}: {motif!r} as a {kind} card on the {'left' if cx < 0.5 else 'right'}")
        return {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "badges": [], "cards": [c]}

    def note(self, name, subj):
        """The pet (else the hero) close up, a handwritten line above it and a small music tag."""
        hand, tagf = self.fonts["hand"], self.fonts["tag"]
        text = self.safe(self.w["note"], hand)
        it = {"text": text, "font": hand, "size": self.fit(text, hand, "soft", 230, 0.86), "x": 0.5, "y": 0.2, "style": "soft"}
        bb = subj["bbox"]
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        zoom = min(max(min(0.58 / bh, 0.72 / bw), 1.8), 3.4)
        for _ in range(12):
            c = 1 / zoom
            rect = crop_rect(zoom, ((bb[0] + bb[2]) / 2 - 0.56 * c + c / 2, bb[3] - 0.95 * c + c / 2))
            hb = to_crop(bb, rect)
            if overlap(self.box(it), hb) < 0.02 or zoom <= 1.8:
                break
            zoom = max(1.8, zoom * 0.92)
        center = [round(rect[0] + rect[2] / 2, 4), round(rect[1] + rect[3] / 2, 4)]
        tag = {"text": self.safe(self.short, tagf), "font": tagf, "size": 120, "style": "tag"}
        for x, y, al in ((0.05, 0.9, "left"), (0.95, 0.33, "right"), (0.05, 0.33, "left")):
            tag.update(x=x, y=y, align=al)
            if overlap(self.box(tag), hb) < 0.02 and overlap(self.box(tag), self.box(it)) == 0:
                break
        v = {"name": name, "frame": self.frame, "zoom": round(zoom, 3), "center": center, "badges": self.badges(), "text": [it, tag]}
        self.shade(v, [it], self.view(zoom, center), alpha=0.45)
        return v

    def polaroid(self, name, _):
        """The scene as a photo on a cream mat with a handwritten caption and the music."""
        hand = self.fonts["hand"]
        cap, line = self.safe(self.w["caption"], hand), self.safe(self.long, hand)
        return {"name": name, "frame": self.frame, "zoom": 1.1, "center": [0.5, 0.5],
                "mat": {"color": "#f1e8d6", "margin": [0.035, 0.06, 0.035, 0.25]}, "badges": self.badges(0.06, 0.13, 150),
                "text": [{"text": cap, "font": hand, "size": self.fit(cap, hand, "ink", 170, 0.88), "x": 0.06, "y": 0.83,
                          "align": "left", "style": "ink"},
                         {"text": line, "font": hand, "size": self.fit(line, hand, "ink", 110, 0.88), "x": 0.06, "y": 0.925,
                          "align": "left", "style": "ink", "fill": "#7a5534"}]}

    def title(self, name, _):
        """The place's name in the look's title font over a soft shade (gold lettering when the motifs ask for gold), the
        music and the weather on a tag below."""
        main, tagf = self.fonts["main"], self.fonts["tag"]
        style = "gold" if any("gold" in m.lower() for m in (self.f.look.get("thumb") or {}).get("motifs", [])) else "soft"
        zoom, center = 1.05, [0.5, 0.47]
        rect, view = crop_rect(zoom, center), self.view(zoom, center)
        l1, l2 = self.safe(self.w["name"], main), self.safe(self.long, tagf)
        s1, s2 = self.fit(l1, main, style, 400, 0.7), self.fit(l2, tagf, "tag", 130, 0.6)
        h2 = self.box({"text": l2, "font": tagf, "size": s2, "x": 0.5, "y": 0.5, "style": "tag"})

        def make(y):
            it1 = {"text": l1, "font": main, "size": s1, "x": 0.5, "y": y, "style": style}
            y2 = float(self.box(it1)[3] + 0.045 + (h2[3] - h2[1]) / 2)
            return [it1, {"text": l2, "font": tagf, "size": s2, "x": 0.5, "y": round(y2, 3), "style": "tag"}]
        best = self.band(view, self.avoid(rect, [BADGES_BOX]), make, [0.26 + 0.02 * i for i in range(20)])
        if best is None:
            return None
        items = best[1]
        v = {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "badges": self.badges(), "text": items}
        self.shade(v, items[:1], view, always=True)
        return v

    def pixel_place(self, name, pet):
        """The place card in the channel's pixel font: the name in amber between rules, the music tag and a weather chip
        (Treetop's place-card-cat); on pixel looks the pet in a corner close-up."""
        zoom, center = 1.05, [0.5, 0.47]
        rect, view = crop_rect(zoom, center), self.view(zoom, center)
        extra, insets = [BADGES_BOX], []
        if pet is not None:
            pb = pet["bbox"]
            pc = [(pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2]
            x, y = (0.17, 0.755) if to_crop(pb, rect)[0] > 0.45 else (0.83, 0.3)
            insets = [{"x": x, "y": y, "w": 0.24, "span": round(min(max(1.5 * (pb[2] - pb[0]), 0.08), 0.3), 3),
                       "center": [round(pc[0], 4), round(pc[1], 4)]}]
            extra.append([x - 0.13, y - 0.23, x + 0.13, y + 0.23])
        name_it = {"text": pixel_safe(self.w["name"]), "px": 30, "style": "amber", "rules": [5, 3], "y": 0.4}
        name_it["px"] = self.px_fit(name_it, 0.8, 30)
        chip = {"text": pixel_safe(self.w["weather_tag"]), "px": 15, "style": "chip"}

        def make(y):
            if self.music:
                return [{**name_it, "y": y}, {"text": pixel_safe(self.w["music_tag"]), "px": 18, "y": round(y + 0.105, 3),
                                              "style": "badge"}, {**chip, "y": round(y + 0.195, 3)}]
            return [{**name_it, "y": y}, {**chip, "y": round(y + 0.105, 3)}]
        best = self.band(view, self.avoid(rect, extra), make, [0.24 + 0.02 * i for i in range(18)])
        if best is None:
            return None
        v = {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "text": best[1]}
        if insets:
            v["insets"] = insets
        self.shade(v, best[1][:1], view)
        return v

    def pixel_polaroid(self, name, _):
        cap = {"text": pixel_safe(self.w["caption"]), "x": 0.06, "y": 0.83, "align": "left", "style": "ink", "bold": True}
        cap["px"] = self.px_fit(cap, 0.88, 30)
        line = {"text": pixel_safe(self.long if self.music else self.w["weather_tag"]), "x": 0.06, "y": 0.925,
                "align": "left", "style": "ink", "fill": "#7a5534", "fill2": "#7a5534", "bold": True}
        line["px"] = self.px_fit(line, 0.88, 15)
        return {"name": name, "frame": self.frame, "zoom": 1.05, "center": [0.5, 0.5],
                "mat": {"color": "#efe4cf", "margin": [0.035, 0.06, 0.035, 0.25]}, "text": [cap, line]}

    def pixel_sign(self, name, _):
        hb = self.p["hero"]["bbox"]
        x = 0.62 if (hb[0] + hb[2]) / 2 < 0.5 else 0.4
        top = {"text": pixel_safe(self.w["name"]), "px": 21, "x": x, "y": 0.2, "style": "sign"}
        sub = {"text": pixel_safe(self.w["music_tag"] if self.music else self.w["weather_tag"]), "px": 15, "x": x, "y": 0.35,
               "style": "sign", "box": {"fill": "#7a5230", "alpha": 1.0, "border": "#3a2414", "planks": 4, "pad": [3, 2], "hang": 0.26}}
        return {"name": name, "frame": self.frame, "zoom": 1.1, "center": [0.5, 0.45], "text": [top, sub]}

    # -- painterly concepts, for looks painted by hand (config/aesthetics.json thumb.painterly). Truman on the Burdock
    #    Shelter's first set (2026-10-26, L160): they needed more variety and still defaulted to blocky, similar text; a
    #    nature look in a pastel, painted style needs thumbnails to match. No pixel letters
    #    here: each concept is its own medium (a watercolor wash, a naturalist's plate, a nature journal, a storybook
    #    cover, a specimen label, a note on a wash) in pastel paper colors, and each says something different (the
    #    opening line, the species, the place, a note).

    def pt(self):
        th = (self.f.look.get("thumb") or {}).get("painterly") or {}
        pal = {"paper": "#f3ebd9", "paper2": "#e9dfc8", "sage": "#cfd8bb", "sage_ink": "#5f6f4f", "rose": "#e8c5bb",
               "butter": "#f1e0ab", "cloth": "#c8d1b5", "cloth2": "#b9c4a5", "journal": "#eef0e1", "journal2": "#e4e7d2",
               "ink": "#3a3027", "cream": "#f5ecd8", **(th.get("palette") or {})}
        typ = {"title": self.f.look.get("title_font") or "patrick-hand", "hand": "caveat", "plate": "im-fell-english",
               "label": "im-fell-english-italic", "book": "cormorant-garamond", **(th.get("type") or {})}
        return pal, typ

    def intro_words(self):
        """The video's opening line, as thumbnail words (no end stops); the place name when there is none."""
        out = []
        for ln in (self.f.sc.get("intro") or {}).get("lines") or []:
            t = (ln if isinstance(ln, str) else ln.get("text", "")).strip().rstrip(".")
            if re.search(r"[A-Za-z]", t):
                out.append(t)
        return out or [self.w["name"]]

    def cast_in_picture(self):
        """[(pet region, species, scientific name)]: the characters in the picture, matched to config/cast.json by name."""
        cast = config("cast")["cast"]
        ids = [k for k in self.f.brief.get("cast") or [] if (cast.get(k) or {}).get("species")]
        out = []
        for g in self.f.regions():
            if g["kind"] != "pet" or not ids:
                continue
            tok = set(re.findall(r"[a-z]+", g["name"].lower()))
            k = max(ids, key=lambda c: len(tok & set(c.split("-"))))
            if tok & set(k.split("-")):
                out.append((g, cast[k]["species"], cast[k].get("scientific", "")))
        return out

    def held(self):
        """What the characters hold or stand under (a lantern, a leaf held up as an umbrella): kept in view like them."""
        return [g for g in self.f.regions() if g.get("shelter") or (g.get("dry_why") and g["kind"] != "pet")]

    def with_held(self, g):
        """A character's box grown by what it holds."""
        b = list(g["bbox"])
        for o in self.held():
            if overlap(o["bbox"], [b[0] - 0.06, b[1] - 0.12, b[2] + 0.08, b[3] + 0.04]) > 0.3:
                b = union([b, o["bbox"]])
        return b

    def keep_clear(self, rect):
        """Boxes in a variant's picture that words and cards must not cover: the characters with what they hold, the
        steaming food with its plume, the fire."""
        return self.avoid(rect) + [to_crop(self.with_held(g), rect) for g in self.f.regions() if g["kind"] == "pet"]

    def ptags(self, x, y, size, font, color=None):
        """4K and the length on small pastel paper tags, left to right from x."""
        st = {"box": {**self.T.TSTYLES["paper_tag"]["box"], "border": color}} if color else {}
        return [{"x": x, "y": y, "font": font, "size": size, "gap": int(size * 0.3), "style": "paper_tag",
                 "items": [{"text": "4K", **st}, {"text": self.hr, **st}]}]

    @staticmethod
    def place_pic(zoom, center, w, h, cx, cy):
        """How a frame crop (zoom, center) laid w x h px at the page point (cx, cy) maps the frame: (left, top, s, x0, y0),
        the same clamp as thumbnail.region."""
        aspect = w / h
        rw = W / max(zoom, 1.0)
        rh = rw / aspect
        if rh > H:
            rh, rw = H, H * aspect
        x0 = min(max(center[0] * W - rw / 2, 0), W - rw)
        y0 = min(max(center[1] * H - rh / 2, 0), H - rh)
        return cx * W - w / 2, cy * H - h / 2, w / rw, x0, y0

    def on_page(self, pl, fx, fy, rot=0.0, about=None):
        """A frame point (fractions) where it lands on the page (fractions), through the picture's crop and its turn."""
        left, top, s, x0, y0 = pl
        px, py = left + (fx * W - x0) * s, top + (fy * H - y0) * s
        if rot:
            R = self.cv2.getRotationMatrix2D((about[0] * W, about[1] * H), rot, 1.0)
            px, py = R[0, 0] * px + R[0, 1] * py + R[0, 2], R[1, 0] * px + R[1, 1] * py + R[1, 2]
        return px / W, py / H

    def page_box(self, pl, b, rot=0.0, about=None):
        pts = [self.on_page(pl, x, y, rot, about) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3]))]
        return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

    def leader(self, lb, ax, ay, color, width=4, arrow=0, gap=0.012):
        """A hand-drawn line from the side of a label box that faces the point (ax, ay) to just short of it."""
        cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
        if abs(ax - cx) * W > abs(ay - cy) * H:
            sx, sy = (lb[2] + 0.006, cy) if ax > cx else (lb[0] - 0.006, cy)
        else:
            sx, sy = (cx, lb[3] + 0.008) if ay > cy else (cx, lb[1] - 0.008)
        d = self.np.hypot((ax - sx) * W, (ay - sy) * H)
        k = max(d - gap * W, 0) / max(d, 1e-6)
        ex, ey = sx + (ax - sx) * k, sy + (ay - sy) * k
        mx, my = (sx + ex) / 2, (sy + ey) / 2 - 0.012 * (1 if ey < sy else -1)        # a slight bow, as a hand draws it
        return {"points": [[round(sx, 4), round(sy, 4)], [round(mx, 4), round(my, 4)], [round(ex, 4), round(ey, 4)]],
                "width": width, "color": color, "alpha": 0.92, "wobble": 1.6, "arrow": arrow, "seed": int(abs(ax * 977 + ay * 313))}

    def pt_wash(self, name, _):
        """The video's opening line hand-lettered on a pastel watercolor wash over the scene, pastel paper tags. The wash
        (not only its words) keeps clear of the characters and what they hold."""
        pal, typ = self.pt()
        words = self.intro_words()
        t1 = self.safe(words[0], typ["title"])
        t2 = self.safe(words[1] if len(words) > 1 else self.long, typ["hand"])
        zoom, center = 1.05, [0.5, 0.47]
        rect, _view = crop_rect(zoom, center), self.view(zoom, center)
        clear = self.keep_clear(rect) + [BADGES_BOX]
        best = None
        for scale in (1.0, 0.9, 0.8, 0.72):
            s1 = self.fit(t1, typ["title"], "ink", int(330 * scale), 0.6 * scale)
            s2 = self.fit(t2, typ["hand"], "ink", int(175 * scale), 0.56 * scale)
            h2 = self.box({"text": t2, "font": typ["hand"], "size": s2, "x": 0.5, "y": 0.5, "style": "ink"})
            for y in [0.15 + 0.015 * i for i in range(40)]:
                it1 = {"text": t1, "font": typ["title"], "size": s1, "x": 0.5, "y": round(y, 3), "style": "ink", "fill": pal["ink"]}
                y2 = float(self.box(it1)[3] + 0.028 + (h2[3] - h2[1]) / 2)
                items = [it1, {"text": t2, "font": typ["hand"], "size": s2, "x": 0.5, "y": round(y2, 3), "style": "ink",
                               "fill": pal["sage_ink"]}]
                u = union([self.box(it) for it in items])
                wb = [u[0] - 0.04, u[1] - 0.05, u[2] + 0.04, u[3] + 0.05]
                if wb[1] < 0.02 or wb[3] > 0.98:
                    continue
                ov = max([overlap(c, wb) for c in clear] + [0])                     # the share of each thing the wash hides
                score = 8 * ov + 0.6 * (1 - scale) + 0.3 * abs(y - 0.3)
                if best is None or score < best[0]:
                    best = (score, items, wb, ov)
        if best is None:
            return None
        _, items, wb, ov = best
        wash = {"x": round((wb[0] + wb[2]) / 2, 4), "y": round((wb[1] + wb[3]) / 2, 4), "w": int((wb[2] - wb[0]) * W),
                "h": int((wb[3] - wb[1]) * H), "color": pal["sage"], "alpha": 0.95, "rim": 0.22, "seed": 23}
        self.notes.append(f"{name}: {t1!r} / {t2!r} on a {pal['sage']} wash at y {wash['y']} (hides {ov:.0%} of a character at most)")
        return {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "washes": [wash], "text": items,
                "badges": self.ptags(0.035, 0.08, 120, typ["hand"])}

    def pt_plate(self, name, _):
        """A naturalist's plate: the painting on cream paper inside thin ink rules, each creature labeled with its species
        in italic with a hand-drawn leader, the place's name below it like a plate's caption."""
        pal, typ = self.pt()
        cast = self.cast_in_picture()
        pets = [g for g, _, _ in cast] or [g for g in self.f.regions() if g["kind"] == "pet"]
        u = union([g["bbox"] for g in pets]) if pets else [0.1, 0.3, 0.9, 0.9]
        w, h, cx, cy = int(0.88 * W), int(0.69 * H), 0.5, 0.425
        center = [0.5, round(min(max((u[1] + u[3]) / 2, 0.3), 0.7), 4)]
        pl = self.place_pic(1.0, center, w, h, cx, cy)
        pic = {"zoom": 1.0, "center": center, "x": cx, "y": cy, "w": w, "h": h, "shadow": None, "grade": {"vignette": 0.15},
               "rules": [{"offset": 20, "width": 5, "color": pal["ink"], "alpha": 0.85},
                         {"offset": 36, "width": 2, "color": pal["ink"], "alpha": 0.55}]}
        inner = [cx - w / W / 2 + 0.012, cy - h / H / 2 + 0.02, cx + w / W / 2 - 0.012, cy + h / H / 2 - 0.02]
        bodies = [self.page_box(pl, g["bbox"]) for g in pets]
        text, strokes, taken = [], [], []
        for g, sp, _ in cast:
            b = self.page_box(pl, g["bbox"])
            ax, ay = (b[0] + b[2]) / 2, b[1] + 0.22 * (b[3] - b[1])
            label = self.safe(sp[0].upper() + sp[1:], typ["label"])
            best = None
            for x, y, al in ((ax, b[1] - 0.06, "center"), (ax, b[3] + 0.05, "center"), (b[2] + 0.02, ay, "left"),
                             (b[0] - 0.02, ay, "right"), (ax, b[1] - 0.12, "center")):
                it = {"text": label, "font": typ["label"], "size": 76, "x": round(x, 4), "y": round(y, 4), "align": al, "style": "cream"}
                lb = self.box(it)
                out_of = max(0.0, inner[0] - lb[0]) + max(0.0, lb[2] - inner[2]) + max(0.0, inner[1] - lb[1]) + max(0.0, lb[3] - inner[3])
                score = 4 * sum(overlap(lb, o) for o in bodies) + 4 * sum(overlap(lb, t) for t in taken) + 20 * out_of
                if best is None or score < best[0]:
                    best = (score, it, lb)
            _, it, lb = best
            taken.append(lb)
            text.append(it)
            strokes.append(self.leader(lb, ax, ay, pal["cream"], width=4))
        num = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}.get(len(cast))
        adj = "snowy" if self.w["weather_word"] == "snow" else "rainy"
        title = self.safe(self.w["name"], typ["plate"])
        sub = self.safe(f"{num} creatures of the Pacific Northwest on a {adj} night" if num else self.long, typ["label"])
        st = self.fit(title, typ["plate"], "ink", 200, 0.62)
        it1 = {"text": title, "font": typ["plate"], "size": st, "x": 0.5, "y": 0.855, "style": "ink", "fill": pal["ink"]}
        y2 = float(self.box(it1)[3] + 0.04)
        text += [it1, {"text": sub, "font": typ["label"], "size": self.fit(sub, typ["label"], "ink", 84, 0.6), "x": 0.5,
                       "y": round(min(y2, 0.955), 3), "style": "ink", "fill": pal["sage_ink"]}]
        self.notes.append(f"{name}: a plate with {len(cast)} species labels; caption {title!r}, {sub!r}")
        return {"name": name, "frame": self.frame, "page": {"color": pal["paper"], "color2": pal["paper2"], "grain": 0.035,
                                                             "mottle": 0.03}, "pictures": [pic], "strokes": strokes,
                "text": text, "badges": self.ptags(0.06, 0.935, 92, typ["plate"], pal["ink"])}

    def pt_journal(self, name, _):
        """A nature journal: the scene as a print taped onto a pale page at a slant, the opening line handwritten beside it,
        a note with an arrow to the creature nearest the page's free side (the arrow stops just inside the print: a long
        dark line across the painting doesn't show), and the music as a plain note."""
        pal, typ = self.pt()
        w, h, cx, cy, rot = int(0.6 * W), int(0.6 * H), 0.355, 0.54, -2.5
        pl = self.place_pic(1.0, [0.5, 0.5], w, h, cx, cy)
        pic = {"zoom": 1.0, "center": [0.5, 0.5], "x": cx, "y": cy, "w": w, "h": h, "rotate": rot,
               "margin": {"width": 34, "color": "#fbf7ec", "deckle": 2}, "shadow": {"alpha": 0.3, "blur": 30, "off": [14, 24]}}
        tl, tr = self.on_page(pl, 0.0, 0.0, rot, (cx, cy)), self.on_page(pl, 1.0, 0.0, rot, (cx, cy))
        right = max(self.on_page(pl, 1.0, 0.0, rot, (cx, cy))[0], self.on_page(pl, 1.0, 1.0, rot, (cx, cy))[0])
        tapes = [{"x": round(tl[0] + 0.004, 4), "y": round(tl[1] + 0.01, 4), "w": 330, "h": 96, "rotate": 38, "fill": pal["rose"],
                  "alpha": 0.8, "grain": 0.03, "radius": 2, "shadow": None},
                 {"x": round(tr[0] - 0.004, 4), "y": round(tr[1] + 0.01, 4), "w": 330, "h": 96, "rotate": -34, "fill": pal["butter"],
                  "alpha": 0.8, "grain": 0.03, "radius": 2, "shadow": None}]
        words = self.intro_words()
        head = self.safe(words[0][0].lower() + words[0][1:], typ["hand"])
        col_x, maxw = 0.835, 0.28
        text = [{"text": head, "font": typ["hand"], "size": self.fit(head, typ["hand"], "ink", 190, 0.29), "x": col_x, "y": 0.18,
                 "style": "ink", "fill": pal["ink"]}]
        strokes, about = [], ""
        cast = self.cast_in_picture()
        if cast:
            g, sp, _ = max(cast, key=lambda c: c[0]["bbox"][2])
            b = g["bbox"]
            ax, ay = self.on_page(pl, (b[0] + b[2]) / 2, b[1] + 0.3 * (b[3] - b[1]), rot, (cx, cy))
            short = " ".join(sp.split()[1:]) if len(sp.split()) >= 3 else sp
            it = {"text": self.safe(short, typ["hand"]), "font": typ["hand"], "x": col_x, "y": round(min(max(ay, 0.34), 0.46), 3),
                  "style": "ink", "fill": pal["sage_ink"]}
            it["size"] = self.fit(it["text"], typ["hand"], "ink", 124, maxw)
            text.append(it)
            ex = max(ax, right - 0.035)                                   # just inside the print, at the creature's height
            strokes.append(self.leader(self.box(it), ex, ay, pal["ink"], width=6, arrow=44, gap=0.0))
            about = f", an arrow to the {sp}"
        mus = self.safe(self.long, typ["hand"])
        text.append({"text": mus, "font": typ["hand"], "size": self.fit(mus, typ["hand"], "ink", 96, maxw), "x": col_x,
                     "y": 0.75, "style": "ink", "fill": pal["ink"]})
        self.notes.append(f"{name}: a taped print, {head!r}{about}, {mus!r}")
        return {"name": name, "frame": self.frame, "page": {"color": pal["journal"], "color2": pal["journal2"], "grain": 0.04,
                                                             "mottle": 0.035, "seed": 9},
                "pictures": [pic], "cards": tapes, "strokes": strokes, "text": text,
                "badges": self.ptags(0.735, 0.62, 104, typ["hand"], pal["sage_ink"])}

    def pt_book(self, name, _):
        """A storybook cover: the friends through an arched window on sage cloth, the opening line as the book's title.
        Every character and what it holds fits inside the arch, clear of its rounded top (the first try cut the
        salamander's head and leaf off at the curve)."""
        pal, typ = self.pt()
        pets = [g for g, _, _ in self.cast_in_picture()] or [g for g in self.f.regions() if g["kind"] == "pet"]
        u = union([self.with_held(g) for g in pets]) if pets else [0.2, 0.3, 0.8, 0.9]
        w, h, cx, cy = int(0.58 * W), int(0.66 * H), 0.5, 0.405
        r = int(0.3 * w)
        # inside the arch: 4% in from the sides, below the curve there (at 92% of the half-width it is 0.61 r down)
        sx0, sx1 = 0.04 * w, 0.96 * w
        sy0, sy1 = 0.61 * r + 0.02 * h, 0.97 * h
        aspect = w / h
        rw = max((u[2] - u[0]) * W * w / (sx1 - sx0), (u[3] - u[1]) * H * w / (sy1 - sy0))
        rw = min(rw, W, H * aspect)
        zoom = round(W / rw, 3)
        rh = rw / aspect
        s = w / rw
        # the crop's top-left so the group's box lands in the safe area's middle
        gx0 = (u[0] + u[2]) / 2 * W - ((sx0 + sx1) / 2) / s
        gy0 = (u[1] + u[3]) / 2 * H - ((sy0 + sy1) / 2) / s
        gx0, gy0 = min(max(gx0, 0), W - rw), min(max(gy0, 0), H - rh)
        center = [round((gx0 + rw / 2) / W, 4), round((gy0 + rh / 2) / H, 4)]
        pic = {"zoom": zoom, "center": center, "x": cx, "y": cy, "w": w, "h": h, "arch": r,
               "rules": [{"offset": 22, "width": 7, "color": pal["cream"], "alpha": 0.95},
                         {"offset": 44, "width": 2, "color": pal["ink"], "alpha": 0.4}],
               "shadow": {"alpha": 0.25, "blur": 24, "off": [0, 14]}}
        words = self.intro_words()
        t1 = self.safe(" ".join(x[0].upper() + x[1:] if x.lower() not in ("a", "the", "of", "and", "with", "to", "in") else x
                                for x in words[0].split()), typ["book"])
        t2 = self.safe(words[1] if len(words) > 1 else self.long, typ["label"])
        s1 = self.fit(t1, typ["book"], "ink", 230, 0.78)
        it1 = {"text": t1, "font": typ["book"], "size": s1, "x": 0.5, "y": 0.855, "style": "ink", "fill": "#2c3527", "weight": 600}
        it2 = {"text": t2, "font": typ["label"], "size": self.fit(t2, typ["label"], "ink", 92, 0.6), "x": 0.5,
               "y": round(min(float(self.box(it1)[3]) + 0.045, 0.955), 3), "style": "ink", "fill": "#4d5a40"}
        self.notes.append(f"{name}: an arched window (zoom {zoom}) on sage cloth, {t1!r} / {t2!r}")
        return {"name": name, "frame": self.frame, "page": {"color": pal["cloth"], "color2": pal["cloth2"], "grain": 0.05,
                                                             "mottle": 0.03, "seed": 5},
                "pictures": [pic], "text": [it1, it2], "badges": self.ptags(0.03, 0.08, 96, typ["hand"], "#6f7f5e")}

    def pt_specimen(self, name, subj):
        """One creature close up, a museum specimen label beside it: its species, its scientific name and where it was seen."""
        pal, typ = self.pt()
        found = next(((g, sp, sci) for g, sp, sci in self.cast_in_picture() if g["name"] == subj["name"]), None)
        if found is None:
            return None
        g, sp, sci = found
        b = list(g["bbox"])
        for o in self.f.regions():                                        # what it holds (a lantern) comes into the shot
            if o["kind"] in ("lantern", "lamp") and overlap(o["bbox"], [b[0] - 0.05, b[1] - 0.05, b[2] + 0.08, b[3] + 0.05]) > 0.3:
                b = union([b, o["bbox"]])
        bw, bh = b[2] - b[0], b[3] - b[1]
        zoom = round(min(max(min(0.4 / bw, 0.78 / bh), 1.4), 3.2), 3)
        c = 1 / zoom
        center = [round(min(max(b[0] + bw / 2 - 0.2 * c, c / 2), 1 - c / 2), 4), round(min(max(b[1] + bh / 2, c / 2), 1 - c / 2), 4)]
        rect = crop_rect(zoom, center)
        cw, chh = 1340, 740
        clear = self.keep_clear(rect)
        hb = to_crop(b, rect)
        best = None
        for cx in (0.2, 0.26, 0.74, 0.8):                             # the card hides no character, nor what one holds
            for cy in (0.5, 0.42, 0.36, 0.3, 0.25, 0.21, 0.64, 0.75):
                cb = [cx - cw / W / 2 - 0.01, cy - chh / H / 2 - 0.015, cx + cw / W / 2 + 0.01, cy + chh / H / 2 + 0.015]
                if cb[0] < 0.01 or cb[2] > 0.99 or cb[1] < 0.02 or cb[3] > 0.98:
                    continue
                hide = max([overlap(k, cb) for k in clear] + [0])
                # the labeled creature's side of the frame reads best: the card on the open side of it, level with its head
                side = 0.0 if (cx < 0.5) == ((hb[0] + hb[2]) / 2 > 0.5) else 0.3
                score = 8 * hide + side + 0.4 * abs(cy - 0.4)
                if best is None or score < best[0]:
                    best = (score, cx, cy)
        _, cx, cy = best
        lines = [{"text": self.safe(sp[0].upper() + sp[1:], typ["plate"]), "font": typ["plate"], "x": 0.5, "y": 0.25, "style": "ink",
                  "fill": pal["ink"]},
                 {"text": self.safe(sci, typ["label"]), "font": typ["label"], "x": 0.5, "y": 0.44, "style": "ink", "fill": pal["sage_ink"]},
                 {"text": self.safe(f"seen at the {self.w['name']}", typ["hand"]), "font": typ["hand"], "x": 0.5, "y": 0.64,
                  "style": "ink", "fill": pal["ink"]},
                 {"text": f"4K  {self.hr}", "font": typ["plate"], "x": 0.5, "y": 0.84, "style": "ink", "fill": "#7a6a55"}]
        for ln, sz in zip(lines, (112, 84, 96, 70)):
            ln["size"] = self.fit(ln["text"], ln["font"], "ink", sz, 0.84 * cw / W)
        card = {"x": cx, "y": cy, "w": cw, "h": chh, "rotate": -2, "fill": "#f6eedb", "fill2": "#eee2c9", "grain": 0.035,
                "radius": 6, "border": pal["ink"], "border_w": 5, "shadow": {"alpha": 0.55, "blur": 26, "off": [12, 20]}, "lines": lines}
        hid = max([overlap(k, [cx - cw / W / 2, cy - chh / H / 2, cx + cw / W / 2, cy + chh / H / 2]) for k in clear] + [0])
        self.notes.append(f"{name}: the {sp} close up (zoom {zoom}) with a specimen label at ({cx}, {cy}), hiding {hid:.0%} "
                          "of a character at most")
        return {"name": name, "frame": self.frame, "zoom": zoom, "center": center, "cards": [card], "badges": []}

    def pt_note(self, name, subj):
        """The hero close up and a handwritten line on a pastel wash (the words' note)."""
        pal, typ = self.pt()
        v = self.note(name, subj)
        it = dict(v["text"][0])
        it.update(font=typ["hand"], style="ink", fill=pal["ink"], text=self.safe(self.w["note"], typ["hand"]))
        it["size"] = self.fit(it["text"], typ["hand"], "ink", 210, 0.62)
        b = self.box(it)
        v.pop("scrims", None)
        v["text"] = [it]
        v["washes"] = [{"x": round((b[0] + b[2]) / 2, 4), "y": round((b[1] + b[3]) / 2, 4), "w": int((b[2] - b[0] + 0.07) * W),
                        "h": int((b[3] - b[1] + 0.09) * H), "color": pal["butter"], "alpha": 0.94, "rim": 0.2, "seed": 41}]
        v["badges"] = self.ptags(0.035, 0.08, 110, typ["hand"])
        return v

    def build(self):
        variants = []
        for name, kind, arg in self.p["concepts"]:
            v = getattr(self, kind)(name, arg)
            if v:
                variants.append(v)
        names = [v["name"] for v in variants]
        trio = [n for n in self.p["trio"] if n in names]
        trio += [n for n in names if n not in trio][:3 - len(trio)]
        th = self.f.look.get("thumb") or {}
        look = ("The others are pixel concepts too (a pixel look)." if self.p["pixel_look"] else
                f"Then concepts in the look's fonts ({', '.join(th.get('fonts', []))}) and motifs, and more pixel options last.")
        first = (f"First and suggested: {names[0]}, the channel's pixel concept Truman picked on both published videos "
                 f"(a big {self.p['hero']['name'].replace('_', ' ')} with the place name and the music tag). {look} ")
        if th.get("painterly"):
            first = (f"A look painted by hand: painterly concepts only, each its own medium in pastel paper colors and with "
                     f"its own words, no pixel letters (Truman 2026-10-26, L160). First and suggested: {names[0]}. ")
        note = (f"Made by tools/finish_video.py on {dt.date.today().isoformat()}. Frame {self.frame}: {self.p['frame_why']}. "
                f"{first}"
                "Every one says 4K and the length. Text colors and shades were chosen against what's behind each line "
                "(lessons L65). Edit freely: the tool never overwrites this spec.")
        return {"_note": note,
                "_finish": {"suggested": names[0], "test_and_compare": trio[:3], "frame": self.frame, "hero": self.p["hero"]["name"],
                            "measured": self.notes},
                "scene": f"scenes/{self.f.scene}", "out": f"out/{self.f.scene}/thumbnails{self.f.sfx}",
                "badges": [{"x": 0.04, "y": 0.085, "px": 21, "gap": 3,
                            "items": [{"text": "4K", "style": "chip"}, {"text": self.hr, "style": "chip"}]}],
                "variants": variants}
