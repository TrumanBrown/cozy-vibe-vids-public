"""Frame and audio checks for a finished render (called by src/render/pipeline.mjs).

  compare <pairs.json> <out.json>
    pairs.json: [{"id": ..., "a": decoded.png, "b": fresh.png, "near": [fresh_prev.png, fresh_next.png]}, ...]
    For each item: PSNR(a, b) and PSNR(a, neighbor) for the neighbors. A decoded frame is "aligned" when it
    matches its own fresh render better than either neighbor (a dropped/duplicated frame at a segment
    join would match a neighbor instead), and "clean" when PSNR(a, b) is high (encoding noise only). A neighbor
    rendered identical to the frame itself says nothing about alignment and is left out ("held"): pixel art animates
    at 12 fps, so 2-3 frames of 30 are the same image (the pixel greenhouse's QA failed every frame on it, 2026-10-21).

  thunder <audio file> <timeline.json> <window start s> <window length s> <out.json>
  Short-term (3 s) loudness rise of each thunder (storm strikes and distant rumbles) over the bed just
  before its flash, measured on the final encoded audio (docs/GOALS.md: <= ~6 dB).
"""
import json
import sys

import cv2
import numpy as np

from audio_analyze import SR, k_weight, loudness_blocks  # noqa: E402
from cozy.media import run_ffmpeg


def psnr(x, y):
    d = (x.astype(np.float32) - y.astype(np.float32)) ** 2
    m = float(d.mean())
    return 99.0 if m <= 1e-10 else 10 * np.log10(255.0 ** 2 / m)


def thunder(audio, timeline, r0, length, dst):
    tl = json.loads(open(timeline).read())
    out = []
    for e in tl["events"]:
        if e["type"] not in ("lightning", "farflash") or not (r0 <= e["t"] < r0 + length):
            continue
        x, th = e["t"] - r0, e["thunder"]["t"] - r0
        t0 = max(0.0, x - 10)
        raw = run_ffmpeg(["-hide_banner", "-loglevel", "error", "-ss", str(t0), "-t", "35", "-i", audio,
                          "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]).stdout
        st, _ = loudness_blocks(k_weight(np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)), 3 * SR, SR // 10)
        tt = t0 + 3 + 0.1 * np.arange(len(st))
        pre, post = st[(tt > x - 6) & (tt < x - 1.5)], st[(tt > th) & (tt < th + 15)]
        if len(pre) and len(post):
            out.append({"t": round(th, 1), "type": e["type"], "distance_m": e["thunder"]["distance_m"], "over_bed_db": round(float(post.max() - np.median(pre)), 2)})
    open(dst, "w").write(json.dumps(out, indent=1))
    far = [o["over_bed_db"] for o in out if o["type"] == "farflash"]
    print(json.dumps({"strikes": len(out) - len(far), "far_rumbles": len(far),
                      "max_over_bed_db": max((o["over_bed_db"] for o in out if o["type"] == "lightning"), default=None),
                      "far_max_over_bed_db": max(far, default=None)}))


def main():
    cmd = sys.argv[1]
    if cmd == "thunder":
        thunder(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), sys.argv[6])
        return
    src, dst = sys.argv[2:4]
    assert cmd == "compare"
    items = json.loads(open(src).read())
    out = []
    for it in items:
        a = cv2.imread(it["a"])
        b = cv2.imread(it["b"])
        if a is None or b is None or a.shape != b.shape:
            out.append({"id": it["id"], "error": "missing or mismatched image"})
            continue
        own = float(psnr(a, b))
        nb = [n for n in (cv2.imread(p) for p in it.get("near", [])) if n is not None]
        held = [bool(n.shape == b.shape and psnr(b, n) >= 60.0) for n in nb]
        near = [float(psnr(a, n)) for n in nb]
        out.append({"id": it["id"], "psnr": round(own, 2), "near": [round(v, 2) for v in near], "held": int(sum(held)),
                    "aligned": bool(all(own > v + 0.5 for v, h in zip(near, held) if not h)), "clean": bool(own >= 34.0)})
    open(dst, "w").write(json.dumps(out, indent=1))
    bad = [o for o in out if o.get("error") or not o["aligned"] or not o["clean"]]
    print(json.dumps({"checked": len(out), "bad": len(bad), "min_psnr": min((o.get("psnr", 0) for o in out), default=None)}))


if __name__ == "__main__":
    main()
