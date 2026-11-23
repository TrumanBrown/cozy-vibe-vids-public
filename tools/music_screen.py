"""Listen to candidate music before Truman does. An audio model (Azure gpt-audio, config/azure.json
`audio_deployment`) hears two 30 s excerpts of every track and reports vocals, instruments, tempo, genre and mood,
plus how well it matches the look's music style, how calm and steady it is and how well it is made. With the
track's own numbers (length, loudness, how soon it reaches its level), that ranks a folder of candidates, so only
the best few become sample clips (tools/music_samples.py --top) for Truman to pick from by ear (new-video STOP 3,
user 2026-10-19: music next, lofi or jazz, with samples to choose from).

  .venv\\Scripts\\python tools\\music_screen.py music\\_candidates\\<style> [...] [--scene <scene>] [--style "..."] [--force]

--scene takes the style from the scene's look (config/aesthetics.json `music`) and its brief (setting, time,
weather); --style overrides. Results are cached per file and style in <folder>/screen.json (re-screening costs
nothing until a file or the style changes; about $0.03 per track). A track with lyrics in either excerpt is out;
wordless vocals cost 2 points. Score = 0.4 style match + 0.35 calm + 0.25 quality (0 to 10).
"""
import argparse
import base64
import hashlib
import json
import pathlib
import sys
import tempfile

from cozy.paths import ROOT, config
from cozy.media import run_ffmpeg
import azure_ai  # noqa: E402
import music as M  # noqa: E402

PROMPT = """You help choose background music for a 10 hour cozy ambience video. Wanted style: {style}.
The music plays quietly under rain and city ambience while people study, read or fall asleep, so it must be calm and
steady, with nothing that grabs attention.

Listen to this excerpt ({where} of a {length} track) and reply with only a JSON object:
{{"vocals": "none" or "wordless" or "lyrics", "instruments": ["..."], "tempo_bpm": 0, "genre": "...", "mood": "...",
"style_match": 0-10 (how well it matches the wanted style), "calm": 0-10 (10 = steady and unobtrusive),
"quality": 0-10 (production and mix; harsh, thin or amateurish sound scores low),
"distracting": "what would pull attention (vocals, speech samples, sudden drops or stops, harsh or piercing sounds, sirens), or none"}}"""


def style_for(scene):
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    aes = config("aesthetics")["aesthetics"].get(sc.get("aesthetic"), {})
    bp = ROOT / "scenes" / scene / "brief.json"
    b = json.loads(bp.read_text(encoding="utf-8")) if bp.exists() else {}
    music = str(aes.get("music", "")).replace("(later)", "").strip()
    where = ", ".join(str(b[k]) for k in ("setting", "time", "weather") if b.get(k))
    return f"{music} for {where or aes.get('title', scene)}"


def excerpt(path, start, dur=30.0):
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "x.mp3"
        run_ffmpeg(["-v", "error", "-y", "-ss", f"{start:.1f}", "-t", f"{dur:g}", "-i", str(path),
                    "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)], capture=False)
        return base64.b64encode(out.read_bytes()).decode()


def listen(path, start, length, style):
    """The model's JSON about one excerpt, and its cost. It sometimes answers in prose or not at all: up to three
    tries, then a record with `error` (scored 0, so the track drops to the bottom)."""
    where = f"{int(start // 60)}:{int(start % 60):02d} to {int((start + 30) // 60)}:{int((start + 30) % 60):02d}"
    audio = excerpt(path, start)
    usd, text = 0.0, ""
    for attempt in range(3):
        prompt = PROMPT.format(style=style, where=where, length=f"{int(length // 60)}:{int(length % 60):02d}")
        if attempt:
            prompt += "\nReply with the JSON object only, nothing else."
        msgs = [{"role": "user", "content": [prompt, {"type": "input_audio", "input_audio": {"data": audio, "format": "mp3"}}]}]
        text, usage = azure_ai.chat(msgs, deployment=azure_ai.CFG.get("audio_deployment"), purpose="music screen", max_tokens=700)
        usd += usage.get("usd_est") or 0.0
        s, e = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[s: e + 1]), usd
        except json.JSONDecodeError:
            continue
    return {"vocals": "unknown", "style_match": 0, "calm": 0, "quality": 0, "error": text[:300]}, usd


def score(r):
    ex = r["excerpts"]
    if any(x.get("vocals") == "lyrics" for x in ex):
        return 0.0
    mean = lambda k: sum(float(x.get(k) or 0) for x in ex) / len(ex)
    s = 0.4 * mean("style_match") + 0.35 * mean("calm") + 0.25 * mean("quality")
    return round(s - (2.0 if any(x.get("vocals") == "wordless" for x in ex) else 0.0), 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--scene", help="take the wanted style from this scene's look and brief")
    ap.add_argument("--style", help="the wanted style in words (overrides --scene)")
    ap.add_argument("--force", action="store_true", help="listen again even if cached")
    a = ap.parse_args()
    style = a.style or (style_for(a.scene) if a.scene else None)
    if not style:
        sys.exit("give --scene or --style")
    print(f"wanted: {style}")
    cfg = dict(M.DEFAULTS)
    usd, rows = 0.0, []
    todo = []                                        # (folder, track): whole folders, or single files
    for arg in map(pathlib.Path, a.folders):
        if arg.is_file():
            todo += [(arg.parent, t) for t in M.scan_one(arg.parent.resolve()) if pathlib.Path(t["path"]).name == arg.name]
        else:
            todo += [(arg, t) for t in M.scan_one(arg.resolve())]
    caches = {}
    for folder, t in todo:
        sp = folder / "screen.json"
        if sp not in caches:
            caches[sp] = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        cache = caches[sp]
        f = pathlib.Path(t["path"])
        h = hashlib.sha1(f.read_bytes()).hexdigest()[:16]
        key = f.name
        c = cache.get(key)
        if c and c.get("sha1") == h and c.get("style") == style and not a.force:
            rows.append(c)
            continue
        an = M.analyze(t, cfg)
        if not an:
            continue
        L = an["dur"]
        starts = [max(0.0, min(L - 31, L * p)) for p in (0.3, 0.7)] if L > 70 else [max(0.0, L / 2 - 15)]
        ex = []
        for s0 in starts:
            r, cost = listen(f, s0 + an["in"] / M.SR, L, style)
            usd += cost
            ex.append(r)
        side = json.loads((f.with_name(f.name + ".json")).read_text(encoding="utf-8")) if f.with_name(f.name + ".json").exists() else {}
        c = {"file": key, "sha1": h, "style": style, "title": t["title"], "artist": t["artist"], "license": t["license"],
             "ai_made": bool(side.get("ai_made")), "length_s": round(L), "lufs": an["lufs"], "lead_s": an["lead"], "excerpts": ex}
        c["score"] = score(c)
        cache[key] = c
        sp.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        rows.append(c)
        v = ",".join(sorted({x.get("vocals", "?") for x in ex}))
        print(f"  {c['score']:4.1f}  {t['title'][:38]:38} vocals {v:8} {ex[0].get('genre', '')[:30]}", flush=True)
    rows.sort(key=lambda r: -r["score"])
    print(f"\n{len(rows)} tracks ranked (this run ~${usd:.2f}):")
    for r in rows:
        ex = r["excerpts"]
        v = ",".join(sorted({x.get("vocals", "?") for x in ex}))
        dis = "; ".join(sorted({str(x.get("distracting", "")) for x in ex if str(x.get("distracting", "")).lower() not in ("", "none")}))
        print(f"  {r['score']:4.1f}  {r['title'][:36]:36} {r['artist'][:16]:16} {r['length_s'] // 60}:{r['length_s'] % 60:02d} "
              f"vocals {v:8} {'AI ' if r['ai_made'] else ''}{ex[0].get('genre', '')[:28]:28} {dis[:60]}")


if __name__ == "__main__":
    main()
