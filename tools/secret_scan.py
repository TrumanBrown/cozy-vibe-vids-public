"""Stop a commit that would publish a key, a token or a private identifier (security review 2026-10-26: the repo is
going public, and a public push can't be taken back).

The pre-commit hook (.githooks/pre-commit, turned on by `git config core.hooksPath .githooks`) runs it on the lines a
commit adds. It refuses:
  - keys and tokens: private key blocks, Azure account keys, SAS signatures and api-key headers, bearer tokens (JWTs),
    GitHub, Hugging Face, OpenAI-style, Google, Slack and AWS keys;
  - a user folder with this PC's user name in it (C:\\Users\\<name>, /home/<name>): write %USERPROFILE%, ~ or a path
    inside the repo instead;
  - the private terms in .git/info/private-terms: one per line, matched without case (the Azure sign-in, subscription
    and tenant IDs, the work email). The file lives inside .git, so it is never committed or pushed; each clone makes
    its own.
It never prints what it found, only where and what kind, so a secret doesn't land in a log either. Reword the line,
stage it and commit again.

  .venv\\Scripts\\python tools\\secret_scan.py --staged      what the hook runs: the lines the commit adds
  .venv\\Scripts\\python tools\\secret_scan.py --tracked     every tracked file as it is now
  .venv\\Scripts\\python tools\\secret_scan.py --history     every file and message of every commit on every ref (slow)
tools/go_public.py uses the same terms and checks to clean and verify the copy that goes public.
"""
import argparse
import getpass
import pathlib
import re
import subprocess
import sys
import threading

KEYS = [
    ("a private key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    ("an Azure account key", r"AccountKey=[A-Za-z0-9+/]{40,}={0,2}"),
    ("a SAS signature", r"[?&]sig=[A-Za-z0-9%+/]{30,}={0,2}"),
    ("an api-key header", r"(?i)\b(?:api-key|ocp-apim-subscription-key)\b[\"']?\s*[:=]\s*[\"']?[0-9a-f]{32}\b"),
    ("a bearer token (JWT)", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("a GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    ("a Hugging Face token", r"\bhf_[A-Za-z0-9]{34,}\b"),
    ("an OpenAI-style key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    ("a Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("a Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),
    ("an AWS key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
]
EDGE = r"(?<![A-Za-z0-9]){}(?![A-Za-z0-9])"


def git(*args, cwd=None, binary=False):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args[:3])} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def terms_file(cwd=None):
    """.git/info/private-terms of the repo at cwd (the main repo's .git, shared by its worktrees)."""
    common = pathlib.Path(git("rev-parse", "--git-common-dir", cwd=cwd).strip())
    if not common.is_absolute():
        common = pathlib.Path(cwd or ".").resolve() / common
    return common / "info" / "private-terms"


def private_terms(cwd=None):
    f = terms_file(cwd)
    if not f.exists():
        return []
    lines = (x.strip() for x in f.read_text(encoding="utf-8").splitlines())
    return [x for x in lines if x and not x.startswith("#")]


def user_name():
    """This PC's user name, when it is specific enough to look for (not a generic account)."""
    try:
        u = getpass.getuser()
    except Exception:
        return None
    return u if u and len(u) >= 3 and u.lower() not in {"user", "admin", "root", "runner", "public", "default"} else None


def checks(terms=None, cwd=None):
    """[(kind, compiled regex)]: the key shapes, this PC's user folders and the private terms."""
    out = [(k, re.compile(p)) for k, p in KEYS]
    u = user_name()
    if u:
        out.append(("a user folder with this PC's user name",
                    re.compile(r"(?i)(?:Users[\\/]+|/home/)" + re.escape(u) + r"(?![A-Za-z0-9])")))
    for t in private_terms(cwd) if terms is None else terms:
        out.append(("a private term from .git/info/private-terms", re.compile(EDGE.format(re.escape(t)), re.I)))
    return out


def scan_text(text, rules):
    """[(line number, kind)] for every line of text that matches a rule."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for kind, rx in rules:
            if rx.search(line):
                hits.append((i, kind))
    return hits


def binary(data):
    return b"\0" in data[:8192]


def staged(rules):
    """The lines the staged commit adds, as (path, new line number, kind)."""
    diff = git("diff", "--cached", "--no-color", "--no-ext-diff", "-U0", "--diff-filter=ACMR", binary=True)
    hits, path, n, header = [], None, 0, False
    for raw in diff.decode("utf-8", "replace").splitlines():
        if raw.startswith("diff --git "):
            path, header = None, True                        # a file's header lines come before its first hunk
        elif header and raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            header = False
            m = re.match(r"@@ -\S+ \+(\d+)", raw)
            n = int(m.group(1)) if m else 0
        elif not header and raw.startswith("+") and path:
            for kind, rx in rules:
                if rx.search(raw[1:]):
                    hits.append((path, n, kind))
            n += 1
    return hits


def tracked(rules, cwd=None):
    root = pathlib.Path(git("rev-parse", "--show-toplevel", cwd=cwd).strip())
    hits = []
    for rel in git("ls-files", "-z", cwd=cwd).split("\0"):
        p = root / rel
        if not rel or not p.is_file():
            continue
        data = p.read_bytes()
        if not binary(data):
            hits += [(rel, i, k) for i, k in scan_text(data.decode("utf-8", "replace"), rules)]
    return hits


def history(rules, cwd=None):
    """Every blob, commit and tag reachable from a ref (what a push sends) in the repo at cwd, as (path or object,
    line, kind)."""
    names, shas = {}, []
    for line in git("rev-list", "--all", "--objects", cwd=cwd).splitlines():
        sha, _, name = line.partition(" ")
        shas.append(sha)
        if name:
            names.setdefault(sha, name)
    p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def feed():
        p.stdin.write(("\n".join(shas) + "\n").encode())
        p.stdin.close()
    threading.Thread(target=feed, daemon=True).start()
    hits = []
    while True:
        head = p.stdout.readline()
        if not head:
            break
        sha, kind, size = head.split()
        data = p.stdout.read(int(size))
        p.stdout.read(1)
        if kind in (b"blob", b"commit", b"tag") and not binary(data):
            where = names.get(sha.decode(), f"{kind.decode()} {sha.decode()[:10]}")
            hits += [(where, i, k) for i, k in scan_text(data.decode("utf-8", "replace"), rules)]
    p.wait()
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="the lines the commit adds (the default; the hook's)")
    g.add_argument("--tracked", action="store_true", help="every tracked file as it is now")
    g.add_argument("--history", action="store_true", help="every object of every commit on every ref")
    a = ap.parse_args()
    rules = checks()
    hits = tracked(rules) if a.tracked else history(rules) if a.history else staged(rules)
    if not hits:
        if a.tracked or a.history:
            print(f"secret_scan: nothing found ({len(rules)} checks, {len(private_terms())} private terms)")
        return 0
    print("secret_scan: this would publish something that must stay private (the repo is public):", file=sys.stderr)
    for where, line, kind in hits[:50]:
        print(f"  {where}:{line}  {kind}", file=sys.stderr)
    if len(hits) > 50:
        print(f"  ... and {len(hits) - 50} more", file=sys.stderr)
    if not (a.tracked or a.history):
        print("Reword those lines (a user folder: %USERPROFILE% or a path in the repo; a key: never in a file), stage "
              "them and commit again.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
