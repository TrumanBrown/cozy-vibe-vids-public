---
name: marketing-outreach
description: "Launch and grow cozy-vibe-vids videos without spam: YouTube packaging and Shorts, Pinterest pins, channel posts and pinned comments, Reddit and forum posts that follow each community's rules, Discord, creator collab outreach, and the campaign log. Use when: launching a video (Treetop or a new scene), planning a week of posts, checking whether a subreddit or forum allows self-promotion, drafting a post, pinned comment, Short caption or collab note, reading Studio numbers, or logging a campaign. Draft-only: Truman posts."
---

# Marketing and outreach

Grow the channel by putting each video where the right viewers already are, in places that allow it. Agents draft, plan and log. Truman posts, comments and messages himself.

## The channel and the first video

- Sweater Weather Productivity, @SweaterWeatherProductivity. Each video is one 10-hour ambience scene: rain, a storm passing, a cat on a cushion, a lantern boat. 4K, no ads for now. The music is from Mojang's Minecraft soundtrack, credited in each description.
- Viewers study, work from home or sleep with a scene on. The title, the thumbnail and the first minutes do most of the work. The video opens on the storm, with strikes at 1:39, 2:36, 3:35 and 5:13 in video time.
- First video: https://www.youtube.com/watch?v=ftYyRPbOgTU, "4K rainy autumn treehouse with calm Minecraft music and distant thunder, no ads (10 hours)". Use this clean link. The `&t=286s` version starts at 4:46.
- Upload folder: `upload/autumn-treetop/`. Facts for copy: `assets/publish/treetop-plate.json` and `assets/publish/channel.md`.

## Rules

The media and outreach agent's hard rules apply. In short: draft only; no bots or scheduled posting; no comments or messages to other creators' audiences; one post per place per video, written for that place; check and log each place's rules first; link, never re-upload; no AI mention in public text except a truthful answer when asked; "Minecraft" only as a secondary word; tag only people Truman names; personal data stays in `marketing/private/`.

The five marketing skills in `.agents/skills` (launch, social, community-marketing, content-strategy, analytics; from coreyhaines31/marketingskills, MIT) give general guidance for structure, hooks, calendars and analysis. Where they suggest direct messages to many people, seeded or pre-filled posts, engagement bait, cold outreach or scheduling automation, these rules win.

## What works, in order of value

1. Packaging and search. A title with search terms first, 4K and length; a thumbnail chosen with Test & compare; the first lines of the description; tags. Studio's traffic source types (Search, Browse, Suggested, External, Playlists) show where viewers come from.
2. Shorts from real moments. Three to five per video, each cut from a different event in the timeline (`out/<scene>/render/<tag>/timeline.json`; the description may not list moments, since Truman drops the list), each under a minute, each with the full 10 hours in the link. One a day at most. Each Short shows different footage, so no two look like the same clip.
3. Playlists. One per series, for example "rain and thunder" or "study scenes", so a viewer who finishes one can start the next. Few viewers reach the end of a 10-hour video, so don't rely on end screens.
4. Pinterest pins made from frames of the video, linking to it. Pinterest adds an "AI modified" label on its own when it detects AI. Leave the label on, and answer truthfully when asked.
5. Channel posts and pinned comments with a real question, such as which place should be next. YouTube's policy allows asking viewers to comment.
6. Places that allow it. r/study once a week, in the self-promotion megathread, as one comment. r/Relaxation after the account has real participation there, one post per video, Truman's call. Discord servers whose moderators say yes first.
7. Creator collabs. Five at most a month, personal, specific, in Truman's words. No mass sends.
8. Direct answers. A viewer asks for a rain or study video in a comment, and Truman answers once in his own words.

## Not doing, and why

- Comments on other creators' videos that send their viewers to us, including viewers who seem unhappy with their video. YouTube's spam policy names "check out my channel" messages posted across many videos as comment spam. The Terms (section 5) bar unsolicited promotion and mass solicitation.
- Bots, scripts, scheduled comments, sub-for-sub, bought or incentivised views, subscribers or likes, and second accounts. The Terms ban automated access (section 3) and incentivised engagement (section 6).
- The same text in several places. Communities remove cross-posts, and they look like spam.
- r/relax. Its rules ban AI content (rule added 2026-05-31) and send YouTube links to r/Relaxation.
- r/Minecraft. Its rules call content that only resembles Minecraft's graphics off topic.
- Re-uploads of the full video or its audio anywhere.

## Music in Shorts (open)

Mojang's Creator-Safe Playlist is described as royalty-free music for creators' content "provided it abides by the Minecraft Usage Guidelines". Mojang's usage pages wouldn't load on 2026-10-16, and a search summary says the allowance is mainly for Minecraft-related content. Until someone checks, Shorts use ambience-only audio (rain and thunder, no soundtrack), taken from the render's ambience track (see the master-render skill). The full video keeps its music and the existing copyright-check step.

## Launch checklist (a new video)

1. Packaging check against `upload/<slug>/` and, once live, `docs/records/<slug>/published.md`: title with 4K and length, thumbnail, description, tags.
2. Pinned comment, from [templates.md](references/templates.md). Truman posts it.
3. A channel post, if the Posts tab is available.
4. Shorts plan: pick three to five moments from the timeline, check each one in the master, cut with the ffmpeg skill, ambience-only audio. Truman picks vertical or 16:9.
5. One or two Pinterest pins from frames, linking to the video.
6. Places: check each place's rules on the day, then draft at most one post per place.
7. Log every item in `marketing/campaign-log.csv`.

## Weekly rhythm

- Up to three outward items, Truman's call.
- Draft replies to comments on our own videos and posts.
- Truman shares the last seven days of Studio numbers. Log them.
- Change one thing at a time, then measure.

## Measure

- Week 1 is the baseline: impressions, click-through rate, average view duration, subscribers, and traffic source types.
- After each outward item, compare the next seven days with the baseline. Log the date and the place.
- Keep Studio exports in `marketing/private/`.
- Open question from `docs/research-aesthetics.md`: whether Shorts send viewers into the long videos in this niche. Test it with these numbers.

## Procedures

### Check a place's rules

1. Read the rules page, the sidebar, and any self-promotion wiki or megathread rule, with the web tools. If a page won't load, ask Truman to paste the rules.
2. Note the place, the rules in one or two lines, and the date in the log's `rules_checked` column.
3. Decide: allowed as written, allowed with conditions, or skip. Skip when a rule bans it.

Reddit's platform-wide rules apply under each community's rules. The channel's account is the one in `marketing/private/accounts.md` (local only). Before any Reddit draft, read its age and karma on the profile page that day, and check the target subreddit's Poster Eligibility Guide on the account (see the gate below).

### Reddit gate and history

The channel's only Reddit account (`marketing/private/accounts.md`) was created 2026-10-16. No link goes out from it, and no comment with a link, until all four are true on the day:

- The account is at least 4 weeks old.
- It has at least 100 karma.
- None of its comments has been removed by moderators.
- The target subreddit's Poster Eligibility Guide shows no unmet criteria. Read it by starting a post in that community, without submitting.

The first three numbers are our own margin. Reddit doesn't publish community thresholds.

Until the gate is met, Truman builds history by hand: his own replies in study threads (suggested: r/Studying, r/studytips and r/productivity, see [platforms.md](references/platforms.md)), with no links and no mention of the channel. The agent doesn't draft these replies, so they don't turn into templated text. The agent can suggest threads and log them.

### Draft and check

1. Write the text in Truman's voice (truman-voice skill), then run the humanizer pass.
2. Save it as `marketing/drafts/<slug>/<platform>-<kind>-<n>.txt`, text only. Kinds: `youtube-title`, `youtube-description`, `youtube-comment`, `reddit-title`, `reddit-post`, `reddit-comment`, `pinterest-title`, `pinterest-description`, `x-post`, `discord-message`.
3. Run `.venv\Scripts\python tools\marketing_check.py marketing\drafts\<slug>` and fix every problem it reports.
4. Log it as drafted. Show Truman the full text, the place, the rules checked and the link.

### After Truman posts

Set the log status to posted, and add the link and the date. Check the numbers seven days later.

## References

- [platforms.md](references/platforms.md): each place's rules, the sources, and the date checked.
- [templates.md](references/templates.md): starting text for each kind of post.
