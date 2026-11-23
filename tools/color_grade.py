"""Color edits for real footage (user 2026-10-23: the fish video looked washed out, the rock nearly white at times;
he wanted highlights, brightness and contrast adjusted the way the iPhone's video editor does, colors only).

iPhone's color sliders, -100 to 100 with 0 as shot: Exposure, Brilliance, Highlights, Shadows, Contrast, Brightness,
Black Point, Saturation, Vibrance, Warmth, Tint. grade() takes the camera's own 10-bit Y'CbCr codes to graded codes; the
editor (tools/color_edit.py) previews it and footage_loop.py renders with it, both through a 3D LUT baked from it, so
what he sees while editing is what renders.

The render applies the LUT to the codes themselves (vf(): the planes moved into an RGB frame without any color
conversion, lut3d, moved back), so nothing clips on the way. The a6700 records above video white (Y' 940 to 1023; in
the aquarium 0.4% of the frame: the top of the rock, the leaves by the light, the gourami's back), which players show as
flat white; Highlights below 0 brings that range back under white with its texture (-20 is enough for all of it).

Sharpness (iPhone's, plus softer below 0; user 2026-10-23: he asked for a sharpness slider in the editor too) is
spatial, so it isn't in the LUT: a 7x7 integer kernel on the luma plane before it (kernel(), ffmpeg's
convolution; sharpen() is the same arithmetic in numpy and the editor's shader does it on the GPU).

How each slider works, on display-referred luminance t (BT.709 R'G'B' through the 2.4 display power, so t is Y' for
greys): Warmth and Tint scale linear R, G, B (white keeps its luminance); Exposure scales linear light (1.5 stops at 100);
Highlights and Shadows scale the light by up to 0.8 and 1 stop, weighted smoothly toward the bright and dark ends (above
0.3 and below 0.5); Contrast is an S-curve through 0.35 that keeps black and white; Brightness moves middle grey (0.5 to
0.63 at 100) with finite slopes at black, so the dark background's noise isn't lifted; all of these scale R'G'B' by
the same ratio, so colors keep their hue. Brilliance is Shadows up, Highlights down and a little Contrast and Vibrance
(Apple: "brighten dark areas, pull in highlights, and add contrast"). Black Point moves black per channel (above 0
deepens, below 0 fades). Saturation scales chroma (0 at -100); Vibrance boosts muted colors and leaves vivid ones.
"""
import hashlib
import json
import math
import pathlib

import numpy as np

SLIDERS = [("exposure", "Exposure"), ("brilliance", "Brilliance"), ("highlights", "Highlights"), ("shadows", "Shadows"),
           ("contrast", "Contrast"), ("brightness", "Brightness"), ("black_point", "Black Point"),
           ("saturation", "Saturation"), ("vibrance", "Vibrance"), ("warmth", "Warmth"), ("tint", "Tint")]
DETAIL = [("sharpness", "Sharpness")]        # spatial, so not in the LUT: kernel(), applied before it
ALL = SLIDERS + DETAIL
KEYS = [k for k, _ in SLIDERS]               # the color sliders (the LUT)
ALL_KEYS = [k for k, _ in ALL]
HELP = {"sharpness": "Fine detail, on brightness only. Above 0 crisper, below 0 softer. Judge it at 100%."}
KR, KB = 0.2126, 0.0722                      # BT.709
KG = 1.0 - KR - KB
CR_R, CB_B = 2 * (1 - KR), 2 * (1 - KB)      # R' = Y' + CR_R Cr, B' = Y' + CB_B Cb
CB_G, CR_G = CB_B * KB / KG, CR_R * KR / KG  # G' = Y' - CB_G Cb - CR_G Cr
GAMMA = 2.4
PIVOT = 0.35                                 # Contrast's pivot: about the aquarium's middle (median Y' 0.30)
LUT_N = 65                                   # the render's LUT: 16 codes between points, tetrahedral
SHARP_B = np.array([1, 6, 15, 20, 15, 6, 1], float)   # binomial 7 taps: a Gaussian of 1.22 px
SHARP_SCALE = 1 << 18                        # the kernel in integers over 2^18 (ffmpeg's convolution takes integers)


def clean(g):
    """The look as {slider: int}, zeros left out; unknown keys or values outside -100..100 are errors."""
    if g is not None and not isinstance(g, dict):
        raise ValueError('a look is a set of sliders, like {"highlights": -20}')
    out = {}
    for k, v in (g or {}).items():
        if k.startswith("_"):
            continue
        if k not in ALL_KEYS:
            raise ValueError(f"unknown slider {k!r} (sliders: {', '.join(ALL_KEYS)})")
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = math.nan
        if not math.isfinite(f) or abs(f - round(f)) > 1e-9:
            raise ValueError(f"{k} {v!r}: the sliders take whole numbers from -100 to 100")
        v = int(round(f))
        if not -100 <= v <= 100:
            raise ValueError(f"{k} {v} is outside -100..100")
        if v:
            out[k] = v
    return out


def color(g):
    """The color part of a look (what the LUT holds)."""
    return {k: v for k, v in clean(g).items() if k in KEYS}


def kernel(g):
    """Sharpness as ffmpeg's convolution takes it: 49 integers (a 7x7 kernel, row by row) and rdiv; None at 0.
    The kernel is (1 + a) at the center minus a times a 7x7 binomial blur (1.22 px): above 0 an unsharp mask (amount
    1.5 at 100), below 0 a blend toward the blur (75% at -100). Rounded to integers over 2^18 with the center set so
    they sum to exactly 2^18 (flat areas keep their level)."""
    s = clean(g).get("sharpness", 0) / 100.0
    if not s:
        return None
    a = 1.5 * s if s > 0 else 0.75 * s
    K = -a * np.outer(SHARP_B, SHARP_B) / SHARP_B.sum() ** 2
    K[3, 3] += 1 + a
    Ki = np.round(K * SHARP_SCALE).astype(np.int64)
    Ki[3, 3] += SHARP_SCALE - Ki.sum()
    return Ki.ravel().tolist(), 1.0 / SHARP_SCALE


def sharpen(Y, g):
    """The kernel on a luma plane of codes, exactly as ffmpeg's convolution does it (edges mirrored without repeating
    the edge pixel, as it does: -1 reads 1; rounded half up; clipped to 0..1023); Y unchanged at 0."""
    kk = kernel(g)
    if kk is None:
        return np.asarray(Y)
    K, rdiv = np.array(kk[0], np.int64).reshape(7, 7), kk[1]
    Y = np.asarray(Y, np.int64)
    h, w = Y.shape
    mir = lambda i, n: np.where(i < 0, -i, np.where(i >= n, 2 * n - 2 - i, i))
    xs, ys = np.arange(w), np.arange(h)
    acc = np.zeros((h, w), np.int64)
    for j in range(7):
        rows = Y[mir(ys + j - 3, h)]
        for i in range(7):
            acc += K[j, i] * rows[:, mir(xs + i - 3, w)]
    return np.clip(np.floor(acc.astype(np.float64) * rdiv + 0.5), 0, 1023)


def key(g):
    """A short hash of the grade and the grading code (a new look or new math makes a new LUT)."""
    from cozy.code import code_hash
    return hashlib.sha1(code_hash("color_grade").encode() + json.dumps(clean(g), sort_keys=True).encode()).hexdigest()[:12]


def _smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _spow(x, p):
    return np.sign(x) * np.abs(x) ** p


def params(g):
    """Slider values (-100..100) to the curve parameters."""
    g = clean(g)
    v = {k: g.get(k, 0) / 100.0 for k in KEYS}
    br = v["brilliance"]
    return {"wb": (0.3 * v["warmth"], -0.2 * v["tint"]),
            "ev": 1.5 * v["exposure"],
            "hi": float(np.clip(v["highlights"] - 0.5 * br, -1.15, 1.15)),
            "sh": float(np.clip(v["shadows"] + 0.5 * br, -1.15, 1.15)),
            "k": float(2 ** (0.7 * np.clip(v["contrast"] + 0.25 * br, -1.25, 1.25))),
            "mid": 0.5 + 0.13 * v["brightness"],
            "bp": v["black_point"],
            "sat": v["saturation"],
            "vib": float(np.clip(v["vibrance"] + 0.15 * br, -1.0, 1.0))}


def tone(t, P):
    """The tone curve on display-referred luminance t >= 0 (Highlights, Shadows, Contrast, Brightness)."""
    hi, sh, k, mid = P["hi"], P["sh"], P["k"], P["mid"]
    x = t * np.exp2(sh * 1.0 * (1 - _smooth(0.0, 0.5, t)) + hi * (0.8 if hi < 0 else 0.5) * _smooth(0.3, 1.0, t))
    if k != 1.0:                              # S-curve: slope k at the pivot, 1/k at black and at white, linear above white
        p = PIVOT
        A, B = k - 1, (1 - k) / k
        u = x / p
        v = np.minimum((x - p) / (1 - p), 1.0)
        lo = p * u / (A * (1 - u) + 1)
        hi_ = p + (1 - p) * v / (B * (1 - v) + 1)
        x = np.where(x < p, lo, np.where(x <= 1.0, hi_, 1.0 + (x - 1.0) / k))
    if mid != 0.5:                            # Schlick bias: 0.5 -> mid, slope mid/(1-mid) at black, linear above white
        C = 1 / mid - 2
        xc = np.minimum(x, 1.0)
        x = np.where(x <= 1.0, xc / (C * (1 - xc) + 1), 1.0 + (1 + C) * (x - 1.0))
    return x


def grade(Y, U, V, g):
    """Graded codes for 10-bit Y'CbCr codes (float arrays of one shape, chroma at the luma's positions), clipped 0..1023.
    The color sliders only: Sharpness is spatial (sharpen(), before this)."""
    P = params(g)
    if not color(g):
        return Y.astype(np.float64), U.astype(np.float64), V.astype(np.float64)
    y = (np.asarray(Y, np.float64) - 64) / 876
    cb = (np.asarray(U, np.float64) - 512) / 896
    cr = (np.asarray(V, np.float64) - 512) / 896
    R, G, B = y + CR_R * cr, y - CB_G * cb - CR_G * cr, y + CB_B * cb
    # white balance and exposure: a gain per channel in linear light is a gain on R'G'B' (the power law is homogeneous)
    w, ti = P["wb"]
    m = np.array([2 ** w, 2 ** ti, 2 ** -w])
    m = m / (KR * m[0] + KG * m[1] + KB * m[2]) * 2 ** P["ev"]
    a = m ** (1 / GAMMA)
    R, G, B = R * a[0], G * a[1], B * a[2]
    # tone on luminance, applied as one ratio to R'G'B'
    t = np.abs(_spow(KR * _spow(R, GAMMA) + KG * _spow(G, GAMMA) + KB * _spow(B, GAMMA), 1 / GAMMA))
    ts = np.maximum(t, 1e-5)
    r = tone(ts, P) / ts
    R, G, B = R * r, G * r, B * r
    bp = P["bp"]
    if bp > 0:                                # deeper black: levels with a soft toe, 0 stays 0
        beta = 0.06 * bp
        eps = beta / 3

        def lv(x):
            sp = lambda z: eps * np.logaddexp(0.0, z / eps)
            return (sp(x - beta) - sp(-beta)) / (1 - beta)
        R, G, B = lv(R), lv(G), lv(B)
    elif bp < 0:                              # faded black
        lam = 0.05 * -bp
        R, G, B = lam + (1 - lam) * R, lam + (1 - lam) * G, lam + (1 - lam) * B
    y2 = KR * R + KG * G + KB * B
    cb2, cr2 = (B - y2) / CB_B, (R - y2) / CR_R
    f = 1.0 + (P["sat"] if P["sat"] < 0 else 0.75 * P["sat"])
    if P["vib"]:
        mag = np.sqrt(cb2 * cb2 + cr2 * cr2)
        f = f * (1.0 + 0.75 * P["vib"] * (1 - _smooth(0.0, 0.25, mag)))
    cb2, cr2 = cb2 * f, cr2 * f
    return (np.clip(64 + 876 * y2, 0, 1023), np.clip(512 + 896 * cb2, 0, 1023), np.clip(512 + 896 * cr2, 0, 1023))


def lut(g, n=LUT_N, order="yuv"):
    """The grade sampled on an n^3 grid of codes 0..1023, normalized 0..1, float32.
    order "yuv": shape (n_V, n_U, n_Y, 3) with (Y', U', V'), Y fastest (the editor's 3D texture: x = Y, y = U, z = V).
    order "cube": shape (n_U, n_Y, n_V, 3) with (V', Y', U'), V fastest: the .cube order (R fastest) for frames whose
    G, B, R planes hold Y, U, V (vf())."""
    c = np.linspace(0, 1023, n)
    if order == "yuv":
        V, U, Y = np.meshgrid(c, c, c, indexing="ij")
    else:
        U, Y, V = np.meshgrid(c, c, c, indexing="ij")
    Y2, U2, V2 = grade(Y, U, V, g)
    out = (Y2, U2, V2) if order == "yuv" else (V2, Y2, U2)
    return (np.stack(out, -1) / 1023).astype(np.float32)


def write_cube(g, path, n=LUT_N):
    a = lut(g, n, "cube").reshape(-1, 3)
    body = "\n".join(f"{r:.7f} {gg:.7f} {b:.7f}" for r, gg, b in a.tolist())
    path.write_text(f"TITLE \"cozy-vibe-vids grade {json.dumps(color(g), sort_keys=True)}\"\n# axes: R = Cr code, G = Y' code, "
                    f"B = Cb code (all /1023), see tools/color_grade.py vf()\nLUT_3D_SIZE {n}\n{body}\n")


def ff_path(p):
    """A path for an ffmpeg filter option (Windows: C:/... with the drive colon escaped)."""
    return pathlib.Path(p).resolve().as_posix().replace(":", r"\:")


def vf(g, cache_dir):
    """The ffmpeg filters that apply the look to 10-bit Y'CbCr frames (any subsampling): Sharpness first, on the luma
    plane alone (convolution with kernel(), chroma planes copied), then the color sliders as the 3D LUT (written to
    cache_dir/grade_<key>.cube). Out as yuv444p10le with BT.709 limited-range tags; None when every slider is 0."""
    g = clean(g)
    if not g:
        return None
    parts = []
    kk = kernel(g)
    if kk is not None:
        parts.append(f"convolution=0m='{' '.join(str(v) for v in kk[0])}':0rdiv={kk[1]!r}:0bias=0:0mode=square")
    c = color(g)
    if c:
        cache_dir = pathlib.Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"grade_{key(c)}.cube"
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            write_cube(c, tmp)
            tmp.replace(path)
        parts.append(f"format=yuv444p10le,mergeplanes=format=gbrp10le:map1p=1:map2p=2,"
                     f"lut3d=file='{ff_path(path)}':interp=tetrahedral,"
                     f"mergeplanes=format=yuv444p10le:map1p=1:map2p=2")
    else:
        parts.append("format=yuv444p10le")
    parts.append("setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")
    return ",".join(parts)


def describe(g):
    g = clean(g)
    return ", ".join(f"{dict(ALL)[k]} {v:+d}" for k, v in g.items()) if g else "as shot"
