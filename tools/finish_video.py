"""Finish a video once Truman has approved its 5 minute sample: the loop window, the 10 hour master, the thumbnails,
the publish spec and the upload package, in one command, so he never has to drive these steps.

  .venv\\Scripts\\python tools\\finish_video.py <scene> [--version v1] [--dry-run] [--skip-render] [--only thumbs,publish,package]

The stages run in this order. Each is skipped when its output is already up to date, so after a stop or a crash the same
command goes on where it stopped. Each is logged to out/<scene>/finish.md, which ends with the report: every output with
its full path, the QA results, the suggested thumbnail, the title and what Truman does next.

  check    scenes/<scene>/scene.json has events.loop.period (1200) and an intro, and tools/review.py <scene> passes
           (otherwise it stops with review's message).
  window   the loop window, one period long, one period in (master-render skill):
             node src/cli.mjs render scenes/<scene> --from 20m --length 20m --name loop20_<version> --music off
           Skipped with --skip-render, or once its qa.md says Overall: PASS.
  master   the 10 hour video: tools/loop_master.py out/<scene>/render/loop20_<version> --times 30 --name 10h_<version>.
           loop_master also writes master_music.mp4 when the look's music folders hold tracks (tools/music.py
           scene_music); without them the video is ambience only. Free disk is checked first: each file is about the
           window's master.mp4 times 30 (250 GB for the ramen alley's rain), and with music there are two. Up to date
           when the 10 h folder passed QA for this window and intro title, and scene.json and the music folders haven't
           changed since it was built.
  thumbs   assets/thumbnails/<scene>.json, made only when there is none (an existing spec is never overwritten), then
           tools/thumbnail.py on it when a thumbnail is missing or older than the spec. The spec it makes:
             - the frame: the strongest lightning strike in the window at its peak (its frame + 3), else the fullest
               second of the window's busiest minute;
             - first, and suggested, the channel's pixel concept Truman picked on both published videos: a big close-up
               of the hero (a steaming dish the place is named for, else the pet, else the main steaming vessel or the
               fire) with the place name in amber pixel letters and the music tag ("<music> & rain"), 4K and 10 HR;
             - concepts in the look's own fonts and motifs (config/aesthetics.json thumb): neon tubes when the look
               has a neon font, a card from its motifs (a ticket, a label, a chalkboard, a sign), a handwritten note
               over the pet, a polaroid with a caption, and the place name over a soft shade; then more pixel options
               (the place card, the other hero). Pixel looks (Minecraft, the pixel farm) get pixel concepts only;
             - 4K and 10 HR on every one, and every line in a color that stands out from what's right behind it
               (lessons L65): the background under each line is measured on the graded frame; a neon line takes a tube
               color that the bright things behind it don't share (pink for the main line unless they do), over a dark
               halo, and a dark shade goes under text on a bright spot.
           Its words (place name, music tag, note, caption) come from the chat model with the title (below). The look's
           fonts it uses are logged in docs/asset-ledger.csv first when they aren't yet (AGENTS.md: logged before use).
  publish  assets/publish/<scene>.json, made only when there is none (never overwritten): slug, name, the 10 h folder and
           its video (master_music.mp4 with music, else master.mp4), the thumbnails (the pixel concept suggested; Test &
           compare: it and two look-styled ones), titles and the description's opening, about 8 hashtags, no tags,
           Film & Animation. The chat model drafts the words in his form from the scene's brief and his published
           videos (docs/records/*/published.md). They must pass upload_package's text rules (voice_problems, AI_WORDS)
           and the facts of the timeline (no thunder without lightning, no music without a music master); the model
           gets one more try with the problems, then a plain template stands in, marked draft_text.
  package  tools/upload_package.py assets/publish/<scene>.json -> upload/<slug>/ (its checks decide; its errors are shown).

--dry-run prints every command and what each stage would do, and writes nothing. --only runs some of the stages
(check, window, master, thumbs, publish, package). Azure: one chat call (tools/azure_ai.py chat, a few cents) when a spec
has to be made; its words are kept in out/<scene>/finish_words.json and reused while the scene stays the same. The tool
never deletes files, never overwrites a spec (it only adds ledger rows for fonts) and never commits or pushes.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from collections import deque

from cozy.paths import ROOT, PY, config, rel
from cozy.ledger import row as ledger_row
from cozy.voice import AI_WORDS, voice_problems  # noqa: E402
from cozy.publish.words import WORD_FIELDS, draft_words, facts, region_word, template_words
from cozy.publish.thumb_spec import ThumbSpec, overlap

NODE = shutil.which("node") or "node"
STAGES = ("check", "window", "master", "thumbs", "publish", "package")
PASS = "Overall: **PASS**"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}     # children print UTF-8 into our pipe
# Card looks for a look's motifs (config/aesthetics.json thumb.motifs): the first motif that names one of these.
CARD_WORDS = [("chalkboard", "chalk"), ("menu", "chalk"), ("parchment", "parchment"), ("log", "parchment"),
              ("chart", "parchment"), ("brass", "brass"), ("sticky", "sticky"), ("console", "console"),
              ("readout", "console"), ("gauge", "console"), ("wooden", "wood"), ("carved", "wood"), ("sign", "wood"),
              ("ticket", "paper"), ("card", "paper"), ("label", "paper"), ("note", "paper"), ("receipt", "paper"),
              ("sleeve", "paper"), ("tag", "paper"), ("page", "paper")]


class Stop(Exception):
    """A stage can't go on; the message says why and what to do (tail: the last lines of the command that failed)."""

    def __init__(self, msg, tail=None):
        super().__init__(msg)
        self.tail = list(tail or [])


def label(s):
    s = int(round(s))
    return f"{s // 3600}h" if s % 3600 == 0 else f"{s // 60}m" if s % 60 == 0 else f"{s}s"


def mmss(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def passed(qa):
    return qa.exists() and PASS in qa.read_text(encoding="utf-8", errors="replace")


def mtime(p):
    return p.stat().st_mtime if p.exists() else 0.0


def write_new(path, obj):
    """Write a spec that must not exist yet: specs are never overwritten (open mode "x" refuses an existing file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def motif_slug(m):
    """A variant name from a motif: "a meal ticket with a red seal" -> meal-ticket."""
    words = [w for w in re.findall(r"[a-z]+", m.lower().replace("'s", "")) if w not in ("a", "an", "the")]
    for i, w in enumerate(words):
        if w in ("with", "for", "in", "of", "like", "on", "or", "around", "and", "from"):
            words = words[:i]
            break
    return "-".join(words[-2:]) or "card"


def card_kind(motifs):
    """(variant name, card look, motif) for the first of the look's motifs that names a flat thing to write on."""
    for m in motifs:
        low = m.lower()
        if "neon" in low or "polaroid" in low:
            continue
        for key, kind in CARD_WORDS:
            if re.search(rf"\b{key}", low):
                return motif_slug(m), kind, m
    return "paper-card", "paper", "a paper card"


def font_roles(look, fonts_cfg):
    """Which of the look's thumbnail fonts plays which part: neon tubes, handwriting, heavy sign letters, small tags."""
    fonts = [f for f in (look.get("thumb") or {}).get("fonts", []) if f != "pixel" and f in fonts_cfg]
    if not fonts:
        return {}
    feel = {f: f"{fonts_cfg[f].get('feel', '')} {fonts_cfg[f].get('title', '')}".lower() for f in fonts}

    def pick(*keys):
        return next((f for f in fonts if any(k in feel[f] for k in keys)), None)
    title = look.get("title_font") if look.get("title_font") in fonts else None
    neon = (next((f for f in fonts if "tube" in feel[f]), None)
            or next((f for f in fonts if "neon" in feel[f] and "tags" not in feel[f]), None))
    hand = pick("handwriting", "hand-drawn", "script") or title or fonts[0]
    others = [f for f in fonts if f != hand]
    heavy = (pick("heavy", "sign lettering") or next((f for f in others if any(k in feel[f] for k in ("serif", "type", "almanac"))), None)
             or hand)
    tag = pick("rounded", "tags") or (others[0] if others else heavy)
    return {"neon": neon, "hand": hand, "heavy": heavy, "tag": tag, "main": title or hand}


def best_frame(tl, R0, L, fps):
    """The thumbnail frame: the strongest lightning strike in the window [R0, R0 + L) at its peak (frame + 3: the flash
    peaks 0.1 s after it starts), else the fullest second of the window's busiest minute. Returns (frame, why)."""
    if not tl:
        return int((R0 + 30) * fps), "30 s into the window (no timeline yet)"
    ev = [e for e in tl["events"] if R0 <= e["t"] < R0 + L]
    strikes = [e for e in ev if e["type"] == "lightning"]
    if strikes:
        s = max(strikes, key=lambda e: (e.get("power", 0), -(e.get("thunder") or {}).get("distance_m", 1e9)))
        d = (s.get("thunder") or {}).get("distance_m")
        return (int(s.get("frame", round(s["t"] * fps))) + 3,
                f"the strongest lightning strike in the window at its peak (power {s.get('power')}, {d} m away, "
                f"{mmss(s['t'] - R0)} into the window)")
    busy = [e for e in ev if e["type"] != "perch"]
    if not busy:
        return int((R0 + 30) * fps), "30 s into the window (no events in it)"
    m0 = max(range(int(R0), int(R0 + L), 60), key=lambda m: (sum(1 for e in busy if m <= e["t"] < m + 60), -m))
    s = max(range(m0, m0 + 60), key=lambda s: (sum(1 for e in tl["events"] if e["t"] <= s < e["t"] + max(e.get("dur", 0), 2)), -s))
    return int(s * fps), f"the fullest second of the window's busiest minute ({mmss(m0 - R0)} into the window)"


def ofl_author(path):
    """The copyright holder in a font's OFL.txt: "Copyright 2020 The Klee Project Authors (https://...)" -> The Klee
    Project Authors."""
    if not path.exists():
        return ""
    line = next((x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if "copyright" in x.lower()), "")
    line = re.sub(r"\([^)]*\)|https?://\S+", "", line)
    line = re.sub(r"(?i)copyright|\(c\)|©|\b(19|20)\d\d(\s*-\s*(19|20)\d\d)?\b|,", " ", line)
    return re.sub(r"\s+", " ", line).strip(" .")


def package_text_problems(S, tspec, f):
    """upload_package's checks of the text and the thumbnails, run on a publish spec before there is a video to package:
    the same rules and functions (titles, the description with his blurb, hashtags, tags, AI words, the music promise, 4K
    and the length on the suggested and Test & compare thumbnails, 3 concepts in the look's own fonts)."""
    import upload_package as U
    P = []
    titles = S.get("titles") or []
    for t in titles:
        if len(t) > 100:
            P.append(f"title over 100 characters ({len(t)}): {t}")
        if re.match(r"\s*minecraft\b", t, re.I):
            P.append(f"title starts with Minecraft: {t}")
        if not re.search(r"(?i)\b4k\b", t):
            P.append(f"title doesn't say 4K: {t}")
        P += [f"title {t!r}: {p}" for p in voice_problems(t, emoji=int(S.get("title_emoji", 0)))]
    b = S.get("blurb", True)
    blurb = "\n".join(b).strip() if isinstance(b, list) else U.BLURB.read_text(encoding="utf-8").strip() if b else ""
    hashtags, tags = S.get("hashtags", []), S.get("tags", [])
    description = "\n\n".join(p for p in ("\n".join(S.get("description") or []).strip(), blurb, " ".join(hashtags)) if p)
    names = [v["name"] for v in tspec["variants"]]
    picks = [S.get("thumbnail"), *S.get("test_and_compare", [])]
    P += [f"thumbnail variant {n!r} isn't in the thumbnail spec" for n in picks if n not in names]
    hr = f"{f.hours} HR"
    for n in dict.fromkeys(n for n in picks if n in names):
        shown = " ".join(U.thumb_texts(tspec, n))
        if not re.search(r"(?i)\b4k\b", shown):
            P.append(f"thumbnail {n!r} doesn't say 4K")
        if not re.search(rf"(?i)\b{re.escape(hr)}\b", shown):
            P.append(f"thumbnail {n!r} doesn't say the length ({hr})")
    if len(description) > 5000:
        P.append(f"description over 5000 characters ({len(description)})")
    if len(hashtags) > 15:
        P.append(f"{len(hashtags)} hashtags, at most 15")
    P += [f"hashtag {h!r}: one word after #" for h in hashtags if not re.fullmatch(r"#\w+", h)]
    th = f.look.get("thumb") or {}
    if th and "pixel" not in th.get("fonts", []):
        own = [n for n in names if any(x not in (None, "pixel") for x in U.thumb_fonts(tspec, n))]
        if len(own) < 3:
            P.append(f"{len(own)} thumbnail concept(s) in the look's own fonts: make at least 3")
    public = "\n".join([*titles, description, ", ".join(tags), " ".join(U.thumb_texts(tspec, S.get("thumbnail")))])
    if re.search(r"[<>]", public):
        P.append("< or > in the title, description or tags")
    if U.tag_chars(tags) > 500:
        P.append(f"tags over 500 characters ({U.tag_chars(tags)})")
    if m := AI_WORDS.search(public):
        P.append(f"public text mentions AI ({m.group(0)!r})")
    P += voice_problems("\n".join([*(S.get("description") or []), blurb, *tags, *hashtags]))
    if re.search(r"(?i)\bmusic\b", public) and "music" not in S.get("video", ""):
        P.append(f"the text or thumbnail promises music, but {S.get('video')} isn't the music master")
    return P


# ---- The run.

class Finish:
    def __init__(self, a):
        self.a, self.scene, self.sfx, self.dry = a, a.scene, a.out_suffix or "", a.dry_run
        self.sd = ROOT / "scenes" / a.scene
        if not (self.sd / "scene.json").exists():
            raise Stop(f"no {self.sd / 'scene.json'}: finish_video is for scenes made with tools/new_video.py")
        self.sc = json.loads((self.sd / "scene.json").read_text(encoding="utf-8"))
        self.brief = self.load(self.sd / "brief.json")
        aes = config("aesthetics")["aesthetics"]
        self.look_id = self.sc.get("aesthetic") or self.brief.get("aesthetic")
        self.look = aes.get(self.look_id) or {}
        self.pd = ROOT / "out" / "plates" / self.sc.get("plate", a.scene)
        self.fps = int(self.sc.get("fps", 30))
        self.duration = int(self.sc.get("duration", 36000))
        self.hours = f"{round(self.duration / 3600, 1):g}"
        self.period = int(((self.sc.get("events") or {}).get("loop") or {}).get("period") or 0)
        self.times = self.duration // self.period if self.period else 0
        self.rd = ROOT / "out" / a.scene / "render"
        self.win = self.rd / (f"loop{self.period // 60}_{a.version}" if self.period else f"loop_{a.version}")
        self.out10 = self.rd / f"{label(self.duration)}_{a.version}"
        self.tspec = ROOT / "assets" / "thumbnails" / f"{a.scene}{self.sfx}.json"
        self.pspec = ROOT / "assets" / "publish" / f"{a.scene}{self.sfx}.json"
        self.report = ROOT / "out" / a.scene / f"finish{self.sfx}.md"
        self.words_path = ROOT / "out" / a.scene / f"finish_words{self.sfx}.json"
        import music as M
        self.music_dirs, self.minecraft = M.scene_music(a.scene)
        self.n_tracks = len(M.scan(self.music_dirs))
        self.has_music = self.n_tracks > 0
        self.recs, self.status, self.t0, self.started = [], "running", time.time(), dt.datetime.now()
        self._regs = self._words = self._tl = None

    # -- helpers

    @staticmethod
    def load(p):
        return json.loads(p.read_text(encoding="utf-8-sig")) if p and p.exists() else {}

    @staticmethod
    def cmdline(cmd):
        return " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd)

    def show(self, cmd):
        print(f"  $ {self.cmdline(cmd)}", flush=True)

    def run(self, cmd, show=True, keep=40):
        """Run a command from the repo root, streaming its output (show) and keeping its last lines (keep; None = all)."""
        tail = deque(maxlen=keep)
        p = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in p.stdout:
            line = line.rstrip()
            tail.append(line)
            if show:
                print(f"    {line}", flush=True)
        return p.wait(), list(tail)

    def rec(self, stage, result, detail, cmd=None, tail=None, t=None):
        self.recs.append({"stage": stage, "result": result, "detail": detail, "cmd": self.cmdline(cmd) if cmd else "",
                          "tail": list(tail or []), "secs": time.time() - t if t else None})
        print(f"  -> {result}: {detail}", flush=True)
        self.write_report()

    def need_period(self):
        if not self.period:
            raise Stop("scene.json has no events.loop.period: the 10 h video loops one period of a timeline that repeats with it")

    def regions(self):
        if self._regs is None:
            r = self.load(self.pd / "regions.json") or []
            self._regs = r["regions"] if isinstance(r, dict) else r
        return self._regs

    def heroes(self):
        """(hero, other, pet): the close-up's subject is a steaming dish the place is named for (the ramen bowl in the
        ramen alley), else the pet, else the biggest steaming vessel, the fire or a lantern; other is the next best."""
        regs = self.regions()

        def big(gs):
            return max(gs, key=lambda g: g.get("area", 0)) if gs else None
        pet = big([g for g in regs if g["kind"] == "pet"])
        vessels = [g for g in regs if g["kind"] == "steam"]
        toks = set(re.findall(r"[a-z]+", self.scene.lower())) - {"rainy", "snowy", "stormy", "night", "the"}
        namesake = big([g for g in vessels if set(re.findall(r"[a-z]+", g["name"].lower())) & toks])
        fire = big([g for g in regs if g["kind"] == "fire"])
        hero = namesake or pet or big(vessels) or fire or big([g for g in regs if g["kind"] in ("lantern", "candle", "lamp")])
        other = pet if hero is not pet else (namesake or big(vessels) or fire)
        return hero, (other if other is not hero else None), pet

    def timeline(self, make):
        """The window's timeline (out/<scene>/render/loop20_<v>/timeline.json); before the window is rendered, the same
        timeline from node src/cli.mjs timeline (not in a dry run)."""
        if self._tl is None:
            p = self.win / "timeline.json"
            if not p.exists():
                p = ROOT / "out" / self.scene / f"finish_timeline{self.sfx}.json"
                if not make:
                    return None
                r = subprocess.run([NODE, "src/cli.mjs", "timeline", f"scenes/{self.scene}", "--out", str(p)], cwd=ROOT,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode:
                    raise Stop(f"node src/cli.mjs timeline failed:\n{(r.stdout + r.stderr)[-800:]}")
            self._tl = json.loads(p.read_text(encoding="utf-8"))
        return self._tl

    def words(self):
        """The place name, the thumbnail tags and the publish text, from the chat model (draft_words), kept in
        out/<scene>/finish_words.json and reused while the brief, the look, the music, the timeline and his published
        records stay the same."""
        if self._words is not None:
            return self._words
        fx = facts(self.timeline(make=not self.dry), self.period, self.period)
        hero, _, pet = self.heroes()
        subj = pet or hero
        recs = sorted((ROOT / "docs" / "records").glob("*/published.md"), key=lambda p: (p.parent.name != "rainy-ramen-alley", p.parent.name))
        records = [(rel(p), p.read_text(encoding="utf-8")) for p in recs]
        key = hashlib.sha1(json.dumps({"v": 4, "brief": self.brief, "look": self.look_id, "music": [self.has_music, self.minecraft],
                                       "facts": fx, "subject": subj and subj["name"], "records": [t for _, t in records],
                                       "hours": self.hours}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        old = self.load(self.words_path)
        if old.get("key") == key:
            self._words = old
        elif self.dry:
            self._words = {**template_words(self, fx, subj), "source": "template (a dry run asks no model)",
                           "template_fields": [*WORD_FIELDS, "titles"]}
        else:
            print("  words: asking the chat model (tools/azure_ai.py chat)", flush=True)
            self._words = {**draft_words(self, fx, subj, records), "key": key}
            self.words_path.parent.mkdir(parents=True, exist_ok=True)
            self.words_path.write_text(json.dumps(self._words, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return self._words

    def thumb_plan(self, tl):
        """The thumbnail spec's frame, hero and concepts (names and builders), and the Test & compare trio."""
        frame, why = best_frame(tl, self.period, self.period, self.fps)
        hero, other, pet = self.heroes()
        if hero is None:
            raise Stop(f"no pet, steaming vessel, fire or lantern in {self.pd / 'regions.json'} for the close-up")
        th = self.look.get("thumb") or {}
        roles = font_roles(self.look, config("fonts")["fonts"])
        if th.get("painterly"):
            # a look painted by hand gets painterly concepts only, no pixel letters (Truman 2026-10-26, L160)
            subj = pet or hero
            pets = [g for g in self.regions() if g["kind"] == "pet"]

            def holds_light(g):
                b = g["bbox"]
                return any(o["kind"] in ("lantern", "lamp") and overlap(o["bbox"], [b[0] - 0.05, b[1] - 0.05, b[2] + 0.08, b[3] + 0.05]) > 0.3
                           for o in self.regions())
            spec = next((g for g in pets if holds_light(g)), None) or next((g for g in pets if g is not subj), subj)
            C = [("watercolor-title", "pt_wash", None), ("field-guide", "pt_plate", None), ("nature-journal", "pt_journal", None),
                 ("storybook", "pt_book", None), (f"{region_word(spec)}-label", "pt_specimen", spec),
                 (f"{region_word(subj)}-note", "pt_note", subj)]
            trio = ["watercolor-title", "field-guide", "storybook"]
            pixel_look = False
        elif not th or "pixel" in th.get("fonts", []) or not roles:
            pixel_look = True
            first = f"pixel-{region_word(hero)}"
            C = [(first, "pixel_hero", hero), ("pixel-place-card", "pixel_place", pet), ("pixel-polaroid", "pixel_polaroid", None),
                 ("pixel-sign", "pixel_sign", None)]
            trio = [first, "pixel-place-card", "pixel-polaroid"]
        else:
            pixel_look = False
            first = f"pixel-{region_word(hero)}"
            subj = pet or hero
            cname, kind, motif = card_kind(th.get("motifs", []))
            note = f"{region_word(subj)}-note"
            C = [(first, "pixel_hero", hero)] + ([("neon-sign", "neon", None)] if roles["neon"] else []) + [
                (cname, "card", (kind, motif)), (note, "note", subj), ("polaroid-note", "polaroid", None),
                ("place-name", "title", None), ("pixel-place-card", "pixel_place", None)]
            if other is not None:
                C.append((f"pixel-{region_word(other)}", "pixel_hero", other))
            trio = [first, "neon-sign" if roles["neon"] else cname, note if subj is not hero else "polaroid-note"]
        seen, out = set(), []
        for n, k, arg in C:
            while n in seen:
                n += "-2"
            seen.add(n)
            out.append((n, k, arg))
        return {"frame": frame, "frame_why": why, "hero": hero, "other": other, "pet": pet, "pixel_look": pixel_look,
                "fonts": roles, "concepts": out, "trio": trio}

    def thumb_dir(self, spec):
        return ROOT / spec.get("out", f"out/{pathlib.Path(spec['scene']).name}/thumbnails")

    def thumbs_stale(self, tspec):
        """Why the thumbnails of a spec must be drawn again (one missing or older than the spec or the drawing code, which
        is thumbnail.py and every tool module it imports), or None."""
        from cozy.code import code_files
        spec = self.load(tspec)
        if not spec:
            return f"there is no {tspec}"
        d = self.thumb_dir(spec)
        ref = max([mtime(tspec)] + [mtime(p) for p in code_files("thumbnail")])
        for v in spec["variants"]:
            for p in (d / f"{v['name']}.jpg", d / f"{v['name']}_1280.jpg"):
                if mtime(p) < ref:
                    return f"{p.name} is {'older than the spec or the drawing code' if p.exists() else 'missing'}"
        return None if mtime(d / "preview.png") >= ref else "preview.png is missing or older than the spec"

    def intro_current(self, intro_id):
        """Whether the 10 h build opens with the scene's current title (loop_master's intro key, from intro.png)."""
        if not self.sc.get("intro"):
            return intro_id is None, "the scene's intro was removed since the build"
        import intro_title as IT
        why = IT.stale(self.scene)
        if why:
            return False, f"the intro title must be drawn again ({why})"
        ij = self.load(self.pd / "intro.json")
        key = hashlib.sha1((self.pd / "intro.png").read_bytes() + json.dumps([ij["box"], ij["timing"]]).encode()).hexdigest()[:16]
        if not intro_id or not str(intro_id).endswith("#" + key):
            return False, "the intro title changed since the build"
        return True, ""

    def master_state(self):
        """Whether the 10 h folder is up to date, why not, and which of its files a build would write (for the disk check)."""
        lj_p, qa = self.out10 / "loop.json", self.out10 / "qa.md"
        mm, mu = self.out10 / "master.mp4", self.out10 / "master_music.mp4"
        if not lj_p.exists():
            return {"fresh": False, "why": f"no 10 h build in {self.out10} yet", "master": True, "music": self.has_music}
        lj = self.load(lj_p)
        checks = (lj.get("qa") or {}).get("checks") or {}
        amb = [v for k, v in checks.items() if not k.startswith("music_")]
        mus = [v for k, v in checks.items() if k.startswith("music_")]
        why = []
        if lj.get("source") != str(self.win.resolve()) or lj.get("times") != self.times or lj.get("offset_s", 0) or lj.get("xfade_s") != 3.0:
            why.append(f"it was looped from {lj.get('source_tag') or lj.get('source')} x{lj.get('times')}, not {self.win.name} x{self.times}")
        ok, w = self.intro_current(lj.get("intro"))
        if not ok:
            why.append(w)
        if not mm.exists():
            why.append("master.mp4 is missing")
        if not amb or not all(v.get("pass") for v in amb):
            why.append("its QA didn't pass")
        need_master = bool(why)
        music_disk = need_master and self.has_music
        if self.has_music and not need_master:
            ins = [self.sd / "scene.json"] + [p for d in self.music_dirs if d.is_dir() for p in d.iterdir() if p.is_file()]
            changed = [p for p in ins if mtime(p) > mtime(lj_p)]
            if not mu.exists() or not lj.get("music"):
                why.append("master_music.mp4 is missing")
                music_disk = True
            elif not mus or not all(v.get("pass") for v in mus):
                why.append("the music master's QA didn't pass")
                music_disk = True
            elif changed:
                why.append(f"{rel(changed[0])} changed since the build (loop_master keeps both masters when the music plan "
                           "comes out the same, after about 4 minutes of planning)")
        if not why and not passed(qa):
            why.append(f"{qa} doesn't say Overall: PASS")
        ok_why = f"{self.out10} passed QA for {self.win.name} x{self.times} and the current title" + (", with music" if self.has_music else "")
        return {"fresh": not why, "why": "; ".join(why) or ok_why, "master": need_master, "music": music_disk}

    def package_stale(self, S, tsp):
        """Why upload/<slug>/ must be written again (something it is made from is newer than its README), or None."""
        from cozy.code import code_files
        pkg = ROOT / "upload" / S["slug"]
        readme = pkg / "README.md"
        video = ROOT / S["render"] / S["video"]
        if not readme.exists():
            return f"there is no {pkg} yet"
        if not video.exists():
            return f"{video} doesn't exist yet"
        if not any(os.path.samefile(p, video) for p in pkg.glob("*.mp4")) and not (pkg / "video_location.txt").exists():
            return "its video isn't the current master"
        ins = [self.pspec, tsp, ROOT / "assets" / "publish" / "description_blurb.txt", ROOT / S["render"] / "qa.md",
               ROOT / S["render"] / "music_plan.json", *code_files("upload_package"), *self.thumb_dir(self.load(tsp)).glob("*.jpg")]
        newer = [p for p in ins if mtime(p) > mtime(readme)]
        return f"{rel(newer[0])} is newer than its README.md" if newer else None

    def unique_slug(self, slug):
        """The model's slug, unless another video's publish spec or record already uses it (then -2, -3...)."""
        mine = [self.load(p) for p in (ROOT / "assets" / "publish").glob(f"{self.scene}*.json")]
        own = {s.get("slug") for s in mine} | {pathlib.Path((s.get("published") or {}).get("record", "x/x")).parent.name for s in mine}
        taken = {self.load(p).get("slug") for p in (ROOT / "assets" / "publish").glob("*.json") if not p.stem.startswith(self.scene)}
        taken |= {d.name for d in (ROOT / "docs" / "records").iterdir() if d.is_dir()} - own
        out, i = slug, 2
        while out in taken:
            out, i = f"{slug}-{i}", i + 1
        return out + self.sfx

    def publish_spec(self):
        w = self.words()
        tspec = self.load(self.tspec)
        names = [v["name"] for v in tspec["variants"]]
        fin = tspec.get("_finish") or {}
        sug = fin.get("suggested") if fin.get("suggested") in names else next(
            (n for n in names if n.startswith("pixel-") and not re.search(r"place|polaroid|letterbox|sign", n)), names[0])
        trio = [n for n in fin.get("test_and_compare", []) if n in names] or ([sug] + [n for n in names if n != sug and not n.startswith("pixel-")][:2])
        draft = bool({"titles", "opening"} & set(w.get("template_fields", [])))
        spec = {"_note": (f"Drafted by tools/finish_video.py on {dt.date.today().isoformat()}: the title, the opening and the hashtags "
                          f"by the chat model in Truman's form ({w.get('source')}), from scenes/{self.scene}/brief.json and his "
                          "published videos (docs/records/*/published.md), checked with upload_package's rules. Edit freely: "
                          "the tool never overwrites this spec. Once it's live, record what he changed (master-render skill, "
                          "Upload checklist step 9)."),
                "slug": self.unique_slug(w["slug"]), "name": w["name"], "render": rel(self.out10),
                "video": "master_music.mp4" if self.has_music else "master.mp4", "thumbnails": rel(self.tspec),
                "thumbnail": sug, "test_and_compare": trio[:3], "draft_text": draft, "titles": w["titles"],
                "description": [w["opening"]], "hashtags": w["hashtags"], "tags": [], "category": "Film & Animation"}
        if self.look.get("ai_label"):
            spec["ai_use"] = True
            spec["ai_use_why"] = ("The look is photoreal (config/aesthetics.json ai_label), and YouTube asks for disclosure of "
                                  "realistic altered content. Truman decides at upload.")
        bl = self.blurb_lines()
        if bl:
            spec["blurb"] = bl
        probs = package_text_problems(spec, tspec, self)
        if probs:
            raise Stop("the drafted publish spec breaks upload_package's rules:\n  - " + "\n  - ".join(probs))
        return spec

    def blurb_lines(self):
        """His blurb with its list of sounds fitted to this video, or None when the standard one holds. It says "(rain,
        wind, thunder and every other effect)"; the Burdock Shelter had no thunder, and its fire crackled (2026-10-26, L158)."""
        import upload_package as U
        text = U.BLURB.read_text(encoding="utf-8").rstrip("\n")
        std = "(rain, wind, thunder and every other effect)"
        fx = facts(self.timeline(make=not self.dry), self.period, self.period)
        if std not in text or fx["lightning"] or fx["farflash"]:
            return None
        fire = any(L.get("type") == "fire" for L in self.sc.get("layers") or [])
        return text.replace(std, "(rain, wind, the crackling fire and every other effect)" if fire else
                            "(rain, wind and every other effect)").split("\n")

    def ledger_missing(self):
        """Tracks of the 10 h music plan that aren't in docs/asset-ledger.csv (AGENTS.md: logged before use)."""
        import csv
        tracks = self.load(self.out10 / "music_plan.json").get("tracks") or []
        with open(ROOT / "docs" / "asset-ledger.csv", newline="", encoding="utf-8") as fh:
            paths = {row["path"] for row in csv.DictReader(fh)}
        return [t["title"] for t in tracks if pathlib.PureWindowsPath(t["file"]).as_posix() not in paths]

    def log_fonts(self, fids):
        """Rows in docs/asset-ledger.csv for the thumbnail fonts that aren't logged yet (AGENTS.md: every asset is logged
        before use; OFL fonts are approved, config/fonts.json). Each is fetched once and pinned by tools/intro_title.py
        font_file; the author is the copyright holder in its OFL.txt. Returns the ids logged (in a dry run: to be logged)."""
        import csv
        import intro_title as IT
        led = ROOT / "docs" / "asset-ledger.csv"
        with open(led, newline="", encoding="utf-8") as fh:
            have = {row["path"] for row in csv.DictReader(fh)}
        cat = config("fonts")["fonts"]
        new, rows = [], []
        for fid in sorted(set(fids) - {None}):
            e = cat[fid]
            if e.get("kind") == "pixel" or f"cache/fonts/{e['file']}" in have:
                continue
            new.append(fid)
            if self.dry:
                continue
            p, _ = IT.font_file(fid)
            rows.append([f"cache/fonts/{e['file']}", "font (thumbnail text)", e["title"],
                         ofl_author(p.with_name(p.name + ".OFL.txt")) or f"{e['title']} authors", e["url"], "SIL Open Font License 1.1",
                         e.get("license_url", ""), "none (OFL needs no credit)", f"none ({self.scene} thumbnails)",
                         dt.date.today().isoformat(), f"config/fonts.json {fid}, pinned by sha256 in cache/fonts; OFL, approved by "
                         "Truman 2026-10-20 (docs/DECISIONS.md); logged by tools/finish_video.py"])
        if rows:
            text = led.read_text(encoding="utf-8")
            with open(led, "a", newline="", encoding="utf-8") as fh:
                if text and not text.endswith("\n"):
                    fh.write("\n")
                csv.writer(fh, lineterminator="\n").writerows([ledger_row(r) for r in rows])
        return new

    # -- stages

    def stage_check(self):
        t = time.time()
        probs = []
        if not self.period:
            probs.append("scene.json has no events.loop.period: the 10 h video loops one period of a timeline that repeats with "
                         "it (1200 s; master-render skill, lessons L54)")
        elif self.period % 60 or self.duration % self.period or not 600 <= self.period <= 3600:
            probs.append(f"events.loop.period is {self.period} s: make it whole minutes, 10 to 60 of them, that divide the "
                         f"video's {self.duration} s")
        if not self.sc.get("intro"):
            probs.append("scene.json has no intro: the opening line in the look's font (tools/intro_title.py, lessons L55)")
        if not self.brief:
            probs.append(f"there is no {self.sd / 'brief.json'}")
        if probs:
            raise Stop("; ".join(probs))
        detail = f"events.loop.period {self.period} s ({self.times} loops make {self.hours} h), intro set"
        cmd = [PY, ROOT / "tools" / "review.py", self.scene]
        self.show(cmd)
        if self.dry:
            import review
            fails = [f"{lid} {msg}" for lid, ok, msg in review.lint(self.scene) if ok is False]
            return self.rec("check", "would run review.py", f"{detail}; its lint has {len(fails)} FAIL now"
                            + "".join(f"; {x}" for x in fails), cmd)
        rc, lines = self.run(cmd, show=False, keep=None)
        lint = [x.strip() for x in lines if re.match(r"\s+FAIL L\d+", x)]
        end = max((i for i, x in enumerate(lines) if re.match(r"(PASS|FAIL): ", x)), default=len(lines))
        summary = [x for x in lines[end:] if x.strip()]
        for x in summary:
            print(f"    {x}", flush=True)
        if rc:
            raise Stop("tools/review.py found problems; fix them, then run this again:\n" + "\n".join(lint + summary), lint + summary)
        self.rec("check", "pass", f"{detail}; tools/review.py {self.scene}: {summary[0] if summary else 'PASS'}", cmd,
                 [x for x in lines if x.startswith("==") or re.match(r"\s+(ok|FAIL|look) ", x)] + summary, t)

    def stage_window(self):
        t = time.time()
        self.need_period()
        qa = self.win / "qa.md"
        cmd = [NODE, "src/cli.mjs", "render", f"scenes/{self.scene}", "--from", label(self.period), "--length", label(self.period),
               "--name", self.win.name, "--music", "off"]
        self.show(cmd)
        if passed(qa):
            return self.rec("window", "up to date", f"{qa} says Overall: PASS", cmd)
        if self.a.skip_render:
            return self.rec("window", "skipped", "--skip-render (the master stage needs a window that passed QA)", cmd)
        if self.dry:
            return self.rec("window", "would render", f"{label(self.period)} from {label(self.period)} into {self.win} (about "
                            "10 minutes of GPU; keep the GPU free)", cmd)
        rc, tail = self.run(cmd)
        if rc or not passed(qa):
            raise Stop(f"the window render {'stopped' if rc else 'finished without passing QA'} ({qa}):"
                       + "".join(f"\n  {x}" for x in tail[-4:]) + "\nIf it says render.json was made from different code or "
                       "config, give a new --version (the old folder stays).", tail)
        self.rec("window", "rendered", f"{self.win}: qa.md Overall PASS, master.mp4 {(self.win / 'master.mp4').stat().st_size / 1e9:.1f} GB",
                 cmd, tail, t)

    def stage_master(self):
        t = time.time()
        self.need_period()
        cmd = [PY, ROOT / "tools" / "loop_master.py", self.win, "--times", str(self.times), "--name", self.out10.name]
        self.show(cmd)
        st = self.master_state()
        if st["fresh"]:
            return self.rec("master", "up to date", st["why"], cmd)
        if not passed(self.win / "qa.md"):
            if self.dry:
                return self.rec("master", "would build", f"after the window passes QA: {st['why']}", cmd)
            raise Stop(f"the loop window has no passing QA ({self.win / 'qa.md'}): render it first (without --skip-render)")
        wm = self.win / "master.mp4"
        est = wm.stat().st_size * self.times if wm.exists() else 0
        files = int(st["master"]) + int(st["music"])
        need = est * files + (5e9 if files else 0)
        free = shutil.disk_usage(self.rd).free
        disk = (f"{files} new file(s) of about {est / 1e9:.0f} GB each (the window's master.mp4 x{self.times}): needs about "
                f"{need / 1e9:.0f} GB, {free / 1e9:.0f} GB free on {self.rd.anchor}")
        if free < need:
            raise Stop(f"not enough free disk for the 10 h build: {disk}. Free some space first (this tool deletes nothing; "
                       "old test renders and the seg/ of published 10 h masters are the usual candidates, master-render skill).")
        if self.dry:
            return self.rec("master", "would build", f"{st['why']}; {disk}", cmd)
        rc, tail = self.run(cmd)
        qa = self.out10 / "qa.md"
        if rc or not passed(qa):
            fails = [x.strip() for x in (qa.read_text(encoding="utf-8").splitlines() if qa.exists() else []) if "FAIL" in x]
            raise Stop(f"loop_master {'stopped' if not fails else 'QA failed'} ({qa}):"
                       + "".join(f"\n  {x}" for x in (fails[:12] or tail[-4:])), tail)
        made = ", ".join(f"{n} {(self.out10 / n).stat().st_size / 1e9:.1f} GB" for n in ("master.mp4", "master_music.mp4")
                         if (self.out10 / n).exists())
        self.rec("master", "built", f"{self.out10}: {made}; qa.md Overall PASS", cmd, tail, t)

    def stage_thumbs(self):
        t = time.time()
        cmd = [PY, ROOT / "tools" / "thumbnail.py", self.tspec]
        feed = self.load(self.pspec).get("feed")
        if feed:
            cmd += ["--feed", ROOT / feed]
        self.show(cmd)
        if self.tspec.exists():
            made = f"kept {self.tspec} (an existing spec is never overwritten)"
        else:
            self.need_period()
            plan = self.thumb_plan(self.timeline(make=not self.dry))
            names = ", ".join(n for n, _, _ in plan["concepts"])
            fonts = self.log_fonts(plan["fonts"].values())
            logged = f"; logs the fonts {', '.join(fonts)} in docs/asset-ledger.csv first" if fonts else ""
            if self.dry:
                return self.rec("thumbs", "would make the spec", f"{self.tspec}: frame {plan['frame']} ({plan['frame_why']}); hero "
                                f"{plan['hero']['name']}; concepts {names}; Test & compare {', '.join(plan['trio'])}{logged}; then "
                                "tools/thumbnail.py", cmd)
            spec = ThumbSpec(self, self.words(), plan).build()
            write_new(self.tspec, spec)
            made = (f"made {self.tspec}: {', '.join(v['name'] for v in spec['variants'])}; suggested "
                    f"{spec['_finish']['suggested']}; frame {plan['frame']} ({plan['frame_why']})"
                    + (f"; logged the fonts {', '.join(fonts)} in docs/asset-ledger.csv" if fonts else ""))
        why = self.thumbs_stale(self.tspec)
        if not why:
            return self.rec("thumbs", "up to date", f"{made}; every thumbnail is newer than the spec", cmd)
        if self.dry:
            return self.rec("thumbs", "would draw", f"{made}; {why}", cmd)
        rc, tail = self.run(cmd)
        left = self.thumbs_stale(self.tspec)
        if rc or left:
            raise Stop(f"tools/thumbnail.py {'failed' if rc else 'ran, but ' + left}", tail)
        self.rec("thumbs", "drawn", f"{made}; thumbnails in {self.thumb_dir(self.load(self.tspec))}", cmd, tail, t)

    def stage_publish(self):
        if self.pspec.exists():
            S = self.load(self.pspec)
            return self.rec("publish", "kept", f"{self.pspec} (an existing spec is never overwritten): {(S.get('titles') or [''])[0]}")
        if not self.tspec.exists():
            if self.dry:
                return self.rec("publish", "would make the spec", f"{self.pspec}, after the thumbnail spec: the title and the "
                                "opening by the chat model in his form")
            raise Stop(f"there is no {self.tspec}: run the thumbs stage first")
        if self.dry:
            return self.rec("publish", "would make the spec", f"{self.pspec}: the title and the opening by the chat model in his "
                            f"form, the video {'master_music.mp4' if self.has_music else 'master.mp4'} of {self.out10}")
        spec = self.publish_spec()
        write_new(self.pspec, spec)
        self.rec("publish", "made", f"{self.pspec}: {spec['titles'][0]}" + (" (plain template text, marked draft_text)" if spec["draft_text"] else ""))

    def stage_package(self):
        t = time.time()
        if not self.pspec.exists():
            if self.dry:
                return self.rec("package", "would write", "upload/<slug>/ after the publish spec is made")
            raise Stop(f"there is no {self.pspec}: run the publish stage first")
        S = self.load(self.pspec)
        tsp = ROOT / S["thumbnails"]
        cmd = [PY, ROOT / "tools" / "upload_package.py", self.pspec] + ([] if self.thumbs_stale(tsp) else ["--no-thumbs"])
        self.show(cmd)
        pkg = ROOT / "upload" / S["slug"]
        why = self.package_stale(S, tsp)
        if not why:
            return self.rec("package", "up to date", f"{pkg} is newer than everything it is made from", cmd)
        if self.dry:
            return self.rec("package", "would write", f"{pkg}: {why}", cmd)
        rc, tail = self.run(cmd)
        if rc:
            errs = [x for x in tail if x.strip().startswith("- ") or "not written" in x or x.startswith("missing")]
            raise Stop("tools/upload_package.py refused the package:\n" + "\n".join(errs or tail[-12:]), tail)
        self.rec("package", "written", f"{pkg} (README.md: the steps in YouTube Studio)", cmd, tail, t)

    # -- the report

    def outputs(self):
        out = []

        def item(what, p, extra=""):
            if p.exists():
                out.append(f"- {what}: {p}" + (f" ({extra})" if extra else ""))

        def qa_of(d):
            q = d / "qa.md"
            return "qa.md: Overall PASS" if passed(q) else "qa.md: not passed" if q.exists() else "no qa.md yet"
        item("Loop window", self.win, qa_of(self.win))
        item("Its intro segment", self.rd / f"{self.win.name}_intro_at{self.period}")
        item("10 hour folder", self.out10, qa_of(self.out10))
        for n in ("master_music.mp4", "master.mp4"):
            p = self.out10 / n
            item(f"The {'music master (upload this one)' if n.startswith('master_music') else 'ambience-only master'}", p,
                 f"{p.stat().st_size / 1e9:.1f} GB" if p.exists() else "")
        checks = ((self.load(self.out10 / "loop.json").get("qa") or {}).get("checks") or {})
        if checks:
            out.append("- 10 h QA: " + ", ".join(f"{k} {'pass' if v.get('pass') else 'FAIL'}" for k, v in checks.items()))
            for k in ("loudness", "music_loudness"):
                if k in checks:
                    out.append(f"  - {k}: {checks[k].get('lufs')} LUFS, true peak {checks[k].get('true_peak')} dBTP")
            if (self.out10 / "music_plan.json").exists():
                miss = self.ledger_missing()
                out.append("- Music in docs/asset-ledger.csv: " + ("every track" if not miss else
                           f"{len(miss)} missing ({', '.join(miss[:4])}): run .venv\\Scripts\\python tools\\music.py ledger "
                           f"{self.out10 / 'music_plan.json'}"))
        item("Thumbnail spec", self.tspec)
        spec = self.load(self.tspec)
        if spec:
            d = self.thumb_dir(spec)
            item("Thumbnails", d)
            item("Them at YouTube's sizes", d / "preview.png")
        item("Publish spec", self.pspec)
        S = self.load(self.pspec)
        if S:
            item("Upload package", ROOT / "upload" / S["slug"], "README.md has the steps in YouTube Studio")
        item("The chat model's words", self.words_path)
        return out or ["- nothing yet"]

    def text_lines(self):
        S, spec = self.load(self.pspec), self.load(self.tspec)
        d = self.thumb_dir(spec) if spec else None
        if S:
            L = [f"- Title: {S['titles'][0]}"] + [f"  - or: {x}" for x in S["titles"][1:]]
            L += [f"- Opening: {(S.get('description') or [''])[0]}", f"- Hashtags: {' '.join(S.get('hashtags', []))}"]
            if S.get("draft_text"):
                L.append("- The title or the opening is the plain template (the model's drafts broke the rules): write it in his "
                         "voice before the upload.")
            L.append(f"- Suggested thumbnail: {S['thumbnail']}" + (f", {d / (S['thumbnail'] + '.jpg')}" if d else ""))
            L.append(f"- Test & compare: {', '.join(S.get('test_and_compare', []))}")
            return L
        if spec:
            fin = spec.get("_finish") or {}
            return [f"- Suggested thumbnail: {fin.get('suggested') or spec['variants'][0]['name']}"]
        return ["- not drafted yet"]

    def next_lines(self):
        S, spec = self.load(self.pspec), self.load(self.tspec)
        slug = S.get("slug", "<slug>")
        prev = self.thumb_dir(spec) / "preview.png" if spec else "preview.png"
        return [f"1. Look at the thumbnails at phone size ({prev}) and the title. To pick another thumbnail or change the words, "
                f"edit {self.pspec} and run this command again: it writes the package again.",
                f"2. Spot-check the 10 h video in a player: the opening title, the first loop join at "
                f"{mmss((self.period or 0) // 60)}:00, a lightning strike with its thunder, the end.",
                f"3. Upload it as Private, following {ROOT / 'upload' / slug / 'README.md'}: the title, the description, the "
                "thumbnail, the AI-use answer and the Checks step. Publish once the 4K version is processed and the copyright "
                "check is clear.",
                f"4. Once it's live, record what he published and changed in {ROOT / 'docs' / 'records' / slug / 'published.md'}, "
                "set the spec's published field, and turn each change into a rule (master-render skill, Upload checklist step 9)."]

    def write_report(self):
        if self.dry:
            return
        took = time.time() - self.t0

        def cell(s):
            return str(s).replace("|", "/").replace("\n", " ")

        def secs(s):
            return "" if s is None else f"{s:.0f} s" if s < 120 else f"{s / 60:.0f} min"
        L = [f"# Finish: {self.scene} {self.a.version}", "",
             f"{self.started:%Y-%m-%d %H:%M}, `.venv\\Scripts\\python tools\\finish_video.py {' '.join(sys.argv[1:])}`: "
             f"{self.status}, {secs(took)}.", "", "| Stage | Result | Detail | Time |", "|---|---|---|---|"]
        L += [f"| {r['stage']} | {r['result']} | {cell(r['detail'])} | {secs(r['secs'])} |" for r in self.recs]
        L += ["", "## Outputs", "", *self.outputs(), "", "## Title and thumbnail", "", *self.text_lines(), "",
              "## What Truman does next", "", *self.next_lines()]
        logs = [r for r in self.recs if r["cmd"] or r["tail"]]
        if logs:
            L += ["", "## Log"]
            for r in logs:
                L += ["", f"### {r['stage']}", ""]
                if r["cmd"]:
                    L += ["```text", r["cmd"], "```", ""]
                if r["tail"]:
                    L += ["Its last lines:", "", "```text", *r["tail"][-30:], "```"]
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text("\n".join(L).rstrip() + "\n", encoding="utf-8")

    def go(self):
        print(f"finish_video {self.scene} {self.a.version}" + (" (dry run: nothing is written)" if self.dry else "")
              + f": {', '.join(self.a.only)}", flush=True)
        stage = None
        try:
            for stage in STAGES:
                if stage in self.a.only:
                    print(f"\n[{stage}]", flush=True)
                    getattr(self, f"stage_{stage}")()
            self.status = "finished"
        except Stop as e:
            self.status = f"stopped at {stage}"
            self.recs.append({"stage": stage, "result": "STOPPED", "detail": str(e), "cmd": "", "tail": e.tail, "secs": None})
            print(f"\nstopped at {stage}: {e}", flush=True)
        except KeyboardInterrupt:
            self.status = f"interrupted at {stage}"
            print(f"\ninterrupted at {stage}; run the same command again to go on", flush=True)
        self.write_report()
        if not self.dry:
            print(f"\nreport: {self.report}", flush=True)
        return 0 if self.status == "finished" else 1


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # Japanese lines and emoji on a Windows console
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", help="a scene folder under scenes/ (with scene.json and brief.json)")
    ap.add_argument("--version", default="v1", help="names the window (loop20_<version>) and the 10 h folder (10h_<version>)")
    ap.add_argument("--dry-run", action="store_true", help="print every command and what each stage would do; write nothing")
    ap.add_argument("--skip-render", action="store_true", help="don't render the loop window (the master stage needs one that passed QA)")
    ap.add_argument("--only", help=f"comma-separated stages: {','.join(STAGES)}")
    ap.add_argument("--out-suffix", default="", help=argparse.SUPPRESS)  # tests: <scene><suffix> specs, thumbnails<suffix>, finish<suffix>.md
    a = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+", a.version):
        ap.error("--version: letters, digits, dots, dashes or underscores")
    if a.out_suffix and not re.fullmatch(r"_[\w-]+", a.out_suffix):
        ap.error("--out-suffix: an underscore and a word, like _test")
    a.only = [s.strip() for s in a.only.split(",") if s.strip()] if a.only else list(STAGES)
    bad = [s for s in a.only if s not in STAGES]
    if bad:
        ap.error(f"--only: unknown stage(s) {', '.join(bad)}; the stages are {', '.join(STAGES)}")
    try:
        f = Finish(a)
    except Stop as e:
        sys.exit(f"finish_video: {e}")
    sys.exit(f.go())


if __name__ == "__main__":
    main()
