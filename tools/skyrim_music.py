"""Skyrim soundtrack -> music/skyrim (Truman 2026-11-08: the Skyrim look plays his own copy of the soundtrack album).

Only the allowlist in config/skyrim_music.json is used: the calm exploration, town and tavern pieces, never the combat
cues or the choir themes. Bethesda's fan video policy allows music from its games in fan videos with YouTube ads;
tools/music.py plays these tracks only for a look of the same franchise and adds the look's not-official disclaimer
to the credits. Uploads still go up Private until YouTube's copyright check is clear.

  list     every track in his album folder, with its allowlist status
  import   copy the allowed tracks ("use": true) into music/skyrim as sk_<title>.mp3, each with a tools/music.py
           sidecar (title, artist, source, license, attribution, franchise, origin); sk_* files no longer allowed
           are removed, so the folder mirrors the allowlist. --to <dir> imports elsewhere (music/_candidates/skyrim
           to screen them with tools/music_screen.py first)
  check    re-read Bethesda's fan video policy page before a new video: it must still allow music from their games

Usage (repo root):
  .venv\\Scripts\\python tools\\skyrim_music.py list [--src <album folder>]
  .venv\\Scripts\\python tools\\skyrim_music.py import [--src <album folder>] [--to music\\skyrim]
  .venv\\Scripts\\python tools\\skyrim_music.py check
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import sys
import urllib.request

from cozy.paths import ROOT, config
PREFIX = "sk_"


def album_files(src):
    """{'CD2/06 Jeremy Soule - Far Horizons.mp3': path} of the album folder, keyed as in the allowlist."""
    if not src:
        sys.exit("no album folder: pass --src <folder with CD1..CD4>, or put {\"source_dir\": \"<folder>\"} in "
                 "config/skyrim_music.local.json (this machine's, never committed)")
    d = pathlib.Path(src)
    if not d.is_dir():
        sys.exit(f"no album folder at {d}; pass --src <folder with CD1..CD4>")
    return {f"{p.parent.name}/{p.name}": p for p in sorted(d.rglob("*.mp3"))}


def file_name(title):
    return PREFIX + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") + ".mp3"


def cmd_list(cfg, files):
    T = cfg["tracks"]
    for k in sorted(set(files) | set(T)):
        t = T.get(k)
        status = "missing" if k not in files else ("USE" if t and t["use"] else "not used" if t else "never (not listed)")
        print(f"{k:58s} {status:10s} {t.get('why', '') if t else ''}")


def cmd_import(cfg, files, to):
    d = pathlib.Path(to)
    d.mkdir(parents=True, exist_ok=True)
    want = {}
    for k, t in cfg["tracks"].items():
        # a track a Content ID claim matched stays out for good (its `claim` says who and where): Tundra was claimed
        # on both Skyrim videos through a third party's track that samples it (2026-11-16)
        if t.get("claim") and t["use"]:
            sys.exit(f"{k}: \"use\" is true but it has a Content ID claim ({t['claim'].get('work', '?')}): it stays out")
        if not t["use"]:
            continue
        if k not in files:
            print(f"skip {k}: not in the album folder")
            continue
        name = file_name(t["title"])
        if name in want:
            sys.exit(f"two allowed tracks map to {name}")
        want[name] = (k, t)
    copied = 0
    for name, (k, t) in want.items():
        src, dst = files[k], d / name
        data = src.read_bytes()
        if not dst.exists() or dst.read_bytes() != data:
            shutil.copyfile(src, dst)
            copied += 1
        disc, num = k.split("/")[0], re.match(r"(?:cd\d+ )?(\d+)", k.split("/")[1])
        meta = {"title": t["title"], **cfg["sidecar"], "album": cfg["album"],
                "disc": int(disc[2:]) if disc[2:].isdigit() else disc, "track": int(num.group(1)) if num else None,
                "origin": f"Truman's own copy of the soundtrack album, {k} (sha1 {hashlib.sha1(data).hexdigest()[:16]})",
                "verified": cfg["verified"]}
        (d / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stale = [p for p in d.glob(PREFIX + "*") if p.name not in want and p.name.removesuffix(".json") not in want]
    for p in stale:
        p.unlink()
    print(f"import: {len(want)} tracks in {d} ({copied} copied, {len(want) - copied} unchanged); {len(stale)} stale file(s) removed")


def cmd_check(cfg):
    try:
        req = urllib.request.Request(cfg["policy_url"], headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:  # network or page format
        sys.exit(f"could not read the policy page ({e}); check {cfg['policy_url']} by hand")
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)).lower()
    missing = [p for p in cfg["policy_phrases"] if p.lower() not in flat]
    for p in cfg["policy_phrases"]:
        print(f"{'OK' if p not in missing else '??'}  \"{p}\"")
    if missing:
        print(f"Bethesda's policy page no longer says {missing}: read {cfg['policy_url']} and ask Truman before using the tracks")
        return 1
    print(f"the fan video policy still allows music from Bethesda's games ({cfg['policy_url']})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["list", "import", "check"])
    ap.add_argument("--src", help="the album folder (default: source_dir in config/skyrim_music.local.json, this machine's)")
    ap.add_argument("--to", default=str(ROOT / "music" / "skyrim"))
    a = ap.parse_args()
    cfg = config("skyrim_music")
    if a.cmd == "check":
        sys.exit(cmd_check(cfg))
    files = album_files(a.src or cfg["source_dir"])
    cmd_list(cfg, files) if a.cmd == "list" else cmd_import(cfg, files, a.to)


if __name__ == "__main__":
    main()
