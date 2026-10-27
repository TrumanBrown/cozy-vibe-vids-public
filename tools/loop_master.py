"""Loop a finished test-window render into a long master, without rendering anything again.

User decision 2026-10-16: loop the approved hour ten times instead of rendering 10 h; the video is background
ambience. The approved test hour becomes the 10 h video.

  .venv\\Scripts\\python tools\\loop_master.py out\\<scene>\\render\\<tag> [--times 10] [--xfade 3] [--name <tag>]

Video: the window's segment files (seg/video.txt) are listed N times and muxed by stream copy, the same
way the pipeline builds its master. Nothing is re-encoded; every join is a segment join, which the
render's QA already proved frame-exact. A window is a whole number of base loops (120 s), so the base
animation (rain, sway, flicker, breathing, waterfalls) lines up at each join. Only slow state changes
there: lights switched during the window come back on, and the weather track's rain and wind level
steps once.

Audio: a windowed render's ambience has soft fades at its edges (src/render/pipeline.mjs: 1.5 s in,
2 s out). Looped as is, the rain would dip every hour. At each internal join the faded seconds are
replaced by unfaded audio re-synthesized with tools/audio.py. That works because audio.py is random
access, so a few seconds synthesized alone match the render. The hour's own continuation past its end is
then crossfaded (equal power, --xfade s) into its start, so the bed never dips or clicks and stays
sample-locked to the video. The video's very first and very last fades are kept. Before using the
re-synthesized audio, the tool checks it against the render's FLAC: if the code or timeline changed
since the render, it stops. Encoded once to AAC 384k, as in the pipeline.

Music (--music auto, the default): when the scene's music folders (tools/music.py scene_music: scene.json
audio.music.dirs, else its look's music_dirs in config/aesthetics.json; the Mojang allowlist in music/ for Minecraft
looks; --music-dir overrides) have tracks with complete sidecars, the
playlist is planned over the whole looped length, so it does not repeat every hour, and mixed over the
looped ambience (music bus + local peak limiter, as tools/audio.py --music; the ambience sits
ambience_db lower under music, default -2 dB). It goes in a second file, master_music.mp4 (same video,
stream copy), and credits.txt then lists the music.

Re-running is cheap: a master.mp4 that already passed QA with the same source, --times and --xfade is
kept (it may be uploading), and so is a master_music.mp4 built from the same music plan. --force
rebuilds both. New files are written under a .new name and swapped in when complete, so a stopped run
leaves the previous files (and their music_plan.json and credits.txt) intact.

--offset 5m starts the video that far into the hour (a multiple of the render's segment length; user
2026-10-16: viewers look hardest at the start, so open on the busier part of the hour). The segment list
starts at that segment and wraps; the audio reads the same seamless loop 5 min later, with fresh linear
fades (1.5 s in, 2 s out) at the video's own start and end. The hour joins then fall at 55:00 + n h.

Get the sound right on short clips first (user 2026-10-16), then build the 10 h files once:
  --preview 7m-11m [--ambience-db 0,-2,-3.5] [--music-lufs ...]
writes only preview_music_<window>_rain<dB>.mp4 clips, one per --ambience-db value: the hour's own
picture for exactly that window (re-encoded with NVENC, frame-exact) with exactly the music mix the 10 h
file would have there. Takes ~1-2 min per 5 min of clip.

Output: out/<scene>/render/<name>/ master.mp4, ambience.m4a, credits.txt, thumbs/, loop.json, qa.md
        (+ master_music.mp4, music_mix.m4a, music_plan.json with music)
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from cozy.paths import ROOT, PY
from cozy.media import grab_frame, probe, run_ffmpeg
import music as M  # noqa: E402
from audio_analyze import integrated_lufs, k_weight  # noqa: E402

SR = 48000
FADE_IN, FADE_OUT = 1.5, 2.0          # src/render/pipeline.mjs: afade at a windowed render's edges


def ffmpeg(args, **kw):
    return run_ffmpeg(["-hide_banner", "-loglevel", "error", "-y", *args], capture=False, **kw)


def pcm(path, ss=None, t=None):
    """Decode audio to float32 stereo at SR (FLAC/WAV 24-bit map exactly onto float). Seeking is
    sample-accurate: a fast input seek to 10 s early, then an output seek (an input seek alone lands
    512-1024 samples off in AAC)."""
    pre = ["-ss", f"{ss - 10:.6f}"] if ss is not None and ss > 10 else []
    post = (["-ss", f"{ss - (ss - 10 if ss > 10 else 0):.6f}"] if ss is not None else []) + (["-t", f"{t:.6f}"] if t is not None else [])
    raw = run_ffmpeg(["-v", "error", *pre, "-i", str(path), *post, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def synth(timeline, start, dur, out):
    subprocess.run([PY, str(ROOT / "tools" / "audio.py"), str(timeline), "--start", f"{start:.6f}",
                    "--duration", f"{dur:.6f}", "--out", str(out)], check=True, capture_output=True)
    return pcm(out)


def label(s):
    return f"{s // 3600}h" if s % 3600 == 0 else f"{s // 60}m" if s % 60 == 0 else f"{s}s"


def ebu(f):
    r = run_ffmpeg(["-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128=peak=true", "-f", "null", "-"], check=False, text=True)
    s = r.stderr.split("Summary:")[-1]
    num = lambda p: (lambda m: float(m.group(1)) if m else None)(re.search(p, s))
    return {"lufs": num(r"I:\s+(-?[\d.]+) LUFS"), "lra": num(r"LRA:\s+([\d.]+) LU"), "true_peak": num(r"Peak:\s+(-?[\d.]+|-inf) dBFS")}


def frame(video, k, fps):
    """Decoded frame k (seek a quarter frame early: the first frame at or after that time is frame k)."""
    raw = grab_frame(video, f"{max(0.0, (k - 0.25) / fps):.6f}", frames=1, pix_fmt="rgb24")
    return np.frombuffer(raw, np.uint8)


def node():
    return shutil.which("node") or "node"


def seam_check(scene, src, R0, L, fps, tmp, log):
    """A looped window joins without a jump when the frame after its end is the frame at its start: render both
    (stills, same code as the segments) and compare. Needs a timeline that repeats with the window
    (scene.json events.loop, src/library/timeline.js loopTimeline); the old hour loops jumped at every join."""
    from PIL import Image
    d = tmp / "seam"
    shutil.rmtree(d, ignore_errors=True)
    f0, f1 = int(round(R0 * fps)), int(round((R0 + L) * fps))
    subprocess.run([node(), str(ROOT / "src" / "cli.mjs"), "still", f"scenes/{scene}", "--frames", f"{f0},{f1}", "--width", "3840",
                    "--height", "2160", "--out", str(d), "--name", "seam"], cwd=ROOT, check=True, capture_output=True)
    a = np.asarray(Image.open(d / f"seam_4k_f{f0:06d}.png").convert("RGB"), np.int16)
    b = np.asarray(Image.open(d / f"seam_4k_f{f1:06d}.png").convert("RGB"), np.int16)
    diff = np.abs(a - b).max(2)
    res = {"pass": bool(diff.max() <= 2), "max_diff": int(diff.max()), "px_over_2": int((diff > 2).sum()),
           "detail": f"frame {f1} (just past the window) rendered identical to frame {f0} (its start)"}
    log(f"loop seam: {'PASS' if res['pass'] else 'FAIL'} (max diff {res['max_diff']}, {res['px_over_2']} px over 2)")
    return res


def intro_segment(scene, src, t0, seg, log):
    """The video's first segment again with the intro title (src/library/title.js; --params intro=<t0>), so only the
    very start of the video carries it, never the window repeated after it. Same pipeline and encoder as the window,
    so it joins the stream copy. Returns its file, or None if the scene has no intro."""
    sj = ROOT / "scenes" / scene / "scene.json"
    if not sj.exists() or not json.loads(sj.read_text(encoding="utf-8")).get("intro"):
        return None
    import intro_title as IT
    plate = json.loads(sj.read_text(encoding="utf-8")).get("plate", scene)
    why = IT.stale(scene)
    if why:
        log(f"intro: {why}: drawing it (tools/intro_title.py)")
        subprocess.run([PY, str(ROOT / "tools" / "intro_title.py"), scene], check=True)
    pd = ROOT / "out" / "plates" / plate
    ij = json.loads((pd / "intro.json").read_text(encoding="utf-8"))
    # what title.js shows: the block and its box and timing
    key = hashlib.sha1((pd / "intro.png").read_bytes() + json.dumps([ij["box"], ij["timing"]]).encode()).hexdigest()[:16]
    tag = f"{src.name}_intro_at{int(t0)}"
    d = src.parent / tag
    man = json.loads((d / "render.json").read_text()) if (d / "render.json").exists() else {}
    wcq = json.loads((src / "render.json").read_text()).get("cq")   # the window's encoder quality, so the stream copy matches
    stamp = d / "intro_key.txt"
    if man.get("qa", {}).get("pass") and not stamp.exists() and (d / "render.json").stat().st_mtime > (pd / "intro.png").stat().st_mtime:
        stamp.write_text(key)                           # rendered before keys were stamped, after this intro.png was drawn
    fresh = man.get("qa", {}).get("pass") and stamp.exists() and stamp.read_text().strip() == key and man.get("cq") == wcq
    if not fresh:
        log(f"intro: rendering the first segment with the title -> {d}")
        subprocess.run([node(), str(ROOT / "src" / "cli.mjs"), "render", f"scenes/{scene}", "--from", str(int(t0)), "--length", str(int(seg)),
                        "--segment", str(int(seg)), "--name", tag, "--params", f"intro={t0:g}", "--music", "off", "--qa", "quick",
                        *(["--cq", str(wcq)] if wcq else []), *(["--force"] if man else [])], cwd=ROOT, check=True)
        stamp.write_text(key)
    files = [re.match(r"file '(.*)'", x).group(1) for x in (d / "seg" / "video.txt").read_text().split("\n") if x.strip()]
    return files[0]


def encoder(path):
    """AAC 384k encoder fed float32 stereo PCM on stdin (encoded once, as in the pipeline)."""
    return subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                             "-c:a", "aac", "-b:a", "384k", str(path)], stdin=subprocess.PIPE)


def put(enc, x):
    x = np.ascontiguousarray(np.clip(x, -1, 1), np.float32)
    mv = memoryview(x).cast("B")
    for i in range(0, len(mv), 1 << 26):
        enc.stdin.write(mv[i: i + (1 << 26)])


def finish(enc, what):
    enc.stdin.close()
    if enc.wait():
        sys.exit(f"AAC encode failed ({what})")


def mux(vtxt, m4a, dst, faststart):
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(vtxt), "-i", str(m4a), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            *(["-movflags", "+faststart"] if faststart else []), str(dst)])


def length_sync(master, N, L, fps):
    v = probe(master, "stream=duration,nb_frames", streams="v:0")["streams"][0]
    vd, nf = float(v["duration"]), int(v["nb_frames"])
    ad = float(probe(master, "stream=duration", streams="a:0")["streams"][0]["duration"])
    return {"pass": nf == N * L * fps and abs(vd - N * L) < 0.05 and abs(ad - N * L) < 0.05,
            "frames": nf, "expected": N * L * fps, "video_s": vd, "audio_s": ad}


def join_audio(m4a, at, level=True):
    """The first hour join (at s into the video) in the encoded audio: no level dip (1 s RMS vs the median
    of +-8 s) and no step (largest sample jump within +-50 samples vs the 99.9th percentile around it).
    Music has its own dynamics, so for a music mix only the step is checked."""
    s = pcm(m4a, at - 8, 16)
    dd = np.abs(np.diff(s, axis=0)).max(1)
    jump = float(dd[8 * SR - 50: 8 * SR + 50].max() / np.percentile(dd, 99.9))
    r = {"pass": jump < 1.5, "step_vs_p999": round(jump, 2)}
    if level:
        st = np.convolve((s ** 2).mean(1), np.ones(SR) / SR, "valid")[:: SR // 10]          # 1 s RMS, 0.1 s hop
        db = 10 * np.log10(st + 1e-12)
        dip = float(np.median(db) - db.min())
        r = {"pass": r["pass"] and dip < 3.0, "level_dip_db": round(dip, 2), "step_vs_p999": r["step_vs_p999"]}
    return r


class Looped:
    """The looped ambience of a windowed render: its FLAC, with the faded edges replaced by
    re-synthesized unfaded audio and each join crossfaded from the hour's own continuation into its
    start. hour(k) gives the pieces of loop k in order; A(n0, n1) any absolute sample range."""

    def __init__(self, src, R0, L, N, xfade, tmp, log):
        flac = pcm(src / "ambience.flac")
        self.N, self.NL = N, L * SR
        X, F, V = int(round(xfade * SR)), int(round(FADE_OUT * SR)), SR // 2
        if len(flac) != self.NL:
            sys.exit(f"ambience.flac has {len(flac)} samples, expected {self.NL}")
        tlp = src / "timeline.json"
        head = synth(tlp, R0, xfade + 0.5, tmp / "head.wav")                         # [R0, R0 + xfade + 0.5)
        tail = synth(tlp, R0 + L - FADE_OUT - 0.5, FADE_OUT + 0.5 + xfade, tmp / "tail.wav")   # 0.5 s check + end + continuation
        lsb = 1 / 2 ** 23
        e_head = float(np.abs(head[int(FADE_IN * SR) + 1: X + V] - flac[int(FADE_IN * SR) + 1: X + V]).max()) / lsb
        e_tail = float(np.abs(tail[:V] - flac[self.NL - F - V: self.NL - F]).max()) / lsb
        log(f"re-synthesized edges vs the render's FLAC: max {e_head:.1f} / {e_tail:.1f} LSB (24-bit; dither only if <= 8)")
        if max(e_head, e_tail) > 8:
            sys.exit("the re-synthesized audio does not match the render (code, scene or timeline changed since?): stopping")
        head_u, cont = head[:X], tail[V + F: V + F + X]
        u = (np.arange(X) + 0.5) / X
        self.join = (np.cos(0.5 * np.pi * u)[:, None] * cont + np.sin(0.5 * np.pi * u)[:, None] * head_u).astype(np.float32)
        self.tail_u = tail[V: V + F]
        self.flac, self.X, self.F = flac, X, F

    def hour(self, k):
        f, X, F = self.flac, self.X, self.F
        return (f[:X] if k == 0 else self.join), f[X: self.NL - F], (f[self.NL - F:] if k == self.N - 1 else self.tail_u)

    @classmethod
    def stem(cls, raw, N, xfade):
        """The same loop for one stem. raw covers [R0, R0 + L + xfade) unfaded (stem_audio); its joins are
        crossfaded from the continuation like the mix's, and the render's edge fades go on the very first and
        last piece."""
        self = cls.__new__(cls)
        X, F = int(round(xfade * SR)), int(round(FADE_OUT * SR))
        NL = len(raw) - X
        u = (np.arange(X) + 0.5) / X
        self.join = (np.cos(0.5 * np.pi * u)[:, None] * raw[NL:] + np.sin(0.5 * np.pi * u)[:, None] * raw[:X]).astype(np.float32)
        self.tail_u = np.asarray(raw[NL - F: NL], np.float32)
        n = np.arange(NL)
        g = (np.clip(n / (FADE_IN * SR), 0, 1) * np.clip((NL - n) / (FADE_OUT * SR), 0, 1)).astype(np.float32)
        self.flac = np.asarray(raw[:NL], np.float32) * g[:, None]
        self.N, self.NL, self.X, self.F = N, NL, X, F
        return self

    def __call__(self, n0, n1):
        """Absolute samples [n0, n1) of the long video (silence outside it)."""
        o = np.zeros((n1 - n0, 2), np.float32)
        n = max(n0, 0)
        while n < min(n1, self.N * self.NL):
            k, j = divmod(n, self.NL)
            pieces, starts = self.hour(k), (0, self.X, self.NL - self.F, self.NL)
            i = 0 if j < self.X else 1 if j < self.NL - self.F else 2
            m = min(n1, k * self.NL + starts[i + 1]) - n
            o[n - n0: n - n0 + m] = pieces[i][j - starts[i]: j - starts[i] + m]
            n += m
        return o


class Periodic:
    """The ambience of a window whose timeline repeats with it (scene.json events.loop; tools/audio.py folds time into
    the period and crossfades its own join): the render's audio (no edge fades) played back to back, so every join is
    sample-exact, with fades only at the video's real start and end (as the pipeline's master fades). Same interface
    as Looped (N, NL, flac, __call__)."""

    def __init__(self, src, L, N, log, raw=None):
        self.flac = pcm(src / "ambience.flac") if raw is None else np.asarray(raw, np.float32)
        self.N, self.NL = N, L * SR
        if len(self.flac) != self.NL:
            sys.exit(f"ambience has {len(self.flac)} samples, expected {self.NL}")
        if raw is None:
            log("audio: the window's own sound, back to back (its timeline repeats with it, so every join is seamless)")

    def __call__(self, n0, n1):
        i = np.arange(n0, n1)
        o = self.flac[i % self.NL]
        g = np.clip(i / (FADE_IN * SR), 0, 1) * np.clip((self.N * self.NL - i) / (FADE_OUT * SR), 0, 1)
        return (o * g[:, None] * ((i >= 0) & (i < self.N * self.NL))[:, None]).astype(np.float32)


class Shifted:
    """The looped ambience of a video that starts `offset` s into the hour (--offset): video sample n plays
    loop sample n + offset (the Looped stream needs one hour more), with fresh linear fades at the video's
    start and end like the pipeline's (the render's own fades sit at hour starts, which no longer begin
    the video)."""

    def __init__(self, A, offset, total):
        self.A, self.o, self.n, self.NL = A, int(round(offset * SR)), total, A.NL

    def __call__(self, n0, n1):
        i = np.arange(n0, n1)
        g = np.clip(i / (FADE_IN * SR), 0, 1) * np.clip((self.n - i) / (FADE_OUT * SR), 0, 1)
        return (self.A(n0 + self.o, n1 + self.o) * g[:, None]).astype(np.float32)


def secs(s):
    """A time like 7m, 1h7m30s, 90s or 420 (seconds)."""
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s?)?", s.strip())
    if not s.strip() or not m:
        raise argparse.ArgumentTypeError(f"not a time: {s!r} (e.g. 7m, 1h7m30s, 420)")
    h, mi, se = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + se


def span(s):
    """A window like 7m-11m."""
    p = s.split("-")
    if len(p) != 2 or secs(p[1]) <= secs(p[0]):
        raise argparse.ArgumentTypeError(f"not a window: {s!r} (e.g. 7m-11m)")
    return secs(p[0]), secs(p[1]), s


def hms(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"


def swap_in(new, final):
    """Replace final with the finished new file in one step, so a stopped run never leaves a half-written file."""
    try:
        os.replace(new, final)
    except PermissionError:
        sys.exit(f"{final} is in use (uploading, or open in a player?). The new file is {new}: close the other program and rename it.")


def music_cfg(a, tl):
    """Music settings: the defaults, the render's timeline snapshot, then the scene's current scene.json (music is
    planned here, after the window was rendered, so the latest settings apply)."""
    cfg = {**M.DEFAULTS, **((tl.get("audio") or {}).get("music") or {})}
    sj = ROOT / "scenes" / str(tl.get("scene") or "") / "scene.json"
    if tl.get("scene") and sj.exists():
        cfg.update(((json.loads(sj.read_text(encoding="utf-8")).get("audio") or {}).get("music")) or {})
    if a.music_lufs is not None:
        cfg["lufs"] = a.music_lufs
    return cfg


def stem_audio(tlp, start, dur, name, tmp, log, ref=None, chunk=300):
    """One stem of tools/audio.py (--stems) over [start, start + dur), rendered in parallel chunks (audio.py is
    random access, so they join sample-exactly) and cached in cache/loop/ by the timeline, the code audio.py runs (its
    imports too: cozy.code) and the range.
    ref: the render's ambience over the same start, to check that a middle chunk's full mix matches it."""
    from cozy.code import code_hash
    key = hashlib.sha1(pathlib.Path(tlp).read_bytes() + code_hash("audio").encode()
                       + f"{start:.6f},{dur:.6f}".encode()).hexdigest()[:20]
    c = ROOT / "cache" / "loop" / f"{name}_{key}.npy"
    if c.exists():
        return np.load(c)
    spans = [(float(s), float(min(chunk, dur - s))) for s in np.arange(0.0, dur, chunk)]
    outs = [tmp / f"stem_{i:03d}.wav" for i in range(len(spans))]

    def one(i):
        s, d = spans[i]
        subprocess.run([PY, str(ROOT / "tools" / "audio.py"), str(tlp), "--start", f"{start + s:.6f}",
                        "--duration", f"{d:.6f}", "--out", str(outs[i]), "--stems"], check=True, capture_output=True)

    log(f"{name} stem: rendering {dur:.0f} s with tools/audio.py in {len(spans)} parallel chunks")
    with ThreadPoolExecutor(max(1, min(8, (os.cpu_count() or 4) // 2))) as ex:
        list(ex.map(one, range(len(spans))))
    if ref is not None:
        k = len(spans) // 2
        s, d = spans[k]
        mixed = pcm(outs[k])
        err = float(np.abs(mixed - ref[int(round(s * SR)): int(round(s * SR)) + len(mixed)]).max()) * 2 ** 23
        log(f"{name} stem: its chunk's full mix vs the render's FLAC: max {err:.1f} LSB")
        if err > 8:
            sys.exit("the stems don't match the render (code, scene or timeline changed since?): stopping")
    x = np.concatenate([pcm(o.with_name(f"{o.stem}_{name}.wav")) for o in outs])
    for o in outs:
        for f in tmp.glob(f"{o.stem}*.wav"):
            f.unlink()
    c.parent.mkdir(parents=True, exist_ok=True)
    np.save(c, x)
    return x


def thunder_loop(src, A, R0, L, N, O, xfade, cfg, tmp, log):
    """The looped thunder stem, read like the ambience (offset, fades), for thunder at its own level under music
    (thunder_db); None if the plan has no thunder_db."""
    if cfg.get("thunder_db") is None:
        return None
    if isinstance(A, Periodic):
        raw = stem_audio(src / "timeline.json", R0, L, "thunder", tmp, log, ref=A.flac)
        return Periodic(src, L, N, log, raw=raw)
    raw = stem_audio(src / "timeline.json", R0, L + xfade, "thunder", tmp, log, ref=A.flac)
    T = Looped.stem(raw, A.N, xfade)
    return Shifted(T, O, N * T.NL) if O else T


def mix(S, plan, cfg, n0, n1, db, T=None, spots=()):
    """The music mix at absolute samples [n0, n1): the looped ambience at db (the thunder at thunder_db when T is
    given) plus the music bus, through the local limiter (spots: lower ceilings where the encode overshot).
    Rendered with 0.25 s margins, so any range is sample-exact (chunks, previews)."""
    mg = SR // 4
    s0, s1 = max(0, n0 - mg), n1 + mg
    ga = 10 ** (db / 20)
    amb = S(s0, s1).astype(np.float64) * ga
    if T is not None:
        amb += T(s0, s1).astype(np.float64) * (10 ** (cfg["thunder_db"] / 20) - ga)
    bus = M.render(plan, s0 / SR, (s1 - s0) / SR)
    return M.limit(amb + bus, s0, spots=spots)[n0 - s0: n1 - s0], amb[n0 - s0: n1 - s0], bus[n0 - s0: n1 - s0]


def overshoots(path, target=-2.0, block=0.1):
    """Where the encoded file's true peak (4x oversampled, decoded from the start as a player does) is over
    target dBTP: [(sample, dBTP)], one per 100 ms block. The limiter holds the mix to -2.5 dBFS, but AAC can
    overshoot a sharp transient by 3-4 dB (2026-10-20: a drum hit in Blue Skies decoded at +0.8 dBFS)."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-map", "a:0", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         stdout=subprocess.PIPE)
    B, pad, C = int(block * SR), SR // 100, 60 * SR
    hot, y, start, b0 = [], np.zeros((0, 2), np.float32), 0, 0      # y[0] is absolute sample `start`; b0 = next block
    while True:
        buf = p.stdout.read(C * 8)
        if buf:
            y = np.concatenate([y, np.frombuffer(buf, np.float32).reshape(-1, 2)])
        while b0 < start + len(y) and (not buf or b0 + B + pad <= start + len(y)):
            i0, i1 = b0 - start, min(b0 + B - start, len(y))
            seg = y[i0:i1]
            if 20 * np.log10(max(float(np.abs(seg).max()), 1e-12)) > target - 3.0:
                w0 = max(i0 - pad, 0)
                w = y[w0: min(i1 + pad, len(y))].astype(np.float64)
                X = np.fft.rfft(w, axis=0)
                Y = np.zeros((4 * len(w) // 2 + 1, 2), complex)
                Y[: X.shape[0]] = X
                up = np.abs(np.fft.irfft(Y, 4 * len(w), axis=0) * 4)
                core = up[4 * (i0 - w0): 4 * (i1 - w0)].max(axis=1)      # the block itself, away from the edges
                tp = 20 * np.log10(max(float(core.max()), 1e-12))
                if tp > target:
                    hot.append((int(b0 + core.argmax() // 4), round(tp, 2)))
            b0 += B
        if not buf:
            break
        keep = max(b0 - pad - start, 0)                # keep pad samples of left context for the next block
        y, start = y[keep:], start + keep
    p.wait()
    return hot


def preview(a, src, L, fps, N, O, out, S, plan, cfg, dbs, log, T=None):
    """Short A/V clips of the music version, one per rain level, to judge the sound before a 10 h build.
    Times are in the video; with --offset O the picture at video time t is the hour's t + O."""
    t0, t1, tag = a.preview
    f0, f1 = int(round((t0 + O) * fps)), int(round((t1 + O) * fps))      # the window in frames of the loop
    k = f0 // (L * fps)
    if t1 > N * L or f1 - k * L * fps > L * fps:
        sys.exit(f"--preview: pick a window inside one hour of the hour's picture (hour joins in the video fall at {hms(L - O)} + n h)")
    h0 = f0 - k * L * fps                               # first frame, in the hour's own master.mp4
    v0 = (f0 / fps) - O                                 # ... and its time in the video
    nf = f1 - f0
    n0 = int(round(v0 * SR))
    n1 = n0 + nf * SR // fps
    raw = out / "tmp" / "preview.f32"
    for db in dbs:
        y, amb, bus = mix(S, plan, cfg, n0, n1, db, T)
        raw.write_bytes(np.ascontiguousarray(np.clip(y, -1, 1), np.float32).tobytes())
        dst = out / (f"preview_music_{tag}_rain{db:+g}dB" + (f"_thunder{cfg['thunder_db']:+g}dB" if T is not None else "") + ".mp4")
        # Frame-exact: seek a quarter frame early and re-encode the clip's picture (a stream copy would have to
        # start at a keyframe, and its first frame gets dropped by players).
        ffmpeg(["-ss", f"{(h0 - 0.25) / fps:.6f}", "-i", str(src / "master.mp4"), "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(raw),
                "-map", "0:v:0", "-map", "1:a:0", "-frames:v", str(nf), "-vf", "setpts=PTS-STARTPTS",
                "-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "21", "-c:a", "aac", "-b:a", "384k", "-movflags", "+faststart", str(dst)])
        lr, lm, lx = (integrated_lufs(k_weight(v)) for v in (amb, bus, y))
        log(f"{dst.name}: video {hms(v0)}-{hms(v0 + nf / fps)} | rain {lr:.1f} LUFS, music {lm:.1f} LUFS "
            f"(music {lm - lr:+.1f} LU over the rain), mix {lx:.1f} LUFS")


def main():
    a = _parse_args()
    T0 = time.time()
    log = lambda s: print(f"[loop {time.time() - T0:6.0f} s] {s}", flush=True)

    src, man, R0, L, fps, N, dbs, vfiles = _window(a)
    out, prev, seg, O, J, tmp = _out_folder(a, src, man, R0, L, N, log)

    # 1. Audio: the render's FLAC plus re-synthesized unfaded edges and the hour's continuation. With an
    # offset the video reads the loop O s later (so the loop needs one hour more) with fresh edge fades.
    # A window whose timeline repeats with it (events.loop) needs none of that: its own sound back to back.
    P0, periodic, A, S, first_join = _ambience(a, src, R0, L, N, O, tmp, log)

    if a.preview:
        _preview_music(a, src, A, S, R0, L, fps, N, O, out, dbs, tmp, log)
        return

    intro_file, intro_id, vtxt = _video_list(a, man, src, R0, L, O, J, N, seg, vfiles, tmp, log)
    faststart, master, pq, keep = _keep_master(a, src, out, N, L, O, intro_id, prev)
    checks, kept = {}, []
    if keep:
        checks = {k: v for k, v in pq.items() if not k.startswith("music_")}
        kept.append("master.mp4")
        log(f"master.mp4 kept: it passed QA with the same source, --times, --xfade and --offset ({prev.get('created')}); --force rebuilds it")
    else:
        m4a = _encode_ambience(out, vtxt, faststart, master, S, A, N, log)
        _ambience_qa(man, src, master, m4a, R0, L, N, O, fps, first_join, intro_file, checks, tmp, log)
    if (src / "thumbs").exists():
        shutil.copytree(src / "thumbs", out / "thumbs", dirs_exist_ok=True)

    music = _music(a, src, out, vtxt, faststart, master, S, A, R0, L, N, O, fps, dbs, keep, prev, pq, checks, kept, first_join,
                   tmp, log)
    _credits(src, out, music, log)

    ok = _loop_json(a, src, out, R0, L, N, O, intro_id, kept, music, checks)
    _qa_md(a, src, man, out, R0, L, N, O, P0, periodic, first_join, intro_file, music, checks, ok)
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"QA {'PASS' if ok else 'FAIL'}: " + ", ".join(f"{k} {'PASS' if v['pass'] else 'FAIL'}" for k, v in checks.items()))
    log(f"done -> {master}" + (f" + {out / 'master_music.mp4'}" if music else ""))
    sys.exit(0 if ok else 1)


def _parse_args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="a finished render folder (out/<scene>/render/<tag>)")
    ap.add_argument("--times", type=int, default=10)
    ap.add_argument("--xfade", type=float, default=3.0, help="audio crossfade at each join, s (>= 1.5)")
    ap.add_argument("--name", help="output tag (default <N x length>_loop_<src tag>)")
    ap.add_argument("--music", choices=["auto", "off"], default="auto",
                    help="auto: with tracks in the scene's music folders (or --music-dir), also write master_music.mp4 (playlist planned over the whole video)")
    ap.add_argument("--music-dir", action="append", help="a music folder (repeatable); default: the scene's own (tools/music.py scene_music)")
    ap.add_argument("--music-lufs", type=float, help="music bus level, LUFS (default: the timeline's audio.music.lufs, else -16.5); "
                                                     "a new level rebuilds only master_music.mp4")
    ap.add_argument("--ambience-db", help="the rain (whole ambience) under music, dB vs the ambience-only master (default: "
                                          "audio.music.ambience_db, else -2); rebuilds only master_music.mp4. With --preview a "
                                          "comma list (one clip each), e.g. 0,-2,-3.5")
    ap.add_argument("--force", action="store_true", help="rebuild master.mp4 and master_music.mp4 even if they are up to date")
    ap.add_argument("--intro", choices=["auto", "off"], default="auto",
                    help="auto: with a scene intro (scene.json intro), the video's first segment is rendered again with the title")
    ap.add_argument("--preview", type=span, help="only write short clips of the music version for this window of the video, "
                                                  "e.g. 7m-11m (no 10 h build)")
    ap.add_argument("--offset", type=secs, help="start the video this far into the hour, e.g. 5m (a multiple of the render's "
                                                "segment length): busier events come sooner; no rendering. Default: the previous "
                                                "build's offset in the output folder, else 0")
    a = ap.parse_args()
    return a


def _window(a):
    """The render and the checked arguments: (its folder, render.json, the window's start and length, fps, times, the
    --ambience-db values, the segment files)."""
    src = pathlib.Path(a.src).resolve()
    man = json.loads((src / "render.json").read_text())
    R0, L, fps, N = int(man["from"]), int(man["length"]), int(man["fps"]), a.times
    if not man.get("qa", {}).get("pass"):
        sys.exit(f"{src} has no passing QA (render.json qa.pass); finish or fix that render first")
    if a.xfade < FADE_IN:
        sys.exit(f"--xfade must be >= {FADE_IN} s (it replaces the render's fade-in)")
    try:
        dbs = [float(x) for x in a.ambience_db.split(",")] if a.ambience_db else None
    except ValueError:
        sys.exit(f"--ambience-db: numbers in dB, e.g. -2 or 0,-2,-3.5 (got {a.ambience_db!r})")
    if dbs and len(dbs) > 1 and not a.preview:
        sys.exit("several --ambience-db values only with --preview (pick one for the 10 h build)")
    # The re-synthesized edges must be clear of audio.py's own master fades at the video's very start/end.
    if R0 < 3 or R0 + L + a.xfade > int(man["duration"]) - 3:
        sys.exit("loop a window from the middle of the video (render it with --from/--length, e.g. --from 8h --length 1h)")
    vfiles = []
    if not a.preview:
        vlist = (src / "seg" / "video.txt").read_text().split("\n")
        vfiles = [re.match(r"file '(.*)'", x).group(1) for x in vlist if x.strip()]
        missing = [f for f in vfiles if not pathlib.Path(f).exists()]
        if missing:
            sys.exit(f"segment files are missing (deleted seg/?): {missing[:3]}")
    return src, man, R0, L, fps, N, dbs, vfiles


def _out_folder(a, src, man, R0, L, N, log):
    """(the output folder, its previous loop.json, the segment length, the offset, the segments it skips, tmp/)."""
    out = src.parent / (a.name or f"{label(N * L)}_loop_{src.name}")
    out.mkdir(parents=True, exist_ok=True)
    prev = json.loads((out / "loop.json").read_text()) if (out / "loop.json").exists() else {}
    # The start offset is part of the video: a re-run (say, to swap a claimed track) keeps the previous one.
    seg = int(man["segment"])
    O = a.offset if a.offset is not None else (prev.get("offset_s", 0) if prev.get("source") == str(src) else 0)
    if O < 0 or O >= L or abs(O / seg - round(O / seg)) > 1e-9:
        sys.exit(f"--offset must be a multiple of the render's segment length ({seg} s) and less than {L} s")
    O, J = int(round(O)), int(round(O / seg))          # J: segments to skip at the start
    if a.offset is None and O:
        print(f"keeping --offset {hms(O)} from the previous build in {out.name} (--offset 0 starts at the hour)", flush=True)
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    log(f"{man['scene']} {src.name}: {label(L)} window at {R0} s, x{N}" + (f", starting {hms(O)} into the hour" if O else "") + f" -> {out}")
    return out, prev, seg, O, J, tmp


def _ambience(a, src, R0, L, N, O, tmp, log):
    """(the timeline's loop period, periodic?, the looped ambience, the same as the video reads it, the first join)."""
    tlj0 = json.loads((src / "timeline.json").read_text())
    P0 = (tlj0.get("loop") or {}).get("period")
    periodic = bool(P0) and abs(L / P0 - round(L / P0)) < 1e-9
    if periodic:
        if O:
            sys.exit("--offset is for hour loops; a periodic window starts wherever its render starts (--from)")
        A = S = Periodic(src, L, N, log)
    else:
        A = Looped(src, R0, L, N + (1 if O else 0), a.xfade, tmp, log)
        S = Shifted(A, O, N * A.NL) if O else A
    first_join = L - O                                  # where the hour's end meets its start in the video
    return P0, periodic, A, S, first_join


def _preview_music(a, src, A, S, R0, L, fps, N, O, out, dbs, tmp, log):
    tl = json.loads((src / "timeline.json").read_text())
    cfg = music_cfg(a, tl)
    plan = M.plan({"seed": tl["seed"], "duration": N * L, "scene": tl.get("scene")}, a.music_dir, cfg)
    if not plan["entries"]:
        sys.exit(f"--preview needs music: no tracks with complete sidecars in {plan['dirs'] or 'the scene (it has no music folders)'}")
    o = plan["tracks"][plan["entries"][0]["track"]]
    log(f"music: {len(plan['tracks'])} tracks; the video opens with {o['title']} (at its normal level after {o['lead']:g} s)")
    cuts = [f"{t['title']} {t['intro_cut']:g} s" for t in plan["tracks"] if t.get("intro_cut")]
    if cuts:
        log(f"music: near-silent intros cut (trim_intro {cfg['trim_intro']:g} s): " + ", ".join(cuts))
    T = thunder_loop(src, A, R0, L, N, O, a.xfade, cfg, tmp, log)
    preview(a, src, L, fps, N, O, out, S, plan, cfg, dbs or [cfg["ambience_db"]], log, T)
    shutil.rmtree(tmp, ignore_errors=True)


def _video_list(a, man, src, R0, L, O, J, N, seg, vfiles, tmp, log):
    """The segment list N times, the intro segment first: (the intro segment, its id, the list's file)."""
    if len(vfiles) * seg != L:
        sys.exit(f"seg/video.txt lists {len(vfiles)} segments of {seg} s, but the window is {L} s")
    seq = [vfiles[(J + i) % len(vfiles)] for i in range(N * len(vfiles))]
    intro_file = intro_segment(man["scene"], src, R0 + O, seg, log) if a.intro == "auto" else None
    intro_id = None
    if intro_file:
        seq[0] = intro_file
        ik = pathlib.Path(intro_file).parent.parent / "intro_key.txt"
        intro_id = f"{intro_file}#{ik.read_text().strip() if ik.exists() else ''}"     # a redrawn title rebuilds the master
        log(f"intro: the video opens with the title segment {pathlib.Path(intro_file).parent.parent.name}")
    vtxt = tmp / "video.txt"
    vtxt.write_text("".join(f"file '{f}'\n" for f in seq))
    return intro_file, intro_id, vtxt


def _keep_master(a, src, out, N, L, O, intro_id, prev):
    """(faststart?, master.mp4, the previous build's checks, whether master.mp4 can be kept)."""
    faststart = N * L <= 7200
    master = out / "master.mp4"
    pq = prev.get("qa", {}).get("checks", {})
    keep = (not a.force and master.exists() and prev.get("source") == str(src) and prev.get("times") == N
            and prev.get("xfade_s") == a.xfade and prev.get("offset_s", 0) == O and prev.get("intro") == intro_id and bool(pq)
            and all(v["pass"] for k, v in pq.items() if not k.startswith("music_")))
    return faststart, master, pq, keep


def _encode_ambience(out, vtxt, faststart, master, S, A, N, log):
    # 2. Ambience master: the looped audio in 60 s chunks, encoded once; the segment list N times, stream copy.
    m4a = out / "ambience.m4a"
    new_a, new_v = out / "ambience.new.m4a", out / "master.new.mp4"
    enc = encoder(new_a)
    C, total = 60 * SR, N * A.NL
    for c0 in range(0, total, C):
        put(enc, S(c0, min(total, c0 + C)))
        if min(total, c0 + C) % A.NL == 0:
            log(f"audio: loop {min(total, c0 + C) // A.NL}/{N} written")
    finish(enc, "ambience")
    log("audio encoded (AAC 384k)")
    mux(vtxt, new_a, new_v, faststart)
    swap_in(new_a, m4a)
    swap_in(new_v, master)
    log(f"master.mp4 muxed ({master.stat().st_size / 1e9:.1f} GB)")
    return m4a


def _ambience_qa(man, src, master, m4a, R0, L, N, O, fps, first_join, intro_file, checks, tmp, log):
    # 3. QA: length and sync, frame-exact hour join, a seamless audio join, loudness.
    checks["length_sync"] = length_sync(master, N, L, fps)
    tlj = json.loads((src / "timeline.json").read_text())
    P = (tlj.get("loop") or {}).get("period")
    if P and abs(L / P - round(L / P)) < 1e-9:
        checks["loop_seam"] = seam_check(man["scene"], src, R0, L, fps, tmp, log)
    elif N > 1:
        log("! the timeline doesn't repeat with the window (scene.json events.loop): the picture jumps at every join")
        checks["loop_seam"] = {"pass": False, "detail": "no repeating timeline (events.loop) matching the window"}
    if N > 1:
        K, H = first_join * fps, L * fps
        # (with an intro segment the first join is the end of the window's copy after it: compare a later join)
        if intro_file and N > 2:
            K += L * fps
        same = all(np.array_equal(frame(master, K + d, fps), frame(src / "master.mp4", (K + d + O * fps) % H, fps)) for d in (-2, -1, 0, 1))
        checks["hour_join_frames"] = {"pass": bool(same), "at_s": K / fps,
                                      "detail": "the 2 frames each side of a join decode identical to the source window's end/start"}
        checks["hour_join_audio"] = {**join_audio(m4a, first_join), "at_s": first_join}
    lu = ebu(m4a)
    checks["loudness"] = {"pass": lu["lufs"] is not None and -21.5 <= lu["lufs"] <= -18.5 and lu["true_peak"] <= -1.5, **lu}


def _music(a, src, out, vtxt, faststart, master, S, A, R0, L, N, O, fps, dbs, keep, prev, pq, checks, kept, first_join, tmp,
           log):
    """The music master, kept or built; -> what loop.json records of the music, or None without any."""
    # 4. Music: a playlist planned over the whole looped length (tools/music.py), mixed over the looped
    # ambience in 60 s chunks (mix(): the limiter is local, so chunk joins are sample-exact). The plan and
    # credits.txt are written only once master_music.mp4 is in place, so they always describe it.
    music = None
    if a.music == "auto":
        cfg, plan = _music_plan(a, src, N, L, dbs)
        if plan["entries"]:
            ptxt, music, mm, mus, pm, mq = _music_record(plan, prev, pq, out)
            if keep and mm.exists() and pm.get("plan_sha1") == music["plan_sha1"] and mq and all(v["pass"] for v in mq.values()):
                checks.update(mq)
                kept.append("master_music.mp4")
                log("master_music.mp4 kept (same music plan); --force rebuilds it")
            else:
                _music_opening(plan, cfg, master, out, mm, log)
                new_a, new_v, stamp, spots = _music_mix(a, src, out, S, A, R0, L, N, O, cfg, plan, music, tmp, log)
                _mux_music(vtxt, faststart, new_a, new_v, stamp, mm, mus, music, spots, log)
                _music_qa(cfg, plan, mm, mus, N, L, fps, first_join, checks, log)
            (out / "music_plan.json").write_text(ptxt)
            (out / "credits.txt").write_text(M.credits(plan), encoding="utf-8")
            log(f"music: {music['tracks']} tracks, {music['plays']} plays over {label(N * L)}; credits.txt lists them")
        else:
            log("music: no tracks with complete sidecars in the music folder; ambience only")
    return music


def _music_plan(a, src, N, L, dbs):
    tl = json.loads((src / "timeline.json").read_text())
    cfg = music_cfg(a, tl)
    if dbs:
        cfg["ambience_db"] = dbs[0]
    plan = M.plan({"seed": tl["seed"], "duration": N * L, "scene": tl.get("scene")}, a.music_dir, cfg)
    return cfg, plan


def _music_record(plan, prev, pq, out):
    ptxt = json.dumps(plan, indent=1)
    music = {"tracks": len(plan["tracks"]), "plays": len(plan["entries"]), "music_dir": plan["dirs"],
             "plan_sha1": hashlib.sha1(ptxt.encode()).hexdigest()[:16]}
    mm, mus = out / "master_music.mp4", out / "music_mix.m4a"
    pm = prev.get("music") or {}
    mq = {k: v for k, v in pq.items() if k.startswith("music_")}
    return ptxt, music, mm, mus, pm, mq


def _music_opening(plan, cfg, master, out, mm, log):
    o = plan["tracks"][plan["entries"][0]["track"]]
    log(f"music: opens with {o['title']} (at its normal level after {o['lead']:g} s); rain {cfg['ambience_db']:+g} dB, "
        f"thunder {cfg.get('thunder_db', cfg['ambience_db']):+g} dB under music")
    # The mux writes the new master next to the old one, so it needs a whole video's worth of free disk.
    need = master.stat().st_size + 5e9
    free = shutil.disk_usage(out).free
    if free < need:
        sys.exit(f"master_music.mp4 needs about {need / 1e9:.0f} GB free while it is written, and {free / 1e9:.0f} GB is free"
                 + (" (the old master_music.mp4 is only replaced at the end: delete it first if it's being rebuilt)" if mm.exists() else ""))


def _music_mix(a, src, out, S, A, R0, L, N, O, cfg, plan, music, tmp, log):
    """The music mix in music_mix.new.m4a, reused when a failed mux left one made from the same plan and settings;
    -> (that file, the new master's, the stamp, the transients held lower)."""
    new_a, new_v = out / "music_mix.new.m4a", out / "master_music.new.mp4"
    # A finished mix survives a failed mux (a full disk, a crash): its stamp says which plan and settings made it.
    stamp = out / "music_mix.new.json"
    key = {"plan_sha1": music["plan_sha1"], "source": src.name, "times": N, "offset_s": O, "xfade_s": a.xfade,
           "ambience_db": cfg["ambience_db"], "thunder_db": cfg.get("thunder_db")}
    done = json.loads(stamp.read_text()) if stamp.exists() and new_a.exists() else {}
    if done.get("key") == key:
        spots = [tuple(s) for s in done["spots"]]
        if done.get("note"):
            music["limited_spots_note"] = done["note"]
        log(f"music mix: reusing the finished {new_a.name} ({len(spots)} transient(s) held lower"
            + (f"; {done['note']}" if done.get("note") else "") + "); only the mux was left")
    else:
        spots = _encode_music_mix(a, src, S, A, R0, L, N, O, cfg, plan, new_a, tmp, log)
        stamp.write_text(json.dumps({"key": key, "spots": spots}))
    return new_a, new_v, stamp, spots


def _encode_music_mix(a, src, S, A, R0, L, N, O, cfg, plan, new_a, tmp, log):
    T = thunder_loop(src, A, R0, L, N, O, a.xfade, cfg, tmp, log)
    spots = []                      # transients the encode overshot: a lower ceiling there, then encode again
    for attempt in range(1, 4):
        enc = encoder(new_a)
        C, total = 60 * SR, N * A.NL
        for c0 in range(0, total, C):
            c1 = min(total, c0 + C)
            put(enc, mix(S, plan, cfg, c0, c1, cfg["ambience_db"], T, spots)[0])
            if c1 % A.NL == 0:
                log(f"music mix: {c1 // A.NL}/{N} written" + (f" (pass {attempt})" if attempt > 1 else ""))
        finish(enc, "music mix")
        hot = overshoots(new_a)
        if not hot or attempt == 3:
            if hot:
                log(f"music mix: after {attempt} passes {len(hot)} transient(s) are still over -2 dBTP, worst "
                    f"{max(t for _, t in hot):+.1f} dBTP (QA allows -1.5)")
            break
        worst = max(hot, key=lambda h: h[1])
        log(f"music mix: the AAC encode goes over -2 dBTP at {len(hot)} transient(s), worst {worst[1]:+.1f} dBTP at "
            f"{hms(worst[0] / SR)}; lowering the ceiling there and encoding again")
        for smp, tp in hot:
            cur = min([db for a0_, a1_, db in spots if a0_ <= smp < a1_], default=-2.5)
            spots.append((smp - SR // 20, smp + SR // 20, round(cur - (tp + 2.0) - 0.5, 2)))
    return spots


def _mux_music(vtxt, faststart, new_a, new_v, stamp, mm, mus, music, spots, log):
    music["limited_spots"] = [[round((a0_ + SR // 20) / SR, 3), db] for a0_, _, db in spots]
    log("music mix encoded (AAC 384k)" + (f"; {len(spots)} transient(s) held lower after the encode overshot them" if spots else ""))
    mux(vtxt, new_a, new_v, faststart)
    swap_in(new_a, mus)
    swap_in(new_v, mm)
    stamp.unlink(missing_ok=True)
    log(f"master_music.mp4 muxed ({mm.stat().st_size / 1e9:.1f} GB)")


def _music_qa(cfg, plan, mm, mus, N, L, fps, first_join, checks, log):
    checks["music_length_sync"] = length_sync(mm, N, L, fps)
    if N > 1:
        checks["music_hour_join_audio"] = {**join_audio(mus, first_join, level=False), "at_s": first_join}
    tr = M.transitions(plan, 24)
    dips = [t["dip_db"] for t in tr]
    worst = max(tr, key=lambda t: t["dip_db"]) if tr else None
    checks["music_transitions"] = {
        "pass": not (cfg.get("fit") and dips and max(dips) > 6.0), "changes": len(tr),
        "dip_median_db": round(float(np.median(dips)), 2) if dips else None, "dip_max_db": max(dips) if dips else None,
        "worst": f"{worst['from']} -> {worst['to']} at {hms(worst['at_s'])}" if worst else None,
        "detail": "the music's level over each of the first 24 track changes vs the 10 s on each side"
                  + (" (fitted plan: every dip <= 6 dB)" if cfg.get("fit") else " (unfitted plan: reported only)")}
    if dips:
        log(f"music transitions: {len(dips)} changes, dip median {np.median(dips):.1f} dB, max {max(dips):.1f} dB ({checks['music_transitions']['worst']})")
    lu = ebu(mus)
    want = M.mix_target(checks["loudness"]["lufs"] or -20.0, cfg)      # the measured ambience, lowered, plus the bus
    checks["music_loudness"] = {"pass": lu["lufs"] is not None and abs(lu["lufs"] - want) <= 1.5 and lu["true_peak"] <= -1.5,
                                **lu, "target": f"{want - 1.5:.1f}..{want + 1.5:.1f} LUFS (music bus {cfg['lufs']:g}, "
                                                f"ambience {cfg['ambience_db']:+g} dB), true peak <= -1.5 dBTP"}


def _credits(src, out, music, log):
    if not music:
        if (src / "credits.txt").exists():
            shutil.copy2(src / "credits.txt", out / "credits.txt")
        if (out / "master_music.mp4").exists():
            log("note: master_music.mp4 here is from an earlier run with music; it was not rebuilt, and credits.txt now has no music")


def _loop_json(a, src, out, R0, L, N, O, intro_id, kept, music, checks):
    ok = all(c["pass"] for c in checks.values())
    info = {"source": str(src), "source_tag": src.name, "window": [R0, R0 + L], "times": N, "xfade_s": a.xfade, "offset_s": O,
            "intro": intro_id, "duration_s": N * L, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "kept": kept, "music": music,
            "qa": {"pass": ok, "checks": checks}}
    (out / "loop.json").write_text(json.dumps(info, indent=1))
    return ok


def _qa_md(a, src, man, out, R0, L, N, O, P0, periodic, first_join, intro_file, music, checks, ok):
    rows = "\n".join(f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | {json.dumps({x: y for x, y in v.items() if x != 'pass'})} |" for k, v in checks.items())
    mline = (f" master_music.mp4: the same video with music, {music['tracks']} tracks planned over the whole video "
             f"({music['plays']} plays; music_plan.json).") if music else ""
    oline = (f" The video starts {hms(O)} into the hour, so an event at hour time t plays at t - {O // 60} min (mod 60); "
             f"the hour joins fall at {hms(first_join)} + n h.") if O else ""
    how = (f"its timeline repeats every {label(int(P0))} (events.loop), so every join is frame- and sample-exact"
           if periodic else f"audio joins crossfaded over {a.xfade:g} s from re-synthesized unfaded audio")
    iline = " The first segment is rendered again with the intro title." if intro_file else ""
    (out / "qa.md").write_text(f"# QA: {man['scene']} {out.name}\n\n{src.name} ({R0}-{R0 + L} s) looped {N} times; {how}.{iline}{oline}{mline}\n\n"
                               f"Overall: **{'PASS' if ok else 'FAIL'}**\n\n"
                               f"| Check | Result | Detail |\n|---|---|---|\n{rows}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
