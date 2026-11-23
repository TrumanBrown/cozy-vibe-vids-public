#!/usr/bin/env python
"""Steam over a vessel as a 2D fluid simulation, saved as a looping flipbook for src/library/steam.js.

User 2026-10-19 (round 2): the ramen bowl's steam was still too wispy, and he asked for research into how real steam
looks. Real
soup steam is condensed droplets: densest just above the hot surface (a low haze over the whole broth), smooth for
a little while as it rises, then breaking into soft curls that thin out and vanish within about a bowl width;
against a dark street, lit by the stall, it glows. Round 3, on the first simulation: far too heavy and not
subtle, the box's outline showing at the top, and the steam rolling back down. The plume is now faint
and soft, rises gently and only sways; the simulation box is far bigger
than what is saved (a box the size of the plume acted as a ceiling, so the steam pooled under it in a flat layer
and rolled back down the sides), there is no net lift on the box, and the steam is gone well inside the saved box.
Round 4: the bowl's plume was right, but the tea cup's two procedural wisps read as two separate sources. Every
vessel with a measured opening, cup or bowl, now gets this simulation, scaled to it: the same grid relative to the
opening (so the same detail), and the time scale of a buoyant plume, which goes as the square root of its real size
(Froude scaling: a cup's steam is no slow-motion copy of a bowl's). The real size is the region's `size_cm`
(hand.json), else a guess from its name (a cup 8 cm, a bowl 20, a pot 26).

The physics runs once per scene (stable fluids, Stam 1999, on the GPU with torch):
  * semi-Lagrangian advection (MacCormack for heat and the strands), an exact pressure projection (spectral,
    periodic, in a box ~5.6 x 4 half-widths whose sponge edges are far from anything saved),
  * buoyancy from heat relative to the box's mean (hot vapour rises, it cools and slows), a little vorticity
    confinement, the room's slow air currents, a slow draft and the scene's lean, drag, cooling,
  * the source: the vessel's opening (regions.json `opening`, fitted to the rim by plate_prep) filled with a patchy
    emission that drifts, with small puffs here and there, so the whole surface steams, never a row of jets,
  * condensation (it shows a little above the surface), evaporation, and a fade with height and to the sides.

Frames hold density only (gamma 2.2, 8 bit); steam.js shades them with the plate's light (bright on dark, almost
gone on bright, self-shadowed from above). The loop closes with a short crossfade of the last frames into the
first. steam.json records `edge_max` (steam left at the saved box's edges: must be ~0) and `down_share` (share of
the steam moving down: must stay small); tools/review.py checks both. Deterministic: same scene, region, seed and
settings give the same frames.

usage: .venv\\Scripts\\python tools\\steam_sim.py <scene> [--region ramen_bowl] [--seconds 120] [--fps 30]
         [--cell px] [--seed 7] [--set k=v,...] [--preview [seconds]] [--out dir]
-> out/plates/<plate>/steam/<region>/s_0000.jpg ... and steam.json {version, fps, frames, box: [x0, y0, x1, y1]
   (px at 4K), size, gamma, cell, scale, size_cm, tempo, edge_max, down_share, cfg}; --preview: preview.mp4
"""
import argparse
import json
import math
import pathlib
import subprocess
import time

import numpy as np
from PIL import Image

from cozy.paths import ROOT
W4, H4 = 3840, 2160
VERSION = 3          # new_video.py life re-runs a plume made by an older version

# Look of the plume (lengths in opening half-widths, times in simulated seconds: `tempo` of them pass per real second).
# Tuned on the ramen bowl (913 px across, 20 cm).
DEFAULTS = {
    "rise": 0.5,           # initial rise at the surface, opening half-widths per s
    "buoy": 1.0,           # buoyancy, half-widths per s^2 per unit heat
    "cool": 0.9,           # heat half-life, s
    "emit": 1.2,           # vapour given off per s at full emission (density units)
    "fade": 0.5,           # visible-steam half-life once it has left the surface, s (it mixes and evaporates)
    "evap": 0.0,           # a steady loss on top (density per s); above ~0.02 it cuts a hard outline into the plume
    "soften": 0.3,         # diffusion per step (soft edges; 0 = ink-sharp)
    "strands": 0.12,       # fine streaks inside the plume (a dye of noise from the surface, carried by the flow)
    "drag": 2.0,           # velocity half-life, s (short: no big rolling vortices)
    "vort": 0.12,          # vorticity confinement (small curls only)
    "stir": 0.16,          # the room's slow air currents (curl noise), half-widths per s: gentle S-bends
    "draft": 0.05,         # slow side draft, half-widths per s (sways the plume)
    "lean": 0.0,           # steady lean (-1..1; the scene's steam layer `lean`: the ramen alley's -0.2 is set there; a
                           # default of -0.2 bent the farm porch mug's plume over to one side, 2026-10-21)
    "patch": 0.75,         # how patchy the emission is over the surface (0 = even)
    "puffs": 1.5,          # puffs per s over the whole surface: small warm bursts
    "puff": 0.6,           # puff strength
    "puff_size": 0.28,     # puff radius, opening half-widths
    "haze": 0.15,          # share of the emission that is even over the surface
    "condense": 0.1,       # s for the vapour to condense into visible steam (it shows a few cm above the surface)
    "sharp": 0.0,          # 1: MacCormack for the velocity too (crisper, more ragged curls)
    "fade_from": 0.8,      # it starts thinning out this many opening half-widths above the far rim ...
    "fade_to": 1.6,        # ... and is gone here (a ramen bowl: about 17 cm)
    "side_from": 1.1,      # and to each side, from the opening's center
    "side_to": 1.5,
    "tempo": 0.0,          # sim seconds per real second; 0: from the vessel's real size, sqrt(REF_CM / size_cm)
}
SCALE = 1.6                # density stored as min(1, rho / SCALE) ** (1 / 2.2)
CELLS = 152                # cells per opening half-width at most (the ramen bowl at 3 px): smaller vessels, same detail
REF_CM = 20.0              # real opening of the vessel the DEFAULTS were tuned on (the ramen bowl)
# a vessel's real opening (cm) from its name when the region has no `size_cm`: the first group that matches, and how
# far above the surface its steam starts to show (`onset_cm`; steam.js): hot soup or boiling water fogs right at the
# surface, a drink at drinking heat gives off less vapour, which shows only once it has mixed with the air a little
# (round 4: with no onset a fog film over the tea hid it)
SIZES_CM = [(("cauldron",), 45.0, 0.0), (("teapot",), 10.0, 1.0), (("pot", "pan", "wok", "kettle", "nabe"), 26.0, 0.0),
            (("bowl", "ramen", "soup", "noodle", "pho", "udon", "stew", "porridge"), 20.0, 0.0),
            (("cup", "mug", "tea", "coffee", "latte", "cocoa", "chocolate", "yunomi", "glass", "chai", "matcha", "cider"), 8.0, 1.0)]


def vessel_cm(g):
    """(real opening in cm, steam onset in cm) of a steam region: its `size_cm` / `onset_cm`, else from its name."""
    n = f"{g.get('name', '')} {g.get('label', '')}".lower()
    cm, onset = next(((cm, on) for keys, cm, on in SIZES_CM if any(k in n for k in keys)), (REF_CM, 0.0))
    return float(g.get("size_cm") or cm), float(g.get("onset_cm", onset))


def load_scene(scene):
    sc = json.loads((ROOT / "scenes" / scene / "scene.json").read_text(encoding="utf-8"))
    return sc, sc.get("plate", scene)


def regions_of(plate):
    r = json.loads((ROOT / "out" / "plates" / plate / "regions.json").read_text(encoding="utf-8"))
    return r["regions"] if isinstance(r, dict) and "regions" in r else r


class Noise:
    """Smooth value noise on the GPU, periodic in time with a whole number of cycles per loop."""

    def __init__(self, torch, dev, seed, cells, steps):
        g = torch.Generator(device="cpu").manual_seed(seed)
        self.t, self.dev = torch, dev
        self.lat = torch.rand((steps, cells, cells), generator=g).to(dev)
        self.cells, self.steps = cells, steps

    def __call__(self, u, v, phase):
        """u, v in [0, 1) (tensors), phase in [0, 1): bilinear in space, smooth in time."""
        k = phase * self.steps
        k0 = int(math.floor(k)) % self.steps
        k1 = (k0 + 1) % self.steps
        f = k - math.floor(k)
        f = f * f * (3 - 2 * f)
        lat = self.lat[k0] * (1 - f) + self.lat[k1] * f
        x, y = u * (self.cells - 1), v * (self.cells - 1)
        x0, y0 = x.floor().long().clamp(0, self.cells - 2), y.floor().long().clamp(0, self.cells - 2)
        fx, fy = (x - x0).clamp(0, 1), (y - y0).clamp(0, 1)
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a, b = lat[y0, x0], lat[y0, x0 + 1]
        c, d = lat[y0 + 1, x0], lat[y0 + 1, x0 + 1]
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def simulate(opening, cfg, seconds, fps, cell, seed, out_dir, log=print, info=None):
    import torch
    import torch.nn.functional as F
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    cx, cy, a, b, H1, S1, sx0, sy0, nx, ny, i0, i1, j0, j1, x0, x1, y0, y1, A = _sim_boxes(opening, cfg, cell)
    tempo, sub, dtr, dt, warm, xfade, n_out, n_x, n_total = _sim_timing(cfg, seconds, fps)
    log(f"steam sim: {nx} x {ny} cells ({cell:.3g} px), tempo {tempo:.2f}, saved box {x0:.0f},{y0:.0f} - {x1:.0f},{y1:.0f} "
        f"({i1 - i0} x {j1 - j0} cells), {n_total} frames x {sub} steps on {dev}")

    xs, ys, ocy, ob, s_, r_, inside, soft_in, sponge, vis_env = _sim_grid(torch, dev, cfg, cx, cy, b, sx0, sy0, cell, nx, ny, A, H1, S1)
    project, advect, advect_soft, curl = _sim_operators(torch, F, dev, nx, ny, xs, ys)
    u, rho, heat, age, dye = _sim_fields(torch, dev, nx, ny)
    loopN, patch, drift, stirn, finen, stir, sx_, sy_ = _sim_noise(torch, dev, cfg, seed, n_out, n_x, fps, tempo, A, xs, ys, nx, ny)
    rng, puffs, up, buoy, k_cool, k_fade, k_drag, draft, lean, su, rv, above = _sim_forcing(torch, cfg, seed, dt, A, s_, r_, ys, ocy, ob)
    write = _sim_writer(out_dir)
    head = []          # the first n_x frames, kept to close the loop
    edge_max, downs = 0.0, []
    k_out = 0
    t = tr = 0.0
    tstart = time.time()
    warm_frames = n_total - n_out - n_x
    for fi in range(n_total):
        for _ in range(sub):
            ph, em, puffs = _sim_emission(torch, cfg, dt, t, tr, warm, loopN, fps, patch, su, rv, rng, puffs, s_, r_, soft_in)
            heat, dye, age, rho = _sim_vapour(torch, cfg, dt, ph, em, finen, su, rv, soft_in, heat, dye, rho, age)
            _sim_lift(dt, ph, em, u, heat, inside, up, buoy, drift, draft, lean, above, xs, ys, nx, ny)
            _sim_swirl(torch, cfg, dt, ph, u, inside, above, stirn, stir, sx_, sy_, nx, ny, curl)
            u, rho, heat, age, dye = _sim_transport(torch, F, cfg, dt, u, rho, heat, age, dye, advect, advect_soft, project, sponge,
                                                    k_drag, k_fade, k_cool, inside)
            t += dt
            tr += dtr
        if fi >= warm_frames:
            edge_max, k_out = _sim_save_frame(torch, cfg, fi, rho, dye, u, vis_env, i0, i1, j0, j1, A, edge_max, downs, head, k_out,
                                              n_x, n_out, write)
        if fi % 300 == 0:
            log(f"  frame {fi}/{n_total} ({time.time() - tstart:.0f} s)")
    down = float(np.mean(downs)) if downs else 0.0
    meta = {"version": VERSION, "fps": fps, "frames": n_out, "box": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
            "size": [i1 - i0, j1 - j0], "sim_size": [nx, ny], "cell": cell, "gamma": 2.2, "scale": SCALE,
            "opening": [round(cx, 1), round(cy, 1), round(a, 1), round(b, 1)], "seed": seed, "crossfade_s": xfade,
            "edge_max": round(edge_max / SCALE, 4), "down_share": round(down, 4),
            "down_max": round(float(np.max(downs)) if downs else 0.0, 4), "cfg": cfg, **(info or {})}
    (out_dir / "steam.json").write_text(json.dumps(meta, indent=1))
    log(f"steam sim: {n_out} frames -> {out_dir} ({time.time() - tstart:.0f} s); steam at the saved box's edges "
        f"{meta['edge_max']:.4f} (must be ~0), share moving down {down:.3f}, at most {meta['down_max']:.3f} (must stay small)")
    return meta


def _sim_boxes(opening, cfg, cell):
    """(the opening's center and half-axes in px, fade_to, side_to, the simulation box's corner in px and its size in
    cells, the saved box in cells and in px, the opening's half-width in cells)."""
    cx, cy, a, b = opening[0] * W4, opening[1] * H4, opening[2] * W4, opening[3] * H4
    # What is saved (the output box) ends a quarter half-width past where the steam is gone: fade_to half-widths
    # above the far rim, side_to to each side. The simulation runs in a much bigger box around it: in a periodic
    # solver the size of the plume, the box's top acts as a ceiling and its sides as walls (v8: the plume hit the
    # top, pooled into a flat layer with a visible edge and rolled back down the sides; user 2026-10-19, round 3).
    H1, S1 = cfg["fade_to"], cfg["side_to"]
    sx0, sy0 = cx - 2.8 * a, cy - b - 3.4 * a
    nx, ny = int(round(5.6 * a / cell)), int(round((3.5 * a + 2 * b) / cell))
    i0 = int(math.floor((cx - (S1 + 0.25) * a - sx0) / cell))
    i1 = int(math.ceil((cx + (S1 + 0.25) * a - sx0) / cell))
    j0 = int(math.floor((cy - b - (H1 + 0.25) * a - sy0) / cell))
    j1 = min(ny, int(math.ceil((cy + b + 0.06 * a - sy0) / cell)))
    x0, x1, y0, y1 = sx0 + i0 * cell, sx0 + i1 * cell, sy0 + j0 * cell, sy0 + j1 * cell
    A = a / cell                      # half-width in cells
    return cx, cy, a, b, H1, S1, sx0, sy0, nx, ny, i0, i1, j0, j1, x0, x1, y0, y1, A


def _sim_timing(cfg, seconds, fps):
    # a smaller vessel's plume evolves faster (tempo: simulated seconds per real second), in more steps per frame;
    # all the physics below runs on simulated time (dt), the loop and its noise on real time (dtr)
    tempo = float(cfg.get("tempo") or 1.0)
    sub = max(4, int(math.ceil(4 * tempo - 1e-6)))
    dtr = 1.0 / (fps * sub)
    dt = dtr * tempo
    warm, xfade = 12.0, 3.0
    n_out = int(round(seconds * fps))
    n_x = int(round(xfade * fps))
    n_total = int(round(warm * fps)) + n_out + n_x
    return tempo, sub, dtr, dt, warm, xfade, n_out, n_x, n_total


def _sim_grid(torch, dev, cfg, cx, cy, b, sx0, sy0, cell, nx, ny, A, H1, S1):
    """The grid, the opening and the surface on it, the sponge at the box's edges and where the steam may show."""
    ys, xs = torch.meshgrid(torch.arange(ny, device=dev, dtype=torch.float32), torch.arange(nx, device=dev, dtype=torch.float32), indexing="ij")
    # the opening in cells, and the surface coordinates (s across -1..1, r depth -1 far .. 1 near)
    ocx, ocy, ob = (cx - sx0) / cell, (cy - sy0) / cell, b / cell
    s_, r_ = (xs - ocx) / A, (ys - ocy) / ob
    rr = s_ * s_ + r_ * r_
    inside = (rr < 1).float()
    soft_in = torch.clamp((1 - rr) / 0.12, 0, 1)
    # sponge: fields fade to zero near the simulation's edges, far from anything saved
    def ramp(d, w):
        return torch.clamp(d / w, 0, 1)
    edge = ramp(xs, 0.06 * nx) * ramp(nx - 1 - xs, 0.06 * nx) * ramp(ys, 0.08 * ny) * ramp(ny - 1 - ys, 0.01 * ny)
    sponge = 1 - 0.25 * (1 - edge)

    # where it shows: it thins out as it rises (it mixes with dry air and evaporates) and is gone by fade_to
    # half-widths above the far rim and side_to to each side, so no edge of the saved box can ever show
    def smooth(e0, e1, v):
        q = torch.clamp((v - e0) / (e1 - e0), 0, 1)
        return q * q * (3 - 2 * q)
    hgt = (ocy - ob - ys) / A
    vis_env = (1 - smooth(cfg["fade_from"], H1, hgt)) * (1 - smooth(cfg["side_from"], S1, (xs - ocx).abs() / A))
    return xs, ys, ocy, ob, s_, r_, inside, soft_in, sponge, vis_env


def _sim_operators(torch, F, dev, nx, ny, xs, ys):
    """The pressure projection, the two advections and the curl on this grid."""
    kx = 2 * math.pi * torch.fft.rfftfreq(nx, device=dev)
    ky = 2 * math.pi * torch.fft.fftfreq(ny, device=dev)
    KY, KX = torch.meshgrid(ky, kx, indexing="ij")
    K2 = KX * KX + KY * KY
    K2[0, 0] = 1.0

    def project(u):
        U = torch.fft.rfft2(u)
        dot = (KX * U[0] + KY * U[1]) / K2
        U0, U1 = U[0] - KX * dot, U[1] - KY * dot
        return torch.fft.irfft2(torch.stack([U0, U1]), s=(ny, nx))

    gx, gy = 2 / (nx - 1), 2 / (ny - 1)

    def sample(f, px, py, pad="zeros"):
        grid = torch.stack([px * gx - 1, py * gy - 1], -1)[None]
        return F.grid_sample(f[None], grid, mode="bilinear", padding_mode=pad, align_corners=True)[0]

    def advect(f, u, h, pad="zeros"):
        """MacCormack with a min/max limiter."""
        bx, by = xs - u[0] * h, ys - u[1] * h
        fw = sample(f, bx, by, pad)
        fb = sample(fw, xs + u[0] * h, ys + u[1] * h, pad)
        fc = fw + 0.5 * (f - fb)
        mx = sample(F.max_pool2d(f[None], 3, 1, 1)[0], bx, by, pad)
        mn = sample(-F.max_pool2d(-f[None], 3, 1, 1)[0], bx, by, pad)
        return torch.minimum(torch.maximum(fc, mn), mx)

    def advect_soft(f, u, h, pad="zeros"):
        """Plain semi-Lagrangian: a little diffusive, which suits steam's soft edges."""
        return sample(f, xs - u[0] * h, ys - u[1] * h, pad)

    def curl(u):
        dvdx = (torch.roll(u[1], -1, 1) - torch.roll(u[1], 1, 1)) * 0.5
        dudy = (torch.roll(u[0], -1, 0) - torch.roll(u[0], 1, 0)) * 0.5
        return dvdx - dudy
    return project, advect, advect_soft, curl


def _sim_fields(torch, dev, nx, ny):
    u = torch.zeros((2, ny, nx), device=dev)
    rho = torch.zeros((1, ny, nx), device=dev)
    heat = torch.zeros((1, ny, nx), device=dev)
    age = torch.zeros((1, ny, nx), device=dev)       # vapour that has not condensed yet (invisible)
    dye = torch.zeros((1, ny, nx), device=dev)       # fine strands: noise from the surface, stretched by the flow
    return u, rho, heat, age, dye


def _sim_noise(torch, dev, cfg, seed, n_out, n_x, fps, tempo, A, xs, ys, nx, ny):
    loopN = n_out + n_x
    patch = Noise(torch, dev, seed * 7 + 1, 9, max(4, int(round(loopN / fps / 6 * tempo))))
    drift = Noise(torch, dev, seed * 7 + 2, 5, max(4, int(round(loopN / fps / 10 * tempo))))
    stirn = Noise(torch, dev, seed * 7 + 3, 12, max(4, int(round(loopN / fps / 3 * tempo))))
    finen = Noise(torch, dev, seed * 7 + 4, 20, max(8, int(round(loopN / fps / 0.8 * tempo))))
    stir = cfg["stir"] * A
    # the stream function's lattice spans the box: ~0.45 half-widths per lattice cell
    sx_, sy_ = (xs / nx).clamp(0, 1), (ys / ny).clamp(0, 1)
    return loopN, patch, drift, stirn, finen, stir, sx_, sy_


def _sim_forcing(torch, cfg, seed, dt, A, s_, r_, ys, ocy, ob):
    rng = np.random.default_rng(seed)
    puffs = []        # [t0, s, r, life, gain]
    up = cfg["rise"] * A
    buoy = cfg["buoy"] * A
    hl = lambda t: math.exp(-math.log(2) * dt / t)
    k_cool, k_fade, k_drag = hl(cfg["cool"]), hl(cfg["fade"]), hl(cfg["drag"])
    draft, lean = cfg["draft"] * A, cfg["lean"] * 0.25 * A
    su = (s_ * 0.5 + 0.5).clamp(0, 1)
    rv = (r_ * 0.5 + 0.5).clamp(0, 1)
    above = torch.clamp((ocy - ob - ys) / (0.6 * A), 0, 1)      # 0 at the far rim, 1 well above it
    return rng, puffs, up, buoy, k_cool, k_fade, k_drag, draft, lean, su, rv, above


def _sim_writer(out_dir):
    """Clears the folder's old frames; -> write(i, f), which saves frame i."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("s_*.jpg"):
        p.unlink()

    def write(i, f):
        g = np.clip(f / SCALE, 0, 1) ** (1 / 2.2)
        Image.fromarray((g * 255 + 0.5).astype(np.uint8), "L").save(out_dir / f"s_{i:04d}.jpg", quality=92)
    return write


def _sim_emission(torch, cfg, dt, t, tr, warm, loopN, fps, patch, su, rv, rng, puffs, s_, r_, soft_in):
    # time in the loop (the emission and draft repeat with the loop: whole cycles)
    tl = max(0.0, tr - warm)
    ph = (tl % (loopN / fps)) / (loopN / fps)
    # emission over the surface: patchy, drifting, plus puffs
    pn = patch(su, rv, ph)
    em = (1 - cfg["patch"]) + cfg["patch"] * torch.clamp((pn - 0.25) * 1.6, 0, 1)
    while rng.random() < cfg["puffs"] * dt:
        rr0 = math.sqrt(rng.random())
        th = rng.uniform(0, 2 * math.pi)
        puffs.append([t, rr0 * math.cos(th), rr0 * math.sin(th), rng.uniform(0.8, 2.0), cfg["puff"] * rng.uniform(0.6, 1.4)])
    puffs = [p for p in puffs if t - p[0] < p[3]]
    for p in puffs:
        pa = (t - p[0]) / p[3]
        env = math.sin(math.pi * pa) ** 2 * p[4]
        ps = cfg["puff_size"]
        em = em + env * torch.exp(-((s_ - p[1]) ** 2 + (r_ - p[2]) ** 2) / (ps * ps))
    em = em * soft_in
    return ph, em, puffs


def _sim_vapour(torch, cfg, dt, ph, em, finen, su, rv, soft_in, heat, dye, rho, age):
    heat = torch.maximum(heat, em[None])
    # vapour given off over the surface (it accumulates along the line of sight over the surface's depth);
    # it shows only as it condenses, within ~condense s of leaving the surface (a few cm up)
    add = (cfg["haze"] + (1 - cfg["haze"]) * em)[None] * soft_in[None] * cfg["emit"] * dt
    fine = finen(su, rv, ph)[None]
    dye = (dye * (rho + age) + fine * add) / (rho + age + add + 1e-6)
    age = age + add
    c = age * (1 - math.exp(-dt / cfg["condense"]))
    age = age - c
    rho = rho + c
    return heat, dye, age, rho


def _sim_lift(dt, ph, em, u, heat, inside, up, buoy, drift, draft, lean, above, xs, ys, nx, ny):
    # the vapour leaves the surface upward
    u[1] = u[1] * (1 - inside * 0.5) + inside * 0.5 * (-up * (0.6 + 0.6 * em))
    # forces: buoyancy (relative to the box's mean: no net lift on the whole box; the air around sinks very
    # slowly instead), the draft (above the rim), vorticity confinement
    fb = buoy * heat[0]
    u[1] = u[1] - (fb - fb.mean()) * dt
    dn = drift(xs / nx * 0.3 + 0.35, ys / ny * 0.6 + 0.2, ph)
    u[0] = u[0] + (draft * (dn - 0.5) * 2 + lean) * above * dt * 3.0


def _sim_swirl(torch, cfg, dt, ph, u, inside, above, stirn, stir, sx_, sy_, nx, ny, curl):
    # slow room air: the curl of a smooth stream function nudges the velocity (divergence free)
    psi = stirn(sx_, sy_, ph)
    dpdx = (torch.roll(psi, -1, 1) - torch.roll(psi, 1, 1)) * 0.5 * (stirn.cells - 1)
    dpdy = (torch.roll(psi, -1, 0) - torch.roll(psi, 1, 0)) * 0.5 * (stirn.cells - 1)
    u[0] = u[0] + stir * dpdy * (nx / ny) * dt * 2.0 * above
    u[1] = u[1] - stir * dpdx * dt * 2.0 * above
    w = curl(u)
    aw = w.abs()
    nxg = (torch.roll(aw, -1, 1) - torch.roll(aw, 1, 1)) * 0.5
    nyg = (torch.roll(aw, -1, 0) - torch.roll(aw, 1, 0)) * 0.5
    nl = torch.sqrt(nxg * nxg + nyg * nyg) + 1e-6
    u[0] = u[0] + cfg["vort"] * (nyg / nl) * w * dt * 60 * (1 - inside)
    u[1] = u[1] - cfg["vort"] * (nxg / nl) * w * dt * 60 * (1 - inside)


def _sim_transport(torch, F, cfg, dt, u, rho, heat, age, dye, advect, advect_soft, project, sponge, k_drag, k_fade, k_cool, inside):
    # advect, project, decay
    u = advect(u, u, dt, "border") if cfg["sharp"] > 0.5 else advect_soft(u, u, dt, "border")
    u = project(u * sponge[None]) * k_drag
    rho = advect_soft(rho, u, dt) * sponge[None]
    heat = advect(heat, u, dt) * sponge[None]
    age = advect_soft(age, u, dt) * sponge[None]
    dye = advect(dye, u, dt, "border")
    if cfg["soften"] > 0:
        ks = 1 - (1 - cfg["soften"]) ** (dt * 60)      # tuned at 60 steps per s
        rho = rho + ks * (F.avg_pool2d(rho[None], 3, 1, 1, count_include_pad=False)[0] - rho)
    rho = torch.where(inside[None] > 0, rho, torch.clamp(rho * k_fade - cfg["evap"] * dt, min=0))
    heat = heat * k_cool
    return u, rho, heat, age, dye


def _sim_save_frame(torch, cfg, fi, rho, dye, u, vis_env, i0, i1, j0, j1, A, edge_max, downs, head, k_out, n_x, n_out, write):
    """A frame after the warm-up: the review numbers every 15th, then kept for the loop's crossfade or written;
    -> (edge_max, k_out)."""
    st = cfg["strands"]
    vis = rho[0] * vis_env * (1 - st + st * torch.clamp((dye[0] - 0.3) / 0.4, 0, 1))
    vbox = vis[j0:j1, i0:i1]
    if fi % 15 == 0:
        # for review: nothing at the saved box's edges, and little of the steam moving down
        m = max(2, int(0.06 * (j1 - j0)))
        edge_max = max(edge_max, float(vbox[:m].max()), float(vbox[:, :m].max()), float(vbox[:, -m:].max()))
        downs.append(float((vbox * (u[1, j0:j1, i0:i1] > 0.05 * A).float()).sum()) / (float(vbox.sum()) + 1e-6))
    f = vbox.clamp(0, SCALE).detach().cpu().numpy().astype(np.float32)
    if k_out < n_x:
        head.append(f)
    elif k_out < n_out:
        write(k_out, f)
    else:
        # close the loop: the first n_x frames crossfade from the frames that follow the loop's end
        i = k_out - n_out
        wx = (i + 0.5) / n_x
        wx = wx * wx * (3 - 2 * wx)
        write(i, wx * head[i] + (1 - wx) * f)
    k_out += 1
    return edge_max, k_out


def preview(plate, meta, out_dir, seconds):
    """A first look without the renderer: the density shaded simply (warm, a little brighter on dark) over the
    plate crop, at half size."""
    x0, y0, x1, y1 = meta["box"]
    im = Image.open(ROOT / "out" / "plates" / plate / "plate.png").convert("RGB")
    crop = np.asarray(im.crop((int(x0), int(y0), int(x1), int(y1))), np.float32) / 255
    h, w = (crop.shape[0] // 4) * 4, (crop.shape[1] // 4) * 4
    lin = crop[:h, :w] ** 2.2
    n = min(meta["frames"], int(seconds * meta["fps"]))
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{w // 2}x{h // 2}", "-r", str(meta["fps"]), "-i", "-", "-c:v", "libx264", "-crf", "16",
                          "-pix_fmt", "yuv420p", str(out_dir / "preview.mp4")], stdin=subprocess.PIPE)
    warm = np.array([1.0, 0.86, 0.72], np.float32)
    for i in range(n):
        g = np.asarray(Image.open(out_dir / f"s_{i:04d}.jpg").resize((w, h), Image.BILINEAR), np.float32) / 255
        d = (g ** 2.2) * meta["scale"]
        al = 1 - np.exp(-2.0 * d)
        col = warm * (0.10 + 0.6 * lin.mean(2, keepdims=True))
        o = np.clip(lin * (1 - al[..., None]) + col * al[..., None], 0, 1) ** (1 / 2.2)
        fr = np.asarray(Image.fromarray((o * 255).astype(np.uint8)).resize((w // 2, h // 2), Image.LANCZOS))
        p.stdin.write(fr.tobytes())
    p.stdin.close()
    p.wait()


def sim_overrides(sc):
    """{vessel region: {DEFAULTS key: value}} from the scene's steam layer (`per.<vessel>.sim`)."""
    L = next((L for L in sc.get("layers", []) if L.get("type") == "steam"), {})
    return {k: v["sim"] for k, v in (L.get("per") or {}).items() if isinstance(v, dict) and isinstance(v.get("sim"), dict)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--region", help="a steam region (default: every vessel with a measured opening, cup or bowl)")
    ap.add_argument("--seconds", type=float, help="loop length (default: the scene's loopSeconds, 120)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cell", type=float, help=f"px at 4K per cell (default: 3, finer for a vessel under {CELLS} cells per half-width)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--set", default="", help="look overrides k=v,... (see DEFAULTS)")
    ap.add_argument("--preview", nargs="?", const=20.0, type=float, help="write preview.mp4 of the first N s (20)")
    ap.add_argument("--out", help="write to this folder instead (trials; steam.js reads out/plates/<plate>/steam/<region>/)")
    a = ap.parse_args()
    sc, plate = load_scene(a.scene)
    seconds = a.seconds or float(sc.get("loopSeconds", 120))
    cfg = dict(DEFAULTS)
    lean = next((L.get("lean") for L in sc.get("layers", []) if L.get("type") == "steam" and "lean" in L), None)
    if lean is not None:
        cfg["lean"] = float(lean)
    for kv in filter(None, a.set.split(",")):
        k, v = kv.split("=")
        cfg[k] = float(v)
    regs = [g for g in regions_of(plate) if g.get("kind") == "steam" and g.get("opening")]
    if a.region:
        regs = [g for g in regs if g["name"] == a.region]
    else:
        regs = [g for g in regs if g.get("opening_fit") in ("rim", "hand")]
    if not regs:
        raise SystemExit("steam_sim: no steam region with a measured opening (plate_prep fits them to the rim)")
    for g in regs:
        out_dir = pathlib.Path(a.out) if a.out else ROOT / "out" / "plates" / plate / "steam" / g["name"]
        # scaled to the vessel: the same detail per half-width, and the time scale of its real size
        c, (cm, onset) = dict(cfg), vessel_cm(g)
        # a vessel's own look (the steam layer's per.<vessel>.sim, e.g. a broader, more even plume over a small mug seen
        # side-on, the pixel greenhouse 2026-10-21); --set still wins
        own = {k: float(v) for k, v in (sim_overrides(sc).get(g["name"]) or {}).items()}
        c.update({k: v for k, v in own.items() if k not in dict(kv.split("=") for kv in filter(None, a.set.split(",")))})
        c["tempo"] = c.get("tempo") or round(math.sqrt(REF_CM / cm), 3)
        cell = a.cell or min(3.0, g["opening"][2] * W4 / CELLS)
        meta = simulate(g["opening"], c, seconds, a.fps, cell, a.seed, out_dir,
                        info={"size_cm": cm, "onset_cm": onset, "tempo": c["tempo"], "sim": own})
        if a.preview:
            preview(plate, meta, out_dir, a.preview)
            print(f"preview -> {out_dir / 'preview.mp4'}")


if __name__ == "__main__":
    main()
