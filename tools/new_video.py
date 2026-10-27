"""New-video workflow: aesthetic + brief -> key art -> plate -> analysis -> animated scene -> previews.

The stages of a new video, one subcommand each, safe to re-run. tools/autopilot.py runs them in order from one line
(since 2026-10-21, with one stop: Truman's OK on the reviewed 5 minute sample). Run them by hand to fix a stage, or
when he asks to go step by step (then the old stops apply: he picks the key art, then approves a preview with sound).

  .venv/Scripts/python tools/new_video.py plan <scene> --aesthetic <id> [--auto] [--hint "..."] [--weather "..." --weather-why "..."]
      write scenes/<scene>/brief.json (--auto: the vision/chat model writes a fresh brief for that
      aesthetic, avoiding every existing brief) and scenes/<scene>/keyart.json
  .venv/Scripts/python tools/new_video.py prompt <scene>         rebuild keyart.json from brief.json
  .venv/Scripts/python tools/new_video.py keyart <scene> [--n 2] [--model <deployment>]
      generate candidates -> assets/keyart/<scene>/ + out/<scene>/keyart_sheet.jpg      (step by step: he picks)
  .venv/Scripts/python tools/new_video.py pick <scene> <png | --auto>   record the hero (auto: model ranks)
  .venv/Scripts/python tools/new_video.py prep <scene>           4K plate + depth (tools/plate_prep.py)
  .venv/Scripts/python tools/new_video.py analyze <scene>        regions + masks + scene.json + clean.json (tools/analyze_plate.py)
  .venv/Scripts/python tools/new_video.py clean <scene>          remove painted steam, flames and drips (along the awning and,
      found by a zoomed vision scan, anywhere else) from the key art (tools/plate_clean.py, Azure image edit) and rebuild
      the plate from it; check out/plates/<scene>/clean_preview.jpg and strands_verify.jpg
  .venv/Scripts/python tools/new_video.py life <scene>           critter sprite (tools/critter.py), the fire's clips
      (tools/fire_clips.py): local video model, ~10 min of GPU per clip, and the simulated steam over bowls and pots
      (tools/steam_sim.py, ~2 min of GPU each). No pet clips: a painted pet only breathes
  .venv/Scripts/python tools/new_video.py preview <scene> [--seconds 10] [--start <s>]
      stills + a preview clip with sound (showcase window: the busiest seconds)        (step by step: he approves)
  .venv/Scripts/python tools/new_video.py catalog [--check <scene>]   every brief, fingerprint overlaps
  .venv/Scripts/python tools/new_video.py status [<scene>]       which stages are done
  .venv/Scripts/python tools/new_video.py spend [--since 2026-10-16]

Nothing that moves in reality may stay painted and still: analyze lists painted steam, flames and drips, clean
removes them, the layers (steam.js, fire.js, drips.js) animate them (the fire from clips of the key art's own fire);
rivers flow, wet ground takes the rain, birds cross the sky, a critter crawls. A pet painted into the key art only
breathes (user 2026-10-18: generated video of it looked eerie and AI); a pet that moves must be a 3D or library asset.
tools/motion_review.py --static checks a preview for anything that should move but doesn't.

After his OK, tools/finish_video.py builds the 20 minute loop window, the 10 hour video, the thumbnails and the
upload folder (master-render skill). The skill .agents/skills/new-video/SKILL.md has the whole procedure.
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

from cozy.paths import ROOT, PY, config, scene_dir
from cozy.media import run_ffmpeg
AES = config("aesthetics")


def load_brief(scene):
    p = scene_dir(scene) / "brief.json"
    if not p.exists():
        sys.exit(f"no brief: {p} (run `new_video.py plan {scene} --aesthetic <id>`)")
    return json.loads(p.read_text(encoding="utf-8"))


def save_brief(scene, brief):
    p = scene_dir(scene) / "brief.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# the boilerplate's one-pet sentence, and what a look with its own creatures says instead (config/cast.json; Truman
# 2026-10-25: original creatures, a recurring cast, awake doing something quiet)
ONE_PET = ("No other animals besides the one pet: no birds, insects, snails or frogs anywhere (small creatures are animated "
           "in afterwards).")
CAST_ONLY = ("No other creatures besides the characters described: no birds, insects or snails anywhere (small creatures are "
             "animated in afterwards).")


def cast_text(ids):
    """The cast members' descriptions, word for word from config/cast.json, so they look the same in every video."""
    cast = config("cast")["cast"]
    missing = [i for i in ids if i not in cast]
    if missing:
        sys.exit(f"unknown cast member(s) {missing}; config/cast.json has {', '.join(cast)}")
    return "The characters, drawn exactly as described: " + " ".join(f"({k + 1}) {cast[i]['prompt']}" for k, i in enumerate(ids))


def build_prompt(brief):
    """The key-art prompt in the order that moves the image model (art-direction reference in the keyart-pipeline skill):
    the look's style block, the scene as a moment, the cast word for word, the light, the composition, the pipeline's
    needs, and the look's avoid list."""
    a = AES["aesthetics"][brief["aesthetic"]]
    parts = [a["style_prompt"], f"The scene: {brief['setting']}."]
    fg = brief.get("foreground") or f"{brief.get('pet', '')}; {', '.join(brief.get('props', [])[:1])}"
    mg = brief.get("midground") or ", ".join(brief.get("props", [])[1:])
    bg = brief.get("background") or f"a window with clear glass showing {brief.get('weather', 'rain')} outside"
    parts += [f"Foreground: {fg}.", f"Midground: {mg}.", f"Background: {bg}."]
    if brief.get("stages"):
        parts.append("Also in view: " + "; ".join(s.rstrip(".") for s in brief["stages"]) + ".")
    if brief.get("cast"):
        parts.append(cast_text(brief["cast"]))
    if brief.get("light"):
        parts.append(brief["light"].rstrip(".") + ".")
    if brief.get("composition"):
        parts.append(brief["composition"].rstrip(".") + ".")
    boiler = AES["boilerplate"]
    if brief.get("cast"):
        boiler = boiler.replace(ONE_PET, CAST_ONLY).replace("the windows and the animal", "the windows and the characters")
    parts.append(boiler)
    if a.get("avoid"):
        parts.append(a["avoid"])
    return " ".join(p for p in parts if p.strip(". "))


def write_keyart_spec(scene, brief, n=2):
    a = AES["aesthetics"][brief["aesthetic"]]
    defaults = {"size": "2560x1440", "quality": "high", "n": n}
    if a.get("keyart_model"):
        # gpt-image-2 follows a hand-made medium; the default model keeps its own house style (2026-10-25)
        defaults["deployment"] = a["keyart_model"]
    spec = {"_note": f"Generated by tools/new_video.py from brief.json ({brief['aesthetic']}). Edit the brief, then `new_video.py prompt {scene}`.",
            "defaults": defaults,
            "items": [{"id": "hero", "prompt": build_prompt(brief)}]}
    (scene_dir(scene) / "keyart.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return spec


# ---------------------------------------------------------------- catalog / fingerprints

STOP = set("a an the of with and in on at by to from its it is are under over into onto near next beside small big large cozy".split())


def tokens(s):
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def fingerprint(b):
    return {"aesthetic": b.get("aesthetic"), "style": AES["aesthetics"].get(b.get("aesthetic"), {}).get("style"),
            "setting": tokens(b.get("setting")), "time": b.get("time"), "weather": b.get("weather"),
            "pet": tokens(b.get("pet")), "props": tokens(" ".join(b.get("props", [])))}


def similarity(f1, f2):
    """0..1: how interchangeable two videos would look (YouTube inauthentic-content guardrail)."""
    def jac(x, y):
        return len(x & y) / max(1, len(x | y))
    s = 0.25 * (f1["aesthetic"] == f2["aesthetic"]) + 0.1 * (f1["style"] == f2["style"])
    s += 0.3 * jac(f1["setting"], f2["setting"]) + 0.1 * (f1["time"] == f2["time"]) + 0.1 * (f1["weather"] == f2["weather"])
    s += 0.1 * jac(f1["pet"], f2["pet"]) + 0.05 * jac(f1["props"], f2["props"])
    return round(s, 3)


def all_briefs():
    out = {}
    for p in sorted((ROOT / "scenes").glob("*/brief.json")):
        out[p.parent.name] = json.loads(p.read_text(encoding="utf-8"))
    return out


def catalog(check=None):
    briefs = all_briefs()
    rows = []
    for k, b in briefs.items():
        hero = "hero" if b.get("hero") else "-"
        stage = b.get("status", "brief")
        rows.append(f"  {k:22s} {b.get('aesthetic', '?'):20s} {b.get('time', ''):10s} {b.get('weather', ''):14s} {stage:10s} {hero}")
    print(f"{len(briefs)} briefs:\n" + "\n".join(rows))
    keys = list(briefs)
    pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if check and check not in (keys[i], keys[j]):
                continue
            s = similarity(fingerprint(briefs[keys[i]]), fingerprint(briefs[keys[j]]))
            pairs.append((s, keys[i], keys[j]))
    pairs.sort(reverse=True)
    print("most similar pairs (>= 0.55 is too close: change the setting, time, weather or pet):")
    for s, a, b in pairs[:8]:
        print(f"  {s:.2f}  {a} ~ {b}" + ("   TOO CLOSE" if s >= 0.55 else ""))
    return pairs


# ---------------------------------------------------------------- stages

def cmd_plan(a):
    if a.aesthetic not in AES["aesthetics"]:
        sys.exit(f"unknown aesthetic {a.aesthetic}; one of: {', '.join(AES['aesthetics'])}")
    # a look that is still an idea lists the code it needs (config/aesthetics.json `needs`, docs/IDEAS.md)
    missing = [p for p in AES["aesthetics"][a.aesthetic].get("needs", []) if not (ROOT / p).exists()]
    if missing:
        sys.exit(f"{a.aesthetic} is an idea that needs new code first ({', '.join(missing)}); see docs/IDEAS.md")
    d = scene_dir(a.scene)
    if (d / "brief.json").exists() and not a.force:
        sys.exit(f"{d / 'brief.json'} exists (use --force to replace it)")
    aes = AES["aesthetics"][a.aesthetic]
    if a.auto:
        from azure_ai import chat
        others = [{k: v for k, v in b.items() if k in ("aesthetic", "setting", "time", "weather", "pet", "props", "signature", "signature_detail", "status")} for b in all_briefs().values()]
        hint = a.hint or "none"
        for attempt in range(2):
            prompt = (
                "You plan one new 10-hour cozy ambience video for a YouTube channel. Write a brief for the aesthetic below as a JSON object "
                "with keys: setting, time, weather, pet, props (2-4), signature (the one motion this video is remembered by), "
                "signature_detail (one small, odd, charming living detail only this video has, that viewers would point out in the "
                "comments, like the ramen alley's ant crossing the counter and walking over its edge. Pick it from what the code places "
                "and animates on its own: a small creature crawling on a level surface (a snail, a ladybug, a beetle, a gecko, a frog, "
                "a mouse), a moth circling a lamp at night, small birds landing on a wire to sit a while, petals drifting off a "
                "blossoming tree, smoke from a chimney; say where it happens in the picture. Never a person, never the painted pet "
                "moving; different from every existing video's, so not the ant unless the hint asks for it), stages (3-5 places in "
                "view where the code brings small life, each a short phrase for the image prompt naming only the place, never the "
                "creature, bird, moth or smoke itself (those are animated in afterwards: painted, they would sit frozen), chosen to "
                "fit the setting: power or phone lines crossing the sky, a lit lamp or lantern outdoors, a chimney or stove pipe on "
                "a building across the way, a tree in blossom, open water, a step, ledge or planter in the near ground, a near "
                "table or counter with a cup or bowl; the signature detail's place is one of them), foreground, "
                "midground, background, light, title_idea, place_name (a short name for the place in title case, 2-3 words, used in "
                "titles and thumbnails, like \"Ramen Alley\" or \"Autumn Treetop\"), intro_lines (the line shown in the first seconds "
                "of the video: one short, warm line in the owner's voice that welcomes the viewer into this place, specific to it, "
                "like \"welcome in, have some ramen and relax\"; when it names the place, say it as he does, with \"the\": \"Welcome "
                "to the Seedling House\", never \"Welcome to Seedling House\" (user 2026-10-21); optionally a short native greeting before it when the setting has "
                "one, like \"いらっしゃいませ\"; a list of 1 or 2 strings, no dashes, no exclamation marks). Rules: one locked-off wide shot; no humans; one sleeping animal with ears and tail "
                "visible; 1-2 props the code can animate (steam, a fire, candles, a hanging lantern or chime, string lights, a neon sign); a "
                "window or opening showing weather if the setting allows; clear glass in windows (the code adds the rain on the glass); "
                "concrete visual detail, no brand names except the aesthetic's franchise. It must be clearly different from every existing "
                "video listed (different setting, layout, time, weather or pet), not a palette swap.\n\n"
                f"Aesthetic: {json.dumps(aes)}\n\nExisting videos: {json.dumps(others)}\n\nHint from the user: {hint}")
            if a.weather:
                # the weather is his call (2026-10-25: not every video needs rain)
                prompt += (f"\n\nThe weather is fixed by the user: {a.weather}. Use exactly this weather, and let the "
                           "foreground, background, light and props fit it (no rain on the glass or wet ground without rain).")
            if aes.get("brief_rules"):
                # a look with its own creatures (config/cast.json) and its own art direction (2026-10-25)
                cast = config("cast")["cast"]
                pick = {k: v["prompt"] for k, v in cast.items() if v.get("status") == "approved"}
                prompt = prompt.replace(
                    "one sleeping animal with ears and tail visible",
                    "the characters are the look's own creatures (below), awake doing something quiet, never a real animal")
                prompt += (f"\n\nThis look's own rules: {aes['brief_rules']} Add the keys \"cast\" (a list of 2 to 4 ids from "
                           f"{json.dumps(pick, ensure_ascii=False)}, exactly the hint's when it names them; their looks are pasted "
                           "into the image prompt word for "
                           "word, so describe only what they do and where they are) and \"composition\" (camera height and "
                           "direction, where the characters sit, what frames the picture, where the quiet space is). The "
                           "\"pet\" key says what the characters are doing.")
            text, usage = chat([{"role": "user", "content": prompt}], purpose=f"plan:{a.scene}", json_mode=True, effort="medium")
            brief = json.loads(text)
            print(f"  (model wrote the brief, ~${usage['usd_est']:.3f})")
            # a near-duplicate of an existing video is reused content to YouTube: one more try, told which one it resembles
            fp = fingerprint({"aesthetic": a.aesthetic, **brief})
            close = sorted(((similarity(fp, fingerprint(b)), k) for k, b in all_briefs().items() if k != a.scene), reverse=True)
            if not close or close[0][0] < 0.55:
                break
            s, k = close[0]
            print(f"  too close to {k} ({s:.2f}); asking again")
            hint = (f"{a.hint or ''} It must not resemble the existing video {k} ({all_briefs()[k].get('setting')}): "
                    "change the place, and the time, weather or pet.").strip()
        else:
            sys.exit(f"the brief stays too close to {k} ({s:.2f}): give a hint with a different setting")
    else:
        brief = {"setting": a.hint or aes["settings"][0], "time": aes["times"][0], "weather": aes["weather"][0],
                 "pet": aes["pets"][0], "props": aes["props"][:3]}
    if a.weather:
        brief["weather"] = a.weather
    brief["weather_why"] = a.weather_why or brief.get("weather_why") or "chosen by the plan model (Truman not asked)"
    brief = {"scene": a.scene, "aesthetic": a.aesthetic, "created": dt.date.today().isoformat(), **brief}
    save_brief(a.scene, brief)
    write_keyart_spec(a.scene, brief, a.n)
    print(json.dumps(brief, indent=2, ensure_ascii=False))
    catalog(check=a.scene)


def cmd_prompt(a):
    b = load_brief(a.scene)
    spec = write_keyart_spec(a.scene, b, a.n)
    print(spec["items"][0]["prompt"])


def contact_sheet(paths, out, cols=2, w=960):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    h = round(w * 9 / 16)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 34)), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for i, (p, im) in enumerate(zip(paths, ims)):
        x, y = (i % cols) * w, (i // cols) * (h + 34)
        sheet.paste(im.resize((w, h), Image.LANCZOS), (x, y + 34))
        d.text((x + 8, y + 8), f"{i + 1}: {pathlib.Path(p).name}", fill=(230, 230, 230))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=90)
    return out


def candidates(scene):
    return sorted((ROOT / "assets" / "keyart" / scene).glob("*.png"))


def cmd_keyart(a):
    b = load_brief(a.scene)
    write_keyart_spec(a.scene, b, a.n)
    args = [PY, str(ROOT / "tools" / "keyart.py"), str(scene_dir(a.scene) / "keyart.json"), "--n", str(a.n)]
    if a.model:
        args += ["--model", a.model]
    if subprocess.run(args).returncode != 0:
        sys.exit("key art generation failed")
    c = candidates(a.scene)
    sheet = contact_sheet(c, ROOT / "out" / a.scene / "keyart_sheet.jpg")
    print(f"{len(c)} candidates; contact sheet: {sheet}")


DETAIL_Q = ("These are full-size crops of the characters in one illustration, one crop per character, in order. The owner rejects "
            "any drawing error on them (2026-10-25: a leaf umbrella cut off a character's antennas and cropped the right "
            "antenna wrong, and a backpack strap clipped through its arm; details like these are not acceptable). Look "
            "closely at every crop for: a body part cut off, cropped wrong or ending abruptly (an antenna, a leg, a tail, a wing); "
            "something held or worn passing through a limb or the body (a strap through an arm, a twig through a hand, a scarf "
            "through the neck); a hand that does not really hold what it holds; extra, missing or merged legs, counted against the "
            "description where it gives a number (insects six, crabs eight legs and two claws); a storybook creature with two "
            "arms and two legs is fine unless the description says otherwise; a main feature of the description missing or "
            "different (a missing scarf, lantern, leaf or pack, the wrong body colors). The crops are cut out of a bigger "
            "picture: something that runs off a crop's edge is not an error. Loose painterly brushwork and small style "
            "differences (a glint in an eye, the eye's size, a slightly different shade, where a stripe ends) are not errors. "
            "The characters should be: {cast}. Answer as JSON: {{\"errors\": [{{\"crop\": 1, "
            "\"what\": \"...\", \"confidence\": 0.0}}], \"seen\": \"briefly\"}}")


def detail_errors(path, boxes, b, min_conf=0.6):
    """Drawing errors on the cast's characters, judged on full-size crops of each (the pick model sees the whole frame at
    1024 px, too small for a strap through an arm). The model is not steady on fine detail (on the same crops it found a
    strap clipping one time and nothing the next, 2026-10-25), so it votes: up to three asks, and a character counts as
    wrong only when two asks flag it. Returns ([what the asks said about those characters], usd)."""
    from PIL import Image
    from azure_ai import vision_json
    im = Image.open(path).convert("RGB")
    crops = []
    for bx in boxes[:6]:
        try:
            x0, y0, x1, y1 = (float(v) for v in bx)
        except (TypeError, ValueError):
            continue
        gx, gy = 0.12 * (x1 - x0), 0.12 * (y1 - y0)
        box = (int(max(0, x0 - gx) * im.width), int(max(0, y0 - gy) * im.height), int(min(1, x1 + gx) * im.width), int(min(1, y1 + gy) * im.height))
        if box[2] - box[0] > 16 and box[3] - box[1] > 16:
            crops.append(im.crop(box))
    if not crops:
        return [], 0.0
    cast = config("cast")["cast"]
    want = "; ".join(cast[i]["prompt"] for i in b.get("cast", []) if i in cast)
    asks, usd = [], 0.0
    while True:
        votes = {}
        for x in asks:
            for n in {e[0] for e in x}:
                votes[n] = votes.get(n, 0) + 1
        bad = {n for n, v in votes.items() if v >= 2}
        open_ = {n for n, v in votes.items() if v == 1}
        if len(asks) >= 3 or (len(asks) >= 2 and not open_):
            break
        res, usage = vision_json(DETAIL_Q.format(cast=want), images=crops, purpose=f"pick:{b.get('scene', '')}:details", max_side=1400)
        usd += float(usage.get("usd_est", 0.0))
        errs = []
        for e in res.get("errors") or []:
            try:
                if isinstance(e, dict) and float(e.get("confidence") or 0) >= min_conf:
                    errs.append((str(e.get("crop")), str(e.get("what"))))
            except (TypeError, ValueError):
                continue
        asks.append(errs)
    return sorted({f"crop {n}: {w}" for x in asks for n, w in x if n in bad}), usd


def cmd_pick(a):
    b = load_brief(a.scene)
    if a.auto:
        from azure_ai import vision_json
        c = candidates(a.scene)
        if not c:
            sys.exit("no candidates")
        q = ("These are key-art candidates for a 10-hour cozy ambience video that will be animated in code (rain, rain on glass, "
             "snow, steam, fire flicker, floating candles, a breathing pet, neon flicker, passing car lights). Brief: "
             f"{json.dumps({k: b.get(k) for k in ('setting', 'pet', 'props', 'signature', 'background')})}. For each image (in order) "
             "score 1-10: composition (calm, readable, locked-off, depth), animatable (the elements the code animates are clearly "
             "visible and separated: window glass, fire, steam source, the pet with ears and tail, light sources), artifacts (10 = none: "
             "no garbled text or letters, no malformed objects, no extra legs, no people), brief (matches the brief). Return JSON: "
             "{\"scores\": [{\"index\": 1, \"composition\": n, \"animatable\": n, \"artifacts\": n, \"brief\": n, \"note\": \"...\"}], \"best\": index}")
        if b.get("cast"):
            q = q.replace("Return JSON: ", "Also give \"characters\" for each image: a box [x0, y0, x1, y1] as fractions of the image "
                          "(0, 0 top left) around each character with whatever it holds or wears. Return JSON: ").replace(
                "\"brief\": n, \"note\"", "\"brief\": n, \"characters\": [[0, 0, 0, 0]], \"note\"")
        res, usage = vision_json(q, images=c, purpose=f"pick:{a.scene}", max_side=1024)
        usd = float(usage.get("usd_est", 0.0))
        if b.get("cast"):
            # the cast's drawing errors, on full-size crops (user 2026-10-25: errors like these can't ship, lessons L138)
            for s in res.get("scores", []):
                i = int(s.get("index", 0)) - 1
                if not 0 <= i < len(c):
                    continue
                errs, cost = detail_errors(c[i], s.get("characters") or [], b)
                usd += cost
                s["detail_errors"] = errs
                if errs:
                    s["artifacts"] = min(int(s.get("artifacts") or 10), 3)
            total = lambda s: sum(int(s.get(k) or 0) for k in ("composition", "animatable", "artifacts", "brief"))  # noqa: E731
            pool = [s for s in res.get("scores", []) if not s.get("detail_errors")] or res.get("scores", [])
            if pool:
                res["best"] = max(pool, key=total)["index"]
        for s in res.get("scores", []):
            print(f"  {s.get('index')}: comp {s.get('composition')} anim {s.get('animatable')} art {s.get('artifacts')} brief {s.get('brief')}  {s.get('note', '')}")
            for e in s.get("detail_errors") or []:
                print(f"     detail error: {e}")
        hero = c[int(res["best"]) - 1]
        b["pick_scores"] = res.get("scores")
        print(f"  (~${usd:.3f})")
    else:
        hero = pathlib.Path(a.png).resolve()
    b["hero"] = str(hero.relative_to(ROOT)).replace("\\", "/")
    b["status"] = "picked"
    save_brief(a.scene, b)
    print(f"hero: {b['hero']}")


def source_image(scene, b):
    """The key art the plate is built from: the cleaned copy (tools/plate_clean.py) once it exists."""
    c = ROOT / "assets" / "keyart" / scene / "clean.png"
    return c if c.exists() else ROOT / b["hero"]


def cmd_prep(a):
    b = load_brief(a.scene)
    if not b.get("hero"):
        sys.exit("pick the hero first")
    args = [PY, str(ROOT / "tools" / "plate_prep.py"), str(source_image(a.scene, b)), "--name", a.scene, "--sr-from", "0"]
    if a.masks_only:
        args.append("--masks-only")
    if subprocess.run(args).returncode != 0:
        sys.exit("plate_prep failed")
    if b.get("status") in (None, "brief", "picked"):
        b["status"] = "plate"
        save_brief(a.scene, b)


def cmd_clean(a):
    """Remove the painted transients the analysis listed (assets/keyart/<scene>.clean.json), then rebuild the plate
    from the cleaned key art (same geometry, so masks and regions stay valid)."""
    cj = ROOT / "assets" / "keyart" / f"{a.scene}.clean.json"
    if not cj.exists():
        print("nothing to clean (no clean.json)")
        return
    if subprocess.run([PY, str(ROOT / "tools" / "plate_clean.py"), a.scene] + (["--force"] if a.force else [])).returncode != 0:
        sys.exit("plate_clean failed")
    b = load_brief(a.scene)
    if subprocess.run([PY, str(ROOT / "tools" / "plate_prep.py"), str(source_image(a.scene, b)), "--name", a.scene, "--sr-from", "0"]).returncode != 0:
        sys.exit("plate_prep failed")
    print(f"check out/plates/{a.scene}/clean_preview.jpg")


def cmd_life(a):
    """The scene's living extras: the critter sprite (tools/critter.py), the fire's clips (tools/fire_clips.py:
    the key art's own painted fire animated; ~10 min of GPU per clip) and the simulated steam over every vessel with
    a measured opening, cup or bowl (tools/steam_sim.py: ~2-3 min of GPU each). Never clips of the pet: a pet painted
    into the key art only breathes (DECISIONS 2026-10-18), so tools/pet_clips.py is not part of the flow."""
    spec = json.loads((scene_dir(a.scene) / "scene.json").read_text(encoding="utf-8"))
    for L in spec.get("layers", []):
        if L.get("type") == "critter":
            cr = L.get("creature", "snail")
            if not (ROOT / "assets" / "keyart" / a.scene / f"critter_{cr}.png").exists():
                subprocess.run([PY, str(ROOT / "tools" / "critter.py"), a.scene, "gen", "--creature", cr], check=True)
    regs = json.loads((ROOT / "out" / "plates" / a.scene / "regions.json").read_text(encoding="utf-8"))
    if any(L.get("type") == "pet" for L in spec.get("layers", [])) or (spec.get("events") or {}).get("petAct"):
        print(f"! {a.scene}: scene.json still plays generated pet clips (a 'pet' layer, events.petAct). A painted pet only "
              "breathes (DECISIONS 2026-10-18): remove them when the scene's renders are next changed.")
    if any(g["kind"] == "fire" for g in regs) and any(L.get("type") == "fire" for L in spec.get("layers", [])) and not a.no_fire:
        subprocess.run([PY, str(ROOT / "tools" / "fire_clips.py"), a.scene, "auto"], check=True)
    # the channel's own cast is awake (user 2026-10-25): their eyes and closed lids for the blink layer, from the
    # cleaned plate (tools/cast_eyes.py; autopilot's setup adds the layer)
    if load_brief(a.scene).get("cast") and any(g["kind"] == "pet" for g in regs):
        subprocess.run([PY, str(ROOT / "tools" / "cast_eyes.py"), a.scene], check=True)
    # Cups, bowls, pots: the steam is a fluid simulation from the whole surface (user 2026-10-19: the procedural veil
    # was still too wispy; round 4: a cup's wisps read as two separate sources); re-run when the opening changes
    # (plate_prep) or the steam layer's lean does
    vessels = [g for g in regs if g["kind"] == "steam" and g.get("opening") and g.get("opening_fit") in ("rim", "hand")]
    if vessels and any(L.get("type") == "steam" for L in spec.get("layers", [])) and not a.no_steam:
        for g in vessels:
            sj = ROOT / "out" / "plates" / a.scene / "steam" / g["name"] / "steam.json"
            want = [round(v, 1) for v in (g["opening"][0] * 3840, g["opening"][1] * 2160, g["opening"][2] * 3840, g["opening"][3] * 2160)]
            if sj.exists() and not a.force:
                sm = json.loads(sj.read_text())
                from steam_sim import VERSION, sim_overrides
                own = {k: float(v) for k, v in (sim_overrides(spec).get(g["name"]) or {}).items()}
                if (sm["opening"] == want and sm.get("version", 0) >= VERSION and sm.get("frames") == round(float(spec.get("loopSeconds", 120)) * 30)
                        and (sm.get("sim") or {}) == own):
                    print(f"  steam {g['name']}: simulated plume up to date")
                    continue
            subprocess.run([PY, str(ROOT / "tools" / "steam_sim.py"), a.scene, "--region", g["name"]], check=True)


def cmd_analyze(a):
    args = [PY, str(ROOT / "tools" / "analyze_plate.py"), a.scene] + (["--reuse"] if a.reuse else [])
    if subprocess.run(args).returncode != 0:
        sys.exit("analysis failed")


def showcase_start(tl, seconds=10.0, horizon=900.0, step=0.5):
    """Start time of the most eventful `seconds` window in the first `horizon` s of a timeline: a storm strike
    whose thunder lands inside counts most, then spotlight events, then ambient ones."""
    w = {"lightning": 6, "farflash": 2.5, "train": 5, "star": 4, "ember": 3, "car": 2, "neon": 2, "gutter": 1.5,
         "flurry": 1.5, "boat": 4, "heron": 4, "fish": 1, "lantern": 1.5, "birds": 2.5, "petact": 5, "critter": 2}
    ev = [e for e in tl.get("events", []) if e["t"] < horizon + seconds]
    best, bs = 0.0, -1.0
    s = 2.0
    while s < horizon:
        sc = 0.0
        for e in ev:
            if s + 1.0 <= e["t"] <= s + seconds - 2.0:
                th = e.get("thunder")
                sc += w.get(e["type"], 0.5) * (1.0 if not th or th["t"] < s + seconds - 1.0 else 0.4)
        if sc > bs:
            best, bs = s, sc
        s += step
    return best, bs


def cmd_sample(a):
    """A short showcase clip (default 10 s) of the scene's busiest moment, with sound -> out/samples/<scene>.mp4."""
    sd = scene_dir(a.scene)
    tlp = ROOT / "out" / a.scene / "timeline.json"
    r = subprocess.run(["node", str(ROOT / "src" / "cli.mjs"), "timeline", f"scenes/{a.scene}", "--duration", "1h"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stderr or r.stdout)
    tl = json.loads(tlp.read_text(encoding="utf-8"))
    start = float(a.start) if a.start is not None else showcase_start(tl, a.seconds)[0]
    evs = [f"{e['type']}@{e['t'] - start:.1f}s" for e in tl["events"] if start <= e["t"] < start + a.seconds]
    print(f"{a.scene}: showcase from {start:.1f} s: {', '.join(evs) or 'continuous motion only'}")
    raw = ROOT / "out" / a.scene / "sample_raw.mp4"
    args = ["node", str(ROOT / "src" / "cli.mjs"), "preview", f"scenes/{a.scene}", "--seconds", str(a.seconds),
            "--start", str(round(start * 30)), "--duration", "1h", "--out", str(raw)]
    if subprocess.run(args).returncode != 0:
        sys.exit("preview failed")
    out = pathlib.Path(a.out) if a.out else ROOT / "out" / "samples" / f"{a.scene}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    fo = max(0.0, a.seconds - 0.6)
    run_ffmpeg(["-v", "error", "-y", "-i", str(raw), "-c:v", "copy", "-af", f"afade=t=in:d=0.4,afade=t=out:st={fo}:d=0.6",
                "-c:a", "aac", "-b:a", "320k", str(out)], capture=False)
    meta = {"scene": a.scene, "aesthetic": json.loads((sd / "brief.json").read_text(encoding="utf-8"))["aesthetic"],
            "start_s": start, "seconds": a.seconds, "events": evs}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"sample: {out}")


def cmd_preview(a):
    args = ["node", str(ROOT / "src" / "cli.mjs"), "preview", f"scenes/{a.scene}", "--seconds", str(a.seconds)]
    if a.start is not None:
        args += ["--start", str(round(float(a.start) * 30))]
    if a.out:
        args += ["--out", a.out]
    if a.params:
        args += ["--params", a.params]
    sys.exit(subprocess.run(args).returncode)


def cmd_status(a):
    scenes = [a.scene] if a.scene else list(all_briefs())
    for s in scenes:
        b = json.loads((scene_dir(s) / "brief.json").read_text(encoding="utf-8")) if (scene_dir(s) / "brief.json").exists() else {}
        plate = ROOT / "out" / "plates" / s
        st = {"brief": bool(b), "keyart": bool(candidates(s)), "hero": bool(b.get("hero")), "plate": (plate / "plate.png").exists(),
              "regions": (plate / "regions.json").exists(), "scene": (scene_dir(s) / "scene.json").exists(),
              "clean": (ROOT / "assets" / "keyart" / s / "clean.png").exists(),
              "fire": (plate / "fire" / "fire.json").exists(),
              "preview": any((ROOT / "out" / s).glob("preview*.mp4")) if (ROOT / "out" / s).exists() else False}
        print(f"  {s:22s} " + "  ".join(f"{k}:{'y' if v else '-'}" for k, v in st.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("scene")
    p.add_argument("--aesthetic", required=True)
    p.add_argument("--auto", action="store_true")
    p.add_argument("--hint")
    p.add_argument("--weather", help="the weather Truman chose or named (user 2026-10-25: rain is not the default; ask him)")
    p.add_argument("--weather-why", help="why this weather (his answer, or the words in his line); goes in the brief")
    p.add_argument("--n", type=int, default=2)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("prompt")
    p.add_argument("scene")
    p.add_argument("--n", type=int, default=2)
    p = sub.add_parser("keyart")
    p.add_argument("scene")
    p.add_argument("--n", type=int, default=2)
    p.add_argument("--model")
    p = sub.add_parser("pick")
    p.add_argument("scene")
    p.add_argument("png", nargs="?")
    p.add_argument("--auto", action="store_true")
    p = sub.add_parser("prep")
    p.add_argument("scene")
    p.add_argument("--masks-only", action="store_true")
    p = sub.add_parser("analyze")
    p.add_argument("scene")
    p.add_argument("--reuse", action="store_true", help="reuse the cached model answer, redo segmentation")
    p = sub.add_parser("clean")
    p.add_argument("scene")
    p.add_argument("--force", action="store_true", help="redo every item from the original key art")
    p = sub.add_parser("life")
    p.add_argument("scene")
    p.add_argument("--no-fire", action="store_true")
    p.add_argument("--no-steam", action="store_true")
    p.add_argument("--force", action="store_true", help="re-run the steam simulation even if it is up to date")
    p = sub.add_parser("preview")
    p.add_argument("scene")
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--start", help="start time in seconds (default: the scene's showcase window)")
    p.add_argument("--out")
    p.add_argument("--params")
    p = sub.add_parser("sample")
    p.add_argument("scene")
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--start", help="start time in seconds (default: the busiest window in the first 15 min)")
    p.add_argument("--out")
    p = sub.add_parser("catalog")
    p.add_argument("--check")
    p = sub.add_parser("status")
    p.add_argument("scene", nargs="?")
    p = sub.add_parser("spend")
    p.add_argument("--since")
    a = ap.parse_args()
    if a.cmd == "spend":
        from azure_ai import spend
        tot, per = spend(a.since)
        for k, (n, u) in sorted(per.items()):
            print(f"  {k:40s} {n:4d} calls  ${u:7.3f}")
        print(f"estimated total: ${tot:.2f}")
        return
    {"plan": cmd_plan, "prompt": cmd_prompt, "keyart": cmd_keyart, "pick": cmd_pick, "prep": cmd_prep, "analyze": cmd_analyze,
     "clean": cmd_clean, "life": cmd_life,
     "preview": cmd_preview, "sample": cmd_sample, "catalog": lambda a: catalog(a.check), "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
