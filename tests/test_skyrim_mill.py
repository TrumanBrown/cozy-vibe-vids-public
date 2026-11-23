"""The Skyrim mill (2026-11-08): the northern lights lifted off the sky to ripple (cozy/plate/aurora.py), the waterwheel
taken apart to turn like the 3D wheel it is (cozy/plate/wheel.py, tools/wheel_layer.py), its sound in step with the
picture (cozy/audio/ambience.py: the river_night bed, with no bubbles), the fire's crackles as warm as real ones
(cozy/audio/kernels.py), and his own copy of the Skyrim soundtrack kept to the Skyrim look (tools/music.py,
tools/skyrim_music.py). Free, offline, a few seconds."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from cozy.audio.ambience import BEDS, Ambience, choose_bed, make_cfg  # noqa: E402
from cozy.plate import wheel as WH  # noqa: E402
from cozy.plate.aurora import base_fit, lift, sky_matte  # noqa: E402
from cozy.plate.primitives import srgb_to_linear  # noqa: E402


def night_sky(W=480, H=270, seed=3):
    """A small painted night: a sky gradient with stars and a green curtain of light, a dark ridge in front."""
    r = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    y, x = yy / H, xx / W
    sky = np.stack([0.02 + 0.03 * y, 0.04 + 0.05 * y, 0.09 + 0.05 * y], -1)
    curtain = np.exp(-((y - 0.35) / 0.12) ** 2) * (0.5 + 0.5 * np.sin(x * 40)) * (x > 0.2) * (x < 0.8)
    lin = sky + curtain[..., None] * np.array([0.02, 0.18, 0.08])
    for _ in range(40):
        lin[r.integers(0, int(0.5 * H)), r.integers(0, W)] += 0.25
    ridge = y > 0.62 + 0.05 * np.sin(x * 9)
    lin[ridge] = [0.03, 0.035, 0.05]
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.clip(lin, 0, 1), 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(srgb, 0, 1) * 255).round().astype(np.uint8)), (~ridge).astype(np.float32)


class Aurora(unittest.TestCase):
    def test_the_plate_and_the_light_add_back_to_the_painting(self):
        import tempfile
        img, sky = night_sky()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            plate = lift(img, sky, np.zeros_like(sky), {"box": [0.05, 0.02, 0.95, 0.66]}, out)
            meta = json.loads((out / "aurora.json").read_text())
            pos = srgb_to_linear(np.asarray(Image.open(out / "aurora.png"), np.float32) / 255) / meta["gain"]
            neg = srgb_to_linear(np.asarray(Image.open(out / "aurora_neg.png"), np.float32) / 255) / meta["dark_gain"]
        a = srgb_to_linear(np.asarray(img, np.float32) / 255)
        b = srgb_to_linear(np.asarray(plate, np.float32) / 255)
        err = np.abs(b + pos - neg - a)[sky > 0.5]
        self.assertLess(float(np.percentile(err, 99)), 0.006, "plate + light - dark paint should be the painting again")
        # the light came off the sky: the curtain's green is mostly gone from the plate
        self.assertLess(float(b[60:120, 150:330, 1].mean()), float(a[60:120, 150:330, 1].mean()) * 0.7)

    def test_nothing_in_front_of_the_sky_moves_with_the_light(self):
        img, sky = night_sky()
        lum = srgb_to_linear(np.asarray(img, np.float32) / 255) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        m = sky_matte(sky, lum)
        self.assertEqual(float(m[sky < 0.5].max()), 0.0, "the matte reached past the ridge")
        self.assertGreater(float(m[20:100, 100:400].min()), 0.99)

    def test_the_base_is_the_lower_envelope(self):
        img, sky = night_sky()
        lin = srgb_to_linear(np.asarray(img, np.float32) / 255)
        base = base_fit(lin, sky > 0.5)
        under = (base - lin)[sky > 0.5].max(-1)
        self.assertLess(float(np.percentile(under, 95)), 0.004, "the fitted sky sits above the painting's darkest sky")

    def test_a_solid_matte_lifts_the_light_up_to_the_ridge(self):
        # the Sleeping Hound Inn (2026-11-15): the aurora brightest right at the ridge; the guided filter alone dipped
        # near the edge and left a share of the light on the plate there, a rim that stays still while the light moves
        img, sky = night_sky()
        lin = srgb_to_linear(np.asarray(img, np.float32) / 255)
        H, W = sky.shape
        yy = np.mgrid[0:H, 0:W][0] / H
        lin = lin + (np.exp(-((yy - 0.6) / 0.08) ** 2) * sky)[..., None] * np.array([0.02, 0.2, 0.09], np.float32)
        lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        soft = sky_matte(sky, lum)
        solid = sky_matte(sky, lum, pull=1, solid=True)
        self.assertEqual(float(solid[sky < 0.5].max()), 0.0, "the solid matte reached past the ridge")
        import cv2
        inner = cv2.erode((sky > 0.5).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        self.assertEqual(float(solid[inner].min()), 1.0, "a solid matte is whole inside the traced sky")
        near = (cv2.dilate((sky < 0.5).astype(np.uint8), np.ones((13, 13), np.uint8)) > 0) & (sky > 0.5)
        self.assertLess(float((1 - solid[near]).mean()), 0.5 * float((1 - soft[near]).mean()),
                        "the light left on the plate beside the ridge should be far less with a solid matte")

    def test_keep_holds_a_small_window_of_sky(self):
        img, sky = night_sky()
        sky = sky.copy()
        sky[230:250, 200:212] = 1          # sky seen through an arch on the slope, a separate small part
        lum = srgb_to_linear(np.asarray(img, np.float32) / 255) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        self.assertEqual(float(sky_matte(sky, lum)[238:242, 204:208].max()), 0.0, "by default a small part is an island")
        self.assertGreater(float(sky_matte(sky, lum, pull=1, keep=0.0005, solid=True)[238:242, 204:208].min()), 0.99)

    def test_the_lifted_light_continues_past_the_ridge(self):
        # the layer folds the curtain up to about 25 px sideways; a fold that samples beside the sky must find light,
        # or a dark seam follows the ridge as the light moves (the Sleeping Hound Inn, 2026-11-15)
        import tempfile
        import cv2
        img, sky = night_sky()
        s8 = (sky > 0.5).astype(np.uint8)
        outer = (cv2.dilate(s8, np.ones((7, 7), np.uint8)) > 0) & (sky < 0.5)
        inner = (sky > 0.5) & ~(cv2.erode(s8, np.ones((13, 13), np.uint8)) > 0)
        for m in (outer, inner):
            m[:, :150] = False
            m[:, 330:] = False
        got = {}
        for ext in (0, 40):
            with tempfile.TemporaryDirectory() as d:
                out = Path(d)
                plate = lift(img, sky, np.zeros_like(sky), {"box": [0.05, 0.02, 0.95, 0.66], "pull": 1, "solid": True, "extend": ext}, out)
                pos = np.asarray(Image.open(out / "aurora.png"), np.float32)
            got[ext] = (float(pos[outer].mean()), float(pos[inner].mean()))
            self.assertEqual(float(np.abs(np.asarray(plate, np.float32) - np.asarray(img, np.float32))[sky < 0.5].max()), 0.0,
                             "the plate outside the sky is untouched")
        self.assertLess(got[0][0], 0.1 * got[0][1], "without the extension there is no light beside the ridge")
        self.assertGreater(got[40][0], 0.6 * got[40][1], "with it, the light beside the ridge is about the light just inside")

    def test_with_a_silhouette_the_maps_carry_the_sky_over_the_land(self):
        # a dark finial left inside the traced sky: the maps hold the sky's light there (nothing dark the folds could
        # carry into the open sky), the matte leaves the finial out, and plate + light x matte is the painting at rest
        import tempfile
        img, sky = night_sky()
        a = np.asarray(img, np.float32).copy()
        a[96:104, 240:246] = [8, 10, 14]                       # a dark finial in the sky, inside the traced outline
        img = Image.fromarray(a.astype(np.uint8))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            plate = lift(img, sky, np.zeros_like(sky), {"box": [0.05, 0.02, 0.95, 0.66], "pull": 1, "solid": True,
                                                        "silhouette": 0.3}, out)
            meta = json.loads((out / "aurora.json").read_text())
            pos = srgb_to_linear(np.asarray(Image.open(out / "aurora.png"), np.float32) / 255) / meta["gain"]
            neg = srgb_to_linear(np.asarray(Image.open(out / "aurora_neg.png"), np.float32) / 255) / meta["dark_gain"]
            air = np.asarray(Image.open(out / "aurorafx.png"), np.float32)[..., 0] / 255
        lin = srgb_to_linear(a / 255)
        b = srgb_to_linear(np.asarray(plate, np.float32) / 255)
        err = np.abs(b + (pos - neg) * air[..., None] - lin)[sky > 0.5]
        self.assertLess(float(np.percentile(err, 99)), 0.006, "at rest the layer gives back exactly what the plate gave up")
        self.assertLess(float(air[97:103, 241:245].max()), 0.05, "the finial is land: out of the matte")
        self.assertLess(float(np.abs(b - lin)[97:103, 241:245].max()), 0.002, "the finial stays on the plate as painted")
        ring = pos[92:108, 236:250].mean(-1)
        self.assertGreater(float(ring.min()), 0.5 * float(pos[60:90, 230:256].mean()), "no dark gap in the maps where the finial is")


def wheel_geo():
    return {"rim": [500.0, 400.0, 120.0, 190.0, 0.03], "hn": [-0.04, 0.02], "d": [100.0, 10.0]}


class Wheel(unittest.TestCase):
    def test_the_disk_maps_onto_the_rim_and_its_center_onto_the_hub(self):
        g = wheel_geo()
        th = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        x, y = WH.to_img(g, np.ones_like(th), th)
        M = WH.ellipse_M(*g["rim"][2:])
        q = np.linalg.inv(M) @ np.stack([x - g["rim"][0], y - g["rim"][1]])
        self.assertTrue(np.allclose(np.hypot(*q), 1.0, atol=1e-9), "the projective map moved the rim off its ellipse")
        hx, hy = WH.to_img(g, np.zeros(1), np.zeros(1))
        hub = M @ np.asarray(g["hn"]) + g["rim"][:2]
        self.assertTrue(np.allclose([hx[0], hy[0]], hub), "the disk's center is not at the hub")

    def test_local_angle_inverts_the_map(self):
        g = wheel_geo()
        for th in (0.3, 1.9, -2.4):
            x, y = WH.to_img(g, np.array([0.7]), np.array([th]))
            a, rho = WH.local_angle(g, (x[0], y[0]))
            self.assertAlmostEqual(a, th, places=9)
            self.assertAlmostEqual(rho, 0.7, places=9)

    def test_the_spokes_meet_at_the_hub(self):
        lines = [[[100, 100], [100, 20]], [[100, 100], [160, 40]], [[100, 100], [20, 100]]]
        self.assertTrue(np.allclose(WH.hub_from_lines(lines), [100, 100]))

    def test_a_whole_number_of_paddles_and_a_rim_that_divides_the_turn(self):
        src = (ROOT / "tools" / "wheel_layer.py").read_text(encoding="utf-8")
        self.assertIn("paddles = max(3, int(round(2 * np.pi / period)))", src)
        self.assertIn("its span must divide a turn", src)

    def test_the_key_art_is_judged_with_the_wheel_in_it(self):
        import tempfile
        from wheel_layer import at_rest
        g = {**wheel_geo(), "spokes": 8, "spoke0": 0.0, "spoke_c": 0.0, "spoke_h": 0.05, "spoke_t": [0.0, 0.88],
             "rim_tex_rho": [0.78, 1.05], "rim_start": 0.0, "rim_period": float(np.pi), "back_dark": 0.45, "dir": 1,
             "paddle_period": float(2 * np.pi / 24), "paddle_phase": 0.0, "box": [300, 150, 760, 650]}
        img = np.zeros((800, 1000, 3))
        with tempfile.TemporaryDirectory() as t:
            wd = Path(t)
            self.assertIs(at_rest(wd, img), img)
            (wd / "wheel.json").write_text(json.dumps(g), encoding="utf-8")
            for k, shape in (("rim", (8, 64)), ("spoke", (16, 8)), ("band", (8, 16))):
                WH.save_rgba(wd / f"{k}.png", np.ones(shape + (4,)))
            Image.new("RGB", (460, 500)).save(wd / "occ.png")
            out = at_rest(wd, img)
        x, y = WH.to_img(g, np.array([0.9]), np.array([1.0]))
        self.assertGreater(out[int(round(y[0])), int(round(x[0]))].mean(), 0.9, "no rim where the wheel's rim is")
        self.assertEqual(out[700, 900].max(), 0, "drawn outside the wheel's box")
        self.assertEqual(img.max(), 0, "the image passed in was changed")

    def test_the_intro_title_keeps_clear_of_the_turning_wheel(self):
        import tempfile
        import intro_title as IT
        with tempfile.TemporaryDirectory() as t:
            pd = Path(t)
            Image.new("RGB", (3840, 2160)).save(pd / "regions.png")
            (pd / "wheel").mkdir()
            (pd / "wheel" / "wheel.json").write_text(json.dumps({"box": [2286, 994, 2696, 1581]}), encoding="utf-8")
            sc = {"layers": [{"type": "wheel", "turn": 16}]}
            av = IT.avoid_map(pd / "regions.png", [], sc, 3840, 2160)
            self.assertGreater(av[1280 // 4, 2490 // 4], 0.99)
            self.assertEqual(av[1280 // 4, 1500 // 4], 0)
            (cx, cy), before, after = IT.clear_of(pd / "regions.png", [], sc, (1500, 240), 1920, 1080)
            self.assertGreater(before, 0.1)
            self.assertLessEqual(after, 0.02)
            self.assertTrue(cy + 120 < 994 or cy - 120 > 1581)
            sc["layers"][0]["enabled"] = False
            self.assertEqual(IT.avoid_map(pd / "regions.png", [], sc, 3840, 2160).max(), 0)


def mill_tl(period=1200, wheel=True):
    return {"seed": 7, "loopSeconds": 120, "duration": 3600, "loop": {"period": period}, "events": [],
            "audio": {"bed": "river_night", **({"wheel": {"turn_s": 16, "vary": 0.03, "paddles": 24, "phase": -0.47, "dir": 1,
                                                         "entry_deg": 216, "exit_deg": -36, "pan": 0.2}} if wheel else {})}}


class WheelSound(unittest.TestCase):
    def test_the_turn_is_the_pictures(self):
        tl = mill_tl()
        amb = Ambience(tl, make_cfg(tl))
        # src/library/wheel.js: n = round(L / 16) turns a loop, the swell over round(L / 37) cycles, phase from the seed
        L, n, k = 1200.0, 75, 32
        ph = 2 * np.pi * ((7 * 0.6180339887) % 1)
        t = np.array([0.0, 13.7, 600.2, 1199.9])
        want = 2 * np.pi * n * t / L + (0.03 * n / k) * np.sin(2 * np.pi * k * t / L + ph)
        self.assertTrue(np.allclose(amb.wheel_turn(t), want))

    def test_a_paddle_every_fifteen_degrees_of_turn_repeating_with_the_loop(self):
        tl = mill_tl()
        amb = Ambience(tl, make_cfg(tl))
        a = amb.paddle_times(100.0, 120.0, -36)
        rate = len(a) / 20.0
        self.assertAlmostEqual(rate, 75 * 24 / 1200.0, delta=0.15)
        b = amb.paddle_times(1300.0, 1320.0, -36)
        self.assertEqual([j for _t, j in a], [j for _t, j in b], "a loop later the paddles have other sounds")
        self.assertTrue(np.allclose([t + 1200 for t, _j in a], [t for t, _j in b], atol=1e-3))

    def test_the_paddles_are_texture_on_the_churn_and_the_bed_is_dry(self):
        from cozy.audio.ambience import BLK, MARGIN, N_EXT
        from cozy.audio.dsp import SR
        tl = mill_tl()
        amb = Ambience(tl, make_cfg(tl))
        st = amb.block(5, layers=True)
        self.assertIn("wheel", st)
        self.assertIn("river", st)
        t0 = 5 * BLK - MARGIN
        parts = amb.wheel_block(t0, t0 + np.arange(N_EXT) / SR, parts=True)
        db = {k: 20 * np.log10(np.sqrt((v[MARGIN * SR:] ** 2).mean()) + 1e-12) for k, v in parts.items()}
        # heard, but under the churn: 36 dB under it they were never heard; over it they read as footsteps (2026-11-08)
        for k in ("slap", "spill"):
            self.assertGreater(db[k] - db["churn"], -8.0, k)
            self.assertLess(db[k] - db["churn"], 3.0, k)
        self.assertEqual(BEDS["river_night"]["rain"], [])
        self.assertEqual(choose_bed("river_night", "clear night with the northern lights", True, False)[0], "river_night")
        self.assertEqual(choose_bed("porch_rain", "clear night", True, False)[0], "quiet_night")

    def test_no_bubbles_in_the_river_or_the_paddles(self):
        """Truman asked why the mill's sample v3 had bubbles in it. The river is a smooth murmur (its babble of bubbles made the
        500-2000 Hz band impulsive: kurtosis 4.1), and the paddles' sounds are noise only."""
        import inspect
        from cozy.audio.dsp import SR
        from cozy.audio.events import paddle_slap, paddle_spill
        tl = mill_tl()
        x = Ambience(tl, make_cfg(tl)).block(5, layers=True)["river"][:, 0]
        f = np.fft.rfftfreq(len(x), 1 / SR)
        y = np.fft.irfft(np.fft.rfft(x) * ((f >= 500) & (f < 2000)), len(x))
        self.assertLess(float((y ** 4).mean() / (y ** 2).mean() ** 2), 3.4)
        for fn in (paddle_slap, paddle_spill):
            self.assertNotIn("bubble(", inspect.getsource(fn), fn.__name__)

    def test_no_wheel_no_paddles(self):
        tl = mill_tl(wheel=False)
        st = Ambience(tl, make_cfg(tl)).block(5, layers=True)
        self.assertNotIn("wheel", st)


class FireSound(unittest.TestCase):
    """Truman found the fire's crackle on the mill's sample v3 odd and too shrill. Its crackles were near-white
    clicks (centered at 5 kHz, per Hz only 5 and 8 dB down at 4-8 and 8-16 kHz from 1-2 kHz); real crackles heard from a
    campfire or a stove a few meters off (Freesound recordings measured) fall 5 to 12 and 9 to 20 dB."""

    def bank(self, fn):
        from cozy.audio.dsp import SR
        f = np.fft.rfftfreq(16384, 1 / SR)
        ks = [fn(np.random.default_rng(100 + i)) for i in range(40)]
        P = np.mean([np.abs(np.fft.rfft(k, 16384)) ** 2 for k in ks], 0)
        m = lambda a, b: P[(f >= a) & (f < b)].mean()  # noqa: E731
        sel = (f >= 300) & (f <= 16000)
        cen = np.median([(f[sel] * (np.abs(np.fft.rfft(k, 16384)) ** 2)[sel]).sum() / (np.abs(np.fft.rfft(k, 16384)) ** 2)[sel].sum() for k in ks])
        return 10 * np.log10(m(4000, 8000) / m(1000, 2000)), 10 * np.log10(m(8000, 16000) / m(1000, 2000)), cen

    def test_crackles_and_pops_are_as_warm_as_real_ones(self):
        from cozy.audio.kernels import k_crackle, k_pop
        for fn in (k_crackle, k_pop):
            mid, top, cen = self.bank(fn)
            self.assertLess(mid, -7.0, fn.__name__)
            self.assertLess(top, -12.0, fn.__name__)
            self.assertLess(cen, 3600.0, fn.__name__)


class FranchiseMusic(unittest.TestCase):
    def test_a_games_tracks_only_for_its_own_look(self):
        import music as M
        sk = {"title": "Far Horizons", "franchise": "The Elder Scrolls V: Skyrim"}
        self.assertEqual(M.foreign([sk], {"franchise": "The Elder Scrolls V: Skyrim"}), [])
        self.assertEqual(M.foreign([sk], {"franchise": "Minecraft"}), [sk])
        self.assertEqual(M.foreign([sk], {}), [sk])
        self.assertEqual(M.foreign([{"title": "a CC0 track"}], {}), [])

    def test_the_looks_disclaimer_goes_into_its_credits(self):
        import music as M
        doc = {"minecraft": False, "disclaimer": "NOT AN OFFICIAL ELDER SCROLLS PRODUCT.",
               "entries": [{"track": 0, "start": 0}],
               "tracks": [{"title": "Far Horizons", "artist": "Jeremy Soule", "license": "x", "source": "y",
                           "attribution": "Music from The Elder Scrolls V: Skyrim by Jeremy Soule, courtesy of Bethesda Softworks"}]}
        c = M.credits(doc, ledger_path=ROOT / "nonexistent.csv")
        self.assertIn("NOT AN OFFICIAL ELDER SCROLLS PRODUCT.", c)
        self.assertIn("Far Horizons - Jeremy Soule", c)
        self.assertNotIn("MINECRAFT", c)

    def test_the_allowlist_leaves_out_combat_and_choir(self):
        cfg = json.loads((ROOT / "config" / "skyrim_music.json").read_text(encoding="utf-8"))
        used = {t["title"] for t in cfg["tracks"].values() if t["use"]}
        for out in ("Dragonborn", "Sovngarde", "Tooth and Claw", "Blood and Steel", "One They Fear"):
            self.assertNotIn(out, used)
        self.assertGreaterEqual(len(used), 15)
        self.assertTrue(all(t.get("why") for t in cfg["tracks"].values() if not t["use"]), "every track left out says why")

    def test_a_claimed_track_stays_out(self):
        """Tundra was claimed by Content ID on both Skyrim videos through a third party's track that samples it
        (2026-11-16): a track with a claim is never used, and import refuses one switched back on."""
        import io
        import contextlib
        import tempfile
        import skyrim_music as SM
        cfg = json.loads((ROOT / "config" / "skyrim_music.json").read_text(encoding="utf-8"))
        claimed = {k: t for k, t in cfg["tracks"].items() if t.get("claim")}
        self.assertIn("Tundra", {t["title"] for t in claimed.values()})
        self.assertFalse(any(t["use"] for t in claimed.values()))
        bad = {**cfg, "tracks": {k: {**t, "use": True} for k, t in claimed.items()}}
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                SM.cmd_import(bad, {}, tmp)
        self.assertIn("Content ID claim", str(e.exception))

    def test_skyrim_names_stay_out_of_the_words(self):
        from cozy.voice import BRANDS
        for w in ("Skyrim", "Riverwood", "Bethesda", "The Elder Scrolls"):
            self.assertTrue(BRANDS.search(w), w)
        self.assertIsNone(BRANDS.search("Northlight Mill"))


if __name__ == "__main__":
    unittest.main()
