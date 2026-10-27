"""Check marketing drafts before Truman reviews them.

  .venv\\Scripts\\python tools\\marketing_check.py marketing\\drafts\\<slug> [file or folder ...]

Drafts are plain .txt files. The file name starts with the place and the kind of text, which sets the length
limit: youtube-title, youtube-description, youtube-comment, reddit-title, reddit-post, reddit-comment,
pinterest-title, pinterest-description, x-post, discord-message. The limits are the platforms' usual maximums.
Change LIMITS if a platform changes one.

Each draft must pass the voice rules (cozy/voice.py voice_problems, DECISIONS 2026-10-16) and also:
  - no AI mention. Public text leaves AI out. A truthful answer to a platform's direct question is for Truman to review.
  - no tags except our own handle. Only people Truman names may be tagged.
  - no "check out my channel" or sub-for-sub wording (YouTube's spam policy).
  - no "not X, but Y" contrast.
  - one link at most, except in youtube-description.
  - within the length limit for its kind.

Exit code 1 if any draft fails.
"""
import argparse
import pathlib
import re
import sys

from cozy.voice import AI_WORDS, voice_problems

LIMITS = {
    "youtube-title": 100,
    "youtube-description": 5000,
    "youtube-comment": 10000,
    "reddit-title": 300,
    "reddit-post": 40000,
    "reddit-comment": 10000,
    "pinterest-title": 100,
    "pinterest-description": 500,
    "x-post": 280,
    "discord-message": 2000,
}
OWN_HANDLE = "@SweaterWeatherProductivity"
MENTION = re.compile(r"@\w+")
LINK = re.compile(r"https?://\S+")
SPAM = re.compile(r"(?i)\b(check out my (?:channel|videos?|new)|sub ?4 ?sub|sub for sub|subscribe for subscribe|"
                  r"follow for follow|drop a sub)\b")
NOT_BUT = re.compile(r"(?i)\bnot\b[^.!?\n]{1,60}?,? but\b")


def kind_of(name):
    """The place and kind a file name starts with, longest match first."""
    for kind in sorted(LIMITS, key=len, reverse=True):
        if name.startswith(kind):
            return kind
    return None


def problems(path):
    text = path.read_text(encoding="utf-8").strip()
    out = list(voice_problems(text))
    kind = kind_of(path.name)
    if kind is None:
        out.append("file name must start with a place and kind: " + ", ".join(LIMITS))
    else:
        if len(text) > LIMITS[kind]:
            out.append(f"{len(text)} characters, over the {LIMITS[kind]} limit for {kind}")
        if kind != "youtube-description" and len(LINK.findall(text)) > 1:
            out.append("more than one link")
    if m := AI_WORDS.search(text):
        out.append(f"mentions AI ({m.group(0)!r}); public text leaves AI out")
    for handle in sorted(set(MENTION.findall(text)) - {OWN_HANDLE}):
        out.append(f"tags {handle}; only people Truman names may be tagged")
    if m := SPAM.search(text):
        out.append(f"spam wording ({m.group(0)!r})")
    if m := NOT_BUT.search(text):
        out.append(f"a 'not X, but Y' contrast ({m.group(0)!r})")
    return out


def drafts_under(arg):
    path = pathlib.Path(arg)
    if path.is_dir():
        return sorted(path.rglob("*.txt"))
    if path.is_file():
        return [path]
    sys.exit(f"not found: {arg}")


def main():
    ap = argparse.ArgumentParser(description="Check marketing drafts (see the module docstring).")
    ap.add_argument("paths", nargs="+", help="draft files or folders")
    args = ap.parse_args()
    files = [f for arg in args.paths for f in drafts_under(arg)]
    if not files:
        sys.exit("no .txt drafts found")
    failed = 0
    for f in files:
        issues = problems(f)
        print(("FAIL " if issues else "ok   ") + str(f))
        for issue in issues:
            print("     - " + issue)
        failed += bool(issues)
    print(f"{len(files) - failed} of {len(files)} drafts pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
