"""A pet that really moves, as pixel-art sprites (user 2026-10-21 on the pixel greenhouse: in pixel looks, animate the
whole dog so it is dynamic instead of the pixels stretching to breathe: lifting its head, walking to the door, lying
back down, a tail wag now and then, with a sprite for each animation, as a best-attempt mock shown side by side).
Pixel art is drawn frame by frame,
so sprites are the look's own way to move; the generated video of a painted pet (the ramen alley's cat, DECISIONS
2026-10-18) stays retired. Mocks only until Truman says otherwise.

  .venv\\Scripts\\python tools\\pet_sprite.py <scene> ref                 the painted pet, cut out -> petsprite/ref.png
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> gen [--only a,b]    sheets on a blank canvas (only the side walk's is still used, as
                                                                      a reference for where the legs go)
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> patches [--only]   the painted pet drowsy, half awake, awake, and the empty mat
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> pose <name> [--dry] one pose of the chain (rise, sit, stand, views): an edit of the
                                                                      pose before it; --dry first, it spends nothing
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> posecut <name>     the pose's dog(s) cut out on the plate's grid -> posed_<dog>.png
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> pderive [--only] [--dry]   walk and wag cycles from the posed masters
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> cut                 frames and petsprite.json for src/library/petsprite.js
  .venv\\Scripts\\python tools\\pet_sprite.py <scene> sheet               out/plates/<plate>/petsprite_sheet.jpg to look at

Order: ref, patches, pose rise/sit, pose stand, pose views, posecut each, pderive, cut.

Round 6 (Truman: the dog must never change style): every pose is painted into the picture from the
one before it, so it stays the dog the picture painted. A pose drawn on its own came out another dog however it was
asked: on a blank canvas a clean game sprite with a hard black outline (round 5), repainted in the picture a longer,
bigger dog (rounds 5 and 6). The painted head is carried up by whole cells and the image model paints only the body
between it and the painted rump; the back and front views are painted beside the standing dog in one edit; the walk
and wag cycles repaint only the legs or the tail of those masters (round 4: a generated walk came out as another
dog, and a generated wag moved the hind leg with the tail).

Writes assets/keyart/<scene>/petsprite/ (committed sources: edits, patches, their .json with prompt and usage, rig.json
by hand) and out/plates/<plate>/petsprite/ (frames and petsprite.json). Every image goes in the asset ledger before use.
"""
import argparse
import base64
import datetime
import io
import json
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image

from cozy.paths import ROOT

STYLE = ("in exactly the same 16-bit pixel-art style as the reference: the same chunky pixel size, the same golden-brown "
         "fur colors and shading, the same face, floppy ears, nose and proportions. ")
RULES = ("Transparent background. No ground, no floor line, no shadow, no text, no numbers, no frame borders or grid "
         "lines. Every frame shows the whole dog with a little space around it, all frames the same size and standing "
         "on the same invisible ground line, evenly spaced in one row.")
SHEETS = {
    "walk_side": ("Pixel-art sprite sheet of this same dog walking to the right, seen exactly from the side, " + STYLE +
                  "Four frames of one smooth walk cycle, left to right: 1 right front paw forward, 2 legs passing under the "
                  "body, 3 left front paw forward, 4 legs passing. Its tail is up and relaxed, its head level, ears soft. "),
    "walk_back": ("Pixel-art sprite sheet of this same dog walking straight away from the viewer, seen from behind and a "
                  "little above: we see its back, the back of its head and its two ears, its rump and its tail, held up "
                  "and wagging a little. " + STYLE + "Four frames of one walk cycle, left to right, the hind legs "
                  "alternating and the tail swinging a little from side to side. "),
    "walk_front": ("Pixel-art sprite sheet of this same dog walking straight toward the viewer, seen from the front and a "
                   "little above: its face, eyes open and friendly, ears, chest and front legs. " + STYLE + "Four frames "
                   "of one walk cycle, left to right, the front legs alternating. "),
    "sit_back": ("Pixel-art sprite sheet of this same dog sitting, seen from behind and a little above, looking straight "
                 "ahead and a little up (at a glass door in front of it): we see its back, the back of its head, its two "
                 "ears and its tail on the floor behind it. " + STYLE + "Four frames of the tail wagging: 1 tail swept "
                 "to the left, 2 tail straight behind, 3 tail swept to the right, 4 tail straight behind. The body and "
                 "head stay exactly the same in all four frames. "),
    "stand_side": ("Pixel-art sprite sheet of this same dog facing right, seen from the side, " + STYLE + "Four frames, "
                   "left to right: 1 standing still, head level, tail relaxed; 2 standing, tail up and wagging; "
                   "3 sitting upright facing right, tail on the floor; 4 lying down facing right, head up and eyes open, "
                   "front paws stretched out in front. "),
}
N_FRAMES = 4

# the cycles (pderive) repaint only a zone of a master: its edge as the rest of the dog, four copies on one canvas
EDGE = "the same pixel size, fur shading, colors and soft dark-brown edge as the rest of the dog (no black outline)"
ROW4 = {"size": [1536, 1024], "cols": 4, "rows": 1}
# the walk cycles' prompts: only the legs repainted; the side walk gets the generated walk sheet as a reference for where
# the legs go
WALK = {
    "walk_side": (
        "Pixel-art sprite sheet: the same golden-brown dog four times, facing right, seen from the side, on a "
        "transparent background. Repaint only the masked strip under each dog's body, its four legs, so that the "
        "four dogs show one smooth walk cycle to the right, in reading order (top left, top right, bottom left, "
        "bottom right): 1 the near front leg reaching forward and the near hind leg stretched back; 2 the legs "
        "passing under the body, the near hind paw lifted; 3 the near front leg back and the near hind leg "
        "forward; 4 the legs passing, the near front paw lifted. The far legs, a little darker, move opposite to "
        "the near ones; the second image shows where the legs go, not how to draw them. Every paw that is down "
        "stands on the same ground line as now. Keep the head, body and tail exactly as they are. Paint the legs "
        "with the same pixel size, fur shading, colors and soft dark-brown edge as the rest of the dog (no black "
        "outline). No ground, no shadow, no text."),
    "walk_back": (
        "Pixel-art sprite sheet: the same golden-brown dog four times in a row, walking straight away from the "
        "viewer, seen from behind, on a transparent background. Repaint only the masked strip at the bottom of "
        "each dog, its hind legs and paws, so that the four dogs show one walk cycle, left to right: 1 the left "
        "hind paw lifted, the right one down; 2 both hind paws down; 3 the right hind paw lifted, the left one "
        "down; 4 both hind paws down. Every paw that is down stands on the same ground line as now. Paint them "
        "with the same pixel size, fur shading, colors and soft dark-brown edge as the rest of the dog (no black "
        "outline). Keep the head, ears, back and tail exactly as they are. No ground, no shadow, no text."),
    "walk_front": (
        "Pixel-art sprite sheet: the same golden-brown dog four times in a row, walking straight toward the "
        "viewer, seen from the front, on a transparent background. Repaint only the masked strip at the bottom of "
        "each dog, its front legs and paws, so that the four dogs show one walk cycle, left to right: 1 the left "
        "front paw lifted and reaching forward, the right one down; 2 both front paws down; 3 the right front paw "
        "lifted and reaching forward, the left one down; 4 both front paws down. Every paw that is down stands on "
        "the same ground line as now. Paint them with the same pixel size, fur shading, colors and soft "
        "dark-brown edge as the rest of the dog (no black outline). Keep the face, ears, chest and body exactly "
        "as they are. No ground, no shadow, no text."),
}


def scene_paths(scene):
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    plate = sc.get("plate", scene)
    return sc, plate, ROOT / "assets" / "keyart" / scene / "petsprite", ROOT / "out" / "plates" / plate


def pet_region(scene):
    ov = json.loads((ROOT / "assets" / "keyart" / f"{scene}.masks.json").read_text(encoding="utf-8"))
    return next(r for r in ov["regions"] if r.get("kind") == "pet")


def ref_image(scene):
    """The painted pet on a plain transparent canvas (1024 square), cut out by its SAM mask from the cleaned key art."""
    from cozy.masks import region_raster
    img = Image.open(ROOT / "assets" / "keyart" / scene / "clean.png").convert("RGB")
    W, H = img.size
    m = region_raster(pet_region(scene), W, H) > 0.5
    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    rgba = np.dstack([np.asarray(img), (m * 255).astype(np.uint8)])[y0:y1, x0:x1]
    cut = Image.fromarray(rgba, "RGBA")
    s = 820 / max(cut.size)
    cut = cut.resize((round(cut.width * s), round(cut.height * s)), Image.NEAREST)
    out = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    out.alpha_composite(cut, ((1024 - cut.width) // 2, (1024 - cut.height) // 2))
    return out


def to_palette(rgb, pal_lab):
    lab = cv2.cvtColor(rgb.astype(np.float32)[None] / 255, cv2.COLOR_RGB2LAB)[0]
    d = ((lab[:, None, :] - pal_lab[None, :, :]) ** 2).sum(-1)
    near = pal_lab[d.argmin(1)]
    return np.clip(cv2.cvtColor(near[None].astype(np.float32), cv2.COLOR_LAB2RGB)[0] * 255, 0, 255).round().astype(np.uint8)


def cmd_ref(a):
    _, _, sd, _ = scene_paths(a.scene)
    sd.mkdir(parents=True, exist_ok=True)
    ref_image(a.scene).save(sd / "ref.png")
    print(f"-> {sd / 'ref.png'}")


def cmd_gen(a):
    from azure_ai import edit_image, CFG
    _, _, sd, _ = scene_paths(a.scene)
    sd.mkdir(parents=True, exist_ok=True)
    ref = sd / "ref.png"
    if not ref.exists():
        ref_image(a.scene).save(ref)
    names = a.only.split(",") if a.only else list(SHEETS)
    for name in names:
        prompt = SHEETS[name] + RULES
        res = edit_image(Image.open(ref), prompt, size="1536x1024", quality="high", purpose=f"petsprite:{a.scene}:{name}",
                         background="transparent")
        im = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"])))
        p = sd / f"sheet_{name}.png"
        im.save(p)
        meta = {"sheet": name, "prompt": prompt, "reference": "ref.png (the painted pet cut from clean.png)",
                "deployment": CFG["default_deployment"], "date": datetime.date.today().isoformat(), "usage": res.get("usage"),
                "mode": im.mode}
        p.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
        print(f"{name}: -> {p} ({im.mode} {im.size})")


def anchor_of(al, mode="feet"):
    """Where a frame stands, in its own pixels: the floor row and the body's middle column."""
    ys, xs = np.nonzero(al)
    if mode == "haunch":
        w = al.sum(1)
        row = int(np.nonzero(w >= 0.5 * w.max())[0].max())
        upper = ys < ys.min() + 0.55 * (ys.max() - ys.min())
        return [round(float(xs[upper].mean()), 1), row]
    lower = ys > (ys.min() + ys.max()) / 2
    return [round(float(xs[lower].mean()), 1), int(np.percentile(ys, 99.5))]


def biggest_blob(al):
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(al.astype(np.uint8), np.ones((5, 5), np.uint8)), 8)
    if n > 2:
        al = al & (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])))
    return al


def load_rig(sd):
    p = sd / "rig.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def frame_palette(rgba, k=24):
    """A frame's own colors (k-means in Lab): a derived zone is mapped onto its master's colors."""
    px = rgba[..., :3][rgba[..., 3] > 128].astype(np.float32) / 255
    lab = cv2.cvtColor(px[None], cv2.COLOR_RGB2LAB)[0]
    cv2.setRNGSeed(0)
    _, _, cen = cv2.kmeans(lab.astype(np.float32), min(k, len(lab)), None,
                           (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 0.2), 4, cv2.KMEANS_PP_CENTERS)
    return cen


def cmd_cut(a):
    """petsprite.json for src/library/petsprite.js: the chained poses (posed_<name>.png, posecut) each as a sheet of one
    frame, the cycles drawn from them (pderive_<name>.png, rebuilt on the plate's grid here) and the patches. Every frame
    carries drawn_at (where it was painted, 4K px): petsprite.js shows it there at its own size, and elsewhere scaled by
    the floor's perspective from that row."""
    _, plate, sd, pd = scene_paths(a.scene)
    od = pd / "petsprite"
    rig = load_rig(sd)
    g = Grid(pd, Image.open(pd / "plate.png").size[::-1])
    meta = {"frames": {}}
    for pj in sorted(od.glob("posed_*.json")):
        m = json.loads(pj.read_text(encoding="utf-8"))
        meta["frames"][pj.stem[len("posed_"):]] = [{k: m[k] for k in ("file", "size", "corner", "drawn_at", "anchor",
                                                                       "lit_at", "height", "width")}]
    for name, spec in PDERIVE.items():
        if not (sd / f"pderive_{name}.png").exists():
            continue
        dj = json.loads((sd / f"pderive_{name}.json").read_text(encoding="utf-8"))
        if dj.get("master_file_sha") != file_sha(od / f"posed_{spec['master']}.png"):
            print(f"  ! {name}: its edit was drawn from another cut of {spec['master']}; skipped (pderive --only {name})")
            continue
        meta["frames"][name] = pderived_frames(name, sd, od, rig, g)
    # the door wag (rig.json "wag"): the sitting dog's own tail lying right (the master), pointing back at the camera (the
    # edit's frame `stub`), lying left (the master's lower rows mirrored), pointing back. The edit drew the dog 9% shorter
    # on its canvas, so its tails swept above the zone and came back as stubs; only its straight-back tail is a stub
    wb = rig.get("wag", {}).get("wag_back")
    if wb and "wag_back" in meta["frames"] and "sit_back" in meta["frames"]:
        m = meta["frames"]["sit_back"][0]
        L, Lc = mirror_cells(np.asarray(Image.open(od / m["file"]).convert("RGBA")), m["corner"], g, wb["row"], wb["col"])
        Image.fromarray(L, "RGBA").save(od / "d_wag_back_left.png")
        yy, xx = np.nonzero(L[..., 3] > 127)
        left = {"file": "d_wag_back_left.png", "size": [L.shape[1], L.shape[0]], "corner": Lc, "drawn_at": m["drawn_at"],
                "anchor": [round(m["drawn_at"][0] - Lc[0], 3), round(m["drawn_at"][1] - Lc[1], 3)], "lit_at": m["lit_at"],
                "height": int(yy.max() - yy.min() + 1), "width": int(xx.max() - xx.min() + 1), "derived": True}
        stub = meta["frames"]["wag_back"][wb["stub"]]
        meta["frames"]["wag_back"] = [dict(m), stub, left, stub]
    for pj in sorted(sd.glob("patch_*.json")):
        meta[pj.stem[len("patch_"):]] = json.loads(pj.read_text(encoding="utf-8"))["placed"]
    # the door sit's outline one cell thick (rig.json "thin": the sheets cut out of ground the model repainted dark; never
    # the chained poses, whose edge is the painted dog's own), then each frame's mean color in linear light (petsprite.js
    # shades the walkers toward the door with it)
    for name, fr in meta["frames"].items():
        if name not in rig.get("thin", []):
            continue
        n = 0
        for f in fr:
            im = np.asarray(Image.open(od / f["file"]).convert("RGBA"))
            th, k = thin_edge(im, f["corner"], g)
            if k:
                n += k
                f["file"] = f["file"] if f["file"].startswith("d_") else "t_" + f["file"]
                Image.fromarray(th, "RGBA").save(od / f["file"])
        if n:
            print(f"  {name}: {n} doubled edge cells dropped")
    for fr in meta["frames"].values():
        for f in fr:
            im = np.asarray(Image.open(od / f["file"]).convert("RGBA")).astype(np.float32) / 255
            c = im[..., :3][im[..., 3] > 0.5]
            f["lin_mean"] = [round(float(v), 5) for v in np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).mean(0)]
    (od / "petsprite.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print(f"frames: {', '.join(f'{k} {len(v)}' for k, v in meta['frames'].items())} -> {od / 'petsprite.json'}")


def file_sha(p):
    import hashlib
    return hashlib.sha1(pathlib.Path(p).read_bytes()).hexdigest()[:16]


def plate_grid(pd):
    pj = json.loads((pd / "plate.json").read_text(encoding="utf-8"))
    return float(pj["pixel"]["cell"]), pj["pixel"]["origin"]


def cell_edges(lo, hi, cell, o):
    """The plate grid's cell boundaries (4K px, integers) covering [lo, hi)."""
    k0, k1 = int(np.floor((lo - o) / cell)) - 1, int(np.ceil((hi - o) / cell)) + 1
    return np.round(o + np.arange(k0, k1 + 1) * cell).astype(int)


def base_plate(pd, sd, meta, base):
    """The 4K plate the dog is repainted over: as painted, or with the empty mat where the painted dog lies."""
    P = np.asarray(Image.open(pd / "plate.png").convert("RGB")).copy()
    if base == "empty" and meta.get("empty"):
        pl = meta["empty"]
        patch = np.asarray(Image.open(sd / pl["file"]).convert("RGBA"))
        reg = P[pl["y"]:pl["y"] + pl["h"], pl["x"]:pl["x"] + pl["w"]]
        m = patch[..., 3] > 127
        reg[m] = patch[..., :3][m]
    return P


def spread_points(m, n):
    """n points spread over a mask (the one nearest its middle, then each farthest from those before)."""
    ys, xs = np.nonzero(m)
    if not len(xs):
        return []
    pts = np.stack([xs, ys], 1).astype(np.float32)
    idx = [int(np.argmin(((pts - pts.mean(0)) ** 2).sum(1)))]
    d = ((pts - pts[idx[0]]) ** 2).sum(1)
    for _ in range(n - 1):
        j = int(np.argmax(d))
        idx.append(j)
        d = np.minimum(d, ((pts - pts[j]) ** 2).sum(1))
    return [[float(pts[j][0]), float(pts[j][1])] for j in idx]


def fill_holes(m):
    inv = (~m).astype(np.uint8)
    ff = inv.copy()
    h, w = m.shape
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 2)
    return m | (ff == 1)


def lab(rgb):
    return cv2.cvtColor(rgb.astype(np.float32) / 255, cv2.COLOR_RGB2LAB)


def to_cells(m, X0, Y0, cell, ox, oy):
    """A mask (window px, window corner at X0, Y0 in 4K) made whole cells: a cell is in where most of it is."""
    h, w = m.shape
    out = np.zeros_like(m)
    xs, ys = cell_edges(X0, X0 + w, cell, ox), cell_edges(Y0, Y0 + h, cell, oy)
    for ya, yb in zip(ys[:-1], ys[1:]):
        for xa, xb in zip(xs[:-1], xs[1:]):
            sl = (slice(max(0, ya - Y0), max(0, yb - Y0)), slice(max(0, xa - X0), max(0, xb - X0)))
            blk = m[sl]
            if blk.size and blk.mean() > 0.5:
                out[sl] = True
    return out


def align_to(inp, out):
    """The edit warped back onto its input (both RGB, the same size): the image model now and then moves the whole
    picture (the standing dog's repaint came back 47 px to the left, so the dog left its anchor and the ground beside it
    no longer matched the plate). ECC, affine, on gray; returns the aligned edit and the warp."""
    A = cv2.cvtColor(inp, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    B = cv2.cvtColor(out, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(A, B, warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    except cv2.error:
        return out, None
    w = [round(float(v), 4) for v in warp.ravel()]
    if abs(warp[0, 2]) < 0.75 and abs(warp[1, 2]) < 0.75 and np.abs(warp[:, :2] - np.eye(2)).max() < 2e-3:
        return out, w
    return cv2.warpAffine(out, warp, (out.shape[1], out.shape[0]), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE), w


PATCHES = {
    "awake": {"mask": "head", "prompt": (
        "This is a 16-bit pixel-art greenhouse. Repaint only the masked area around the sleeping golden-brown dog's head: "
        "the dog wakes up and lifts its head up from its paws, eyes open, ears up a little, looking toward the right, "
        "calm and curious. Its body, front paws, back and tail stay exactly as they are, curled on the woven mat. Same "
        "pixel-art style, pixel size, colors and warm lantern light as the rest of the picture. Nothing else changes.")},
    "empty": {"mask": "empty", "prompt": (
        "This is a 16-bit pixel-art greenhouse. Repaint only the masked area: the dog is gone, and the empty woven mat it "
        "was lying on shows there, continuing the mat's pattern, border and colors, with the brick floor around it as "
        "before. Same pixel-art style, pixel size and warm light. No animal, no blanket, no objects, nothing new.")},
    # the in-betweens of waking (round 4: asleep to awake was a little too abrupt): eyes open first, then the head
    # halfway up, turning toward where the awake patch looks
    "drowsy": {"mask": "eyes", "prompt": (
        "This is a 16-bit pixel-art greenhouse. Repaint only the masked area, the sleeping golden-brown dog's closed eyes: "
        "its eyes are now open halfway, sleepy, looking straight ahead. Its head stays resting on its paws exactly as it "
        "is, the same face, fur and colors. Same pixel-art style and pixel size. Nothing else changes.")},
    "half": {"mask": "head", "base": "awake", "prompt": (
        "This is a 16-bit pixel-art greenhouse with a golden-brown dog on a woven mat, its head up. Repaint only the "
        "masked area: the dog lowers its head halfway back toward its front paws, its chin a little above them, eyes "
        "open and sleepy, still facing toward the right. The top of its head ends well below where it is now; where the "
        "head was, the wooden wall and the floor behind it continue as they are around it. Its body, back and tail stay "
        "exactly as they are, curled on the woven mat. Same pixel-art style, pixel size, colors and warm lantern light "
        "as the rest of the picture. Nothing else changes.")},
}


def cmd_patches(a):
    """The painted pet awake (its head lifted) and the empty mat, as patches on the plate's own grid: masked edits of the
    cleaned key art, upscaled and rebuilt on the plate's pixel grid; every cell outside the edit is the plate's own,
    so the patch cannot show a seam."""
    from azure_ai import edit_image, CFG
    from cozy.masks import region_raster, pixelize
    sc, plate, sd, pd = scene_paths(a.scene)
    sd.mkdir(parents=True, exist_ok=True)
    img = Image.open(ROOT / "assets" / "keyart" / a.scene / "clean.png").convert("RGB")
    W, H = img.size
    pet = region_raster(pet_region(a.scene), W, H) > 0.5
    ys, xs = np.nonzero(pet)
    bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    names = a.only.split(",") if a.only else list(PATCHES)
    pj = json.loads((pd / "plate.json").read_text(encoding="utf-8"))
    cell, (ox, oy) = float(pj["pixel"]["cell"]), pj["pixel"]["origin"]
    P4 = np.asarray(Image.open(pd / "plate.png").convert("RGB"))
    H4, W4 = P4.shape[:2]
    k4 = W4 / W
    for name in names:
        spec = PATCHES[name]
        m = np.zeros((H, W), bool)
        if spec["mask"] == "empty":
            m = cv2.dilate(pet.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        elif spec["mask"] == "eyes":
            ex0, ey0, ex1, ey1 = load_rig(sd)["eyes"]
            m[int(ey0 * H):int(ey1 * H) + 1, int(ex0 * W):int(ex1 * W) + 1] = True
        else:
            # the head (the pet's still boxes from hand.json, the first is the head) and room above it to lift into
            hand = json.loads((ROOT / "assets" / "keyart" / f"{a.scene}.hand.json").read_text(encoding="utf-8"))
            hx0, hy0, hx1, hy1 = hand["pet_still"][0]
            hb = [int(hx0 * W) - 10, int(hy0 * H) - int(spec.get("raise", 0.06) * H), int(hx1 * W) + 14, int(hy1 * H) + 4]
            m[max(0, hb[1]):hb[3], max(0, hb[0]):hb[2]] = True
        mx0, my0 = max(0, min(bx0, np.nonzero(m.any(0))[0].min()) - 60), max(0, min(by0, np.nonzero(m.any(1))[0].min()) - 60)
        mx1, my1 = min(W, max(bx1, np.nonzero(m.any(0))[0].max()) + 60), min(H, max(by1, np.nonzero(m.any(1))[0].max()) + 60)
        # an edit window of a supported size around it
        tw, th = 1024, 1024
        cx, cy = (mx0 + mx1) // 2, (my0 + my1) // 2
        tx, ty = min(max(0, cx - tw // 2), W - tw), min(max(0, cy - th // 2), H - th)
        crop = img.crop((tx, ty, tx + tw, ty + th))
        base = None
        if spec.get("base"):
            # an in-between drawn from the pose it leads into: asked to lift the sleeping head halfway, the edit lifted it
            # all the way (round 4); asked to lower the awake head halfway, it keeps that head's look
            bj = json.loads((sd / f"patch_{spec['base']}.json").read_text(encoding="utf-8"))
            if bj["window"][:2] != [int(tx), int(ty)]:
                sys.exit(f"{name}: its base {spec['base']} was edited in another window {bj['window']}")
            base = f"patch_{spec['base']}_edit.png"
            crop = Image.open(pd / "petsprite" / base).convert("RGB")
        mm = m[ty:ty + th, tx:tx + tw]
        rgba = np.zeros((th, tw, 4), np.uint8)
        rgba[..., 3] = np.where(mm, 0, 255)
        refs = []
        ref_edit = pd / "petsprite" / f"patch_{spec.get('ref')}_edit.png"
        if spec.get("ref") and ref_edit.exists():
            rj = json.loads((sd / f"patch_{spec['ref']}.json").read_text(encoding="utf-8"))
            if rj["window"][:2] == [int(tx), int(ty)]:
                refs.append(Image.open(ref_edit).convert("RGB"))
        res = edit_image(crop, spec["prompt"], mask=Image.fromarray(rgba, "RGBA"), size=f"{tw}x{th}", quality="high",
                         purpose=f"petsprite:{a.scene}:patch_{name}", images=refs)
        out = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGB")
        if out.size != (tw, th):
            out = out.resize((tw, th), Image.LANCZOS)
        ed = np.asarray(img).copy()
        win = ed[ty:ty + th, tx:tx + tw]
        win[mm] = np.asarray(out)[mm]
        (pd / "petsprite").mkdir(parents=True, exist_ok=True)
        Image.fromarray(ed[ty:ty + th, tx:tx + tw]).save(pd / "petsprite" / f"patch_{name}_edit.png")   # the edit window (not a source)
        # on the plate's grid: the edited window upscaled to 4K and rebuilt cell by cell; cells whose center lies in
        # the edit take it, the rest stay the plate's
        X0, Y0, X1, Y1 = int(tx * k4), int(ty * k4), int((tx + tw) * k4), int((ty + th) * k4)
        up = Image.fromarray(ed[ty:ty + th, tx:tx + tw]).resize((X1 - X0, Y1 - Y0), Image.LANCZOS)
        pix = np.asarray(pixelize(up, cell, (ox - X0) % cell, (oy - Y0) % cell))
        m4 = cv2.resize(mm.astype(np.uint8), (X1 - X0, Y1 - Y0), interpolation=cv2.INTER_NEAREST) > 0
        m4 = cv2.dilate(m4.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        xs_ = np.round(ox + np.arange(int((X0 - ox) // cell) - 1, int((X1 - ox) // cell) + 2) * cell).astype(int)
        ys_ = np.round(oy + np.arange(int((Y0 - oy) // cell) - 1, int((Y1 - oy) // cell) + 2) * cell).astype(int)
        res4 = P4[Y0:Y1, X0:X1].copy()
        alpha = np.zeros((Y1 - Y0, X1 - X0), np.uint8)
        for ya, yb in zip(ys_[:-1], ys_[1:]):
            for xa, xb in zip(xs_[:-1], xs_[1:]):
                ccx, ccy = (xa + xb) // 2 - X0, (ya + yb) // 2 - Y0
                if 0 <= ccx < X1 - X0 and 0 <= ccy < Y1 - Y0 and m4[ccy, ccx]:
                    sl = (slice(max(0, ya - Y0), max(0, yb - Y0)), slice(max(0, xa - X0), max(0, xb - X0)))
                    res4[sl] = pix[sl]
                    alpha[sl] = 255
        ys4, xs4 = np.nonzero(alpha)
        qx0, qy0, qx1, qy1 = xs4.min(), ys4.min(), xs4.max() + 1, ys4.max() + 1
        patch = np.dstack([res4, alpha])[qy0:qy1, qx0:qx1]
        Image.fromarray(patch, "RGBA").save(sd / f"patch_{name}.png")
        placed = {"file": f"patch_{name}.png", "x": int(X0 + qx0), "y": int(Y0 + qy0), "w": int(qx1 - qx0), "h": int(qy1 - qy0)}
        meta = {"patch": name, "prompt": spec["prompt"], "mask": spec["mask"], "window": [int(tx), int(ty), tw, th],
                "references": [f"patch_{spec['ref']}_edit.png (the {spec['ref']} edit window)"] if refs else [],
                "base": f"{base} (the edit window of the {spec['base']} patch, edited)" if base else None,
                "deployment": CFG["default_deployment"], "date": datetime.date.today().isoformat(), "usage": res.get("usage"),
                "placed": placed}
        (sd / f"patch_{name}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
        print(f"{name}: -> {sd / ('patch_' + name + '.png')} at {placed}")


# Round 6 (his crops of the painted dog awake and the restyled dog lying a moment later showed the dog changing style
# between frames, which it must never do). A pose repainted on its own came out another dog
# however it was asked; so did a sit repainted from the awake picture with its whole front half masked (an adult
# retriever with a longer face, a third bigger). The drowsy, half and awake patches never did: each was the picture
# before it with only what moves repainted. So the poses are a chain on the plate's own grid, and what makes it this dog
# is never repainted: the painted head is moved as whole cells (rig.json "move"), the rump stays, and the image model
# paints only what joins them (the neck, chest and front legs of the sit; the hind half of the stand). The back and
# front views are painted into the same picture as the standing dog. rig.json "poses": each edit's 4K window (x, y on
# multiples of 3, w and h 1.5 times an edit size), its mask (boxes, polys) and its move (poly, by: cells), in key-art px.
JOIN = ("in the same fluffy golden fur with the same small shades and warm highlights as its head and rump, its edge the "
        "same soft dark brown, the same pixel size as the rest of the picture and lit by the same warm light")
POSES = {
    "sit": {"base": "awake", "prompt": (
        "This is a 16-bit pixel-art greenhouse. A golden-brown puppy sits up on a woven mat facing right: its head is held "
        "up and its rump and hind leg rest on the mat, but the rest of its body is missing. Repaint only the masked area: "
        "paint the rest of this same puppy, sitting upright and joining its head to its rump: its neck under its head, its "
        "chest, its two front legs straight down with the front paws on the mat, and its back curving down from the "
        f"shoulders to the rump, {JOIN}. Its head and rump stay exactly as they are. Around it the wooden wall, the raised "
        "bed and the woven mat continue as they are. Nothing else changes.")},
    "rise": {"base": "awake", "prompt": (
        "This is a 16-bit pixel-art greenhouse. A golden-brown puppy on a woven mat facing right is getting up: its head is "
        "lifted and its rump and hind leg rest on the mat, but the rest of its body is missing. Repaint only the masked "
        "area: paint the rest of this same puppy halfway between lying and sitting, pushing itself up: its neck under its "
        "head, its chest raised off the mat, its front legs half straightened with the front paws on the mat, its back "
        f"rising from the rump to the shoulders, {JOIN}. Its head and rump stay exactly as they are. Around it the wooden "
        "wall, the raised bed and the woven mat continue as they are. Nothing else changes.")},
    "stand": {"base": "sit", "prompt": (
        "This is a 16-bit pixel-art greenhouse. A golden-brown puppy faces right on a woven mat: its head, chest and front "
        "legs are there, but the back half of its body is missing. Repaint only the masked area: paint the rest of this "
        "same puppy standing up on all four legs: its back level from the shoulders to the rump, its belly, its two hind "
        f"legs straight down with the hind paws on the mat, and its tail hanging down relaxed behind, {JOIN.replace('head and rump', 'head and chest')}. "
        "Its head, chest and front legs stay exactly as they are. Under its belly and behind it the woven mat, the floor "
        "and the wall continue as they are. Nothing else changes.")},
    # the back and front views, painted into the picture beside the standing dog (left unmasked: the model's reference
    # in the same picture), all three in one edit so they are drawn as one dog
    "views": {"base": "stand", "prompt": (
        "This is a 16-bit pixel-art greenhouse with a golden-brown puppy standing on a woven mat at the left. Paint this "
        "same puppy three more times, once in each masked area, as if the picture showed it at three moments. In the "
        "masked area on the brick floor just right of the mat: walking straight away from the viewer, seen from behind: "
        "the back of its head and its two floppy ears, its back, its rump with its fluffy tail held up, and its hind legs, "
        "one paw lifted. In the masked area on the brick floor further right: walking straight toward the viewer, seen "
        "from the front: its face looking ahead with the same eyes and nose, its floppy ears, its chest and its two front "
        "legs, one paw lifted. In the small masked area far back: sitting on the brick floor in front of the glass door, "
        "seen from behind, looking out through the glass: the back of its head and its two floppy ears, its back and its "
        "haunches on the floor, its fluffy tail lying on the floor behind it. Each is exactly the same puppy as the one "
        "standing on the mat: the same round head, the same golden fur with the same small shades and warm highlights, "
        "the same soft dark-brown edge, the same proportions and the same pixel size as the rest of the picture. The two "
        "on the floor are as big as the one on the mat; the one at the door is smaller because it is far away. Each is lit "
        "by the light where it is. Around them the floor, the beds, the door and the plants continue as they are. "
        "Nothing else changes.")},
}


def keyart(scene):
    return np.asarray(Image.open(ROOT / "assets" / "keyart" / scene / "clean.png").convert("RGB"))


class Grid:
    """The plate's pixel grid. The plate is exactly one color per cell, so a picture is held as one color per cell, a
    pose is built from whole cells and a move is an exact shift (nothing is resampled)."""
    def __init__(self, pd, shape):
        self.cell, (self.ox, self.oy) = plate_grid(pd)
        self.H, self.W = shape[:2]
        self.xs = np.unique(np.clip(cell_edges(0, self.W, self.cell, self.ox), 0, self.W))
        self.ys = np.unique(np.clip(cell_edges(0, self.H, self.cell, self.oy), 0, self.H))
        self.cx = ((self.xs[:-1] + self.xs[1:]) // 2).clip(0, self.W - 1)
        self.cy = ((self.ys[:-1] + self.ys[1:]) // 2).clip(0, self.H - 1)

    def cells(self, img):
        return img[np.ix_(self.cy, self.cx)]

    def raster(self, c):
        return np.repeat(np.repeat(c, np.diff(self.ys), axis=0), np.diff(self.xs), axis=1)

    def mask(self, c):
        return self.raster(c.astype(np.uint8)[..., None])[..., 0] > 0


def chain_ctx(scene):
    _, plate, sd, pd = scene_paths(scene)
    od = pd / "petsprite"
    meta = json.loads((od / "petsprite.json").read_text(encoding="utf-8"))
    P4 = np.asarray(Image.open(pd / "plate.png").convert("RGB"))
    g = Grid(pd, P4.shape)
    PA = P4.copy()
    aw = meta["awake"]
    patch = np.asarray(Image.open(sd / aw["file"]).convert("RGBA"))
    reg = PA[aw["y"]:aw["y"] + aw["h"], aw["x"]:aw["x"] + aw["w"]]
    reg[patch[..., 3] > 127] = patch[..., :3][patch[..., 3] > 127]
    return {"scene": scene, "sd": sd, "pd": pd, "od": od, "meta": meta, "g": g, "rig": load_rig(sd),
            "k4": P4.shape[1] / keyart(scene).shape[1], "A": g.cells(PA), "B": g.cells(base_plate(pd, sd, meta, "empty"))}


def key_mask(cx, spec, key=("boxes", "polys")):
    """Boxes and polygons in key-art px, as cells (a cell is in where its center is)."""
    g, k = cx["g"], cx["k4"]
    m = np.zeros((g.H, g.W), np.uint8)
    for x0, y0, x1, y1 in spec.get(key[0], []):
        m[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] = 1
    for poly in spec.get(key[1], []):
        cv2.fillPoly(m, [np.round(np.array(poly, np.float32) * k).astype(np.int32)], 1)
    return g.cells(m) > 0


def unwarp(raw, warp):
    """A saved edit put back onto its input with the warp align_to measured (only when align_to applied it)."""
    if not warp:
        return raw
    w = np.array(warp, np.float32).reshape(2, 3)
    if abs(w[0, 2]) < 0.75 and abs(w[1, 2]) < 0.75 and np.abs(w[:, :2] - np.eye(2)).max() < 2e-3:
        return raw
    return cv2.warpAffine(raw, w, (raw.shape[1], raw.shape[0]), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def apply_move(cx, j, C, src=None):
    """The pose before with its head carried by whole cells (rig.json move: the cells, by [kx, ky]); returns the colors
    and the cells it landed on."""
    dest = np.zeros(C.shape[:2], bool)
    mv = j.get("move")
    if not mv:
        return C, dest
    if src is None:
        src = np.asarray(Image.open(cx["sd"] / mv["cells"]).convert("L")) > 127
    kx, ky = mv["by"]
    ys, xs = np.nonzero(src)
    C2 = C.copy()
    C2[ys + ky, xs + kx] = C[ys, xs]
    dest[ys + ky, xs + kx] = True
    return C2, dest


def win_size(cx, j):
    X, Y, w4, h4 = j["window4"]
    return X, Y, w4, h4, round(w4 / cx["k4"]), round(h4 / cx["k4"])


def edit_input(cx, j, C, dest):
    """The edit's input at the key art's scale (the window) with the mask filled with the plate without the dog (what
    the model paints into reads as a gap, not as the old pose under it), and its mask (True where it may paint)."""
    g = cx["g"]
    M = key_mask(cx, j) & ~dest
    Cin = C.copy()
    Cin[M] = cx["B"][M]
    X, Y, w4, h4, w, h = win_size(cx, j)
    small = cv2.resize(g.raster(Cin)[Y:Y + h4, X:X + w4], (w, h), interpolation=cv2.INTER_AREA)
    mk = cv2.resize(g.mask(M)[Y:Y + h4, X:X + w4].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
    return small, mk


def edit_cells(cx, j, raw):
    """The model's edit as cells: upscaled to 4K and rebuilt on the plate's grid (the patches' way)."""
    from cozy.masks import pixelize
    g = cx["g"]
    X, Y, w4, h4, w, h = win_size(cx, j)
    if raw.shape[:2] != (h, w):
        raw = cv2.resize(raw, (w, h), interpolation=cv2.INTER_LANCZOS4)
    up = cv2.resize(unwarp(raw, j.get("warp")), (w4, h4), interpolation=cv2.INTER_LANCZOS4)
    full = np.zeros((g.H, g.W, 3), np.uint8)
    full[Y:Y + h4, X:X + w4] = np.asarray(pixelize(Image.fromarray(up), g.cell, (g.ox - X) % g.cell, (g.oy - Y) % g.cell))
    return g.cells(full)


def pose_cells(cx, name):
    """A pose as cells, rebuilt from the committed edits: (colors, the cells the chain moved or repainted, the cells the
    image model painted)."""
    if name == "awake":
        z = np.zeros(cx["A"].shape[:2], bool)
        return cx["A"].copy(), z, z.copy()
    j = json.loads((cx["sd"] / f"pose_{name}.json").read_text(encoding="utf-8"))
    C, ch, pt = pose_cells(cx, j["base"])
    C, dest = apply_move(cx, j, C)
    M = key_mask(cx, j) & ~dest
    out = edit_cells(cx, j, np.asarray(Image.open(cx["sd"] / f"pose_{name}.png").convert("RGB")))
    C[M] = out[M]
    return C, ch | M | dest, (pt & ~dest & ~M) | M


def head_cells(cx, C, poly):
    """The cells a move carries: the dog inside the polygon (SAM on the pose before, prompted with the polygon's box,
    points where it differs from the plate without the dog and points where it does not)."""
    from cozy.segment import Segmenter
    g, k = cx["g"], cx["k4"]
    P = np.round(np.array(poly, np.float32) * k).astype(np.int32)
    pad = int(4 * g.cell)
    x0, y0 = np.maximum(P.min(0) - pad, 0)
    x1, y1 = P.max(0) + pad
    img = g.raster(C)[y0:y1, x0:x1]
    pm = np.zeros((g.H, g.W), np.uint8)
    cv2.fillPoly(pm, [P], 1)
    pm = pm[y0:y1, x0:x1] > 0
    dE = np.linalg.norm(lab(img) - lab(g.raster(cx["B"])[y0:y1, x0:x1]), axis=2)
    kk = int(np.ceil(g.cell)) * 2 + 1
    sure = (cv2.erode((pm & (dE > 25)).astype(np.uint8), np.ones((kk, kk), np.uint8)) > 0)
    ref = fill_holes(biggest_blob(pm & (dE > 12)))
    pos = spread_points(sure, 6)
    neg = spread_points(~(cv2.dilate(ref.astype(np.uint8), np.ones((kk, kk), np.uint8)) > 0) & (dE < 4), 6)
    box = [float(P[:, 0].min() - x0), float(P[:, 1].min() - y0), float(P[:, 0].max() - x0), float(P[:, 1].max() - y0)]
    best, bi = None, -1.0
    for m, _ in Segmenter().prompt_candidates(Image.fromarray(img), box, pos + neg, [1] * len(pos) + [0] * len(neg)):
        m = m & pm
        iou = (m & ref).sum() / max(1, (m | ref).sum())
        if iou > bi:
            best, bi = m, float(iou)
    # SAM leaves out dark cells now and then (the eye, the nose against the dark wall): what lies inside it and the cells
    # at its edge that still differ from the plate without the dog go too (a cell left behind would be repainted)
    best = fill_holes(best)
    ring = (cv2.dilate(best.astype(np.uint8), np.ones((kk, kk), np.uint8)) > 0) & pm & (dE > 10)
    best = fill_holes(best | ring)
    full = np.zeros((g.H, g.W), bool)
    full[y0:y1, x0:x1] = best
    print(f"  the head: SAM IoU with what differs from the empty mat {bi:.2f}")
    return fill_holes(g.cells(full))


def cmd_pose(a):
    """One pose of the chain: the pose before it (POSES base) with its head carried by whole cells (rig.json move) and the
    mask repainted by one image edit (the mask filled with the plate without the dog first) -> pose_<name>.png (+ .json:
    prompt, base, window, mask, move, warp, usage; pose_<name>_move.png the head's cells). --dry writes
    pose_<name>_dry.png (the edit's input, the mask tinted, the moved head outlined) and spends nothing: look at it first."""
    cx = chain_ctx(a.scene)
    g, sd, od = cx["g"], cx["sd"], cx["od"]
    spec, hand = POSES[a.name], cx["rig"]["poses"][a.name]
    C, _, _ = pose_cells(cx, spec["base"])
    j = {"pose": a.name, "base": spec["base"], "prompt": spec["prompt"], "window4": hand["window4"],
         **{k: hand[k] for k in ("boxes", "polys") if k in hand}}
    src = None
    if hand.get("move"):
        src = head_cells(cx, C, hand["move"]["poly"])
        j["move"] = {"poly": hand["move"]["poly"], "by": hand["move"]["by"], "cells": f"pose_{a.name}_move.png"}
    C2, dest = apply_move(cx, j, C, src)
    M = key_mask(cx, j) & ~dest
    if j.get("move"):
        left = src & ~dest & ~M
        if left.any():
            print(f"  ! {int(left.sum())} cells the head left are outside the mask: they would keep the old head")
    small, mk = edit_input(cx, j, C2, dest)
    X, Y, w4, h4, w, h = win_size(cx, j)
    if a.dry:
        prev = g.raster(C2)[Y:Y + h4, X:X + w4].astype(np.float32)
        Mm = g.mask(M)[Y:Y + h4, X:X + w4]
        prev[Mm] = g.raster(cx["B"])[Y:Y + h4, X:X + w4][Mm] * 0.6 + np.array([255, 0, 170], np.float32) * 0.4
        D = g.mask(dest)[Y:Y + h4, X:X + w4]
        prev[D & ~(cv2.erode(D.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)] = [0, 255, 255]
        Image.fromarray(prev.clip(0, 255).astype(np.uint8)).save(od / f"pose_{a.name}_dry.png")
        Image.fromarray(small).save(od / f"pose_{a.name}_input.png")
        print(f"-> {od / f'pose_{a.name}_dry.png'} (4K window {j['window4']}, mask {int(M.sum())} cells, head "
              f"{int(dest.sum())} cells; the edit's input {od / f'pose_{a.name}_input.png'}; nothing spent)")
        return
    from azure_ai import edit_image, CFG
    if src is not None:   # the head's cells, a source of the pose (written only with the edit it belongs to)
        Image.fromarray((src * 255).astype(np.uint8)).save(sd / f"pose_{a.name}_move.png")
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 3] = np.where(mk, 0, 255)
    res = edit_image(Image.fromarray(small), spec["prompt"], mask=Image.fromarray(rgba, "RGBA"), size=f"{w}x{h}",
                     quality="high", purpose=f"petsprite:{a.scene}:pose_{a.name}")
    out = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGB")
    out.save(sd / f"pose_{a.name}.png")
    _, warp = align_to(small, np.asarray(out.resize((w, h), Image.LANCZOS)))
    j.update({"warp": warp, "deployment": CFG["default_deployment"], "date": datetime.date.today().isoformat(),
              "usage": res.get("usage")})
    (sd / f"pose_{a.name}.json").write_text(json.dumps(j, indent=1), encoding="utf-8", newline="\n")
    C3, _, _ = pose_cells(cx, a.name)
    Image.fromarray(g.raster(C3)[Y:Y + h4, X:X + w4]).save(od / f"pose_{a.name}_edit.png")
    moved = f", the edit moved {warp[2]:+.1f},{warp[5]:+.1f} px and was put back" if warp and max(abs(warp[2]), abs(warp[5])) >= 0.75 else ""
    print(f"{a.name}: -> {sd / f'pose_{a.name}.png'}; the pose on the plate's grid: {od / f'pose_{a.name}_edit.png'}{moved}")


def dog_palette(cx, k=20):
    """The painted dog's own colors (the awake dog's cells, k-means in Lab): a painted cell is mapped onto them."""
    from cozy.masks import region_raster
    g = cx["g"]
    K = keyart(cx["scene"])
    pet = cv2.resize((region_raster(pet_region(cx["scene"]), K.shape[1], K.shape[0]) > 0.5).astype(np.uint8),
                     (g.W, g.H), interpolation=cv2.INTER_NEAREST) > 0
    aw = cx["meta"]["awake"]
    pet[aw["y"]:aw["y"] + aw["h"], aw["x"]:aw["x"] + aw["w"]] = True
    dE = np.linalg.norm(lab(cx["A"]) - lab(cx["B"]), axis=2)
    sel = g.cells(pet.astype(np.uint8)) > 0
    px = cx["A"][sel & (dE > 20)].astype(np.float32) / 255
    L = cv2.cvtColor(px[None], cv2.COLOR_RGB2LAB)[0]
    cv2.setRNGSeed(0)
    return cv2.kmeans(L.astype(np.float32), k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 0.2), 4,
                      cv2.KMEANS_PP_CENTERS)[2]


def chain_cutout(seg, E, B, grow, cell, pal=None):
    """A chained pose's dog (bool, window px): where the pose differs from the plate without the dog (B), refined by SAM
    (a box around it, points on it and on what clearly is not it), inside `grow`. With `pal` (rig.json dogs "seed":
    "fur") only what differs in the painted dog's fur colors seeds it: where the model repainted the ground around a new
    dog (the door sit: the door's lower panel came back darker, and all of it differed from the plate). Not for a
    chained pose: its dark shading lines split the fur into pieces and the seed kept only one (the rise). No color rules
    on the edge: the dog's soft dark-brown edge is its own
    and against the dark wall and mat it differs little from them (dog_cutout's rules for repainted frames took the nose
    tip and the line under the rump off the sit)."""
    H, W = E.shape[:2]
    dE = np.linalg.norm(lab(E) - lab(B), axis=2)
    if pal is not None:
        fur = pal[pal[:, 0] > 35]   # the fur's colors: the dark edge's are as dark as the panels and mats around
        dpal = np.min(np.linalg.norm(lab(E)[..., None, :] - fur[None, None], axis=3), axis=2)
    else:
        dpal = np.zeros(E.shape[:2], np.float32)
    kc = int(np.ceil(cell)) | 1
    k2 = int(np.ceil(cell)) * 2 + 1
    chg = cv2.morphologyEx(((dE > 22) & (dpal < 12) & grow).astype(np.uint8), cv2.MORPH_OPEN, np.ones((kc, kc), np.uint8)) > 0
    prior = fill_holes(biggest_blob(chg))
    ys, xs = np.nonzero(prior)
    pad = int(3 * cell)
    box = [max(0, xs.min() - pad), max(0, ys.min() - pad), min(W - 1, xs.max() + pad), min(H - 1, ys.max() + pad)]
    core = cv2.erode(prior.astype(np.uint8), np.ones((k2, k2), np.uint8)) > 0
    pos = spread_points(core & (dE > 30), 8)
    inbox = np.zeros_like(prior)
    inbox[box[1]:box[3], box[0]:box[2]] = True
    far = ~(cv2.dilate(prior.astype(np.uint8), np.ones((k2, k2), np.uint8)) > 0)
    neg = spread_points(far & inbox & ((dE < 4) | (dpal > 25)), 10 if pal is not None else 8)
    cands = []
    for m, sc in seg.prompt_candidates(Image.fromarray(E), box, pos + neg, [1] * len(pos) + [0] * len(neg)):
        m = m & grow
        cands.append((float((m & prior).sum() / max(1, (m | prior).sum())), sc, m))
    # the candidate nearest what changed; of near ties SAM's own best (the sit: 0.788 with flecks of floor, 0.787 clean
    # at SAM 0.95). What changed itself is not added: it holds the floor line the model redrew beside the chest
    top = max(c[0] for c in cands)
    bi, _, best = max((c for c in cands if c[0] >= top - 0.03), key=lambda c: c[1])
    if bi < 0.6:
        print(f"  ! SAM found no dog matching what changed (IoU {bi:.2f}): what changed is used")
        best = prior
    # SAM leaves the darkest edge cells out (the black nose tip, the dark line under the rump and paws): a cell around
    # its mask that is as dark as the dog's edge and differs from the plate without the dog goes back in
    best = fill_holes(best)
    Lw = lab(E)[..., 0]
    k1 = int(np.ceil(cell)) * 2 + 1
    ring = (cv2.dilate(best.astype(np.uint8), np.ones((k1, k1), np.uint8)) > 0) & ~best
    edge = ring & grow & (dE > 6) & (Lw < 0.6 * np.median(Lw[core & best]))
    return fill_holes(best | edge), bi


def cmd_posecut(a):
    """A pose's dog(s) cut out on the plate's grid -> posed_<name>.png (+ .json: drawn_at, the feet in 4K px where it was
    painted, on a grid point; anchor, the same point in the frame's px; lit_at). The dog is what the chain changed or kept
    of the painted dog and differs from the plate without the dog, refined by SAM, whole cells; never clipped at the
    floor (round 6: the sitting dog at the door had its haunches and tail cut at the floor row, which looked
    wrong). The cells the image model painted are mapped onto the painted dog's own colors."""
    from cozy.segment import Segmenter
    from cozy.masks import region_raster
    cx = chain_ctx(a.scene)
    g, od = cx["g"], cx["od"]
    j = json.loads((cx["sd"] / f"pose_{a.name}.json").read_text(encoding="utf-8"))
    hand = cx["rig"]["poses"].get(a.name, {})
    C, ch, pt = pose_cells(cx, a.name)
    pal = dog_palette(cx)
    X, Y, w4, h4, _, _ = win_size(cx, j)
    E = g.raster(C)[Y:Y + h4, X:X + w4]
    B = g.raster(cx["B"])[Y:Y + h4, X:X + w4]
    chw = g.mask(ch)[Y:Y + h4, X:X + w4]
    ptw = g.mask(pt)[Y:Y + h4, X:X + w4]
    K = keyart(a.scene)
    pet = (cv2.resize((region_raster(pet_region(a.scene), K.shape[1], K.shape[0]) > 0.5).astype(np.uint8), (g.W, g.H),
                      interpolation=cv2.INTER_NEAREST) > 0)[Y:Y + h4, X:X + w4]
    seg = Segmenter()
    kc = int(np.ceil(g.cell)) | 1
    for d in hand.get("dogs", [{"name": a.name}]):
        grow = chw | pet
        if d.get("box"):
            bx0, by0, bx1, by1 = [round(v * cx["k4"]) for v in d["box"]]
            bm = np.zeros_like(grow)
            bm[max(0, by0 - Y):max(0, by1 - Y), max(0, bx0 - X):max(0, bx1 - X)] = True
            grow = grow & bm
        grow = cv2.dilate(grow.astype(np.uint8), np.ones((kc, kc), np.uint8)) > 0
        al, iou = chain_cutout(seg, E, B, grow, g.cell, pal if d.get("seed") == "fur" else None)
        al = fill_holes(biggest_blob(to_cells(al, X, Y, g.cell, g.ox, g.oy) & grow))
        rgb = E.copy()
        mp = al & ptw
        if mp.any():
            rgb[mp] = to_palette(rgb[mp], pal)
        ys, xs = np.nonzero(al)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        rgba = np.dstack([rgb, al.astype(np.uint8) * 255])[y0:y1, x0:x1]
        fx, fy = anchor_of(al[y0:y1, x0:x1], d.get("anchor", "feet"))
        gx = g.ox + round((X + x0 + fx - g.ox) / g.cell) * g.cell
        gy = g.oy + round((Y + y0 + fy + 1 - g.oy) / g.cell) * g.cell
        nm = d["name"]
        Image.fromarray(rgba, "RGBA").save(od / f"posed_{nm}.png")
        pj = {"pose": a.name, "file": f"posed_{nm}.png", "size": [x1 - x0, y1 - y0], "corner": [X + x0, Y + y0],
              "drawn_at": [round(gx, 3), round(gy, 3)], "anchor": [round(gx - X - x0, 3), round(gy - Y - y0, 3)],
              # the light it was painted in: where it stands, or (views) the mat's: the model painted every dog in the
              # standing dog's warm light, wherever it put it
              "lit_at": hand.get("lit_at", [round(gx, 1), round(gy, 1)]), "height": int(y1 - y0), "width": int(x1 - x0),
              "painted_share": round(float(mp.sum() / max(1, al.sum())), 3), "sam_iou_with_the_change": round(iou, 3)}
        (od / f"posed_{nm}.json").write_text(json.dumps(pj, indent=1), encoding="utf-8", newline="\n")
        view = B.copy()
        view[al] = rgb[al]
        side = view.copy()
        side[al & ~(cv2.erode(al.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)] = [0, 255, 0]
        pad = int(4 * g.cell)
        sl = (slice(max(0, y0 - pad), y1 + pad), slice(max(0, x0 - pad), x1 + pad))
        Image.fromarray(np.hstack([E[sl], view[sl], side[sl]])).save(od / f"posed_{nm}_check.png")
        print(f"{nm}: -> {od / f'posed_{nm}.png'} ({x1 - x0}x{y1 - y0}, drawn at {pj['drawn_at']}, {pj['painted_share']:.0%} "
              f"painted by the model, SAM IoU with the change {iou:.2f}); check {od / f'posed_{nm}_check.png'}")


# The cycles of the chained masters (round 6): four copies of a posed master (its 4K cells, scaled onto the canvas), only
# the rig's zone of each repainted in one edit, so the cycle is drawn as one and everything outside the zone stays the
# master's own cells. rig.json "zones": polygons in the master's own px (posed_<master>.png), may run past its edges.
PDERIVE = {
    "walk_side": {"master": "stand", "zone": "stand_legs", "scale": 2 / 3, "ref_sheet": "walk_side", "fit_legs": 320,
                  "layout": {"size": [1024, 1024], "cols": 2, "rows": 2}, "prompt": WALK["walk_side"]},
    "walk_back": {"master": "back", "zone": "back_legs", "scale": 2 / 3, "layout": ROW4, "fit_legs": 325, "prompt": WALK["walk_back"]},
    "walk_front": {"master": "front", "zone": "front_legs", "scale": 2 / 3, "layout": ROW4, "fit_legs": 315,
                   "prompt": WALK["walk_front"]},
    # cover: the share of a cell the edit must cover to be a cell of the dog; at the door the tail is under a cell thick
    # and at one half it came back as a stub
    "wag_back": {"master": "sit_back", "zone": "sit_back_tail", "scale": 1.5, "layout": ROW4, "cover": 0.3, "prompt": (
        "Pixel-art sprite sheet: the same golden-brown puppy four times in a row, sitting, seen from behind, on a "
        "transparent background. Repaint only the masked area at the bottom of each puppy: its tail and the empty space "
        "around it, low on the floor. Left to right the four puppies sweep their tail across the floor: 1 the tail swept "
        "out to the left, 2 the tail lying straight back toward the viewer, 3 the tail swept out to the right, 4 the tail "
        "lying straight back. The tail grows from the same spot under the rump in all four and is the same fluffy tail "
        f"as now, with {EDGE}. The head, ears, back and haunches stay exactly as they are. No ground, no shadow, no text.")},
}


def pd_layout(spec, msize):
    """A cycle's canvas: its size, a cell's size, the master's size on it, its top-left in a cell, each copy's cell."""
    L = spec["layout"]
    (W, H), cols = L["size"], L["cols"]
    cw, ch = W // cols, H // L["rows"]
    mw, mh = round(msize[0] * spec["scale"]), round(msize[1] * spec["scale"])
    if mw > cw or mh > ch:
        sys.exit(f"the master ({mw}x{mh} on the canvas) does not fit a {cw}x{ch} cell")
    return (W, H), (cw, ch), (mw, mh), ((cw - mw) // 2, (ch - mh) // 2), [(cw * (i % cols), ch * (i // cols)) for i in range(N_FRAMES)]


def cmd_pderive(a):
    """The cycles' edits -> pderive_<name>.png (+ .json). --dry writes pderive_<name>_dry.png (the canvas, the zones
    tinted) and spends nothing. Run cut afterwards."""
    _, plate, sd, pd = scene_paths(a.scene)
    od = pd / "petsprite"
    rig = load_rig(sd)
    for name in (a.only.split(",") if a.only else list(PDERIVE)):
        spec = PDERIVE[name]
        mm = json.loads((od / f"posed_{spec['master']}.json").read_text(encoding="utf-8"))
        master = Image.open(od / mm["file"]).convert("RGBA")
        (CW, CH), _, (mw, mh), (tx, ty), cells = pd_layout(spec, mm["size"])
        small = np.asarray(master.resize((mw, mh), Image.LANCZOS)).copy()
        small[..., 3] = np.where(small[..., 3] > 127, 255, 0)
        small = Image.fromarray(small, "RGBA")
        canvas = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        mask = np.full((CH, CW, 4), 255, np.uint8)
        Z = np.array(rig["zones"][spec["zone"]], np.float32) * spec["scale"]
        for gx, gy in cells:
            canvas.alpha_composite(small, (gx + tx, gy + ty))
            zm = np.zeros((CH, CW), np.uint8)
            cv2.fillPoly(zm, [np.round(Z + [gx + tx, gy + ty]).astype(np.int32)], 1)
            mask[..., 3][zm > 0] = 0
        if a.dry:
            v = np.asarray(Image.alpha_composite(Image.new("RGBA", (CW, CH), (40, 60, 110, 255)), canvas).convert("RGB")).astype(np.float32)
            z = mask[..., 3] == 0
            v[z] = v[z] * 0.55 + np.array([255, 0, 170], np.float32) * 0.45
            Image.fromarray(v.astype(np.uint8)).save(od / f"pderive_{name}_dry.png")
            print(f"{name}: -> {od / f'pderive_{name}_dry.png'} (nothing spent)")
            continue
        from azure_ai import edit_image, CFG
        refs = []
        if spec.get("ref_sheet") and (sd / f"sheet_{spec['ref_sheet']}.png").exists():
            refs.append(Image.open(sd / f"sheet_{spec['ref_sheet']}.png").convert("RGBA"))
        res = edit_image(canvas, spec["prompt"], mask=Image.fromarray(mask, "RGBA"), size=f"{CW}x{CH}", quality="high",
                         purpose=f"petsprite:{a.scene}:pderive_{name}", background="transparent", images=refs)
        im = Image.open(io.BytesIO(base64.b64decode(res["data"][0]["b64_json"]))).convert("RGBA")
        if im.size != canvas.size:
            im = im.resize(canvas.size, Image.LANCZOS)
        im.save(sd / f"pderive_{name}.png")
        info = {"derived": name, "prompt": spec["prompt"], "master": f"posed_{spec['master']}.png",
                "master_file_sha": file_sha(od / mm["file"]), "zone": spec["zone"], "scale": spec["scale"],
                "references": [f"sheet_{spec['ref_sheet']}.png (where the legs go)"] if refs else [],
                "deployment": CFG["default_deployment"], "date": datetime.date.today().isoformat(), "usage": res.get("usage")}
        (sd / f"pderive_{name}.json").write_text(json.dumps(info, indent=1), encoding="utf-8", newline="\n")
        print(f"{name}: -> {sd / f'pderive_{name}.png'}")


def pderived_frames(name, sd, od, rig, g):
    """A cycle's frames on the plate's grid: per copy, the edit taken back to the master's 4K px (shifted onto the master
    if the edit moved it), rebuilt cell by cell on the plate's grid where the master was painted; a cell in the zone
    takes the edit (mapped onto the master's colors), every other cell is the master's own. One frame size for the
    cycle (the master and every zone), the master's drawn_at, the anchor moved with the frame's corner."""
    spec = PDERIVE[name]
    mm = json.loads((od / f"posed_{spec['master']}.json").read_text(encoding="utf-8"))
    master = np.asarray(Image.open(od / mm["file"]).convert("RGBA"))
    edit = np.asarray(Image.open(sd / f"pderive_{name}.png").convert("RGBA"))
    pal = frame_palette(master)
    s = spec["scale"]
    _, (cw, ch), (mw, mh), (tx, ty), cells = pd_layout(spec, mm["size"])
    h0, w0 = master.shape[:2]
    Zp = np.array(rig["zones"][spec["zone"]], np.float32)
    # the frame: the master's box and the zone's, out to whole cells of the plate's grid (4K px from the master's corner)
    X0, Y0 = mm["corner"]
    xs_ = cell_edges(X0 + min(0, Zp[:, 0].min()), X0 + max(w0, Zp[:, 0].max()), g.cell, g.ox)
    ys_ = cell_edges(Y0 + min(0, Zp[:, 1].min()), Y0 + max(h0, Zp[:, 1].max()), g.cell, g.oy)
    FX, FY = int(xs_[0]), int(ys_[0])
    fw, fh = int(xs_[-1]) - FX, int(ys_[-1]) - FY
    M = np.zeros((fh, fw, 4), np.uint8)
    M[Y0 - FY:Y0 - FY + h0, X0 - FX:X0 - FX + w0] = master
    zm = np.zeros((fh, fw), np.uint8)
    cv2.fillPoly(zm, [np.round(Zp + [X0 - FX, Y0 - FY]).astype(np.int32)], 1)
    ma = M[..., 3] > 127
    keep = ~(cv2.dilate(zm, np.ones((25, 25), np.uint8)) > 0)
    frames = []
    for i, (gx, gy) in enumerate(cells):
        # the copy's region on the canvas covering the frame, back at 4K px
        cx0, cy0 = gx + tx + (FX - X0) * s, gy + ty + (FY - Y0) * s
        Mx = np.array([[s, 0, cx0], [0, s, cy0]], np.float32)
        best = (1e18, 0, 0)
        for dy in range(-8, 9, 2):
            for dx in range(-8, 9, 2):
                Mt = Mx + np.array([[0, 0, dx], [0, 0, dy]], np.float32)
                ea = cv2.warpAffine(edit[..., 3], Mt, (fw, fh), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP) > 127
                best = min(best, (float((ea != ma)[keep].sum()), dx, dy))
        _, dx, dy = best
        Mt = Mx + np.array([[0, 0, dx], [0, 0, dy]], np.float32)
        E = cv2.warpAffine(edit, Mt, (fw, fh), flags=cv2.INTER_LANCZOS4 + cv2.WARP_INVERSE_MAP)
        out = M.copy()
        for ya, yb in zip(ys_[:-1], ys_[1:]):
            for xa, xb in zip(xs_[:-1], xs_[1:]):
                sl = (slice(int(ya) - FY, int(yb) - FY), slice(int(xa) - FX, int(xb) - FX))
                ccy, ccx = (int(ya) + int(yb)) // 2 - FY, (int(xa) + int(xb)) // 2 - FX
                if not zm[ccy, ccx]:
                    continue
                blk = E[sl]
                inner = blk[1:-1, 1:-1] if blk.shape[0] > 3 and blk.shape[1] > 3 else blk
                if (inner[..., 3] > 127).mean() > spec.get("cover", 0.5):
                    col = np.median(inner[..., :3][inner[..., 3] > 127].reshape(-1, 3), axis=0)
                    out[sl] = [*to_palette(col[None].astype(np.uint8), pal)[0], 255]
                else:
                    out[sl] = 0
        al = biggest_blob(out[..., 3] > 127)
        out[..., 3] = al * 255
        out = fit_legs(out, al, M, zm, ys_, FY, spec["fit_legs"] + Y0 - FY) if spec.get("fit_legs") else out
        al = out[..., 3] > 127
        f = od / f"d_{name}_{i}.png"
        Image.fromarray(out, "RGBA").save(f)
        yy, xx = np.nonzero(al)
        frames.append({"file": f.name, "size": [fw, fh], "corner": [FX, FY], "drawn_at": mm["drawn_at"],
                       "anchor": [round(mm["drawn_at"][0] - FX, 3), round(mm["drawn_at"][1] - FY, 3)],
                       "lit_at": mm["lit_at"], "height": int(yy.max() - yy.min() + 1), "width": int(xx.max() - xx.min() + 1),
                       "derived": True})
        print(f"  {name} {i}: edit shift {dx:+d},{dy:+d} (canvas px), mismatch outside the zone {best[0]:.0f} px")
    return frames


def fit_legs(out, al, M, zm, ys_, FY, y_s):
    """A walk frame's paws put back on the master's ground line (round 6: the model drew every walk with shorter legs, the
    paws 6 to 8 cells above the master's, so the dog would drop when it starts walking): below row y_s (frame px) the
    zone's cell rows are remapped, the bottom three (the paws) moved down whole and the leg rows above them stretched."""
    rows = [(int(a) - FY, int(b) - FY) for a, b in zip(ys_[:-1], ys_[1:])]
    row_of = lambda y: next(i for i, (a, b) in enumerate(rows) if a <= y < b)
    b_m = int(np.nonzero((M[..., 3] > 127).any(1))[0].max())
    b_e = int(np.nonzero(al.any(1))[0].max())
    if b_e >= b_m:
        return out
    r_s, r_e, r_m = row_of(y_s), row_of(b_e), row_of(b_m)
    P = 3
    new = out.copy()
    z = zm > 0
    for t in range(r_s, len(rows)):
        if t > r_m:
            s = None
        elif t > r_m - P:
            s = t - (r_m - r_e)
        else:
            s = r_s + int((t - r_s) * (r_e - P + 1 - r_s) / max(1, r_m - P + 1 - r_s))
        ta, tb = rows[t]
        for y in range(max(0, ta), min(out.shape[0], tb)):
            if s is None:
                new[y][z[y]] = 0
            else:
                sa, sb = rows[s]
                sy = (sa + sb) // 2
                take = z[y] & z[sy]   # only the zone's own cells move (the hanging tail beside it stays where it is)
                new[y][take] = out[sy][take]
                new[y][z[y] & ~z[sy]] = 0
    return new


def mirror_cells(rgba, corner, g, row_from, col_axis):
    """A sprite on the plate's grid with its rows from cell row `row_from` down mirrored about the middle of cell column
    `col_axis` (both counted from its top-left cell): the sitting dog's tail lying left instead of right, its haunches'
    lower edge mirrored with it (seen from behind they are the same both sides). Exact on the grid: cell c -> 2 axis - c.
    Returns (rgba, corner) on a canvas wide enough for both."""
    X0, Y0 = corner
    h, w = rgba.shape[:2]
    i0 = int(np.searchsorted(g.xs, X0, side="right")) - 1
    j0 = int(np.searchsorted(g.ys, Y0, side="right")) - 1
    i1 = int(np.searchsorted(g.xs, X0 + w, side="left"))
    j1 = int(np.searchsorted(g.ys, Y0 + h, side="left"))
    nc = i1 - i0
    pad = max(0, 2 * col_axis - (nc - 1), (nc - 1) - 2 * col_axis)
    cx = ((g.xs[i0:i1] + g.xs[i0 + 1:i1 + 1]) // 2 - X0).clip(0, w - 1)
    cy = ((g.ys[j0:j1] + g.ys[j0 + 1:j1 + 1]) // 2 - Y0).clip(0, h - 1)
    C = rgba[np.ix_(cy, cx)]
    C = np.pad(C, ((0, 0), (pad, pad), (0, 0)))
    a = col_axis + pad
    M = C.copy()
    for c in range(C.shape[1]):
        m = 2 * a - c
        M[row_from:, c] = C[row_from:, m] if 0 <= m < C.shape[1] else 0
    xs = g.xs[i0 - pad:i1 + pad + 1]
    ys = g.ys[j0:j1 + 1]
    out = np.repeat(np.repeat(M, np.diff(ys), axis=0), np.diff(xs), axis=1)
    return out, [int(xs[0]), int(ys[0])]


def thin_edge(rgba, corner, g, dark=30):
    """A frame's outline kept one cell thick: a dark cell on the silhouette with a dark cell right inside it (toward the
    body, away from the open side) is dropped. The cut's edge ring takes a dark cell around SAM's mask to give back the
    dog's own edge where SAM left it out; where SAM had kept it and the model painted the ground around dark (the door
    sit's door panel), it doubled the edge (round 6)."""
    X0, Y0 = corner
    h, w = rgba.shape[:2]
    i0 = int(np.searchsorted(g.xs, X0, side="right")) - 1
    j0 = int(np.searchsorted(g.ys, Y0, side="right")) - 1
    i1 = int(np.searchsorted(g.xs, X0 + w, side="left"))
    j1 = int(np.searchsorted(g.ys, Y0 + h, side="left"))
    cx = ((g.xs[i0:i1] + g.xs[i0 + 1:i1 + 1]) // 2 - X0).clip(0, w - 1)
    cy = ((g.ys[j0:j1] + g.ys[j0 + 1:j1 + 1]) // 2 - Y0).clip(0, h - 1)
    C = rgba[np.ix_(cy, cx)]
    A = np.pad(C[..., 3] > 127, 1)
    D = np.pad(lab(C[..., :3])[..., 0] < dark, 1) & A
    drop = np.zeros_like(A)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        opn = ~np.roll(A, (dy, dx), (0, 1))            # the open side
        inner = np.roll(D, (-dy, -dx), (0, 1))          # the cell on the other side, toward the body
        drop |= D & opn & inner
    drop = drop[1:-1, 1:-1]
    if not drop.any():
        return rgba, 0
    out = rgba.copy()
    ys, xs = np.nonzero(drop)
    for j, i in zip(ys, xs):
        out[max(0, g.ys[j0 + j] - Y0):max(0, g.ys[j0 + j + 1] - Y0), max(0, g.xs[i0 + i] - X0):max(0, g.xs[i0 + i + 1] - X0)] = 0
    return out, int(drop.sum())


def cmd_sheet(a):
    _, plate, sd, pd = scene_paths(a.scene)
    meta = json.loads((pd / "petsprite" / "petsprite.json").read_text(encoding="utf-8"))
    rows = []
    for name, fr in meta["frames"].items():
        ims = [Image.open(pd / "petsprite" / f["file"]) for f in fr]
        h = 260
        ims = [im.resize((max(1, round(im.width * h / im.height)), h), Image.NEAREST) for im in ims]
        row = Image.new("RGBA", (sum(i.width + 16 for i in ims), h + 10), (60, 44, 40, 255))
        x = 0
        for im in ims:
            row.alpha_composite(im, (x, 5))
            x += im.width + 16
        rows.append(row)
    W = max(r.width for r in rows)
    out = Image.new("RGBA", (W, sum(r.height + 6 for r in rows)), (30, 30, 30, 255))
    y = 0
    for r in rows:
        out.alpha_composite(r, (0, y))
        y += r.height + 6
    out.convert("RGB").save(pd / "petsprite_sheet.jpg", quality=90)
    print(f"-> {pd / 'petsprite_sheet.jpg'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ref")
    g = sub.add_parser("gen")
    g.add_argument("--only")
    sub.add_parser("cut")
    p = sub.add_parser("patches")
    p.add_argument("--only")
    q = sub.add_parser("pose")
    q.add_argument("name", choices=list(POSES))
    q.add_argument("--dry", action="store_true", help="the window and mask to look at, no edit")
    q = sub.add_parser("posecut")
    q.add_argument("name")
    q = sub.add_parser("pderive")
    q.add_argument("--only")
    q.add_argument("--dry", action="store_true", help="the canvas and zones to look at, no edit")
    sub.add_parser("sheet")
    a = ap.parse_args()
    {"ref": cmd_ref, "gen": cmd_gen, "cut": cmd_cut, "patches": cmd_patches, "pose": cmd_pose, "posecut": cmd_posecut,
     "pderive": cmd_pderive, "sheet": cmd_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
