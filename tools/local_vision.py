"""A local vision model next to Azure: start and stop it, and measure it against Azure's answers.

Truman, 2026-10-22, after the Minecraft tea house's outdoor check spent $4.59 of the run's $6.01 in 166 Azure vision
calls, asked whether vision calls could run on local models. He chose to install and test first and see the
comparison (below), then decided: the local model for first passes to save cost, Azure for the final check.
config/local_vision.json names the server (llama.cpp's llama-server, MIT), the models (Qwen3.5-9B active, Qwen3-VL 8B;
Apache-2.0, Q4_K_M with their F16 vision projectors) and the checks that screen with it first (first_pass:
tools/outdoor_check.py --repair, Azure confirming its flags and looking last); tools/azure_ai.py chat() takes a backend.

  .venv\\Scripts\\python tools\\local_vision.py [--model <name>] serve       start the server (the model goes on the GPU), wait for it
  .venv\\Scripts\\python tools\\local_vision.py stop                        stop it (frees the GPU for renders)
  .venv\\Scripts\\python tools\\local_vision.py status
  .venv\\Scripts\\python tools\\local_vision.py [--model <name>] ask <image> "question"
  .venv\\Scripts\\python tools\\local_vision.py [--model <name>] compare [--scenes a,b] [--cuts 10]

--model picks one of config/local_vision.json "models" (default: its "active" one). compare runs
tools/outdoor_check.py's own evidence and judging (the same prompt, the same vote of up to three asks) with the local
model, on cases whose right answer is known, without any Azure call:
  clean    every tile of each scene's current weather area: the check passed on them with Azure, and Truman's eye
           after it (Azure's cached answers for the same tiles are counted next to the local ones);
  cut-in   each indoor thing the outdoor check cut out of the weather (hand.json outdoor_cuts: a beam, the porch
           floor, plants, a frame), put back under the weather in a tile around it: the model must flag it, and its
           box should land on it;
  cut-out  the check's false cuts, put back the same way: on the Minecraft tea house it cut the rain in front of the
           buildings across the garden (2026-10-22); a model is right to call them outside;
  self     outdoor_check.py's own fixtures: the greenhouse's v6 lantern tile and its indoor trough must be flagged, the
           fixed v7 lantern tile and the tea house's pavilion across the pond (L121) must pass.
Which cut is which: assets/reference/selftest/outdoor_cut_labels.json (by eye; a cut without a label is shown, not
scored). Writes out/local_vision/compare_<model>.json, compare_<model>.md (the numbers) and compare_<model>_sheet.jpg
(every case it got wrong: its boxes in red, the cut thing's box in yellow). It starts the server when it isn't running
and stops it again after. Run it with the GPU free (no render): the server holds about 10 GB.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from cozy.paths import ROOT
from cozy.llama import OUT, cfg, loaded, model, serve, stop, up
import outdoor_check as oc
LABELS = ROOT / "assets" / "reference" / "selftest" / "outdoor_cut_labels.json"


def gpu_mem():
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True)
    try:
        used, total = (int(x) for x in r.stdout.strip().split(","))
        return used, total
    except ValueError:
        return None, None


def ask(image, question):
    os.environ["COZY_VISION"] = "local"
    from azure_ai import chat
    started = serve()
    try:
        text, usage = chat([{"role": "user", "content": [question, {"image": image}]}], purpose="local_vision:ask")
        print(text)
        print(f"[{usage.get('prompt_tokens')} in, {usage.get('completion_tokens')} out]")
    finally:
        if started:
            stop()
    return 0


# ---------------------------------------------------------------- the comparison

def judge(oc, plain, tint_im, ctx_im, pats, min_conf):
    """outdoor_check.check()'s vote: up to three asks, a tile fails when two of them find something."""
    asks, secs, errors, err = [], [], 0, ""
    while errors < 2:
        k = sum(1 for x in asks if oc.hits(x, min_conf))
        if asks and (k == 0 or k >= 2 or len(asks) - k >= 2):
            break
        t0 = time.time()
        try:
            ans, _ = oc.ask(plain, tint_im, ctx_im, "outdoor_check:local-compare", "medium", pats)
        except Exception as e:                                   # a bad answer counts against the model, never as a pass
            errors, err = errors + 1, str(e)[:300]
            continue
        secs.append(time.time() - t0)
        asks.append(ans)
    found = [x for x in asks if oc.hits(x, min_conf)]
    flagged = len(found) >= 2 or (len(found) == 1 and len(asks) < 3)
    return {"flagged": flagged, "asks": asks, "found": found, "secs": secs, "errors": errors, "error": err}


def verdict(oc, asks, min_conf):
    if not asks:
        return None
    found = [x for x in asks if oc.hits(x, min_conf)]
    return len(found) >= 2 or (len(found) == 1 and len(asks) < 3)


def frac_box(b, w, h):
    """A model's box as tile pixels: fractions as asked, else 0-1000 (Qwen3-VL's own grounding scale), else pixels.
    Returns (box, scale used)."""
    if not b:
        return None, None
    m = max(abs(v) for v in b)
    if m <= 1.5:
        sx, sy, sc = w, h, "fraction"
    elif m <= 1000:
        sx, sy, sc = w / 1000, h / 1000, "0-1000"
    else:
        sx, sy, sc = 1, 1, "pixels"
    x0, y0, x1, y1 = b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy
    return (int(max(0, min(x0, x1))), int(max(0, min(y0, y1))), int(min(w, max(x0, x1))), int(min(h, max(y0, y1)))), sc


def cases_for(oc, scene, ncuts, min_conf):
    spec, plate_name, pd = oc.load(scene)
    cj = pd / "outdoor_check" / "check.json"
    cache = (json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}).get("cache") or {}
    plate = np.asarray(Image.open(pd / "plate.png").convert("RGB"))
    area, beads = oc.weather_area(spec, pd)
    g = oc.grid(spec, pd)
    H, W = area.shape
    ctx, s = oc.context(plate, area)
    out = []
    for key, box in oc.tiles(area):
        hsh = oc.tile_hash(plate, area, beads, box)
        plain, tint_im, pats = oc.evidence(plate, area, beads, box)
        out.append({"set": "clean", "scene": scene, "id": f"tile {key}", "want": False, "box": list(box),
                    "azure": verdict(oc, (cache.get(hsh) or {}).get("asks"), min_conf),
                    "ev": (plain, tint_im, oc.context_for(ctx, s, box), pats), "thing": None})
    hp = ROOT / "assets" / "keyart" / f"{plate_name}.hand.json"
    cuts = (json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {}).get("outdoor_cuts") or []
    cm = np.zeros((H, W), np.uint8)
    for poly in cuts:
        if len(poly) >= 3:
            cv2.fillPoly(cm, [np.array([[x * W, y * H] for x, y in poly], np.int32)], 1)
    cm = cv2.morphologyEx(cm, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))   # one thing's fragments become one case
    n, lab, st, _ = cv2.connectedComponentsWithStats(cm, 8)
    comps = sorted((i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 1500), key=lambda i: -st[i, cv2.CC_STAT_AREA])
    bw, bh = int(W / oc.GRID * (1 + 2 * oc.MARGIN)), int(H / oc.GRID * (1 + 2 * oc.MARGIN))
    lab_all = json.loads(LABELS.read_text(encoding="utf-8")).get(scene, {}) if LABELS.exists() else {}
    for j, i in enumerate(comps[:ncuts]):
        x, y, w, h = (int(v) for v in st[i, :4])
        cx_, cy_ = x + w // 2, y + h // 2
        side, what = None, ""
        for s_ in ("inside", "outside"):
            for lx, ly, lw in lab_all.get(s_, []):
                if abs(lx - cx_) <= 40 and abs(ly - cy_) <= 40:
                    side, what = s_, lw
        thing = lab == i
        a2 = area | thing
        if g:
            a2 = oc.on_grid(a2, g)
        x0 = int(min(max(0, x + w / 2 - bw / 2), W - bw))
        y0 = int(min(max(0, y + h / 2 - bh / 2), H - bh))
        box = (x0, y0, x0 + bw, y0 + bh)
        ctx2, s2 = oc.context(plate, a2)
        plain, tint_im, pats = oc.evidence(plate, a2, beads, box)
        out.append({"set": {"inside": "cut-in", "outside": "cut-out"}.get(side, "cut-?"), "scene": scene,
                    "id": f"cut {j + 1} at ({cx_}, {cy_}) px" + (f": {what}" if what else ""), "want": side != "outside",
                    "box": list(box), "azure": True, "ev": (plain, tint_im, oc.context_for(ctx2, s2, box), pats),
                    "thing": thing[y0:y0 + bh, x0:x0 + bw]})
    return out


def self_cases(oc):
    out = []
    for name, want in oc.SELFTEST_CASES:
        ps = [oc.SELFTEST / f"{name}_{k}" for k in ("plain.jpg", "area.png", "ctx.jpg")]
        if not all(p.exists() for p in ps):
            continue
        plain = Image.open(ps[0]).convert("RGB")
        m = np.asarray(Image.open(ps[1]).convert("L")) > 127
        pats = oc.patches(m)
        tint_im = Image.fromarray(oc.numbered(oc.tint(np.asarray(plain), m), pats))
        out.append({"set": "self", "scene": "selftest", "id": name, "want": want, "box": None, "azure": want,
                    "ev": (plain, tint_im, Image.open(ps[2]).convert("RGB"), pats), "thing": None})
    return out


def sheet(wrong, path):
    """Every wrong case, its tinted tile with the local model's boxes (red) and the cut thing's box (yellow)."""
    if not wrong:
        return None
    tiles = []
    for c in wrong:
        t = c["ev"][1].copy()
        d = ImageDraw.Draw(t)
        for x in c["found"]:
            for o in x["covered"]:
                if not o.get("outside") and o.get("box"):
                    b, _ = frac_box(o["box"], t.width, t.height)
                    if b:
                        d.rectangle(b, outline=(255, 0, 0), width=6)
        if c["thing"] is not None:
            ys, xs = np.nonzero(c["thing"])
            if len(xs):
                d.rectangle((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())), outline=(255, 230, 0), width=6)
        s = 640 / t.width
        t = t.resize((640, round(t.height * s)), Image.LANCZOS)
        lab = Image.new("RGB", (640, 64), (20, 20, 20))
        dl = ImageDraw.Draw(lab)
        dl.text((8, 6), f"{c['set']}: {c['scene']} {c['id']}", fill=(255, 255, 255))
        said = "flagged: " + "; ".join(sorted({o["what"] for x in c["found"] for o in x["covered"] if not o.get("outside")}))[:95] \
            if c["flagged"] else ("no valid answer" if not c["asks"] else "called it clean") + (f" ({c['errors']} bad answers)" if c["errors"] else "")
        dl.text((8, 26), said, fill=(255, 200, 200) if c["flagged"] else (200, 220, 255))
        tiles.append(np.vstack([np.asarray(lab), np.asarray(t)]))
    w = 2
    rows = []
    for r in range(0, len(tiles), w):
        row = tiles[r:r + w]
        hmax = max(t.shape[0] for t in row)
        row = [np.pad(t, ((0, hmax - t.shape[0]), (0, 0), (0, 0))) for t in row]
        while len(row) < w:
            row.append(np.zeros_like(row[0]))
        rows.append(np.hstack(row))
    Image.fromarray(np.vstack(rows)).save(path, quality=88)
    return path


def azure_ref(scenes):
    """Seconds and dollars per Azure ask of the outdoor check on these scenes (the spend log)."""
    from azure_ai import usage_records
    secs, usd = [], []
    for r in usage_records():
        if r.get("deployment", "").startswith("local:"):
            continue
        p = r.get("purpose", "")
        if p.startswith("outdoor_check:") and p.split(":", 1)[1] in scenes:
            secs.append(r.get("s", 0))
            usd.append(r.get("usd_est", 0))
    return (statistics.median(secs) if secs else None, statistics.median(usd) if usd else None, len(secs))


def compare(scenes, ncuts, min_conf=0.6):
    os.environ["COZY_VISION"] = "local"
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for sc in scenes:
        cases += cases_for(oc, sc, ncuts, min_conf)
    cases += self_cases(oc)
    name, mc = model()
    started = serve()
    mem = gpu_mem()
    t_all = time.time()
    try:
        for i, c in enumerate(cases):
            plain, tint_im, ctx_im, pats = c["ev"]
            c.update(judge(oc, plain, tint_im, ctx_im, pats, min_conf))
            c["right"] = c["flagged"] == c["want"] and bool(c["asks"])     # no valid answer at all is never right
            c["hit"] = None
            if c["thing"] is not None and c["flagged"] and c["want"]:
                tw, th = tint_im.size
                hit, scales = False, set()
                for x in c["found"]:
                    for o in x["covered"]:
                        if o.get("outside") or not o.get("box"):
                            continue
                        b, sc = frac_box(o["box"], tw, th)
                        scales.add(sc)
                        if b and c["thing"][b[1]:b[3], b[0]:b[2]].any():
                            hit = True
                c["hit"], c["scales"] = hit, sorted(s for s in scales if s)
            print(f"  [{i + 1}/{len(cases)}] {c['set']:7s} {c['scene']} {c['id']}: want {'flag' if c['want'] else 'clean'}, "
                  f"local {'flag' if c['flagged'] else 'clean'}{'' if c['right'] else '  WRONG'}"
                  + (f", box on it: {c['hit']}" if c["hit"] is not None else "")
                  + (f", {c['errors']} bad answers" if c["errors"] else "")
                  + f" ({sum(c['secs']):.0f} s, {len(c['asks'])} asks)", flush=True)
    finally:
        if started:
            stop()
    took = time.time() - t_all
    secs = [s for c in cases for s in c["secs"]]
    az_s, az_usd, az_n = azure_ref(scenes)
    rows = []
    for st_ in ("clean", "cut-in", "cut-out", "cut-?", "self"):
        cs = [c for c in cases if c["set"] == st_]
        if cs:
            rows.append((st_, len(cs), sum(c["right"] for c in cs), [c for c in cs if not c["right"]]))
    scored = [c for c in cases if c["set"] != "cut-?"]
    pos = [c for c in scored if c["want"]]
    neg = [c for c in scored if not c["want"]]
    wrong = [c for c in scored if not c["right"]]
    tag = name.replace(".", "_")
    sp = sheet(wrong, OUT / f"compare_{tag}_sheet.jpg")
    flags = [c for c in pos if c["flagged"] and c["thing"] is not None]
    az_clean = [c for c in cases if c["set"] == "clean" and c["azure"] is not None]
    n_asks = len(secs)
    lines = [f"# Local vision vs Azure: the outdoor check, {name} ({dt.date.today().isoformat()})", "",
             f"Model: {name} ({pathlib.Path(mc['model']).name}) through llama.cpp on this PC's GPU; "
             f"GPU memory with it loaded: {mem[0]} of {mem[1]} MiB." if mem[0] else f"Model: {name}.",
             f"Scenes: {', '.join(scenes)}. {len(cases)} cases, {n_asks} local asks in {took / 60:.1f} min, "
             f"median {statistics.median(secs):.1f} s per ask." if secs else "No answers.",
             (f"Azure on the same check: median {az_s:.1f} s and ${az_usd:.3f} per ask ({az_n} asks logged); the same "
              f"{n_asks} asks would cost about ${az_usd * n_asks:.2f}." if az_s is not None else ""), "",
             f"Caught (indoor things under the weather flagged): {sum(c['right'] for c in pos)} of {len(pos)}. "
             f"Quiet (the outside called outside): {sum(c['right'] for c in neg)} of {len(neg)}. "
             f"Cases without a single valid answer: {sum(1 for c in scored if not c['asks'])}.", "",
             "| set | the right answer | cases | local right |", "|---|---|---|---|"]
    want = {"clean": "clean (tiles the check passed)", "cut-in": "flag (an indoor thing the check cut, put back under the weather)",
            "cut-out": "clean (a false cut: outside, put back)", "cut-?": "not labeled, not scored", "self": "outdoor_check's fixtures"}
    for st_, n, r, _ in rows:
        lines.append(f"| {st_} | {want[st_]} | {n} | {r if st_ != 'cut-?' else '-'} |")
    lines += ["", f"Flagged indoor cut things with a box on the thing: {sum(1 for c in flags if c['hit'])} of {len(flags)}; "
              f"box scales used: {sorted({s for c in flags for s in c.get('scales', [])})}.",
              f"Azure's own cached answers on the clean tiles: {sum(1 for c in az_clean if c['azure'] is False)} of {len(az_clean)} "
              "pass.", f"Answers that weren't valid JSON: {sum(c['errors'] for c in cases)}.", ""]
    if wrong:
        lines += ["## Wrong", ""]
        for c in wrong:
            said = "; ".join(sorted({o["what"] for x in c["found"] for o in x["covered"] if not o.get("outside")}))
            lines.append(f"- {c['set']} {c['scene']} {c['id']}: wanted {'a flag' if c['want'] else 'clean'}, got "
                         + (f"a flag: {said}" if c["flagged"] else "clean") + (f" ({c['error']})" if c["errors"] else ""))
        lines += ["", f"Sheet: {sp}"]
    (OUT / f"compare_{tag}.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    keep = [{k: v for k, v in c.items() if k not in ("ev", "thing", "asks", "found")} | {"asks": c["asks"]} for c in cases]
    (OUT / f"compare_{tag}.json").write_text(json.dumps({"model": name, "scenes": scenes, "gpu_mib": mem, "cases": keep},
                                                       indent=1, ensure_ascii=False, default=str), encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="a model from config/local_vision.json models (default: its active one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("stop")
    sub.add_parser("status")
    p = sub.add_parser("ask")
    p.add_argument("image")
    p.add_argument("question")
    p = sub.add_parser("compare")
    p.add_argument("--scenes", default="blossom-teahouse-rain,pixel-greenhouse-rain")
    p.add_argument("--cuts", type=int, default=10, help="cut things per scene, biggest first")
    p.add_argument("--min-conf", type=float, default=0.6)
    a = ap.parse_args()
    if a.model:
        os.environ["COZY_LOCAL_MODEL"] = a.model
    if a.cmd == "serve":
        try:
            serve()
        except RuntimeError as e:
            print(f"local vision: {e}")
            return 1
        return 0
    if a.cmd == "stop":
        return stop()
    if a.cmd == "status":
        lc = cfg()
        print(f"local vision: {'running with ' + str(loaded(lc)) if up(lc) else 'not running'} at {lc['endpoint']}; "
              f"active model {lc.get('active')}; first passes: {', '.join(lc.get('first_pass') or []) or 'none'} "
              f"(Azure has the final look); decided locally: {', '.join(lc.get('purposes') or []) or 'nothing'}; "
              f"GPU memory used/total MiB {gpu_mem()}")
        return 0
    if a.cmd == "ask":
        return ask(a.image, a.question)
    return compare([s for s in a.scenes.split(",") if s], a.cuts, a.min_conf)


if __name__ == "__main__":
    sys.exit(main())
