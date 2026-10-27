"""Short A/V clips of a finished render with candidate music, one clip per track, to choose a video's music by ear
before anything long is built (user 2026-10-16: sound first, then build once; 2026-10-19: music next, lofi or jazz,
with samples to choose from).

  .venv\\Scripts\\python tools\\music_samples.py out\\<scene>\\render\\<tag> <track file or folder> [...]
      [--top N] [--start 0] [--seconds 70] [--ambience-db -2] [--out out\\samples\\music\\<scene>] [--only <part of a name>]

--top N takes the N best tracks of each folder by its screen.json (tools/music_screen.py). Every sampled track is
logged in docs/asset-ledger.csv (kind "music candidate") before it is mixed. Each finished clip is then heard by the
audio model (config/azure.json audio_deployment) over its 30 s with the first storm strike: music, rain and thunder
audible, the balance, anything harsh (index.md "Heard"; --no-listen skips it, ~$0.015 a clip). The agent can't
listen, so this stands in for its ears before Truman's.

Each clip is the render's own picture over [start, start + seconds) of the video, with the ambience synthesized for
that range (tools/audio.py: the same as the render's) and one track as the whole playlist, mixed as the real video
would be: the music bus at audio.music.lufs (-16.5), the ambience ambience_db lower (-2 dB), the thunder at its own
level, a 4 s fade-in at the video start, the limiter. From --start 0 a clip shows the opening: the music should be
in within a few seconds (opener_lead). Tracks need complete sidecars (tools/music.py); Mojang's tracks only for
Minecraft looks. Clips are frame exact (HEVC, AAC 384k). index.md lists each clip with its track, artist, license,
source and the measured loudness. The scene's music folders are not touched.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

import numpy as np

from cozy.paths import ROOT, PY
from cozy.media import run_ffmpeg
import music as M  # noqa: E402
from audio_analyze import integrated_lufs, k_weight, load, true_peak  # noqa: E402

HEAR = ("This is 30 seconds of the soundtrack of a cozy ambience video: music mixed over rain and other ambience, maybe "
        "with thunder. Reply with only a JSON object: {\"music_audible\": true/false, \"rain_audible\": true/false, "
        "\"thunder_heard\": true/false, \"balance\": \"music too loud\" or \"about right\" or \"rain too loud\", "
        "\"harsh_or_clipping\": \"none or what\", \"overall\": \"one short sentence\"}")


def hear(clip, start):
    """The audio model's report on 30 s of a finished clip (dict, or {"error": ...})."""
    import base64
    import tempfile
    import azure_ai
    with tempfile.TemporaryDirectory() as d:
        x = pathlib.Path(d) / "x.mp3"
        run_ffmpeg(["-v", "error", "-y", "-ss", f"{start:.2f}", "-t", "30", "-i", str(clip), "-vn", "-ac", "2",
                    "-ar", "24000", "-b:a", "96k", str(x)], capture=False)
        b64 = base64.b64encode(x.read_bytes()).decode()
    text = ""
    for _ in range(3):
        text, _u = azure_ai.chat([{"role": "user", "content": [HEAR, {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}}]}],
                                 deployment=azure_ai.CFG.get("audio_deployment"), purpose="music sample mix check", max_tokens=400)
        s, e = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[s: e + 1])
        except json.JSONDecodeError:
            continue
    return {"error": text[:200]}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def tracks_from(paths, top=0):
    """(group, track) for every track with a complete sidecar in the given files and folders; with top, the best
    `top` of each folder by its screen.json score (unscreened tracks last)."""
    out = []
    for p in map(pathlib.Path, paths):
        p = p if p.is_absolute() else ROOT / p
        if p.is_dir():
            ts = M.scan_one(p)
            if top:
                sp = p / "screen.json"
                sc = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
                ts = sorted(ts, key=lambda t: -(sc.get(pathlib.Path(t["path"]).name) or {}).get("score", -1))[:top]
            out += [(p.name, t) for t in ts]
        elif p.exists():
            out += [(p.parent.name, t) for t in M.scan_one(p.parent) if pathlib.Path(t["path"]).resolve() == p.resolve()]
        else:
            sys.exit(f"no such track or folder: {p}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="a finished render folder (out/<scene>/render/<tag>)")
    ap.add_argument("tracks", nargs="+", help="track files or folders of tracks (each with a sidecar)")
    ap.add_argument("--start", type=float, default=None, help="video time of the clip start, s (default: the render's start)")
    ap.add_argument("--seconds", type=float, default=70.0)
    ap.add_argument("--ambience-db", type=float, help="the ambience under music, dB (default: audio.music.ambience_db, else -2)")
    ap.add_argument("--out", help="output folder (default out/samples/music/<scene>)")
    ap.add_argument("--only", help="only tracks whose title or file name contains this")
    ap.add_argument("--top", type=int, default=0, help="the best N tracks of each folder by its screen.json")
    ap.add_argument("--no-listen", action="store_true", help="skip the audio model's check of each finished clip")
    a = ap.parse_args()

    src = pathlib.Path(a.src).resolve()
    man = json.loads((src / "render.json").read_text())
    R0, L, fps = float(man["from"]), float(man["length"]), int(man["fps"])
    tl_path = src / "timeline.json"
    tl = json.loads(tl_path.read_text())
    scene = tl.get("scene") or man.get("scene")
    S = R0 if a.start is None else a.start
    if S < R0 or S + a.seconds > R0 + L + 1e-6:
        sys.exit(f"the clip [{S:g}, {S + a.seconds:g}) s must lie inside the render's window [{R0:g}, {R0 + L:g}) s")
    cfg = {**M.DEFAULTS, **((tl.get("audio") or {}).get("music") or {})}
    if a.ambience_db is not None:
        cfg["ambience_db"] = a.ambience_db
    mc = M.scene_music(scene)[1]
    out = pathlib.Path(a.out) if a.out else ROOT / "out" / "samples" / "music" / scene
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    todo = tracks_from(a.tracks, a.top)
    if a.only:
        todo = [(g, t) for g, t in todo if a.only.lower() in (t["title"] + " " + t["file"]).lower()]
    if not todo:
        sys.exit("no tracks with complete sidecars")
    f0, nf = int(round((S - R0) * fps)), int(round(a.seconds * fps))
    # what the model hears: the 30 s around the clip's first storm strike (thunder over music), else the middle
    strikes = [e["t"] for e in tl.get("events", []) if e.get("type") == "lightning" and S <= e["t"] < S + a.seconds]
    hs = min(max((strikes[0] - 12 - S) if strikes else (a.seconds - 30) / 2, 0.0), max(a.seconds - 30, 0.0))
    rows = []
    for i, (group, t) in enumerate(todo, 1):
        if not mc and M.is_mojang(t):
            print(f"skip {t['title']}: Mojang's tracks are only for Minecraft looks")
            continue
        plan = M.plan_tracks({"seed": tl["seed"], "duration": tl["duration"], "scene": scene}, [t], cfg,
                             [pathlib.Path(t["path"]).parent], mc)
        if not plan["entries"]:
            print(f"skip {t['title']}: too short or silent")
            continue
        # provenance first (AGENTS.md: every external asset goes in the ledger before use)
        M.ledger(plan, kind="music candidate (sample clips only)", modified="none (loudness-normalized in the clips)")
        tr = plan["tracks"][0]
        pp = tmp / f"plan_{i:02d}.json"
        pp.write_text(json.dumps(plan, indent=1))
        wav = tmp / f"clip_{i:02d}.wav"
        subprocess.run([PY, str(ROOT / "tools" / "audio.py"), str(tl_path), "--start", f"{S:g}", "--duration", f"{a.seconds:g}",
                        "--out", str(wav), "--music", str(pp)], check=True, capture_output=True)
        mix = wav.with_name(f"{wav.stem}_music.wav")
        name = f"{i:02d}_{slug(group)}_{slug(t['title'])}.mp4"
        dst = out / name
        # Frame-exact: seek a quarter frame early and re-encode (a stream copy would start at a keyframe).
        run_ffmpeg(["-hide_banner", "-loglevel", "error", "-y", "-ss", f"{(f0 - 0.25) / fps:.6f}",
                    "-i", str(src / "master.mp4"), "-i", str(mix), "-map", "0:v:0", "-map", "1:a:0", "-frames:v", str(nf),
                    "-vf", "setpts=PTS-STARTPTS", "-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "21",
                    "-c:a", "aac", "-b:a", "384k", "-movflags", "+faststart", str(dst)], capture=False)
        y = load(str(mix)).astype(np.float64)
        lufs, tp = integrated_lufs(k_weight(y)), true_peak(y)
        sp = pathlib.Path(t["path"] + ".json")
        side = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        heard = None if a.no_listen else hear(dst, hs)
        rows.append({"clip": name, "group": group, **{k: t.get(k) for k in ("title", "artist", "license", "license_url", "source", "attribution")},
                     "ai_made": bool(side.get("ai_made")), "length_s": round(tr["dur"]), "lead_s": tr["lead"],
                     "intro_cut_s": tr.get("intro_cut", 0), "track_lufs": tr["lufs"], "mix_lufs": round(float(lufs), 1),
                     "true_peak": round(float(tp), 1), "heard": heard})
        print(f"{name}: {t['title']} - {t['artist']} | track {tr['dur']:.0f} s, at its level after {tr['lead']:g} s | "
              f"mix {lufs:.1f} LUFS, true peak {tp:.1f} dBTP" + (f" | heard: {heard.get('balance')}, harsh: {heard.get('harsh_or_clipping')}"
                                                                  if heard else ""), flush=True)
        for f in (wav, mix):
            f.unlink(missing_ok=True)

    lines = [f"# Music samples: {scene}", "",
             f"Picture and ambience: `{src.relative_to(ROOT).as_posix()}`, video {S:g}-{S + a.seconds:g} s. Mix: music bus "
             f"{cfg['lufs']:g} LUFS, ambience {cfg['ambience_db']:+g} dB, thunder {cfg.get('thunder_db', 0):+g} dB, "
             f"{cfg['fade_in']:g} s fade-in at the video start. Each clip has one track; the real video shuffles the "
             "chosen tracks with crossfades.", "",
             "| Clip | Style | Track | Artist | Made | Length | In after | Heard | License | Source |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lic = f"[{r['license']}]({r['license_url']})" if r.get("license_url") else r["license"]
        h = r.get("heard") or {}
        heard = (f"{h.get('balance', '?')}; harsh: {h.get('harsh_or_clipping', '?')}" if h and "error" not in h else "not checked")
        lines.append(f"| `{r['clip']}` | {r['group']} | {r['title']} | {r['artist']} | {'AI (see source)' if r['ai_made'] else 'by the artist'} | "
                     f"{r['length_s'] // 60}:{r['length_s'] % 60:02d} | {r['lead_s']:g} s | {heard} | {lic} | {r['source']} |")
    (out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "index.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{len(rows)} clip(s) -> {out}")


if __name__ == "__main__":
    main()
