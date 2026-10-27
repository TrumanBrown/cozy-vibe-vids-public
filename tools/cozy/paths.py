"""Where things are, for every tool (TASKS.md T10): the repo, the venv's Python, the scene, plate, key-art and output
folders, the config files and scene.json.

  ROOT                 the repo
  PY                   the venv's Python (.venv\\Scripts\\python.exe or .venv/bin/python) for child processes; else this one
  scene_dir(s)         scenes/<s>              plate_dir(p)   out/plates/<p>
  keyart_dir(s)        assets/keyart/<s>       out_dir(s)     out/<s>          (no argument: the folder itself)
  config(name)         config/<name>.json, read again on every call (autopilot adds a look to aesthetics.json mid-run)
  safe_name(s, d)      a name a model made (a region, a creature) as one plain folder or file name, else d
  load_scene(s)        scenes/<s>/scene.json
  save_scene(s, spec)  scenes/<s>/scene.json in the one format: indent 2, UTF-8 unescaped, LF, a trailing newline;
                       written to a temp file and moved over the old one, so a failed write never leaves half a file
  load_json(p, d)      a JSON file, or d when it doesn't exist
  rel(p)               a path as shown in logs and records: repo-relative with / inside the repo, else absolute
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = next((str(p) for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python") if p.exists()),
          sys.executable)


def scene_dir(scene=""):
    return ROOT / "scenes" / scene


def plate_dir(plate=""):
    return ROOT / "out" / "plates" / plate


def keyart_dir(scene=""):
    return ROOT / "assets" / "keyart" / scene


def out_dir(scene=""):
    return ROOT / "out" / scene


def config(name):
    """config/<name>.json, parsed. Never cached: a file edited during a run is read as it is now."""
    return json.loads((ROOT / "config" / f"{name}.json").read_text(encoding="utf-8"))


def safe_name(s, default):
    """A name a vision or chat model made, fit to be one folder or file name (steam/<name>/, critter_<creature>.png):
    lowercase letters and digits joined by underscores, at most 40 characters; default when nothing is left. A name
    like "../x" or "a/b" can't reach outside its folder (security review 2026-10-26)."""
    s = re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:40].strip("_")
    return s or default


def creature_id(s, default="snail"):
    """One id per creature, however a model or a person wrote it: lowercase letters and digits only, so "shield bug",
    "shield_bug" and "Shield-Bug" are all "shieldbug". It is the sprite's file name (critter_<id>.png, safe like
    safe_name's), the key of every creature table (plate_features PACE, cozy.segment CRITTER_M, critter.py LOOKS and
    LIFT) and what review compares a signature critter by. safe_name made "shield bug" into "shield_bug", which no
    table knew: the bug was drafted at a snail's pace and review failed its own signature check (2026-10-27)."""
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())[:40] or default


def load_scene(scene):
    return json.loads((scene_dir(scene) / "scene.json").read_text(encoding="utf-8"))


def load_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def rel(p):
    p = Path(p).resolve()
    return p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)


def write_atomic(path, text):
    """Write text (UTF-8, LF) to a temp file beside path, then move it over path in one step."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


TYPES_FILE = ROOT / "src" / "library" / "types.json"


def scene_problems(spec):
    """What a scene.json has that the renderer doesn't know (src/library/types.json: its layer types and the top-level
    keys a scene may have; a key starting with _ is a note). Empty when it is fine (TASKS.md T14)."""
    t = json.loads(TYPES_FILE.read_text(encoding="utf-8"))
    keys, layers = set(t["scene_keys"]), set(t["layers"])
    out = [f"top-level key {k!r}" for k in spec if k not in keys and not k.startswith("_")]
    out += [f"layer {i} has type {L.get('type')!r}" for i, L in enumerate(spec.get("layers", [])) if L.get("type") not in layers]
    return out


def save_scene(scene, spec):
    """Write scenes/<scene>/scene.json (the folder must exist) in the one format every writer uses. Returns its path.
    A spec with a key or a layer type the renderer doesn't know is refused before anything is written."""
    bad = scene_problems(spec)
    if bad:
        raise ValueError(f"scenes/{scene}/scene.json not written: {'; '.join(bad)} (the known ones: src/library/types.json)")
    p = scene_dir(scene) / "scene.json"
    write_atomic(p, json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
    return p
