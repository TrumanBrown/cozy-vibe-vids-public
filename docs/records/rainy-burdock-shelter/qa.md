# QA: leaf-campfire-rain 10h_v1

loop20_v1 (1200-2400 s) looped 30 times; its timeline repeats every 20m (events.loop), so every join is frame- and sample-exact. The first segment is rendered again with the intro title. master_music.mp4: the same video with music, 24 tracks planned over the whole video (241 plays; music_plan.json).

Overall: **PASS**

| Check | Result | Detail |
|---|---|---|
| length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| loop_seam | PASS | {"max_diff": 0, "px_over_2": 0, "detail": "frame 72000 (just past the window) rendered identical to frame 36000 (its start)"} |
| hour_join_frames | PASS | {"at_s": 2400.0, "detail": "the 2 frames each side of a join decode identical to the source window's end/start"} |
| hour_join_audio | PASS | {"level_dip_db": 0.48, "step_vs_p999": 0.46, "at_s": 1200} |
| loudness | PASS | {"lufs": -19.3, "lra": 1.1, "true_peak": -6.2} |
| music_length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| music_hour_join_audio | PASS | {"step_vs_p999": 0.37, "at_s": 1200} |
| music_transitions | PASS | {"changes": 24, "dip_median_db": 1.48, "dip_max_db": 4.51, "worst": "April Showers -> Slow Dancing By the Stove at 0:14:53.1", "detail": "the music's level over each of the first 24 track changes vs the 10 s on each side (fitted plan: every dip <= 6 dB)"} |
| music_loudness | PASS | {"lufs": -15.3, "lra": 3.1, "true_peak": -2.1, "target": "-16.8..-13.8 LUFS (music bus -16.5, ambience -2 dB), true peak <= -1.5 dBTP"} |
