"""Prepare an AI key-art image for animation: crop to 16:9, upscale, estimate depth, build motion masks.

Usage (repo root):
  .venv/Scripts/python tools/plate_prep.py <image.png> --name <plate> [--crop-y 0.5] [--width 3840] [--sr-from 0]
  .venv/Scripts/python tools/plate_prep.py <image.png> --name <plate> --masks-only   # reuse plate/depth

Writes out/plates/<plate>/:
  plate_raw.png  WxH sRGB upscale of the key art
  plate.png      plate_raw with painted-in rain streaks removed (see derain() and, on pixel art, derain_cells(); static
                 streaks look frozen under animated rain). Configure with "derain": {"strength": 1.5} / false and
                 "not_derain" polygons.
  depth.png      16-bit relative disparity (near = bright); depth8.png = sqrt(disparity) 8-bit (for WebGL)
  masks.png      R = sky, G = water, B = near foliage
  lights.png     R = light sources, G = OUTDOORS (weather region), B = light glow (wide falloff)
  env.png        local outdoor environment radiance (blurred, 1/8 res): lights rain drops locally
  flash.png      light reaching in through the opening (blurred outdoor mask, 1/4 res): lightning room glow
  lightid.png    ids (1..63, 0 = none) of the 4 controllable lights affecting each pixel most: RGB low 6
                 bits = id1..id3, top 2 bits of R/G/B = id4 (bits 0-1/2-3/4-5); plate.json light_groups
  lightw.png     their shares of the lights-off delta: RGB = w1..w3, w4 = 1 - w1 - w2 - w3
  plate_off.png  the plate with every controllable light off (windows dark, lanterns dimmed)
  blur.png       the plate defocused, half resolution (rain on glass refracts it; steam/dust scatter it)
  defocus.png    how out of focus the plate is around each point (Gaussian sigma in 4K px = value / 20, one
                 pixel per 16x16 block): the ant is blurred to match the surface it walks on
  refl.png       where the wet ground reflects a flickering light (R = its region id, G = weight): plate.js dims
                 the reflection with the light; refl_preview.jpg shows them ("reflections": false turns it off)
  gaps.png       wet ground seen through gaps in near objects (between a stool's legs, a railing's balusters): filled
                 in by gap_fill, where the depth is the object's smear (weather_audit doesn't flag it as upright)
  gap_parts.png  the near object's own parts seen through its gaps (a stool's back legs): kept out of the weather
  depth_fine.png depth8.png with the depth model's halo around thin dark structures against the sky (poles,
                 wires) put back to the sky's depth: what flies in the sky is hidden by the pole, not the air
                 beside it (birds.js, perch.js); depth_fine_preview.jpg
  regions.png    named animation regions ("regions" in the masks json): R = id 1..63 (depth order, nearest
                 wins), G = feathered weight, B = coordinate along the region's anchor axis; regions.json
                 lists id -> name, kind, bbox, center, geometry; regions_preview.png shows them labeled
  flow.png       waterfalls (only with "waterfall" polygons): R = flow weight (soft, gated to the bright bluish
                 water), G = progress down each fall (0 at the lip, 1 at the foot), B = 0
  occ.png        what the crawling critter passes behind (only with "critter_occ": region names or polygons):
                 255 = in front of it; critters.js hides it there and pushes its path ends in out of sight
  plate.json     size, env colors (linear RGB), outdoor top-edge profile, drip/stream source candidates,
                 "beads" (hanging drops along wet edges) and "strand_drips" (where plate_clean.py removed
                 painted drips: [x, y, w, stop row, px per m]; built from clean.png's clean.json)
  preview_masks.png, edges_preview.png (sources overlay)

Outdoors (where rain can exist) = pixels whose disparity is below `outdoor_disp` (porch geometry is near,
the world outside is far), edge-snapped to the image with a guided filter, then limited by optional
polygons. This is what keeps rain off the roof, posts, railing, pets and interior.

Hand overrides: assets/keyart/<plate>.masks.json (normalized x,y polygons, y down):
  {"outdoor_disp": 0.15, "only_outdoor": [...], "not_outdoor": [...], "sky": [...], "not_water": [...], ...}
Analyzed scenes (tools/analyze_plate.py) also set "regions": [{name, kind, polys | box | point, ...}],
"outdoor_regions": ["glass"] (outdoors = those regions, "all" = whole frame), "outdoor_disp": "auto",
"auto_masks": false (sky/water/foliage only from polygons), "auto_lanterns": false, "auto_windows": false,
"critter_occ": [region names or polygons] (what the critter goes behind at its path ends -> occ.png).

Models (Apache-2.0): depth-anything/Depth-Anything-V2-Small-hf, caidas/swin2SR-classical-sr-x4-64.

The steps are in tools/cozy/plate/ (TASKS.md T16), one module per job: image (crop, upscale, depth), primitives,
regions, weather (the masks), derain, lights, sources and pets. This script reads the arguments, merges the hand fixes
and writes the plate folder.
"""
import argparse
import json
import os
import pathlib

from cozy.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from cozy.masks import pixelize, render_occluders  # noqa: E402  (TASKS.md T12)
# the steps are in cozy/plate/ (TASKS.md T16)
from cozy.plate.image import crop_16x9, defocus_map, depth, depth_fine, upscale  # noqa: E402
from cozy.plate.primitives import srgb_to_linear  # noqa: E402
from cozy.plate.regions import regions_preview, render_regions  # noqa: E402
from cozy.plate.weather import flow_map, masks  # noqa: E402
from cozy.plate.derain import cleanup, derain, derain_cells, pixel_grid  # noqa: E402
from cozy.plate.lights import light_groups, light_reflections  # noqa: E402
from cozy.plate.sources import bead_sources, dry_mask, edge_sources, fire_beds, keep_off_dry, strand_drips, vessel_openings  # noqa: E402
from cozy.plate.pets import pet_map  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--name", required=True)
    ap.add_argument("--crop-y", type=float, default=0.5, help="vertical center of the 16:9 crop (0..1)")
    ap.add_argument("--width", type=int, default=3840)
    ap.add_argument("--masks-only", action="store_true", help="reuse existing plate.png/depth.png")
    ap.add_argument("--redepth", action="store_true", help="reuse plate.png but recompute depth")
    ap.add_argument("--keep-depth", action="store_true",
                    help="upscale the image again but keep depth.png: after an art edit (tools/art_edit.py) that changes "
                         "colors and textures, not the room's shape, so the masks built on the depth stay put")
    ap.add_argument("--sr-from", type=int, default=0, help="downscale to this width first so Swin2SR x4 adds detail (0 = off)")
    a = ap.parse_args()
    out = ROOT / "out" / "plates" / a.name
    out.mkdir(parents=True, exist_ok=True)
    if a.masks_only or a.redepth:
        raw_p = out / "plate_raw.png"
        if not raw_p.exists():  # plates made before de-rain existed: plate.png is the raw upscale
            Image.open(out / "plate.png").save(raw_p)
        plate = Image.open(raw_p).convert("RGB")
    else:
        src = crop_16x9(Image.open(a.image).convert("RGB"), a.crop_y)
        if a.sr_from and src.width > a.sr_from:
            src = src.resize((a.sr_from, round(a.sr_from * src.height / src.width)), Image.LANCZOS)
        plate = upscale(src, a.width)
        plate.save(out / "plate_raw.png")
    if a.masks_only or (a.keep_depth and (out / "depth.png").exists()):
        disp = np.asarray(Image.open(out / "depth.png"), np.float32) / 65535
    else:
        disp = depth(plate)
        Image.fromarray((disp * 65535).astype(np.uint16)).save(out / "depth.png")
    W, H = plate.size
    ov_path = ROOT / "assets" / "keyart" / f"{a.name}.masks.json"
    ov = json.loads(ov_path.read_text()) if ov_path.exists() else {}
    # Hand fixes on top of an analyzed scene (tools/analyze_plate.py rewrites masks.json, never hand.json):
    # lists (polygons, regions) are appended, other keys replace.
    hp = ROOT / "assets" / "keyart" / f"{a.name}.hand.json"
    if hp.exists():
        hand = json.loads(hp.read_text())
        for k, v in hand.items():
            if k.startswith("_"):
                continue
            ov[k] = ov[k] + v if isinstance(v, list) and isinstance(ov.get(k), list) else v
        for k in ("outdoor", "water"):
            ov[f"_hand_not_{k}"] = list(hand.get(f"not_{k}") or [])     # the hand's own cuts win over its "<k>_open"
        print(f"  hand fixes: {hp.name}")
    # what tools/outdoor_check.py found inside under the weather (traced by SAM, a cell around it) is cut like a hand
    # not_outdoor / not_water polygon; kept under its own keys so weather_audit knows it is dry on purpose
    for src, dst in (("outdoor_cuts", "not_outdoor"), ("water_cuts", "not_water")):
        if ov.get(src):
            ov[dst] = list(ov.get(dst) or []) + list(ov[src])
    pg = None
    if ov.get("pixel"):
        pg = ov["pixel"] if isinstance(ov["pixel"], dict) else None
        if pg is None:
            g = pixel_grid(plate)
            pg = {"cell": round(g[0], 3), "origin": [round(g[1], 2), round(g[2], 2)]} if g else None
    m = masks(plate, disp, ov, out_dir=out, cell=pg["cell"] if pg else None)
    clean, corr = derain(plate, m["outdoor"], m["lights"], ov)
    clean = cleanup(clean, ov, m["outdoor"])
    pixel = None
    if pg:
        clean = pixelize(clean, pg["cell"], *pg["origin"])
        clean, ndash = derain_cells(clean, pg, m["outdoor"], m["lights"], ov)
        pixel = pg
        print(f"  pixel art: cell {pg['cell']:.2f} px, origin {pg['origin']} (plate rebuilt on the grid)"
              + (f"; {ndash} cells of painted rain removed on the grid" if ndash else ""))
    clean.save(out / "plate.png")
    plate = clean
    rgb = np.stack([m["sky"], m["water"], m["foliage"]], -1)
    Image.fromarray((rgb * 255).round().astype(np.uint8), "RGB").save(out / "masks.png")
    fm = flow_map(plate, ov)
    if fm is not None:
        Image.fromarray((np.clip(fm, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "flow.png")

    # Light glow (float blur, dithered): rain/mist pick up warm light from it.
    small = cv2.resize(m["lights"].astype(np.float32), (W // 8, H // 8), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(small, (0, 0), W / 8 / 50) + 2.0 * cv2.GaussianBlur(small, (0, 0), W / 8 / 16)
    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_CUBIC)
    glow = np.clip(g / max(float(g.max()), 1e-6), 0, 1) ** 0.6
    glow = glow + (np.random.default_rng(0).random(glow.shape) - 0.5) / 255.0
    Image.fromarray((np.clip(np.stack([m["lights"], m["outdoor"], glow], -1), 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "lights.png")
    Image.fromarray((np.sqrt(disp) * 255).round().astype(np.uint8)).save(out / "depth8.png")
    # Defocused plate (half resolution): what rain on the glass refracts (the view behind the pane is out of
    # focus) and the light that steam and dust scatter.
    half = cv2.resize(np.asarray(plate, np.float32), (W // 2, H // 2), interpolation=cv2.INTER_AREA)
    Image.fromarray(np.clip(cv2.GaussianBlur(half, (0, 0), 6 * W / 3840), 0, 255).round().astype(np.uint8)).save(out / "blur.png")
    defocus_map(plate, out)
    depth_fine(plate, disp, m["outdoor"], out)
    regions = render_regions(ov.get("regions"), disp, W, H, out, plate=plate, outdoor=m["outdoor"],
                             views_outdoor=ov.get("views_outdoor", True), no_view=ov.get("no_view") or {})
    render_occluders(ov, W, H, out)
    if regions and (fire_beds(plate, regions, W, H) | vessel_openings(plate, regions, ov, W, H)):
        (out / "regions.json").write_text(json.dumps(regions, indent=1))
    regions_preview(plate, regions, out)
    if ov.get("reflections") is not False:
        light_reflections(plate, m["water"], disp, out)
    if regions:
        names = ", ".join("%d:%s(%s)" % (g["id"], g["name"], g["kind"]) for g in regions)
        print(f"  regions: {names}")

    # Environment colors (linear RGB) for lighting rain: what a drop "sees" (Garg & Nayar: a drop
    # refracts a ~165 deg view of the environment, so its radiance ~ the environment average).
    lin = srgb_to_linear(np.asarray(plate, np.float32) / 255)
    def mean_rgb(mask):
        w = mask.reshape(-1).astype(np.float64)
        return (lin.reshape(-1, 3) * w[:, None]).sum(0) / max(w.sum(), 1.0)
    env = {"sky": mean_rgb(m["sky"] if m["sky"].sum() > 500 else m["outdoor"]).round(5).tolist(), "outdoor": mean_rgb(m["outdoor"]).round(5).tolist(),
           "scene": lin.reshape(-1, 3).mean(0).round(5).tolist()}
    # env.png: local environment radiance around each point of the opening (outdoor pixels only,
    # normalized Gaussian blur, ~1/14 frame width): drops in front of dark forest see a darker
    # environment than drops against the misty sky. sRGB-encoded, 1/8 resolution.
    s8 = (W // 8, H // 8)
    lo = cv2.resize(lin.astype(np.float32), s8, interpolation=cv2.INTER_AREA)
    wo = cv2.resize(m["outdoor"].astype(np.float32), s8, interpolation=cv2.INTER_AREA)
    sig = W / 8 / 14
    num = cv2.GaussianBlur(lo * wo[..., None], (0, 0), sig)
    den = cv2.GaussianBlur(wo, (0, 0), sig)[..., None]
    loc = np.where(den > 0.02, num / np.maximum(den, 1e-6), np.array(env["outdoor"], np.float32))
    enc = np.where(loc <= 0.0031308, loc * 12.92, 1.055 * np.power(np.clip(loc, 0, 1), 1 / 2.4) - 0.055)
    Image.fromarray((np.clip(enc, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "env.png")
    # flash.png: how much light from the opening reaches each point (blurred outdoor mask, 1/4 res).
    # Lightning lights the porch most near the opening (docs/GOALS.md: "soft glow lights the room").
    s4 = (W // 4, H // 4)
    o4 = cv2.resize(m["outdoor"].astype(np.float32), s4, interpolation=cv2.INTER_AREA)
    fl = cv2.GaussianBlur(o4, (0, 0), W / 4 / 14) + 0.6 * cv2.GaussianBlur(o4, (0, 0), W / 4 / 4)
    fl = np.clip(fl / max(float(fl.max()), 1e-6), 0, 1)
    Image.fromarray((fl * 255).round().astype(np.uint8)).save(out / "flash.png")

    xs, ytop, cands = edge_sources(m["outdoor"], W, H)
    # Controllable lights: id map (nearest filtering in shaders) + the plate with all lights off.
    disp_full = disp
    lid, lwt, off, lgroups = light_groups(plate, m["outdoor"], m["water"], disp_full, ov)
    Image.fromarray(lid, "RGB").save(out / "lightid.png")
    Image.fromarray(lwt, "RGB").save(out / "lightw.png")
    Image.fromarray((np.clip(off, 0, 1) * 255).round().astype(np.uint8)).save(out / "plate_off.png")
    pv = (np.asarray(plate, np.float32) * 0.55).astype(np.uint8).copy()
    for g in lgroups:
        c = (0, 255, 0) if g["kind"] == "window" and not g["reflective"] else (255, 160, 0) if g["kind"] == "lantern" else (120, 120, 255)
        cv2.circle(pv, (int(g["x"] * W), int(g["y"] * H)), 22, c, 3)
        cv2.putText(pv, str(g["id"]), (int(g["x"] * W) + 20, int(g["y"] * H) - 18), cv2.FONT_HERSHEY_SIMPLEX, 1.1, c, 2)
    Image.fromarray(pv).resize((1920, 1080)).save(out / "lights_preview.png")
    # Foliage palette (sRGB, sorted dark -> bright, with pixel share): colors for falling leaves etc.
    fol = np.asarray(plate, np.float32)[m["foliage"] > 0.5]
    palette = []
    if len(fol) > 500:
        smp = fol[np.random.default_rng(0).choice(len(fol), min(len(fol), 60000), replace=False)]
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
        cv2.setRNGSeed(0)
        _, lab, cen = cv2.kmeans(smp, 6, None, crit, 4, cv2.KMEANS_PP_CENTERS)
        share = np.bincount(lab.ravel(), minlength=6) / len(lab)
        order = np.argsort(cen @ np.array([0.2126, 0.7152, 0.0722], np.float32))
        palette = [[int(round(v)) for v in cen[i]] + [round(float(share[i]), 3)] for i in order]
    beads = bead_sources(m["outdoor"], ov, W, H, disp=disp)
    cj = pathlib.Path(a.image).resolve().parent / "clean.json"
    sdrips = (strand_drips(json.loads(cj.read_text(encoding="utf-8")), disp, W, H, lights=m["lights"], wet=m["water"])
              if pathlib.Path(a.image).name == "clean.png" and cj.exists() else [])
    dry = dry_mask(W, H, out)
    beads = keep_off_dry(beads, dry, m["outdoor"], W, H, "hanging drop")
    sdrips = keep_off_dry(sdrips, dry, m["outdoor"], W, H, "strand drip")
    pmap = pet_map(ov, W, H, out, pixel)
    if pmap:
        print(f"  pet.png: the torso breathes, {pmap['still_parts']} still part(s) (head, tail) hold still, the background never moves"
              + (f"; {len(pmap['pets'])} characters, each from its own base: " + ", ".join(f"{p['region']} amp {p['amp']:.3f}" for p in pmap["pets"])
                 if pmap.get("multi") else ""))
    meta = {"width": W, "height": H, "source": a.image, "outdoor_disp": ov.get("outdoor_disp", 0.15), "env_linear": env,
            "foliage_palette": palette, "light_groups": lgroups, "flow": fm is not None, "regions": regions, "pixel": pixel,
            "edge_step": 4, "edge_ytop": ytop[::4].tolist(), "drip_candidates": cands, "beads": beads, "strand_drips": sdrips,
            "pet_map": pmap}
    (out / "plate.json").write_text(json.dumps(meta, indent=1))

    # Previews.
    p = np.asarray(plate, np.float32) / 255 * 0.45
    tint = p + m["outdoor"][..., None] * [0.3, 0, 0.3] + m["sky"][..., None] * [0, 0, 0.4] + m["water"][..., None] * [0, 0.4, 0.4] + m["foliage"][..., None] * [0, 0.5, 0] + m["lights"][..., None] * [0.6, 0.6, 0.6]
    prev = np.concatenate([np.clip(tint, 0, 1), np.repeat(disp[..., None], 3, -1)], 1)
    Image.fromarray((prev * 255).astype(np.uint8)).resize((1920, 540)).save(out / "preview_masks.png")
    ep = (np.asarray(plate, np.float32) * 0.6).astype(np.uint8).copy()
    for i, x in enumerate(xs):
        if ytop[i] >= 0:
            cv2.circle(ep, (int(x), int(ytop[i])), 2, (0, 255, 255), -1)
    colors = {"tip": (255, 80, 80), "eave": (80, 255, 80), "top": (80, 160, 255)}
    for x, y, k in cands:
        cv2.circle(ep, (x, y), 14, colors[k], 4)
        cv2.putText(ep, f"{x / W:.3f}", (x - 40, y + 50), cv2.FONT_HERSHEY_SIMPLEX, 1.1, colors[k], 2)
    for x, y, w in beads:
        cv2.circle(ep, (x, y + 6), 5 if w < 2 else 9, (255, 0, 255), -1)
    for x, y, _, stop, *_ in sdrips:
        cv2.circle(ep, (x, y + 4), 7, (0, 255, 255), -1)
        cv2.line(ep, (x, y + 10), (x, min(stop, H - 1)), (0, 255, 255), 2)
    Image.fromarray(ep).resize((1920, 1080)).save(out / "edges_preview.png")
    print(f"plate {plate.size} -> {out}; env {env}; {len(cands)} drip candidates, {len(beads)} bead sources, {len(sdrips)} strand drips")


if __name__ == "__main__":
    main()
