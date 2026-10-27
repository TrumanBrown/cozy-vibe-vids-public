---
name: new-sample
description: "Make a new video sample from one line: a look or an idea (minecraft style, pixel 8 bit style, a real life farmscape scene). Runs the autopilot to a polished 5 minute sample with music, fixes whatever its review gates find, and reports for Truman's OK."
agent: "Video Studio"
argument-hint: "the idea, e.g. pixel 8 bit style, or a real life farmscape scene"
---

Make a new video sample for the idea Truman typed after the command. If he typed nothing, ask him for the idea with the ask_user tool.

1. Read the top of [docs/STATUS.md](../../docs/STATUS.md) and the Autopilot section of [the new-video skill](../../.agents/skills/new-video/SKILL.md).
2. Start `.venv\Scripts\python tools\autopilot.py run "<the idea>"` in the background and follow `out/<scene>/auto/progress.md` (the scene name is in its first line). Don't view images you don't need: every image you view stays in the session log.
3. At a gate (exit 2) fix the cause and its whole class, then resume with `--from <stage>` as the skill says. At a failure (exit 1) read the stage's log, fix, resume. At the budget stop (exit 3) ask him.
4. When `out/<scene>/auto/sample.md` is written, do your own eye pass (the critic's UNSURE items, the first 15 s at 1:1, the first appearance of each event type).
5. Report in his style: the sample's full path, the key-art sheet's full path, the look (and whether it is new), the opening line, what happens when, what you fixed on the way, the spend. Then stop and wait for his OK.
