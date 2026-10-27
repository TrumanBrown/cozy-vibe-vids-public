"""AI enhancement of a rendered scene frame ("plate") with a local SDXL model.

Our three.js render supplies the composition, lighting and exact depth; SDXL (img2img + depth
ControlNet) repaints it with photoreal material detail while the depth guide pins geometry in place.
A tiled low-strength second pass refines detail at full 4K.

Usage (from repo root):
  .venv/Scripts/python tools/enhance.py out/treetop/guides/f000000 --prompt-file scenes/treetop/prompt.json \
      --out out/treetop/plates/plate.png [--seed 1] [--strength 0.6] [--control 0.6] [--base-only]

Models (downloaded once into cache/hf; licenses recorded in docs/asset-ledger.csv):
  stabilityai/stable-diffusion-xl-base-1.0      CreativeML Open RAIL++-M
  diffusers/controlnet-depth-sdxl-1.0           CreativeML Open RAIL++-M
  diffusers/controlnet-canny-sdxl-1.0           CreativeML Open RAIL++-M
  madebyollin/sdxl-vae-fp16-fix                 MIT
"""
import argparse
import json
import os
import pathlib
import sys
import time

from cozy.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from cozy.models import revision  # noqa: E402  (pinned model revisions, TASKS.md T8)

BASE = "stabilityai/stable-diffusion-xl-base-1.0"
CONTROL = "diffusers/controlnet-depth-sdxl-1.0"
CANNY = "diffusers/controlnet-canny-sdxl-1.0"
VAE = "madebyollin/sdxl-vae-fp16-fix"


def load_guides(prefix):
    meta = json.loads(pathlib.Path(f"{prefix}_guides.json").read_text())
    w, h = meta["width"], meta["height"]
    rgba = np.fromfile(f"{prefix}_color.rgba", dtype=np.uint8).reshape(h, w, 4)
    dist = np.fromfile(f"{prefix}_depth.f32", dtype=np.float32).reshape(h, w)[::-1]  # bottom-up -> top-down
    return Image.fromarray(rgba[..., :3]), np.ascontiguousarray(dist), meta


def depth_image(dist, far):
    """Disparity map (near = white) normalized robustly; the background (sky) maps to black."""
    disp = 1.0 / np.maximum(dist, 1e-3)
    valid = dist < far * 0.999
    lo, hi = np.percentile(disp[valid], 1), np.percentile(disp[valid], 99.5)
    d = np.clip((disp - lo) / (hi - lo + 1e-9), 0, 1) ** 0.6  # spread the far range a little
    d[~valid] = 0
    return Image.fromarray((d * 255).astype(np.uint8)).convert("RGB")


def edge_image(color, dist):
    """Block edges: canny on the render plus depth discontinuities (silhouettes)."""
    import cv2
    g = cv2.cvtColor(np.asarray(color), cv2.COLOR_RGB2GRAY)
    g = cv2.bilateralFilter(g, 7, 40, 7)
    e = cv2.Canny(g, 40, 110)
    ld = np.log(np.maximum(dist, 1e-3)).astype(np.float32)
    dd = np.abs(cv2.Sobel(ld, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(ld, cv2.CV_32F, 0, 1))
    e = np.maximum(e, (dd > 0.25).astype(np.uint8) * 255)
    return Image.fromarray(e).convert("RGB")


def build_pipe():
    from diffusers import AutoencoderKL, ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline

    dtype = torch.float16
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=dtype, revision=revision(VAE))
    def load(name):
        try:
            return ControlNetModel.from_pretrained(name, torch_dtype=dtype, variant="fp16", revision=revision(name))
        except Exception:
            return ControlNetModel.from_pretrained(name, torch_dtype=dtype, revision=revision(name))
    cn = [load(CONTROL), load(CANNY)]
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        BASE, controlnet=cn, vae=vae, torch_dtype=dtype, variant="fp16", use_safetensors=True, revision=revision(BASE)
    )
    pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    return pipe


def run(pipe, image, control, prompt, neg, seed, strength, cscale, steps, guidance):
    """control = (depth_img, edge_img); cscale = (depth_scale, edge_scale); prompt = (p1, p2)."""
    g = torch.Generator("cuda").manual_seed(seed)
    return pipe(
        prompt=prompt[0], prompt_2=prompt[1], negative_prompt=neg, image=image, control_image=list(control),
        strength=strength, controlnet_conditioning_scale=list(cscale), num_inference_steps=steps,
        guidance_scale=guidance, generator=g, width=image.width, height=image.height,
    ).images[0]


def tiled_refine(pipe, img, control, prompt, neg, seed, strength, cscale, steps, guidance, tile=1024, overlap=192):
    """Low-strength img2img over overlapping tiles, feather-blended (keeps 4K detail coherent)."""
    W, H = img.size
    acc = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    step = tile - overlap
    xs = list(range(0, W - tile + 1, step))
    ys = list(range(0, H - tile + 1, step))
    if xs[-1] + tile < W:
        xs.append(W - tile)
    if ys[-1] + tile < H:
        ys.append(H - tile)
    ramp = np.minimum(1, np.minimum(np.arange(tile) + 1, tile - np.arange(tile)) / overlap).astype(np.float32)
    mask = (ramp[None, :] * ramp[:, None])[..., None]
    n = 0
    for y in ys:
        for x in xs:
            box = (x, y, x + tile, y + tile)
            out = run(pipe, img.crop(box), tuple(c.crop(box) for c in control), prompt, neg, seed + n, strength, cscale, steps, guidance)
            acc[y:y + tile, x:x + tile] += np.asarray(out).astype(np.float32) * mask
            wsum[y:y + tile, x:x + tile] += mask
            n += 1
            print(f"  tile {n}/{len(xs) * len(ys)}", flush=True)
    return Image.fromarray(np.clip(acc / np.maximum(wsum, 1e-6), 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--strength", type=float, default=0.6)
    ap.add_argument("--control", type=float, default=0.6)
    ap.add_argument("--steps", type=int, default=36)
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--base-size", default="1368x768")
    ap.add_argument("--final-size", default="3840x2160")
    ap.add_argument("--refine-strength", type=float, default=0.3)
    ap.add_argument("--base-only", action="store_true")
    ap.add_argument("--edges", type=float, default=0.5, help="edge (canny) ControlNet scale")
    ap.add_argument("--sweep", default="", help="comma list of strength:depth:edge triples (base only), e.g. 0.6:0.6:0.5")
    a = ap.parse_args()

    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    spec = json.loads(pathlib.Path(a.prompt_file).read_text(encoding="utf-8"))
    prompt, neg = (spec["prompt"], spec.get("prompt2", spec["prompt"])), spec["negative"]
    color, dist, meta = load_guides(a.prefix)
    depth = depth_image(dist, meta["far"])
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    edges = edge_image(color, dist)
    depth.save(out.with_name(out.stem + "_depth.png"))
    edges.save(out.with_name(out.stem + "_edges.png"))

    t0 = time.time()
    pipe = build_pipe()
    print(f"models loaded in {time.time() - t0:.0f}s", flush=True)
    bw, bh = map(int, a.base_size.split("x"))
    small_c = color.resize((bw, bh), Image.LANCZOS)
    small_d = (depth.resize((bw, bh), Image.BILINEAR), edges.resize((bw, bh), Image.BILINEAR))
    if a.sweep:
        for pair in a.sweep.split(","):
            s, c, e = map(float, pair.split(":"))
            t1 = time.time()
            img = run(pipe, small_c, small_d, prompt, neg, a.seed, s, (c, e), a.steps, a.guidance)
            img.save(out.with_name(f"{out.stem}_s{s}_d{c}_e{e}.png"))
            print(f"sweep s={s} d={c} e={e} in {time.time() - t1:.0f}s", flush=True)
        return
    t1 = time.time()
    base = run(pipe, small_c, small_d, prompt, neg, a.seed, a.strength, (a.control, a.edges), a.steps, a.guidance)
    base.save(out.with_name(out.stem + "_base.png"))
    print(f"base {bw}x{bh} in {time.time() - t1:.0f}s", flush=True)
    if a.base_only:
        return
    fw, fh = map(int, a.final_size.split("x"))
    t2 = time.time()
    ctl = (depth.resize((fw, fh), Image.BILINEAR), edges.resize((fw, fh), Image.NEAREST))
    final = tiled_refine(pipe, base.resize((fw, fh), Image.LANCZOS), ctl, prompt, neg,
                         a.seed + 1000, a.refine_strength, (a.control * 0.6, a.edges * 0.6), a.steps, a.guidance)
    final.save(out)
    print(f"refined {fw}x{fh} in {time.time() - t2:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
