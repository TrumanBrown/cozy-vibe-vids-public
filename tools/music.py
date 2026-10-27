"""Music slot (docs/GOALS.md "Music slot"): user-supplied tracks under the ambience.

Tracks live in folders under `music/` (gitignored), each with a JSON sidecar next to it (`<file>.json`):
  {"title": "...", "artist": "...", "source": "https://...", "license": "...",
   "license_url": "https://... (optional)", "attribution": "exact credit text the license asks for (optional)",
   "origin": "where this exact file came from, for the asset ledger (optional)"}
A track without a complete sidecar (title, artist, source, license) is never used. Licensing is the
user's call (docs/GOALS.md: only licenses that allow monetized YouTube use). Minecraft music: only the
Mojang-owned allowlist imported by tools/mc_music.py, never C418 (docs/DECISIONS.md "Minecraft music").

Which folders a video draws from (`scene_music`): the scene's `audio.music.dirs` (scene.json), else its look's
`music_dirs` in config/aesthetics.json (a style per look: the ramen alley lofi and jazz, a café jazz), else none
(ambience only). The root `music/` folder holds the Mojang allowlist: only Minecraft looks use it (the hand-built
scenes without a scene.json are all Minecraft looks), and a plan for any other look refuses Mojang tracks.
Mojang's not-official disclaimer goes into the credits of Minecraft looks only (user 2026-10-19: music for the
ramen alley, lofi or jazz).

  plan     seeded playlist that fills the video: whole tracks (leading/trailing silence trimmed) back to
           back with equal-power crossfades (6 s, or the length of a track's own fade-out up to 12 s, so
           endings don't leave a dip), reshuffled every cycle, never the same track twice in a row.
           Each track is loudness-normalized (BS.1770) so the music bus sits at `lufs` (default -16.5).
           Under music the ambience is lowered by `ambience_db` (default -2 dB; user 2026-10-16: the rain
           sat a touch high against the music), so the music mix lands at ~-16 LUFS (mix_target).
           The video opens with a track that is at its normal level within `opener_lead` s (default 5;
           0 = off): viewers look hardest at the start (user 2026-10-16), and some tracks sit almost
           silent for their first 40-70 s. Such near-silent intros (40 s or more, `trim_intro`; 0 = keep)
           are cut to their last 3 s, so the music never drops out for a minute (user 2026-10-16: those 6 songs
           start near silent, so skip that part). Under music the thunder stays at its own level,
           `thunder_db` (default 0 = as in the ambience-only mix), while the rest of the ambience is lowered.
  render   the music bus for any [start, start+dur): sample-exact in any range (random access), so
           segments rendered separately join seamlessly.
  credits  credits.txt for the YouTube description: the tracklist in order of first play (no timestamps:
           a list starting at 0:00 would turn into YouTube chapters) + licenses (tracks sharing a license
           and source share one line), the visuals/ambience note and Mojang's not-official disclaimer.
  ledger   add/refresh the tracks' rows in docs/asset-ledger.csv.

Usage (repo root):
  .venv/Scripts/python tools/music.py plan out/<scene>/timeline.json [--music-dir music/lofi ...] [--out .../music_plan.json]
  .venv/Scripts/python tools/music.py credits out/<scene>/music_plan.json [--out out/<scene>/credits.txt]
  .venv/Scripts/python tools/music.py ledger out/<scene>/music_plan.json
`--music-dir` (repeatable) overrides the scene's folders. The mix itself: tools/audio.py <timeline> ... --music
out/<scene>/music_plan.json (writes the ambience-only mix and <out>_music.wav = ambience (lowered by ambience_db) +
music, peak-limited). Short A/V clips of candidate tracks over a render: tools/music_samples.py.
"""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import re
import sys

import numpy as np

from cozy.paths import ROOT, config, rel
from cozy.ledger import row as ledger_row
from audio_analyze import integrated_lufs, k_weight, load, loudness_blocks, true_peak  # noqa: E402

SR = 48000
AUDIO_EXT = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".opus"}
REQUIRED = ("title", "artist", "source", "license")
DEFAULTS = {"lufs": -16.5, "crossfade": 6.0, "max_crossfade": 12.0, "fade_in": 4.0, "fade_out": 8.0, "silence_db": -60.0,
            "ambience_db": -2.0, "thunder_db": 0.0, "opener_lead": 5.0, "trim_intro": 40.0}
CACHE = ROOT / "cache" / "music"


def mix_target(ambience_lufs, cfg):
    """Where the music mix should land: the ambience (lowered by ambience_db) and the music bus added up.
    Plans from before ambience_db existed mixed the ambience at 0 dB. QA allows +-1.5 LU around it."""
    return float(10 * np.log10(10 ** ((ambience_lufs + cfg.get("ambience_db", 0.0)) / 10) + 10 ** (cfg["lufs"] / 10)))


def scene_music(scene):
    """(music folders, Minecraft look?) of a scene: scene.json `audio.music.dirs` (or `dir`), else its aesthetic's
    `music_dirs` (config/aesthetics.json), else none. A scene without a scene.json (Treetop and the other hand-built
    Minecraft scenes) keeps the root music/ folder, the Mojang allowlist."""
    sj = ROOT / "scenes" / str(scene or "") / "scene.json"
    if not scene or not sj.exists():
        return [ROOT / "music"], True
    sc = json.loads(sj.read_text(encoding="utf-8"))
    aes = config("aesthetics")["aesthetics"].get(sc.get("aesthetic"), {})
    m = (sc.get("audio") or {}).get("music") or {}
    dirs = m.get("dirs") or ([m["dir"]] if m.get("dir") else None) or aes.get("music_dirs") or []
    return [ROOT / d for d in dirs], aes.get("franchise") == "Minecraft"


def is_mojang(t):
    return "mojang" in " ".join(str(t.get(k) or "") for k in ("source", "attribution", "license", "origin")).lower()


def scan(music_dirs):
    """Tracks with complete sidecars in one folder or a list of folders (not their subfolders), sorted by file
    name per folder; prints why others are skipped."""
    out = []
    for d in [music_dirs] if isinstance(music_dirs, (str, pathlib.Path)) else music_dirs:
        out += scan_one(pathlib.Path(d))
    return out


def scan_one(d):
    out = []
    if not d.is_dir():
        return out
    for f in sorted(p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXT):
        side = f.with_name(f.name + ".json")
        if not side.exists():
            side = f.with_suffix(".json")
        if not side.exists():
            print(f"music: skipping {f.name} (no sidecar {f.name}.json)", file=sys.stderr)
            continue
        meta = json.loads(side.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if not str(meta.get(k, "")).strip()]
        if missing:
            print(f"music: skipping {f.name} (sidecar lacks {', '.join(missing)})", file=sys.stderr)
            continue
        out.append({"file": str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f), "path": str(f), **{k: meta.get(k) for k in
                    ("title", "artist", "source", "license", "license_url", "attribution", "origin")},
                    **({"vibe": meta["vibe"]} if meta.get("vibe") else {})})
    return out


def decoded(path):
    """48 kHz stereo float32 samples of a track, cached by content hash (cache/music/<sha1>.npy)."""
    h = hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()[:20]
    c = CACHE / f"{h}.npy"
    if not c.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(c, load(path).astype(np.float32))
    return h, np.load(c, mmap_mode="r")


def analyze(track, cfg):
    """Content hash, trim points (silence at the ends), loudness, the gain to the bus target, the tail:
    seconds after the last loud passage (short-term within 8 dB of the track's loudness), so a crossfade
    can overlap a track's own fade-out instead of leaving a dip, and the lead: seconds until the track
    first reaches its normal level (short-term within 6 dB of its loudness). A lead longer than
    trim_intro is cut to its last 3 s (`intro_cut` s; the crossfade fades the rest in); `lead` stays the
    track's own, so the opener is still a track that starts promptly by itself."""
    h, x = decoded(track["path"])
    env = np.abs(np.asarray(x)).max(1)
    thr = 10 ** (cfg["silence_db"] / 20)
    loud = np.nonzero(env > thr)[0]
    if not len(loud):
        return None
    a, b = int(loud[0]), int(loud[-1]) + 1
    xk = k_weight(np.asarray(x[a:b], np.float64))
    lufs = integrated_lufs(xk)
    st, _ = loudness_blocks(xk, 3 * SR, SR // 2)
    hot = np.nonzero(st >= lufs - 8.0)[0]
    tail = (b - a) / SR - ((hot[-1] * 0.5 + 3.0) if len(hot) else (b - a) / SR)
    near = np.nonzero(st >= lufs - 6.0)[0]
    lead = near[0] * 0.5 if len(near) else (b - a) / SR
    cut = lead - 3.0 if cfg.get("trim_intro") and lead >= cfg["trim_intro"] else 0.0
    end_cut = 0.0
    if cfg.get("body_db"):
        # (user 2026-10-19: smooth changes between tracks) play only the track's body: from 1 s before it first
        # comes within body_db of its own level to 0.5 s after it last holds it. Quiet intros and long fade-outs
        # crossfaded into each other left a hole of 4 to 19 dB and a jump of up to 10 dB at most track changes;
        # two full-level bodies crossfaded at equal power keep a steady level
        body = np.nonzero(st >= lufs - cfg["body_db"])[0]
        if len(body):
            cut = max(cut, body[0] * 0.5 - 1.0)
            end_cut = max(0.0, (b - a) / SR - (body[-1] * 0.5 + 3.0 + 0.5))
            tail = max(0.0, tail - end_cut)
    a += int(round(cut * SR))
    b -= int(round(end_cut * SR))
    return {"hash": h, "in": a, "out": b, "dur": (b - a) / SR, "lufs": round(float(lufs), 2),
            "gain_db": round(float(cfg["lufs"] - lufs), 2), "tail": round(max(float(tail), 0.0), 2), "lead": round(float(lead), 1),
            "intro_cut": round(float(cut), 1), **({"outro_cut": round(float(end_cut), 1)} if end_cut else {})}


def tempo_bpm(h, x):
    """A track's tempo (BPM, folded into 60-120, where lofi sits), cached in cache/music/<hash>.tempo: the
    autocorrelation of its onset envelope (spectral flux of the mono mix, 93.75 frames per s)."""
    c = CACHE / f"{h}.tempo"
    if c.exists():
        return float(c.read_text())
    m = np.asarray(x, np.float32).mean(1)
    hop, nfft = 512, 2048
    n = (len(m) - nfft) // hop
    if n < 200:
        return 0.0
    w = np.hanning(nfft).astype(np.float32)
    flux = np.zeros(n, np.float32)
    prev = None
    for i0 in range(0, n, 4096):
        idx = np.arange(i0, min(n, i0 + 4096))[:, None] * hop + np.arange(nfft)[None, :]
        S = np.log1p(np.abs(np.fft.rfft(m[idx] * w, axis=1))[:, :400])
        d = np.diff(np.vstack([S[:1] if prev is None else prev[None], S]), axis=0)
        flux[i0: i0 + len(S)] = np.maximum(d, 0).sum(1)
        prev = S[-1]
    flux -= np.convolve(flux, np.ones(64) / 64, mode="same")
    flux = np.maximum(flux, 0)
    fr = SR / hop
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    lo, hi = int(fr * 60 / 180), int(fr * 60 / 50)
    best = lo + int(np.argmax(ac[lo:hi]))
    bpm = 60 * fr / best
    while bpm < 60:
        bpm *= 2
    while bpm > 120:
        bpm /= 2
    CACHE.mkdir(parents=True, exist_ok=True)
    c.write_text(f"{bpm:.2f}")
    return float(round(bpm, 2))


def plan(timeline, music_dir, cfg):
    """The playlist for a timeline ({seed, duration, scene}) from music_dir (a folder or a list; None: the
    scene's own, scene_music)."""
    dirs, mc = scene_music(timeline.get("scene"))
    if music_dir is not None:
        dirs = [music_dir] if isinstance(music_dir, (str, pathlib.Path)) else list(music_dir)
    tracks = scan(dirs)
    if not mc and any(is_mojang(t) for t in tracks):
        sys.exit(f"music: Mojang's tracks are only for Minecraft looks, and {timeline.get('scene')} isn't one "
                 f"({', '.join(t['title'] for t in tracks if is_mojang(t))}); give the scene its own music folder")
    return plan_tracks(timeline, tracks, cfg, dirs, mc)


def smooth_costs(tracks):
    """Transition cost between tracks for the smooth order: the tempo distance in octaves, where half and double
    time count as the same (detected lofi tempos are often an octave off; 0.15 octave, ~8 BPM at 72, counts 1), plus
    the distance between their `vibe` (sidecar: similarity to each favorite, tools/music_like.py)."""
    n = len(tracks)
    tp = [t.get("tempo") or 0.0 for t in tracks]
    vb = [np.asarray(t.get("vibe") or [], float) for t in tracks]
    C = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            v = float(np.linalg.norm(vb[i] - vb[j])) if len(vb[i]) and len(vb[i]) == len(vb[j]) else 0.0
            o = abs(np.log2(tp[i] / tp[j])) if tp[i] > 0 and tp[j] > 0 else 0.0
            C[i, j] = min(o % 1.0, 1.0 - o % 1.0) / 0.15 + v
    return C


def smooth_cycle(r, C, last=None, avoid=(), start=None, tries=48):
    """One cycle through every track for the smooth order: of `tries` seeded walks that each step to one of the 3
    nearest unplayed tracks (the first third never from `avoid`: what ended the cycle before, so nothing repeats
    within minutes), the one with the lowest sum plus 3 x the worst of its transitions."""
    n = len(C)
    best, best_cost = None, np.inf
    for _ in range(tries):
        rr = np.random.default_rng(int(r.integers(2 ** 32)))
        unused, seq, cost, worst = set(range(n)), [], 0.0, 0.0
        cur = last
        while unused:
            pool = [j for j in unused if len(seq) >= n // 3 or j not in avoid] or list(unused)
            if cur is None:
                nxt = start if start is not None else pool[int(rr.integers(len(pool)))]
            else:
                near = sorted(pool, key=lambda j: C[cur, j])[:3]
                nxt = near[int(rr.integers(len(near)))]
                cost += C[cur, nxt]
                worst = max(worst, C[cur, nxt])
            seq.append(nxt)
            unused.discard(nxt)
            cur = nxt
        score = cost + 3 * worst
        if score < best_cost:
            best, best_cost = seq, score
    return best


def edge_env(tr, side, secs=30.0):
    """K-weighted power (linear, both channels) in 0.1 s steps, smoothed over 1 s, of the first (head) or last (tail)
    `secs` s of a track's body at its bus gain: what fit_transition lines up."""
    x = decoded(tr["path"])[1]
    a, b, n = tr["in"], tr["out"], int(secs * SR)
    seg = np.asarray(x[a: min(b, a + n)] if side == "head" else x[max(a, b - n): b], np.float64)
    y = k_weight(seg) * 10 ** (tr["gain_db"] / 20)
    p = (y ** 2).mean(1)
    hop = SR // 10
    k = len(p) // hop
    pw = p[: k * hop].reshape(k, hop).mean(1)
    return np.convolve(pw, np.ones(10) / 10, mode="same")


FIT_WIDE_DB = 4.0   # a join the usual search can't hold under this many dB gets the wide search


def _fit_search(envA, envB, trims, skips, overlaps):
    db = lambda p: 10 * np.log10(p + 1e-12)
    best = None
    for trim in trims:
        for skip in skips:
            for L in overlaps:
                a1 = len(envA) - int(round(trim * 10))
                a0 = a1 - int(round(L * 10))
                b0 = int(round(skip * 10))
                b1 = b0 + int(round(L * 10))
                if a0 - 100 < 0 or b1 + 100 > len(envB):
                    continue
                u = (np.arange(b1 - b0) + 0.5) / (b1 - b0)
                p = np.cos(0.5 * np.pi * u) ** 2 * envA[a0:a1] + np.sin(0.5 * np.pi * u) ** 2 * envB[b0:b1]
                ref = min(db(np.median(envA[a0 - 100: a0])), db(np.median(envB[b1: b1 + 100])))
                dip = max(0.0, float(ref - db(p).min()))
                score = dip + 0.15 * (trim + skip) + 0.05 * abs(L - 8.0)
                if best is None or score < best[0]:
                    best = (score, trim, skip, L, dip)
    return best


def fit_transition(envA, envB):
    """The track change from A (its tail envelope) into B (its head envelope) whose summed level holds best: of
    trims of A's end (0-3 s), skips of B's start (0-3 s) and equal-power overlaps (6, 8, 10 s), the one whose
    1 s level drops least under the quieter side's median of the 10 s around it (shorter cuts preferred on a
    tie). When the best of those still dips over FIT_WIDE_DB, it searches again with trims and skips up to 8 s and
    overlaps of 4-12 s: Minecraft's sparse tracks left 11 of the Minecraft tea house's 156 joins over 4 dB (up to
    9.5), and its Home into Bromeliad failed loop_master's QA at 6.75 dB; the wide search held every join under 4
    (2026-10-22). Joins that already held keep their fit, so an approved opening doesn't move.
    -> (trim, skip, overlap, predicted dip dB)"""
    best = _fit_search(envA, envB, (0.0, 1.0, 2.0, 3.0), (0.0, 1.0, 2.0, 3.0), (6.0, 8.0, 10.0))
    if best is not None and best[4] > FIT_WIDE_DB:
        wide = _fit_search(envA, envB, [float(s) for s in range(9)], [float(s) for s in range(9)], (4.0, 6.0, 8.0, 10.0, 12.0))
        if wide is not None and wide[4] < best[4]:
            best = wide
    return (0.0, 0.0, 8.0, None) if best is None else best[1:]


def plan_tracks(timeline, scanned, cfg, dirs=(), mc=True):
    """Whole tracks back to back with crossfades until the video is filled. order "shuffle" (default): every
    cycle a fresh shuffle. order "smooth" (user 2026-10-19: smooth changes between tracks): every cycle a
    seeded walk that always moves to one of the 3 unplayed tracks nearest in tempo and vibe (smooth_costs), so
    neighbours sound alike and each cycle still differs; nothing comes back within a third of a cycle. opener: a
    file name (or title) the video opens with."""
    tracks = []
    for t in scanned:
        a = analyze(t, cfg)
        if a and a["dur"] > 2 * cfg["max_crossfade"] + 4:
            tracks.append({**t, **a})
    order = cfg.get("order", "shuffle")
    if order == "smooth":
        for t in tracks:
            t["tempo"] = tempo_bpm(t["hash"], decoded(t["path"])[1])
    doc = {"version": 1, "seed": timeline["seed"], "duration": timeline["duration"], "cfg": cfg, "tracks": tracks, "entries": [],
           "scene": timeline.get("scene"), "dirs": [rel(d) for d in dirs], "minecraft": mc}
    if not tracks:
        return doc
    # Seeded per scene/seed and the exact track set (file hashes), so adding a track changes the plan.
    key = int(hashlib.sha1(json.dumps([timeline["seed"], [t["hash"] for t in tracks]]).encode()).hexdigest()[:8], 16)
    r = np.random.default_rng([key, 0x6D75])
    opener = cfg.get("opener")
    first = next((i for i, t in enumerate(tracks) if opener and (pathlib.Path(t["path"]).name == opener or t["title"] == opener)), None)
    if opener and first is None:
        print(f"music: opener {opener!r} isn't among the tracks; the usual opener rule applies", file=sys.stderr)
    C = smooth_costs(tracks) if order == "smooth" else None
    t, last, xf = 0.0, None, cfg["crossfade"]
    while t < timeline["duration"]:
        if order == "smooth":
            n = len(tracks)
            tail = [e["track"] for e in doc["entries"][-max(1, n // 3):]]
            cyc = smooth_cycle(r, C, last, avoid=set(tail), start=first if last is None else None)
        else:
            cyc = [int(i) for i in r.permutation(len(tracks))]
            if last is None and first is not None:
                cyc.insert(0, cyc.pop(cyc.index(first)))
            elif last is None and cfg.get("opener_lead"):
                # Open with the first track in the shuffle that is at its normal level within opener_lead s.
                j = next((j for j, i in enumerate(cyc) if tracks[i]["lead"] <= cfg["opener_lead"]), None)
                if j:
                    cyc.insert(0, cyc.pop(j))
            if last is not None and len(cyc) > 1 and cyc[0] == last:
                cyc[0], cyc[1] = cyc[1], cyc[0]
        for i in cyc:
            ov = round(min(max(xf, tracks[i]["tail"]), cfg["max_crossfade"]), 3)   # overlap with the next entry
            doc["entries"].append({"track": i, "start": round(t, 6), "xfade": ov})
            t += tracks[i]["dur"] - ov
            last = i
            if t >= timeline["duration"]:
                break
    if cfg.get("fit"):
        refit(doc)
    return doc


def refit(doc):
    """Fit every track change of a plan to its two tracks (fit_transition) and re-time the entries: each entry gets
    its own skip (off its start), trim (off its end) and overlap with the next, and starts where the one before,
    so cut, crosses into it. Fills the video again (more or fewer plays at the end)."""
    T, E = doc["tracks"], doc["entries"]
    env = {}
    edge = lambda i, side: env.setdefault((i, side), edge_env(T[i], side))
    order = [e["track"] for e in E]
    # extend the order with its own repeat, in case the cuts make the plays shorter than before
    while sum(T[i]["dur"] for i in order) < doc["duration"] * 1.2 + 600:
        order += [e["track"] for e in E]
    out, t, skip = [], 0.0, 0.0
    for k, i in enumerate(order):
        trim, nskip, L, dip = fit_transition(edge(i, "tail"), edge(order[k + 1], "head")) if k + 1 < len(order) else (0.0, 0.0, 8.0, None)
        e = {"track": i, "start": round(t, 6), "xfade": L, "skip": skip, "trim": trim}
        if dip is not None:
            e["fit_dip_db"] = round(dip, 2)
        out.append(e)
        t += T[i]["dur"] - skip - trim - L
        skip = nskip
        if t >= doc["duration"]:
            break
    doc["entries"] = out
    return doc


def transitions(doc, n=12):
    """How smooth the first n track changes are (user 2026-10-19: smooth changes between tracks): around each
    crossfade, the bus's 1 s level (K-weighted, dB) over the overlap vs the 10 s before and after. dip = how far the
    overlap drops under the quieter side; jump = the level step from the track before to the track after."""
    E, T = doc["entries"], doc["tracks"]
    out = []
    for k in range(1, min(len(E), n + 1)):
        s, ov = E[k]["start"], E[k - 1]["xfade"]
        a = max(0.0, s - 10.0)
        x = k_weight(render(doc, a, (s + ov + 10.0) - a))
        hop = SR // 10
        st = np.array([10 * np.log10(np.mean(x[i: i + SR] ** 2) + 1e-12) for i in range(0, len(x) - SR + 1, hop)])
        tt = a + 0.5 + np.arange(len(st)) * 0.1
        before = np.median(st[tt < s]) if np.any(tt < s) else np.nan
        after = np.median(st[tt > s + ov]) if np.any(tt > s + ov) else np.nan
        mid = st[(tt >= s) & (tt <= s + ov)]
        dip = float(min(before, after) - mid.min()) if len(mid) else 0.0
        out.append({"at_s": round(s, 1), "from": T[E[k - 1]["track"]]["title"], "to": T[E[k]["track"]]["title"], "xfade_s": ov,
                    "dip_db": round(max(dip, 0.0), 2), "jump_db": round(float(after - before), 2)})
    return out


def render(doc, start, dur):
    """Music bus for [start, start+dur) (stereo float64): tracks at their loudness gain, equal-power
    crossfades between consecutive entries, fades at the very start/end of the video."""
    n0, n1 = int(round(start * SR)), int(round((start + dur) * SR))
    out = np.zeros((n1 - n0, 2))
    if not doc["entries"]:
        return out
    cfg, T, E = doc["cfg"], doc["tracks"], doc["entries"]
    arrays = {}
    for k, e in enumerate(E):
        tr = T[e["track"]]
        s0 = int(round(e["start"] * SR))
        # this play's own cuts (fit_transition): skip off the start, trim off the end
        i0 = tr["in"] + int(round(e.get("skip", 0.0) * SR))
        n = tr["out"] - int(round(e.get("trim", 0.0) * SR)) - i0
        lo, hi = max(n0, s0), min(n1, s0 + n)
        if hi <= lo:
            continue
        if tr["hash"] not in arrays:
            arrays[tr["hash"]] = decoded(tr["path"])[1]
        seg = np.asarray(arrays[tr["hash"]][i0 + lo - s0: i0 + hi - s0], np.float64) * 10 ** (tr["gain_db"] / 20)
        i = np.arange(lo - s0, hi - s0)
        g = np.ones(len(i))
        if k > 0:                                    # equal-power fade in over the overlap with the previous entry
            xi = E[k - 1]["xfade"] * SR
            g *= np.sin(0.5 * np.pi * np.clip(i / xi, 0, 1))
        if k < len(E) - 1:                           # and out over this entry's overlap with the next
            xo = e["xfade"] * SR
            g *= np.cos(0.5 * np.pi * np.clip((i - (n - xo)) / xo, 0, 1))
        out[lo - n0: hi - n0] += seg * g[:, None]
    t = np.arange(n0, n1) / SR
    fade = np.clip(t / cfg["fade_in"], 0, 1) * np.clip((doc["duration"] - t) / cfg["fade_out"], 0, 1)
    return out * (0.5 - 0.5 * np.cos(np.pi * fade))[:, None]


def limit(x, n0, thr_db=-2.5, release=0.08, look=0.005, smooth=0.01, spots=()):
    """Local look-ahead peak limiter. 1 ms frames on the absolute sample grid (x starts at absolute
    sample n0); gain = the minimum needed gain over [-release, +look] around each frame, smoothed with a
    Hann window (the min window is widened by the smoothing half-width, so peaks never exceed thr). Every
    output sample depends only on input within ~0.1 s, so a range rendered with a 0.25 s margin on both
    sides is sample-exact (random access, seamless segments). spots: [(a0, a1, db)] absolute sample ranges
    with a lower ceiling (loop_master: transients the AAC encode overshot)."""
    fr = SR // 1000
    f0 = n0 // fr
    pad0 = n0 - f0 * fr
    nf = int(np.ceil((pad0 + len(x)) / fr))
    thr = np.full(nf, 10 ** (thr_db / 20))
    for a0, a1, db in spots:
        k0, k1 = max(int(a0) // fr - f0, 0), min(-(-int(a1) // fr) - f0, nf)
        if k1 > k0:
            thr[k0:k1] = np.minimum(thr[k0:k1], 10 ** (db / 20))
    a = np.zeros((nf * fr, 2))
    a[pad0: pad0 + len(x)] = np.abs(x)
    need = np.minimum(1.0, thr / np.maximum(a.reshape(nf, fr, 2).max(axis=(1, 2)), 1e-12))
    hs = int(smooth * 1000) // 2
    lb, la = int(release * 1000) + hs, int(look * 1000) + hs
    p = np.pad(need, (lb, la), constant_values=1.0)
    g = np.lib.stride_tricks.sliding_window_view(p, lb + la + 1).min(axis=1)
    w = np.hanning(2 * hs + 1)
    g = np.convolve(np.pad(g, hs, mode="edge"), w / w.sum(), mode="valid")
    gs = np.interp((np.arange(len(x)) + pad0) / fr, np.arange(nf) + 0.5, g)
    return x * gs[:, None]


# Mojang's usage guidelines ask for this wherever the Minecraft name or look is used, and every scene so far
# has the Minecraft look (user decision 2026-10-15). Public text never mentions AI (DECISIONS 2026-10-16).
MINECRAFT_DISCLAIMER = "NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT."


def credits(doc, ledger_path=ROOT / "docs" / "asset-ledger.csv"):
    """The credits for a YouTube description, in the form Truman published (2026-10-20): music that asks for credit
    (an `attribution` in its sidecar, like "Music courtesy of Mojang Studios", or a license that isn't CC0 or public
    domain) under that credit line, one "Title - Artist" per track in order of first play; CC0 music asks for none and
    gets none (the ledger keeps every track's provenance); then attributions the ledger asks for, and Mojang's
    disclaimer on Minecraft looks. Empty when nothing asks for credit. How the video is made is in his own words in
    assets/publish/description_blurb.txt, which tools/upload_package.py puts before these."""
    lines = []
    first = {}                                       # track -> first play
    for e in doc.get("entries") or []:
        first.setdefault(e["track"], e["start"])
    groups = {}                                      # credit line -> tracks, in first-play order
    for i in first:
        t = doc["tracks"][i]
        att = (t.get("attribution") or "").strip()
        if not att and re.search(r"(?i)\bCC0\b|public domain", t.get("license") or ""):
            continue
        url = f" ({t['license_url']})" if t.get("license_url") else ""
        head = att or f"{t['license']}{url} | {t['source']}"
        groups.setdefault(head, []).append(t)
    for head, items in groups.items():
        lines += ([""] if lines else []) + [head] + [f"{t['title']} - {t['artist']}" for t in items]
    extra = []
    if pathlib.Path(ledger_path).exists():
        with open(ledger_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                att = (row.get("attribution") or "").strip()
                if att and not att.lower().startswith("none") and not row["path"].startswith("music/"):
                    extra.append(f"{row['title']} - {att} ({row['license']})")
    if extra:
        lines += ([""] if lines else []) + ["Additional credits"] + extra
    if doc.get("minecraft", True):                   # plans from before 2026-10-19 were all Minecraft looks
        lines += ([""] if lines else []) + [MINECRAFT_DISCLAIMER]
    return "\n".join(lines) + "\n" if lines else ""


def ledger(doc, ledger_path=ROOT / "docs" / "asset-ledger.csv", kind=None, modified=None):
    """Upsert one row per track (keyed by path) into the asset ledger. kind/modified override the defaults (music
    used in a video); tools/music_samples.py logs candidates heard on sample clips."""
    p = pathlib.Path(ledger_path)
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    today = datetime.date.today().isoformat()
    for t in doc["tracks"]:
        path = t["file"].replace("\\", "/")
        row = {"path": path, "kind": kind or "music (user-supplied)", "title": t["title"], "author": t["artist"],
               "source_url": t["source"], "license": t["license"], "license_url": t.get("license_url") or "",
               "attribution": t.get("attribution") or "none",
               "modified": modified or f"loudness-normalized ({t['gain_db']:+.1f} dB), crossfaded",
               "date_retrieved": today, "notes": f"sidecar {path}.json; sha1 {t['hash']}" + (f"; from {t['origin']}" if t.get("origin") else "")}
        old = next((r for r in rows if r["path"] == path), None)
        if old:
            row["date_retrieved"] = old.get("date_retrieved") or today
            old.update(row)
        else:
            rows.append(row)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(ledger_row(r) for r in rows)
    return len(doc["tracks"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "credits", "ledger"])
    ap.add_argument("src", help="timeline.json (plan) or music_plan.json (credits, ledger)")
    ap.add_argument("--music-dir", action="append", help="a music folder (repeatable); default: the scene's own (scene_music)")
    ap.add_argument("--out")
    a = ap.parse_args()
    src = pathlib.Path(a.src)
    doc = json.loads(src.read_text())
    if a.cmd == "plan":
        cfg = {**DEFAULTS, **((doc.get("audio") or {}).get("music") or {})}
        p = plan(doc, a.music_dir, cfg)
        out = pathlib.Path(a.out) if a.out else src.with_name("music_plan.json")
        out.write_text(json.dumps(p, indent=1))
        tot = sum(p["tracks"][e["track"]]["dur"] for e in p["entries"])
        print(json.dumps({"out": str(out), "dirs": p["dirs"], "tracks": len(p["tracks"]), "entries": len(p["entries"]),
                          "music_s": round(tot), "lufs_target": cfg["lufs"]}))
        for t in p["tracks"]:
            tp = true_peak(np.asarray(decoded(t["path"])[1][t["in"]: t["out"]], np.float64)) + t["gain_db"]
            print(f"  {t['title']} - {t['artist']}: {t['dur']:.0f} s, {t['lufs']:.1f} LUFS -> gain {t['gain_db']:+.1f} dB (true peak {tp:+.1f} dBTP before limiting)")
    elif a.cmd == "credits":
        out = pathlib.Path(a.out) if a.out else src.with_name("credits.txt")
        out.write_text(credits(doc), encoding="utf-8")
        print(f"credits -> {out}")
    else:
        print(f"ledger: {ledger(doc)} music row(s) upserted in docs/asset-ledger.csv")


if __name__ == "__main__":
    main()
