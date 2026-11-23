"""Per-layer loudness of an ambience bed (what is each layer contributing?), for one block of a timeline.

  .venv/Scripts/python tools/audio_layers.py out/<scene>/timeline.json [--block 20]

Prints each layer's momentary loudness range and integrated LUFS after the master gain, and its share of the
bed's power. Use it to balance a new bed by numbers before listening.
"""
import argparse
import json
import pathlib

import numpy as np

from cozy.audio.ambience import Ambience, make_cfg  # noqa: E402
from audio_analyze import integrated_lufs, k_weight  # noqa: E402

from cozy.paths import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("--block", type=int, default=20)
    a = ap.parse_args()
    tl = json.loads(pathlib.Path(a.timeline).read_text())
    amb = Ambience(tl, make_cfg(tl))
    amb.calibrate(ROOT / "cache" / pathlib.Path(a.timeline).parent.name)
    g = 10 ** (amb.master / 20)
    lay = amb.block(a.block, layers=True)
    tot = sum(v for v in lay.values()) * g
    P = (tot ** 2).mean()
    print(f"bed {amb.cfg.get('bed')}: total {integrated_lufs(k_weight(tot)):.1f} LUFS, master {amb.master:.1f} dB")
    for k, v in sorted(lay.items(), key=lambda kv: -float((kv[1] ** 2).mean())):
        x = v * g
        p = (x ** 2).mean()
        lu = integrated_lufs(k_weight(x)) if p > 1e-14 else -99
        print(f"  {k:8s} {lu:6.1f} LUFS  {100 * p / max(P, 1e-20):5.1f}% of power  peak {20 * np.log10(np.abs(x).max() + 1e-12):6.1f} dBFS")


if __name__ == "__main__":
    main()
