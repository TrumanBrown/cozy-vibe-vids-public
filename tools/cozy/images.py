"""Two small image helpers that had one copy per tool (TASKS.md T13); the copies did the same thing to the bit.

  lum(x)                          Rec. 709 luma of RGB values (the last axis); thumbnail.py, critter_concept.py
  normal_map(img, strength=3.0)   a normal map from an image's blurred luminance; gen_textures.py, gen_leaves.py
"""
import numpy as np
from PIL import Image, ImageFilter


def lum(x):
    return x[..., 0] * 0.2126 + x[..., 1] * 0.7152 + x[..., 2] * 0.0722


def normal_map(img, strength=3.0):
    g = np.asarray(img.convert("L").filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0
    dx = (np.roll(g, -1, 1) - np.roll(g, 1, 1)) * strength
    dy = (np.roll(g, -1, 0) - np.roll(g, 1, 0)) * strength
    n = np.stack([-dx, dy, np.ones_like(g)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8))
