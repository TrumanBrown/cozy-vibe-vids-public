"""pet.png: what breathes (TASKS.md T16), moved verbatim from plate_prep.py.

  pet_map          one pet, or several characters through pet_map_multi (PET_HMAX, PET_AMP_REF)
"""
import cv2
import numpy as np
from PIL import Image

from cozy.masks import region_raster


PET_HMAX = 0.25      # multi-character pet.png: R = (height above the character's own base / frame height) / PET_HMAX
PET_AMP_REF = 0.035  # times the character's own breathing amplitude / PET_AMP_REF (Treetop's approved 0.035)


def pet_map(ov, W, H, out, pixel=None):
    """pet.png for the breathing pet (plate.js): R = how much each point rises with a breath (the torso; 0 on the head
    and tail, ramping up over three cells away from them, and carried three cells above the back so the back rises
    over what is behind it), G = the whole pet. The shader keeps a warped sample only where it lands on the pet, so the
    background never moves (user 2026-10-21, the pixel greenhouse's dog: the breathing pushed up the background with
    it, like the shelf corner, the eyes moved oddly, and the eyes and tail must hold still; before, a soft
    ellipse around the whole pet stretched everything in it). Still parts: the pet region's "still" boxes
    (analyze_plate asks for its head and tail) and hand.json "pet_still" (boxes, frame fractions).
    Several characters (the channel's own cast, 2026-10-25: four friends at a campfire, each breathing): each rises
    from its own base, so R carries the height above that base and the character's own amplitude (sized to it as
    autoscene sizes one pet), B its index, for its own rate and phase in the shader."""
    pets = [rg for rg in ov.get("regions") or [] if rg.get("kind") == "pet" and rg.get("polys")]
    if not pets:
        return None
    if len(pets) > 1 and not pixel:
        return pet_map_multi(pets, ov, W, H, out)
    rg = pets[0]
    M = region_raster(rg, W, H)
    if M.max() <= 0.5:
        return None
    cell = float(pixel["cell"]) if pixel else 4 * W / 1920
    boxes = (rg.get("still") or []) + (ov.get("pet_still") or [])
    still = np.zeros((H, W), np.uint8)
    for x0, y0, x1, y1 in boxes:
        still[int(y0 * H):int(np.ceil(y1 * H)), int(x0 * W):int(np.ceil(x1 * W))] = 1
    free = (np.clip(cv2.distanceTransform(1 - still, cv2.DIST_L2, 5) / (3 * cell), 0, 1) if still.any()
            else np.ones((H, W), np.float32))
    torso = (M > 0.5).astype(np.float32) * free
    n = max(3, int(round(3 * cell)))
    rise = cv2.dilate(torso, np.ones((n, 1), np.uint8), anchor=(0, 0)) * free
    rgb = np.stack([rise, M, np.zeros_like(M)], -1)
    Image.fromarray((np.clip(rgb, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "pet.png")
    ys, xs = np.nonzero(M > 0.5)
    return {"file": "pet.png", "region": rg["name"], "still_parts": len(boxes),
            "bbox": [round(xs.min() / W, 5), round(ys.min() / H, 5), round((xs.max() + 1) / W, 5), round((ys.max() + 1) / H, 5)]}


def pet_map_multi(pets, ov, W, H, out):
    """pet.png for several breathing characters (see pet_map): R = height above the character's own base (frame
    fractions / PET_HMAX) times its amplitude / PET_AMP_REF, G = every character, B = (index + 1) / 8."""
    cell = 4 * W / 1920
    n = max(3, int(round(3 * cell)))
    rows = (np.arange(H, dtype=np.float32) / H)[:, None]
    R = np.zeros((H, W), np.float32)
    G = np.zeros((H, W), np.float32)
    B = np.zeros((H, W), np.float32)
    metas = []
    for i, rg in enumerate(pets[:7]):
        M = region_raster(rg, W, H)
        if M.max() <= 0.5:
            continue
        still = np.zeros((H, W), np.uint8)
        for x0, y0, x1, y1 in (rg.get("still") or []) + (ov.get("pet_still") or []):
            still[int(y0 * H):int(np.ceil(y1 * H)), int(x0 * W):int(np.ceil(x1 * W))] = 1
        free = (np.clip(cv2.distanceTransform(1 - still, cv2.DIST_L2, 5) / (3 * cell), 0, 1) if still.any()
                else np.ones((H, W), np.float32))
        torso = (M > 0.5).astype(np.float32) * free
        rise = cv2.dilate(torso, np.ones((n, 1), np.uint8), anchor=(0, 0)) * free
        ys, xs = np.nonzero(M > 0.5)
        base = (ys.max() + 1) / H
        hpx = (ys.max() + 1 - ys.min()) * 2160 / H
        amp = PET_AMP_REF * min(1.0, max(0.3, 200 / max(hpx, 1)))
        h = np.clip(base - rows, 0, None) / PET_HMAX * (amp / PET_AMP_REF)
        R = np.maximum(R, rise * h)
        G = np.maximum(G, M)
        B = np.where(rise > 0, (i + 1) / 8, B)
        metas.append({"region": rg["name"], "index": i, "base": round(float(base), 5), "amp": round(float(amp), 5),
                      "bbox": [round(xs.min() / W, 5), round(ys.min() / H, 5), round((xs.max() + 1) / W, 5), round(base, 5)]})
    if not metas:
        return None
    if R.max() > 1:
        print(f"  pet.png: a character's breath is clipped (R {R.max():.2f} > 1): raise PET_HMAX")
    rgb = np.stack([np.clip(R, 0, 1), G, B], -1)
    Image.fromarray((np.clip(rgb, 0, 1) * 255).round().astype(np.uint8), "RGB").save(out / "pet.png")
    bb = np.array([m["bbox"] for m in metas])
    return {"file": "pet.png", "multi": True, "hmax": PET_HMAX, "amp_ref": PET_AMP_REF, "pets": metas,
            "region": metas[0]["region"], "still_parts": sum(len(rg.get("still") or []) for rg in pets),
            "bbox": [float(bb[:, 0].min()), float(bb[:, 1].min()), float(bb[:, 2].max()), float(bb[:, 3].max())]}
