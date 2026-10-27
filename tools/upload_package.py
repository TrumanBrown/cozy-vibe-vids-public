"""Assemble the upload folder for one video: upload/<slug>/ holds everything YouTube Studio asks for.

  .venv\\Scripts\\python tools\\upload_package.py assets\\publish\\<scene>.json [--no-thumbs]

The spec (assets/publish/<scene>.json):
  slug, name             folder name and the video's public name
  render, video          the finished render or loop folder and the file in it to upload
  thumbnails, thumbnail  the thumbnail spec and its suggested variant; test_and_compare = up to 3 variants
  feed                   optional competitor list for thumbnail.py --feed
  titles                 suggested title first, then alternatives
  description            the video's own opening lines (Truman's form, 2026-10-20: "Come relax with rain on <the scene>,
                         with <the music> and <the weather>. 10 hours of 4K, calming ambience with smooth music. Never
                         interrupting with ads."); then come the channel blurb, the credits and the hashtags
  blurb                  default: assets/publish/description_blurb.txt (his own paragraphs, the same on every video);
                         a list of lines replaces it for one video (e.g. a scene without thunder), false leaves it out
  hashtags, tags, category, draft_text (true while the wording is a placeholder)
  ai_use                 YouTube's "AI use" answer for the README; Yes by default when a track's sidecar says
                         ai_made, and it can't be false then (YouTube lists AI generated music for disclosure);
                         ai_use_why gives the README's reason either way (the default No reason says the scene is
                         stylized, which isn't true of real footage)
  published              {url, date} once it is live (the live text is recorded in docs/records/<slug>/published.md)

upload/<slug>/
  README.md               what to do in YouTube Studio, in order, with every setting
  <slug>_<len>_<res>.mp4  the video: a hard link to the master (no extra disk space)
  thumbnail.jpg           the suggested thumbnail, 3840x2160; thumbnail_1280.jpg is under 2 MB, for phones
  thumbnail-options/      every variant (4K), preview.png (YouTube's sizes), feed_compare.png (among others, when made)
  title.txt               the suggested title, then alternatives
  description.txt         paste-ready: the opening, the blurb, credits where a track asks for them (tools/music.py
                          credits: CC0 music gets none), Mojang's disclaimer on Minecraft looks, hashtags
  tags.txt                for the Tags field (may be empty: he left them out on the ramen video)
  credits.txt             the credits on their own (also in description.txt)
  qa.md                   the render's QA report

Before writing anything it checks, and stops on a failure: YouTube's limits (title <= 100 characters,
description <= 5000, tags <= 500, at most 15 hashtags, no < or >), Mojang's naming rule (no title starts with
"Minecraft"), that no public text mentions AI (DECISIONS 2026-10-16), that the description carries Mojang's
disclaimer exactly when the video has the Minecraft look (tools/music.py scene_music),
that "music" is only promised with a music master, that the render's QA passed, that the video fits YouTube's
upload limit (256 GB and 12 hours), that a look that isn't pixel art has at least 3 thumbnail concepts in its
own fonts (config/aesthetics.json thumb; user 2026-10-20; the one he picks can be any of them), and that every
title says 4K and the suggested and Test & compare thumbnails say 4K and the length (e.g. 10 HR). The written
text (titles, description lines, blurb, tags, hashtags) must also pass the mechanical part of Truman's voice
rules: no em or en dashes, no exclamation mark and none of the stock AI words (voice_problems); no emoji, titles
included (user 2026-10-26). A spec made before that keeps its titles' emoji with "title_emoji": 2
(the ramen alley's 🍜 and ☔, the tea house's and the aquarium's drafts). Thumbnails are
regenerated first (--no-thumbs skips that). Re-run it after re-rendering or changing a spec: stale links
and copies are replaced.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from cozy.paths import ROOT, PY, config
from cozy.media import probe
from cozy.voice import AI_WORDS, voice_problems
DISCLAIMER = "NOT AN OFFICIAL MINECRAFT PRODUCT"
BLURB = ROOT / "assets" / "publish" / "description_blurb.txt"     # his own paragraphs, the same on every video


def length_label(seconds):
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h}h" if m == 0 else f"{h}h{m:02d}" if h else f"{m}m"


def tag_chars(tags):
    # YouTube counts the commas, and a tag with a space as if it were quoted.
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)


def thumb_texts(tspec, name):
    v = next((v for v in tspec["variants"] if v["name"] == name), {})
    rows = v.get("badges", tspec.get("badges", [])) + v.get("chips", [])
    return ([t["text"] for t in v.get("text", [])] + [c["text"] for r in rows for c in r["items"]]
            + [ln["text"] for c in v.get("cards", []) for ln in c.get("lines", [])])


def thumb_fonts(tspec, name):
    """The fonts a variant's text is drawn in (None = the pixel font)."""
    v = next((v for v in tspec["variants"] if v["name"] == name), {})
    rows = v.get("badges", tspec.get("badges", [])) + v.get("chips", [])
    return ([t.get("font") for t in v.get("text", [])] + [r.get("font") for r in rows]
            + [ln.get("font") for c in v.get("cards", []) for ln in c.get("lines", [])])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--no-thumbs", action="store_true", help="don't regenerate the thumbnails first")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # the title's emoji on a Windows console
    spec_path, S, render, video, tspec_path, tspec, tdir = _load_spec(a)
    errors = []

    info, dur = _check_inputs(render, video, errors)
    minecraft, ai_tracks, n_tracks, credits = _music_credits(S, render, video, errors)
    names = _thumb_names(S, tspec, tspec_path, errors)
    titles, blurb, hashtags, description, tags, public = _public_text(S, tspec, credits)
    _check_titles(S, tspec, tspec_path, names, titles, dur, errors)
    _check_counts(hashtags, description, errors)
    _check_look_fonts(S, tspec, names, errors)
    ai_use = _check_wording(S, video, minecraft, ai_tracks, titles, blurb, hashtags, description, tags, public, errors)
    if errors:
        sys.exit("upload package not written:\n  - " + "\n  - ".join(errors))

    _thumbnails(a, S, tspec_path, tdir, names)
    vs, pkg, vname, linked = _link_video(S, info, dur, video)
    opts = _copy_thumbnails(S, tdir, pkg, names)
    _write_texts(pkg, render, titles, description, tags, credits)

    # README.
    gb, hours_up, fps, spec_rel, opt_list, feed, draft, where, compare = _readme_files(S, spec_path, video, vs, names, opts, linked)
    claims, ai_line, credits_row, money, tags_line, chapters, length, channel = _readme_studio(
        S, video, minecraft, ai_use, ai_tracks, n_tracks, credits, titles, description, tags, dur)
    readme = _readme_text(S, spec_rel, draft, vname, length, vs, fps, gb, where, opt_list, feed, tags, credits_row, channel, hours_up,
                          compare, ai_line, chapters, tags_line, money, claims)
    (pkg / "README.md").write_text(readme, encoding="utf-8")

    print(f"upload package: {pkg}")
    print(f"  video      {vname} ({gb:.1f} GB, {'hard link' if linked else 'NOT linked, see video_location.txt'})")
    print(f"  thumbnail  {S['thumbnail']} + {len(names)} options")
    print(f"  title      {titles[0]} ({len(titles[0])} chars)")
    print(f"  description {len(description)} chars, tags {tag_chars(tags)} chars")


def _load_spec(a):
    """(the spec's path, the spec, the render folder, the video, the thumbnail spec's path, the thumbnail spec, the
    thumbnails' folder)."""
    spec_path = pathlib.Path(a.spec).resolve()
    S = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    # the slug names upload/<slug>/, where old videos and thumbnail options get deleted: plain words only, so a spec
    # can't point that at another folder
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){0,7}", str(S.get("slug", ""))):
        sys.exit(f"{spec_path.name}: slug {S.get('slug')!r} must be lowercase words joined by hyphens, like rainy-ramen-alley")
    render = ROOT / S["render"]
    video = render / S["video"]
    tspec_path = ROOT / S["thumbnails"]
    tspec = json.loads(tspec_path.read_text(encoding="utf-8-sig"))
    tdir = ROOT / tspec.get("out", f"out/{pathlib.Path(tspec['scene']).name}/thumbnails")
    return spec_path, S, render, video, tspec_path, tspec, tdir


def _check_inputs(render, video, errors):
    # Inputs.
    if not video.exists():
        sys.exit(f"missing video: {video}")
    info = probe(video, "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate")
    dur = float(info["format"]["duration"])
    qa = (render / "qa.md").read_text(encoding="utf-8") if (render / "qa.md").exists() else ""
    if "Overall: **PASS**" not in qa:
        errors.append(f"{render / 'qa.md'} doesn't say Overall: PASS")
    size_gb = video.stat().st_size / 1e9
    if size_gb > 256 or dur > 12 * 3600:
        errors.append(f"{video.name} is {size_gb:.1f} GB and {dur / 3600:.1f} h; YouTube takes at most 256 GB or 12 hours "
                      "(re-render the window one --cq step higher, checked against a lossless still first)")
    return info, dur


def _music_credits(S, render, video, errors):
    """(Minecraft look?, the AI-made tracks, how many tracks, the credits)."""
    import music  # noqa: E402
    minecraft = music.scene_music(pathlib.Path(S["render"]).parts[1])[1]      # out/<scene>/render/<tag>
    plan = {"entries": [], "tracks": [], "minecraft": minecraft}
    ai_tracks, n_tracks = [], 0
    if "music" in video.name:
        # The music credits come from the plan the music master was built from, not from credits.txt,
        # which the loop tool rewrites depending on its flags.
        plan_txt = (render / "music_plan.json").read_text(encoding="utf-8") if (render / "music_plan.json").exists() else ""
        loop = json.loads((render / "loop.json").read_text(encoding="utf-8")) if (render / "loop.json").exists() else {}
        want = (loop.get("music") or {}).get("plan_sha1")
        if not plan_txt:
            errors.append(f"{video.name} has music, but {render / 'music_plan.json'} is missing")
        elif want and hashlib.sha1(plan_txt.encode()).hexdigest()[:16] != want:
            errors.append("music_plan.json isn't the plan the music master was built from (loop.json plan_sha1)")
        else:
            plan = json.loads(plan_txt)
            tracks = plan.get("tracks", [])
            n_tracks = len(tracks)
            for t in tracks:
                sc = ROOT / pathlib.Path(*re.split(r"[\\/]", t["file"] + ".json"))
                if sc.exists() and json.loads(sc.read_text(encoding="utf-8")).get("ai_made"):
                    ai_tracks.append(t["title"])
    # Credits only where something asks for them (Mojang's tracks, CC-BY and the like); CC0 music gets none, as he
    # published the ramen video (the ledger keeps the provenance either way).
    credits = music.credits(plan).strip()
    return minecraft, ai_tracks, n_tracks, credits


def _thumb_names(S, tspec, tspec_path, errors):
    names = [v["name"] for v in tspec["variants"]]
    for n in [S["thumbnail"], *S.get("test_and_compare", [])]:
        if n not in names:
            errors.append(f"thumbnail variant {n!r} isn't in {tspec_path.name}")
    return names


def _public_text(S, tspec, credits):
    # Text: his opening for this video, his blurb, the credits, the hashtags (the form he published, 2026-10-20).
    titles = S["titles"]
    b = S.get("blurb", True)
    blurb = "\n".join(b).strip() if isinstance(b, list) else BLURB.read_text(encoding="utf-8").strip() if b else ""
    hashtags = S.get("hashtags", [])
    description = "\n\n".join(p for p in ("\n".join(S["description"]).strip(), blurb, credits, " ".join(hashtags)) if p)
    tags = S.get("tags", [])
    thumb_text = " ".join(thumb_texts(tspec, S["thumbnail"]))
    public = "\n".join([*titles, description, ", ".join(tags), thumb_text])
    return titles, blurb, hashtags, description, tags, public


def _check_titles(S, tspec, tspec_path, names, titles, dur, errors):
    for t in titles:
        if len(t) > 100:
            errors.append(f"title over 100 characters ({len(t)}): {t}")
        if re.match(r"\s*minecraft\b", t, re.I):
            errors.append(f"title starts with Minecraft (Mojang: only as a secondary part): {t}")
        if not re.search(r"(?i)\b4k\b", t):
            errors.append(f"title doesn't say 4K: {t}")
    hr_label = f"{round(dur / 3600, 1):g} HR"
    for n in dict.fromkeys([S["thumbnail"], *S.get("test_and_compare", [])]):
        if n not in names:
            continue
        shown = " ".join(thumb_texts(tspec, n))
        if not re.search(r"(?i)\b4k\b", shown):
            errors.append(f"thumbnail {n!r} doesn't say 4K (its badges in {tspec_path.name})")
        if not re.search(rf"(?i)\b{re.escape(hr_label)}\b", shown):
            errors.append(f"thumbnail {n!r} doesn't say the length ({hr_label!r})")


def _check_counts(hashtags, description, errors):
    if len(description) > 5000:
        errors.append(f"description over 5000 characters ({len(description)})")
    if len(hashtags) > 15:
        errors.append(f"{len(hashtags)} hashtags: YouTube ignores all of them over 15 (the first 3 show above the title)")
    for h in hashtags:
        if not re.fullmatch(r"#\w+", h):
            errors.append(f"hashtag {h!r}: one word after #")


def _check_look_fonts(S, tspec, names, errors):
    # Thumbnails in the look of the video (user 2026-10-20): unless the look is pixel art, the options include at
    # least 3 concepts in the look's own fonts (config/aesthetics.json thumb). The one he picks can be any of them:
    # he published the ramen alley with pixel-bowl.
    scene_dir = ROOT / "scenes" / pathlib.Path(S["render"]).parts[1]
    look = json.loads((scene_dir / "brief.json").read_text(encoding="utf-8")).get("aesthetic") if (scene_dir / "brief.json").exists() else None
    th = (config("aesthetics")["aesthetics"].get(look) or {}).get("thumb") or {}
    if th and "pixel" not in th.get("fonts", []):
        own = [n for n in names if any(f not in (None, "pixel") for f in thumb_fonts(tspec, n))]
        if len(own) < 3:
            errors.append(f"{len(own)} thumbnail concept(s) in the {look} look's own fonts ({', '.join(th['fonts'])}; "
                          "config/aesthetics.json thumb): make at least 3")


def _check_wording(S, video, minecraft, ai_tracks, titles, blurb, hashtags, description, tags, public, errors):
    """The disclaimer, YouTube's characters and limits, the voice rules and the AI answer; -> the AI answer."""
    if minecraft and DISCLAIMER not in description:
        errors.append("the description lacks Mojang's disclaimer (credits.txt adds it)")
    if not minecraft and DISCLAIMER in description:
        errors.append("Mojang's disclaimer in the description of a video without the Minecraft look")
    if re.search(r"[<>]", public):
        errors.append("< or > in the title, description or tags (YouTube rejects them)")
    if tag_chars(tags) > 500:
        errors.append(f"tags over 500 characters ({tag_chars(tags)})")
    m = AI_WORDS.search(public)
    if m:
        errors.append(f"public text mentions AI ({m.group(0)!r}); DECISIONS 2026-10-16")
    # Thumbnails (pixel glyphs) and the generated credits (track names) are exempt. No emoji in a title since
    # 2026-10-26 (L157); a spec from before keeps its titles' with "title_emoji": 2.
    errors += voice_problems("\n".join([*S["description"], blurb, *tags, *hashtags]))
    for t in titles:
        errors += [f"title {t!r}: {p}" for p in voice_problems(t, emoji=int(S.get("title_emoji", 0)))]
    if re.search(r"(?i)\bmusic\b", public) and "music" not in video.name:
        errors.append(f"the text or thumbnail promises music, but {video.name} isn't the music master")
    # YouTube asks for disclosure of AI generated music (DECISIONS 2026-10-20); the tracks' sidecars say ai_made.
    ai_use = S.get("ai_use", bool(ai_tracks))
    if ai_tracks and not ai_use:
        errors.append(f"{len(ai_tracks)} AI-made tracks in the music ({', '.join(ai_tracks[:3])}): YouTube's 'AI use' answer "
                      "must be Yes, so the spec's ai_use can't be false")
    return ai_use


def _thumbnails(a, S, tspec_path, tdir, names):
    # Thumbnails (regenerated so they match the spec).
    if not a.no_thumbs:
        cmd = [PY, str(ROOT / "tools" / "thumbnail.py"), str(tspec_path)]
        if S.get("feed"):
            cmd += ["--feed", str(ROOT / S["feed"])]
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    for n in names:
        if not (tdir / f"{n}.jpg").exists():
            sys.exit(f"missing thumbnail {tdir / (n + '.jpg')}; run tools/thumbnail.py {tspec_path}")


def _link_video(S, info, dur, video):
    """(the video stream, the package folder, the video's name in it, linked?)."""
    vs = next(s for s in info["streams"] if s["codec_type"] == "video")
    res = {2160: "4k", 1440: "1440p", 1080: "1080p"}.get(int(vs["height"]), f"{vs['height']}p")
    pkg = ROOT / "upload" / S["slug"]
    pkg.mkdir(parents=True, exist_ok=True)

    # Video: a hard link (same file, no copy); replaced if the master was rebuilt since.
    vname = f"{S['slug']}_{length_label(dur)}_{res}.mp4"
    dst = pkg / vname
    for old in pkg.glob("*.mp4"):
        if old.name != vname or not os.path.samefile(old, video):
            old.unlink()
    linked = True
    if not dst.exists():
        try:
            os.link(video, dst)
        except OSError:
            linked = False
            (pkg / "video_location.txt").write_text(f"{video}\n", encoding="utf-8")
    return vs, pkg, vname, linked


def _copy_thumbnails(S, tdir, pkg, names):
    # Thumbnails.
    shutil.copy2(tdir / f"{S['thumbnail']}.jpg", pkg / "thumbnail.jpg")
    shutil.copy2(tdir / f"{S['thumbnail']}_1280.jpg", pkg / "thumbnail_1280.jpg")
    opts = pkg / "thumbnail-options"
    if opts.exists():
        shutil.rmtree(opts)
    opts.mkdir()
    for i, n in enumerate(names, 1):
        shutil.copy2(tdir / f"{n}.jpg", opts / f"{i:02d}_{n}.jpg")
    for src, name in (("preview.png", "preview.png"), ("_feed_compare.png", "feed_compare.png")):
        if (tdir / src).exists():
            shutil.copy2(tdir / src, opts / name)
    return opts


def _write_texts(pkg, render, titles, description, tags, credits):
    # Text files.
    (pkg / "title.txt").write_text(titles[0] + "\n\nalternatives:\n" + "\n".join(titles[1:]) + "\n", encoding="utf-8")
    (pkg / "description.txt").write_text(description + "\n", encoding="utf-8")
    (pkg / "tags.txt").write_text(", ".join(tags) + "\n", encoding="utf-8")
    (pkg / "credits.txt").write_text(credits + "\n", encoding="utf-8")
    shutil.copy2(render / "qa.md", pkg / "qa.md")


def _readme_files(S, spec_path, video, vs, names, opts, linked):
    """What the README's table of files says about the video, the thumbnails and the spec."""
    gb = video.stat().st_size / 1e9
    hours_up = video.stat().st_size * 8 / 20e6 / 3600
    num, den = (int(x) for x in vs["r_frame_rate"].split("/"))
    fps = round(num / den)
    tc = S.get("test_and_compare", [])
    spec_rel = spec_path.relative_to(ROOT).as_posix()
    opt_list = ", ".join(f"`{i:02d}_{n}`" for i, n in enumerate(names, 1))
    feed = ", `feed_compare.png` among other channels' thumbnails" if (opts / "feed_compare.png").exists() else ""
    draft = (f"\n> **The title and description are plain drafts** until the language skills arrive. Edit them in "
             f"`{spec_rel}` and re-run the tool, or edit the .txt files here.\n") if S.get("draft_text") else ""
    where = (f"A hard link to the master in `{S['render']}`: it takes no extra disk space, and deleting either "
             f"copy leaves the other." if linked else "Not linked (different drive): `video_location.txt` has the path.")
    compare = (" Test & compare (needs advanced features): " + ", ".join(f"`{n}`" for n in tc)
               + " from `thumbnail-options/`.") if tc else ""
    return gb, hours_up, fps, spec_rel, opt_list, feed, draft, where, compare


def _readme_studio(S, video, minecraft, ai_use, ai_tracks, n_tracks, credits, titles, description, tags, dur):
    """What the README's YouTube Studio steps say about claims, AI use, credits, ads, tags, chapters and the channel."""
    claims = ""
    if "music" in video.name:
        fix = ("it's dropped from `config/minecraft_music.json` and the music master is rebuilt (under an hour)" if minecraft else
               "it's taken out of the look's music folder and the music master is rebuilt (under an hour)")
        claims = (f" If a music track gets a claim, don't publish; tell the agent which track, and {fix}. Studio may also "
                  "offer to mute that part.")
    if ai_use:
        why = (f"{len(ai_tracks)} of the {n_tracks} tracks in the playlist are AI-made (their sidecars say `ai_made`), and "
               "YouTube lists AI generated music among what must be disclosed." if ai_tracks else S.get("ai_use_why", "The spec says so."))
        ai_line = f'Altered content ("AI use"): **Yes**. {why} The label doesn\'t limit reach or monetization.'
    else:
        ai_line = ('Altered content ("AI use"): **No**. '
                   + S.get("ai_use_why", "Disclosure is only for realistic content, and this scene is stylized."))
    credits_row = ("the credits on their own (already in description.txt)" if credits else
                   "empty: no track asks for credit (CC0), so the description has none")
    no_ads = bool(re.search(r"(?i)\bno ads\b|never interrupting with ads|without ads", "\n".join([*titles, description])))
    money = ("on, with **mid-roll ads off**: the title and description promise no ads" if no_ads else
             "on, with few or no mid-roll ads, because ads wake people up")
    tags_line = "Tags: `tags.txt`" if tags else "Tags: none (he left them out on the ramen video; the hashtags carry the search terms)"
    chapters = (" The moments list in the description isn't meant as chapters."
                if re.search(r"(?m)^\d{1,2}:\d{2} ", description) else "")
    length = f"{int(dur // 3600)}:{int(dur % 3600 // 60):02d}:{int(dur % 60):02d}"
    channel = ("0. **Once per channel** (skip if done): the About text, keywords and settings in "
               "`assets/publish/channel.md`.\n") if (ROOT / "assets" / "publish" / "channel.md").exists() else ""
    return claims, ai_line, credits_row, money, tags_line, chapters, length, channel


def _readme_text(S, spec_rel, draft, vname, length, vs, fps, gb, where, opt_list, feed, tags, credits_row, channel, hours_up,
                 compare, ai_line, chapters, tags_line, money, claims):
    readme = f"""# Upload: {S['name']}

Everything YouTube Studio needs is in this folder. Made {datetime.date.today().isoformat()} by `tools/upload_package.py` from `{spec_rel}`.
{draft}
| File | What it's for |
|---|---|
| `{vname}` | the video: {length}, {vs['width']}x{vs['height']} {fps} fps {vs['codec_name'].upper()}, {gb:.1f} GB. {where} |
| `thumbnail.jpg` | the suggested thumbnail (`{S['thumbnail']}`), 3840x2160. `thumbnail_1280.jpg` is the same under 2 MB, for uploading from a phone. |
| `thumbnail-options/` | every thumbnail, in case you prefer another: {opt_list}. `preview.png` shows them at YouTube's sizes{feed}. |
| `title.txt` | the suggested title (first line), then alternatives |
| `description.txt` | paste the whole file into the description |
| `tags.txt` | paste into Tags{'' if tags else ' (empty on purpose)'} |
| `credits.txt` | {credits_row} |
| `qa.md` | the render's quality report (Overall: PASS) |

## In YouTube Studio

{channel}1. **Create → Upload videos**, choose `{vname}`. {gb:.0f} GB takes about {hours_up:.0f} h at 20 Mbit/s upload; keep the computer awake.
2. **Details**
   - Title: the first line of `title.txt`. Description: all of `description.txt`.
   - Thumbnail: Upload file → `thumbnail.jpg`.{compare}
   - Audience: **No, it's not made for kids** (it's for sleep and study).
   - Show more:
     - Paid promotion: no.
     - {ai_line}
     - Automatic chapters: **off**.{chapters}
     - {tags_line}. Language: English. Category: {S.get('category', 'Film & Animation')}. License: Standard YouTube License. Allow embedding: on. Comments: on.
3. **Monetization** (once the channel is in the Partner Program): {money}.
4. **Checks**: wait for the copyright check to say no issues.{claims}
5. **Visibility**: save as **Private** first. When the 4K version has finished processing (hours, for 10 h) and the checks are clear, switch to Public or schedule it.
6. Afterwards: put the link in `docs/STATUS.md`. The old test folders and `seg/` listed there can then be deleted.
"""
    return readme


if __name__ == "__main__":
    main()
