"""Music for a look that has none yet, found and curated by itself, so Truman approves the music together with the
sample instead of in a round of its own. For a look in config/aesthetics.json it finds CC0 tracks in the look's music
style, has the audio model screen them, curates a playlist into music/<look>/, logs every track in the asset ledger and
sets the look's `music_dirs`.

  .venv\\Scripts\\python tools\\music_auto.py <look-id> [--scene <scene>] [--max-screen 30] [--budget 2.0] [--n 24]
      [--no-ai] [--dry-run]

1. A look whose `music_dirs` already hold 15 or more tracks with complete sidecars (tools/music.py's loader decides) is
   done, and so is a look whose music is "none" (the underwater station's drone). Minecraft looks only ever use
   Mojang's allowlist in music/: tools/mc_music.py check runs and nothing is fetched.
2. Screened pools under music/_candidates/<style>/ whose style is the look's (the genre family named first in its
   `music`: lofi, jazz, synthwave, piano, acoustic, orchestral ...) are reused as they are. Short of clean tracks, it
   screens the pools' unscreened tracks first, then fetches new ones with tools/music_fetch.py from the checked CC0
   sources for the style (HoliznaCC0 albums on Free Music Archive and open-lofi categories, SOURCES below) into
   music/_candidates/<family>/. At most --max-screen tracks are screened in all.
3. tools/music_screen.py screens them with the Azure audio model (about $0.04 a track) in small batches; the run stops
   before its audio-model spend in out/azure_usage.jsonl (azure_ai.spend) would pass --budget. A clean track has no
   vocals of any kind, a screen score of 8.5 or more, a style match of 7 or more, nothing distracting like speech or
   sirens, and lasts 100 s or more.
4. --n tracks (default 24) are copied into music/<look>/ with their sidecars (plus `picked`) and a screen.json. When the
   look's entry lists `music_favorites` (paths under music/, or file names in the pools), tools/music_like.py curates
   around them; otherwise the best screen scores win, spread over several artists and albums, and tracks no other
   look plays come first. --no-ai leaves out AI-made tracks (open-lofi is made with Suno).
5. Every track gets a row in docs/asset-ledger.csv, the look's `music_dirs` is set in config/aesthetics.json (only that
   key is written, the file keeps its layout) and music/<look>/README.md gets the report: tracks, artists, licenses,
   how many are AI-made (with any, YouTube's "AI use" answer is Yes) and the spend.

CC0 only, or Mojang's allowlist for Minecraft looks: a style the CC0 sources can't fill stops with a report, because
any other license needs Truman's OK; when 15 tracks are out of reach even if every candidate came out clean, it stops
before spending anything. Choices are deterministic (sorted, no randomness). --dry-run prints the plan and fetches,
screens and writes nothing. Exit codes: 0 done or nothing to do, 1 an error, 2 not enough music (a dry run too).
"""
import argparse
import datetime
import hashlib
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys

from cozy.paths import ROOT, PY, rel
from cozy.media import probe
import music as M  # noqa: E402

CAND = ROOT / "music" / "_candidates"
TODAY = datetime.date.today().isoformat()
MIN_TRACKS = 15        # a look with this many tracks has music; fewer clean ones than this make no playlist
MIN_LENGTH = 100.0     # s
MIN_SCORE = 8.5        # tools/music_screen.py score, as tools/music_like.py `clean`
MIN_MATCH = 7.0        # mean style match over the excerpts; lower is a poor fit
YIELD = 0.7            # share of screened tracks that came out clean for the ramen alley (98 of 133)
CALL_USD = 0.02        # one excerpt heard by the audio model, while the spend log has none
MARGIN = 1.5           # batches are sized as if every track cost this much more (retries when the model rambles)
BATCH = 8              # tracks per music_screen.py call; the spend is read again between calls
DISTRACTING = re.compile(r"(?i)speech|spoken|voice|vocal|lyric|talking|siren|alarm|scream|shout")
CC0 = re.compile(r"(?i)\bCC0\b|publicdomain/zero")
NEEDS_OK = ("Pixabay Music (its own license), Kevin MacLeod on incompetech.com (CC BY 4.0) or the YouTube Audio Library "
            "(downloads only in Truman's YouTube Studio)")

# A style's genre family, by the words that name it. The first one named is the style's own (it picks the pools and
# the candidate folder); the others widen the sources. "chiptune-free" or "no chiptune" rules a family out.
FAMILIES = (
    ("lofi", r"lo-?fi|chillhop|hip[ -]?hop|boom-?bap"),
    ("jazz", r"jazz\w*|bossa( nova)?|lounge|swing|saxophone"),
    ("synthwave", r"synthwave|synths?|retrowave|vaporwave|outrun"),
    ("downtempo", r"downtempo|trip[ -]?hop|chillwave|electronica"),
    ("ambient", r"ambient|drones?|meditation|dreamscape"),
    ("piano", r"piano"),
    ("acoustic", r"acoustic|guitars?|ukulele|folk|celtic"),
    ("orchestral", r"orchestral|orchestra|strings|celesta|harps?|cinematic|classical|chamber"),
    ("carols", r"carols?|christmas|holiday"),
    ("chiptune", r"chiptunes?|chip ?music|8-?bit"),
)

# The checked CC0 sources of each family, best first (terms: ambience-audio skill "Music sources", 2026-10-19), as
# (tools/music_fetch.py source, what, about how many tracks). fma: HoliznaCC0's albums on Free Music Archive, chosen by
# the genres and titles of the discography (read 2026-10-20; each track's own page must still show CC0 when it is
# fetched). openlofi: categories of github.com/btahir/open-lofi, all lofi, made with Suno (ai_made). Only the families
# a look's style names are fetched, so the Christmas and chiptune albums only serve looks that ask for them.
SOURCES = {
    "lofi": [("fma", "holiznacc0/lo-fi-and-chill", 33), ("openlofi", "chillhop", 8), ("fma", "holiznacc0/public-domain-lofi", 57),
             ("openlofi", "late-night", 18), ("fma", "holiznacc0/city-slacker", 12), ("openlofi", "seasonal-weather", 27),
             ("fma", "holiznacc0/summer-air-lo-fi", 5), ("openlofi", "activities", 29), ("fma", "holiznacc0/winter-lofi", 5),
             ("openlofi", "asian-lofi", 8), ("fma", "holiznacc0/ocean-memory-lo-fi-chill", 5), ("openlofi", "soul-rnb", 21),
             ("fma", "holiznacc0/lazy-summer-lofi-1", 4), ("fma", "holiznacc0/spring-at-last-lofi-tape", 4)],
    "jazz": [("openlofi", "jazzhop", 12), ("fma", "holiznacc0/busted-guitar-jazz", 4), ("fma", "holiznacc0/busted-guitar-lofi-edit", 4),
             ("fma", "holiznacc0/be-happy-with-who-you-are", 14), ("openlofi", "soul-rnb", 21), ("fma", "holiznacc0/city-slacker", 12)],
    "synthwave": [("fma", "holiznacc0/waves-of-nostalgia-2", 9), ("openlofi", "late-night", 18), ("fma", "holiznacc0/we-drove-all-night", 7)],
    "downtempo": [("fma", "holiznacc0/only-in-the-milky-way-part-3", 9), ("openlofi", "ambient-lofi", 21),
                  ("fma", "holiznacc0/transformations", 6), ("fma", "holiznacc0/only-in-the-milky-way-part-1", 7)],
    "ambient": [("openlofi", "ambient-lofi", 21), ("fma", "holiznacc0/space-sleep-meditation", 16),
                ("fma", "holiznacc0/gamer-soundtrack-caves", 5), ("fma", "holiznacc0/transformations", 6)],
    "piano": [("fma", "holiznacc0/background-music", 20), ("fma", "holiznacc0/lullabies-for-the-end-of-the-world", 5)],
    "acoustic": [("fma", "holiznacc0/busted-guitar-lofi-edit", 4), ("fma", "holiznacc0/nature-spirit", 6),
                 ("fma", "holiznacc0/gamer-soundtrack-quiet-towns", 4), ("fma", "holiznacc0/busted-guitar-jazz", 4)],
    "orchestral": [("openlofi", "hybrid", 8), ("fma", "holiznacc0/scores", 1)],
    "carols": [("fma", "holiznacc0/a-lo-fi-christmas-special", 4), ("fma", "holiznacc0/a-synth-wave-christmas-special", 5)],
    "chiptune": [("fma", "holiznacc0/chiptunes", 13), ("fma", "holiznacc0/retro-gamer-soundtrack", 37),
                 ("fma", "holiznacc0/gamer-soundtrack-beginnings", 8), ("fma", "holiznacc0/ruby-chiptunes", 5),
                 ("fma", "holiznacc0/amethyst-chiptunes", 5)],
}
# open-lofi category -> the album label tools/music_fetch.py writes into its sidecars (catalog.json, 2026-10-20)
OPENLOFI = {"chillhop": "Chillhop & Cozy Beats", "jazzhop": "Jazz Lounge & Bookstore Grooves",
            "ambient-lofi": "Ambient Drift & Dreamscapes", "soul-rnb": "Soul, Slow Jams & Warm Rooms",
            "asian-lofi": "Asian & Zen Lo-Fi", "funk-soul": "Funk, Soul & Retro Bounce",
            "seasonal-weather": "Seasons, Rain & Weather", "late-night": "Late Night, Neon & After Hours",
            "activities": "Focus, Rituals & Daily Routines", "hybrid": "Hybrid, World & Cinematic"}


def families(text):
    """(the genre families a music style names, in order of first mention; the families it rules out)."""
    t = str(text or "").lower()
    first, out = {}, set()
    for fam, pat in FAMILIES:
        for m in re.finditer(rf"(?<![a-z0-9])(?:{pat})(?![a-z0-9])", t):
            if re.match(r"[- ]?free\b", t[m.end():]) or re.search(r"\b(?:no|non|not|without)[- ]$", t[:m.start()]):
                out.add(fam)
            else:
                first.setdefault(fam, m.start())
    return [f for f in sorted(first, key=first.get) if f not in out], out


def style_words(music):
    """The look's music style without its notes in parentheses: '' for a look without music ("none (drone)"), and the
    alternative of "none (sleep) or soft piano"."""
    s, prev = str(music or ""), None
    while s != prev:
        prev, s = s, re.sub(r"\s*\([^()]*\)", "", s)
    s = s.strip()
    m = re.match(r"(?i)none\b\s*(?:or\b\s*(.*))?$", s)
    return (m.group(1) or "").strip() if m else s


def screen_style(words, aes, brief):
    """What the audio model is told the look wants, built as tools/music_screen.py `style_for` builds it."""
    where = ", ".join(str(brief[k]) for k in ("setting", "time", "weather") if brief.get(k))
    return f"{words} for {where or aes.get('title') or 'a cozy ambience video'}"


def side(audio):
    """A track's sidecar (<file>.json, else <stem>.json) as a dict."""
    p = pathlib.Path(audio)
    s = p.with_name(p.name + ".json")
    s = s if s.exists() else p.with_suffix(".json")
    return json.loads(s.read_text(encoding="utf-8")) if s.exists() else {}


def mean(xs):
    xs = [float(x or 0) for x in xs]
    return sum(xs) / len(xs) if xs else 0.0


def why_not(v):
    """'' when a tools/music_screen.py verdict is clean, else the reason it isn't."""
    ex = v.get("excerpts") or []
    if not ex:
        return "not heard"
    if any(x.get("vocals") != "none" for x in ex):
        return "vocals"
    if float(v.get("score") or 0) < MIN_SCORE:
        return "low score"
    if mean(x.get("style_match") for x in ex) < MIN_MATCH:
        return "poor fit"
    if any(DISTRACTING.search(str(x.get("distracting") or "")) for x in ex):
        return "distracting"
    if float(v.get("length_s") or 0) < MIN_LENGTH:
        return "under 100 s"
    return ""


def pool(d):
    """A candidate folder: its tracks with complete sidecars, its screen.json, the styles it was screened for and the
    families it serves (its name's, and the first family of each of those styles)."""
    sp = d / "screen.json"
    scr = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    styles = sorted({str(v.get("style") or "") for v in scr.values()} - {""})
    fams = set(families(d.name)[0][:1])
    for s in styles:
        fams.update(families(s)[0][:1])
    tracks = M.scan_one(d)
    names = {pathlib.Path(t["path"]).name for t in tracks}
    clean = sum(1 for k, v in scr.items() if k in names and not why_not(v))
    return {"dir": d, "tracks": tracks, "screen": scr, "styles": styles, "families": fams, "clean": clean,
            "screened": sum(1 for k in scr if k in names)}


def used_elsewhere(doc, look):
    """(file name, size) of every track in another look's music folders (the Mojang root aside): copies keep both."""
    out = set()
    for k, a in doc["aesthetics"].items():
        for d in (a.get("music_dirs") or []) if k != look else []:
            p = ROOT / d
            if p.is_dir() and p.resolve() != (ROOT / "music").resolve():
                out |= {(f.name, f.stat().st_size) for f in p.iterdir() if f.suffix.lower() in M.AUDIO_EXT}
    return out


def gather(pools, used, taken, no_ai):
    """The clean candidates of the pools (one per content hash and file name), their unscreened tracks as
    (pool, track, sidecar), and why the others are out {reason: count}."""
    cands, unscreened, skipped, hashes, names, pending = [], [], {}, set(), set(taken), set()

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    for P in pools:
        for t in P["tracks"]:
            f = pathlib.Path(t["path"])
            sd = side(f)
            if not CC0.search(f"{t.get('license')} {t.get('license_url')}"):
                skip("not CC0 (needs Truman's OK)")
                continue
            if no_ai and sd.get("ai_made"):
                skip("AI-made (--no-ai)")
                continue
            if f.name in names:
                skip("already picked or a duplicate")
                continue
            v = P["screen"].get(f.name)
            if v is None:
                if f.name not in pending:
                    pending.add(f.name)
                    unscreened.append((P, t, sd))
                continue
            why = why_not(v)
            if why:
                skip(why)
                continue
            if v.get("sha1") in hashes:
                skip("already picked or a duplicate")
                continue
            hashes.add(v.get("sha1"))
            names.add(f.name)
            ex = v["excerpts"]
            cands.append({"path": f, "name": f.name, "pool": P["dir"], "title": t["title"], "artist": t["artist"],
                          "album": sd.get("album") or "", "ai_made": bool(sd.get("ai_made")), "score": float(v["score"]),
                          "match": mean(x.get("style_match") for x in ex), "calm": mean(x.get("calm") for x in ex),
                          "lead": float(v.get("lead_s") or 0), "verdict": v, "used": (f.name, f.stat().st_size) in used})
    return cands, [u for u in unscreened if pathlib.Path(u[1]["path"]).name not in names], skipped


def seconds(path):
    """A file's duration from ffprobe, or None."""
    try:
        return float(probe(path, "format=duration", check=False)["format"]["duration"])
    except (KeyError, ValueError):
        return None


def interleave(items, key):
    """Round robin over the groups of `items` (in order of first appearance), so a list cut short still spans them."""
    groups = {}
    for x in items:
        groups.setdefault(key(x), []).append(x)
    out = []
    while any(groups.values()):
        for g in groups.values():
            if g:
                out.append(g.pop(0))
    return out


def source_of(sd):
    """The SOURCES entry (source, what) a candidate's sidecar says it came from, or None."""
    src = str(sd.get("source") or "")
    m = re.search(r"freemusicarchive\.org/music/([^/]+/[^/]+)/", src)
    if m:
        return ("fma", m.group(1))
    if "open-lofi" in src:
        return next((("openlofi", k) for k, v in OPENLOFI.items() if v == sd.get("album")), None)
    return None


def fetch_plan(fams, excluded, no_ai, target, n):
    """({(source, what): (new tracks, tracks the target already holds from it)}, tracks left in the sources after it)
    for n new tracks: round robin over the sources of the style's families, two a round from each source of its own
    family and one from each of the others', each up to its size less what the target pool already holds."""
    have = {}
    for t in M.scan_one(target):
        k = source_of(side(t["path"]))
        if k:
            have[k] = have.get(k, 0) + 1
    srcs = {}
    for i, fam in enumerate(f for f in fams if f not in excluded):
        for kind, what, size in SOURCES.get(fam, []):
            if (kind, what) not in srcs and not (no_ai and kind == "openlofi"):
                srcs[(kind, what)] = {"weight": 2 if i == 0 else 1, "room": max(0, size - have.get((kind, what), 0)), "new": 0}
    left = n
    while left > 0 and any(s["room"] for s in srcs.values()):
        for s in srcs.values():
            for _ in range(s["weight"]):
                if left > 0 and s["room"] > 0:
                    s["new"], s["room"], left = s["new"] + 1, s["room"] - 1, left - 1
    return {k: (s["new"], have.get(k, 0)) for k, s in srcs.items() if s["new"]}, sum(s["room"] for s in srcs.values())


def fetch(plan, target):
    """tools/music_fetch.py for each source of the plan (it reads the license of every track and refuses anything
    but CC0); -> the new tracks in the target folder (music.py records)."""
    target.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in target.iterdir()}
    for (kind, what), (k, have) in plan.items():
        print(f"fetch {kind} {what}: {k} new", flush=True)
        r = subprocess.run([PY, str(ROOT / "tools" / "music_fetch.py"), kind, what, "--to", str(target), "--max", str(have + k)])
        if r.returncode:
            print(f"  ! music_fetch.py {kind} {what} failed (exit {r.returncode}); going on with the other sources")
    return [t for t in M.scan_one(target) if pathlib.Path(t["path"]).name not in before]


def call_usd():
    """What hearing one excerpt has cost on average (purpose "music screen" in out/azure_usage.jsonl), or CALL_USD."""
    import azure_ai
    xs = [float(r.get("usd_est") or 0) for r in azure_ai.usage_records() if r.get("purpose") == "music screen"]
    return sum(xs) / len(xs) if xs else CALL_USD


def audio_spend(since):
    """This run's spend: the audio deployment's share of azure_ai.spend since the run started (other tools log their
    vision calls to the same file at the same time, and those are not this run's)."""
    import azure_ai
    dep = azure_ai.CFG.get("audio_deployment") or ""
    return sum(usd for k, (_, usd) in azure_ai.spend(since)[1].items() if k.split(" ")[0] == dep)


def screen(files, style, budget, since, per_track):
    """tools/music_screen.py on the files, BATCH at a time. Before each batch the run's spend is read from the log
    (audio_spend) and the batch is sized to stay under the budget even if each track cost MARGIN times the usual;
    -> how many files were screened."""
    done = 0
    while done < len(files):
        spent = audio_spend(since)
        k = min(BATCH, len(files) - done, int(max(0.0, budget - spent) // (per_track * MARGIN)))
        if k <= 0:
            print(f"budget: ${spent:.2f} of ${budget:.2f} spent, so {len(files) - done} track(s) stay unscreened")
            break
        r = subprocess.run([PY, str(ROOT / "tools" / "music_screen.py"), *map(str, files[done: done + k]), "--style", style])
        if r.returncode:
            print(f"  ! music_screen.py failed (exit {r.returncode}; az login?), so the screening stops here")
            break
        done += k
    return done


def choose(cands, n):
    """n tracks: those no other look plays first, then by screen score (style match, calm and a prompt start break
    ties, then the name), at most 60% by one artist when there are several and a quarter (3 or more) from one album;
    the caps ease only when the candidates can't fill n otherwise."""
    order = sorted(cands, key=lambda c: (c["used"], -c["score"], -c["match"], -c["calm"], c["lead"], c["name"]))
    per_artist = math.ceil(0.6 * n) if len({c["artist"] for c in cands}) > 1 else n
    per_album = max(3, math.ceil(n / 4))
    pick, names = [], set()
    for ca, cb in ((per_artist, per_album), (per_artist, n), (n, n)):
        for c in order:
            if len(pick) < n and c["name"] not in names \
                    and sum(p["artist"] == c["artist"] for p in pick) < ca \
                    and sum((p["artist"], p["album"]) == (c["artist"], c["album"]) for p in pick) < cb:
                pick.append(c)
                names.add(c["name"])
    return pick


def copy_in(picks, dst, look):
    """The picks with their sidecars (plus `picked`) into the look's folder."""
    dst.mkdir(parents=True, exist_ok=True)
    for c in picks:
        shutil.copy2(c["path"], dst / c["name"])
        sd = side(c["path"])
        sd["picked"] = f"tools/music_auto.py for {look} ({TODAY}): screen score {c['score']:g}, from {rel(c['pool'])}"
        (dst / (c["name"] + ".json")).write_text(json.dumps(sd, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_screen(dst, pools):
    """dst/screen.json: the screen verdicts of the folder's tracks, from the pools they came from, so
    tools/music_samples.py --top and tools/music_like.py can rank the playlist as they rank a pool."""
    dst.mkdir(parents=True, exist_ok=True)
    sp = dst / "screen.json"
    out = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    for t in M.scan_one(dst):
        name = pathlib.Path(t["path"]).name
        v = next((P["screen"][name] for P in pools if name in P["screen"]), None)
        if v and name not in out:
            out[name] = v
    sp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def log_ledger(dst, title):
    """One row per track of the folder in docs/asset-ledger.csv (tools/music.py ledger: upsert keyed by path)."""
    tracks = [{**t, "hash": hashlib.sha1(pathlib.Path(t["path"]).read_bytes()).hexdigest()[:20]} for t in M.scan_one(dst)]
    M.ledger({"tracks": tracks}, kind=f"music ({title} playlist, chosen by tools/music_auto.py)",
             modified="none yet (loudness-normalized and crossfaded when the video's playlist is built)")
    return len(tracks)


def members(text, i):
    """[(key, value start, value end)] of the JSON object whose "{" is at text[i], and the index of its "}"."""
    ws, dec, out = re.compile(r"\s*"), json.JSONDecoder(), []
    i = ws.match(text, i + 1).end()
    while text[i] != "}":
        if text[i] != '"':
            raise ValueError(f"a key expected at {i}")
        key, i = json.decoder.scanstring(text, i + 1)
        i = ws.match(text, i).end()
        if text[i] != ":":
            raise ValueError(f"':' expected at {i}")
        vs = ws.match(text, i + 1).end()
        _, ve = dec.raw_decode(text, vs)
        out.append((key, vs, ve))
        i = ws.match(text, ve).end()
        if text[i] == ",":
            i = ws.match(text, i + 1).end()
    return out, i


def set_music_dirs(path, look, dirs):
    """Writes the look's "music_dirs" into the aesthetics file and changes nothing else: the value is replaced where it
    is, or the key goes right after the look's "music" (as the ramen alley has it), else at the end of its entry. The
    result must parse to the same document with only that key set, or nothing is written."""
    text = path.read_bytes().decode("utf-8")
    want = json.loads(text)
    want["aesthetics"][look]["music_dirs"] = dirs
    top, _ = members(text, text.index("{"))
    looks, _ = members(text, next(vs for k, vs, _ in top if k == "aesthetics"))
    keys, close = members(text, next(vs for k, vs, _ in looks if k == look))
    span = {k: (vs, ve) for k, vs, ve in keys}
    val = json.dumps(dirs, ensure_ascii=False)
    if "music_dirs" in span:
        vs, ve = span["music_dirs"]
        new = text[:vs] + val + text[ve:]
    else:
        at = span["music"][1] if "music" in span else (keys[-1][2] if keys else close)
        new = text[:at] + (", " if keys else "") + f'"music_dirs": {val}' + text[at:]
    if json.loads(new) != want:
        sys.exit(f"music_dirs: the edit of {path} did not validate; nothing written")
    path.write_bytes(new.encode("utf-8"))


def hours(s):
    return f"{int(s // 3600)} h {int(s % 3600 // 60)} min" if s >= 3600 else f"{int(s // 60)} min"


def summary(look, aes, dst, style, spend, screened, pools):
    """The report (README.md lines) of the look's folder: tracks, artists, licenses, AI-made, spend, the tracklist."""
    tracks = M.scan_one(dst)
    sp = dst / "screen.json"
    scr = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    rows, total, ai, artists, lic = [], 0.0, 0, {}, {}
    for i, t in enumerate(tracks, 1):
        sd, v = side(t["path"]), scr.get(pathlib.Path(t["path"]).name) or {}
        L = float(v.get("length_s") or seconds(t["path"]) or 0)
        total += L
        ai += bool(sd.get("ai_made"))
        artists[t["artist"]] = artists.get(t["artist"], 0) + 1
        lic[t["license"]] = lic.get(t["license"], 0) + 1
        rows.append(f"| {i} | {t['title']} | {t['artist']} | {sd.get('album') or ''} | {int(L) // 60}:{int(L) % 60:02d} | "
                    f"{v.get('score', '')} | {'yes' if sd.get('ai_made') else 'no'} |")
    count = lambda d: ", ".join(f"{k} {n}" for k, n in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
    return [f"# Music for {aes.get('title') or look} ({look})", "",
            f"Chosen by tools/music_auto.py on {TODAY} for \"{style}\". Truman approves it with the sample. Every track "
            "is in docs/asset-ledger.csv.", "",
            f"- {len(tracks)} tracks, {hours(total)} in all, from {', '.join(rel(p) for p in pools) or 'the folder'}",
            f"- Artists: {count(artists)}. Licenses: {count(lic)}",
            (f"- AI-made: {ai} of {len(tracks)} (open-lofi, made with Suno), so YouTube's \"AI use\" answer is Yes for a "
             "video with this playlist. Public text still never mentions AI" if ai else "- AI-made: none"),
            f"- Screened this run: {screened} track(s), Azure spend this run about ${spend:.2f}", "",
            "| # | Track | Artist | Album | Length | Screen score | AI-made |", "|---|---|---|---|---|---|---|", *rows]


def minecraft(a, aes, aes_path):
    """Minecraft looks: Mojang's allowlist in music/ and nothing else (DECISIONS 2026-10-16 "Minecraft music")."""
    tracks = [t for t in M.scan_one(ROOT / "music") if M.is_mojang(t)]
    mc = ROOT / "tools" / "mc_music.py"
    print(f"  a Minecraft look: only Mojang's allowlist in music/ (config/minecraft_music.json), never anything else; "
          f"{len(tracks)} allowed tracks there")
    if a.dry_run:
        print(f"  plan: {'tools/mc_music.py check, then ' if mc.exists() else ''}music_dirs [\"music\"]; nothing is fetched"
              "\n  dry run: nothing checked or written")
        return 0
    if mc.exists() and subprocess.run([PY, str(mc), "check"]).returncode:
        print("  ! mc_music.py check did not pass: check the Creator-Safe Playlist by hand, or set \"use\": false for "
              "the tracks marked ?? and import again")
        return 1
    if len(tracks) < MIN_TRACKS:
        print(f"  only {len(tracks)} allowed tracks in music/: run tools/mc_music.py import (it copies them from your "
              "Minecraft install)")
        return 2
    if aes.get("music_dirs") != ["music"]:
        set_music_dirs(aes_path, a.look, ["music"])
        print(f"  music_dirs [\"music\"] set in {aes_path}")
    print(f"  music: {len(tracks)} Mojang tracks in music/")
    return 0


def find_favorites(names):
    """The look's music_favorites as files: paths under the repo, or file names looked up in the candidate pools."""
    out = []
    pools = sorted(d for d in CAND.iterdir() if d.is_dir()) if CAND.is_dir() else []
    for f in names:
        p = ROOT / f
        if not p.is_file():
            p = next((d / pathlib.Path(f).name for d in pools if (d / pathlib.Path(f).name).is_file()), None)
        if p is None:
            sys.exit(f"music_favorites: {f} is neither a file nor a track in music/_candidates/")
        out.append(p.resolve())
    return out


def around_favorites(favs, folders, n, dst, no_ai):
    """tools/music_like.py: n clean tracks most like the favorites into dst. dst (empty) is its first --in folder, so
    its like.json lands next to the playlist instead of replacing a pool's. With --no-ai the AI-made picks it copied
    are taken out again. -> its exit code."""
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [PY, str(ROOT / "tools" / "music_like.py"), *map(str, favs)]
    for d in [dst, *folders]:
        cmd += ["--in", str(d)]
    rc = subprocess.run(cmd + ["--pick", str(n), "--to", str(dst)]).returncode
    for t in M.scan_one(dst) if no_ai and not rc else []:
        if side(t["path"]).get("ai_made"):
            p = pathlib.Path(t["path"])
            print(f"  --no-ai: {p.name} is AI-made, out again")
            p.with_name(p.name + ".json").unlink()
            p.unlink()
    return rc


def run(a):
    since = datetime.datetime.now().isoformat(timespec="seconds")
    found = _the_look(a)
    if isinstance(found, int):
        return found
    aes_path, doc, aes, title, brief, scene_dirs = found

    # 1. music already, or none wanted
    found = _music_wanted(a, aes, scene_dirs)
    if isinstance(found, int):
        return found
    kept, have, words = found
    found = _style_and_families(aes, brief, words)
    if isinstance(found, int):
        return found
    fams, excluded, style, primary = found
    dst, rel_dst, in_dst, existing, n_want = _music_now(a, have)

    # 2. pools that fit, and what more to screen
    found = _fitting_pools(a, doc, aes, primary, have, in_dst)
    if isinstance(found, int):
        return found
    fit, used, taken, favs = found

    def take_stock(label):
        cands, unscreened, skipped = gather(fit, used, taken, a.no_ai)
        fresh = sum(not c["used"] for c in cands)
        print(f"  {label}: {len(cands)}" + (f" ({len(cands) - fresh} already play in another look)" if len(cands) > fresh else "")
              + (f"; left out: {', '.join(f'{k} {v}' for k, v in sorted(skipped.items()))}" if skipped else ""))
        return cands, unscreened, fresh

    cands, unscreened, fresh = take_stock("clean tracks that fit")
    need, per_track, to_screen, local, target, plan, room, n_new = _screen_plan(a, fams, excluded, primary, fit, unscreened, n_want, fresh)
    rc = _reachable(a, existing, n_want, cands, need, to_screen, local, n_new, room)
    if rc is not None:
        return rc
    new_dirs = _then(kept, rel_dst, aes_path, favs, n_want)
    if a.dry_run:
        print("  dry run: nothing fetched, screened, copied or written")
        return 0

    # 3. fetch and screen
    screened = 0
    if local or plan:
        screened = _fetch_and_screen(a, plan, target, local, style, since, per_track, to_screen)
        fit = [pool(P["dir"]) for P in fit] + ([pool(target)] if target.is_dir() and all(P["dir"] != target for P in fit) else [])
        cands, unscreened, fresh = take_stock("clean tracks that fit now")
    rc = _too_few(a, existing, n_want, cands, unscreened, room)
    if rc is not None:
        return rc

    # 4. curate, 5. ledger, music_dirs, report
    rc = _curate(a, favs, in_dst, fit, n_want, dst, rel_dst, cands)
    if rc is not None:
        return rc
    return _report(a, aes, aes_path, dst, rel_dst, title, style, since, screened, fit, new_dirs)


def _the_look(a):
    """The look and the scene: an exit code to stop with, else (the aesthetics file, its document, the look, its title,
    the scene's brief, the scene's own music folders)."""
    aes_path = pathlib.Path(a.aesthetics).resolve()
    doc = json.loads(aes_path.read_text(encoding="utf-8"))
    if a.look not in doc["aesthetics"]:
        print(f"unknown look {a.look!r}; one of: {', '.join(doc['aesthetics'])}")
        return 1
    aes = doc["aesthetics"][a.look]
    title = aes.get("title") or a.look
    brief, scene_dirs = {}, []
    if a.scene:
        sd = ROOT / "scenes" / a.scene
        if not sd.is_dir():
            print(f"no scene {a.scene} in scenes/")
            return 1
        brief = json.loads((sd / "brief.json").read_text(encoding="utf-8")) if (sd / "brief.json").exists() else {}
        sc = json.loads((sd / "scene.json").read_text(encoding="utf-8")) if (sd / "scene.json").exists() else {}
        if sc.get("aesthetic") not in (None, a.look):
            print(f"  note: scene {a.scene} is in the look {sc['aesthetic']}, not {a.look}")
        m = (sc.get("audio") or {}).get("music") or {}
        scene_dirs = m.get("dirs") or ([m["dir"]] if m.get("dir") else [])
    print(f"{a.look}: {title}")
    if aes.get("franchise") == "Minecraft":
        return minecraft(a, aes, aes_path)
    return aes_path, doc, aes, title, brief, scene_dirs


def _music_wanted(a, aes, scene_dirs):
    """An exit code when the look has music or wants none, else (its music folders but music/, their tracks, its style)."""
    dirs = list(aes.get("music_dirs") or [])
    kept = [d for d in dirs if (ROOT / d).resolve() != (ROOT / "music").resolve()]
    if len(kept) < len(dirs):
        print("  ! its music_dirs list music/, Mojang's allowlist, which only Minecraft looks may use: left out")
    have = [t for t in M.scan([ROOT / d for d in kept]) if not M.is_mojang(t)]
    own = [t for t in M.scan([ROOT / d for d in scene_dirs]) if not M.is_mojang(t)] if scene_dirs else []
    if len(own) >= MIN_TRACKS:
        print(f"  scene {a.scene} has its own music: {len(own)} tracks in {', '.join(scene_dirs)}; nothing to do")
        return 0
    if len(have) >= MIN_TRACKS:
        print(f"  has music: {len(have)} tracks in {', '.join(kept)}; nothing to do")
        return 0
    words = style_words(aes.get("music"))
    if not words:
        print(f"  its music is {aes.get('music')!r}: no music for this look; nothing to do")
        return 0
    return kept, have, words


def _style_and_families(aes, brief, words):
    """Exit code 2 without a known source, else (the families, those ruled out, the style to screen for, the first family)."""
    fams, excluded = families(words)
    style = screen_style(words, aes, brief)
    print(f"  style: {style}")
    if not fams:
        print(f"  no checked CC0 source is known for {words!r}. Other sources need Truman's OK: {NEEDS_OK}")
        return 2
    primary = fams[0]
    print(f"  families: {', '.join(fams)}" + (f" (not {', '.join(sorted(excluded))})" if excluded else ""))
    return fams, excluded, style, primary


def _music_now(a, have):
    dst = ROOT / "music" / a.look
    rel_dst = rel(dst)
    have_paths = {pathlib.Path(t["path"]).resolve() for t in have}
    in_dst = [t for t in M.scan_one(dst) if pathlib.Path(t["path"]).resolve() not in have_paths]
    existing = len(have) + len(in_dst)
    n_want = max(0, a.n - existing)
    print(f"  music now: {existing} tracks" if existing else "  music now: none")
    return dst, rel_dst, in_dst, existing, n_want


def _fitting_pools(a, doc, aes, primary, have, in_dst):
    """Exit code 1 for an AI-made favorite with --no-ai, else (the pools that fit, the tracks other looks play, the
    names already in the look's music, the favorites)."""
    pools = [pool(d) for d in sorted(CAND.iterdir()) if d.is_dir()] if CAND.is_dir() else []
    fit = [P for P in pools if primary in P["families"]]
    print(f"  pools in {rel(CAND)} (one fits when it serves {primary}):" + ("" if pools else " none"))
    for P in pools:
        print(f"    {P['dir'].name}: {len(P['tracks'])} tracks, {P['screened']} screened, {P['clean']} clean; serves "
              f"{', '.join(sorted(P['families'])) or 'no family'}: {'fits' if primary in P['families'] else 'does not fit'}")
    used = used_elsewhere(doc, a.look)
    taken = {pathlib.Path(t["path"]).name for t in have + in_dst}
    favs = find_favorites(aes.get("music_favorites") or [])
    if favs and a.no_ai and any(side(f).get("ai_made") for f in favs):
        print("  --no-ai, but a music favorite is AI-made: drop one or the other")
        return 1
    return fit, used, taken, favs


def _screen_plan(a, fams, excluded, primary, fit, unscreened, n_want, fresh):
    """How many more tracks are wanted and what to screen for them: (need, cost a track, how many to screen, those from
    the pools, the pool new ones go to, the fetch plan, what the sources have left, how many new)."""
    need = max(0, n_want - fresh)
    per_track = 2 * call_usd()
    to_screen = min(a.max_screen, math.ceil(need / YIELD), int(a.budget // (per_track * MARGIN))) if need else 0
    local = []
    for P, t, sd in interleave(unscreened, key=lambda x: (x[0]["dir"].name, x[2].get("album") or "")):
        if len(local) >= to_screen:
            break
        if (seconds(t["path"]) or MIN_LENGTH) >= MIN_LENGTH:
            local.append(pathlib.Path(t["path"]))
    target = next((P["dir"] for P in fit if families(P["dir"].name)[0][:1] == [primary]), CAND / primary)
    plan, room = fetch_plan(fams, excluded, a.no_ai, target, to_screen - len(local)) if to_screen > len(local) else ({}, 0)
    n_new = sum(k for k, _ in plan.values())
    if not need:
        print("  enough clean tracks: nothing to screen")
    elif not to_screen:
        print(f"  {need} more wanted, but ${a.budget:.2f} pays for no screening (about ${per_track:.3f} a track)")
    else:
        print(f"  {need} more wanted: screen {len(local) + n_new} (at most {a.max_screen}; about "
              f"${(len(local) + n_new) * per_track:.2f} of the ${a.budget:.2f} budget): {len(local)} from the pools, "
              f"{n_new} new into {rel(target)}")
        for (kind, what), (k, h) in plan.items():
            print(f"    {kind} {what}: {k}" + (f" (it holds {h} already)" if h else ""))
    return need, per_track, to_screen, local, target, plan, room, n_new


def _reachable(a, existing, n_want, cands, need, to_screen, local, n_new, room):
    """Exit code 2 when even a clean screening of every candidate can't make a playlist; a warning when it likely won't."""
    expect = existing + len(cands) + int((len(local) + n_new) * YIELD)
    best = existing + len(cands) + len(local) + n_new
    if n_want and best < MIN_TRACKS:
        more = ("A larger --max-screen or --budget could reach it." if room or to_screen < min(a.max_screen, math.ceil(need / YIELD))
                else "The checked CC0 sources have no more in this style.")
        print(f"  ! even if every candidate came out clean there would be {best} tracks, {MIN_TRACKS} needed, so this stops "
              f"before any spend. {more} Other sources need Truman's OK: {NEEDS_OK}")
        return 2
    if n_want and expect < MIN_TRACKS:
        print(f"  ! likely short: about {expect} clean tracks to expect, {MIN_TRACKS} needed. Other sources need "
              f"Truman's OK: {NEEDS_OK}")


def _then(kept, rel_dst, aes_path, favs, n_want):
    new_dirs = kept + ([rel_dst] if rel_dst not in kept else [])
    how = (f"around its favorites {', '.join(f.name for f in favs)} (tools/music_like.py)" if favs
           else "by screen score over several artists and albums, tracks no other look plays first")
    print(f"  then: {n_want} tracks into {rel_dst} {how}; their ledger rows; music_dirs {json.dumps(new_dirs)} in "
          f"{rel(aes_path)}; the report in {rel_dst}/README.md")
    return new_dirs


def _fetch_and_screen(a, plan, target, local, style, since, per_track, to_screen):
    new = fetch(plan, target) if plan else []
    new = [t for t in new if CC0.search(f"{t.get('license')} {t.get('license_url')}")
           and not (a.no_ai and side(t["path"]).get("ai_made")) and (seconds(t["path"]) or MIN_LENGTH) >= MIN_LENGTH]
    files = local + [pathlib.Path(t["path"]) for t in interleave(new, key=lambda t: source_of(side(t["path"])))]
    screened = screen(files[:to_screen], style, a.budget, since, per_track)
    return screened


def _too_few(a, existing, n_want, cands, unscreened, room):
    if existing + min(n_want, len(cands)) < MIN_TRACKS:
        if unscreened or room:
            print(f"  CC0 candidates remain ({len(unscreened)} unscreened in the pools, about {room} more in the sources): "
                  "a larger --max-screen or --budget may get there")
        print(f"not enough music for {a.look}: {existing + len(cands)} clean tracks in its style, {MIN_TRACKS} needed; "
              f"other sources need Truman's OK: {NEEDS_OK}")
        return 2


def _curate(a, favs, in_dst, fit, n_want, dst, rel_dst, cands):
    if n_want:
        if favs and not in_dst:
            rc = around_favorites(favs, sorted({P["dir"] for P in fit} | {f.parent for f in favs}), n_want, dst, a.no_ai)
            if rc:
                print(f"  ! music_like.py failed (exit {rc})")
                return 1
        else:
            if favs:
                print(f"  {rel_dst} holds tracks already, so this top-up goes by screen score, not the favorites")
            copy_in(choose(cands, n_want), dst, a.look)


def _report(a, aes, aes_path, dst, rel_dst, title, style, since, screened, fit, new_dirs):
    write_screen(dst, fit)
    rows = log_ledger(dst, title)
    set_music_dirs(aes_path, a.look, new_dirs)
    lines = summary(a.look, aes, dst, style, audio_spend(since), screened, [P["dir"] for P in fit])
    (dst / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(x for x in lines if not x.startswith("|")).rstrip())
    print(f"\nledger: {rows} rows upserted in docs/asset-ledger.csv; music_dirs {json.dumps(new_dirs)} set in "
          f"{rel(aes_path)}; report: {rel_dst}/README.md")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)   # in order with the subprocesses
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("look", help="the look's id in config/aesthetics.json")
    ap.add_argument("--scene", help="describe the wanted style with this scene's brief (setting, time, weather)")
    ap.add_argument("--max-screen", type=int, default=30, help="screen at most this many tracks in all (default 30)")
    ap.add_argument("--budget", type=float, default=2.0, help="stop screening before this run's audio-model spend passes "
                                                                "this many USD (default 2)")
    ap.add_argument("--n", type=int, default=24, help=f"tracks in the playlist (default 24, at least {MIN_TRACKS})")
    ap.add_argument("--no-ai", action="store_true", help="leave out AI-made tracks (open-lofi), so YouTube's AI answer can stay No")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; fetch, screen and write nothing")
    ap.add_argument("--aesthetics", default=str(ROOT / "config" / "aesthetics.json"), help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.n < MIN_TRACKS:
        sys.exit(f"--n must be {MIN_TRACKS} or more: fewer tracks repeat too often over 10 h")
    sys.exit(run(a))


if __name__ == "__main__":
    main()
