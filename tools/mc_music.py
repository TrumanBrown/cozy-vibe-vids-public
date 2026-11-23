"""Minecraft soundtrack -> music/ (user decision 2026-10-16; docs/DECISIONS.md "Minecraft music").

Tracks come from the user's own Minecraft: Java Edition install (the newest asset index). Only the
allowlist in config/minecraft_music.json is used: Mojang-owned tracks that were on the official
Creator-Safe Playlist when verified. All C418 music and "Lava Chicken" are never used (third-party
Content ID claims), and nothing outside the allowlist is ever imported.

  list     every music file in the install, with its allowlist status
  import   copy the allowed tracks ("use": true) into music/ as mc_<name>.ogg, each with a
           tools/music.py sidecar (title, artist, source, license, attribution, album, origin).
           mc_* files that are no longer allowed are removed, so music/ mirrors the allowlist.
           (Mojang's not-official disclaimer is added to every credits.txt by tools/music.py.)
  check    re-verify the allowed tracks against the live Creator-Safe Playlist before a new video
           (Spotify's embed page: the playlist's first 100 tracks); --snapshot saves it to
           docs/reference/creator-safe-playlist-<date>.json

Usage (repo root):
  .venv\\Scripts\\python tools\\mc_music.py list
  .venv\\Scripts\\python tools\\mc_music.py import [--music-dir music] [--minecraft <.minecraft dir>]
  .venv\\Scripts\\python tools\\mc_music.py check [--snapshot]
Then tools/music.py plan + ledger, and tools/loop_master.py or the render pipeline as usual.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import urllib.request

from cozy.paths import ROOT, config
PREFIX = "mc_"


def minecraft_dir(arg):
    if arg:
        return pathlib.Path(arg)
    for p in (pathlib.Path(os.environ.get("APPDATA", "")) / ".minecraft", pathlib.Path.home() / ".minecraft",
              pathlib.Path.home() / "Library" / "Application Support" / "minecraft"):
        if (p / "assets" / "indexes").is_dir():
            return p
    sys.exit("no Minecraft: Java Edition install found; pass --minecraft <.minecraft dir> (from WSL: /mnt/c/Users/<you>/AppData/Roaming/.minecraft)")


def music_files(mc):
    """{'music/game/x.ogg': (index file, object path, sha1)} from the newest asset index."""
    idx = max((mc / "assets" / "indexes").glob("*.json"), key=lambda p: p.stat().st_mtime)
    out = {}
    for k, v in json.loads(idx.read_text())["objects"].items():
        if k.startswith(("minecraft/sounds/music/", "minecraft/sounds/records/")):
            h = v["hash"]
            out[k[len("minecraft/sounds/"):]] = (idx.name, mc / "assets" / "objects" / h[:2] / h, h)
    return out


def cmd_list(cfg, files):
    T = cfg["tracks"]
    for k in sorted(files):
        t = T.get(k)
        status = ("USE" if t["use"] else "safe, not used") if t else "never (not allowlisted)"
        print(f"{k:50s} {status:24s} {(t['title'] + ' - ' + t['artist']) if t else '':36s} {t.get('why', '') if t else ''}")
    gone = [k for k, t in T.items() if t["use"] and k not in files]
    if gone:
        print("allowed but missing from this install:", ", ".join(gone))


def cmd_import(cfg, files, music_dir):
    d = pathlib.Path(music_dir)
    d.mkdir(parents=True, exist_ok=True)
    side, want = cfg["sidecar"], {}
    for k, t in cfg["tracks"].items():
        if not t["use"]:
            continue
        if k not in files:
            print(f"skip {k}: not in this install")
            continue
        name = PREFIX + pathlib.PurePosixPath(k).stem + ".ogg"
        if name in want:
            sys.exit(f"two allowed tracks map to {name}")
        want[name] = (k, t)
    copied = 0
    for name, (k, t) in want.items():
        idx, obj, h = files[k]
        dst = d / name
        if not dst.exists() or dst.read_bytes() != obj.read_bytes():
            shutil.copyfile(obj, dst)
            copied += 1
        meta = {"title": t["title"], "artist": t["artist"], **side, "album": t.get("album", ""),
                "origin": f"the user's Minecraft: Java Edition install, minecraft/sounds/{k} (asset index {idx}, object {h})",
                "verified": cfg["verified"]}
        (d / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stale = [p for p in d.glob(PREFIX + "*") if p.name not in want and p.name.removesuffix(".json") not in want]
    for p in stale:
        p.unlink()
    print(f"import: {len(want)} tracks in {d} ({copied} copied, {len(want) - copied} unchanged); {len(stale)} stale file(s) removed")


def playlist(url):
    """[(title, artists)] of the first 100 tracks, from Spotify's server-rendered embed page."""
    pid = url.rstrip("/").split("/")[-1]
    req = urllib.request.Request(f"https://open.spotify.com/embed/playlist/{pid}", headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)

    def find(o):
        if isinstance(o, dict):
            if "trackList" in o:
                return o["trackList"]
            o = list(o.values())
        for v in o if isinstance(o, list) else []:
            r = find(v)
            if r:
                return r
        return None

    tl = find(json.loads(m.group(1))) if m else None
    return [(t["title"], t.get("subtitle", "")) for t in tl or []]


def cmd_check(cfg, snapshot):
    try:
        tl = playlist(cfg["playlist"])
    except Exception as e:  # network or page format
        sys.exit(f"could not read the playlist ({e}); check {cfg['playlist']} by hand")
    if not tl:
        sys.exit(f"the playlist page had no track list (Spotify changed it?); check {cfg['playlist']} by hand")
    bad = 0
    for k, t in cfg["tracks"].items():
        if t["use"]:
            ok = any(a.casefold() == t["title"].casefold() and t["artist"].casefold() in b.casefold() and "minecraft" in b.casefold()
                     for a, b in tl)
            bad += not ok
            print(f"{'OK' if ok else '??'}  {t['title']} - {t['artist']}")
    print(f"{len(tl)} playlist tracks read. OK = on the official Creator-Safe Playlist as a Mojang ('Minecraft') release. "
          + (f"{bad} track(s) marked ?? are not among them: check the playlist by hand, or set \"use\": false." if bad else "All allowed tracks found."))
    if snapshot:
        day = datetime.date.today().isoformat()
        p = ROOT / "docs" / "reference" / f"creator-safe-playlist-{day}.json"
        doc = {"playlist": "Minecraft Creator-Safe Playlist (official, Mojang Studios)", "url": cfg["playlist"], "retrieved": day,
               "method": f"https://open.spotify.com/embed/playlist/{cfg['playlist'].rstrip('/').split('/')[-1]} (server-rendered, "
                         "first 100 tracks of the playlist); tools/mc_music.py check",
               "description": "This playlist is a collection of tracks that you're welcome to use in the Minecraft content that you create. (Spotify playlist description)",
               "policy_url": cfg["sidecar"]["license_url"], "tracks": [{"title": a, "artists": b} for a, b in tl]}
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"snapshot -> {p.relative_to(ROOT)}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["list", "import", "check"])
    ap.add_argument("--music-dir", default=str(ROOT / "music"))
    ap.add_argument("--minecraft", help=".minecraft folder (default: the standard location)")
    ap.add_argument("--snapshot", action="store_true", help="check: save the playlist to docs/reference/")
    a = ap.parse_args()
    cfg = config("minecraft_music")
    if a.cmd == "check":
        sys.exit(1 if cmd_check(cfg, a.snapshot) else 0)
    files = music_files(minecraft_dir(a.minecraft))
    cmd_list(cfg, files) if a.cmd == "list" else cmd_import(cfg, files, a.music_dir)


if __name__ == "__main__":
    main()
