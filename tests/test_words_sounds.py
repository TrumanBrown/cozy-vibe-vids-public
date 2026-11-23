"""The public text names only the sounds a video's mix has (2026-10-27, the jungle temple's 10 h): its draft promised
"the sound of the falls", "waterfall sounds" and #waterfallsounds over a quiet night bed with no water in it, his blurb
said "rain" on a dry night, and two thumbnails read "calm minecraft music & clear".

  .venv\\Scripts\\python -m unittest discover -s tests -p test_words_sounds.py -v
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import finish_video  # noqa: E402
from cozy.publish.thumb_spec import tag_lines  # noqa: E402
from cozy.publish.words import facts, mix_sounds, sound_problems, template_words, word_problems  # noqa: E402

P = 1200


def timeline(bed, events=(), extra=None):
    audio = {"bed": bed, **({"extra_db": extra} if extra else {})}
    return {"audio": audio, "events": [{"t": P + 5.0 + i, **e} for i, e in enumerate(events)]}


NIGHT = timeline("quiet_night", [{"type": "frog", "croaks": [3.0]}, {"type": "fish"}, {"type": "moth"}, {"type": "birds"}])
RAIN = timeline("street_rain", [{"type": "lightning"}, {"type": "boat", "profile": [1]}])
COAST = timeline("coast_fog", [{"type": "surf"}, {"type": "moth"}, {"type": "birds"}])
SPRING = timeline("hotspring_snow", [{"type": "flurry"}, {"type": "gutter"}, {"type": "critter"}])


def mill_timeline():
    tl = timeline("river_night", [{"type": "critter"}, {"type": "birds"}])
    tl["audio"]["wheel"] = {"turn_s": 16, "paddles": 24}
    return tl

# what the words model drafted for the jungle temple, word for word
JUNGLE = {"name": "Moonvine Temple", "slug": "moonvine-temple-night", "music_word": "Calm Music", "music_tag": "calm minecraft music",
          "weather_word": "clear", "weather_tag": "clear night", "note": "shh, the ocelot's asleep",
          "caption": "moonvine temple, a clear night",
          "opening": "Come relax with clear night skies on a mossy jungle temple overhang by a waterfall, with calm Minecraft music "
                     "and the sound of the falls. 10 hours of 4K, calming ambience with smooth music. Never interrupting with ads.",
          "hashtags": ["#minecraftmusic", "#waterfallsounds", "#sleepmusic", "#study", "#relaxing", "#relax", "#4k", "#10hours"],
          "titles": ["Calm Music Moonvine Temple. Sleep and relax by the waterfall. 4K, 10 hours, no Ads",
                     "Calm Music Moonvine Temple. Study with waterfall sounds. 4K, 10 hours, no Ads",
                     "Calm Music Moonvine Temple. Rest under clear night skies. 4K, 10 hours, no Ads"]}


def finish(brief=None):
    return SimpleNamespace(brief=brief or {"place_name": "Moonvine Temple", "time": "night", "weather": "clear night with fireflies",
                                           "setting": "a mossy jungle temple by a waterfall, at night"},
                           scene="jungle-temple-night", has_music=True, minecraft=True, hours="10", look={})


class Mix(unittest.TestCase):
    def test_what_each_bed_and_event_sounds_like(self):
        self.assertEqual(set(facts(NIGHT, P, P)["sounds"]), {"howl", "frog", "fish"})
        self.assertEqual(set(facts(RAIN, P, P)["sounds"]), {"rain", "city", "lightning", "boat"})
        snow = facts(timeline("cabin_snow"), P, P)["sounds"]
        self.assertIn("fire", snow)
        self.assertNotIn("rain", snow)
        self.assertNotIn("fire", facts(timeline("cabin_snow", extra={"fire": None}), P, P)["sounds"])
        self.assertIn("fire", facts(timeline("quiet_night", extra={"fire": -2.0}), P, P)["sounds"])

    def test_silent_events_add_nothing(self):
        self.assertEqual(mix_sounds(timeline("quiet_night"), [{"type": "frog", "t": 1, "croaks": []}, {"type": "boat", "t": 2}]),
                         {"howl": "a soft wind"})

    def test_no_timeline_knows_no_sounds(self):
        fx = facts(None, P, P)
        self.assertEqual((fx["known"], fx["sounds"]), (False, {}))

    def test_the_coast_bed_is_its_waves(self):
        """The tide pool's draft (2026-11-05) could only name fog and a soft wind: the coast bed's surf, its waves and the
        sea's roar, was no sound the text knew."""
        self.assertEqual(set(facts(COAST, P, P)["sounds"]), {"howl", "surf"})

    def test_a_clock_ticks_only_where_one_plays(self):
        """The spruce cabin's pendulum clock ticks in the mix (audio "clock", 2026-11-06); a text may name it there only."""
        tl = timeline("cabin_snow")
        tl["audio"]["clock"] = {"hz": 0.5, "phase": 0, "db": -24}
        sounds = facts(tl, P, P)["sounds"]
        self.assertEqual(sounds.get("clock"), "a clock ticking")
        self.assertEqual(sound_problems("a fire crackling and a clock ticking softly", sounds), [])
        self.assertTrue(sound_problems("a clock ticking by the fire", facts(timeline("cabin_snow"), P, P)["sounds"]))

    def test_the_mills_river_and_waterwheel_are_named_where_they_play(self):
        """The Skyrim mill's river_night bed (2026-11-08): its draft could only name the fire and a soft wind 25 dB under
        it, while the river and the waterwheel carry the bed."""
        mill = facts(mill_timeline(), P, P)["sounds"]
        self.assertEqual(set(mill), {"river", "wheel", "fire", "howl"})
        night = facts(NIGHT, P, P)["sounds"]
        for t in ("the river's murmur", "#riversounds", "the sound of the river", "the waterwheel's churning"):
            with self.subTest(t=t):
                self.assertEqual(sound_problems(t, mill), [])
                self.assertTrue(sound_problems(t, night))
        self.assertTrue(sound_problems("the sound of the falls", mill))
        self.assertNotIn("wheel", facts(timeline("river_night"), P, P)["sounds"], "no wheel in the scene, no waterwheel heard")

    def test_the_springs_spout_is_named_where_it_pours(self):
        """The hot spring's hotspring_snow bed (2026-11-12): its bamboo spout pouring into the pool carries the bed, so a
        text may name it, and a spout's or trickling water's sound needs it."""
        spring = facts(SPRING, P, P)["sounds"]
        self.assertEqual(set(spring), {"spout", "howl", "flurry"})
        self.assertEqual(spring["spout"], "a bamboo spout pouring into the hot spring")
        night = facts(NIGHT, P, P)["sounds"]
        for t in ("a bamboo spout pouring into the hot spring", "trickling water", "the sound of the spout", "#hotspringsounds",
                  "#tricklingwater", "with water pouring into the pool", "the hot spring's sounds"):
            with self.subTest(t=t):
                self.assertEqual(sound_problems(t, spring), [])
                self.assertTrue(sound_problems(t, night))
        for t in ("a hot spring in the snowy woods", "#hotspring #onsen", "a bamboo spout"):
            with self.subTest(t=t):
                self.assertEqual(sound_problems(t, night), [], "the picture's spout and spring are no sound claims")
        self.assertEqual(sound_problems("rain trickling down the window", facts(RAIN, P, P)["sounds"]), [])
        self.assertTrue(sound_problems("Study and relax with calming rain", spring))
        self.assertTrue(sound_problems("a crackling fire", spring))


class Claims(unittest.TestCase):
    def test_the_jungle_drafts_false_sounds_are_caught(self):
        fields = {k for k, m in word_problems(finish(), JUNGLE, facts(NIGHT, P, P)) if "a sound this video doesn't have" in m}
        self.assertEqual(fields, {"opening", "hashtags", "title1"})

    def test_sounds_a_dry_night_doesnt_have(self):
        snd = facts(NIGHT, P, P)["sounds"]
        for t in ("and the sound of the falls", "#waterfallsounds", "Study with waterfall sounds", "the river's murmur",
                  "Study and relax with calming rain", "#rainsounds", "a rainy night", "a crackling fire", "#firesounds",
                  "crickets in the dark", "birdsong at dawn", "waves crashing", "#oceansounds"):
            with self.subTest(t=t):
                self.assertTrue(sound_problems(t, snd))

    def test_true_lines_pass(self):
        snd = facts(NIGHT, P, P)["sounds"]
        for t in (*JUNGLE["titles"][::2], "a red-eyed tree frog that croaks now and then", "a jungle rainforest temple",
                  "watch the falls", "#waterfall", "a rainbow over the falls", "#minecraftmusic #sleepmusic"):
            with self.subTest(t=t):
                self.assertEqual(sound_problems(t, snd), [])
        rain = facts(RAIN, P, P)["sounds"]
        self.assertEqual(sound_problems("Lofi Ramen Alley. Study and relax with calming rain. #rainsounds", rain), [])
        self.assertTrue(sound_problems("a frog croaking in the rain", rain))

    def test_the_coast_names_its_waves_and_nothing_else_does(self):
        coast = facts(COAST, P, P)["sounds"]
        for t in ("Come relax with ocean waves on the rocks by a foggy tide pool", "#oceanwaves", "waves crashing on the rocks",
                  "Lofi Driftwood Shelter. Study and relax with ocean waves. 4K, 10 hours, no Ads"):
            with self.subTest(t=t):
                self.assertEqual(sound_problems(t, coast), [])
        self.assertTrue(sound_problems("Study and relax with calming rain", coast))
        self.assertTrue(sound_problems("relax with ocean waves", facts(NIGHT, P, P)["sounds"]))

    def test_the_template_is_true_on_a_clear_night(self):
        f, fx = finish(), facts(NIGHT, P, P)
        w = template_words(f, fx, None)
        self.assertEqual((w["weather_word"], w["weather_tag"], w["slug"]), ("clear", "clear night", "moonvine-temple-night"))
        self.assertTrue(w["opening"].startswith("Come relax on a clear night at a mossy jungle temple by a waterfall"))
        self.assertEqual(word_problems(f, w, fx), [])

    def test_the_template_still_rains_without_a_timeline(self):
        w = template_words(finish(), facts(None, P, P), None)
        self.assertEqual((w["weather_word"], w["weather_tag"]), ("rain", "soft rain"))


class Blurb(unittest.TestCase):
    def blurb(self, tl, brief=None):
        f = finish_video.Finish.__new__(finish_video.Finish)
        f._tl, f.dry, f.period, f.sc = tl, False, P, {}
        if brief is not None:
            f.brief = brief
        lines = f.blurb_lines()
        return None if lines is None else "\n".join(lines)

    def test_a_dry_night_names_its_own_sounds(self):
        text = self.blurb(NIGHT)
        self.assertIn("the ambience (wind, the frog's call, fish splashing and every other effect)", text)
        self.assertEqual(sound_problems(text, facts(NIGHT, P, P)["sounds"]), [])

    def test_rainy_videos_read_as_before(self):
        self.assertIn("(rain, wind and every other effect)", self.blurb(timeline("porch_rain")))
        self.assertIn("(rain, wind, the crackling fire and every other effect)", self.blurb(timeline("cottage_rain")))
        self.assertIsNone(self.blurb(RAIN))

    def test_snow_by_the_fire_has_no_rain(self):
        self.assertIn("(wind, the crackling fire and every other effect)", self.blurb(timeline("cabin_snow")))

    def test_the_coast_names_its_waves(self):
        text = self.blurb(COAST)
        self.assertIn("(the waves, wind and every other effect)", text)
        self.assertEqual(sound_problems(text, facts(COAST, P, P)["sounds"]), [])

    def test_the_mill_names_its_river_and_waterwheel(self):
        text = self.blurb(mill_timeline())
        self.assertIn("(the river, the waterwheel, wind, the crackling fire and every other effect)", text)
        self.assertEqual(sound_problems(text, facts(mill_timeline(), P, P)["sounds"]), [])

    def test_the_springs_recording_is_named_and_the_no_recordings_line_goes(self):
        """The spout is a CC0 recording (2026-11-12): his blurb says the ambience is synthesized and that no recordings or
        sound-effect libraries are used, which would be false."""
        text = self.blurb(SPRING)
        self.assertIn("the ambience (wind and every other effect) is synthesized in my engine. The water pouring from the "
                      "spout is a public domain recording. I love making", text)
        self.assertNotIn("recordings or sound-effect libraries", text)
        self.assertIn("\nNo stock footage.", text)
        self.assertEqual(sound_problems(text, facts(SPRING, P, P)["sounds"]), [])
        self.assertIn("No stock footage, recordings or sound-effect libraries.", self.blurb(NIGHT), "other videos keep his line")

    def test_he_can_keep_his_standard_description(self):
        """Truman 2026-11-15, approving the Yuzu Spring: don't change the description, he deals with the recording himself.
        The brief's publish.recording_note false keeps his lines, and the package check doesn't refuse them."""
        text = self.blurb(SPRING, brief={"publish": {"recording_note": False}})
        self.assertIn("the ambience (wind and every other effect) is synthesized in my engine. I love making", text)
        self.assertIn("No stock footage, recordings or sound-effect libraries.", text)
        self.assertNotIn("public domain recording", text)
        f = finish_video.Finish.__new__(finish_video.Finish)
        f.brief = {"publish": {"recording_note": False}}
        self.assertEqual(f.recorded({"spout", "howl"}), [])
        f.brief = {}
        self.assertEqual(f.recorded({"spout", "howl"}), ["the water pouring from the spout"])


class GameTitles(unittest.TestCase):
    """A video with a game's own music is titled in the form he gave Treetop and the jungle temple: he rewrote the
    jungle temple's drafted titles, which were in the ramen alley's form (docs/records/moonvine-temple-night/published.md),
    and the spruce cabin's and the Skyrim mill's drafts came out in that form again."""

    def skyrim(self):
        return SimpleNamespace(brief={"place_name": "Northlight Mill", "time": "night", "weather": "clear night with the northern lights",
                                      "setting": "a porch over a river mill at night"},
                               scene="skyrim-mill-night", has_music=True, minecraft=False, hours="10",
                               look={"franchise": "The Elder Scrolls V: Skyrim", "franchise_word": "Skyrim"})

    def titles(self, f, w, fx):
        return {k: m for k, m in word_problems(f, w, fx) if k.startswith("title")}

    def test_his_own_titles_pass(self):
        mine = {**JUNGLE, "opening": "Come relax on a clear night at a mossy jungle temple by a waterfall, with calm Minecraft music "
                                     "and a frog's call. 10 hours of 4K, calming ambience with smooth music. Never interrupting with ads.",
                "hashtags": ["#minecraftmusic", "#sleepmusic", "#study", "#relaxing", "#relax", "#4k", "#10hours"],
                "titles": ["4K calm jungle night with calm Minecraft music and waterfall, no ads (10 hours)",
                           "4K clear jungle night with calm Minecraft music and a frog's call, no ads (10 hours)"]}
        self.assertEqual(self.titles(finish(), mine, facts(NIGHT, P, P)), {})

    def test_the_ramen_alleys_form_is_caught_for_a_games_music(self):
        bad = self.titles(finish(), JUNGLE, facts(NIGHT, P, P))
        self.assertEqual(set(bad), {"title0", "title1", "title2"})
        mill = {"name": "Northlight Mill", "slug": "northlight-mill-night", "music_word": "Calm Music", "music_tag": "calm skyrim music",
                "weather_word": "clear", "weather_tag": "clear night", "note": "shh, the hound's asleep", "caption": "northlight mill",
                "opening": "Come relax on a clear night at Northlight Mill, with calm Skyrim music and a river flowing past. 10 hours of "
                           "4K, calming ambience with smooth music. Never interrupting with ads.",
                "hashtags": ["#skyrimmusic", "#firesounds", "#studymusic", "#study", "#relaxing", "#relax", "#4k", "#10hours"],
                "titles": ["Calm Music Northlight Mill. Rest by the fire under northern lights. 4K, 10 hours, no Ads",
                           "4K Nordic river mill at night with calm Skyrim music and a crackling fire, no ads (10 hours)"]}
        got = self.titles(self.skyrim(), mill, facts(mill_timeline(), P, P))
        self.assertEqual(set(got), {"title0"})
        self.assertEqual(word_problems(self.skyrim(), {**mill, "titles": mill["titles"][1:]}, facts(mill_timeline(), P, P)), [])

    def test_the_template_follows_the_game_form(self):
        f, fx = self.skyrim(), facts(mill_timeline(), P, P)
        w = template_words(f, fx, None)
        self.assertEqual(w["titles"], ["4K clear night at Northlight Mill with calm Skyrim music, no ads (10 hours)"])
        self.assertEqual(w["music_tag"], "calm skyrim music")
        self.assertEqual(word_problems(f, w, fx), [])

    def test_other_music_keeps_the_ramen_alleys_form(self):
        f = SimpleNamespace(**{**vars(self.skyrim()), "look": {"music": "chill lofi"}})
        w = template_words(f, facts(mill_timeline(), P, P), None)
        self.assertTrue(w["titles"][0].startswith("Lofi Northlight Mill. "))


class Tags(unittest.TestCase):
    def test_the_music_pairs_only_with_weather(self):
        w = {"music_word": "Calm Music", "music_tag": "calm minecraft music", "weather_word": "clear", "weather_tag": "clear night"}
        self.assertEqual(tag_lines(w, True), ("calm music", "calm minecraft music"))
        self.assertEqual(tag_lines(w, False), ("clear night", "clear night"))
        r = {**w, "music_word": "Lofi", "music_tag": "chill lofi music", "weather_word": "rain"}
        self.assertEqual(tag_lines(r, True), ("lofi & rain", "chill lofi music & rain"))


class CastRegion(unittest.TestCase):
    """The words say where the cast's species are native only when the whole cast shares a region (config/cast.json
    native_to): the Yuzu Spring's field-guide thumbnail called its Japanese macaque and stoat "two creatures of the
    Pacific Northwest" (2026-11-15)."""

    def test_only_a_troupe_from_one_region_gets_a_region(self):
        from cozy.publish.words import cast_region
        region = lambda cast: cast_region(SimpleNamespace(brief={"cast": cast}))  # noqa: E731
        self.assertEqual(region(["polyphemus-mothling", "garter-snake"]), "the Pacific Northwest")
        self.assertEqual(region(["snow-monkey", "long-stoat", "yuzu-sprite"]), "")
        self.assertEqual(region(["sea-otter", "snow-monkey"]), "", "a mixed cast names no region")
        self.assertEqual(region([]), "")

    def test_the_template_opening_follows_it(self):
        spring = finish({"place_name": "Yuzu Spring", "time": "night", "weather": "gentle snow", "cast": ["snow-monkey", "long-stoat"],
                         "setting": "a small hot spring in the snowy woods at night"})
        w = template_words(spring, facts(SPRING, P, P), None)
        self.assertIn("The friends here are a Japanese macaque and a stoat. ", w["opening"])
        self.assertNotIn("Pacific Northwest", w["opening"])


if __name__ == "__main__":
    unittest.main()
