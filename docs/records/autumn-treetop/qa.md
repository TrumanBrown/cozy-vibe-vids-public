# QA: treetop-plate 10h_loop_1h_at8h_seed11_v5

1h_at8h_seed11_v5 (28800-32400 s) looped 10 times; audio joins crossfaded over 3 s from re-synthesized unfaded audio. The video starts 0:05:00.0 into the hour, so an event at hour time t plays at t - 5 min (mod 60); the hour joins fall at 0:55:00.0 + n h. master_music.mp4: the same video with music, 30 tracks planned over the whole video (138 plays; music_plan.json).

Overall: **PASS**

| Check | Result | Detail |
|---|---|---|
| length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| hour_join_frames | PASS | {"at_s": 3300, "detail": "the 2 frames each side of the first join decode identical to the source hour's end/start"} |
| hour_join_audio | PASS | {"level_dip_db": 0.82, "step_vs_p999": 0.73, "at_s": 3300} |
| loudness | PASS | {"lufs": -19.9, "lra": 2.0, "true_peak": -4.7} |
| music_length_sync | PASS | {"frames": 1080000, "expected": 1080000, "video_s": 36000.0, "audio_s": 36000.0} |
| music_hour_join_audio | PASS | {"step_vs_p999": 0.69, "at_s": 3300} |
| music_loudness | PASS | {"lufs": -16.2, "lra": 8.6, "true_peak": -2.4, "target": "-16.9..-13.9 LUFS (music bus -16.5, ambience -2 dB), true peak <= -1.5 dBTP"} |
