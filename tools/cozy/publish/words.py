"""The words of a finished video: the place name, the thumbnail tags and the publish text, drafted by the chat model in
Truman's form and checked against his rules and the facts of the timeline. Moved verbatim from finish_video.py (TASKS.md
T15), which imports them from here.

  facts(tl, R0, L)                    what happens in one loop period: counts per event type, the strikes, the closest
  words_prompt(f, fx, subj, records)  the chat model's prompt (f: finish_video's Finish)
  template_words(f, fx, subj)         plain words from the brief and the look, where the model's fail
  word_problems(f, w, fx)             [(field, problem)] for words that break the rules or the facts
  draft_words(f, fx, subj, records)   the model's words, checked; one more try; the template where they still fail
"""
import json
import re
from collections import Counter

from cozy.paths import config
from cozy.voice import AI_WORDS, BRANDS, voice_problems

EVENT_WORDS = {"lightning": "lightning strikes with thunder", "farflash": "far flashes with distant thunder",
               "boat": "boats passing", "birds": "birds crossing the sky", "perch": "birds landing on the wires",
               "ant": "an ant crossing", "critter": "a small creature crawling past", "moth": "a moth at a lamp",
               "neon": "a neon sign flickering", "gutter": "a lantern flickering", "flurry": "gusts of wind",
               "heron": "a heron flying past", "fish": "fish jumping", "lantern": "a lantern flickering"}


def region_word(g):
    """One word for a region in variant names: sleeping_cat -> cat, ramen_bowl -> bowl, hearth_fire -> fire."""
    if g["kind"] == "pet":
        return re.sub(r"[^a-z]", "", (g.get("species") or g["name"].split("_")[-1]).lower()) or "pet"
    if g["kind"] == "fire":
        return "fire"
    return re.sub(r"[^a-z]", "", g["name"].split("_")[-1].lower()) or g["kind"]


def facts(tl, R0, L):
    """What happens in one loop period, from the timeline: counts per event type, the strikes and the closest one."""
    ev = [e for e in (tl or {}).get("events", []) if R0 <= e["t"] < R0 + L]
    n = Counter(e["type"] for e in ev)
    dist = [(e.get("thunder") or {}).get("distance_m") for e in ev if e["type"] == "lightning"]
    dist = [d for d in dist if d]
    return {"counts": dict(n), "lightning": n.get("lightning", 0), "farflash": n.get("farflash", 0),
            "closest_m": min(dist) if dist else None, "storm": bool(n.get("lightning") or n.get("farflash")),
            "known": bool(tl)}


# ---- The words: the place name, the thumbnail tags and the publish text, drafted by the chat model in Truman's form.

SYSTEM = ("You draft the public text of Truman's YouTube channel of 10 hour cozy ambience videos: one animated scene each, "
          "with rain or snow, sound made in his engine and often music. You write the way he publishes: plain, warm and "
          "literal, in his own form, never like an ad. Answer with one JSON object and nothing else.")
STOCK_WORDS = ("stunning, breathtaking, vibrant, captivating, seamless, robust, delve, tapestry, testament, nestled, immerse, "
               "immersive, embark, unleash, elevate, unlock, discover, dive in, deep dive, journey through, moreover, "
               "furthermore, additionally, ultimately, that said, worth noting, important to note, in conclusion, not just, "
               "more than just")
WORD_FIELDS = ("name", "slug", "music_word", "music_tag", "weather_word", "weather_tag", "note", "caption", "opening", "hashtags")
SHAPE = {"name": "the place's name for the thumbnail and the title: 1 to 3 words in title case, like Ramen Alley or Autumn Treetop",
         "slug": "the upload folder's name: 2 to 4 lowercase words joined by hyphens, like rainy-ramen-alley",
         "music_word": "the music as it leads the title, one or two words, like Lofi",
         "music_tag": "the music on the thumbnail tag, lowercase, ending in music, like chill lofi music",
         "weather_word": "one lowercase word, like rain or snow",
         "weather_tag": "the weather on a thumbnail tag, lowercase, at most 30 characters, like rain & distant thunder",
         "note": "a short handwritten line for the close-up, lowercase, at most 34 characters, like shh, the cat's asleep",
         "caption": "a polaroid caption, lowercase, at most 40 characters, like ramen alley, a rainy night",
         "titles": ["three titles in his form, the best first"],
         "opening": "the description's first paragraph in his form",
         "hashtags": ["about 8 hashtags"]}


def promise_line(f):
    return (f"{f.hours} hours of 4K, calming ambience with smooth music. Never interrupting with ads." if f.has_music else
            f"{f.hours} hours of 4K, calming ambience. Never interrupting with ads.")


def music_desc(f):
    if f.minecraft:
        return "calm Minecraft music by Mojang's own composers (their official Creator-Safe tracks)"
    return re.sub(r"\s*\([^)]*\)", "", f.look.get("music") or "music").strip()


def subject_desc(f, subj):
    if not subj:
        return "the scene"
    if subj["kind"] == "pet":
        bits = [subj.get("look"), subj.get("pose"), f"on a {subj['place']}" if subj.get("place") else None]
        return ", ".join(b for b in bits if b) or f.brief.get("pet") or "the pet"
    w = region_word(subj)
    return next((p for p in f.brief.get("props") or [] if w in p.lower()), subj["name"].replace("_", " "))


def picture_desc(f):
    """What the picked key art really shows, from the plate analysis (regions.json), grouped by kind, and whether any
    water runs off a roof or an edge. The brief is a plan, and the key art can lack part of it: the pixel greenhouse's
    brief planned rain spilling from the roof gutter into a trough; the picture has the trough and nothing spills, and
    the draft description promised the spill (2026-10-22)."""
    groups = {}
    for g in f.regions():
        name = re.sub(r"(_\d+)+$", "", str(g.get("name") or "")).replace("_", " ").strip()
        groups.setdefault(str(g.get("kind") or "other"), set()).add(name)
    seen = "; ".join("glass panes" if k == "glass" else ", ".join(sorted(n for n in v if n)) for k, v in sorted(groups.items()))
    layers = {str(l.get("type")) for l in f.sc.get("layers") or [] if isinstance(l, dict)}
    runs = f.sc.get("runoff") or []
    water = (f"{len(runs)} stream(s) of rain running off the roof" if runs else
             "drops falling from wet edges, but no stream running off" if "drips" in layers else
             "none: no gutter, eave or roof spills water in this video, so never mention a gutter, runoff or water spilling")
    return seen or "not known", water


def words_prompt(f, fx, subj, records):
    def clean(s):                 # the brief's internal notes in parentheses ("(Truman 2026-10-19: ...)") stay out
        return re.sub(r"\s*\([^)]*\b(?:Truman|user|20\d\d-\d\d-\d\d)\b[^)]*\)", "", str(s or "")).strip()
    b = {k: ([clean(x) for x in v] if isinstance(v, list) else clean(v)) for k, v in f.brief.items() if isinstance(v, (str, list))}
    look = f.look
    fr = look.get("franchise")
    ev = ", ".join(f"{EVENT_WORDS.get(k, k)} {n}" for k, n in sorted(fx["counts"].items(), key=lambda kv: -kv[1]))
    storm = (f"lightning strikes with thunder {fx['lightning']} times (the closest {fx['closest_m']} m away) and far flashes "
             f"{fx['farflash']} times, so distant thunder and a storm passing in the distance are true" if fx["lightning"] else
             "far flashes with distant thunder, so distant thunder is true" if fx["farflash"] else
             "no lightning and no thunder, so never mention thunder, lightning or a storm")
    music = (f"{music_desc(f)} ({f.n_tracks} tracks in its playlist)" if f.has_music else
             "none, the video is ambience only. No title, tag, line or hashtag may mention music; music_word and music_tag "
             "are empty strings")
    intro = " / ".join(x if isinstance(x, str) else x.get("text", "") for x in ((f.sc.get("intro") or {}).get("lines") or []))
    rule = ""
    if f.minecraft:
        rule = ("This is a Minecraft look: its music is calm Minecraft music (music_tag \"calm minecraft music\"), and "
                "\"Minecraft\" may only be a secondary part of a title, never its first word.")
    elif fr:
        rule = f"The look is like {fr}: that name may only be a secondary part of a title, never its first word, never the place name."
    parts = ["How he published his last videos, and what he changed from my drafts. Follow his form; the ramen alley is the "
             "reference.", ""]
    for path, text in records:
        parts += [f"=== {path} ===", text.strip(), ""]
    seen, water = picture_desc(f)
    parts += [f"The new video ({f.scene}):",
              f"- Look: {look.get('title', f.look_id)} ({look.get('style', '')})",
              f"- Setting: {b.get('setting', '')}",
              f"- Time: {b.get('time', '')}. Weather: {b.get('weather', '')}.",
              f"- Pet: {b.get('pet') or 'none'}",
              f"- In the picture (what the analysis of the key art found): {seen}",
              f"- Water running off the roof or an edge: {water}",
              f"- Planned in the brief, which the key art may not show (use only what the picture list above confirms): "
              f"props: {'; '.join(b.get('props') or []) or 'none'}; signature: {b.get('signature', '')}",
              f"- Its signature detail: {b.get('signature_detail') or 'none'}",
              f"- In every {f.period // 60} minutes of the video (from its timeline): {ev or 'not known yet'}",
              f"- Weather facts: {storm}.",
              f"- Music: {music}.",
              f"- The line shown at its start: {intro or 'none'}",
              *([f"- The place's name is fixed: \"{place_name(f)}\", the brief's, the name he knows the video by. Use it "
                 "as the name, in every title and in the slug, word for word."] if place_name(f) else []),
              *([f"- Its characters are the channel's own creatures, each based on a real species native to the Pacific "
                 f"Northwest: {and_list(cast_species(f))}. The opening names every one of these species by its common "
                 "name, word for word, saying what each is doing in the picture."] if cast_species(f) else []),
              f"- The thumbnail's close-up shows: {subject_desc(f, subj)}",
              f"- Length: {f.hours} hours, 4K.",
              "", "Return this JSON object:", json.dumps(SHAPE, indent=1, ensure_ascii=False), "", "His rules:",
              f"- Each title: <music word> <place name>. <what it's for, in plain words>. 4K, {f.hours} hours, no Ads. Like "
              f"\"Lofi Ramen Alley. Study and relax with calming rain. 4K, 10 hours, no Ads\". At most 100 characters and no "
              f"emoji (his rule since 2026-10-26). {rule}".rstrip(),
              f"- The opening: \"Come relax with <the weather> on <the scene, concrete and short>, with <the music> and <the "
              f"weather's sounds>.\" then \"{promise_line(f)}\" Like \"Come relax with rain on a small ramen stall in a Japanese "
              "alley at night, with chill lofi music and a storm passing in the distance. 10 hours of 4k, calming ambience with "
              "smooth music. Never interrupting with ads.\"",
              "- Hashtags: about 8, one word after each #. First the three YouTube shows above the title: the music, the sound "
              "and the use (like #lofi #rainsounds #studymusic), then #study #relaxing #relax #4k #10hours.",
              f"- No em or en dashes, no exclamation marks, no emoji anywhere, and none of these words: {STOCK_WORDS}.",
              "- Never mention AI, how the picture was made, or stock footage. No brand or franchise name in the name, the "
              "note or the caption.",
              "- Every fact must be true of this video: the weather facts and the music above, and each thing the opening "
              "names is in the picture list or the timeline above, never only in the brief's plan."]
    return "\n".join(parts)


def place_name(f):
    """The brief's place name (plan --auto writes it; the opening line and his messages use it), or "". The words model
    renamed the Burdock Shelter "Burdock Camp" for its thumbnails, title and upload folder (2026-10-26, L158)."""
    return str(f.brief.get("place_name") or "").strip()


def cast_species(f):
    """The species the brief's cast are based on (config/cast.json "species"), in the brief's order. The description
    names them (user 2026-10-26: the description names the species, L159)."""
    try:
        cast = config("cast")["cast"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []
    return [cast[k]["species"] for k in f.brief.get("cast") or [] if (cast.get(k) or {}).get("species")]


def and_list(xs):
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


def template_words(f, fx, subj):
    """Plain words from the brief and the look, used where the model's fail the rules (or in a dry run)."""
    b = f.brief
    name = place_name(f) or " ".join(w.capitalize() for w in f.scene.split("-"))
    ww = "snow" if re.search(r"snow|blizzard", (b.get("weather") or "").lower()) else "rain"
    mt, mw, mh = "", "", "#ambience"
    if f.has_music:
        mt, mw, mh = "calm music", "Calm", "#ambience"
        if f.minecraft:
            mt, mw, mh = "calm minecraft music", "Calm Minecraft", "#minecraftmusic"
        else:
            low = (f.look.get("music") or "").lower()
            for key, tag, word, hashtag in (("lofi", "chill lofi music", "Lofi", "#lofi"), ("jazz", "smooth jazz music", "Jazz", "#jazz"),
                                            ("synthwave", "synthwave music", "Synthwave", "#synthwave"),
                                            ("piano", "soft piano music", "Piano", "#pianomusic"),
                                            ("orchestral", "soft orchestral music", "Orchestral", "#orchestralmusic"),
                                            ("guitar", "acoustic guitar music", "Acoustic", "#acousticmusic"),
                                            ("harp", "soft harp music", "Harp", "#harpmusic")):
                if key in low:
                    mt, mw, mh = tag, word, hashtag
                    break
    storm = fx["storm"]
    wtag = f"{ww} & distant thunder" if storm else "falling snow" if ww == "snow" else "soft rain"
    note = f"shh, the {region_word(subj)}'s asleep" if subj and subj["kind"] == "pet" else f"{name.lower()} in the {ww}"
    tw = {"dusk": "evening", "evening": "evening", "late evening": "evening", "morning": "morning", "day": "day"}.get(b.get("time") or "", "night")
    adj = "snowy" if ww == "snow" else "rainy"
    use = "Study and relax with calming rain" if ww == "rain" else "Sleep and relax with falling snow"
    title = f"{mw + ' ' if mw else ''}{name}. {use}. 4K, {f.hours} hours, no Ads"
    place = (b.get("setting") or f"a {name.lower()}").split(",")[0].strip()
    sp = cast_species(f)
    opening = (f"Come relax with {ww} at {place}" + (f", with {mt}" if mt else "") + (" and a storm passing in the distance" if storm else "")
               + ". " + (f"The friends here are {and_list([('an ' if s[0] in 'aeiou' else 'a ') + s for s in sp])}, all native to "
                         "the Pacific Northwest. " if sp else "") + promise_line(f))
    slug = re.sub(r"[^a-z0-9]+", "-", (name if name.lower().startswith(adj) else f"{adj} {name}").lower()).strip("-")
    return {"name": name, "slug": slug, "music_word": mw, "music_tag": mt, "weather_word": ww, "weather_tag": wtag, "note": note,
            "caption": f"{name.lower()}, a {adj} {tw}", "titles": [title], "opening": opening,
            "hashtags": [mh, "#snowambience" if ww == "snow" else "#rainsounds", "#studymusic" if mt else "#sleepsounds",
                         "#study", "#relaxing", "#relax", "#4k", f"#{f.hours}hours"]}


def word_problems(f, w, fx):
    """[(field, problem)] for words that break upload_package's text rules, his form or the facts of the video."""
    P = []

    def add(field, msg):
        P.append((field, msg))

    def rules(field, t, emoji=0):
        for p in voice_problems(t, emoji):
            add(field, f"{field} {t!r}: {p}")
        if AI_WORDS.search(t):
            add(field, f"{field} {t!r} mentions AI")
        if re.search(r"[<>]", t):
            add(field, f"{field} {t!r} has < or >")
        if not fx["storm"] and re.search(r"(?i)thunder|storm|lightning", t):
            add(field, f"{field} {t!r}: this video has no lightning or thunder, so it can't mention them")
        if not f.has_music and re.search(r"(?i)music|lofi|jazz|piano|beats", t):
            add(field, f"{field} {t!r}: this video has no music (ambience only), so it can't mention any")

    for k in WORD_FIELDS:
        if not isinstance(w.get(k), list if k == "hashtags" else str):
            add(k, f"{k} is missing")
    if not isinstance(w.get("titles"), list) or not w["titles"] or not all(isinstance(t, str) for t in w["titles"]):
        add("titles", "titles is missing (a list of 3)")
    if P:
        return P
    name = w["name"].strip()
    if not 1 <= len(name.split()) <= 4 or len(name) > 26:
        add("name", f"name {name!r}: 1 to 4 words, at most 26 characters")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){1,4}", w["slug"]):
        add("slug", f"slug {w['slug']!r}: 2 to 5 lowercase words joined by hyphens")
    pn = place_name(f)
    if pn:
        if name != pn:
            add("name", f"name {name!r}: the place's name is the brief's, {pn!r}")
        if re.sub(r"[^a-z0-9]+", "-", pn.lower()).strip("-") not in w["slug"]:
            add("slug", f"slug {w['slug']!r}: it holds the place's name, {pn!r}")
        for i, t in enumerate(w["titles"]):
            if pn.lower() not in t.lower():
                add(f"title{i}", f"title {t!r} doesn't name the place, {pn!r}")
    mt, mw = w["music_tag"].strip(), w["music_word"].strip()
    if f.has_music:
        if "music" not in mt or len(mt) > 30 or mt != mt.lower():
            add("music_tag", f"music_tag {mt!r}: lowercase, ending in music, at most 30 characters")
        if not 1 <= len(mw.split()) <= 2:
            add("music_word", f"music_word {mw!r}: one or two words")
        if f.minecraft and "minecraft" not in mt:
            add("music_tag", f"music_tag {mt!r}: a Minecraft look's tag says calm minecraft music")
    elif mt or mw:
        add("music_tag", "this video has no music: music_tag and music_word stay empty")
    if not re.fullmatch(r"[a-z]+", w["weather_word"].strip()):
        add("weather_word", f"weather_word {w['weather_word']!r}: one lowercase word")
    for k, n in (("weather_tag", 30), ("note", 34), ("caption", 40)):
        if not w[k].strip() or len(w[k]) > n:
            add(k, f"{k} {w[k]!r}: at most {n} characters")
    for k in ("name", "music_word", "music_tag", "weather_word", "weather_tag", "note", "caption"):
        rules(k, w[k])
        brand = BRANDS.search(re.sub(r"(?i)minecraft", "", w[k]) if f.minecraft and k.startswith("music") else w[k])
        if brand:
            add(k, f"{k} {w[k]!r}: no brand or franchise names here ({brand.group(0)!r})")
    for i, t in enumerate(w["titles"]):
        k = f"title{i}"
        rules(k, t, emoji=0)
        if len(t) > 100:
            add(k, f"title {t!r}: {len(t)} characters, at most 100")
        if not re.search(r"(?i)\b4k\b", t):
            add(k, f"title {t!r} doesn't say 4K")
        if not re.search(rf"(?i)\b{f.hours} hours\b", t):
            add(k, f"title {t!r} doesn't say {f.hours} hours")
        m = BRANDS.search(t)
        if m and not re.sub(r"\W", "", t[:m.start()]):
            add(k, f"title {t!r} starts with a brand or franchise name (only a secondary part)")
        if re.search(r"(?i)\b(mojang|microsoft|nintendo)\b", t):
            add(k, f"title {t!r} names a company")
    o = w["opening"]
    rules("opening", o)
    if not o.startswith("Come relax"):
        add("opening", f"opening {o[:60]!r}...: his openings start with \"Come relax\"")
    for sp in cast_species(f):
        if sp.lower() not in o.lower():
            add("opening", f"opening doesn't name the {sp} (the description names the cast's species, L159)")
    if not re.search(rf"(?i)\b{f.hours} hours of 4k\b", o) or "Never interrupting with ads" not in o:
        add("opening", f"opening: end it with \"{promise_line(f)}\"")
    if len(o) > 600:
        add("opening", f"opening: {len(o)} characters, keep it under 600")
    hs = w["hashtags"]
    if not 5 <= len(hs) <= 12:
        add("hashtags", f"{len(hs)} hashtags: about 8")
    for h in hs:
        if not isinstance(h, str) or not re.fullmatch(r"#\w+", h):
            add("hashtags", f"hashtag {h!r}: one word after #")
    for need in ("#4k", f"#{f.hours}hours"):
        if need not in [str(h).lower() for h in hs]:
            add("hashtags", f"the hashtags lack {need}")
    if all(isinstance(h, str) for h in hs):
        rules("hashtags", " ".join(hs))
    return P


def parse_json(text):
    """The model's JSON object ({} when it isn't one)."""
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        try:
            out = json.loads(text[s:e + 1]) if s >= 0 < e else {}
        except json.JSONDecodeError:
            out = {}
    return out if isinstance(out, dict) else {}


def draft_words(f, fx, subj, records):
    """The chat model's words, checked; one more try with the problems; the template where they still fail."""
    fb = template_words(f, fx, subj)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": words_prompt(f, fx, subj, records)}]
    got, probs, log, usd = {}, [("all", "no answer")], [], 0.0
    try:
        import azure_ai
    except Exception as e:                       # noqa: BLE001
        azure_ai, log = None, [f"tools/azure_ai.py didn't load: {e}"]
    for attempt in (1, 2):
        if azure_ai is None:
            break
        try:
            text, usage = azure_ai.chat(msgs, purpose=f"finish:{f.scene}:words", json_mode=True, effort="medium", max_tokens=8000)
        except (Exception, SystemExit) as e:     # noqa: BLE001 (az login missing exits)
            log.append(f"the chat model failed: {e}")
            break
        usd += float(usage.get("usd_est") or 0)
        got = parse_json(text)
        probs = word_problems(f, got, fx)
        log.append(f"try {attempt}: {len(probs)} problem(s)" + "".join(f"; {m}" for _, m in probs))
        print(f"  words, try {attempt}: {len(probs)} problem(s)" + "".join(f"\n    - {m}" for _, m in probs), flush=True)
        if not probs:
            break
        msgs += [{"role": "assistant", "content": text},
                 {"role": "user", "content": "These break his rules or the facts of this video:\n- " + "\n- ".join(m for _, m in probs)
                  + "\nReturn the whole JSON object again with them fixed."}]
    bad = {k for k, _ in probs}
    if "all" in bad or "titles" in bad:
        bad |= {"titles"}
    w = {k: (got[k] if got and k not in bad and k in got else fb[k]) for k in WORD_FIELDS}
    titles = [t for i, t in enumerate(got.get("titles") or []) if f"title{i}" not in bad and "titles" not in bad and isinstance(t, str)]
    w["titles"] = titles or fb["titles"]
    template = [k for k in WORD_FIELDS if w[k] is fb[k]] + ([] if titles else ["titles"])
    w["hashtags"] = list(dict.fromkeys(str(h).lower() if h.lower() in ("#4k", f"#{f.hours}hours") else h for h in w["hashtags"]))
    return {**w, "source": "model" if not template else "template" if len(template) == len(WORD_FIELDS) + 1 else "model and template",
            "template_fields": template, "log": log, "usd_est": round(usd, 4)}
