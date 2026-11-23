# QA: jungle-temple-night 10h_v2

loop20_v2 (1200-2400 s) looped 30 times; its timeline repeats every 20m (events.loop), so every join is frame- and sample-exact. The first segment is rendered again with the intro title. master_music.mp4: the same video with music, 30 tracks planned over the whole video (156 plays; music_plan.json).

Overall: **PASS**

| Check | Result | Detail |
|---|---|---|
| length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| loop_seam | PASS | {"max_diff": 0, "px_over_2": 0, "detail": "frame 72000 (just past the window) rendered identical to frame 36000 (its start)"} |
| hour_join_frames | PASS | {"at_s": 2400.0, "detail": "the 2 frames each side of a join decode identical to the source window's end/start"} |
| hour_join_audio | PASS | {"level_dip_db": 0.18, "step_vs_p999": 0.83, "at_s": 1200} |
| loudness | PASS | {"lufs": -20.0, "lra": 0.4, "true_peak": -8.5} |
| music_length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| music_hour_join_audio | PASS | {"step_vs_p999": 0.77, "at_s": 1200} |
| music_transitions | PASS | {"changes": 24, "dip_median_db": 0.0, "dip_max_db": 2.77, "worst": "An Ordinary Day -> O's Piano at 1:14:21.0", "detail": "the music's level over each of the first 24 track changes vs the 10 s on each side (fitted plan: every dip <= 6 dB)"} |
| music_loudness | PASS | {"lufs": -15.9, "lra": 8.0, "true_peak": -2.4, "target": "-16.9..-13.9 LUFS (music bus -16.5, ambience -2 dB), true peak <= -1.5 dBTP"} |
