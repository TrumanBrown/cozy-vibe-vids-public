"""Small image and mask helpers the plate modules share (TASKS.md T16), moved verbatim from plate_prep.py.

  guided_filter     He et al.'s guided filter: snaps a soft mask to the image's edges
  local_var         the local variance of a gray image
  poly_bbox         the box around a region's polygons
  soften            a mask clipped to 0..1 and blurred
  otsu_threshold    the Otsu split of values in 0..1, and how well it separates them
  srgb_to_linear    sRGB values to linear light
"""
import cv2
import numpy as np


def guided_filter(guide, src, r, eps):
    """He et al. guided filter (gray guide): snaps a soft mask to image edges."""
    def box(x):
        return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), normalize=True, borderType=cv2.BORDER_REFLECT)
    mI, mp = box(guide), box(src)
    cov = box(guide * src) - mI * mp
    var = box(guide * guide) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    return box(a) * guide + box(b)


def local_var(gray, r):
    m = cv2.blur(gray, (2 * r + 1, 2 * r + 1))
    m2 = cv2.blur(gray * gray, (2 * r + 1, 2 * r + 1))
    return np.maximum(m2 - m * m, 0)


def poly_bbox(polys):
    """The box (x0, y0, x1, y1, frame fractions) around a region's polygons."""
    pts = [pt for p in polys for pt in p]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def soften(m, sigma):
    return cv2.GaussianBlur(np.clip(m, 0, 1).astype(np.float32), (0, 0), sigma) if sigma > 0 else m


def otsu_threshold(v, bins=256):
    """Otsu split of values in 0..1; returns (threshold, separation 0..1 = between-class / total variance)."""
    h, e = np.histogram(v, bins=bins, range=(0, 1))
    p = h.astype(np.float64) / max(h.sum(), 1)
    c = (e[:-1] + e[1:]) / 2
    w0 = np.cumsum(p)
    m0 = np.cumsum(p * c)
    mt = m0[-1]
    sb = (mt * w0 - m0) ** 2 / np.maximum(w0 * (1 - w0), 1e-12)
    k = int(np.argmax(sb))
    tot = ((c - mt) ** 2 * p).sum()
    return float(e[k + 1]), float(sb[k] / max(tot, 1e-12))


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
