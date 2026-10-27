"""Make or update the public copy of this repo: a snapshot of main's files without the private notes, never its history
(security review 2026-10-26; 2026-10-27: nobody can read Truman's chats word for word in public).

This repo stays private. It keeps the chat archives, the status and decision logs, the lessons with his feedback in his
own words, the marketing drafts, and a history that still holds old identifiers and other creators' frames. The public
repo gets none of that. Each run:
  - takes main's files as committed (git archive), never its history;
  - leaves out the private notes: PRIVATE_DIRS whole, and each of PRIVATE_FILES as a short stub, since other files link
    to them (and each --drop path);
  - replaces any private term in a text file, as tools/secret_scan.py knows them (.git/info/private-terms, the az
    account, this PC's user folder); normally there are none, and the run says so;
  - names the public repo (PUBLIC_REPO) wherever a text file names this one, so its clone commands work for others;
  - checks the result: secret_scan's checks on every file, no private path, no message quoted whole (**User:**),
    no six of his words in a row from the chat archives or the lessons (his published text and ALLOWED aside;
    tests/test_go_public.py runs the same check on every tracked file), and in binaries no private term or user
    folder in their bytes and no GPS position in a photo's EXIF;
  - commits it in the public folder as one snapshot, under this repo's identity (the GitHub noreply address).
Nothing is pushed.

  .venv\\Scripts\\python tools\\go_public.py C:\\dev\\cozy-vibe-vids-public [--drop <path>]

The first run makes the folder a new git repo with one commit: push it to a new GitHub repo. Later runs take a clone of
that public repo (github.com/TrumanBrown/cozy-vibe-vids-public, cloned in C:\\dev\\cozy-vibe-vids-public) and add one
commit when main has changed: push it. Never make this repo public, and never push its branches to the public one.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile

from cozy.paths import ROOT
import secret_scan as S

# The private working notes (2026-10-27). A note other files link to becomes a stub; a folder goes whole.
PRIVATE_DIRS = ("docs/history/", "marketing/")
PRIVATE_FILES = ("docs/STATUS.md", "docs/DECISIONS.md", ".agents/skills/new-video/references/lessons.md",
                 ".agents/skills/new-video/references/retrospective.md")
STUB = ("# {title}\n\nThis file is part of the project's private working notes (status, decisions and the channel "
        "owner's feedback in his own words), so the public copy leaves it out. The code, the skills and the other docs "
        "are all here.\n")
# The public repo (2026-10-27). In the copy, a clone command or link that names this private repo (its origin remote)
# names the public one instead.
PUBLIC_REPO = "TrumanBrown/cozy-vibe-vids-public"
WHOLE_MESSAGE = re.compile(r"\*\*User:\*\*\s*[\"\u201c]")          # a message quoted whole, as the decision log did
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
# His words (2026-10-27): six of them in a row, in order, are a quote, with or without quote marks. They come from the
# chat archives' messages and the lessons' "asked" column. What he published (the records, the blurb) is public already,
# and ALLOWED is quoted on purpose: the one-line command with its examples (documented), a rule's wording (AGENTS.md),
# two YouTube videos' titles, two opening lines shown in videos, and the vision model's words. A run through a link or
# a path doesn't count.
RUN = 6
ALLOWED = ("generate me a new youtube video sample for minecraft style / pixel 8 bit / a real life farmscape",
           "awake doing something quiet with breathing and blinks drawn in code",
           "90's Chill Lofi, Study Music, Lofi Rain, Chillhop Beats",
           "Rainy Night at a Japanese Ramen",
           "Seedling House. Come listen to the morning rain",
           "welcome, have some ramen and relax",
           "wooden floorboards in the sheltered foreground")
WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*", re.I)                # words, an inner apostrophe kept: don't, it's
LINKISH = re.compile(r"[/\\]|https?|www\.")


def git(*args, cwd):
    return S.git(*args, cwd=cwd)


def az_terms():
    """The signed-in az account's user, subscription and tenant; none when az is missing or logged out."""
    from azure_ai import AZ
    try:
        r = subprocess.run([AZ, "account", "show", "-o", "json"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode:
        return []
    a = json.loads(r.stdout)
    return [x for x in ((a.get("user") or {}).get("name"), a.get("id"), a.get("tenantId")) if x]


def scrubbers():
    """[(regex on bytes, replacement)]: this PC's user folders, then each private term as a whole word, longest first."""
    terms = set(S.private_terms(ROOT)) | set(az_terms())
    terms |= {t[:8] for t in terms if GUID.fullmatch(t)}
    out = []
    u = S.user_name()
    if u:
        out.append((re.compile(rb"(?i)(Users[\\/]+|/home/)" + re.escape(u.encode()) + rb"(?![A-Za-z0-9])"), rb"\1<you>"))
    for t in sorted(terms, key=lambda t: (-len(t), t.lower())):
        word = "[email removed]" if "@" in t else "[id removed]" if re.fullmatch(r"[0-9a-f-]{8,36}", t, re.I) else "[removed]"
        out.append((re.compile(rb"(?i)(?<![A-Za-z0-9])" + re.escape(t.encode()) + rb"(?![A-Za-z0-9])"), word.encode()))
    return sorted(terms), out


def private(name, drops):
    return name.startswith(PRIVATE_DIRS) or any(name == d.rstrip("/") or name.startswith(d.rstrip("/") + "/") for d in drops)


def clear(dest):
    """Everything in dest but .git: the snapshot replaces the whole tree, deletions included."""
    def onerror(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    for p in dest.iterdir():
        if p.name == ".git":
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, onerror=onerror)
        else:
            p.unlink()


def prepare(dest, name, email):
    """Make dest a git repo for the snapshot or check it is the public clone. Returns True when it has no commit yet."""
    dest.mkdir(parents=True, exist_ok=True)
    if not any(dest.iterdir()):
        git("init", "-q", "-b", "main", cwd=dest)
    elif not (dest / ".git").is_dir():
        sys.exit(f"{dest} isn't empty and isn't a git repo: give a new folder or the public repo's clone")
    new = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=dest, capture_output=True).returncode != 0
    if not new:
        mine = set(git("rev-list", "--max-parents=0", "HEAD", cwd=ROOT).split())
        theirs = set(git("rev-list", "--max-parents=0", "--all", cwd=dest).split())
        if mine & theirs:
            sys.exit(f"{dest} shares history with this private repo: it must be the public repo's clone, never this one's")
        if git("status", "--porcelain", cwd=dest).strip():
            sys.exit(f"{dest} has uncommitted changes: commit or discard them first (it is made by this tool only)")
    # with no commit yet, whatever is there is an earlier run of this tool that stopped before committing
    git("config", "user.name", name, cwd=dest)
    git("config", "user.email", email, cwd=dest)
    git("config", "core.autocrlf", "false", cwd=dest)          # files are written byte for byte, as committed here
    return new


def origin_repo():
    """owner/name of this repo on GitHub, from its origin remote; None without one."""
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", r.stdout.strip()) if r.returncode == 0 else None
    return m.group(1) if m else None


def export(dest, branch, drops, rules, own=None):
    """Write main's files into dest without the private notes, naming PUBLIC_REPO where a text file names `own` (this
    repo). Returns (files, stubs, scrubbed, executable paths)."""
    files, stubs, scrubbed, execs = 0, [], 0, []
    own_rx = re.compile(rb"(?i)(?<![\w.-])" + re.escape(own.encode()) + rb"(?![\w-])") \
        if own and own.lower() != PUBLIC_REPO.lower() else None
    p = subprocess.Popen(["git", "archive", "--format=tar", branch], cwd=ROOT, stdout=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout, mode="r|") as tar:
        for m in tar:
            if not m.isfile() or private(m.name, drops):
                continue
            data = tar.extractfile(m).read()
            out = dest / m.name
            out.parent.mkdir(parents=True, exist_ok=True)
            if m.name in PRIVATE_FILES:
                head = next((ln[2:].strip() for ln in data.decode("utf-8", "replace").splitlines() if ln.startswith("# ")), "Notes")
                out.write_text(STUB.format(title=head), encoding="utf-8", newline="\n")
                stubs.append(m.name)
                continue
            if not S.binary(data):
                for rx, word in rules:
                    data, n = rx.subn(word, data)
                    scrubbed += n
                data = own_rx.sub(PUBLIC_REPO.encode(), data) if own_rx else data
            out.write_bytes(data)
            files += 1
            if m.mode & 0o111:
                execs.append(m.name)
    p.stdout.read()     # the tar's padding after its end marker: left unread, it can fill the pipe and git never exits
    p.stdout.close()
    if p.wait():
        sys.exit(f"git archive {branch} failed ({p.returncode})")
    return files, stubs, scrubbed, execs


def word_runs(texts, n=RUN):
    """Every run of n words in the texts, lowercased, punctuation left out."""
    runs = set()
    for t in texts:
        w = [m.group(0).lower() for m in WORD.finditer(t)]
        runs.update(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    return runs


def his_runs(root=ROOT):
    """The runs of his own words a public file must not repeat: the archived messages and the lessons' quotes of him,
    less what he published and ALLOWED. Empty where the private notes aren't."""
    hist = root / "docs" / "history"
    texts = [p.read_text(encoding="utf-8") for p in sorted(hist.rglob("truman-messages.md"))]
    texts += [p.read_text(encoding="utf-8") for p in [hist / "kickoff.prompt.md"] if p.exists()]
    lessons = root / ".agents" / "skills" / "new-video" / "references" / "lessons.md"
    for row in lessons.read_text(encoding="utf-8").splitlines() if lessons.exists() else []:
        cells = row.split("|")
        if len(cells) > 4 and re.fullmatch(r"\s*L\d+\s*", cells[1]):
            texts += re.findall(r"[\"\u201c]([^\"\u201c\u201d]+)[\"\u201d]", cells[3].replace('\\"', '"'))
    published = [p.read_text(encoding="utf-8") for p in sorted((root / "docs" / "records").rglob("*"))
                 if p.name in ("published.md", "credits.txt")]
    published += [p.read_text(encoding="utf-8") for p in [root / "assets" / "publish" / "description_blurb.txt"] if p.exists()]
    return word_runs(texts) - word_runs(published + list(ALLOWED))


def repeats(text, runs, n=RUN):
    """[(line, words)] where the text repeats a run of his words; a run through a link or a path doesn't count."""
    toks = [(m.group(0).lower(), m.start(), m.end()) for m in WORD.finditer(text)]
    out, i = [], 0
    while i <= len(toks) - n:
        if tuple(t for t, _, _ in toks[i:i + n]) in runs:
            j = i + n
            while j < len(toks) and tuple(t for t, _, _ in toks[j - n + 1:j + 1]) in runs:
                j += 1
            span = text[toks[i][1]:toks[j - 1][2]]
            if not LINKISH.search(span):
                out.append((text.count("\n", 0, toks[i][1]) + 1, " ".join(span.split())))
            i = j
        else:
            i += 1
    return out


def binary_problems(path, data, terms):
    """What a binary file would publish that the text checks can't see: a private term (8 characters or more) or this
    PC's user folder anywhere in its bytes, UTF-8 or UTF-16 (an image's text chunks, a path a tool wrote into it), or a
    GPS position in a photo's EXIF. The key art's content credentials (C2PA) only say Azure OpenAI made it, and when."""
    low, out = data.lower(), []
    u = S.user_name()
    needles = [t for t in terms if len(t) >= 8]
    needles += [f"users\\{u}", f"users\\\\{u}", f"users/{u}", f"/home/{u}"] if u else []
    if any(n.lower().encode() in low or n.lower().encode("utf-16-le") in low for n in needles):
        out.append("a private term or this PC's user folder inside the file")
    if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"):
        from PIL import Image
        try:
            with Image.open(path) as im:
                if im.getexif().get_ifd(0x8825):
                    out.append("a GPS position in its EXIF")
        except Exception:
            pass
    return out


def check(dest, terms, drops):
    """What would leak: secret_scan's checks on every file, a private path, a whole message, his words in a row, a
    private term or GPS position inside a binary, a missing stub."""
    problems = []
    rules = S.checks(terms, cwd=ROOT)
    runs = his_runs()
    for f in sorted(x for x in dest.rglob("*") if x.is_file() and ".git" not in x.relative_to(dest).parts):
        rel = f.relative_to(dest).as_posix()
        if private(rel, drops):
            problems.append(f"{rel}: a private path")
            continue
        data = f.read_bytes()
        if S.binary(data):
            problems += [f"{rel}: {k}" for k in binary_problems(f, data, terms)]
            continue
        text = data.decode("utf-8", "replace")
        if rel in PRIVATE_FILES:
            if "private working notes" not in text:
                problems.append(f"{rel}: should be a stub")
            continue
        problems += [f"{rel}:{n}  {k}" for n, k in S.scan_text(text, rules)]
        problems += [f"{rel}:{i}  a message quoted whole (**User:**)" for i, line in enumerate(text.splitlines(), 1)
                     if WHOLE_MESSAGE.search(line)]
        problems += [f"{rel}:{i}  his words, {len(s.split())} in a row: {s[:60]}" for i, s in repeats(text, runs)]
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest", help="the public repo's folder: new and empty the first time, its clone later")
    ap.add_argument("--drop", action="append", default=[], help="one more path to leave out (repeatable)")
    ap.add_argument("--branch", default="main")
    a = ap.parse_args()
    dest = pathlib.Path(a.dest).resolve()
    if dest == ROOT or ROOT in dest.parents or dest in ROOT.parents:
        sys.exit(f"{dest}: pick a folder outside this repo")
    name, email = git("config", "user.name", cwd=ROOT).strip(), git("config", "user.email", cwd=ROOT).strip()
    if not email.endswith("@users.noreply.github.com"):
        sys.exit(f"this repo's user.email is {email!r}, not a GitHub noreply address: set it first")
    if git("status", "--porcelain", "--untracked-files=no", cwd=ROOT).strip():
        print(f"note: uncommitted changes here aren't in the copy; it has what is committed on {a.branch}", flush=True)
    terms, rules = scrubbers()
    if not terms:
        sys.exit("no private terms: make .git/info/private-terms (docs/SETUP.md section 2) or log in with az first")
    head = git("rev-parse", "--short", a.branch, cwd=ROOT).strip()

    new = prepare(dest, name, email)
    clear(dest)
    files, stubs, scrubbed, execs = export(dest, a.branch, a.drop, rules, origin_repo())
    git("add", "-A", cwd=dest)
    for i in range(0, len(execs), 100):
        git("update-index", "--chmod=+x", "--", *execs[i:i + 100], cwd=dest)
    if scrubbed:
        print(f"! replaced {scrubbed} private term(s) in the copy: tools/secret_scan.py --tracked shows where they are "
              "in this repo; take them out here too", flush=True)
    problems = check(dest, terms, a.drop)
    if problems:
        print("NOT READY: the copy would publish:\n  " + "\n  ".join(problems[:40]))
        print(f"Nothing was committed in {dest}; fix these here, commit, and run again.")
        return 1
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=dest).returncode == 0:
        print(f"No changes: {dest} already matches {a.branch} at {head} (without the private notes).")
        return 0
    msg = ("Cozy Vibe Vids: first public version" if new else f"Update to the private repo's {a.branch}, {dt.date.today().isoformat()}")
    git("commit", "-q", "-m", msg, cwd=dest)
    n = git("rev-list", "--count", "HEAD", cwd=dest).strip()
    print(f"Ready: {dest} ({files} files from {a.branch} at {head}; {len(stubs)} notes stubbed, {', '.join(PRIVATE_DIRS)} "
          f"left out; {n} commit(s), all {name} <{email}>). Every file passed the checks. Nothing was pushed.")
    if new:
        print("Next, by hand:\n"
              f"  1. gh repo create {PUBLIC_REPO} --private --source \"{dest}\" --push\n"
              "  2. Look it over on GitHub; turn on secret scanning, push protection and Dependabot; then make it public.\n"
              "  3. Keep this repo private: the public repo never gets its history.")
    else:
        print(f"Next: git -C \"{dest}\" push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
