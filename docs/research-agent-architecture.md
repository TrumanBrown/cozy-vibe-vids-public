# How the agent setup is built, and why

Truman, 2026-10-21, asked for the whole process to be written down in the agent, the skills and the other files so it is reproducible and automated and doesn't take hours of his time each round; for research into how professional projects do it and the best architecture; and for a simple one-line start ("generate me a new youtube video sample for <idea>", a Minecraft style, pixel 8 bit or a real-life farmscape) after which the agent iterates by itself to a finished, polished sample he can OK before the 10 h render.

This file records what the research found (October 2026), what was built from it, and where the setup differs on purpose. Sources are numbered at the end.

## What the research says

- **Keep always-on context small; load the rest when needed.** AGENTS.md is read on every turn by every agent, so it holds stable facts and rules only [1][3][20]. Procedures go in Agent Skills, whose name and description are always visible but whose body and references load only when a task matches (progressive disclosure; SKILL.md under about 500 lines) [8][9][11]. Context rots as it grows, well before the window is full [20].
- **Pick the right artifact for each job** (VS Code's decision matrix [12]): a repeated multi-step process is a skill; a role with its own tools and voice is a custom agent [5][6]; a one-line entry point is a prompt file (`/command`) [7]; anything that must happen whatever the model does is a script or a hook [13].
- **Evaluator-optimizer before a human looks.** One step generates, another judges against explicit criteria and sends it back until it passes [18][19]. For images: gating pass/fail checks for the non-negotiables first, graded quality next, and human verdicts stored as labeled examples to calibrate the judge [22]. Rubrics split into small binary checks beat one overall score [23][24].
- **Vision judges have known biases.** They trust what they expect over the pixels [25], pairwise comparisons are easier to sway than absolute judgments [26], and position bias is common [27]. The fixes: absolute pass/fail per check, a reference shown as "what passing looks like", calibration against the owner's real verdicts, and re-anchoring over time [28][29].
- **Long runs need a progress log and resumable state** (the initializer and progress-file pattern): a run that dies mid-way picks up where it stopped instead of starting over [21].
- **Taste becomes evals.** Each owner complaint becomes a regression check that must keep passing; new kinds of work start as capability checks with a low pass rate and graduate once they pass reliably [30].

## What was built

| Piece | File | Pattern |
|---|---|---|
| One-line entry | `.github/prompts/new-sample.prompt.md` (`/new-sample <idea>`), or the Video Studio agent with the same sentence | prompt file [7] |
| The orchestrator | `tools/autopilot.py`: look, plan, keyart, pick, prep, analyze, clean, features, life, setup, checks, music, render, review, critic, report; state in `out/<scene>/auto/state.json`, a log in `progress.md`, resumable `--from <stage>`, a spend budget per run | deterministic workflow with a progress log [18][21] |
| The fixer and reporter | `.github/agents/video-studio.agent.md`: runs autopilot, fixes what a gate finds (the cause and its whole class), does the last eye pass, reports, stops once | custom agent [5] |
| Procedures | `.agents/skills/*/SKILL.md` (new-video, plate-weather, ambient-events, ambience-audio, master-render, keyart-pipeline, plate-scene), each with references | Agent Skills [8][9] |
| Rules that always apply | `AGENTS.md` (non-negotiables, working agreements, a short command list) | always-on instructions [1][3] |
| His settled taste as numbers | `config/defaults.json` (event rates, loop period, music settings, sample length, budget), applied by autopilot's `setup` | configuration, not prose |
| His revisions as regression checks | `.agents/skills/new-video/references/lessons.md` (L01 onward): each row says what he saw, what is built in, and how it is checked; `tools/review.py` runs every automatic check and lists the eye checks | regression evals [30] |
| The eye checks, automated | `tools/critic.py`: evidence cut from the render (steam crops 0.4 s apart, the pet, the gaps between legs, the rain, the opening line, event contact sheets with tight crops of small creatures, thumbnails), judged pass or fail per check by the vision model next to an approved reference from a published video, with his own words about what went wrong before; UNSURE when it can't see enough; a failure stands only when two of three independent judgments fail (the same frames once passed at 0.83 and then failed at 0.9) | gating VLM judge with rubric decomposition and self-consistency [18][22][23] |
| Judge calibration | `tools/critic_selftest.py`: the approved references must pass and synthetic failures of his past complaints (a steam box, wisps, rain on the pet, a dry gap, a missing opening line, an opening line off center, rain over a door's frame) must fail; 12 of 12 on 2026-10-21, 15 of 15 after the pixel greenhouse's round 2 | human-anchored calibration [22][29] |
| Approved references | `assets/reference/approved/<scene>/` with `index.json`; `critic.py --approve` adds a scene's passing evidence after his OK | labeled examples that grow with each approval [22][29] |
| What the plate offers | `tools/plate_features.py`: candidates on a gridded plate, refined on zoomed crops with a fine grid, snapped to the image (a wire's line, a lamp's lit glass, SAM surfaces for path ends), then judged again by the model; calibrated against the ramen alley's hand-traced perches, moth, petals and cup | generate, refine, verify |
| Music for a new look | `tools/music_auto.py`: CC0 sources and open-lofi per style, screened by the audio model within a budget, curated, ledgered | tool step inside the workflow |
| After his OK | `tools/finish_video.py`: the 20 minute loop window, the 10 h with music, thumbnails, the upload folder | deterministic workflow |
| After he publishes | `.github/prompts/record-published.prompt.md` (`/record-published <link>`): his changes recorded and folded into the templates | owner verdicts as labeled data [22] |

## Where it differs from the research, on purpose

- **A script orchestrates, not an agent with subagents.** The research suggests an orchestrator agent delegating to worker subagents [5][18]. The stages here are known in advance and each is already a tool, so a deterministic script runs them in order (Anthropic recommends workflows over agents when the steps are predictable [18]). The agent's judgment is spent where it is needed: fixing what a gate finds and the final eye pass. Subagents are still used for big independent jobs (research, building a new tool).
- **No hooks yet.** VS Code hooks are in Preview [13]. The gates are inside autopilot instead, which works the same in any chat surface. A `PostToolUse` hook that runs review.py after scene.json edits is a candidate once hooks are stable.
- **The lessons stay one table.** The research suggests splitting the lessons per stage [11]. They stay one table because review.py parses it and he reads it, with an index by stage at the top so an agent can read only the rows for the stage it is fixing.
- **Copilot Memory is not relied on** [15][16]. It expires after 28 days and is not reviewable in the repo. Everything that matters is in files under version control.

## How taste keeps getting captured

1. He approves a sample: `critic.py --approve` adds its evidence as approved references (the judge gets a reference from his own OKs for that look).
2. He flags something: a lessons row the same round; an automatic check in review.py when it is measurable, else a rubric line in critic.py's CHECKS plus a negative case in critic_selftest.py (every case still right); a change in config/defaults.json when it is about every video.
3. He publishes: `/record-published` records his edits and changes the templates so the next package matches.
4. A genuinely new kind of video (the first photoreal farm, the first pixel video) is a capability test: expect gates to catch new problems; each fix becomes a lesson and the check graduates into the regression set [30].

## Sources

1. https://agents.md (AGENTS.md standard)
3. https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions
5. https://code.visualstudio.com/docs/agent-customization/custom-agents
6. https://docs.github.com/en/copilot/reference/custom-agents-configuration
7. https://code.visualstudio.com/docs/agent-customization/prompt-files
8. https://code.visualstudio.com/docs/agent-customization/agent-skills
9. https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
11. https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
12. https://code.visualstudio.com/docs/agents/concepts/customization
13. https://code.visualstudio.com/docs/agent-customization/hooks
15. https://docs.github.com/en/copilot/concepts/prompting-and-context/copilot-memory
16. https://github.blog/changelog/2026-03-04-copilot-memory-now-on-by-default-for-pro-and-pro-users-in-public-preview/
18. https://www.anthropic.com/engineering/building-effective-agents
19. https://github.com/anthropics/claude-cookbooks/blob/main/patterns/agents/evaluator_optimizer.ipynb
20. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
21. https://www.anthropic.com/research/effective-harnesses-for-long-running-agents
22. https://developers.openai.com/cookbook/examples/multimodal/image_evals
23. https://arxiv.org/abs/2608.26956 (RubricRM)
24. https://arxiv.org/abs/2512.12220 (TechImage-Bench)
25. https://openreview.net/forum?id=4GWfYyo6FS (Vision Language Models are Biased)
26. https://arxiv.org/abs/2504.14716 (Pairwise or Pointwise?)
27. https://arxiv.org/abs/2406.07791 (Judging the Judges)
28. https://www.microsoft.com/en-us/research/publication/can-we-trust-llm-judges-a-study-of-capability-dependent-biases-and-multi-judge-ensemble-for-bias-calibration/
29. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0339920
30. https://www.anthropic.com/research/demystifying-evals-for-ai-agents

Numbers follow the research report's list; sources it cited that this file doesn't use are left out.
