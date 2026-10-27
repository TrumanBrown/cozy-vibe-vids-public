"""Generate the block texture pack with a local SDXL model.

Each texture is generated as a normal photo-style image (SDXL is good at this), then made seamless by
shifting it half a tile and inpainting only a cross-shaped band over the wrapped seams. Result tiles
perfectly per block face.

Usage (repo root):  .venv/Scripts/python tools/gen_textures.py [--only id1,id2]
Writes assets/textures/<id>.png (+ <id>_n.png normal map). Model: stabilityai/stable-diffusion-xl-base-1.0
(CreativeML Open RAIL++-M; outputs may be used commercially), logged in docs/asset-ledger.csv.
"""
import argparse
import json
import os
import time

from cozy.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402
from cozy.images import normal_map  # noqa: E402
from cozy.models import revision  # noqa: E402  (pinned model revisions, TASKS.md T8)

OUT = ROOT / "assets" / "textures"
S = 1024


def leaves_alpha(img):
    """Leaves were generated on black: dark background -> transparent (leaf-block cutout)."""
    a = np.asarray(img.convert("RGB"), np.float32) / 255.0
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    sat = a.max(-1) - a.min(-1)
    keep = (lum > 0.12) & ((sat > 0.18) | (lum > 0.3))  # drops dark and greyish/purple background
    k = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))
    rgba = img.convert("RGBA")
    rgba.putalpha(k)
    return rgba


def flatten_light(img, radius=96):
    """Remove low-frequency lighting gradients (banding) while keeping grain and color."""
    a = np.asarray(img, np.float32)
    blur = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), np.float32)
    mean = a.reshape(-1, 3).mean(0)
    return Image.fromarray(np.clip(a / np.maximum(blur, 1) * mean, 0, 255).astype(np.uint8))


def seam_mask(band):
    m = np.zeros((S, S), np.uint8)
    c = S // 2
    m[:, c - band // 2:c + band // 2] = 255
    m[c - band // 2:c + band // 2, :] = 255
    return Image.fromarray(m).filter(ImageFilter.GaussianBlur(band / 6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--steps", type=int, default=30)
    a = ap.parse_args()
    man = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    only = set(filter(None, a.only.split(",")))
    from diffusers import AutoencoderKL, StableDiffusionXLInpaintPipeline, StableDiffusionXLPipeline

    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16,
                                        revision=revision("madebyollin/sdxl-vae-fp16-fix"))
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", vae=vae, torch_dtype=torch.float16, variant="fp16", use_safetensors=True,
        revision=revision("stabilityai/stable-diffusion-xl-base-1.0")
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    pipe.vae.enable_tiling()
    inpaint = StableDiffusionXLInpaintPipeline.from_pipe(pipe, torch_dtype=torch.float16)  # default upcasts to fp32 (13 GB)
    inpaint.set_progress_bar_config(disable=True)
    for t in man["textures"]:
        if only and t["id"] not in only:
            continue
        t0 = time.time()
        prompt = f"{t['prompt']}, {man['style']}"
        g = torch.Generator("cuda").manual_seed(t["seed"])
        img = pipe(prompt=prompt, negative_prompt=man["negative"], width=S, height=S,
                   num_inference_steps=a.steps, guidance_scale=6.0, generator=g).images[0]
        if t.get("flatten"):
            img = flatten_light(img)
        img.resize((512, 512), Image.LANCZOS).save(OUT / f"{t['id']}_raw.png")
        torch.cuda.empty_cache()
        print(f"  gen {time.time() - t0:.1f}s", flush=True)
        # Seamless: wrap by half, inpaint the seam cross.
        shifted = Image.fromarray(np.roll(np.asarray(img), (S // 2, S // 2), (0, 1)))
        g = torch.Generator("cuda").manual_seed(t["seed"] + 7)
        fixed = inpaint(prompt=prompt, negative_prompt=man["negative"], image=shifted, mask_image=seam_mask(t.get("band", 200)),
                        width=S, height=S, strength=0.85, num_inference_steps=a.steps, guidance_scale=6.0, generator=g).images[0]
        # Keep untouched pixels exactly (inpaint VAE round-trip slightly shifts colors outside the mask).
        m = np.asarray(seam_mask(t.get("band", 200)), np.float32)[..., None] / 255.0
        out = np.asarray(fixed, np.float32) * m + np.asarray(shifted, np.float32) * (1 - m)
        img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).resize((t["size"], t["size"]), Image.LANCZOS)
        if t.get("alpha") == "leaves":
            img = leaves_alpha(img)
        img.save(OUT / f"{t['id']}.png")
        normal_map(img).save(OUT / f"{t['id']}_n.png")
        torch.cuda.empty_cache()
        print(f"{t['id']}: {time.time() - t0:.1f}s (peak {torch.cuda.max_memory_allocated() / 2**30:.1f} GB)", flush=True)


if __name__ == "__main__":
    main()
