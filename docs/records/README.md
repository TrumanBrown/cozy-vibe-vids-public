# Records of published videos

Each published video gets a folder here:
- `published.md`: the title, description, tags, category and thumbnail exactly as they went live, read from the video's page, and what Truman changed from the draft. The next video's draft starts from these (master-render skill, Upload checklist step 4).
- The render's small records: `qa.md` (the checks it passed), `loop.json` (how it was looped), `music_plan.json` (every track and when it plays) and, where there are any, `credits.txt`.

The source window or hour stays in `out/` with its `seg/`, so the video can be rebuilt after a claim (master-render skill, "Upload checklist").

| Folder | Video | Published | Rebuild from |
|---|---|---|---|
| [rainy-ramen-alley](rainy-ramen-alley/published.md) | [Lofi Ramen Alley](https://www.youtube.com/watch?v=GjF9esap044), 10 h, lofi | 2026-10-20 | the 20 minute window `out/ramen-alley/render/loop20_v1` and its intro segment: `.venv\Scripts\python tools\loop_master.py out\ramen-alley\render\loop20_v1 --times 30 --name 10h_v1`. The 10 h folder `10h_v1` is still there. |
| [autumn-treetop](autumn-treetop/published.md) | [Autumn Treetop](https://www.youtube.com/watch?v=ftYyRPbOgTU), 10 h, Minecraft music | 2026-10-16 | the hour `out/treetop-plate/render/1h_at8h_seed11_v5`: `.venv\Scripts\python tools\loop_master.py out\treetop-plate\render\1h_at8h_seed11_v5 --times 10 --offset 5m` (the offset is in loop.json here; with the 10 h folder gone the tool can't read it, so pass it). About an hour and 220 GB of free disk for both files. |
