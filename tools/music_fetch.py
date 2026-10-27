"""Fetch candidate music with its license checked and a sidecar written (tools/music.py), for the music step of a
new video (new-video STOP 3, user 2026-10-19). Sources whose terms were checked on 2026-10-19 (ambience-audio skill,
"Music sources"):

  fma <artist>/<album>   Free Music Archive. Each track's own page must show CC0 (creativecommons.org/publicdomain/
                         zero); anything else is skipped unless --allow names its license URL part. Direct MP3s, no login.
  openlofi <category>    github.com/btahir/open-lofi: 166 CC0 tracks made with Suno v5 by the repo's author and
                         dedicated to the public domain (sidecar ai_made: true). Categories: chillhop, jazzhop,
                         ambient-lofi, soul-rnb, asian-lofi, funk-soul, seasonal-weather, late-night, activities,
                         hybrid. Release v1.0.0 only: its 554 MB zip, SHA-256 checked, is cached in cache/openlofi/.

  .venv\\Scripts\\python tools\\music_fetch.py fma holiznacc0/lo-fi-and-chill --to music\\_candidates\\lofi [--max 20]
  .venv\\Scripts\\python tools\\music_fetch.py openlofi jazzhop late-night --to music\\_candidates\\jazz

Sidecars: title, artist, album, source (the track's page), license, license_url, origin (the exact file), ai_made,
verified (date). Nothing here puts a track in a video: candidates are screened (tools/music_screen.py), heard on
clips (tools/music_samples.py), and only the ones Truman picks move into the look's music folder.
"""
import argparse
import datetime
import hashlib
import html
import http.client
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from cozy.paths import ROOT
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
TODAY = datetime.date.today().isoformat()
CC0 = "creativecommons.org/publicdomain/zero"
# Pinned to release v1.0.0 (2026-03-14), the one vetted on 2026-10-19: the zip's SHA-256 is GitHub's own digest for the
# asset, and the catalog is read at the release's commit. A newer release can change the music in a video: vet it,
# then move all three together (security review 2026-10-26).
OPENLOFI = {"repo": "https://github.com/btahir/open-lofi",
            "zip": "https://github.com/btahir/open-lofi/releases/download/v1.0.0/openlofi.zip",
            "zip_sha256": "0040fb9c8bcc22e5f91d1dbf3fb02b6ceff97e249588369bddf9c1fb26950550",
            "catalog": "https://raw.githubusercontent.com/btahir/open-lofi/5c633c47e7235a27f99f5b4869a9988fcc4950c6/catalog.json",
            "license_url": "https://github.com/btahir/open-lofi/blob/main/LICENSE"}
# a file name taken from a remote list: a plain audio file name, no folders (a backslash is one on Windows) and no drive
SAFE_AUDIO = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()'&,+-]*\.(mp3|wav|flac|ogg)")


def get(url, binary=False, tries=3):
    """The body of url. A dropped connection or a 429/5xx answer is tried again; anything else is a RuntimeError that
    names the address."""
    if urllib.parse.urlparse(url).scheme != "https":            # urlopen would also read file:// and plain http
        raise RuntimeError(f"{url}: only https addresses are fetched")
    for attempt in range(tries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
            return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise RuntimeError(f"{url}: HTTP {e.code} {e.reason}") from None
            why = f"HTTP {e.code}"
        except (OSError, http.client.HTTPException) as e:          # URLError, timeouts, resets, a read cut short
            if attempt == tries - 1:
                raise RuntimeError(f"{url}: {getattr(e, 'reason', None) or str(e) or type(e).__name__} (network)") from None
            why = type(e).__name__
        wait = 10 * (attempt + 1)
        print(f"  {why} from {url}: trying again in {wait}s", flush=True)
        time.sleep(wait)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "track"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def on_fma(url):
    """An address read from an FMA page, kept to FMA's own hosts (pages on freemusicarchive.org, files on
    files.freemusicarchive.org)."""
    host = (urllib.parse.urlparse(str(url)).hostname or "").lower()
    if not (host == "freemusicarchive.org" or host.endswith(".freemusicarchive.org")):
        raise RuntimeError(f"{url}: not a Free Music Archive address")
    return str(url)


def write(dst_dir, name, audio, side):
    dst_dir.mkdir(parents=True, exist_ok=True)
    f = dst_dir / name
    if pathlib.Path(name).name != name or f.resolve().parent != dst_dir.resolve():
        raise RuntimeError(f"refusing to write {name!r}: not a plain file name in {dst_dir}")
    if not f.exists():
        f.write_bytes(audio() if callable(audio) else audio)
    f.with_name(f.name + ".json").write_text(json.dumps(side, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return f


def fma(spec, to, allow, limit):
    parts = spec.strip("/").split("/")
    if len(parts) < 2 or not all(parts[-2:]):
        sys.exit(f"fma: give <artist>/<album> as in freemusicarchive.org/music/<artist>/<album>, not {spec!r}")
    artist, album = parts[-2:]
    page = get(f"https://freemusicarchive.org/music/{artist}/{album}")
    try:
        tracks = [json.loads(html.unescape(x)) for x in re.findall(r"data-track-info='([^']+)'", page)]
    except ValueError:
        sys.exit(f"fma {artist}/{album}: the page's track list didn't parse (the site changed?)")
    print(f"fma {artist}/{album}: {len(tracks)} tracks")
    n = 0
    for t in tracks[:limit or None]:
        try:
            tp = get(on_fma(t["url"]))
        except (RuntimeError, KeyError) as e:                     # one track that won't load doesn't end the album
            print(f"  skip {t.get('title', '?')}: its page didn't load ({e})")
            continue
        # the track's own license line: "... is licensed under a <a rel="license" href="...">CC0 1.0 Universal License</a>"
        m = re.search(r'licensed under an? <a rel="license" href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', tp)
        lic_url, lic = (m.group(1), m.group(2).replace(" License", "")) if m else ("", "")
        if CC0 not in lic_url and not any(x and x in lic_url for x in allow):
            print(f"  skip {t['title']}: license {lic or 'not shown'} ({lic_url})")
            continue
        name = f"{slug(t['artistName'])}_{slug(re.sub(r'(?i)[.](mp3|wav|flac)$', '', t['title']))}.mp3"
        side = {"title": re.sub(r"(?i)[.](mp3|wav|flac)$", "", t["title"]).rstrip("."), "artist": t["artistName"],
                "album": t.get("albumTitle"), "source": t["url"],
                "license": lic, "license_url": lic_url, "ai_made": False, "verified": TODAY,
                "origin": f"Free Music Archive, {t['fileUrl']} (license read on the track's page {TODAY})"}
        try:
            write(pathlib.Path(to), name, lambda: get(on_fma(t["fileUrl"]), True), side)
        except RuntimeError as e:
            print(f"  skip {t['title']}: the download failed ({e})")
            continue
        n += 1
        print(f"  {name}")
    return n


def openlofi(cats, to, limit):
    # the catalog first: a mistyped category or a changed license stops before the 554 MB download
    cat = json.loads(get(OPENLOFI["catalog"]))
    if cat.get("license") != "CC0-1.0":
        sys.exit(f"open-lofi's catalog says license {cat.get('license')!r}, not CC0-1.0: check the repo before using it")
    labels = {c["slug"]: c["label"] for c in cat["categories"]}
    unknown = [c for c in cats if c not in labels]
    if unknown:
        sys.exit(f"openlofi: no category {', '.join(unknown)} (categories: {', '.join(labels)})")
    cache = ROOT / "cache" / "openlofi"
    cache.mkdir(parents=True, exist_ok=True)
    zp = cache / "openlofi.zip"
    if not zp.exists():
        print("downloading openlofi.zip (554 MB) ...", flush=True)
        part = zp.with_suffix(".part")
        part.write_bytes(get(OPENLOFI["zip"], True))
        if sha256_of(part) != OPENLOFI["zip_sha256"]:
            part.unlink()
            sys.exit(f"{OPENLOFI['zip']} isn't the vetted v1.0.0 zip (its SHA-256 differs): check the repo before using it")
        part.replace(zp)
    elif sha256_of(zp) != OPENLOFI["zip_sha256"]:
        sys.exit(f"{zp} isn't the vetted v1.0.0 zip (its SHA-256 differs): delete it to download it again")
    want = [t for t in cat["tracks"] if t["category"] in cats]
    with zipfile.ZipFile(zp) as z:
        names = {pathlib.PurePosixPath(n).name: n for n in z.namelist()}
        n = 0
        for t in want[:limit or None] if limit else want:
            if not SAFE_AUDIO.fullmatch(str(t.get("filename", ""))):
                print(f"  skip {t.get('filename')!r}: not a plain audio file name")
                continue
            member = names.get(t["filename"])
            if not member:
                print(f"  missing in the zip: {t['filename']}")
                continue
            side = {"title": t["title"], "artist": "Open Lo-Fi", "album": labels.get(t["category"], t["category"]),
                    "source": OPENLOFI["repo"], "license": "CC0 1.0 Universal", "license_url": OPENLOFI["license_url"],
                    "ai_made": True, "verified": TODAY,
                    "origin": f"openlofi.zip ({OPENLOFI['zip']}, fetched {TODAY}), {member}; made with Suno v5 by the repo's "
                              "author, who dedicated it to the public domain (CC0)"}
            write(pathlib.Path(to), f"openlofi_{t['filename']}", lambda: z.read(member), side)
            n += 1
    print(f"openlofi {', '.join(cats)}: {n} tracks -> {to}")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", choices=["fma", "openlofi"])
    ap.add_argument("what", nargs="+", help="fma: <artist>/<album> ...; openlofi: category slugs")
    ap.add_argument("--to", required=True, help="candidate folder, e.g. music/_candidates/jazz")
    ap.add_argument("--max", type=int, default=0, help="at most this many tracks per album or in all")
    ap.add_argument("--allow", action="append", default=[], help="fma: also accept a license whose URL contains this "
                                                                 "(only with Truman's OK, e.g. 'licenses/by/4.0')")
    a = ap.parse_args()
    try:
        if a.source == "fma":
            for w in a.what:
                fma(w, a.to, a.allow, a.max)
        else:
            openlofi(a.what, a.to, a.max)
    except RuntimeError as e:
        sys.exit(f"music_fetch: {e}")


if __name__ == "__main__":
    main()
