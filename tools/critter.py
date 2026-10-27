"""Critter sprites: a small creature (snail, ladybug, gecko, beetle, frog, mouse) in the scene's art style, for
src/library/critters.js to crawl along a surface of the plate.

Usage (repo root):
  .venv/Scripts/python tools/critter.py <scene> gen --creature snail [--seed-note "..."]   # Azure gpt-image, transparent PNG
  .venv/Scripts/python tools/critter.py <scene> info --creature snail                      # (re)measure an existing sprite

Writes assets/keyart/<scene>/critter_<creature>.png (committed: a source asset) and .json: provenance plus
measurements the renderer needs (sprite px): bbox of the opaque pixels, the foot line (lowest opaque row,
where it touches the surface), the front (head) end, the stretchy part (the foot/body in front of the shell,
for snails), mean luminance (to light it like its surroundings). Facing right; the renderer mirrors it.
"""
import argparse
import base64
import datetime as dt
import io
import json
import sys

import numpy as np
from PIL import Image

from cozy.paths import ROOT, config, creature_id

LOOKS = {
    "snail": ("a small garden snail crawling to the right, seen from the side: a glossy spiral shell, brown with darker bands, on its "
              "back; its soft grey-brown body stretched out low along the ground in front of the shell, two long eye stalks up and "
              "two short feelers at the front, wet and shiny"),
    "ladybug": "a small red ladybug with black spots walking to the right, seen from the side and a little above, legs visible",
    "gecko": "a small pale gecko walking to the right, seen from above at a slight angle, its tail curving behind",
    "beetle": "a small dark shiny beetle walking to the right, seen from the side, legs visible",
    "shieldbug": ("a small green shield bug walking to the right, seen from the side and a little above: a flat shield-shaped green "
                  "back with a slightly darker edge, six thin legs and two antennae, legs visible"),
    "frog": "a small green frog sitting facing right, seen from the side, wet and shiny",
    "mouse": "a small brown field mouse walking to the right, seen from the side, its tail behind it",
}
# Creatures dark by nature: critters.js lights a sprite to about 1.6 times the light around it divided by the sprite's
# own mean brightness, which turned the pixel greenhouse's black beetle into a pink-gray bug on the lit floor
# (2026-10-21); its "lift" scales that down. Written into the sprite's json.
LIFT = {"beetle": 0.55}


def sprite_path(scene, creature):
    return ROOT / "assets" / "keyart" / scene / f"critter_{creature}.png"


def measure(png):
    im = Image.open(png).convert("RGBA")
    a = np.asarray(im, np.float32)
    al = a[..., 3] / 255
    ys, xs = np.nonzero(al > 0.5)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    cols = np.arange(x0, x1 + 1)
    # foot line: per column the lowest opaque row; the contact is the long flat run at the bottom
    low = np.array([np.flatnonzero(al[:, c] > 0.5).max() if (al[:, c] > 0.5).any() else -1 for c in cols])
    foot_y = int(np.percentile(low[low > 0], 90))
    # thickness per column (opaque rows): the shell is the tall part, the body in front of it is low
    thick = np.array([(al[:, c] > 0.5).sum() for c in cols])
    tall = thick > 0.55 * thick.max()
    shell = [int(cols[tall].min()), int(cols[tall].max())] if tall.any() else [x0, (x0 + x1) // 2]
    rgb = a[..., :3][al > 0.5] / 255
    lum = float((rgb @ np.array([0.2126, 0.7152, 0.0722])).mean())
    return {"size": list(im.size), "bbox": [x0, y0, x1, y1], "foot_y": foot_y, "front_x": x1, "back_x": x0, "shell_x": shell, "lum": round(lum, 4)}


def cmd_gen(a):
    from azure_ai import generate_image, CFG
    brief = json.loads((ROOT / "scenes" / a.scene / "brief.json").read_text(encoding="utf-8"))
    aes = config("aesthetics")["aesthetics"][brief["aesthetic"]]
    style = aes.get("style_prompt") or aes.get("style", "")
    light = brief.get("light", "")
    prompt = (f"A single {LOOKS.get(a.creature, a.creature)}. Painted to match this art style: {style}. Lighting to match the scene: {light}. "
              "The whole creature is in view, centered, with a little space around it. Transparent background, no ground, no shadow, "
              "no other objects, no text.")
    dep = aes.get("keyart_model")
    try:
        res = generate_image(prompt, deployment=dep, size="1024x1024", quality="high", purpose=f"critter:{a.scene}:{a.creature}", background="transparent")
        im = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"])))
        if im.mode != "RGBA":
            raise ValueError("an opaque image (no transparent background)")
    except (Exception, SystemExit) as e:
        if not dep:
            raise
        # the look's own model first (a hand-made medium, 2026-10-25); the default one when it can't cut the sprite out
        print(f"  {dep}: {e}; the default model instead")
        dep = None
        res = generate_image(prompt, size="1024x1024", quality="high", purpose=f"critter:{a.scene}:{a.creature}", background="transparent")
        im = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"])))
    if im.mode != "RGBA":
        sys.exit("the model returned an opaque image (no transparent background): retry or cut it out")
    p = sprite_path(a.scene, a.creature)
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p)
    meta = {"creature": a.creature, "prompt": prompt, "deployment": dep or CFG["default_deployment"], "date": dt.date.today().isoformat(),
            "usage": res.get("usage"), **measure(p)}
    if a.creature in LIFT:
        meta["lift"] = LIFT[a.creature]
    p.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"wrote {p.relative_to(ROOT)}: {meta['bbox']}, foot {meta['foot_y']}, shell {meta['shell_x']}, lum {meta['lum']}")


def cmd_info(a):
    p = sprite_path(a.scene, a.creature)
    mp = p.with_suffix(".json")
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"creature": a.creature}
    meta.update(measure(p))
    if a.creature in LIFT:
        meta["lift"] = LIFT[a.creature]
    mp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("gen", "info"):
        s = sub.add_parser(name)
        s.add_argument("--creature", default="snail")
    a = ap.parse_args()
    a.creature = creature_id(a.creature)    # "shield bug" -> shieldbug: LOOKS, LIFT and critter_<creature>.png agree
    {"gen": cmd_gen, "info": cmd_info}[a.cmd](a)


if __name__ == "__main__":
    main()
