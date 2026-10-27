"""The plate and its depth (TASKS.md T16), moved verbatim from plate_prep.py.

  crop_16x9      the key art cropped to 16:9 (at a chosen height when it is taller)
  upscale        Swin2SR x4 in tiles on the GPU, then Lanczos to the target width (a large image is only resized)
  depth          relative disparity (0 far .. 1 near) from Depth Anything V2 (DEPTH_MODEL, pinned in cozy/models.py)
  defocus_map    defocus.png: how out of focus the plate is around each point
  depth_fine     depth_fine.png: the depth model's halos around thin structures against the sky put back to its depth

Importing this sets the Hugging Face cache to cache/hf and imports torch, as importing plate_prep.py always did; the
models load with the first upscale() or depth(). The other cozy.plate modules don't import torch.
"""
import os

from cozy.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from cozy.models import revision  # noqa: E402  (pinned model revisions, TASKS.md T8)
from cozy.plate.primitives import srgb_to_linear  # noqa: E402


DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def crop_16x9(img, cy):
    w, h = img.size
    th = round(w * 9 / 16)
    if th <= h:
        top = int(np.clip(cy * h - th / 2, 0, h - th))
        return img.crop((0, top, w, top + th))
    tw = round(h * 16 / 9)
    return img.crop(((w - tw) // 2, 0, (w - tw) // 2 + tw, h))


def upscale(img, target_w, tile=256, pad=16):
    """x4 Swin2SR in overlapping tiles (bounded VRAM), then Lanczos to the target width.
    Inputs that already exceed 80% of the target are only resized (best for gpt-image output)."""
    th = round(target_w * 9 / 16)
    if img.width >= target_w * 0.8:
        return img.resize((target_w, th), Image.LANCZOS)
    from transformers import Swin2SRForImageSuperResolution
    model = Swin2SRForImageSuperResolution.from_pretrained("caidas/swin2SR-classical-sr-x4-64", revision=revision("caidas/swin2SR-classical-sr-x4-64")).to("cuda").half().eval()
    src = np.asarray(img, np.float32) / 255.0
    H, W = src.shape[:2]
    out = np.zeros((H * 4, W * 4, 3), np.float32)
    for y in range(0, H, tile):
        for x in range(0, W, tile):
            y0, x0 = max(0, y - pad), max(0, x - pad)
            y1, x1 = min(H, y + tile + pad), min(W, x + tile + pad)
            t = torch.from_numpy(src[y0:y1, x0:x1]).permute(2, 0, 1)[None].to("cuda").half()
            ph, pw = (8 - t.shape[2] % 8) % 8, (8 - t.shape[3] % 8) % 8
            t = torch.nn.functional.pad(t, (0, pw, 0, ph), mode="reflect")
            with torch.no_grad():
                r = model(pixel_values=t).reconstruction[0].float().clamp(0, 1).permute(1, 2, 0).cpu().numpy()
            r = r[: (y1 - y0) * 4, : (x1 - x0) * 4]
            oy, ox = (y - y0) * 4, (x - x0) * 4
            hh, ww = min(tile, H - y) * 4, min(tile, W - x) * 4
            out[y * 4: y * 4 + hh, x * 4: x * 4 + ww] = r[oy: oy + hh, ox: ox + ww]
    del model
    torch.cuda.empty_cache()
    return Image.fromarray((out * 255).round().astype(np.uint8)).resize((target_w, th), Image.LANCZOS)


def depth(img, net_h=1036):
    """Relative disparity (0 far .. 1 near). Runs Depth Anything V2 at ~1036 px height (multiple of 14;
    sharper object edges than the default 518) and averages with a horizontally flipped pass."""
    from transformers import AutoModelForDepthEstimation
    model = AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL, dtype=torch.float16, revision=revision(DEPTH_MODEL)).to("cuda").eval()
    W, H = img.size
    nh = net_h
    nw = int(round(nh * W / H / 14)) * 14
    x = np.asarray(img.resize((nw, nh), Image.BICUBIC), np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    t = torch.from_numpy(x).permute(2, 0, 1)[None].to("cuda").half()
    with torch.no_grad():
        d0 = model(pixel_values=t).predicted_depth
        d1 = model(pixel_values=torch.flip(t, dims=[3])).predicted_depth
    d = (0.5 * (d0 + torch.flip(d1, dims=[2]))).float()[0].cpu().numpy()
    del model
    torch.cuda.empty_cache()
    d = cv2.resize(d, (W, H), interpolation=cv2.INTER_CUBIC)
    lo, hi = np.percentile(d, 0.5), np.percentile(d, 99.5)
    return np.clip((d - lo) / (hi - lo + 1e-6), 0, 1).astype(np.float32)


def defocus_map(plate, out, step=16, win=128, s0=2.0):
    """defocus.png: how out of focus the plate is around each point, as a Gaussian sigma in 4K px (value / 20),
    one pixel per 16x16 block. Re-blur gradient ratio at edges (Zhuo & Sim 2011): an edge blurred by sigma,
    blurred again by s0, loses gradient by R = sqrt(sigma^2 + s0^2) / sigma. The median over a window of the
    edges' estimates, holes filled from the cells around them. On a plate blurred by a known amount it reads
    ~20% low (fewer edges survive strong blur), so it is scaled by 1.2. What the code adds onto a surface
    (ant.js) is blurred to match, so it doesn't look pasted on a soft foreground."""
    g = cv2.cvtColor(np.asarray(plate), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    H, W = g.shape
    k = 3840 / W
    grad = lambda im: cv2.magnitude(cv2.Sobel(im, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(im, cv2.CV_32F, 0, 1, ksize=3))  # noqa: E731
    g1, g2 = grad(g), grad(cv2.GaussianBlur(g, (0, 0), s0))
    R = g1 / np.maximum(g2, 1e-6)
    edges = cv2.Canny(cv2.GaussianBlur((g * 255).astype(np.uint8), (0, 0), 1.0), 20, 60) > 0
    valid = edges & (R > 1.0005) & (g1 > 0.01)
    sig = np.clip(1.2 * s0 / np.sqrt(np.maximum(R * R - 1, 1e-6)), 0, 12)
    gh, gw = H // step, W // step
    est = np.zeros((gh, gw), np.float32)
    wt = np.zeros((gh, gw), np.float32)
    for j in range(gh):
        y0, y1 = max(0, j * step + step // 2 - win // 2), min(H, j * step + step // 2 + win // 2)
        vr, sr = valid[y0:y1], sig[y0:y1]
        for i in range(gw):
            x0, x1 = max(0, i * step + step // 2 - win // 2), min(W, i * step + step // 2 + win // 2)
            v = sr[:, x0:x1][vr[:, x0:x1]]
            if v.size >= 12:
                est[j, i], wt[j, i] = np.median(v), min(1.0, v.size / 200)
    s = 3.0
    num, den = cv2.GaussianBlur(est * wt, (0, 0), s), cv2.GaussianBlur(wt, (0, 0), s)
    fill = np.where(den > 1e-4, num / np.maximum(den, 1e-4), float(np.median(est[wt > 0])) if wt.any() else 1.0)
    d = np.where(wt > 0, wt * est + (1 - wt) * fill, fill)
    d = cv2.GaussianBlur(d, (0, 0), 1.0) * k
    Image.fromarray(np.clip(d * 20, 0, 255).round().astype(np.uint8)).save(out / "defocus.png")
    print(f"  defocus: sigma p10 {np.percentile(d, 10):.2f} px, median {np.median(d):.2f}, p90 {np.percentile(d, 90):.2f} -> defocus.png")
    return d


def depth_fine(plate, disp, outdoor, out, far=0.012):
    """depth_fine.png (as depth8.png: sqrt(disparity) 8-bit): the depth model smears thin dark structures
    against the sky (a 25 px pole reads ~100 px wide, wires and branches likewise), so things flying in the sky
    vanished in the open air beside a pole (birds.js, user 2026-10-19). Here every pixel that looks like the sky
    around it (within ~35% of the local far background's brightness and close to its color) gets the
    background's disparity back, so only the pole itself hides what passes behind it. The local background is a
    normalized blur of the far pixels (disparity < `far`, outdoors) reaching ~80 px. depth_fine_preview.jpg:
    red = still nearer than the sky (hides a bird), the rest dimmed."""
    a = np.asarray(plate, np.float32) / 255
    H, W = disp.shape
    lin = srgb_to_linear(a)
    lw = np.array([0.2126, 0.7152, 0.0722], np.float32)
    lum = lin @ lw
    farm = ((disp < far) & (outdoor > 0.5)).astype(np.float32)
    s = 40 * W / 3840
    den = cv2.GaussianBlur(farm, (0, 0), s)
    bg = cv2.GaussianBlur(lin * farm[..., None], (0, 0), s) / np.maximum(den, 1e-6)[..., None]
    bgd = cv2.GaussianBlur(disp * farm, (0, 0), s) / np.maximum(den, 1e-6)
    bl = bg @ lw
    ratio = lum / np.maximum(bl, 1e-5)
    cn = lin / np.maximum(lin.sum(-1, keepdims=True), 1e-5)
    cb = bg / np.maximum(bg.sum(-1, keepdims=True), 1e-5)
    cd = np.abs(cn - cb).sum(-1)
    skylike = np.clip(1 - np.abs(np.log(np.maximum(ratio, 1e-3))) / np.log(1.35), 0, 1) * np.clip(1 - cd / 0.12, 0, 1)
    w = skylike * np.clip((den - 0.02) / 0.06, 0, 1) * (outdoor > 0.5) * (disp < 0.25) * (disp > bgd)
    w = cv2.GaussianBlur(w.astype(np.float32), (0, 0), 0.7 * W / 3840)
    fine = disp * (1 - w) + bgd * w
    Image.fromarray((np.sqrt(np.clip(fine, 0, 1)) * 255).round().astype(np.uint8)).save(out / "depth_fine.png")
    near = np.clip((fine - 0.012) / 0.02, 0, 1) * (outdoor > 0.5)
    pv = a * 0.4
    pv[..., 0] = np.maximum(pv[..., 0], near)
    Image.fromarray((np.clip(pv, 0, 1) * 255).astype(np.uint8)).resize((W // 2, H // 2)).save(out / "depth_fine_preview.jpg", quality=88)
    moved = float((w > 0.5).sum()) / max(float((outdoor > 0.5).sum()), 1)
    print(f"  depth_fine: {moved * 100:.1f}% of the outdoors put back to the sky's depth (thin-structure halos) -> depth_fine.png")
