---
name: finish-video
description: "Truman approved a sample: build the 10 hour video and everything YouTube needs (the 20 minute loop window, the 10 h with music, thumbnails, title and description in his form, the upload folder), check it, and report what he uploads."
agent: "Video Studio"
argument-hint: "the scene, e.g. farm-porch-rain"
---

Truman approved the sample of the scene he typed after the command (ask with the ask_user tool if it is missing; `out/<scene>/auto/sample.md` names the scene).

1. Save his OK as approved references: `.venv\Scripts\python tools\critic.py <scene> --render <the approved sample's render folder> --approve --note "<his words>"`.
2. Run `.venv\Scripts\python tools\finish_video.py <scene>` in the background (about 1 to 2 hours: the 20 minute window renders on the GPU, then loop_master builds the 10 h files). It resumes where it stopped when run again. `--dry-run` first if anything about the scene changed since the sample.
3. Check its report in `out/<scene>/finish.md`: QA PASS on the window and the 10 h files, the thumbnails (look at `out/<scene>/thumbnails/preview.png` at phone size: 4K and 10 HR on each, every line readable), the title and description against his published form (master-render Upload checklist), and `upload_package.py`'s checks.
4. Report in his style: the upload folder's full path, the suggested thumbnail and the alternatives, the title, the AI-use answer, and the YouTube steps from the folder's README. Then stop. He uploads himself (Private first when the music needs YouTube's copyright check).
5. When he sends the link, run `/record-published <link>`.
