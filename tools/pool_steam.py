#!/usr/bin/env python
"""Steam off a hot spring's whole pool, as a 2D fluid simulation, for src/library/poolsteam.js.

Truman 2026-11-12, the Yuzu Spring: steam rising off the water nonstop is the video's signature motion. steam_sim.py
simulates the plume over one vessel, a bowl or a cup, from its fitted rim. A pool seen from its rim at eye level is
different: every patch of water steams, near and far, each at its own scale on screen, and the steam passes behind
whoever soaks nearer. So the physics runs once, in meters, over a strip of hot water periodic across (stable fluids,
Stam 1999, on the GPU with torch, like steam_sim: semi-Lagrangian and MacCormack advection, a spectral pressure
projection, buoyancy from heat against the box's mean, the room's slow air as curl noise, a slow side draft with no
net drift, vorticity confinement, drag, cooling, condensation a little above the surface, a fade with height), and is
saved as a looping flipbook of visible density. poolsteam.js lays it over the pool as a stack of slices from the far
waterline to the near one, blended in one pass: each slice is the water's row on a ground plane seen from the camera's
height (the horizon row, the camera's height above the water, the focal length), scaled by its distance, hidden behind
what stands in front of it (front.png), lit by the lantern by its distance in 3D and grained like pencil on paper.

This tool also writes the slice table (each slice's row, distance, px per meter, its disparity in the depth map, how
far the water runs across that row, its own offset across the strip, mirroring and time offset, so no two slices show
the same steam at the same moment) and two maps: rows.png, the water under each slice with whatever soaks or floats in
it, and front.png, how many slices stand behind each pixel. A character or a floating fruit hides the slices farther
than where it meets the water, never by its depth: the depth model read the stoat on the far rim as nearer than the
water in front of it. Anything else hides them by its depth (the rocks along the near rim).

usage: .venv\\Scripts\\python tools\\pool_steam.py <scene> [--seconds 120] [--fps 30] [--seed 11] [--set k=v,...]
         [--preview [seconds]] [--sheets-only]
The scene's poolsteam layer gives the water region (`region`), `horizon` (0..1), `camHeight` (m), `focal` (px at
4K), `sheets` (count), `farRow` and `nearRow` (the waterlines the slices run between, frame fractions; default the
water region's own) and `sim` overrides (DEFAULTS below); --set wins.
-> out/plates/<plate>/poolsteam/p_0000.jpg ... and poolsteam.json {version, fps, frames, world [w, h] m, cell, size,
   water_row, scale, gamma, edge_max, down_share, sheets [...], camera {...}, cfg}; --preview: preview.mp4
"""
import argparse
import json
import math
import subprocess
import time

import numpy as np
from PIL import Image

from cozy.paths import ROOT

W4, H4 = 3840, 2160
VERSION = 1          # new_video.py life re-runs a flipbook made by an older version
SCALE = 1.6          # density stored as min(1, rho / SCALE) ** (1 / 2.2), as steam_sim

# The steam's physics, in meters and seconds (tuned on the Yuzu Spring, 2026-11-12).
DEFAULTS = {
    "width": 3.2,          # the strip's width (m), periodic across: sheets read it at their own offsets
    "height": 1.6,         # the box's height (m); the top is a sponge far above anything saved
    "cell": 0.005,         # m per cell
    "band": 0.02,          # the water surface the vapour leaves from (m)
    "rise": 0.07,          # initial rise off the surface (m/s)
    "buoy": 0.55,          # buoyancy (m/s^2 per unit heat)
    "cool": 1.3,           # heat half-life (s)
    "emit": 1.1,           # vapour given off per s at full emission (density units)
    "fade": 1.0,           # visible steam's half-life once it has left the surface (s)
    "soften": 0.25,        # diffusion per step (soft edges)
    "strands": 0.14,       # fine streaks carried by the flow
    "drag": 2.2,           # velocity half-life (s)
    "vort": 0.08,          # vorticity confinement (small curls; 0.12 sent 7% of the steam back down at times)
    "stir": 0.04,          # the night air's slow currents (m/s)
    "draft": 0.035,        # a slow side draft that wanders both ways (m/s; no net drift, so a sheet may be mirrored)
    "patch": 0.7,          # how patchy the emission is across the water (0 = even)
    "puffs": 1.1,          # warm bursts per s per meter of water
    "puff": 0.7,           # puff strength
    "puff_size": 0.07,     # puff radius (m)
    "haze": 0.2,           # share of the emission that is even across the water
    "condense": 0.12,      # s for the vapour to condense into visible steam (it shows a few cm above the water)
    "fade_from": 0.1,      # it starts thinning out this high above the water (m) ...
    "fade_to": 0.75,       # ... and is gone here
    "onset": 0.035,        # and shows only from this high (m): the vapour film on the water itself would draw a bright
                           # line along every sheet's waterline
}
SHEET_DEFAULTS = {"horizon": 0.38, "camHeight": 0.52, "focal": 2700.0, "sheets": 28, "seed": 11}


def load_scene(scene):
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    L = next((L for L in sc.get("layers", []) if L.get("type") == "poolsteam"), None)
    if L is None:
        raise SystemExit(f"pool_steam: scenes/{scene}/scene.json has no poolsteam layer")
    return sc, sc.get("plate", scene), L


class PNoise:
    """Smooth value noise on the GPU, periodic across (u) and in time (whole cycles per loop)."""

    def __init__(self, torch, dev, seed, cx, cy, steps):
        g = torch.Generator(device="cpu").manual_seed(seed)
        self.lat = torch.rand((steps, cy, cx), generator=g).to(dev)
        self.cx, self.cy, self.steps = cx, cy, steps

    def __call__(self, u, v, phase):
        """u in [0, 1) across (periodic), v in [0, 1] up the box, phase in [0, 1)."""
        k = phase * self.steps
        k0 = int(math.floor(k)) % self.steps
        f = k - math.floor(k)
        f = f * f * (3 - 2 * f)
        lat = self.lat[k0] * (1 - f) + self.lat[(k0 + 1) % self.steps] * f
        x = (u % 1.0) * self.cx
        y = v.clamp(0, 1) * (self.cy - 1)
        x0 = x.floor().long() % self.cx
        x1 = (x0 + 1) % self.cx
        y0 = y.floor().long().clamp(0, self.cy - 2)
        fx, fy = x - x.floor(), (y - y0).clamp(0, 1)
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a, b = lat[y0, x0], lat[y0, x1]
        c, d = lat[y0 + 1, x0], lat[y0 + 1, x1]
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def operators(torch, F, dev, nx, ny):
    """The grid, the spectral projection, advection that wraps across (and clamps up and down), the curl, and a 3x3
    max/min/mean that wraps across."""
    ys, xs = torch.meshgrid(torch.arange(ny, device=dev, dtype=torch.float32),
                            torch.arange(nx, device=dev, dtype=torch.float32), indexing="ij")
    kx = 2 * math.pi * torch.fft.rfftfreq(nx, device=dev)
    ky = 2 * math.pi * torch.fft.fftfreq(ny, device=dev)
    KY, KX = torch.meshgrid(ky, kx, indexing="ij")
    K2 = KX * KX + KY * KY
    K2[0, 0] = 1.0

    def project(u):
        U = torch.fft.rfft2(u)
        dot = (KX * U[0] + KY * U[1]) / K2
        return torch.fft.irfft2(torch.stack([U[0] - KX * dot, U[1] - KY * dot]), s=(ny, nx))

    P = 8
    gx, gy = 2 / (nx + 2 * P - 1), 2 / (ny - 1)

    def wrap(f, p):
        return torch.cat([f[..., -p:], f, f[..., :p]], -1)

    def sample(f, px, py):
        grid = torch.stack([(torch.remainder(px, nx) + P) * gx - 1, py * gy - 1], -1)[None]
        return F.grid_sample(wrap(f, P)[None], grid, mode="bilinear", padding_mode="border", align_corners=True)[0]

    def pool3(f, kind):
        g = wrap(f, 1)[None]
        if kind == "max":
            return F.max_pool2d(g, 3, 1, (1, 0))[0]
        if kind == "min":
            return -F.max_pool2d(-g, 3, 1, (1, 0))[0]
        return F.avg_pool2d(g, 3, 1, (1, 0), count_include_pad=False)[0]

    def advect(f, u, h):
        """MacCormack with a min/max limiter."""
        bx, by = xs - u[0] * h, ys - u[1] * h
        fw = sample(f, bx, by)
        fb = sample(fw, xs + u[0] * h, ys + u[1] * h)
        fc = fw + 0.5 * (f - fb)
        return torch.minimum(torch.maximum(fc, sample(pool3(f, "min"), bx, by)), sample(pool3(f, "max"), bx, by))

    def advect_soft(f, u, h):
        return sample(f, xs - u[0] * h, ys - u[1] * h)

    def curl(u):
        dvdx = (torch.roll(u[1], -1, 1) - torch.roll(u[1], 1, 1)) * 0.5
        dudy = (torch.roll(u[0], -1, 0) - torch.roll(u[0], 1, 0)) * 0.5
        return dvdx - dudy
    return xs, ys, project, advect, advect_soft, curl, pool3


def simulate(cfg, seconds, fps, seed, out_dir, log=print):
    import torch
    import torch.nn.functional as F
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    c = cfg["cell"]
    nx, ny = int(round(cfg["width"] / c)), int(round(cfg["height"] / c))
    yw = ny - 6                                    # the water's row (a few cells under it, sponged)
    j0 = max(0, yw - int(math.ceil((cfg["fade_to"] + 0.06) / c)))
    j1 = yw + 2                                    # saved rows: from just above where the steam is gone to the water
    xs, ys, project, advect, advect_soft, curl, pool3 = operators(torch, F, dev, nx, ny)
    hgt = (yw - ys) * c                            # m above the water
    band = ((hgt >= -c) & (hgt <= cfg["band"])).float()
    above = torch.clamp(hgt / 0.08, 0, 1)
    edge = torch.clamp((ys - 0) / (0.12 * ny), 0, 1) * torch.clamp((ny - 1 - ys) / 3.0, 0, 1)
    sponge = 1 - 0.3 * (1 - edge)

    def smooth(e0, e1, v):
        q = torch.clamp((v - e0) / (e1 - e0), 0, 1)
        return q * q * (3 - 2 * q)
    vis_env = (1 - smooth(cfg["fade_from"], cfg["fade_to"], hgt)) * smooth(0.0, cfg["onset"], hgt)

    sub = 4
    dt = 1.0 / (fps * sub)
    warm, xfade = 15.0, 3.0
    n_out, n_x = int(round(seconds * fps)), int(round(xfade * fps))
    n_total = int(round(warm * fps)) + n_out + n_x
    loopN = n_out + n_x
    loop_s = loopN / fps
    u_ = (xs / nx)                                  # across, 0..1 (periodic)
    v_ = (hgt / cfg["height"]).clamp(0, 1)
    patch = PNoise(torch, dev, seed * 7 + 1, int(round(cfg["width"] / 0.35)), 4, max(4, int(round(loop_s / 7))))
    drift = PNoise(torch, dev, seed * 7 + 2, int(round(cfg["width"] / 1.2)), 3, max(4, int(round(loop_s / 12))))
    stirn = PNoise(torch, dev, seed * 7 + 3, int(round(cfg["width"] / 0.25)), 8, max(4, int(round(loop_s / 4))))
    finen = PNoise(torch, dev, seed * 7 + 4, int(round(cfg["width"] / 0.06)), 6, max(8, int(round(loop_s / 1.0))))
    hl = lambda t: math.exp(-math.log(2) * dt / t)  # noqa: E731
    k_cool, k_fade, k_drag = hl(cfg["cool"]), hl(cfg["fade"]), hl(cfg["drag"])
    up, buoy, stir, draft = cfg["rise"] / c, cfg["buoy"] / c, cfg["stir"] / c, cfg["draft"] / c
    rng = np.random.default_rng(seed)
    puffs = []
    u = torch.zeros((2, ny, nx), device=dev)
    rho, heat, age, dye = (torch.zeros((1, ny, nx), device=dev) for _ in range(4))
    log(f"pool steam: {nx} x {ny} cells ({c * 100:.2g} cm), strip {cfg['width']} m, saved rows {j0}..{j1} "
        f"({(j1 - j0) * c:.2f} m), {n_total} frames x {sub} steps on {dev}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("p_*.jpg"):
        p.unlink()

    def write(i, f):
        g = np.clip(f / SCALE, 0, 1) ** (1 / 2.2)
        Image.fromarray((g * 255 + 0.5).astype(np.uint8), "L").save(out_dir / f"p_{i:04d}.jpg", quality=92)

    head, downs, edge_max, k_out = [], [], 0.0, 0
    t = tr = 0.0
    t0 = time.time()
    warm_frames = n_total - n_out - n_x
    for fi in range(n_total):
        for _ in range(sub):
            tl = max(0.0, tr - warm)
            ph = (tl % loop_s) / loop_s
            # emission across the water: patchy and drifting, plus warm puffs here and there
            pn = patch(u_, torch.zeros_like(u_), ph)
            em = (1 - cfg["patch"]) + cfg["patch"] * torch.clamp((pn - 0.25) * 1.6, 0, 1)
            while rng.random() < cfg["puffs"] * cfg["width"] * dt:
                puffs.append([t, rng.uniform(0, cfg["width"]), rng.uniform(0.8, 2.2), cfg["puff"] * rng.uniform(0.6, 1.4)])
            puffs = [q for q in puffs if t - q[0] < q[2]]
            for q in puffs:
                env = math.sin(math.pi * (t - q[0]) / q[2]) ** 2 * q[3]
                dx = (xs * c - q[1] + cfg["width"] / 2) % cfg["width"] - cfg["width"] / 2
                em = em + env * torch.exp(-(dx * dx) / (cfg["puff_size"] ** 2))
            em = em * band
            heat = torch.maximum(heat, em[None])
            add = (cfg["haze"] + (1 - cfg["haze"]) * em)[None] * band[None] * cfg["emit"] * dt
            fine = finen(u_, v_, ph)[None]
            dye = (dye * (rho + age) + fine * add) / (rho + age + add + 1e-6)
            age = age + add
            cnd = age * (1 - math.exp(-dt / cfg["condense"]))
            age, rho = age - cnd, rho + cnd
            # the vapour leaves the water upward; buoyancy against the box's mean (no net lift); a wandering draft
            u[1] = u[1] * (1 - band * 0.5) + band * 0.5 * (-up * (0.6 + 0.6 * em))
            fb = buoy * heat[0]
            u[1] = u[1] - (fb - fb.mean()) * dt
            dn = drift(u_, v_ * 0.5, ph)
            u[0] = u[0] + draft * (dn - 0.5) * 2 * above * dt * 3.0
            # the night air's slow currents: the curl of a smooth stream function, periodic across (the same scale
            # on both components keeps it free of divergence; its rows at the box's top and bottom don't wrap)
            psi = stirn(u_, v_, ph)
            s_ = stir * (nx / stirn.cx) * 2.0
            dpdx = (torch.roll(psi, -1, 1) - torch.roll(psi, 1, 1)) * 0.5
            dpdy = (torch.roll(psi, -1, 0) - torch.roll(psi, 1, 0)) * 0.5
            dpdy[0] = dpdy[-1] = 0
            u[0] = u[0] + s_ * dpdy * dt * above
            u[1] = u[1] - s_ * dpdx * dt * above
            w = curl(u)
            aw = w.abs()
            gxw = (torch.roll(aw, -1, 1) - torch.roll(aw, 1, 1)) * 0.5
            gyw = (torch.roll(aw, -1, 0) - torch.roll(aw, 1, 0)) * 0.5
            nl = torch.sqrt(gxw * gxw + gyw * gyw) + 1e-6
            u[0] = u[0] + cfg["vort"] * (gyw / nl) * w * dt * 60 * (1 - band)
            u[1] = u[1] - cfg["vort"] * (gxw / nl) * w * dt * 60 * (1 - band)
            # transport, projection, decay
            u = advect_soft(u, u, dt)
            u = project(u * sponge[None]) * k_drag
            rho = advect_soft(rho, u, dt) * sponge[None]
            heat = advect(heat, u, dt) * sponge[None]
            age = advect_soft(age, u, dt) * sponge[None]
            dye = advect(dye, u, dt)
            if cfg["soften"] > 0:
                ks = 1 - (1 - cfg["soften"]) ** (dt * 60)
                rho = rho + ks * (pool3(rho, "mean") - rho)
            rho = torch.where(band[None] > 0, rho, rho * k_fade)
            heat = heat * k_cool
            t += dt
            tr += dt
        if fi >= warm_frames:
            st = cfg["strands"]
            vis = rho[0] * vis_env * (1 - st + st * torch.clamp((dye[0] - 0.3) / 0.4, 0, 1))
            vbox = vis[j0:j1]
            if fi % 15 == 0:
                m = max(2, int(0.06 * (j1 - j0)))
                edge_max = max(edge_max, float(vbox[:m].max()))
                # share of the visible steam sinking faster than 1 cm/s (u is in cells per s, y down)
                downs.append(float((vbox * (u[1, j0:j1] > 0.01 / c).float()).sum()) / (float(vbox.sum()) + 1e-6))
            f = vbox.clamp(0, SCALE).detach().cpu().numpy().astype(np.float32)
            if k_out < n_x:
                head.append(f)
            elif k_out < n_out:
                write(k_out, f)
            else:
                i = k_out - n_out
                wx = (i + 0.5) / n_x
                wx = wx * wx * (3 - 2 * wx)
                write(i, wx * head[i] + (1 - wx) * f)
            k_out += 1
        if fi % 300 == 0:
            log(f"  frame {fi}/{n_total} ({time.time() - t0:.0f} s)")
    meta = {"version": VERSION, "fps": fps, "frames": n_out, "world": [cfg["width"], round((j1 - j0) * c, 4)],
            "cell": c, "size": [nx, j1 - j0], "water_row": yw - j0, "gamma": 2.2, "scale": SCALE, "seed": seed,
            "crossfade_s": xfade, "edge_max": round(edge_max / SCALE, 4),
            "down_share": round(float(np.mean(downs)) if downs else 0.0, 4),
            "down_max": round(float(np.max(downs)) if downs else 0.0, 4), "cfg": cfg}
    log(f"pool steam: {n_out} frames -> {out_dir} ({time.time() - t0:.0f} s); steam at the saved box's top "
        f"{meta['edge_max']:.4f} (must be ~0), share moving down {meta['down_share']:.3f}")
    return meta


def sheet_table(plate, L, cfg, seed, pdir=None):
    """The sheets from the far waterline to the near one: rows, distances, scale, disparity, the water's span across
    each row, offsets and weights (module docstring). pdir: the plate's folder (tests)."""
    pdir = pdir or ROOT / "out" / "plates" / plate
    regs = json.loads((pdir / "regions.json").read_text(encoding="utf-8"))
    name = L.get("region")
    g = next((g for g in regs if (g["name"] == name if name else g["kind"] == "water")), None)
    if g is None:
        raise SystemExit(f"pool_steam: no water region {name or '(kind water)'} in {pdir / 'regions.json'}")
    ids = np.asarray(Image.open(pdir / "regions.png").convert("RGB"))[..., 0]
    disp = np.asarray(Image.open(pdir / "depth8.png").convert("L"), np.float32) / 255
    H, W = ids.shape
    if disp.shape != ids.shape:
        disp = np.asarray(Image.fromarray((disp * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32) / 255
    water = ids == g["id"]
    o = {**SHEET_DEFAULTS, **{k: L[k] for k in SHEET_DEFAULTS if k in L}}
    yh, hc, f = float(o["horizon"]), float(o["camHeight"]), float(o["focal"])
    rows = np.flatnonzero(water.sum(1) > 0.05 * W)
    if not len(rows):
        raise SystemExit(f"pool_steam: the water region {g['name']} has no row wider than 5% of the frame")
    # the waterlines the slices run between (frame fractions; the layer's farRow and nearRow override the water's own)
    y_far = float(L.get("farRow", rows.min() / H + 0.004))
    y_near = float(L.get("nearRow", rows.max() / H - 0.004))
    if y_far <= yh:
        raise SystemExit(f"pool_steam: the far waterline ({y_far:.3f}) is above the horizon ({yh}): set the layer's horizon")
    n = int(o["sheets"])
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        y = y_far + (y_near - y_far) * k / max(1, n - 1)
        r0, r1 = int((y - 0.012) * H), int((y + 0.012) * H)
        band = water[max(0, r0):r1]
        xs = np.flatnonzero(band.any(0))
        if len(xs) < 20:
            continue
        x0, x1 = np.percentile(xs, 1) / W, np.percentile(xs, 99) / W
        dv = disp[max(0, r0):r1][band]
        z = f * hc / ((y - yh) * H4)          # the focal length is in px at 4K, whatever the maps' size
        out.append({"y": round(y, 4), "z": round(z, 3), "ppm": round(f / z, 2), "disp": round(float(np.median(dv)), 4),
                    "x0": round(float(x0), 4), "x1": round(float(x1), 4),
                    "offset": round(float(rng.uniform(0, cfg["width"])), 3), "mirror": k % 2 == 1,
                    # three time offsets in all: the layer loads two frames for each, so 6 a frame
                    "toff": [0.0, 40.0, 80.0][k % 3]})
    return out, {"horizon": yh, "camHeight": hc, "focal": f, "water_region": g["name"], "water_id": g["id"]}


# what stands up out of the water and hides the steam behind it by where it meets the water, not by its depth: the
# depth model read the stoat on the far rim as nearer than the water in front of it (0.505 against 0.36 to 0.47), and
# a depth test would have cut a stoat-shaped hole in the steam rising in front of it
UPRIGHT = ("pet", "bob")
FRONT_SCALE = 20       # front.png stores the number of sheets a pixel hides, times this


def sheet_maps(plate, sheets, cam, out_dir, margin=0.05, eps=0.004, pdir=None):
    """rows.png: one row per sheet, the water under it across the frame (at a quarter of the width), with whatever
    soaks or floats in it there (an upright region whose foot is in the water), never what lies on the rocks.
    front.png: at each pixel, how many sheets, counted
    from the far one, stand behind it (times FRONT_SCALE): a character or a floating thing hides the sheets farther
    than where its column meets the water; anything else hides the sheets more than `margin` farther than its own
    depth (depth8 units). Nested by construction, so poolsteam.js needs one number per pixel. pdir: the plate's
    folder (tests)."""
    pdir = pdir or ROOT / "out" / "plates" / plate
    regs = json.loads((pdir / "regions.json").read_text(encoding="utf-8"))
    ids = np.asarray(Image.open(pdir / "regions.png").convert("RGB"))[..., 0]
    disp = np.asarray(Image.open(pdir / "depth8.png").convert("L"), np.float32) / 255
    H, W = ids.shape
    water = ids == cam["water_id"]
    upright = np.isin(ids, [r["id"] for r in regs if r["kind"] in UPRIGHT])
    # rows.png: the water across each sheet's row, and whatever stands in the water there (a soaking character, a
    # floating fruit: an upright run whose foot is in the water), never what lies on the rocks (the stoat's long body)
    q = 4
    wet_foot = np.zeros((H, W), bool)
    for rid in np.unique(ids[upright]):
        reg = ids == rid
        for x in np.flatnonzero(reg.any(0)):
            y = np.flatnonzero(reg[:, x])
            cuts = np.flatnonzero(np.diff(y) > 1)
            for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, len(y) - 1]):
                foot = y[b] + 1
                if water[foot:foot + max(3, H // 300), x].any():
                    wet_foot[y[a]:foot, x] = True
    rows = np.zeros((len(sheets), W // q), np.float32)
    for k, s in enumerate(sheets):
        r0, r1 = max(0, int((s["y"] - 0.012) * H)), int((s["y"] + 0.012) * H)
        wat = water[r0:r1].any(0) | wet_foot[r0:r1].any(0)
        col = wat.reshape(-1, q).mean(1)
        rows[k] = np.convolve(np.pad(col, 6, mode="edge"), np.ones(13) / 13, mode="valid")
    Image.fromarray((np.clip(rows, 0, 1) * 255 + 0.5).astype(np.uint8), "L").save(out_dir / "rows.png")
    # front.png: where each upright region meets the water, column by column, region by region (merged, the stoat
    # lying on the far rim above the monkey took the monkey's waterline and cut a vertical edge into the steam)
    ys_ = np.array([s["y"] for s in sheets], np.float32)
    ds_ = np.array([s["disp"] for s in sheets], np.float32)
    base = np.zeros((H, W), np.float32)
    for rid in np.unique(ids[upright]):
        reg = ids == rid
        for x in np.flatnonzero(reg.any(0)):
            y = np.flatnonzero(reg[:, x])
            cuts = np.flatnonzero(np.diff(y) > 1)
            for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, len(y) - 1]):
                base[y[a]:y[b] + 1, x] = (y[b] + 1) / H
    n_up = (ys_[None, None, :] < base[..., None] - eps).sum(-1)
    n_dp = (ds_[None, None, :] + margin < disp[..., None]).sum(-1)
    front = np.where(upright, n_up, n_dp).astype(np.float32)
    front = cv2_blur(front, 1.2)
    Image.fromarray(np.clip(front * FRONT_SCALE + 0.5, 0, 255).astype(np.uint8), "L").save(out_dir / "front.png")
    # a look at it: each sheet's hidden part tinted, nearer sheets warmer
    pv = np.asarray(Image.open(pdir / "plate.png").convert("RGB").resize((W // 2, H // 2), Image.LANCZOS), np.float32)
    fr = np.asarray(Image.fromarray(front).resize((W // 2, H // 2), Image.BILINEAR), np.float32) / max(1, len(sheets))
    tint = np.stack([fr, 0.4 * np.ones_like(fr), 1 - fr], -1) * 255
    Image.fromarray(np.clip(pv * 0.55 + tint * 0.45 * (fr[..., None] > 0), 0, 255).astype(np.uint8)).save(out_dir / "front_preview.jpg", quality=88)
    return {"rows": rows.shape, "hidden_share": round(float((front > 0.5).mean()), 4)}


def cv2_blur(a, sigma):
    import cv2
    return cv2.GaussianBlur(a, (0, 0), sigma)


def preview(plate, meta, out_dir, seconds):
    """A first look without the renderer: the strip as it is (no sheets), white on black, at its own size x2."""
    n = min(meta["frames"], int(seconds * meta["fps"]))
    w, h = meta["size"]
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                          "-s", f"{w}x{h}", "-r", str(meta["fps"]), "-i", "-", "-vf", "scale=iw*2:ih*2:flags=bicubic",
                          "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out_dir / "preview.mp4")],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(np.asarray(Image.open(out_dir / f"p_{i:04d}.jpg").convert("L")).tobytes())
    p.stdin.close()
    p.wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--seconds", type=float, help="loop length (default: the scene's loopSeconds, 120)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--set", default="", help="physics overrides k=v,... (see DEFAULTS)")
    ap.add_argument("--preview", nargs="?", const=20.0, type=float, help="write preview.mp4 of the first N s (20)")
    ap.add_argument("--sheets-only", action="store_true", help="rewrite the sheet table only (no simulation)")
    a = ap.parse_args()
    sc, plate, L = load_scene(a.scene)
    cfg = {**DEFAULTS, **{k: float(v) for k, v in (L.get("sim") or {}).items() if k in DEFAULTS}}
    for kv in filter(None, a.set.split(",")):
        k, v = kv.split("=")
        if k not in DEFAULTS:
            raise SystemExit(f"--set {k}: not a pool steam setting ({', '.join(DEFAULTS)})")
        cfg[k] = float(v)
    seed = a.seed if a.seed is not None else int(L.get("seed", SHEET_DEFAULTS["seed"]))
    seconds = a.seconds or float(sc.get("loopSeconds", 120))
    out_dir = ROOT / "out" / "plates" / plate / "poolsteam"
    js = out_dir / "poolsteam.json"
    sheets, cam = sheet_table(plate, L, cfg, seed)
    if a.sheets_only:
        if not js.exists():
            raise SystemExit("pool_steam: --sheets-only needs a simulation first")
        meta = json.loads(js.read_text(encoding="utf-8"))
    else:
        meta = simulate(cfg, seconds, a.fps, seed, out_dir)
    maps = sheet_maps(plate, sheets, cam, out_dir, margin=float(L.get("margin", 0.05)))
    meta.update(sheets=sheets, camera=cam, maps=maps)
    js.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"pool steam: {len(sheets)} sheets, rows {sheets[0]['y']}..{sheets[-1]['y']}, "
          f"{sheets[0]['z']:.2f}..{sheets[-1]['z']:.2f} m -> {js}; look at {out_dir / 'front_preview.jpg'}")
    if a.preview and not a.sheets_only:
        preview(plate, meta, out_dir, a.preview)
        print(f"preview -> {out_dir / 'preview.mp4'}")


if __name__ == "__main__":
    main()
