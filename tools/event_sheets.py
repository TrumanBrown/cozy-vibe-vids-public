"""Contact sheets of every event in a render, cropped to where it happens, for review without watching.

For each event in the render's timeline (birds, the critter, the ant, neon flickers, lantern gutters, gust
flurries, windows, boats, cars, lightning...) it extracts frames across the event from the master and crops them
to the region it plays in (the bird band, the critter's or ant's path, the sign...). Steam sources and water
regions get sheets too (they run all the time), plus an x-t strip of each water region so a current shows as
slanted streaks (still water = vertical lines). One JPEG per kind in <render>/review/, and an index.md.

Usage (repo root):
  .venv/Scripts/python tools/event_sheets.py out/<scene>/render/<tag> [--max 6] [--kinds petact,birds]
"""
import argparse
import json
import pathlib

import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT
from cozy.media import grab_frame, probe as media_probe
W, H = 3840, 2160
CELL = 420


def probe_start(render):
    rj = json.loads((render / "render.json").read_text(encoding="utf-8")) if (render / "render.json").exists() else {}
    return float(rj.get("from", 0) or 0), rj


def frame(video, t, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    raw = grab_frame(video, f"{max(0.0, t):.3f}", frames=1, vf=f"format=rgb24,crop={w}:{h}:{x0}:{y0}", pix_fmt="rgb24", check=False)
    if len(raw) != w * h * 3:
        return Image.new("RGB", (w, h))
    return Image.fromarray(np.frombuffer(raw, np.uint8).reshape(h, w, 3))


def px_box(b, grow=0.0, min_w=0.12, aspect=16 / 9):
    """0..1 bbox -> 4K px box grown by `grow` of its size, at least min_w of the frame wide, roughly 16:9-ish."""
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) / 2 * W, (y0 + y1) / 2 * H
    w = max((x1 - x0) * W * (1 + grow), min_w * W)
    h = max((y1 - y0) * H * (1 + grow), w / aspect * 0.6)
    w, h = min(w, W), min(h, H)
    X0, Y0 = int(min(max(0, cx - w / 2), W - w)), int(min(max(0, cy - h / 2), H - h))
    return [X0, Y0, X0 + int(w) // 2 * 2, Y0 + int(h) // 2 * 2]


def sheet(rows, out, title):
    """rows: [(label, [(caption, PIL image)])] -> one JPEG, each row a strip of cells."""
    if not rows:
        return None
    cw = CELL
    cells = []
    for label, ims in rows:
        line = []
        for cap, im in ims:
            s = cw / im.width
            line.append((cap, im.resize((cw, max(1, round(im.height * s))), Image.LANCZOS)))
        cells.append((label, line))
    ncol = max(len(line) for _, line in cells)
    rh = [max(im.height for _, im in line) + 22 for _, line in cells]
    img = Image.new("RGB", (ncol * (cw + 4) + 4, sum(rh) + 30), (20, 20, 20))
    d = ImageDraw.Draw(img)
    d.text((6, 6), title, fill=(255, 255, 255))
    y = 30
    for (label, line), h in zip(cells, rh):
        d.text((6, y), label, fill=(255, 220, 0))
        for i, (cap, im) in enumerate(line):
            img.paste(im, (4 + i * (cw + 4), y + 18))
            d.text((8 + i * (cw + 4), y + 20), cap, fill=(255, 255, 0))
        y += h
    img.save(out, quality=88)
    return out


def plan(render, only=(), max_n=6):
    """Where and when each event of a render plays, without extracting anything: returns ({kind: (count,
    [(label, [(caption, t in the master, 4K px box)])])}, ctx) with ctx = (video, t0, t1, spec, regs, plate, dur).
    tools/critic.py uses it to cut the same evidence at full size."""
    render = pathlib.Path(render)
    video = render / "master.mp4"
    t0, rj = probe_start(render)
    tl = json.loads((render / "timeline.json").read_text(encoding="utf-8"))
    scene = tl.get("scene") or rj.get("scene") or render.parent.parent.name
    sd = ROOT / "scenes" / scene
    spec = json.loads((sd / "scene.json").read_text(encoding="utf-8")) if (sd / "scene.json").exists() else {}
    plate = spec.get("plate", scene)
    regs = json.loads((ROOT / "out" / "plates" / plate / "regions.json").read_text(encoding="utf-8"))
    dur = float(media_probe(video, "format=duration", check=False).get("format", {}).get("duration") or 0)
    t1 = t0 + dur
    only = set(k for k in only if k)
    of = lambda kind: [g for g in regs if g["kind"] == kind]   # noqa: E731
    union = lambda gs: [min(g["bbox"][0] for g in gs), min(g["bbox"][1] for g in gs), max(g["bbox"][2] for g in gs), max(g["bbox"][3] for g in gs)]  # noqa: E731
    ev_spec = spec.get("events", {})
    critters = {int(L.get("track", 0)): L for L in spec.get("layers", []) if L.get("type") == "critter"}
    ant = next((L for L in spec.get("layers", []) if L.get("type") == "ant"), None)
    perch = next((L for L in spec.get("layers", []) if L.get("type") == "perch"), None)

    def where(e):
        k = e["type"]
        if k == "petact" and of("pet"):
            return px_box(union(of("pet")), grow=0.9)
        if k == "birds":
            b = (ev_spec.get("birds") or {}).get("band") or [0, 0, 1, 0.45]
            return px_box(b, grow=0.15, min_w=0.3)
        # each critter event on its own track's path (the greenhouse's ladybug row showed the snail's aisle, 2026-10-21)
        critter = critters.get(int(e.get("track", 0))) if k == "critter" else None
        if critter:
            xs = [p[0] for p in critter["path"]]
            ys = [p[1] for p in critter["path"]]
            return px_box([min(xs), min(ys), max(xs), max(ys)], grow=0.5, min_w=0.16)
        if k == "ant" and ant and ant.get("paths"):
            pts = ant["paths"][int(e.get("path", 0)) % len(ant["paths"])]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return px_box([min(xs), min(ys), max(xs), max(ys)], grow=0.15, min_w=0.12)
        if k == "perch" and perch and perch.get("perches"):
            pts = perch["perches"][int(e.get("perch", 0)) % len(perch["perches"])]["pts"]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return px_box([min(xs), min(ys) - 0.03, max(xs), max(ys) + 0.01], grow=0.3, min_w=0.1)
        if k == "neon" and of("neon"):
            g = next((g for g in of("neon") if g["name"] == e.get("name")), None)
            return px_box((g or {"bbox": union(of("neon"))})["bbox"], grow=0.8)
        if k in ("gutter", "lantern") and (of("lantern") or of("candle")):
            gs = of("lantern") + of("candle")
            g = next((g for g in gs if g["name"] == e.get("name")), None)
            return px_box((g or {"bbox": union(gs)})["bbox"], grow=1.5)
        return [0, 0, W, H]

    kinds = {}
    for e in tl.get("events", []):
        # events under way when the window starts count too (a snail that set off in the loop's previous period)
        if e["t"] < t1 and e["t"] + float(e.get("dur", 0) or 0) > t0 and (not only or e["type"] in only):
            kinds.setdefault(e["type"], []).append(e)
    out = {}
    for k, evs in sorted(kinds.items()):
        rows = []
        for e in evs[:max_n]:
            box = where(e)
            d = max(float(e.get("dur", 2.0)), 0.6)
            n = 7 if k == "petact" else 6
            ts = [e["t"] + d * i / (n - 1) for i in range(n)]
            if k == "petact":     # before, rising, at rest, holding, lying back down, after
                ts = [e["t"] - 0.5, e["t"] + 0.35 * (d - e.get("hold", 0)) / 2, e["t"] + (d - e.get("hold", 0)) / 2,
                      e["t"] + d / 2, e["t"] + d - (d - e.get("hold", 0)) / 2, e["t"] + d - 0.4, e["t"] + d + 0.5]
            if k == "perch" and e.get("members"):   # the first bird: flying in, just landed, sitting, taking off, gone
                m = e["members"][0]
                tl_, tv = e["t"] + m["land"] + m["inT"], e["t"] + m["leave"]
                ts = [tl_ - 0.5 * m["inT"], tl_ + 0.15, tl_ + 8, 0.5 * (tl_ + tv), tv + 0.25, tv + 0.9]
            cells = [(f"{tt:.1f}s", tt - t0, box) for tt in ts if t0 <= tt < t1]
            extra = {kk: v for kk, v in e.items() if kk in ("act", "name", "hold", "n", "amp")}
            rows.append((f"{k} at {e['t']:.1f}s for {d:.1f}s {extra if extra else ''}", cells, e))
        out[k] = (len(evs), rows)
    return out, (video, t0, t1, spec, regs, plate, dur)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("render")
    ap.add_argument("--max", type=int, default=6, help="events per kind")
    ap.add_argument("--kinds", default="", help="only these event kinds (comma list)")
    a = ap.parse_args()
    render = pathlib.Path(a.render)
    plans, (video, t0, t1, spec, regs, plate, dur) = plan(render, a.kinds.split(","), a.max)
    outd = render / "review"
    outd.mkdir(exist_ok=True)
    of = lambda kind: [g for g in regs if g["kind"] == kind]   # noqa: E731
    lines = [f"# Event sheets: {render}", "", f"{spec.get('scene') or render.parent.parent.name}, {t0:.0f}-{t1:.0f} s of the timeline", ""]
    for k, (count, prow) in sorted(plans.items()):
        rows = [(label, [(cap, frame(video, tv, box)) for cap, tv, box in cells]) for label, cells, _e in prow]
        p = sheet(rows, outd / f"{k}.jpg", f"{k}: {count} in this render (first {min(count, a.max)} shown)")
        if p:
            lines.append(f"- {k}: {count} events, [{p.name}]({p.name})")
            print(f"{k}: {count} -> {p}")
    # always-on motion: steam sources and water regions
    mid = t0 + dur / 2
    rows = []
    for g in of("steam"):
        box = px_box([g["bbox"][0], g["bbox"][1] - 0.6 * (g["bbox"][3] - g["bbox"][1]), g["bbox"][2], g["bbox"][1] + 0.3 * (g["bbox"][3] - g["bbox"][1])], grow=0.2)
        rows.append((f"steam {g['name']}", [(f"{t:.1f}s", frame(video, t - t0, box)) for t in np.linspace(mid, mid + 4, 6)]))
    for g in of("water"):
        box = px_box(g["bbox"], grow=0.3)
        rows.append((f"water {g['name']}", [(f"{t:.1f}s", frame(video, t - t0, box)) for t in np.linspace(mid, mid + 2, 4)]))
        # x-t strip (every frame, one row, 1:1) through the row with the most water: a current leaves slanted
        # streaks, still water and things in front of it (railing bars) vertical lines. Downscaled, the slant of a
        # far canal's few px/s disappears, so the strip is also saved at full size.
        rm = np.asarray(Image.open(ROOT / "out" / "plates" / plate / "regions.png").convert("RGB"), np.uint8)
        wm = (rm[..., 0] == g["id"]) & (rm[..., 1] > 128)
        if not wm.any():
            continue
        yc = int(np.argmax(wm.sum(1)))
        xs = np.flatnonzero(wm[yc])
        x0, x1 = int(xs.min()) // 2 * 2, min(W, (int(xs.max()) + 2) // 2 * 2)
        raw = grab_frame(video, f"{mid - t0:.2f}", t="4", vf=f"crop={x1 - x0}:2:{x0}:{yc // 2 * 2},format=rgb24", pix_fmt="rgb24",
                         check=False)
        v = np.frombuffer(raw, np.uint8)
        if v.size:
            v = v.reshape(-1, 2, x1 - x0, 3)[:, yc % 2]
            xt = Image.fromarray(np.repeat(v, 2, 0))
            xp = outd / f"water_{g['name']}_xt.png"
            xt.save(xp)
            lines.append(f"- water {g['name']}: x-t strip at full size (row {yc}, x {x0}-{x1}, 4 s down): [{xp.name}]({xp.name})")
            rows.append((f"water {g['name']}: x (across) over 4 s (down); slanted streaks = moving ({xp.name} at full size)", [("x-t", xt)]))
    p = sheet(rows, outd / "always_on.jpg", "steam and water (always on)")
    if p:
        lines.append(f"- steam and water: [{p.name}]({p.name})")
        print(f"always on -> {p}")
    (outd / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"index: {outd / 'index.md'}")


if __name__ == "__main__":
    main()
