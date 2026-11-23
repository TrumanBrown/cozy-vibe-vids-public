"""More music like the tracks Truman picked. After he listens to the sample clips and names favorites (user
2026-10-19: clip 6 first, then 3, and curate around that sound), this ranks every candidate by how much it
sounds like them, measured, not guessed: CLAP (laion/larger_clap_music, Apache-2.0, a music-trained audio embedding
model run locally on the GPU) embeds 8 windows of 10 s across each track; a track's embedding is their normalized
mean. Every lofi track sits at about 0.99 cosine to every other in raw CLAP space (they share the genre), so the
pool's mean embedding is taken out first and the residuals are compared. A track's likeness is its best weighted
similarity to any favorite (preference 1 for the first, 0.85 for a close second): the ramen favorites were far apart
(-0.09 to each other), and a weighted average picked tracks halfway between them, like neither. The audio model was
tried for this and failed: it rated another excerpt of the favorite itself 7/10 against it.

  .venv\\Scripts\\python tools\\music_like.py <favorite track> [<favorite> ...] --in music\\_candidates\\<style> [...]
      [--weights 1,0.85] [--pick 28] [--to music\\<style-name>] [--min-length 100] [--top-unscreened N]

Ranks every track (with a complete sidecar) in the --in folders; prints the ranking with each track's screen.json
verdict (tools/music_screen.py: vocals, score). --pick N selects N clean tracks (no vocals in any screened excerpt,
screen score >= 8.5, at least --min-length s): a quota per favorite by preference, each filled with the clean tracks
most like that favorite (favorites always in), and copies them with their sidecars to --to. Embeddings are cached in
cache/music_clap/<sha1>.npy. Writes <first --in folder>/like.json.
"""
import argparse
import hashlib
import json
import pathlib
import shutil

import numpy as np

from cozy.paths import ROOT
import music as M  # noqa: E402
from cozy.models import revision  # noqa: E402  (pinned model revisions, TASKS.md T8)

MODEL = "laion/larger_clap_music"
CACHE = ROOT / "cache" / "music_clap"
SR = 48000


class Clap:
    def __init__(self):
        import os
        os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
        import torch
        from transformers import ClapModel, ClapProcessor
        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = ClapModel.from_pretrained(MODEL, cache_dir=str(ROOT / "cache" / "hf" / "hub"), revision=revision(MODEL)).to(self.dev).eval()
        self.proc = ClapProcessor.from_pretrained(MODEL, cache_dir=str(ROOT / "cache" / "hf" / "hub"), revision=revision(MODEL))

    def embed(self, path):
        h = hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()[:20]
        c = CACHE / f"{h}.npy"
        if c.exists():
            return np.load(c)
        x = np.asarray(M.decoded(path)[1], np.float32).mean(1)
        n = len(x)
        win = 10 * SR
        starts = [int(s) for s in np.linspace(0.1 * n, max(0.1 * n, 0.9 * n - win), 8)] if n > win else [0]
        chunks = [x[s: s + win] for s in starts]
        try:
            inp = self.proc(audio=chunks, sampling_rate=SR, return_tensors="pt")
        except TypeError:
            inp = self.proc(audios=chunks, sampling_rate=SR, return_tensors="pt")
        inp = {k: v.to(self.dev) for k, v in inp.items()}
        with self.torch.no_grad():
            e = self.model.get_audio_features(**inp)
        e = getattr(e, "pooler_output", e)
        e = e.float().cpu().numpy()
        e = e / np.linalg.norm(e, axis=1, keepdims=True)
        v = e.mean(0)
        v = v / np.linalg.norm(v)
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(c, v)
        return v


def verdict(path):
    """screen.json entry of a track (tools/music_screen.py), or None."""
    p = pathlib.Path(path)
    sp = p.parent / "screen.json"
    if not sp.exists():
        return None
    return json.loads(sp.read_text(encoding="utf-8")).get(p.name)


def clean(v, min_len):
    if not v:
        return False
    ex = v.get("excerpts") or []
    return (bool(ex) and all(x.get("vocals") == "none" for x in ex) and v.get("score", 0) >= 8.5
            and v.get("length_s", 0) >= min_len)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("favorites", nargs="+", help="the tracks he picked, best first")
    ap.add_argument("--in", dest="folders", action="append", required=True, help="candidate folder (repeatable)")
    ap.add_argument("--weights", help="preference of each favorite, comma separated (default 1 for the first, 0.85 for each "
                                      "other: a close second). A track's likeness is its best weighted similarity to any "
                                      "favorite, so the playlist holds tracks like either one, not ones halfway between")
    ap.add_argument("--pick", type=int, default=0, help="select this many clean tracks (favorites included)")
    ap.add_argument("--to", help="copy the selection with sidecars here")
    ap.add_argument("--min-length", type=float, default=100.0)
    a = ap.parse_args()
    favs = [pathlib.Path(f).resolve() for f in a.favorites]
    w = [float(x) for x in a.weights.split(",")] if a.weights else [1.0] + [0.85] * (len(favs) - 1)
    clap = Clap()
    pool = []
    for d in a.folders:
        for t in M.scan_one(pathlib.Path(d).resolve()):
            p = pathlib.Path(t["path"]).resolve()
            pool.append((t, p, clap.embed(p)))
    # Every lofi track sits near 0.99 cosine to every other (they share the genre): take out the pool's mean, so what
    # is left is what sets a track apart within the genre, then compare those residuals.
    mu = np.mean([e for _, _, e in pool], axis=0)
    res = lambda e: (e - mu) / (np.linalg.norm(e - mu) + 1e-9)
    F = np.stack([res(clap.embed(f)) for f in favs])
    rows = []
    for t, p, e in pool:
        sims = F @ res(e)
        v = verdict(p)
        rows.append({"file": str(p), "title": t["title"], "artist": t["artist"], "sims": [round(float(s), 4) for s in sims],
                     "like": round(float(np.max(np.asarray(w) * sims)), 4), "near": int(np.argmax(np.asarray(w) * sims)),
                     "fav": p in favs, "clean": clean(v, a.min_length),
                     "screened": v is not None, "length_s": (v or {}).get("length_s"), "score": (v or {}).get("score")})
    rows.sort(key=lambda r: -r["like"])
    out = pathlib.Path(a.folders[0]) / "like.json"
    out.write_text(json.dumps({"favorites": [str(f) for f in favs], "weights": w, "model": MODEL, "ranking": rows}, indent=1),
                   encoding="utf-8")
    print(f"{len(rows)} tracks ranked by likeness to {', '.join(f.name for f in favs)} (weights {w}) -> {out}")
    for i, r in enumerate(rows[:60], 1):
        tag = "FAV" if r["fav"] else ("ok " if r["clean"] else ("?  " if not r["screened"] else "x  "))
        print(f"  {i:3d} {tag} {r['like']:.3f} ({'/'.join(f'{s:.2f}' for s in r['sims'])}) {r['title'][:34]:34} {r['artist'][:14]:14} "
              f"{(r['length_s'] or 0) // 60}:{(r['length_s'] or 0) % 60:02d} score {r['score']}")
    if a.pick:
        # quotas by preference (the favorite gets the biggest share), each filled with the clean tracks most like that
        # favorite, so the playlist leans to the one he liked best instead of to whichever sits nearer the middle
        quota = [int(round(a.pick * x / sum(w))) for x in w]
        quota[0] += a.pick - sum(quota)
        sel, taken = [], set()
        for i in range(len(favs)):
            mine = [r for r in rows if r["fav"] and pathlib.Path(r["file"]) == favs[i]]
            cands = sorted((r for r in rows if not r["fav"] and r["clean"] and r["file"] not in taken), key=lambda r: -r["sims"][i])
            for r in mine + cands[: quota[i] - len(mine)]:
                if r["file"] not in taken:
                    taken.add(r["file"])
                    sel.append({**r, "near": i})
        unscreened = [r for r in rows[: a.pick * 2] if not r["screened"]]
        if unscreened:
            print(f"! {len(unscreened)} of the top {a.pick * 2} are not screened yet (vocals unknown): run tools/music_screen.py on their folder first")
        print(f"\nselected {len(sel)} (quotas {quota}):")
        for r in sel:
            print(f"  near {r['near'] + 1}: {r['sims'][r['near']]:.3f} {r['title']} - {r['artist']} ({(r['length_s'] or 0) // 60}:{(r['length_s'] or 0) % 60:02d})")
        if a.to:
            dst = pathlib.Path(a.to)
            dst.mkdir(parents=True, exist_ok=True)
            for r in sel:
                p = pathlib.Path(r["file"])
                shutil.copy2(p, dst / p.name)
                # the sidecar carries where the track sits between the favorites (its similarity to each), which
                # tools/music.py's smooth order uses to keep neighbours alike
                side = json.loads(p.with_name(p.name + ".json").read_text(encoding="utf-8"))
                side["vibe"] = r["sims"]
                side["picked"] = f"like {', '.join(f.name for f in favs)} (tools/music_like.py, {MODEL})"
                (dst / (p.name + ".json")).write_text(json.dumps(side, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"copied to {dst}")


if __name__ == "__main__":
    main()
