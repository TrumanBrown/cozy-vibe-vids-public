# QA: aquarium 10h_v3

C0140.MP4 looped 36 times (tools/footage_loop.py), then its first 720 frames once more so it runs a full 10 h (36011.976 s): the loop is source frames 35834-95774 (1000.00 s), its continuation dissolving into its start over 150 frames; the video opens 9541 frames into the loop (source frame 45375), the first 720 frames carry the intro line. Water (tools/water_bed.py, 1200 s periodic) under 30 tracks planned over the whole video (156 plays; music_plan.json). Color: Brilliance +2, Shadows -50, Contrast -77, Brightness -63, Black Point -5, Saturation +35, Warmth +51, Sharpness +30.

Overall: **PASS**

| Check | Result | Detail |
|---|---|---|
| pieces | PASS | {"frames": {"a": 720, "i": 720, "b": 59220}, "same_parameter_sets": true} |
| size | PASS | {"projected_gb": 213.3, "video_mbps": 47.0, "detail": "under YouTube's 256 GB with room to spare"} |
| length_sync | PASS | {"frames": 2158560, "expected": 2158560, "video_s": 36011.976, "audio_s": 36011.976} |
| joins | PASS | {"frames": [{"frame": 719, "source": 46094, "psnr": 43.75, "neighbours": 36.3, "pass": true}, {"frame": 720, "source": 46095, "psnr": 45.25, "neighbours": 36.39, "pass": true}, {"frame": 59939, "source": 45374, "psnr": 43.78, "neighbours": 35.83, "pass": true}, {"frame": 59940, "source": 45375, "psnr": 45.28, "neighbours": 35.93, "pass": true}, {"frame": 60659, "source": 46094, "psnr": 43.77, "neighbours": 36.32, "pass": true}, {"frame": 60660, "source": 46095, "psnr": 45.25, "neighbours": 36.39, "pass": true}, {"frame": 119879, "source": 45374, "psnr": 43.78, "neighbours": 35.83, "pass": true}, {"frame": 119880, "source": 45375, "psnr": 45.28, "neighbours": 35.93, "pass": true}, {"frame": 2098620, "source": 46095, "psnr": 45.25, "neighbours": 36.39, "pass": true}, {"frame": 2157839, "source": 45374, "psnr": 43.78, "neighbours": 35.83, "pass": true}, {"frame": 2157840, "source": 45375, "psnr": 45.28, "neighbours": 35.93, "pass": true}, {"frame": 2158559, "source": 46094, "psnr": 43.77, "neighbours": 36.32, "pass": true}], "detail": "frames each side of every kind of join decode as their own source frame (better than its neighbours)"} |
| dissolve | PASS | {"at_s": 1842.07, "psnr_blend": 40.4, "psnr_continuation": 29.38, "psnr_start": 29.06, "detail": "mid-dissolve frame is the blend of the loop's continuation and its start (150 frames, 840.8 s into every window)"} |
| music_loudness | PASS | {"lufs": -16.3, "lra": 12.7, "true_peak": -2.4, "target": "-17.9..-14.9 LUFS (music bus -16.5, water -35), true peak <= -1.5 dBTP"} |
| music_transitions | PASS | {"changes": 24, "dip_median_db": 0.0, "dip_max_db": 2.73, "worst": "Firebugs -> O's Piano at 5280 s"} |
| water_join | PASS | {"step_vs_p999": 0.95, "at_s": 1200, "detail": "where the water bed comes round again: no step"} |
| music_opening | PASS | {"music_over_water_p10_db": 15.1, "music_median_lufs": -17.7, "water_median_lufs": -35.0, "opener": "Broken Clocks", "detail": "4-34 s: the music 3 dB or more over the water 90% of the time"} |
| music_over_water | PASS | {"share_music_louder_while_playing": 1.0, "median_db": 17.5, "p5_db": 9.4, "rests_share": 0.094, "detail": "3 s loudness of the music over the water, 30 min from 0:04, while the music plays (within 12 dB of its level); pass: louder 95% of the time and by 6 dB or more in the median. In the rests the water carries."} |
