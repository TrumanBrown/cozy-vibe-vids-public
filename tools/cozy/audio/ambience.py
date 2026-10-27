"""The ambience renderer (TASKS.md T17), moved verbatim from tools/audio.py, whose docstring has the design: the beds,
the defaults, the seeding, and class Ambience, which makes the bed in canonical 15 s blocks (rain layers, runoff,
wind, the bed's other layers, the reverb), the thunder and the event sounds from a scene's timeline.

  BEDS, choose_bed       the layers of each setting's bed; the bed for a scene's weather
  DEFAULTS, make_cfg     levels, rates, reverb, thunder and event settings; a timeline's config
  Ambience               calibrate() to the loudness target, then render(start, dur): the stems
  VERSION                bump when the synthesis changes: it keys the loudness calibration cache
  rng, LAYER, SLOT_OFS   each random draw comes from rng(seed, LAYER[...], ...): same timeline, same samples
"""
import hashlib
import json
import pathlib

import numpy as np

from audio_analyze import integrated_lufs, k_weight, loudness_blocks
from cozy.audio.dsp import SR, TAU, _conv_causal, design_fir, fft_filter, pan_gains, peak_limit, unit
from cozy.audio.events import boat_wash, car_hiss, creak, fish_plop, gutter, log_settle, neon_buzz, stereo, train_pass, wake_laps
from cozy.audio.kernels import drip_wave, k_clink, k_crackle, k_near, k_patter, k_pop, k_roof, k_runoff, k_water

BLK = 15                      # canonical block length (s)
MARGIN = 3                    # warm-up before each block (s); > reverb IR + longest kernel
LOOP_XF = 3.0                 # a looped timeline's join: crossfade from the period running on into its start (s)
N_EXT = (BLK + MARGIN) * SR   # 864000 = 2^8 3^3 5^3: fast FFT size
VERSION = 3                   # bump when synthesis changes (invalidates the loudness calibration cache)
SLOT_OFS = 1 << 20            # keeps seed keys non-negative for t < 0 (block 0's warm-up)
LAYER = {"wash": 1, "patter": 2, "roof": 3, "water": 4, "runoff": 5, "drips": 6, "wind": 7, "mod": 8,
         "kern": 9, "ir": 10, "thunder": 11, "near": 12, "boat": 13, "lap": 14, "gutter": 15, "creak": 16, "fish": 17,
         "fire": 18, "crackle": 19, "murmur": 20, "clink": 21, "howl": 22, "room": 23, "city": 24, "car": 25, "train": 26,
         "ember": 27, "neon": 28, "pop": 29}

# Ambience beds by setting (scene audio "bed"; config/aesthetics.json audio_bed). "rain": which rain layers play;
# "muffle": 0..1 how much the rain is heard through glass (indoors); "extra": continuous non-rain layers with
# levels (dB, like levels_db). Treetop is "porch_rain" (every rain layer, no extras).
BEDS = {
    "porch_rain": {"rain": ["wash", "patter", "near", "roof", "water", "runoff", "drips", "wind"], "muffle": 0, "extra": {}},
    "library": {"rain": ["wash", "patter", "drips", "wind"], "muffle": 0.6, "extra": {"fire": -3.0, "room": -24.0},
                "levels_db": {"wash": -4.0, "patter": -9.0, "drips": 0.0, "wind": -20.0}},
    "cafe_rain": {"rain": ["wash", "patter", "near", "drips"], "muffle": 0.45, "extra": {"murmur": 4.0, "clink": -24.0, "room": -24.0, "city": -8.0},
                  "levels_db": {"wash": -3.0, "patter": -7.0, "near": -12.0, "drips": 2.0}},
    "cabin_snow": {"rain": [], "muffle": 0, "extra": {"fire": -2.0, "howl": -9.0, "room": -22.0}},
    "cabin_rain": {"rain": ["wash", "patter", "roof", "drips", "wind"], "muffle": 0.4, "extra": {"fire": -1.0, "room": -24.0},
                   "levels_db": {"roof": -9.0, "patter": -9.0}},
    "street_rain": {"rain": ["wash", "patter", "near", "roof", "water", "runoff", "drips"], "muffle": 0, "extra": {"city": -16.0},
                    "levels_db": {"roof": -9.0, "water": -12.0, "near": -9.0}},
    "country_rain": {"rain": ["wash", "patter", "near", "roof", "water", "runoff", "drips", "wind"], "muffle": 0, "extra": {}},
    "cottage_rain": {"rain": ["wash", "patter", "roof", "drips", "wind"], "muffle": 0.4, "extra": {"fire": -6.0, "room": -24.0}},
    "bedroom_rain": {"rain": ["wash", "patter", "drips", "wind"], "muffle": 0.55, "extra": {"room": -22.0, "city": -24.0}},
    "city_rain": {"rain": ["wash", "patter", "near", "drips"], "muffle": 0.4, "extra": {"city": -14.0, "room": -24.0}},
    "sea_storm": {"rain": ["wash", "patter", "roof", "drips", "wind"], "muffle": 0.35, "extra": {"fire": -12.0, "howl": -14.0, "room": -24.0}},
    "underwater": {"rain": [], "muffle": 0, "extra": {"room": -12.0, "city": -18.0}},
    "quiet_night": {"rain": [], "muffle": 0, "extra": {"room": -14.0, "howl": -22.0}},
}


def choose_bed(aesthetic_bed, weather, has_fire, indoor):
    """The bed for a scene: the aesthetic's own for rain, a snow bed for snow, a quiet room for clear weather;
    a fire layer when the scene has a fire."""
    w = (weather or "").lower()
    if "snow" in w or "blizzard" in w:
        return "cabin_snow", ({} if has_fire else {"fire": None})
    if any(k in w for k in ("rain", "storm", "drizzle", "thunder")):
        # a look without a rain bed of its own (a snowy cabin's): rain on a roof indoors, or out in the open with no
        # city in it (street_rain's traffic hum on a farm porch, 2026-10-21); city looks carry their own beds
        bed = aesthetic_bed if any(aesthetic_bed == k for k, v in BEDS.items() if v["rain"]) else ("cabin_rain" if indoor else "porch_rain")
        extra = {"fire": -3.0} if has_fire and "fire" not in BEDS[bed].get("extra", {}) else {}
        if not has_fire and "fire" in BEDS[bed].get("extra", {}):
            extra["fire"] = None
        return bed, extra
    return "quiet_night", ({"fire": -2.0} if has_fire else {})

DEFAULTS = {
    "lufs": -20.0,
    # Layer levels (dB; RMS at nominal intensity before loudness normalization; drips: peak).
    "levels_db": {"wash": -2.0, "patter": -6.0, "near": -7.0, "roof": -7.0, "water": -16.0, "runoff": -10.0, "drips": 6.0, "wind": -15.0},
    # Grain rates at nominal intensity (per second; runoff per stream at full flow).
    "rates": {"patter": 1100.0, "near": 40.0, "roof": 850.0, "water": 600.0, "runoff": 240.0, "drips": 0.3},
    "reverb": {"rt60": 1.0, "wet_db": -7.0,
               "sends": {"wash": 0.15, "patter": 0.35, "near": 0.4, "roof": 0.4, "water": 0.5, "runoff": 0.5, "drips": 0.6, "wind": 0.2}},
    "thunder": {"over_bed_db": [1.2, 4.5], "lowpass_hz": [320, 700], "fade_in": 0.4, "rt60": 4.0, "wet": 0.6, "peak_dbfs": -8.0},
    # Distant lightning (timeline 'farflash', 3-7 km): only the low rumble survives the distance; it rolls in
    # slowly and stays under the rain (the mix rises by over_bed_db, i.e. the rumble alone is 5-11 dB below the bed).
    "far_thunder": {"over_bed_db": [0.3, 1.2], "lowpass_hz": [130, 240], "fade_in": 1.5, "rt60": 5.0, "wet": 0.75, "tail": 9.0},
    # Event sounds (timeline events), levels = loudness peak relative to the bed: subtle, never startling.
    #   boat: hull wash following the boat's distance/pan (short-term 3 s); lap: its wake lapping on the
    #   shore below the porch `lap_delay` s after its closest approach (momentary 0.4 s); gutter: lantern
    #   flame flutter at each dip; creak: treehouse wood creaks at strong gust peaks in windy spells.
    "events": {"boat_db": -15.0, "lap_db": -9.0, "lap_delay": [18.0, 30.0], "gutter_db": -12.0,
               "creak_db": -11.0, "creak_wind": 1.15, "creak_p": 0.35,
               # fish: momentary loudness of the plop at 100 m (falls off ~1/distance); flurry: extra wind
               # whoosh / leaf rustle at full gust (linear amplitude, nominal gust peak = 1)
               "fish_db": -13.0, "flurry_whoosh": 1.2, "flurry_rustle": 2.0, "flurry_creak": 0.5},
    "intensity_db": {"fast": 0.8, "slow": 1.2},   # +- dB micro drift (9 s, 41 s); macro drift = timeline track
    "gust_boost": 0.25,          # rain swells this much (rate) at full gust
    "stream_fall_s": 1.3,        # time for stream water to reach the ground below (splash lag)
    "fade_s": [2.0, 3.0],        # master fade in at t=0 / out at the end of the video
    "bed": "porch_rain",         # BEDS key (layers by setting)
    "fire_pan": 0.5,             # fireplace position (pan -1..1) for the fire layer
    # New-setting event sounds, levels relative to the bed (dB, loudest window): passing car tire hiss (3 s),
    # distant train (3 s), a log settling in the fire with a burst of crackles (0.4 s), neon buzz (0.4 s),
    # candle gutter flutter (0.4 s).
    "events2": {"car_db": -11.0, "train_db": -12.0, "ember_db": -7.0, "neon_db": -22.0, "gutter_db": -16.0},
}


def rng(seed, *keys):
    return np.random.default_rng(np.random.SeedSequence([int(seed) & 0xFFFFFFFF] + [int(k) & 0xFFFFFFFF for k in keys]))


def merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def bed_of(cfg):
    return BEDS.get(cfg.get("bed", "porch_rain"), BEDS["porch_rain"])


def make_cfg(tl):
    """DEFAULTS, then the bed's level defaults, then the scene's audio overrides."""
    bed = (tl.get("audio") or {}).get("bed", DEFAULTS["bed"])
    return merge(merge(DEFAULTS, {"levels_db": BEDS.get(bed, {}).get("levels_db", {})}), tl.get("audio"))


# ---------------------------------------------------------------- the renderer

class Ambience:
    def __init__(self, tl, cfg):
        self.tl, self.cfg = tl, cfg
        self.seed = int(tl["seed"])
        self.L = float(tl["loopSeconds"])
        self.duration = float(tl["duration"])
        w = (tl.get("weather") or {}).get("wind") or {}
        self.wind = {"mean": w.get("mean", 0.3), "gust": w.get("gust", 0.8),
                     "cycles": max(1, round(w.get("gustCycles", 5))), "fronts": w.get("fronts", 0.6)}
        self.streams = [s for s in (tl.get("weather") or {}).get("runoff", []) if s["rate"] >= 10]
        self.bed = bed_of(cfg)
        self.active = set(self.bed["rain"])
        self.extra = dict(self.bed.get("extra", {}))
        for k, v in (cfg.get("extra_db") or {}).items():    # scene overrides: {"fire": -8, "murmur": null}
            if v is None:
                self.extra.pop(k, None)
            else:
                self.extra[k] = v
        kr = lambda name, k: rng(self.seed, LAYER["kern"], LAYER[name], k)  # noqa: E731
        makers = {"patter": (k_patter, 16), "near": (k_near, 12), "roof": (k_roof, 12), "water": (k_water, 16), "runoff": (k_runoff, 12)}
        banks = {name: [f(kr(name, i)) for i in range(n)] for name, (f, n) in makers.items() if name in self.active}
        if "fire" in self.extra:
            banks["crackle"] = [k_crackle(kr("crackle", i)) for i in range(16)]
            banks["pop"] = [k_pop(kr("pop", i)) for i in range(8)]
        if "clink" in self.extra:
            banks["clink"] = [k_clink(kr("clink", i)) for i in range(8)]
        self.kfft = {k: np.stack([np.fft.rfft(np.pad(x, (0, N_EXT - len(x))).astype(np.float32)) for x in v]) for k, v in banks.items()}
        # Warm, pink-ish roar: amplitude falls ~4.75 dB/oct above 500 Hz (band power ~ -1.75 dB/oct).
        self.wash_fir = design_fir([(20, -30), (60, -12), (120, -6), (250, -2), (500, 0), (1000, -2.5), (2000, -7),
                                    (4000, -12.5), (8000, -19), (12000, -25), (16000, -32), (22000, -45)])
        self.whoosh_fir = design_fir([(20, -30), (80, -8), (200, 0), (450, -2), (900, -10), (2000, -26), (22000, -60)])
        self.rustle_fir = design_fir([(20, -60), (800, -24), (2000, -6), (4000, 0), (7000, -4), (12000, -16), (22000, -40)])
        self.ir_fft = self._room_ir()
        self.wash_fft = np.fft.rfft(np.pad(self.wash_fir, (0, N_EXT - len(self.wash_fir))))
        self.whoosh_fft = np.fft.rfft(np.pad(self.whoosh_fir, (0, N_EXT - len(self.whoosh_fir))))
        self.rustle_fft = np.fft.rfft(np.pad(self.rustle_fir, (0, N_EXT - len(self.rustle_fir))))
        ext = lambda pts, n=4097: np.fft.rfft(np.pad(design_fir(pts, n), (0, N_EXT - n)))  # noqa: E731
        m = float(self.bed.get("muffle", 0))
        self.muffle_fft = ext([(20, 0), (700, 0), (1800, -5 * m), (4000, -12 * m), (9000, -20 * m), (22000, -30 * m)]) if m > 0 else None
        self.roar_fft = ext([(10, -40), (40, -8), (90, 0), (250, -2), (600, -10), (1500, -24), (4000, -45), (22000, -70)])
        self.hiss_fft = ext([(20, -70), (800, -30), (2000, -8), (4500, 0), (9000, -6), (16000, -20), (22000, -40)])
        self.speech_fft = ext([(20, -50), (100, -20), (200, -6), (500, 0), (1000, -3), (2000, -11), (3000, -17), (5000, -28), (8000, -45), (22000, -70)])
        self.room_fft = ext([(20, -12), (60, -3), (200, 0), (1000, -4), (3000, -12), (8000, -26), (22000, -50)])
        self.city_fft = ext([(10, -40), (30, -8), (80, 0), (200, -3), (500, -12), (1500, -28), (4000, -50), (22000, -70)])
        self.howl_ffts = [ext([(20, -60), (fc / 1.35, -26), (fc / 1.1, -8), (fc, 0), (fc * 1.1, -8), (fc * 1.35, -26), (22000, -70)], 8193) for fc in (340, 510, 760)]
        self.rumble_fft = ext([(10, -30), (25, -4), (60, 0), (150, -6), (400, -30), (22000, -70)])
        self.thunders = [e for e in tl.get("events", []) if e["type"] in ("lightning", "farflash")]
        self._thunder_cache = {}
        self.boats = [e for e in tl.get("events", []) if e["type"] == "boat" and e.get("profile")]
        self.lanterns = [e for e in tl.get("events", []) if e["type"] == "lantern" and e.get("dips")]
        self.fishes = [e for e in tl.get("events", []) if e["type"] == "fish"]
        self.flurries = [e for e in tl.get("events", []) if e["type"] == "flurry"]
        evs = tl.get("events", [])
        self.cars = [e for e in evs if e["type"] == "car"]
        self.trains = [e for e in evs if e["type"] == "train"]
        self.embers = [e for e in evs if e["type"] == "ember"] if "fire" in self.extra else []
        self.neons = [e for e in evs if e["type"] == "neon"]
        self.gutters = [e for e in evs if e["type"] == "gutter"]
        self._event_cache = {}
        self.master = None
        self.nominal = False

    # ---- modulation (pure functions of absolute time)
    def snoise(self, key, t, period):
        k0 = np.floor(t / period).astype(np.int64)
        f = t / period - k0
        f = f * f * (3 - 2 * f)
        lo, hi = int(k0.min()), int(k0.max()) + 1
        vals = np.array([rng(self.seed, LAYER["mod"], key, k + SLOT_OFS).uniform(-1, 1) for k in range(lo, hi + 1)])
        v0, v1 = vals[k0 - lo], vals[k0 + 1 - lo]
        return v0 + (v1 - v0) * f

    def track(self, key, t):
        """Timeline weather track (timeline.js weatherTrack), linearly interpolated; 1.0 when calibrating."""
        tr = self.tl.get("track") or {}
        a = tr.get(key)
        if self.nominal or not a:
            return np.ones_like(np.asarray(t, float))
        return np.interp(np.asarray(t, float) / tr["dt"], np.arange(len(a)), np.asarray(a, float))

    def gust(self, t):
        """Wind strength at the porch (visual windAt(t, x = 0.45 W) in rain.js, with the track's gustiness);
        1 = nominal peak."""
        w = self.wind
        th = TAU * (w["cycles"] * np.mod(t, self.L) / self.L - w["fronts"] * 0.45)
        v = w["mean"] + w["gust"] * self.track("wind", t) * (0.75 * np.sin(th) + 0.25 * np.sin(2 * th + 1.3))
        return np.abs(v) / (abs(w["mean"]) + w["gust"])

    def flow(self, s, t):
        """Exact copy of flowAt() in rain.js (runoff shader), times the track's stream strength."""
        tt = np.mod(t, self.L)
        sd = s["seedf"]
        th = TAU * s["burstCycles"] * tt / self.L + sd
        v = 0.5 * np.sin(th) + 0.3 * np.sin(2 * th + 2.1 + sd) + 0.35 * np.sin(TAU * 37 * tt / self.L + 3 * sd)
        pk = 0.5 * np.sin(TAU * 263 * tt / self.L + 5 * sd) + 0.5 * np.sin(TAU * 389 * tt / self.L + 7 * sd)
        return np.clip(np.clip(s["flow"] + s["burst"] * v + 0.22 * pk, 0.04, 1.0) * self.track("streams", t), 0.04, 1.0)

    def flurry_env(self, t):
        """Gust flurries (timeline 'flurry' events; same raised-cosine gust as timeline.js flurryWind):
        strength 0..1 (|wind| / 2 m/s). Off while calibrating, so loudness doesn't depend on events."""
        t = np.asarray(t, float)
        v = np.zeros_like(t)
        if self.nominal:
            return v
        for e in self.flurries:
            if e["t"] > t[-1] or e["t"] + e["dur"] < t[0]:
                continue
            s = t - e["t"]
            m = (s >= 0) & (s < e["dur"])
            v[m] += e["amp"] * 0.5 * (1 - np.cos(TAU * s[m] / e["dur"]))
        return np.minimum(np.abs(v) / 2.0, 1.0)

    def intensity(self, t, key):
        c = self.cfg["intensity_db"]
        db = c["fast"] * self.snoise(100, t, 9.0) + c["slow"] * self.snoise(101, t, 41.0) + 0.4 * self.snoise(110 + key, t, 13.0)
        return 10 ** (db / 20) * self.track("rain", t) * (1 + self.cfg["gust_boost"] * (self.gust(t) + 0.8 * self.flurry_env(t)))

    # ---- building blocks
    def _room_ir(self):
        r = rng(self.seed, LAYER["ir"])
        rt = self.cfg["reverb"]["rt60"]
        n = int(2.2 * SR)
        t = np.arange(n) / SR
        lp = design_fir([(20, 0), (700, 0), (1400, -12), (4000, -40), (22000, -60)], 1025)
        out = []
        for _ in range(2):
            nz = r.standard_normal(n)
            lo = fft_filter(nz, lp)
            hi = nz - lo
            ir = (lo * np.exp(-6.9 * t / rt) + 0.6 * hi * np.exp(-6.9 * t / (0.45 * rt))) * (1 - np.exp(-t / 0.008))
            for _k in range(6):  # early reflections: porch floor, roof, posts
                i = int(r.uniform(0.004, 0.028) * SR)
                ir[i] += r.uniform(0.25, 0.6) * (1 if r.random() < 0.5 else -1) * 30
            ir = unit(ir)
            out.append(np.fft.rfft(np.pad(ir, (0, N_EXT - n))))
        return np.stack(out)

    def _grains(self, layer, key, t0, rate_nom, rate_fn, amp_sigma, pan_fn, K):
        """Seeded Poisson grains in per-second slots covering [t0, t0 + BLK + MARGIN); thinning by rate_fn.
        Amplitudes are lognormal truncated at +2.2 sigma: close drops stand out, but never startle."""
        rmax = rate_nom * 2.2
        idx, kk, gl, gr = [], [], [], []
        for slot in range(int(np.floor(t0)), int(np.ceil(t0 + BLK + MARGIN))):
            r = rng(self.seed, LAYER[layer], key, slot + SLOT_OFS)
            n = r.poisson(rmax)
            tg = slot + r.random(n)
            u = r.random(n)
            k = r.integers(0, K, n)
            a = np.exp(amp_sigma * np.clip(r.standard_normal(n), -3.0, 2.2))
            p = pan_fn(r, n)
            ok = (u * rmax < rate_fn(tg)) & (tg >= t0) & (tg < t0 + BLK + MARGIN)
            L, R = pan_gains(p[ok])
            idx.append(np.round((tg[ok] - t0) * SR).astype(np.int64))
            kk.append(k[ok])
            gl.append(a[ok] * L)
            gr.append(a[ok] * R)
        return np.concatenate(idx), np.concatenate(kk), np.concatenate(gl), np.concatenate(gr)

    def _convolve_bank(self, bank, idx, kk, gl, gr):
        K = self.kfft[bank].shape[0]
        idx = np.minimum(idx, N_EXT - 1)
        out = []
        for g in (gl, gr):
            trains = np.zeros((K, N_EXT), np.float32)
            for k in range(K):
                s = kk == k
                if s.any():
                    trains[k] = np.bincount(idx[s], weights=g[s], minlength=N_EXT)
            Y = (np.fft.rfft(trains, axis=1) * self.kfft[bank]).sum(0)
            out.append(np.fft.irfft(Y, N_EXT))
        return np.stack(out, 1)

    def _norm(self, rate, sigma):
        """1 / RMS per channel of a grain layer at its nominal rate (unit-energy kernels, equal-power pan)."""
        z = np.linspace(-6, 6, 4001)
        w = np.exp(-0.5 * z * z)
        ea2 = (np.exp(2 * sigma * np.clip(z, -3.0, 2.2)) * w).sum() / w.sum()
        return 1.0 / np.sqrt(rate * ea2 * 0.5 / SR)

    def _noise(self, layer, key, t0, ch=2):
        """White noise from per-second seeded slots covering the extended block (random access)."""
        out = np.empty((N_EXT, ch))
        s0 = int(np.floor(t0))
        buf = np.concatenate([rng(self.seed, LAYER[layer], key, s + SLOT_OFS).standard_normal((SR, ch)) for s in range(s0, s0 + BLK + MARGIN + 1)])
        o = int(round((t0 - s0) * SR))
        out[:] = buf[o: o + N_EXT]
        return out

    def _filter_ext(self, x, H):
        return np.fft.irfft(np.fft.rfft(x, axis=0) * H[:, None], N_EXT, axis=0)

    # ---- one canonical block: dict of stems (BLK*SR, 2), before master gain (thunder separate)
    def block(self, b, layers=False):
        cfg, lv = self.cfg, self.cfg["levels_db"]
        t0 = b * BLK - MARGIN
        t = t0 + np.arange(N_EXT) / SR
        rates = cfg["rates"]
        dry = {}
        act = self.active
        # Wash: distant roar, decorrelated stereo, following the rain intensity.
        if "wash" in act:
            nz = self._filter_ext(self._noise("wash", 0, t0), self.wash_fft)
            c = 0.25
            a1, a2 = np.sqrt((1 + np.sqrt(1 - c * c)) / 2), np.sqrt((1 - np.sqrt(1 - c * c)) / 2)
            wash = np.stack([a1 * nz[:, 0] + a2 * nz[:, 1], a1 * nz[:, 1] + a2 * nz[:, 0]], 1)
            dry["wash"] = wash * np.sqrt(self.intensity(t, 0))[:, None]
        # Granular rain layers: name -> (kernel bank, rate, amplitude sigma, pan law, seed key).
        specs = {
            "patter": ("patter", rates["patter"], 0.6, lambda r, n: np.sign(r.random(n) - 0.5) * r.random(n) ** 0.8, 1),
            "near": ("near", rates["near"], 0.35, lambda r, n: np.sign(r.random(n) - 0.5) * r.uniform(0.2, 0.95, n), 4),
            "roof": ("roof", rates["roof"], 0.5, lambda r, n: r.uniform(-0.7, 0.7, n), 2),
            "water": ("water", rates["water"], 0.5, lambda r, n: r.uniform(-0.75, 0.75, n), 3),
        }
        for name, (bank, rate, sig, pan, key) in specs.items():
            if name not in act:
                continue
            g = self._grains(name, 0, t0, rate, lambda tg, key=key, rate=rate: rate * self.intensity(tg, key), sig, pan, self.kfft[bank].shape[0])
            dry[name] = self._convolve_bank(bank, *g) * self._norm(rate, sig)
        # Runoff: one grain stream per roof stream, rate/level following the visible flow (splash lag).
        parts = []
        lag = cfg["stream_fall_s"]
        for si, s in enumerate(self.streams if "runoff" in act else []):
            pan0 = float(np.clip((s["x"] - 0.5) * 1.6, -0.9, 0.9))
            rate = rates["runoff"]
            g = self._grains("runoff", si, t0, rate, lambda tg, s=s: rate * self.flow(s, tg - lag) ** 1.2,
                             0.55, lambda r, n, p=pan0: p + r.uniform(-0.06, 0.06, n), self.kfft["runoff"].shape[0])
            parts.append(g)
        if parts:
            g = tuple(np.concatenate([p[i] for p in parts]) for i in range(4))
            dry["runoff"] = self._convolve_bank("runoff", *g) * self._norm(rates["runoff"], 0.55)
        # Wind: gust-driven whoosh + leaf rustle (fluttering); gust flurries swell both (rustle most: leaves).
        gs = self.gust(t)
        fe = self.flurry_env(t) ** 1.2
        ec = cfg["events"]
        if "wind" in act:
            wn = self._noise("wind", 0, t0, 4)
            who = self._filter_ext(wn[:, :2], self.whoosh_fft)
            rus = self._filter_ext(wn[:, 2:], self.rustle_fft) * (0.6 + 0.4 * self.snoise(120, t, 0.09))[:, None]
            g15 = gs ** 1.5
            dry["wind"] = who * (g15 + ec["flurry_whoosh"] * fe)[:, None] + 0.6 * rus * (g15 + ec["flurry_rustle"] * fe)[:, None]
        # Close drips: individually synthesized, sparse; level = peak relative to the bed (not RMS).
        drips = np.zeros((N_EXT, 2))
        for slot in range(int(np.floor(t0)), int(np.ceil(t0 + BLK + MARGIN))) if "drips" in act else []:
            r = rng(self.seed, LAYER["drips"], 0, slot + SLOT_OFS)
            for _ in range(r.poisson(rates["drips"])):
                td = slot + r.random()
                w = drip_wave(r)
                w = w / np.abs(w).max() * r.lognormal(0, 0.4)
                p = (1 if r.random() < 0.5 else -1) * r.uniform(0.35, 0.9)
                L, R = pan_gains(np.array([p]))
                i0 = int(round((td - t0) * SR))
                if i0 < 0 or i0 >= N_EXT:
                    continue
                m = min(len(w), N_EXT - i0)
                drips[i0: i0 + m, 0] += w[:m] * L[0]
                drips[i0: i0 + m, 1] += w[:m] * R[0]
        if "drips" in act:
            dry["drips"] = drips
        # Rain heard from indoors comes through the glass: duller.
        if self.muffle_fft is not None:
            for k in ("wash", "patter", "near", "roof", "water", "drips"):
                if k in dry:
                    dry[k] = self._filter_ext(dry[k], self.muffle_fft)
        # Non-rain layers of the bed (levels in self.extra).
        ex = self.extra
        if "fire" in ex:
            fp = float(np.clip(cfg.get("fire_pan", 0.0), -0.9, 0.9))
            nz = self._noise("fire", 0, t0, 2)
            roar = self._filter_ext(nz, self.roar_fft) * ((0.62 + 0.38 * (0.5 + 0.5 * self.snoise(201, t, 0.35))) * (0.85 + 0.15 * self.snoise(202, t, 2.3)))[:, None]
            hiss = self._filter_ext(self._noise("fire", 1, t0, 2), self.hiss_fft) * (0.4 + 0.6 * np.abs(self.snoise(203, t, 0.07)))[:, None]
            crate = 9.0
            burst = lambda tg: crate * (0.25 + 1.6 * np.maximum(self.snoise(204, tg, 0.8), 0) ** 1.5)  # noqa: E731
            g = self._grains("crackle", 0, t0, crate, burst, 0.6, lambda r, n, p=fp: p + r.uniform(-0.18, 0.18, n), self.kfft["crackle"].shape[0])
            crk = self._convolve_bank("crackle", *g) * self._norm(crate, 0.6)
            crk = 8.0 * np.tanh(crk / 8.0)          # round only the extreme snaps (memoryless: random access stays exact)
            g = self._grains("pop", 0, t0, 0.28, lambda tg: 0.28 + 0 * tg, 0.5, lambda r, n, p=fp: p + r.uniform(-0.12, 0.12, n), self.kfft["pop"].shape[0])
            pops = self._convolve_bank("pop", *g) * self._norm(0.28, 0.5)
            pops = 8.0 * np.tanh(pops / 8.0)
            L, R = pan_gains(np.array([fp]))
            dry["fire"] = (1.0 * roar + 0.15 * hiss) * np.array([L[0], R[0]]) * 1.4 + 0.35 * crk + 0.25 * pops
        if "murmur" in ex:
            K = 10
            nz = self._filter_ext(self._noise("murmur", 0, t0, K), self.speech_fft)
            mix = np.zeros((N_EXT, 2))
            for k in range(K):
                syl = np.maximum(self.snoise(300 + k, t, 0.1 + 0.02 * (k % 4)), 0) ** 1.2
                phrase = np.clip((self.snoise(320 + k, t, 1.7 + 0.3 * (k % 3)) + 0.15) * 3, 0, 1)
                p = rng(self.seed, LAYER["murmur"], k).uniform(-0.8, 0.8)
                L, R = pan_gains(np.array([p]))
                v = nz[:, k] * syl * phrase
                mix[:, 0] += v * L[0]
                mix[:, 1] += v * R[0]
            dry["murmur"] = mix / np.sqrt(K * 0.18)
        if "clink" in ex:
            g = self._grains("clink", 0, t0, 0.12, lambda tg: 0.12 + 0 * tg, 0.5, lambda r, n: r.uniform(-0.7, 0.7, n), self.kfft["clink"].shape[0])
            dry["clink"] = self._convolve_bank("clink", *g) * self._norm(0.12, 0.5)
        if "howl" in ex:
            nz = self._noise("howl", 0, t0, 2)
            gust = (gs ** 1.3 + 1.4 * self.flurry_env(t))[:, None]
            h = sum(self._filter_ext(nz, H) * (0.35 + 0.65 * (0.5 + 0.5 * self.snoise(400 + i, t, 3.0 + 1.3 * i)))[:, None] for i, H in enumerate(self.howl_ffts))
            rum = self._filter_ext(self._noise("howl", 1, t0, 2), self.rumble_fft)
            dry["howl"] = (h * 0.8 + rum * 0.6) * gust
        if "room" in ex:
            dry["room"] = self._filter_ext(self._noise("room", 0, t0, 2), self.room_fft)
        if "city" in ex:
            dry["city"] = self._filter_ext(self._noise("city", 0, t0, 2), self.city_fft) * (0.75 + 0.25 * self.snoise(500, t, 6.0))[:, None]
        # Levels, reverb send, crop the warm-up.
        sends = {**cfg["reverb"]["sends"], "fire": 0.25, "murmur": 0.6, "clink": 0.55, "howl": 0.2, "room": 0.0, "city": 0.1}
        send = np.zeros((N_EXT, 2))
        for k in dry:
            dry[k] = dry[k] * 10 ** ((lv[k] if k in lv else ex.get(k, 0.0)) / 20)
            send += dry[k] * sends.get(k, 0.0)
        wet = np.fft.irfft(np.fft.rfft(send, axis=0) * self.ir_fft.T, N_EXT, axis=0) * 10 ** (cfg["reverb"]["wet_db"] / 20)
        o = MARGIN * SR
        if layers:  # debug: every layer separately (levels applied), plus the reverb return
            return {**{k: v[o:] for k, v in dry.items()}, "reverb": wet[o:]}
        zero = np.zeros((N_EXT, 2))
        stems = {"rain": sum((dry[k] for k in dry if k != "runoff"), zero)[o:] + wet[o:], "runoff": dry.get("runoff", zero)[o:]}
        return stems

    # ---- thunder
    def thunder_wave(self, ev):
        key = ev["id"]
        if key in self._thunder_cache:
            return self._thunder_cache[key]
        th = ev["thunder"]
        far_ev = ev["type"] == "farflash"
        cfg = {**self.cfg["thunder"], **self.cfg["far_thunder"]} if far_ev else self.cfg["thunder"]
        r = rng(self.seed, LAYER["thunder"], th["seed"])
        D = float(th["distance_m"])
        # 0..1 position in the level/brightness range: storm strikes by nearness, distant ones by their draw.
        near = float(th["gain"]) if far_ev else float(np.clip((th["gain"] - 0.55) / 0.45, 0, 1))
        az = (ev["x"] - 0.5) * np.radians(70)
        # Tortuous channel from the ground point up into the cloud, then a horizontal in-cloud run.
        H = r.uniform(2200, 3600)
        p = np.array([D * np.sin(az), D * np.cos(az), 0.0])
        pts, d = [p], np.array([0.0, 0.0, 1.0])
        while pts[-1][2] < H and len(pts) < 600:
            d = d + r.normal(0, 0.5, 3)
            d[2] = abs(d[2]) + 0.3
            d /= np.linalg.norm(d)
            pts.append(pts[-1] + d * 30 * r.uniform(0.6, 1.4))
        hd = r.normal(0, 1, 2)
        hd /= np.linalg.norm(hd)
        for _ in range(int(r.uniform(40, 140))):
            d = np.array([hd[0], hd[1], 0.0]) + r.normal(0, 0.4, 3)
            d /= np.linalg.norm(d)
            pts.append(pts[-1] + d * 30 * r.uniform(0.6, 1.4))
        P = np.array(pts)
        mid, vec = 0.5 * (P[1:] + P[:-1]), P[1:] - P[:-1]
        ln = np.linalg.norm(vec, axis=1)
        los = mid - np.array([0.0, 0.0, 2.0])
        dist = np.linalg.norm(los, axis=1)
        cosang = np.abs((vec * los).sum(1) / (ln * dist))
        amp = ln * ((1 - cosang ** 2) ** 1.5 + 0.05) / dist
        tarr = dist / 343.0
        tarr -= tarr.min()                       # first arrival = timeline thunder.t
        tail = cfg.get("tail", 7.0)
        n = int((tarr.max() + tail) * SR)
        out = np.zeros((n, 2))
        fc = cfg["lowpass_hz"][0] + (cfg["lowpass_hz"][1] - cfg["lowpass_hz"][0]) * near
        # Distance bands: farther segments are later and duller.
        order = np.argsort(dist)
        for bi, sel in enumerate(np.array_split(order, 4)):
            train = np.zeros(n)
            np.add.at(train, np.minimum((tarr[sel] * SR).astype(np.int64), n - 1), amp[sel] * r.choice([-1, 1], len(sel)))
            nw = int(r.uniform(4e-3, 9e-3) * SR * (1 + 0.3 * bi))
            nwave = np.concatenate([np.linspace(1, -1, nw), np.zeros(8)])
            sig = np.convolve(train, nwave)[:n]
            fcb = fc * (0.85 ** bi)
            lp = design_fir([(10, 0), (fcb, 0), (fcb * 2, -18), (fcb * 4, -40), (22000, -80)], 2049)
            sig = fft_filter(sig, lp)
            pan = float(np.clip(np.sin(az) * 1.3, -0.8, 0.8))
            spread = r.uniform(-0.25, 0.25)
            L, R = pan_gains(np.array([pan + spread * bi / 3]))
            out[:, 0] += sig * L[0]
            out[:, 1] += sig * R[0]
        # Rumble texture: low noise following the arrival density (matched to the N-wave part's power).
        env = np.zeros(n)
        np.add.at(env, np.minimum((tarr * SR).astype(np.int64), n - 1), amp)
        env = fft_filter(env, np.hanning(int(0.35 * SR)))
        env /= env.max() + 1e-12
        rum = fft_filter(r.standard_normal(n), design_fir([(10, -30), (35, 0), (120, 0), (fc, -6), (fc * 2.5, -40), (22000, -80)], 4097)) * env
        rum *= np.sqrt((out ** 2).mean() / max((rum ** 2).mean(), 1e-20))
        out += 0.8 * rum[:, None]
        # High-pass ~30 Hz, valley reverb (pre-delay 0.12 s), soft onset, end fade.
        hp = design_fir([(5, -60), (18, -30), (32, -3), (45, 0), (22000, 0)], 4097)
        out = np.stack([fft_filter(out[:, c], hp) for c in range(2)], 1)
        irn = int(cfg["rt60"] * 1.4 * SR)
        ti = np.arange(irn) / SR
        lpir = design_fir([(10, 0), (400, 0), (900, -12), (2500, -40), (22000, -70)], 1025)
        wet = np.zeros_like(out)
        for c in range(2):
            ir = fft_filter(r.standard_normal(irn), lpir) * np.exp(-6.9 * ti / cfg["rt60"]) * (1 - np.exp(-ti / 0.06))
            wet[:, c] = _conv_causal(out[:, c], np.concatenate([np.zeros(int(0.12 * SR)), unit(ir)]))
        out = (1 - cfg["wet"]) * out + cfg["wet"] * wet * 2.0
        fi = int(cfg["fade_in"] * SR)
        out[:fi] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fi)))[:, None]
        fo = int(2.0 * SR)
        out[-fo:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fo)))[:, None]
        # Level: the mix's short-term loudness rises by over_bed dB (near strikes more), i.e. thunder alone
        # sits at bed + 10 log10(10^(over/10) - 1); then a look-ahead peak limiter (low rumble is quiet in
        # LUFS but large in amplitude; keeps the mix's true peak safe).
        st, _ = loudness_blocks(k_weight(out), 3 * SR, SR // 10)
        over = cfg["over_bed_db"][0] + (cfg["over_bed_db"][1] - cfg["over_bed_db"][0]) * near
        target = self.cfg["lufs"] + 10 * np.log10(10 ** (over / 10) - 1)
        out *= 10 ** ((target - st.max()) / 20)
        out = peak_limit(out, cfg.get("peak_dbfs", -8.0))
        self._thunder_cache[key] = out
        return out

    # ---- event sounds
    def _level(self, x, rel_db, win):
        """Scale so the sound's loudest `win`-second window sits `rel_db` dB relative to the bed's target."""
        st, _ = loudness_blocks(k_weight(x), int(win * SR), SR // 20)
        return x * 10 ** ((self.cfg["lufs"] + rel_db - st.max()) / 20)

    def event_waves(self, t0, t1):
        """[(start s, stereo wave)] for boat (hull wash, wake laps) and lantern (guttering) events that
        overlap [t0, t1). Each wave depends only on its event: cached, identical in any render range."""
        ec = self.cfg["events"]
        out = []
        for ev in self.boats:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 90 < t0:   # laps end < 90 s after the event
                continue
            key = ("boat", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["boat"], ev["seed"])
                wash = self._level(boat_wash(r, ev["profile"], ev["dur"]), ec["boat_db"], 3.0)
                d = np.asarray(ev["profile"]["dist"])
                tc = ev["t"] + int(np.argmin(d)) * ev["profile"]["dt"]
                rl = rng(self.seed, LAYER["lap"], ev["seed"])
                laps = self._level(wake_laps(rl, int(rl.integers(7, 12)), (1.3, 2.4)), ec["lap_db"], 0.4)
                self._event_cache[key] = [(ev["t"], wash), (tc + rl.uniform(*ec["lap_delay"]), laps)]
            out += self._event_cache[key]
        for ev in self.lanterns:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 1 < t0:
                continue
            key = ("lantern", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["gutter"], ev["seed"])
                pan = float(np.clip((ev.get("x", 0.5) - 0.5) * 1.6, -0.9, 0.9))
                deepest = max(d[2] for d in ev["dips"])
                w = gutter(r, ev["dips"], ev["dur"], pan)
                self._event_cache[key] = [(ev["t"], self._level(w, ec["gutter_db"] + 20 * np.log10(deepest / 0.6), 0.4))]
            out += self._event_cache[key]
        for ev in self.fishes:
            if ev["t"] > t1 or ev["t"] + 2 < t0:
                continue
            key = ("fish", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["fish"], ev["seed"])
                w = stereo(fish_plop(r, ev.get("jump", 0), ev.get("size", 1.0)), ev.get("pan", 0.0))
                lv = ec["fish_db"] - 20 * np.log10(max(ev.get("dist", 150.0), 30.0) / 100.0) + 3 * (ev.get("size", 1.0) - 1.0)
                self._event_cache[key] = [(ev["t"], self._level(w, lv, 0.4))]
            out += self._event_cache[key]
        e2 = self.cfg["events2"]
        for ev in self.cars:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 2 < t0:
                continue
            key = ("car", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["car"], ev["seed"])
                w = car_hiss(r, ev["dur"], ev.get("dir", 1))
                self._event_cache[key] = [(ev["t"], self._level(w, e2["car_db"] + r.normal(0, 1.5), 3.0))]
            out += self._event_cache[key]
        for ev in self.trains:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 3 < t0:
                continue
            key = ("train", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["train"], ev["seed"])
                self._event_cache[key] = [(ev["t"], self._level(train_pass(r, ev["dur"], ev.get("dir", 1)), e2["train_db"], 3.0))]
            out += self._event_cache[key]
        for ev in self.embers:
            if ev["t"] > t1 or ev["t"] + 2 < t0:
                continue
            key = ("ember", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["ember"], ev["seed"])
                w = log_settle(r, int(ev.get("n", 8)), float(np.clip(self.cfg.get("fire_pan", 0.0), -0.9, 0.9)))
                w = peak_limit(self._level(w, e2["ember_db"] + 4 * (ev.get("power", 0.8) - 0.8), 0.4), -9.0)
                self._event_cache[key] = [(ev["t"], w)]
            out += self._event_cache[key]
        for ev in self.neons:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 1 < t0:
                continue
            key = ("neon", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["neon"], ev["seed"])
                self._event_cache[key] = [(ev["t"], self._level(neon_buzz(r, ev["dips"], ev["dur"]), e2["neon_db"], 0.4))]
            out += self._event_cache[key]
        for ev in self.gutters:
            if ev["t"] > t1 or ev["t"] + ev["dur"] + 1 < t0:
                continue
            key = ("gutter", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["gutter"], ev["seed"])
                self._event_cache[key] = [(ev["t"], self._level(gutter(r, ev["dips"], ev["dur"], r.uniform(-0.5, 0.5)), e2["gutter_db"], 0.4))]
            out += self._event_cache[key]
        return out

    def creaks(self, t0, t1):
        """Treehouse creaks starting in [t0, t1): at the visual gust peaks (every loop/gustCycles s) while
        the weather track's wind is strong; seeded per peak, so any render range agrees."""
        ec, w = self.cfg["events"], self.wind
        P = self.L / w["cycles"]
        th = np.linspace(0, TAU, 3600, endpoint=False)
        ph0 = (th[np.argmax(0.75 * np.sin(th) + 0.25 * np.sin(2 * th + 1.3))] / TAU + w["fronts"] * 0.45) % 1.0
        out = []

        def draw(k):   # raw decision for gust peak k (stateless: depends only on k)
            tk = (k + ph0) * P
            wk = float(self.track("wind", tk))
            r = rng(self.seed, LAYER["creak"], k + SLOT_OFS)
            return wk > ec["creak_wind"] and r.random() < ec["creak_p"] * min(1.0, (wk - ec["creak_wind"]) / 0.25), r

        for k in range(int(np.floor(t0 / P - ph0)) - 1, int(np.ceil(t1 / P - ph0)) + 1):
            hit, r = draw(k)
            if not hit or draw(k - 1)[0] or draw(k - 2)[0]:   # never on consecutive gusts (>= ~70 s apart)
                continue
            ts = (k + ph0) * P + r.uniform(-1.5, 1.0)
            if t0 <= ts < t1:
                x = stereo(creak(r), r.uniform(-0.6, 0.6))
                out.append((ts, self._level(x, ec["creak_db"] + r.normal(0, 2.0), 0.4)))
        # Strong gust flurries make the treehouse creak too (at the gust's peak, every other one or so).
        for e in self.flurries:
            r = rng(self.seed, LAYER["creak"], 1 << 24, e["seed"])
            if abs(e["amp"]) < 1.3 or r.random() >= ec["flurry_creak"]:
                continue
            ts = e["t"] + e["dur"] * r.uniform(0.4, 0.6)
            if t0 <= ts < t1:
                x = stereo(creak(r), r.uniform(-0.6, 0.6))
                out.append((ts, self._level(x, ec["creak_db"] + r.normal(0, 1.5), 0.4)))
        return out

    # ---- calibration + rendering
    def calibrate(self, cache_dir):
        key = hashlib.sha1(json.dumps([VERSION, self.seed, self.cfg, self.tl.get("weather"), self.L], sort_keys=True).encode()).hexdigest()[:16]
        cache = pathlib.Path(cache_dir) / "audio_cal.json"
        if cache.exists():
            c = json.loads(cache.read_text())
            if c.get("key") == key:
                self.master = c["master_db"]
                return self.master
        bs = range(int(300 // BLK), int(300 // BLK) + int(np.ceil(self.L / BLK)))   # one full loop from 5 min
        self.nominal = True   # calibrate at nominal weather (track = 1), so the track's drift stays audible
        x = np.concatenate([sum(self.block(b).values()) for b in bs])
        self.nominal = False
        lufs = integrated_lufs(k_weight(x))
        self.master = float(self.cfg["lufs"] - lufs)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "master_db": self.master, "measured_lufs_at_0db": lufs}))
        return self.master

    def render(self, start, dur):
        """Stereo float64 stems {'rain','runoff','thunder','events'} for [start, start+dur), master gain applied.
        A looped timeline (tl.loop.period, timeline.js loopTimeline): the sound repeats with the period exactly like
        the picture (engine.js timeAt). Every sample is synthesized at its time folded into [period, 2 period), where
        the timeline holds one period with the one before spilling over. The synthesis itself (seeded noise, grains,
        reverb tails) doesn't repeat, so each fold boundary is crossfaded over XF s from the stream running on past the
        period's end into the period's start (equal power, as loop_master's joins): no click, no step. Only the
        video's master fades read real time."""
        P = float((self.tl.get("loop") or {}).get("period") or 0)
        if P:
            n0, n1 = int(round(start * SR)), int(round((start + dur) * SR))
            NP, X = int(round(P * SR)), int(round(LOOP_XF * SR))
            out = {k: np.zeros((n1 - n0, 2)) for k in ("rain", "runoff", "thunder", "events")}
            n = n0
            while n < n1:
                j = n % NP
                m = min(n1 - n, NP - j)
                part = self._render(P + j / SR, m / SR, fades=False)
                if j < X:
                    # the first XF s of each period: crossfade from the period before running on (its time 2P + j).
                    # Only the bed (rain, runoff: seeded per second, so the two streams are unrelated); thunder and
                    # event sounds are the same waves on both sides (the timeline repeats), so they pass as they are
                    # (an equal-power blend of a signal with itself would swell it by up to 3 dB)
                    k = min(m, X - j)
                    over = self._render(2 * P + j / SR, k / SR, fades=False)
                    u = (np.arange(j, j + k) + 0.5) / X
                    a, b = np.sin(0.5 * np.pi * u)[:, None], np.cos(0.5 * np.pi * u)[:, None]
                    for key in ("rain", "runoff"):
                        part[key][:k] = a * part[key][:k] + b * over[key]
                for key in out:
                    out[key][n - n0: n - n0 + m] = part[key][:m]
                n += m
            t = (np.arange(n0, n1) / SR)
            fi, fo = self.cfg["fade_s"]
            fade = np.clip(t / fi, 0, 1) * np.clip((self.duration - t) / fo, 0, 1)
            fade = (0.5 - 0.5 * np.cos(np.pi * fade))[:, None]
            return {k: v * fade for k, v in out.items()}
        return self._render(start, dur)

    def _render(self, start, dur, fades=True):
        g = 10 ** (self.master / 20)
        n0, n1 = int(round(start * SR)), int(round((start + dur) * SR))
        stems = {k: np.zeros((n1 - n0, 2)) for k in ("rain", "runoff", "thunder", "events")}
        for b in range(n0 // (BLK * SR), (n1 - 1) // (BLK * SR) + 1):
            blk = self.block(b)
            bs = b * BLK * SR
            lo, hi = max(n0, bs), min(n1, bs + BLK * SR)
            for k, v in blk.items():
                stems[k][lo - n0: hi - n0] = v[lo - bs: hi - bs] * g
        for ev in self.thunders:
            ts = int(round(ev["thunder"]["t"] * SR))
            if ts >= n1 or ts + 40 * SR <= n0:   # thunder waves are < 40 s long
                continue
            w = self.thunder_wave(ev)
            lo, hi = max(n0, ts), min(n1, ts + len(w))
            if hi > lo:
                stems["thunder"][lo - n0: hi - n0] += w[lo - ts: hi - ts]
        # Event sounds (boat, lantern, creaks): self-contained waves placed at their start sample.
        creaky = "wind" in self.active or "howl" in self.extra
        for t_ev, w in self.event_waves(start, start + dur) + (self.creaks(start - 3.0, start + dur) if creaky else []):
            ts = int(round(t_ev * SR))
            lo, hi = max(n0, ts), min(n1, ts + len(w))
            if hi > lo:
                stems["events"][lo - n0: hi - n0] += w[lo - ts: hi - ts]
        # Master fades at the very start / end of the video.
        if not fades:
            return stems
        t = (np.arange(n0, n1) / SR)
        fi, fo = self.cfg["fade_s"]
        fade = np.clip(t / fi, 0, 1) * np.clip((self.duration - t) / fo, 0, 1)
        fade = (0.5 - 0.5 * np.cos(np.pi * fade))[:, None]
        return {k: v * fade for k, v in stems.items()}
