"""The ambience renderer (TASKS.md T17), moved verbatim from tools/audio.py, whose docstring has the design: the beds,
the defaults, the seeding, and class Ambience, which makes the bed in canonical 15 s blocks (rain layers, runoff,
wind, the bed's other layers, the reverb), the thunder and the event sounds from a scene's timeline. A recorded layer
(the hot spring's spout) is read from its loops in cozy/audio/recorded.py.

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
from cozy.audio.events import (boat_wash, car_hiss, clock_tick, creak, fish_plop, frog_call, gutter, log_settle, neon_buzz,
                               paddle_slap, paddle_spill, stereo, train_pass, wake_laps)
from cozy.audio.kernels import drip_wave, k_clink, k_crackle, k_near, k_patter, k_pop, k_roof, k_runoff, k_water
from cozy.audio.recorded import RECORDINGS, Recorded

BLK = 15                      # canonical block length (s)
MARGIN = 3                    # warm-up before each block (s); > reverb IR + longest kernel
LOOP_XF = 3.0                 # a looped timeline's join: crossfade from the period running on into its start (s)
N_EXT = (BLK + MARGIN) * SR   # 864000 = 2^8 3^3 5^3: fast FFT size
VERSION = 4                   # bump when synthesis changes (invalidates the loudness calibration cache)
SLOT_OFS = 1 << 20            # keeps seed keys non-negative for t < 0 (block 0's warm-up)
LAYER = {"wash": 1, "patter": 2, "roof": 3, "water": 4, "runoff": 5, "drips": 6, "wind": 7, "mod": 8,
         "kern": 9, "ir": 10, "thunder": 11, "near": 12, "boat": 13, "lap": 14, "gutter": 15, "creak": 16, "fish": 17,
         "fire": 18, "crackle": 19, "murmur": 20, "clink": 21, "howl": 22, "room": 23, "city": 24, "car": 25, "train": 26,
         "ember": 27, "neon": 28, "pop": 29, "frog": 30, "surf": 31, "clock": 32, "river": 33, "wheel": 34,
         "slap": 36, "spill": 37, "axle": 38, "spout": 39}   # 35 was the river's babble of bubbles (removed 2026-11-08)

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
    # a rocky shore on a still evening (the tide pool, 2026-11-05): the surf breaking on the far rocks, wave by wave from
    # the timeline (the picture's foam comes in with the same waves), over the sea's steady roar, a soft breeze
    "coast_fog": {"rain": [], "muffle": 0, "dry": True, "extra": {"surf": 0.0, "howl": -24.0, "room": -32.0}},
    # a river village on a clear night, heard from a porch (the Skyrim mill, 2026-11-08): the river's soft murmur, the
    # waterwheel's water churning with a soft swish and pour for each paddle, in step with the picture's turning wheel,
    # its axle creaking now and then (scene audio "wheel"), a small fire close by, a faint breeze. No bubbles (Truman)
    "river_night": {"rain": [], "muffle": 0, "dry": True, "extra": {"river": -5.0, "wheel": 0.0, "fire": -3.5, "howl": -26.0, "room": -34.0}},
    # a small hot spring in snowy woods at night, heard at the water's edge (the Yuzu Spring, 2026-11-12): a bamboo spout
    # pouring a thin stream into the pool close by on the right (a CC0 recording, cozy/audio/recorded.py; scene audio
    # "spout_pan" moves it), its level breathing a little; a faint breeze in the spruces, about 16 dB under the pour, that
    # swells with the snow's gusts; a very quiet night. No fire, no rain. "snow": choose_bed keeps it for a snowy scene of
    # its look (cabin_snow has a fire and a wind howl)
    "hotspring_snow": {"rain": [], "muffle": 0, "snow": True, "extra": {"spout": 0.0, "howl": -12.0, "room": -28.0}},
}


def choose_bed(aesthetic_bed, weather, has_fire, indoor):
    """The bed for a scene: the aesthetic's own for rain, a snow bed for snow (the look's own bed when it is made for
    snow: "snow" in BEDS, the hot spring's spout, 2026-11-12), a quiet room for clear weather (or the look's own bed
    when it is made for dry weather: "dry" in BEDS, the Skyrim mill's river); a fire layer when the scene has a fire.
    The words count as words, never negated ("fog, no rain": wet_weather)."""
    from cozy.paths import wet_weather
    w = (weather or "").lower()
    if wet_weather(w, ("snow", "blizzard")):
        if BEDS.get(aesthetic_bed, {}).get("snow"):
            return aesthetic_bed, _own_fire(aesthetic_bed, has_fire)
        return "cabin_snow", ({} if has_fire else {"fire": None})
    if wet_weather(w, ("rain", "storm", "drizzle", "thunder")):
        # a look without a rain bed of its own (a snowy cabin's): rain on a roof indoors, or out in the open with no
        # city in it (street_rain's traffic hum on a farm porch, 2026-10-21); city looks carry their own beds
        bed = aesthetic_bed if any(aesthetic_bed == k for k, v in BEDS.items() if v["rain"]) else ("cabin_rain" if indoor else "porch_rain")
        extra = {"fire": -3.0} if has_fire and "fire" not in BEDS[bed].get("extra", {}) else {}
        if not has_fire and "fire" in BEDS[bed].get("extra", {}):
            extra["fire"] = None
        return bed, extra
    if BEDS.get(aesthetic_bed, {}).get("dry"):
        return aesthetic_bed, _own_fire(aesthetic_bed, has_fire)
    return "quiet_night", ({"fire": -2.0} if has_fire else {})


def _own_fire(bed, has_fire):
    """A look's own bed keeps its fire only where the picture has one, and gets one where it does."""
    own = BEDS[bed].get("extra", {})
    return {"fire": -2.0} if has_fire and "fire" not in own else {"fire": None} if not has_fire and "fire" in own else {}

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
               # whoosh / leaf rustle at full gust (linear amplitude, nominal gust peak = 1); frog: its call, near the
               # camera on the floor
               "fish_db": -13.0, "flurry_whoosh": 1.2, "flurry_rustle": 2.0, "flurry_creak": 0.5, "frog_db": -16.0},
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
    # A pendulum clock in the room (scene audio "clock": {"hz", "phase", "pan", "db"}): a soft tick each time its
    # pendulum swings through the middle, at the rate and phase of the pendulum the picture swings (vines.js, a rigid
    # strand: the same hz and phase), db its loudest 0.4 s against the bed. No clock, no ticks.
    "clock": None,
    # A waterwheel in the picture (scene audio "wheel": {"turn_s", "vary", "paddles", "phase" (rad, wheel.json
    # paddle_phase), "dir", "entry_deg", "exit_deg" (where a paddle dips in and rises out, wheel angle), "pan"}): its
    # paddles slap in and drain out in step with src/library/wheel.js's turn (the same function of time), its axle
    # creaks now and then. No wheel, none of it.
    "wheel": None,
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


def bed_layers(cfg):
    """The rain layers that play and the continuous extras with their levels: the bed's, then the scene's overrides
    (extra_db: {"fire": -8, "murmur": null}). The public text names only what these and the voiced events hold."""
    bed = bed_of(cfg)
    extra = dict(bed.get("extra", {}))
    for k, v in (cfg.get("extra_db") or {}).items():
        if v is None:
            extra.pop(k, None)
        else:
            extra[k] = v
    return set(bed["rain"]), extra


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
        self.active, self.extra = bed_layers(cfg)
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
        # the flames' soft fizz, a breath that rises and falls, quiet (2026-11-08: twice as loud, centered at 4.5 kHz and
        # fluttering 15-30 times a second it sizzled high over the fire)
        self.hiss_fft = ext([(20, -70), (600, -32), (1500, -12), (3500, 0), (6500, -8), (11000, -20), (16000, -32), (22000, -50)])
        self.speech_fft = ext([(20, -50), (100, -20), (200, -6), (500, 0), (1000, -3), (2000, -11), (3000, -17), (5000, -28), (8000, -45), (22000, -70)])
        self.room_fft = ext([(20, -12), (60, -3), (200, 0), (1000, -4), (3000, -12), (8000, -26), (22000, -50)])
        self.city_fft = ext([(10, -40), (30, -8), (80, 0), (200, -3), (500, -12), (1500, -28), (4000, -50), (22000, -70)])
        self.howl_ffts = [ext([(20, -60), (fc / 1.35, -26), (fc / 1.1, -8), (fc, 0), (fc * 1.1, -8), (fc * 1.35, -26), (22000, -70)], 8193) for fc in (340, 510, 760)]
        self.rumble_fft = ext([(10, -30), (25, -4), (60, 0), (150, -6), (400, -30), (22000, -70)])
        # the surf: each wave's low roar as it breaks and the hiss of its foam running in and washing back
        self.surf_roar_fft = ext([(10, -40), (30, -10), (80, -2), (160, 0), (350, -3), (800, -11), (2000, -22), (5000, -36), (22000, -60)])
        self.surf_hiss_fft = ext([(20, -60), (300, -28), (900, -12), (2000, -3), (4000, 0), (8000, -7), (14000, -20), (22000, -40)])
        # the river: calm and wide in the picture, so a soft, low murmur heard across the water, under the wheel's water
        # (2026-11-08: a brighter rush, alone with the fire's crackles once its bubbles were gone, read as rain)
        self.river_fft = ext([(20, -40), (70, -14), (200, -4), (420, 0), (900, -4), (1800, -10), (3500, -18), (7000, -29), (14000, -42), (22000, -56)])
        # the water churning under the wheel
        self.churn_fft = ext([(20, -40), (60, -10), (150, -2), (350, 0), (800, -6), (2000, -18), (6000, -40), (22000, -60)])
        self.wheel = cfg.get("wheel") or None
        if self.wheel:
            L = float((tl.get("loop") or {}).get("period") or tl.get("loopSeconds") or 120)
            ts = float(self.wheel.get("turn_s", 16))
            # src/library/wheel.js: whole turns per loop, the speed swelling +-vary over ~37 s, phase from the scene's seed
            self.wheel_fn = {"L": L, "n": max(1, round(L / ts)), "k": max(1, round(L / 37)), "vary": float(self.wheel.get("vary", 0.03)),
                             "ph": TAU * ((self.seed * 0.6180339887) % 1)}
        waves = sorted((e for e in tl.get("events", []) if e["type"] == "surf"), key=lambda e: e["t"]) if "surf" in self.extra else []
        self.surf_t = np.array([e["t"] for e in waves], float)
        self.surf_a = np.array([e.get("amp", 0.7) for e in waves], float)
        self.surf_p = np.array([e.get("pan", 0.0) for e in waves], float)
        self.thunders = [e for e in tl.get("events", []) if e["type"] in ("lightning", "farflash")]
        self._thunder_cache = {}
        self.boats = [e for e in tl.get("events", []) if e["type"] == "boat" and e.get("profile")]
        self.lanterns = [e for e in tl.get("events", []) if e["type"] == "lantern" and e.get("dips")]
        self.fishes = [e for e in tl.get("events", []) if e["type"] == "fish"]
        self.frogs = [e for e in tl.get("events", []) if e["type"] == "frog" and e.get("croaks")]
        self.flurries = [e for e in tl.get("events", []) if e["type"] == "flurry"]
        evs = tl.get("events", [])
        self.cars = [e for e in evs if e["type"] == "car"]
        self.trains = [e for e in evs if e["type"] == "train"]
        self.embers = [e for e in evs if e["type"] == "ember"] if "fire" in self.extra else []
        self.neons = [e for e in evs if e["type"] == "neon"]
        self.gutters = [e for e in evs if e["type"] == "gutter"]
        self.clock = cfg.get("clock") or None
        # layers played from a recording (the hot spring's spout, 2026-11-12): loops cut once, read by modulo in block()
        self.rec = {k: Recorded(k, rng(self.seed, LAYER[k], 1), cfg.get(f"{k}_pan")) for k in RECORDINGS if k in self.extra}
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

    def surf_env(self, t):
        """The surf over t: (roar, hiss), each (len(t), 2), panned per wave. Every 'surf' wave of the timeline (plate.js
        brings the painted foam in with the same ones, so a wave is heard as it is seen): its roar rises as it breaks and
        dies over a few seconds, the hiss of its foam swells as the wash runs in, then a softer one as it drains back."""
        n = len(t)
        roar, hiss = np.zeros((n, 2)), np.zeros((n, 2))
        if not len(self.surf_t):
            return roar, hiss
        k0, k1 = np.searchsorted(self.surf_t, t[0] - 25.0), np.searchsorted(self.surf_t, t[-1])
        step = SR // 100
        tc = t[::step]
        R, Hs = np.zeros((len(tc), 2)), np.zeros((len(tc), 2))

        def ramp(x):
            x = np.clip(x, 0, 1)
            return x * x * (3 - 2 * x)
        for k in range(k0, k1):
            tau = tc - self.surf_t[k]
            on = tau > 0
            a = self.surf_a[k]
            L, Rg = pan_gains(np.array([self.surf_p[k]]))
            g = np.array([L[0], Rg[0]])
            r_env = a * ramp(tau / 0.9) * np.exp(-np.maximum(tau - 0.9, 0) / 2.4) * on
            h_env = a * (ramp((tau - 0.4) / 2.0) * np.exp(-np.maximum(tau - 2.4, 0) / 3.5) + 0.35 * np.exp(-((tau - 6.5) / 1.6) ** 2)) * on
            R += r_env[:, None] * g
            Hs += h_env[:, None] * g
        x = np.arange(n) / step
        xc = np.arange(len(tc))
        roar = np.stack([np.interp(x, xc, R[:, c]) for c in range(2)], 1)
        hiss = np.stack([np.interp(x, xc, Hs[:, c]) for c in range(2)], 1)
        return roar, hiss

    # ---- building blocks
    def wheel_turn(self, t):
        """The waterwheel's turn so far (rad, increasing) at times t: src/library/wheel.js's turn, the same function."""
        f = self.wheel_fn
        return TAU * f["n"] * t / f["L"] + (f["vary"] * f["n"] / f["k"]) * np.sin(TAU * f["k"] * t / f["L"] + f["ph"])

    def paddle_times(self, t0, t1, angle_deg):
        """When a paddle passes the wheel angle `angle_deg` in [t0, t1): [(time, its index among the paddles that pass in
        one loop)]. A paddle's middle shows at phase + dir * turn + m * spacing (wheel.js's band), so one passes the angle
        each time the turn crosses dir * (angle - phase) by a whole spacing."""
        w = self.wheel
        P = int(w.get("paddles", 24))
        dp = TAU / P
        off = int(w.get("dir", 1)) * (np.radians(angle_deg) - float(w.get("phase", 0.0)))
        tg = np.arange(t0 - 0.004, t1 + 0.004, 0.002)
        g = (self.wheel_turn(tg) - off) / dp
        j = np.floor(g)
        per = self.wheel_fn["n"] * P
        out = []
        for i in np.nonzero(j[1:] > j[:-1])[0]:
            tc = tg[i] + (j[i + 1] - g[i]) / (g[i + 1] - g[i]) * (tg[i + 1] - tg[i])
            if t0 <= tc < t1:
                out.append((float(tc), int(j[i + 1]) % per))
        return out

    def wheel_block(self, t0, t, parts=False):
        """The waterwheel over the extended block: the water churning under it, swelling as each paddle sweeps through,
        with a soft swish as each paddle dips in and a pour as it rises out and drains (seeded by the paddle's index in
        the loop: the same sounds a loop later), under the churn so they read as its texture (louder, the audio model
        heard them as footsteps or fireworks, 2026-11-08), and the axle creaking at one point of most turns. Each
        paddle sound has unit energy over a paddle's spacing in time, so its stream holds its level at any turning
        speed: the first version placed them at unit energy, 36 dB under the churn, unheard. `parts`: the slaps,
        spills, creaks and churn apart (tests)."""
        w = self.wheel
        tb = t0 + N_EXT / SR
        pan = float(w.get("pan", 0.0))
        P = int(w.get("paddles", 24))
        rate = self.wheel_fn["n"] * P / self.wheel_fn["L"]          # paddles past one point a second
        acc = {k: np.zeros((N_EXT, 2)) for k in ("slap", "spill", "creak")}

        def place(x, tc, p, into):
            i0 = int(round((tc - t0) * SR))
            s = stereo(x, float(np.clip(p, -1, 1)))
            lo, hi = max(0, i0), min(N_EXT, i0 + len(s))
            if hi > lo:
                acc[into][lo:hi] += s[lo - i0: hi - i0]

        for ang, maker, lay, p, lv in ((w.get("entry_deg", 216.0), paddle_slap, "slap", pan - 0.06, 0.3),
                                       (w.get("exit_deg", -36.0), paddle_spill, "spill", pan + 0.06, 0.35)):
            for tc, j in self.paddle_times(t0 - 1.2, tb, ang):
                r = rng(self.seed, LAYER[lay], j + SLOT_OFS)
                x = unit(maker(r)) * np.sqrt(SR / rate)
                level = min((0.3 + 0.7 * r.random() ** 0.7) * r.lognormal(0, 0.25), 1.25)
                place(x * level * lv, tc, p + r.uniform(-0.05, 0.05), lay)
        for k in ("slap", "spill"):
            acc[k] = 4.0 * np.tanh(acc[k] / 4.0)      # round the rare loud splash (memoryless: random access stays exact)
        for tc, j in self.paddle_times(t0 - 1.6, tb, w.get("entry_deg", 216.0) + 90.0):
            if j % P:
                continue
            r = rng(self.seed, LAYER["axle"], j // P + SLOT_OFS)
            if r.random() < 0.6:
                place(creak(r) * r.uniform(0.18, 0.4), tc, pan, "creak")
        off = int(w.get("dir", 1)) * (np.radians(w.get("entry_deg", 216.0)) - float(w.get("phase", 0.0)))
        sweep = 0.75 + 0.25 * np.cos(TAU * (self.wheel_turn(t) - off) / (TAU / P))
        L, R = pan_gains(np.array([pan]))
        churn = 0.35 * self._filter_ext(self._noise("wheel", 0, t0, 2), self.churn_fft) * sweep[:, None] * np.array([L[0], R[0]])
        if parts:
            return {**acc, "churn": churn}
        return acc["slap"] + acc["spill"] + acc["creak"] + churn

    def spout_block(self, t0, t):
        """The hot spring's spout over the extended block (2026-11-12): the recording's two loops at the block's own
        samples (by modulo, so a block is the same alone or in any order), blended by a slow seeded balance (equal power:
        the two halves of the recording are unrelated water, so the sum holds its level and never repeats), the whole
        breathing about 1 dB over tens of seconds, never surging."""
        n = int(round(t0 * SR)) + np.arange(N_EXT, dtype=np.int64)
        a, b = self.rec["spout"].read(n)
        th = 0.25 * np.pi * (1 + 0.8 * self.snoise(800, t, 37.0))
        lv = 10 ** ((0.8 * self.snoise(801, t, 17.0) + 0.6 * self.snoise(802, t, 47.0)) / 20)
        return (a * np.cos(th)[:, None] + b * np.sin(th)[:, None]) * lv[:, None]

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
            hiss = self._filter_ext(self._noise("fire", 1, t0, 2), self.hiss_fft) * (0.55 + 0.45 * (0.5 + 0.5 * self.snoise(203, t, 0.9)))[:, None]
            crate = 9.0
            burst = lambda tg: crate * (0.25 + 1.6 * np.maximum(self.snoise(204, tg, 0.8), 0) ** 1.5)  # noqa: E731
            g = self._grains("crackle", 0, t0, crate, burst, 0.6, lambda r, n, p=fp: p + r.uniform(-0.18, 0.18, n), self.kfft["crackle"].shape[0])
            crk = self._convolve_bank("crackle", *g) * self._norm(crate, 0.6)
            crk = 8.0 * np.tanh(crk / 8.0)          # round only the extreme snaps (memoryless: random access stays exact)
            g = self._grains("pop", 0, t0, 0.28, lambda tg: 0.28 + 0 * tg, 0.5, lambda r, n, p=fp: p + r.uniform(-0.12, 0.12, n), self.kfft["pop"].shape[0])
            pops = self._convolve_bank("pop", *g) * self._norm(0.28, 0.5)
            pops = 8.0 * np.tanh(pops / 8.0)
            L, R = pan_gains(np.array([fp]))
            dry["fire"] = (1.0 * roar + 0.075 * hiss) * np.array([L[0], R[0]]) * 1.4 + 0.35 * crk + 0.25 * pops
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
        if "surf" in ex:
            env_r, env_h = self.surf_env(t)
            roar = self._filter_ext(self._noise("surf", 0, t0, 2), self.surf_roar_fft)
            hiss = self._filter_ext(self._noise("surf", 1, t0, 2), self.surf_hiss_fft)
            sea = roar * (0.32 + 0.08 * self.snoise(600, t, 7.0))[:, None]     # the sea's steady roar further off
            dry["surf"] = roar * env_r + 0.55 * hiss * env_h + sea
        if "river" in ex:
            # a steady rush with slow surges; no babble of bubbles (Truman asked why the Skyrim mill's sample had bubbles,
            # 2026-11-08; synthesized bubbles had read as cartoony on the aquarium too, L130-L132)
            dry["river"] = self._filter_ext(self._noise("river", 0, t0, 2), self.river_fft) * (
                (0.88 + 0.12 * self.snoise(700, t, 5.0)) * (0.9 + 0.1 * self.snoise(702, t, 0.5)))[:, None]
        if "wheel" in ex and self.wheel:
            dry["wheel"] = self.wheel_block(t0, t)
        if "spout" in ex:
            dry["spout"] = self.spout_block(t0, t)
        # Levels, reverb send, crop the warm-up.
        sends = {**cfg["reverb"]["sends"], "fire": 0.25, "murmur": 0.6, "clink": 0.55, "howl": 0.2, "room": 0.0, "city": 0.1, "surf": 0.3,
                 "river": 0.15, "wheel": 0.22, "spout": 0.08}
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
            if ev["t"] > t1 or ev["t"] + 3 < t0:
                continue
            key = ("fish", ev["id"])
            if key not in self._event_cache:
                r = rng(self.seed, LAYER["fish"], ev["seed"])
                w = stereo(fish_plop(r, ev.get("jump", 0), ev.get("size", 1.0), ev.get("air", 0.45)), ev.get("pan", 0.0))
                lv = ec["fish_db"] - 20 * np.log10(max(ev.get("dist", 150.0), 30.0) / 100.0) + 3 * (ev.get("size", 1.0) - 1.0)
                self._event_cache[key] = [(ev["t"], self._level(w, lv, 0.4))]
            out += self._event_cache[key]
        # the frog's calls, each as its vocal sac swells (0.1 s after the croak's time), panned where it sits
        for ev in self.frogs:
            if ev["t"] > t1 or ev["t"] + ev.get("dur", 0) + 1 < t0:
                continue
            key = ("frog", ev["id"])
            if key not in self._event_cache:
                waves = []
                for i, c in enumerate(ev["croaks"]):
                    sat = [h for h in ev["hops"] if h[0] + h[1] <= c]
                    x = sat[-1][4] if sat else ev["hops"][0][2]
                    r = rng(self.seed, LAYER["frog"], ev["seed"] + i)
                    w = stereo(frog_call(r), float(np.clip((x - 0.5) * 1.6, -0.9, 0.9)))
                    waves.append((ev["t"] + c + 0.1, self._level(w, ec.get("frog_db", -16.0), 0.4)))
                self._event_cache[key] = waves
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

    def ticks(self, t0, t1):
        """The clock's ticks in [t0, t1): one each time the pendulum swings through the middle of its arc. vines.js swings it
        as deg * sin(2 pi n t / P + phase) with n = round(hz * P) whole swings per loop period P, so it passes the middle
        at t = (m pi - phase) P / (2 pi n); a tick there, the tock on the swing back. Eight seeded variants of each,
        leveled once."""
        c = self.clock
        P = float((self.tl.get("loop") or {}).get("period") or self.L)
        n = max(1, round(float(c.get("hz", 0.5)) * P))
        half = P / (2 * n)
        off = -float(c.get("phase", 0.0)) * P / (2 * np.pi * n)
        if "clock" not in self._event_cache:
            pan = float(np.clip(c.get("pan", 0.0), -0.9, 0.9))
            lv = float(c.get("db", -24.0))
            self._event_cache["clock"] = [[self._level(stereo(clock_tick(rng(self.seed, LAYER["clock"], v, tock), bool(tock)), pan), lv, 0.4)
                                           for v in range(8)] for tock in (0, 1)]
        bank = self._event_cache["clock"]
        out = []
        for m in range(int(np.floor((t0 - off) / half)), int(np.ceil((t1 - off) / half)) + 1):
            ts = off + m * half
            if t0 <= ts < t1:
                # the variant by the tick's place in the loop period (2n ticks a period): the same a period later
                v = int(rng(self.seed, LAYER["clock"], m % (2 * n) + SLOT_OFS).integers(8))
                out.append((ts, bank[m % 2][v]))
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
        # the surf's waves come from the timeline's events, which the rest of the key doesn't see; nor do the bed's own
        # layers and levels (BEDS): a bed tuned in code kept its old gain (the Skyrim mill's river and wheel, 2026-11-08);
        # nor a recorded layer's file and loops (the hot spring's spout, 2026-11-12)
        surf = [len(self.surf_t), round(float(self.surf_a.sum()), 3)] if len(self.surf_t) else []
        rec = [self.rec[k].key for k in sorted(self.rec)]
        key = hashlib.sha1(json.dumps([VERSION, self.seed, self.cfg, self.tl.get("weather"), self.L] + ([surf] if surf else [])
                                      + [sorted(self.active), self.extra] + ([rec] if rec else []),
                                      sort_keys=True).encode()).hexdigest()[:16]
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
        clock = self.ticks(start - 0.2, start + dur) if self.clock else []
        for t_ev, w in self.event_waves(start, start + dur) + (self.creaks(start - 3.0, start + dur) if creaky else []) + clock:
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
