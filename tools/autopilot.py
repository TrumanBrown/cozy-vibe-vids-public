"""Autopilot: one idea in, a polished 5 minute sample out, with self-review gates before Truman sees anything.

User 2026-10-21: by the next day he wanted to ask in one simple line ("generate me a new youtube video sample for
<idea>", with a Minecraft style, 8-bit pixel art or a real-life farm scene as examples) and get back a finished,
polished sample to OK, built on everything learned so far and iterated on without him, then render the 10 h video
from it. This chains the existing stages (tools/new_video.py and friends), applies his settled defaults
(config/defaults.json), and stops only where the agent must fix something or he must look.

  .venv\\Scripts\\python tools\\autopilot.py look "<idea>" [--apply]
      which look (config/aesthetics.json) fits the idea; --apply adds a new look when none does
  .venv\\Scripts\\python tools\\autopilot.py run "<idea>" [--scene <name>] [--look <id>] [--pick <png>] [--budget 6]
      the whole path to the sample; re-run the same command (or `run --scene <name>`) to resume
  .venv\\Scripts\\python tools\\autopilot.py run --scene <name> --from <stage>     redo from a stage after a fix
  .venv\\Scripts\\python tools\\autopilot.py status <scene>

Stages (state in out/<scene>/auto/state.json, a log in out/<scene>/auto/progress.md):
  look      the idea's look: an existing one, or a new entry drafted by the chat model (validated)
  plan      the brief (new_video.py plan --auto): setting, pet, props, signature detail, place name, opening line; the
            weather is his: named in his line, or asked (exit 4, a question; resume with --weather "<his answer>")
  keyart    candidates (Azure gpt-image, config/defaults.json keyart_candidates)
  pick      the hero, picked by the vision model (or --pick <png>); the sheet goes in the report so he can redirect
  prep      the 4K plate and depth
  analyze   regions, masks, scene.json draft (vision model + SAM 2)
  clean     painted steam, flames and drips removed from the key art (Azure image edit)
  features  what the plate offers beyond the draft (tools/plate_features.py): birds on wires, a moth at a lamp, chimney
            smoke, petals, a drink in an empty cup, more critter paths, the ant when it is the signature detail
  life      critter sprites, fire clips, the steam simulation for every vessel (local GPU)
  setup     his defaults: the 20 minute loop period, event rates at least config/defaults.json, the opening line, the
            music settings, a sound bed that matches the weather
  music     the look's music (tools/music_auto.py when the look has none yet); else ambience only
  checks    tools/outdoor_check.py --repair (the vision model on every tile of the weather; what is inside gets cut),
            then tools/review.py without a render (lint against the lessons, leaks, dry pockets, timeline)    GATE
  render    the 5 minute sample with the opening line and the music (node src/cli.mjs render)
  review    tools/review.py on the render (render QA, static check, event sheets)                       GATE
  critic    tools/critic.py: the vision model's eye checks against approved references                  GATE
  report    out/<scene>/auto/sample.md and the sample in out/samples/<scene>/
A GATE that fails stops with exit code 2 and the list of what to fix: the agent fixes the cause (and its whole
class, lessons L56), then resumes with --from <stage> (after a scene.json change: --from render). Spend is
guarded per run (config/defaults.json budget_usd_per_sample; --budget overrides) and per day (config/azure.json
daily_cap_usd, in tools/azure_ai.py): either stops the run with exit code 3, for Truman to decide.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from cozy.paths import ROOT, PY, config, load_scene, rel, save_scene
from cozy.ledger import row as ledger_row
AES_PATH = ROOT / "config" / "aesthetics.json"
DEFAULTS = config("defaults")
STAGES = ["look", "plan", "keyart", "pick", "prep", "analyze", "clean", "features", "life", "setup", "music", "checks", "render",
          "review", "critic", "report"]
GATES = {"checks", "review", "critic"}
PAID = {"look", "plan", "keyart", "pick", "analyze", "clean", "features", "music", "critic"}


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def slug(s, n=4):
    w = re.findall(r"[a-z0-9]+", s.lower())
    w = [x for x in w if x not in {"a", "an", "the", "of", "for", "with", "in", "on", "style", "scene", "video", "sample",
                                   "youtube", "new", "me", "generate", "make"}]
    return "-".join(w[:n]) or "scene"


# ---------------------------------------------------------------- the look

def catalog():
    return config("aesthetics")


def allowed():
    from cozy.audio.ambience import BEDS
    beds = list(BEDS)
    cat = catalog()["aesthetics"]
    motions, styles = set(), set()
    for v in cat.values():
        motions.update(v["motions"])
        styles.add(v["style"])
    fonts = config("fonts")["fonts"]
    return {"audio_bed": beds, "motions": sorted(motions), "style": sorted(styles),
            "fonts": {k: v.get("feel", v.get("title")) for k, v in fonts.items()}}


def resolve(idea, weather=None):
    """Ask the chat model which look fits the idea, or draft a new one. Returns its JSON answer, validated.
    `weather` is Truman's choice when it is known (his --weather answer, or named in his line). The scene name and the
    setting hint follow it, and while it isn't chosen they leave the weather out: the jungle temple was named
    jungle-temple-rain with a "rainy dawn" hint before he picked a clear night (L161)."""
    from azure_ai import chat
    cat = catalog()["aesthetics"]
    al = allowed()
    summary = [{"id": k, "title": v["title"], "style": v["style"], "franchise": v.get("franchise"), "settings": v["settings"][:3],
                "weather": v.get("weather"), "audio_bed": v.get("audio_bed")} for k, v in cat.items()]
    example = cat["ramen-alley"]
    made = []
    for p in sorted((ROOT / "scenes").glob("*/brief.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        made.append({"look": b.get("aesthetic"), "setting": b.get("setting"), "time": b.get("time"), "weather": b.get("weather"),
                     "pet": b.get("pet"), "status": b.get("status", "sample")})
    wx_rule = (f"The weather is decided: {weather}. The setting_hint and the scene name must fit it, with no rain, storm, snow "
               "or fog in either unless this weather has it (e.g. jungle-temple-night for a clear night).\n\n" if weather else
               "The weather is the owner's call and isn't chosen yet: leave the weather out of the setting_hint and the "
               "scene name (jungle-temple, not jungle-temple-rain).\n\n")
    prompt = (
        "A YouTube channel makes 10-hour cozy ambience videos (study, relax, sleep): one painted key-art image per video, "
        "animated in code (rain, snow, steam, fire, neon, birds, small creatures, a sleeping pet that only breathes). The "
        "owner asked for a new video with this idea:\n\n"
        f"IDEA: {idea}\n\nThe channel's looks (an aesthetic plus a family of settings):\n{json.dumps(summary, ensure_ascii=False)}\n\n"
        f"Videos already made (published or sampled):\n{json.dumps(made, ensure_ascii=False)}\n\n"
        "Never propose a setting one of these already has: the setting_hint must differ clearly in place and in at least one "
        "of time, weather or pet (YouTube treats look-alike videos as reused content).\n\n"
        f"{wx_rule}"
        "Decide which look fits. Prefer an existing look when its style, its weather and its kind of place all fit the idea "
        "(the setting can be new: the brief step writes a fresh setting within the look; its sound bed must suit the idea: "
        "a snowed-in cabin look does not fit a rainy farm porch). Make a NEW look when no existing one fits all three (for "
        "example a photoreal farm when the only farm look is pixel art). Answer as JSON: {\"look\": \"<existing id, or a new short "
        "kebab-case id>\", \"new\": true|false, \"why\": \"one sentence\", \"setting_hint\": \"the concrete setting the idea asks "
        "for, in a few words\", \"scene\": \"<a short kebab-case scene name, 1-3 words, e.g. farm-porch-rain when it rains>\", \"entry\": "
        "{...only when new...}}.\n\n"
        f"A new entry has exactly these keys, like this example: {json.dumps(example, ensure_ascii=False)}\n"
        f"Rules for a new entry: style one of {al['style']}; motions only from {al['motions']}; audio_bed one of "
        f"{al['audio_bed']}; title_font and thumb.fonts only ids from {json.dumps(al['fonts'], ensure_ascii=False)} "
        "('pixel' only for pixel or voxel styles); ai_label true for photoreal or cinematic-realistic styles; no people in any "
        "setting; every setting has weather to animate and a sleeping pet; props are things the code animates (a steaming "
        "mug or bowl, a fire, candles, a hanging lantern, a wind chime, string lights, a neon sign); tier \"new\"; evidence "
        "\"autopilot from the idea\"; music: the music style in a few words with its main genre named first, one of lofi, "
        "ambient, piano, jazz, synthwave, acoustic, orchestral, chiptune (chiptune only for pixel or voxel styles; lofi and "
        "ambient have the most free music, acoustic and orchestral very little, so prefer e.g. \"lofi with soft acoustic "
        "guitar\" over \"acoustic folk\"); leave music_dirs out.")
    text, usage = chat([{"role": "user", "content": prompt}], purpose="autopilot:look", json_mode=True, effort="medium")
    res = json.loads(text)
    res["usd_est"] = usage.get("usd_est", 0.0)
    if not res.get("new"):
        if res.get("look") not in cat:
            raise SystemExit(f"look: the model chose {res.get('look')!r}, which isn't in config/aesthetics.json")
        return res
    e = res.get("entry") or {}
    need = ["title", "style", "style_prompt", "settings", "times", "weather", "pets", "props", "motions", "audio_bed",
            "playlist", "music", "title_font", "thumb"]
    miss = [k for k in need if not e.get(k)]
    if miss:
        raise SystemExit(f"look: the new entry lacks {miss}")
    e["motions"] = [m for m in e["motions"] if m in al["motions"]] or ["rain", "pet"]
    if e["audio_bed"] not in al["audio_bed"]:
        e["audio_bed"] = "country_rain"
    if e["style"] not in al["style"]:
        raise SystemExit(f"look: unknown style {e['style']!r}")
    if e["title_font"] not in al["fonts"]:
        e["title_font"] = "patrick-hand"
    e["thumb"]["fonts"] = [f for f in e["thumb"].get("fonts", []) if f in al["fonts"] and (f != "pixel" or e["style"] in ("pixel", "voxel"))] or [e["title_font"]]
    e.setdefault("franchise", None)
    e["ai_label"] = e["style"] in ("photoreal", "cinematic-realistic") or bool(e.get("ai_label"))
    e["tier"], e["evidence"] = "new", f"autopilot from the idea \"{idea}\" ({dt.date.today().isoformat()})"
    e.pop("music_dirs", None)
    res["entry"] = {k: e[k] for k in ["title", "tier", "evidence", "style", "franchise", "ai_label", "style_prompt", "settings",
                                      "times", "weather", "pets", "props", "motions", "audio_bed", "playlist", "music",
                                      "title_font", "thumb"]}
    # the model's id becomes a key in aesthetics.json and a folder (music/<look>): kebab-case only, like the scene name
    look = re.sub(r"[^a-z0-9]+", "-", str(res.get("look") or "").lower()).strip("-")
    if not 3 <= len(look) <= 40:
        raise SystemExit(f"look: the model's id {res.get('look')!r} isn't a short kebab-case id")
    res["look"], k = look, 2
    while res["look"] in cat:
        res["look"], k = f"{look}-{k}", k + 1
    return res


def add_look(look, entry):
    """Append a look to config/aesthetics.json without reformatting the rest of the file."""
    t = AES_PATH.read_text(encoding="utf-8")
    before = json.loads(t)["aesthetics"]
    if look in before:
        raise SystemExit(f"look {look!r} is already in {AES_PATH.name}")
    end = t.rstrip().rfind("}", 0, t.rstrip().rfind("}"))           # the closing brace of "aesthetics"
    body = json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n    ")
    t2 = t[:end].rstrip() + f",\n    {json.dumps(look, ensure_ascii=False)}: {body}\n  " + t[end:]
    after = json.loads(t2)["aesthetics"]
    if len(after) != len(before) + 1 or after.get(look) != entry:
        raise SystemExit(f"adding look {look!r} would change {AES_PATH.name} beyond one new entry")
    AES_PATH.write_text(t2, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- state

class Run:
    def __init__(self, scene):
        self.scene = scene
        self.dir = ROOT / "out" / scene / "auto"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "state.json"
        self.s = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "scene": scene, "started": now(), "stages": {}, "sample_version": 0}

    def save(self):
        self.path.write_text(json.dumps(self.s, indent=1, ensure_ascii=False), encoding="utf-8")

    def log(self, msg):
        line = f"- {now()} {msg}"
        print(line)
        with open(self.dir / "progress.md", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def mark(self, stage, status, note=""):
        self.s["stages"][stage] = {"status": status, "at": now(), "note": note}
        self.save()
        self.log(f"{stage}: {status}{' - ' + note if note else ''}".replace(" - ", ": ", 1))

    def done(self, stage):
        return (self.s["stages"].get(stage) or {}).get("status") in ("done", "skip")

    def spent(self):
        return spend_breakdown(self)[0]


def spend_breakdown(run):
    """This run's Azure spend from out/azure_usage.jsonl, by what it paid for: the calls since the run started that are
    tagged with the scene (every tool puts it in the call's purpose), plus the two it makes untagged (the look resolver,
    the music screening). Other work logged meanwhile (tests, another scene) doesn't count; the first farm report's
    "spend this run" had the critic's self-tests in it (2026-10-21). Returns (total, {group: usd})."""
    import azure_ai
    groups = {}
    for r in azure_ai.usage_records():
        p = r.get("purpose") or ""
        if r["t"] < run.s["started"] or not (run.scene in p.split(":") or p in ("autopilot:look", "music screen")):
            continue
        img = str(r.get("deployment", "")).startswith("gpt-image")
        k = ("clean-up edits" if r.get("kind") == "image_edit" else "key art and sprites" if img else
             "music screening (once per look)" if p == "music screen" else
             "review checks" if p.split(":")[0] in ("critic", "static", "review", "outdoor_check") else "brief, analysis, placement")
        groups[k] = groups.get(k, 0.0) + float(r.get("usd_est") or 0.0)
    return sum(groups.values()), groups


class DailyCap(Exception):
    """A tool stopped at azure_ai's daily cap (config/azure.json daily_cap_usd): nothing was sent, and no stage or gate
    found anything. It used to read as a gate with no reason ("NEEDS FIX at critic:", then --from render) or, at the
    music stage, as music skipped; the run now stops as at its own budget, for Truman to decide (exit 3)."""


def sh(args, run, label, tail=12):
    run.log(f"{label}: {' '.join(str(a) for a in args[1:])[:300]}")
    # A child Python writing to a pipe uses the Windows code page unless told otherwise; a curly apostrophe then decoded as
    # U+FFFD here, and echoing that to a cp1252 console killed the run (pixel greenhouse, 2026-10-21). UTF-8 mode for the
    # whole subtree, so every child prints and decodes UTF-8 alike (PYTHONIOENCODING alone broke review.py, whose own
    # child then printed UTF-8 that it read as cp1252)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                       env=env)
    out = (r.stdout + r.stderr).strip().splitlines()
    with open(run.dir / f"{label}.log", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    for line in out[-tail:]:
        print("    " + line)
    cap = next((l.strip() for l in out if l.strip().startswith("daily cap:")), None) if r.returncode else None
    if cap:
        raise DailyCap(cap)
    return r.returncode, out


def nv(*a):
    return [PY, ROOT / "tools" / "new_video.py", *a]


# ---------------------------------------------------------------- stages

def st_look(run, a):
    if run.s.get("look"):
        return "skip", run.s["look"]
    if a.look:
        if a.look not in catalog()["aesthetics"]:
            raise SystemExit(f"unknown look {a.look}")
        run.s.update({"look": a.look, "new_look": False})
        return "done", a.look
    res = resolve(run.s["idea"], getattr(a, "weather", None) or run.s.get("weather") or named_weather(run.s["idea"]))
    if res.get("new"):
        add_look(res["look"], res["entry"])
    run.s.update({"look": res["look"], "new_look": bool(res.get("new")), "look_why": res.get("why"),
                  "setting_hint": res.get("setting_hint")})
    return "done", f"{res['look']} ({'new look' if res.get('new') else 'existing'}): {res.get('why')}"


def st_plan(run, a):
    if (ROOT / "scenes" / run.scene / "brief.json").exists():
        return "skip", "brief exists"
    # the weather is Truman's call (user 2026-10-25, the Burdock Shelter: not every video needs rain, so check with him):
    # from his line when it names one, else from his answer to the question
    wx = a.weather or run.s.get("weather")
    why = run.s.get("weather_why") or ("his answer before the key art" if a.weather else None)
    if not wx:
        named = named_weather(run.s["idea"])
        if named:
            wx, why = named, f"named in his line: \"{run.s['idea']}\""
    if not wx:
        opts = catalog()["aesthetics"].get(run.s.get("look"), {}).get("weather") or []
        return "ask", ("which weather? His line names none, and rain is not the default (2026-10-25). The look's usual: "
                       f"{', '.join(opts) or 'none listed'}; clear or still weather works too. Ask him (ask_user), then "
                       f"resume: autopilot.py run --scene {run.scene} --weather \"<his answer>\"")
    run.s.update({"weather": wx, "weather_why": why})
    hint = f"{run.s['idea']}. {run.s.get('setting_hint') or ''}".strip()
    rc, out = sh(nv("plan", run.scene, "--aesthetic", run.s["look"], "--auto", "--hint", hint, "--n", str(a.n),
                    "--weather", wx, "--weather-why", why), run, "plan")
    return ("done", f"brief written (weather: {wx}, {why})") if rc == 0 else ("fail", out[-1] if out else "plan failed")


WEATHER_WORDS = re.compile(
    r"\b(rain\w*|drizzl\w*|downpour|storm\w*|thunder\w*|snow\w*|blizzard|sleet|fog\w*|mist\w*|sunny|sunshine|sunlit|"
    r"starry|starlight|moonlit|windy|overcast|cloudy|clear (?:night|sky|skies|day|weather)|no rain|calm night)\b", re.I)


def named_weather(idea):
    """The weather words in his line ("a rainy ramen alley" -> "rainy"), or None."""
    hits = [m.group(0).lower() for m in WEATHER_WORDS.finditer(idea or "")]
    return ", ".join(dict.fromkeys(hits)) or None


def candidates(scene):
    return [p for p in sorted((ROOT / "assets" / "keyart" / scene).glob("*.png")) if p.name != "clean.png" and not p.name.startswith("critter")]


def st_keyart(run, a):
    if candidates(run.scene):
        return "skip", f"{len(candidates(run.scene))} candidates"
    rc, out = sh(nv("keyart", run.scene, "--n", str(a.n)), run, "keyart")
    return ("done", f"{len(candidates(run.scene))} candidates") if rc == 0 else ("fail", out[-1] if out else "keyart failed")


def brief(run):
    return json.loads((ROOT / "scenes" / run.scene / "brief.json").read_text(encoding="utf-8"))


def st_pick(run, a):
    if brief(run).get("hero"):
        return "skip", brief(run)["hero"]
    args = nv("pick", run.scene, a.pick) if a.pick else nv("pick", run.scene, "--auto")
    rc, out = sh(args, run, "pick")
    return ("done", brief(run).get("hero", "")) if rc == 0 else ("fail", out[-1] if out else "pick failed")


def st_prep(run, a):
    if (ROOT / "out" / "plates" / run.scene / "plate.png").exists():
        return "skip", "plate exists"
    rc, out = sh(nv("prep", run.scene), run, "prep")
    return ("done", "plate built") if rc == 0 else ("fail", out[-1] if out else "prep failed")


def st_analyze(run, a):
    if (ROOT / "scenes" / run.scene / "scene.json").exists():
        return "skip", "scene.json exists"
    rc, out = sh(nv("analyze", run.scene), run, "analyze")
    return ("done", "regions, masks, scene.json") if rc == 0 else ("fail", out[-1] if out else "analyze failed")


def st_clean(run, a):
    if not (ROOT / "assets" / "keyart" / f"{run.scene}.clean.json").exists():
        return "skip", "nothing painted to remove"
    if (ROOT / "assets" / "keyart" / run.scene / "clean.png").exists():
        return "skip", "already clean"
    rc, out = sh(nv("clean", run.scene), run, "clean")
    return ("done", "painted transients removed") if rc == 0 else ("fail", out[-1] if out else "clean failed")


def st_features(run, a):
    """What the plate offers beyond the draft (tools/plate_features.py): birds on wires, a moth at a lamp, chimney
    smoke, petals, a drink in an empty cup, more critter paths, the ant when it is the signature detail."""
    fj = ROOT / "out" / "plates" / run.scene / "features.json"
    if fj.exists() and json.loads(fj.read_text(encoding="utf-8")).get("applied") is not None:
        return "skip", "features placed"
    rc, out = sh([PY, ROOT / "tools" / "plate_features.py", run.scene], run, "features", tail=24)
    summary = next((l.strip() for l in reversed(out) if l.strip().startswith("features: kept")), "placed")
    return ("done", summary) if rc == 0 else ("fail", out[-1] if out else "features failed")


def st_life(run, a):
    rc, out = sh(nv("life", run.scene), run, "life")
    return ("done", "critters, fire clips, steam") if rc == 0 else ("fail", out[-1] if out else "life failed")


def ledger(run):
    """Every AI-made file the sample uses gets its row in docs/asset-ledger.csv before the render (AGENTS.md
    provenance): the key-art candidates, the clean edits, the critter sprites, the fire clips. Rows are keyed by path
    and rewritten in place, in the form the ramen alley's rows were written by hand."""
    import csv
    import io
    lp = ROOT / "docs" / "asset-ledger.csv"
    text = lp.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    head, body = rows[0], rows[1:]
    sc, kd = run.scene, ROOT / "assets" / "keyart" / run.scene
    today = dt.date.today().isoformat()
    az = ("https://learn.microsoft.com/azure/foundry/openai/how-to/dall-e", "Azure OpenAI Service terms (customer owns outputs)",
          "https://learn.microsoft.com/legal/cognitive-services/openai/data-privacy", "none")

    def side(p):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    want = []
    heroes = sorted(kd.glob("hero_*.png"))
    if heroes:
        dep = side(heroes[0].with_suffix(".json")).get("deployment", "gpt-image")
        want.append([f"assets/keyart/{sc}/hero_*.png", f"AI key art (Azure OpenAI {dep})", f"{sc} key-art candidates ({run.s['look']})",
                     "Generated via tools/new_video.py keyart (tools/keyart.py) in rg-cozyvibevids-img", *az, "", today,
                     f"Prompt built from scenes/{sc}/brief.json + config/aesthetics.json; prompt + model per image in the .json sidecar; "
                     f"autopilot picked {brief(run).get('hero', '')}"])
    cj = side(kd / "clean.json")
    if (kd / "clean.png").exists():
        names = ", ".join(i.get("name", "") for i in (cj.get("items") or [])) if isinstance(cj.get("items"), list) else ""
        want.append([f"assets/keyart/{sc}/clean.png", f"AI image edit of key art (Azure OpenAI {cj.get('deployment', 'gpt-image')}, images/edits with a mask)",
                     f"painted transients removed from the {sc} key art", "Generated via tools/plate_clean.py in rg-cozyvibevids-img", *az,
                     "only the masked areas are repainted", today, f"items and usage in assets/keyart/{sc}.clean.json and clean.json {names}".strip()])
    for p in sorted(kd.glob("critter_*.png")):
        s = side(p.with_suffix(".json"))
        want.append([f"assets/keyart/{sc}/{p.name}", f"AI sprite (Azure OpenAI {s.get('deployment', 'gpt-image')}, transparent background)",
                     f"{s.get('creature', 'critter')} sprite for the crawling critter ({sc})", "Generated via tools/critter.py in rg-cozyvibevids-img",
                     *az, "", s.get("date", today), f"prompt (style from config/aesthetics.json) and measurements in {p.with_suffix('.json').name}"])
    if (ROOT / "out" / "plates" / sc / "fire").exists():
        want.append([f"out/plates/{sc}/fire/* (derived, gitignored)", "AI video clips (Wan 2.2 TI2V-5B, local GPU)",
                     f"fire clips: the {sc} key art's own painted fire animated", "Wan-AI/Wan2.2-TI2V-5B-Diffusers run locally by tools/fire_clips.py",
                     "https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers", "Apache-2.0", "https://www.apache.org/licenses/LICENSE-2.0", "none", "",
                     today, "generated from a crop of the original key art"])
    by = {r[0]: i for i, r in enumerate(body) if r}
    for r in want:
        r = (r + [""] * len(head))[:len(head)]
        if r[0] in by:
            body[by[r[0]]] = r
        else:
            body.append(r)
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows([head] + [ledger_row(r) for r in body])
    lp.write_text(out.getvalue(), encoding="utf-8", newline="\n")
    return len(want)


def st_setup(run, a):
    """His settled defaults onto the scene draft: the loop period, rates at least the baseline, the opening line."""
    spec = load_scene(run.scene)
    ev = spec.setdefault("events", {})
    notes = []
    loop = ev.setdefault("loop", {})
    if not loop.get("period"):
        loop["period"] = DEFAULTS["loop"]["period"]
        notes.append(f"loop period {loop['period']} s")
    for kind, base in DEFAULTS["events"].items():
        cur = ev.get(kind)
        if not isinstance(cur, dict):
            continue                                   # only kinds the scene already has: the plate decides what fits
        for k, v in base.items():
            if k in ("perHour", "sigh") and cur.get(k, 0) < v:    # rates (a pet's sighs are per hour too)
                cur[k] = v
                notes.append(f"{kind} {v}/h")
            elif k == "first" and cur.get(k, 1e9) > v:
                cur[k] = v
            elif k not in cur:
                cur[k] = v
                if k == "intro":
                    notes.append(f"{kind} busy opening")
    if isinstance(ev.get("critter"), list) and ev["critter"]:
        tot = sum(c.get("perHour", 0) for c in ev["critter"])
        if tot < DEFAULTS["critter_total_per_hour"]:
            f = DEFAULTS["critter_total_per_hour"] / max(tot, 1)
            for c in ev["critter"]:
                c["perHour"] = max(1, round(c.get("perHour", 1) * f))
            notes.append(f"critters {DEFAULTS['critter_total_per_hour']}/h")
    b = brief(run)
    if not spec.get("intro") and b.get("intro_lines"):
        lines = b["intro_lines"][:2]
        if len(lines) == 2 and not re.search(r"[A-Za-z]", lines[0]):
            lines = [{"text": lines[0], "scale": 0.62}, lines[1]]
        # one long line reads as a caption strip; in the middle of the screen it breaks at its comma into two
        # centered lines (user 2026-10-21: centered, not at the bottom), each a sentence of
        # its own: the comma dropped and the second line left lowercase read "Welcome to Seedling House / come listen
        # to the morning rain", which he found badly punctuated (2026-10-21)
        if len(lines) == 1 and isinstance(lines[0], str) and len(lines[0]) > 32:
            t = lines[0]
            for sep in (". ", ", "):
                at = [i for i in range(len(t)) if t.startswith(sep, i)]
                if at:
                    cut = min(at, key=lambda i: abs(i - len(t) / 2))
                    lines = [t[:cut + (sep == ". ")], t[cut + 2:]]
                    break
        if lines and all(isinstance(x, str) for x in lines) and len(lines) == 2:
            import intro_title
            lines = intro_title.sentences(lines)
        # a look may style its opening line (config/aesthetics.json `intro`: the comic look's caption box, 2026-10-25)
        look_intro = {k: v for k, v in (catalog()["aesthetics"].get(run.s.get("look") or b.get("aesthetic"), {}).get("intro") or {}).items()
                      if k != "lines"}
        spec["intro"] = {"lines": lines, "pos": [0.5, 0.5], **look_intro}
        notes.append("opening line" + (" (the look's " + ", ".join(look_intro) + ")" if look_intro else ""))
    mus = spec.setdefault("audio", {}).setdefault("music", {})
    for k, v in DEFAULTS["music"].items():
        if k not in mus:
            mus[k] = v
            notes.append(f"music {k}")
    # the awake cast blinks (user 2026-10-25): the layer right after the plate, once tools/cast_eyes.py has run
    if (ROOT / "out" / "plates" / spec.get("plate", run.scene) / "eyes.json").exists() and not any(L.get("type") == "blink" for L in spec.get("layers", [])):
        spec.setdefault("layers", []).insert(0, {"type": "blink"})
        notes.append("blinks")
    # the thunder a little louder (L27) wherever there is lightning
    if isinstance(ev.get("lightning"), dict) and "thunder" not in spec["audio"]:
        spec["audio"]["thunder"] = dict(DEFAULTS["audio"]["thunder"])
        notes.append("thunder level")
    # the sound bed must match the weather the brief and the picture have (a look's bed is for its usual weather)
    wx = f"{b.get('weather', '')} {spec.get('title', '')}".lower()
    bed = spec["audio"].get("bed") or ""
    wet = any(w in wx for w in ("rain", "storm", "drizzle", "shower"))
    beds = allowed()["audio_bed"]
    if wet and bed in ("cabin_snow", "underwater", "quiet_night", ""):
        ana = json.loads((ROOT / "out" / "plates" / run.scene / "analysis.json").read_text(encoding="utf-8"))
        place = f"{b.get('setting', '')}".lower()
        new = ("porch_rain" if "porch" in place or "veranda" in place else "country_rain") if not ana.get("indoor", True) or "porch" in place \
            else "cabin_rain"
        if new in beds:
            spec["audio"]["bed"] = new
            notes.append(f"sound bed {bed or 'none'} -> {new} (the brief's weather is {b.get('weather')})")
    elif "snow" in wx and not wet and bed and bed != "cabin_snow" and "cabin_snow" in beds:
        spec["audio"]["bed"] = "cabin_snow"
        notes.append(f"sound bed {bed} -> cabin_snow (snow)")
    save_scene(run.scene, spec)
    if spec.get("intro"):
        rc, out = sh([PY, ROOT / "tools" / "intro_title.py", run.scene], run, "intro")
        if rc != 0:
            return "fail", "intro_title: " + (out[-1] if out else "failed")
    return "done", ", ".join(notes) or "already at the defaults"


def st_checks(run, a):
    # weather only over the outdoors, judged by the vision model tile by tile; what it finds inside under the weather
    # is traced and cut (user 2026-10-21: rain kept reaching the plants by the lamp, to be fixed for good); review.py
    # then finds it cached
    rc, out = sh([PY, ROOT / "tools" / "outdoor_check.py", run.scene, "--repair", "--rounds", "3"], run, "outdoor_check", tail=16)
    if rc == 2 or crashed(out):
        return "fail", "outdoor_check: " + (crashed(out) or (out[-1] if out else "could not run"))
    if rc != 0:
        return "gate", "outdoor_check: " + "; ".join(l.strip()[2:] for l in out if l.strip().startswith("- "))[:600]
    rc, out = sh([PY, ROOT / "tools" / "review.py", run.scene], run, "checks", tail=20)
    if rc != 0 and crashed(out):
        return "fail", "review.py: " + crashed(out)
    return ("done", "outdoor check, review lint, leaks, dry pockets, wet frames, timeline: PASS") if rc == 0 else ("gate", "; ".join(l.strip() for l in out if l.strip().startswith("- "))[:600])


def crashed(out):
    """The error line when a tool died with a traceback (a reset connection, a bug), else "": that is a failure to fix
    and resume, not a gate's finding (the tea house's outdoor check crashed on a network error and autopilot reported
    an empty gate, 2026-10-22)."""
    if not any(l.startswith("Traceback (most recent call last)") for l in out):
        return ""
    return next((l.strip() for l in reversed(out) if l.strip() and not l.startswith(" ")), "a traceback")


def st_music(run, a):
    import music as M
    dirs, mc = M.scene_music(run.scene)
    if mc:
        # Minecraft looks: only Mojang's allowlist, checked against the live Creator-Safe Playlist before each video
        rc, out = sh([PY, ROOT / "tools" / "mc_music.py", "check"], run, "mc_music")
        if rc != 0:
            return "fail", ("mc_music check: " + (out[-1] if out else "failed") + " (AGENTS.md: only the checked allowlist; "
                            "ask Truman before using anything else)")
    n = len(M.scan(dirs)) if dirs else 0
    if n >= 15:
        run.s["music"] = True
        return "done", f"{n} tracks in {', '.join(rel(d) for d in dirs)}"
    tool = ROOT / "tools" / "music_auto.py"
    if not tool.exists():
        run.s["music"] = False
        return "skip", "no music for this look yet: the sample is ambience only; music comes as clips (ambience-audio skill)"
    left = max(0.0, run.s["budget"] - run.spent())
    rc, out = sh([PY, tool, run.s["look"], "--scene", run.scene, "--budget", f"{min(2.5, left):.2f}"], run, "music", tail=16)
    run.s["music"] = rc == 0
    return ("done", "playlist curated for the look") if rc == 0 else ("skip", "music_auto: " + (out[-1] if out else "failed") + "; ambience only")


def st_render(run, a):
    run.s["sample_version"] = int(run.s.get("sample_version", 0)) + 1
    run.save()       # a render stopped midway must not hand its name (and its manifest of other settings) to the next one
    tag = f"sample_v{run.s['sample_version']}"
    secs = DEFAULTS["sample"]["seconds"]
    run.log(f"ledger: {ledger(run)} rows for this scene's AI-made files in docs/asset-ledger.csv")
    args = ["node", ROOT / "src" / "cli.mjs", "render", f"scenes/{run.scene}", "--from", "0", "--length", f"{secs}s", "--name", tag,
            "--params", f"intro={DEFAULTS['sample']['intro_at']}", "--music", "auto" if run.s.get("music") else "off"]
    rc, out = sh(args, run, "render", tail=6)
    run.s["sample"] = str(ROOT / "out" / run.scene / "render" / tag)
    return ("done", tag) if rc == 0 else ("fail", out[-1] if out else "render failed")


def st_review(run, a):
    rc, out = sh([PY, ROOT / "tools" / "review.py", run.scene, "--render", run.s["sample"]], run, "review", tail=24)
    if rc == 0:
        return "done", "render QA, static check, event sheets: PASS"
    if crashed(out):
        return "fail", "review.py: " + crashed(out)
    fails = [l.strip()[2:] for l in out if l.strip().startswith("- ")]
    # what the static check found still that is foliage or cloth the analysis missed gets a traced sway region
    # (tools/hand_region.py, the noren and cherry-tree fix) and the sample renders again; at most twice a run
    st = pathlib.Path(run.s["sample"]) / "review" / "first40s_static.json"
    if fails and all("motion_review --static" in f for f in fails) and st.exists() and run.s.get("redos", 0) < 2:
        rc2, out2 = sh([PY, ROOT / "tools" / "hand_region.py", run.scene, "--from-static", st], run, "hand_region", tail=8)
        added = next((int(m.group(1)) for l in out2 for m in [re.search(r"hand_region: (\d+) added", l)] if m), 0)
        if added:
            run.s["redos"] = run.s.get("redos", 0) + 1
            return "redo", f"render (the static check found {added} still thing(s) of cloth or foliage: added as sway regions)"
    return "gate", "; ".join(fails)[:600]


def look_refs(run):
    """The approved critic references of the newest earlier scene in the same look (assets/reference/approved/<scene>/,
    written by `critic.py --approve` on his OK), or None: the critic then falls back to the ramen alley's. Without this
    every look was judged against the ramen alley's painted night street, even after a video of its own look was
    approved (the first Minecraft run through autopilot, 2026-10-22)."""
    base = ROOT / "assets" / "reference" / "approved"
    best = None
    for d in (base.iterdir() if base.exists() else []):
        bp = ROOT / "scenes" / d.name / "brief.json"
        if not d.is_dir() or d.name == run.scene or not bp.exists():
            continue
        if json.loads(bp.read_text(encoding="utf-8")).get("aesthetic") != run.s.get("look"):
            continue
        idx = d / "index.json"
        t = (idx if idx.exists() else d).stat().st_mtime
        if best is None or t > best[0]:
            best = (t, d)
    return best[1] if best else None


def st_critic(run, a):
    refs = look_refs(run)
    args = [PY, ROOT / "tools" / "critic.py", run.scene, "--render", run.s["sample"]] + (["--refs", refs] if refs else [])
    if refs:
        run.log(f"critic: approved references of the look from {refs.relative_to(ROOT)}")
    rc, out = sh(args, run, "critic", tail=30)
    if rc != 0 and crashed(out):
        return "fail", "critic.py: " + crashed(out)
    cj = pathlib.Path(run.s["sample"]) / "critic" / "critic.json"
    res = json.loads(cj.read_text(encoding="utf-8"))["results"] if cj.exists() else []
    bad = [r for r in res if r.get("verdict") in ("FAIL", "ERROR")]
    unsure = [r["label"] for r in res if r.get("verdict") == "UNSURE"]
    run.s["critic_unsure"] = unsure
    if rc == 0:
        return "done", f"{len(res)} judgments, none failed" + (f"; unsure (look yourself): {', '.join(unsure)}" if unsure else "")
    return "gate", " | ".join(f"{r['label']}: {'; '.join(r.get('problems') or [r.get('error', '')])}" for r in bad)[:900]


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def st_report(run, a):
    sd = pathlib.Path(run.s["sample"])
    video = sd / ("master_music.mp4" if (sd / "master_music.mp4").exists() else "master.mp4")
    dst = ROOT / "out" / "samples" / run.scene / f"{run.scene}_{sd.name}.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(video, dst)
    except OSError:
        shutil.copy2(video, dst)
    b = brief(run)
    tl = json.loads((sd / "timeline.json").read_text(encoding="utf-8"))
    secs = DEFAULTS["sample"]["seconds"]
    kinds = {}
    for e in tl["events"]:
        if e["t"] < secs and e["t"] + float(e.get("dur", 0) or 0) > 0:      # under way at 0:00 counts too (a snail)
            kinds.setdefault(e["type"], []).append(e["t"])
    ev_lines = [f"- {k}: {len(ts)}, " + ("under way from the start" if min(ts) < 0 else f"first at {mmss(min(ts))}")
                for k, ts in sorted(kinds.items(), key=lambda kv: min(kv[1]))]
    spec = json.loads((ROOT / "scenes" / run.scene / "scene.json").read_text(encoding="utf-8"))
    intro = spec.get("intro", {}).get("lines", [])
    intro_txt = " / ".join(x["text"] if isinstance(x, dict) else x for x in intro)
    aes = catalog()["aesthetics"].get(run.s["look"], {})
    cm = sd / "critic" / "critic.md"
    pick = b.get("pick_scores") or []
    scores = "; ".join(f"#{s.get('index')}: composition {s.get('composition')}, animatable {s.get('animatable')}, "
                       f"artifacts {s.get('artifacts')}" for s in pick)
    md = [f"# Sample: {run.scene}", "",
          f"Idea: \"{run.s['idea']}\". Look: `{run.s['look']}` ({aes.get('title', '')})"
          + (", a NEW look added to config/aesthetics.json" if run.s.get("new_look") else "") + ".", "",
          f"**Watch:** `{dst}` ({mmss(secs)}, 4K, {'with music' if video.name == 'master_music.mp4' else 'ambience only'}).", "",
          f"- **Key art:** `{ROOT / 'out' / run.scene / 'keyart_sheet.jpg'}`; the vision model picked `{b.get('hero', '')}`"
          + (f" ({scores})" if scores else "")
          + f". To use another candidate: `autopilot.py run --scene {run.scene} --pick <png> --from pick`.",
          f"- **Setting:** {b.get('setting', '')}. Pet: {b.get('pet', '')}. Signature detail: {b.get('signature_detail', '')}.",
          f"- **Opening line:** \"{intro_txt}\" in {aes.get('title_font', '')}.",
          f"- **Checks:** review PASS; critic: `{cm}`"
          + (f". Unsure (the model couldn't see enough; looked at by the agent): {', '.join(run.s.get('critic_unsure') or [])}" if run.s.get("critic_unsure") else ""),
          f"- **Azure spend this run:** ~${spend_breakdown(run)[0]:.2f} of the ${run.s['budget']:.2f} budget: "
          + ", ".join(f"{k} ${v:.2f}" for k, v in sorted(spend_breakdown(run)[1].items(), key=lambda kv: -kv[1]))
          + ". Renders run on the local GPU and cost nothing.", "",
          f"## What happens in these {mmss(secs)}", "", *ev_lines, "",
          "## Next", "",
          f"- **OK:** say so, and the agent runs `tools/finish_video.py {run.scene}` (the 20 minute loop, the 10 h with music, "
          "thumbnails, title and description in his form, the upload folder).",
          "- **Changes:** say what; each one becomes a lessons row and the agent re-renders from the right stage."]
    (run.dir / "sample.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    run.s["report"] = str(run.dir / "sample.md")
    return "done", str(run.dir / "sample.md")


FUNCS = {"look": st_look, "plan": st_plan, "keyart": st_keyart, "pick": st_pick, "prep": st_prep, "analyze": st_analyze,
         "clean": st_clean, "features": st_features, "life": st_life, "setup": st_setup, "checks": st_checks, "music": st_music,
         "render": st_render, "review": st_review, "critic": st_critic, "report": st_report}

FIX_HINTS = {
    "checks": "Read out/<scene>/auto/checks.log. Fix the scene data or masks (lessons rows named there; plate-scene and "
              "plate-weather skills), then `--from checks`.",
    "review": "Read out/<scene>/auto/review.log and the event sheets in the render's review/ folder. Fix, then `--from render`.",
    "critic": "Read the render's critic/critic.md and its evidence. Fix the cause and its whole class (L56), then `--from render`. "
              "If you are sure the critic is wrong, look at the evidence, write why in progress.md and `--from report`.",
}


def cmd_run(a):
    scene = a.scene
    pre = None
    if not scene:
        if not a.idea:
            raise SystemExit("give an idea, or --scene to resume")
        # the look first, so the scene gets the resolver's descriptive name (farm-porch-rain, not the idea's words)
        if not a.look:
            pre = resolve(a.idea, getattr(a, "weather", None) or named_weather(a.idea))
        name = re.sub(r"[^a-z0-9-]+", "-", str((pre or {}).get("scene") or "").lower()).strip("-")
        scene = name if 3 <= len(name) <= 40 else slug(a.idea)
        base, k = scene, 2
        while (ROOT / "scenes" / scene).exists() and not (ROOT / "out" / scene / "auto" / "state.json").exists():
            scene, k = f"{base}-{k}", k + 1
    run = Run(scene)
    if a.idea:
        run.s.setdefault("idea", a.idea)
    if not run.s.get("idea"):
        raise SystemExit("no idea recorded for this scene; pass it")
    if pre and not run.s.get("look"):
        if pre.get("new"):
            add_look(pre["look"], pre["entry"])
        run.s.update({"look": pre["look"], "new_look": bool(pre.get("new")), "look_why": pre.get("why"),
                      "setting_hint": pre.get("setting_hint")})
        run.mark("look", "done", f"{pre['look']} ({'new look' if pre.get('new') else 'existing'}): {pre.get('why')}")
    run.s["budget"] = float(a.budget if a.budget is not None else run.s.get("budget", DEFAULTS["budget_usd_per_sample"]))
    if a.pick:
        run.s["stages"].pop("pick", None)
    if a.from_stage:
        i = STAGES.index(a.from_stage)
        for s in STAGES[i:]:
            run.s["stages"].pop(s, None)
        if a.from_stage == "pick":
            b = brief(run)
            b.pop("hero", None)
            (ROOT / "scenes" / scene / "brief.json").write_text(json.dumps(b, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    run.save()
    run.log(f"run: {scene}: \"{run.s['idea']}\"")
    run.s["redos"] = 0
    i = 0
    while i < len(STAGES):
        stage = STAGES[i]
        if run.done(stage):
            i += 1
            continue
        if stage in PAID and run.spent() >= run.s["budget"]:
            run.mark(stage, "stopped", f"budget: ~${run.spent():.2f} of ${run.s['budget']:.2f} spent this run")
            print(f"\nSTOPPED at {stage}: the run's budget is spent. Ask Truman before raising --budget.")
            return 3
        try:
            status, note = FUNCS[stage](run, a)
        except DailyCap as e:
            run.mark(stage, "stopped", str(e))
            print(f"\nSTOPPED at {stage}: {e}\nAsk Truman before raising the cap. Resume with --from {stage}.")
            return 3
        if status == "redo":
            # a gate fixed what it found by itself (evaluator-optimizer): go back to the named stage
            target = note.split(" ", 1)[0]
            run.mark(stage, "redo", note)
            for s in STAGES[STAGES.index(target):]:
                run.s["stages"].pop(s, None)
            run.save()
            i = STAGES.index(target)
            continue
        run.mark(stage, status, note)
        if status == "ask":
            print(f"\nQUESTION for Truman at {stage}: {note}")
            return 4
        if status == "gate":
            print(f"\nNEEDS FIX at {stage}: {note}\n{FIX_HINTS[stage].replace('<scene>', scene)}\n"
                  f"Resume: .venv\\Scripts\\python tools\\autopilot.py run --scene {scene} --from {'render' if stage != 'checks' else 'checks'}")
            return 2
        if status == "fail":
            print(f"\nFAILED at {stage}: {note}\nSee out/{scene}/auto/{stage}.log; fix, then resume with --from {stage}.")
            return 1
        i += 1
    print(f"\nsample ready: {run.s.get('report')}")
    return 0


def cmd_look(a):
    res = resolve(a.idea, named_weather(a.idea))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    if res.get("new") and a.apply:
        add_look(res["look"], res["entry"])
        print(f"added look {res['look']} to {AES_PATH}")
    return 0


def cmd_status(a):
    run = Run(a.scene)
    for s in STAGES:
        st = run.s["stages"].get(s) or {}
        print(f"  {s:9s} {st.get('status', '-'):8s} {st.get('note', '')[:110]}")
    print(f"  spend this run ~${run.spent():.2f}; sample: {run.s.get('sample', '-')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("look")
    p.add_argument("idea")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("idea", nargs="?")
    p.add_argument("--scene")
    p.add_argument("--look")
    p.add_argument("--pick")
    p.add_argument("--from", dest="from_stage", choices=STAGES)
    p.add_argument("--n", type=int, default=DEFAULTS["keyart_candidates"])
    p.add_argument("--budget", type=float)
    p.add_argument("--weather", help="the weather Truman chose (the plan stage asks when his line names none)")
    p = sub.add_parser("status")
    p.add_argument("scene")
    a = ap.parse_args()
    return {"look": cmd_look, "run": cmd_run, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    sys.exit(main())
