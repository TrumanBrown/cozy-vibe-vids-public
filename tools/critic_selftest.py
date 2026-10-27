"""Calibration of tools/critic.py: does the vision judge pass what Truman approved and fail what he flagged?

Positives are the approved reference crops (assets/reference/approved/<scene>/, cut from a published video).
Negatives are the same crops with the failures he flagged drawn in: a steam box with a hard edge (L12, L32),
steam as a few separate wisps (L18, L35), rain on the pet (L19), a dry box between the stool's legs (L24), a
missing opening line (L55), rain over a door's frame and handle (L92), rain over the leaves of the plants in front of
a window (L100); and the key art: the published ramen key art passes, a key art with a painted snail fails (L71). Each is judged exactly as critic.py judges a render (same rubric,
same reference).
Run it after changing the critic's wording, the vision model or the references; it should score 100%.

  .venv\\Scripts\\python tools\\critic_selftest.py [--refs assets\\reference\\approved\\ramen-alley]

Writes out/critic_selftest/ (the test images and report.md). About $0.10 per run.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from cozy.paths import ROOT
import critic  # noqa: E402

OUT = ROOT / "out" / "critic_selftest"


def panels(im, n):
    """Split a horizontal strip of n equal panels (with 6 px gaps) into their boxes."""
    w = (im.width - 6 * (n - 1)) // n
    return [(i * (w + 6), 0, i * (w + 6) + w, im.height) for i in range(n)]


def draw_box_steam(im, n):
    im = im.copy()
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for x0, y0, x1, y1 in panels(im, n):
        w, h = x1 - x0, y1 - y0
        d.rectangle((x0 + 0.2 * w, y0 + 0.08 * h, x0 + 0.8 * w, y0 + 0.55 * h), fill=(235, 235, 235, 95))
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


def draw_wisps(im, n):
    im = im.copy()
    ov = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(ov)
    for x0, y0, x1, y1 in panels(im, n):
        w, h = x1 - x0, y1 - y0
        for k, fx in enumerate((0.3, 0.5, 0.68)):
            pts = [(x0 + fx * w + 0.02 * w * np.sin(j / 3 + k), y0 + h * (0.6 - 0.5 * j / 20)) for j in range(21)]
            d.line(pts, fill=255, width=max(3, w // 80))
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    white = Image.new("RGB", im.size, (240, 240, 240))
    return Image.composite(white, im, ov.point(lambda v: int(v * 0.8)))


def draw_rain_on_pet(im, n):
    im = im.copy()
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(3)
    for x0, y0, x1, y1 in panels(im, n):
        w, h = x1 - x0, y1 - y0
        for _ in range(70):
            x, y = x0 + rng.uniform(0.15, 0.85) * w, y0 + rng.uniform(0.1, 0.8) * h
            d.line((x, y, x - 0.02 * w, y + 0.09 * h), fill=(225, 230, 240), width=2)
    return im


def draw_dry_box(im, n):
    im = im.copy()
    for x0, y0, x1, y1 in panels(im, n):
        w, h = x1 - x0, y1 - y0
        box = (int(x0 + 0.25 * w), int(y0 + 0.45 * h), int(x0 + 0.75 * w), int(y0 + 0.95 * h))
        patch = im.crop(box).filter(ImageFilter.GaussianBlur(18))
        im.paste(patch, box[:2])
    return im


def draw_rain_on_frames(im, n):
    """Rain streaks over a door's dark wooden frame and its handle (L92: the pixel greenhouse's door, 2026-10-21)."""
    im = im.copy()
    a = np.asarray(im, np.float32) / 255
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    frame = (lum < 0.2) & (a[..., 0] >= a[..., 2])
    frame[:24] = False                      # the panels' labels
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(5)
    for x0, y0, x1, y1 in panels(im, n):
        ys, xs = np.nonzero(frame[y0:y1, x0:x1])
        if not len(xs):
            continue
        for k in rng.choice(len(xs), min(len(xs), 90), replace=False):
            x, y = x0 + xs[k], y0 + ys[k]
            d.line((x, y, x, y + 0.035 * (y1 - y0)), fill=(205, 215, 240), width=3)
    return im


def draw_rain_on_leaves(im, n):
    """Rain streaks over the leaves of the plants standing in front of the glass (L100: the pixel greenhouse's plants by
    the lantern and the potted plant left of it, v6, 2026-10-21)."""
    im = im.copy()
    a = np.asarray(im, np.float32) / 255
    leaf = (a[..., 1] > a[..., 2] + 0.06) & (a[..., 1] >= 0.8 * a[..., 0]) & (a.max(-1) > 0.18)
    leaf[:24] = False                       # the panels' labels
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(7)
    for x0, y0, x1, y1 in panels(im, n):
        ys, xs = np.nonzero(leaf[y0:y1, x0:x1])
        if not len(xs):
            continue
        for k in rng.choice(len(xs), min(len(xs), 110), replace=False):
            x, y = x0 + xs[k], y0 + ys[k]
            d.line((x, y, x, y + 0.035 * (y1 - y0)), fill=(205, 215, 240), width=3)
    return im


def no_title(refs):
    full = Image.open(refs / "full_frame_strike.jpg").convert("RGB")
    W, H = full.size
    return full.crop((int(0.26 * W), int(0.84 * H), int(0.80 * W), int(0.98 * H))).resize((1000, 260))


def opening_strip(refs, with_title):
    """The shape of critic.py's opening evidence: the line at 1:1 over its first seconds, then gone."""
    t = Image.open(refs / "intro_title.jpg").convert("RGB").resize((760, 111))
    g = no_title(refs).resize((760, 111))
    return critic.strip([t, t, t, g] if with_title else [g, g, g, g],
                        ["3.2 s, 1:1", "6.1 s, 1:1", "8.9 s, 1:1", "12.3 s, 1:1"], max_w=760)


def opening_center_cases(refs):
    """The opening line in the middle of the screen (the pixel greenhouse's v6: the critic's own crops and full frame,
    fixtures in assets/reference/selftest/) passes; the same line low and right of center, where v5 put it before Truman
    asked for it centered (L97), fails."""
    d = ROOT / "assets" / "reference" / "selftest"
    need = ["opening_center_crops.jpg", "opening_center_full.jpg", "opening_none_full.jpg", "opening_block.png"]
    if not all((d / n).exists() for n in need):
        return []
    crops = Image.open(d / "opening_center_crops.jpg").convert("RGB")
    full = Image.open(d / "opening_center_full.jpg").convert("RGB")
    low = Image.open(d / "opening_none_full.jpg").convert("RGBA")
    blk = Image.open(d / "opening_block.png").convert("RGBA")
    s = low.width / 3840
    blk = blk.resize((round(blk.width * s), round(blk.height * s)), Image.LANCZOS)
    low.alpha_composite(blk, (round(0.63 * low.width - blk.width / 2), round(0.93 * low.height - blk.height / 2)))
    return [("opening_ok", "opening", "the opening line", [crops, full], None, True),
            ("opening_low", "opening", "the opening line", [crops, low.convert("RGB")], None, False)]


def frames_cases():
    """A door seen at 1:1 with its frame and handle dry (the pixel greenhouse's v6, checked by eye; a fixture in
    assets/reference/selftest/) passes; the same with rain streaks over the frame and handle fails (L92). The panes by
    the lantern with their plants dry (v7) pass; the same with rain over the leaves fails (L100)."""
    d = ROOT / "assets" / "reference" / "selftest"
    out = []
    if (d / "frames_door.jpg").exists():
        im = Image.open(d / "frames_door.jpg").convert("RGB")
        label = "rain at the frames of back door glass"
        out += [("frames_ok", "frames", label, im, None, True),
                ("frames_wet", "frames", label, draw_rain_on_frames(im, 2), None, False)]
    if (d / "frames_lamp.jpg").exists():
        im = Image.open(d / "frames_lamp.jpg").convert("RGB")
        label = "rain at the glass and what stands in front of it (upper middle, left)"
        out += [("frames_lamp_ok", "frames", label, im, None, True),
                ("frames_lamp_wet", "frames", label, draw_rain_on_leaves(im, 2), None, False)]
    return out


def keyart_cases():
    """The published ramen key art (passes), and the farm porch's cleaned key art with the snail its first draft painted
    pasted back in (fails: L71), both as critic.py's keyart evidence (the image at 1600 px)."""
    ka = ROOT / "assets" / "keyart"
    good = ka / "ramen-alley" / "clean.png"
    farm = ka / "real-life-farmscape"
    raw = next(iter(sorted(farm.glob("hero_*_4.png"))), None) if farm.exists() else None
    out = []
    if good.exists():
        im = Image.open(good).convert("RGB")
        im.thumbnail((1600, 1600))
        out.append(("keyart_ok", "keyart", "key art", im, None, True))
    if raw is not None and (farm / "clean.png").exists():
        clean, orig = Image.open(farm / "clean.png").convert("RGB"), Image.open(raw).convert("RGB").resize(Image.open(farm / "clean.png").size)
        W, H = clean.size
        box = (int(0.205 * W), int(0.778 * H), int(0.285 * W), int(0.878 * H))
        clean.paste(orig.crop(box), box[:2])
        clean.thumbnail((1600, 1600))
        out.append(("keyart_creature", "keyart", "key art", clean, None, False))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", default=str(critic.REFS))
    a = ap.parse_args()
    refs = pathlib.Path(a.refs)
    critic.REFS = refs
    OUT.mkdir(parents=True, exist_ok=True)
    idx = json.loads((refs / "index.json").read_text(encoding="utf-8"))["refs"]
    n_of = lambda name: len(idx[name]["video_times_s"])          # noqa: E731
    img = lambda name: Image.open(refs / f"{name}.jpg").convert("RGB")   # noqa: E731
    cases = [  # (name, check, label, candidate image, reference, expected pass)
        ("steam_ok", "steam", "steam over ramen bowl", img("steam_bowl"), None, True),
        ("steam_cup_ok", "steam", "steam over tea cup", img("steam_cup"), None, True),
        ("steam_box", "steam", "steam over ramen bowl", draw_box_steam(img("steam_bowl"), n_of("steam_bowl")), refs / "steam_bowl.jpg", False),
        ("steam_wisps", "steam", "steam over ramen bowl", draw_wisps(img("steam_bowl"), n_of("steam_bowl")), refs / "steam_bowl.jpg", False),
        ("pet_ok", "pet", "the pet (sleeping cat)", img("pet_dry"), None, True),
        ("pet_rain", "pet", "the pet (sleeping cat)", draw_rain_on_pet(img("pet_dry"), n_of("pet_dry")), refs / "pet_dry.jpg", False),
        ("gaps_ok", "gaps", "the gaps of a near object (1)", img("stool_gaps_rain"), None, True),
        ("gaps_dry", "gaps", "the gaps of a near object (1)", draw_dry_box(img("stool_gaps_rain"), n_of("stool_gaps_rain")), refs / "stool_gaps_rain.jpg", False),
        ("opening_missing", "opening", "the opening line", opening_strip(refs, False), refs / "intro_title.jpg", False),
    ] + opening_center_cases(refs) + frames_cases() + keyart_cases()
    rows, right, usd = [], 0, 0.0
    for name, check, label, im, ref, want in cases:
        ps = []
        for k, x in enumerate(im if isinstance(im, list) else [im]):
            p = OUT / (f"{name}.jpg" if k == 0 else f"{name}_{k}.jpg")
            x.save(p, quality=88)
            ps.append(p)
        res, cost, _votes = critic.verdict(label, ps, ref, check, critic.CHECKS[check][1], "selftest")
        usd += cost
        got = bool(res.get("pass")) and (res.get("confidence") or 0) >= 0.5 if want else not res.get("pass")
        right += got
        rows.append(f"| {'ok' if got else 'WRONG'} | {name} | expected {'pass' if want else 'fail'} | "
                    f"{'pass' if res.get('pass') else 'fail'} {res.get('confidence')} | {'; '.join(res.get('problems') or []) or res.get('seen', '')} |")
        print(f"  {'ok   ' if got else 'WRONG'} {name:16s} expected {'pass' if want else 'fail'}, got {'pass' if res.get('pass') else 'fail'} ({res.get('confidence')})")
    md = [f"# Critic self-test: {right}/{len(cases)} right, ~${usd:.2f}", "", "| | Case | Expected | Got | What it said |", "|---|---|---|---|---|", *rows]
    (OUT / "report.md").write_text("\n".join(md).replace("\u2014", ",") + "\n", encoding="utf-8")
    print(f"\nself-test: {right}/{len(cases)} right, ~${usd:.2f} -> {OUT / 'report.md'}")
    return 0 if right == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
