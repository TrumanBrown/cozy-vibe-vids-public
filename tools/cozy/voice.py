"""Truman's voice rules for public text, the part a program can check (TASKS.md T12), moved verbatim from
upload_package.py and intro_title.py. upload_package, finish_video, intro_title and marketing_check hold every title,
description, opening line and promotion draft to them.

  voice_problems(text, emoji=0)  what breaks the rules: dashes, emoji, stock AI words, exclamation marks (empty: passes)
  AI_WORDS                       public text never mentions AI (DECISIONS 2026-10-16)
  BRANDS                         brand and franchise names that the opening line and the video's own words leave out
"""
import re

AI_WORDS = re.compile(r"\bA\.?I\b|(?i:artificial intelligence|\bgpt\b|openai|midjourney|dall-?e|stable diffusion|"
                      r"\bai[- ]generated|\bgenerative\b)")
# The checkable part of Truman's voice rules (user-level truman-voice and humanizer skills, DECISIONS 2026-10-16).
DASHES = re.compile(r"[\u2013\u2014]|\s--\s")
EMOJI = re.compile(r"[\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff\U0001f000-\U0001faff]")
STOCK = re.compile(r"(?i)\b(?:stunning|breathtaking|vibrant|captivating|seamless(?:ly)?|robust|delve|tapestry|"
                   r"testament|nestled|immerse|immersive|embark|unleash|elevate|unlock|discover|dive in|deep dive|"
                   r"journey through|moreover|furthermore|additionally|ultimately|that said|worth noting|"
                   r"important to note|in conclusion|not just|more than just|isn't just)\b")
BRANDS = re.compile(r"(?i)\b(minecraft|mojang|microsoft|hogwarts|harry potter|ghibli|totoro|stardew|lofi girl|nintendo|pokemon)\b")


def voice_problems(text, emoji=0):
    """What breaks Truman's voice rules in written public text; empty when it passes. emoji: how many he allows
    (a title may carry 2, like the 🍜 and ☔ he put in the ramen title; none elsewhere)."""
    out = []
    if DASHES.search(text):
        out.append("an em or en dash in the written text (use a period, comma or colon)")
    em = EMOJI.findall(text)
    if len(em) > emoji:
        out.append(f"{len(em)} emoji or symbols in the written text ({' '.join(f'U+{ord(c):04X}' for c in em[:4])}; "
                   f"allowed here: {emoji})")
    if m := STOCK.search(text):
        out.append(f"stock AI wording in the written text ({m.group(0)!r})")
    if "!" in text:
        out.append("an exclamation mark in the written text")
    return out
