# Art direction: key art that doesn't read as AI slop

Truman, 2026-10-25, after the comic bus stop's key art: it looked far too much like other AI art, with nothing unique in it. The references he likes each have their own artistic style, unique animals, varied colors, lines that aren't always clean and very detailed lighting, and you can tell people spent a long time drawing them. He expects that level of detail in every video.

His six references are kept locally in `cache/style_refs/truman-2026-10-25/` (gitignored: they are other artists' work). They teach principles. Never feed them to the image model, never copy their characters, never name a living artist in a prompt.

## The references, one by one

| # | What it is | What makes it hand-made |
|---|---|---|
| 1 | A huge spiky moss monster with orange eyes looming over a tiny white spirit on a bamboo-forest path (portrait) | One hue family (yellow-green to deep teal) with a single accent, the orange eyes. Thin outlines in dark green, never black, the same weight throughout. Every fern leaf drawn as its own slightly different shape. Flat fills with one light tone, no gradients, no glow. Scale story: the giant and the tiny one. The brightest value (the white spirit) is the focal point. |
| 2 | Two original blob creatures wrapped in one rust knitted blanket on a window seat, one reading, one playing a handheld console; a melting candle, fairy lights, lace curtains, a snowy pine forest outside | Ink lines that vary, taper and break (wood grain as a few long broken strokes). Paint with visible grain, like gouache or a print. Warm rust and brown inside against cool steel blue outside, muted (chroma about 24). Light from the candle and the bulbs, faces lit by them; the wall corners left dark. A specific, funny moment: two friends, a book and a game. Detail only on the seat; the walls are simple. |
| 3 | Round frog creatures under mossy stones: one stacked on another on a log bridge, one below, one sitting up in a plant | A painted anime background (soft stones, no outlines) under simple cel creatures with outlines. Dark, desaturated greens and grays; the creatures are the lightest, most saturated shapes. Soft diagonal light from the top left; most of the scene in shadow. A frog-scale world. |
| 4 | Night in a dark forest: a mushroom creature roasting a marshmallow, two frog creatures by a tiny campfire under a big leaf propped on a stick | About 90% of the frame near-black green; one small fire lights a small circle with a real falloff. A cool blue gap of moonlight far back. Dark grass silhouettes frame the bottom. The group is small, left of center, with lots of empty dark around it. Painterly background, simple lined creatures. |
| 5 | Grayscale painting: a white antlered serpent studies a flower sprig on a stump; a baby one sleeps at the bottom right | Forms made from light and value, almost no lines. Loose, confident brush strokes; edges lost in shadow. Light shafts through tall trunks. A quiet story (a parent and a sleeping child). |
| 6 | A giant white antlered serpent curled on a red barn, guarding a huge egg; a dirt road, bushes, a teal sky | Chunky opaque gouache-like strokes, simplified shapes, lost and found edges. A limited palette: teal sky, brick red, white with cool blue shadows, warm greens. Faded hand-painted letters on the barn. Absurd scale story. Slightly imperfect perspective. |

Truman picked 1, 2, 4 and 5 as the direction (2026-10-25).

## What they share (the rules for our prompts)

1. **Their own creatures.** Made-up beings with simple, iconic shapes and tiny faces (two dot eyes, a small mouth or none). Never a stock cute animal in the model's default style.
2. **A small story.** Someone is doing something specific and a little funny: roasting a marshmallow, reading and gaming under one blanket, a dragon nesting on a barn. Never only "an animal sleeps in a cozy room".
3. **One medium, visible everywhere.** Gouache strokes, ink that tapers and breaks, brush grain, or clear flat color with pen lines. The same mark-making on every surface. Lines are colored (dark green, brown), not black, and sometimes left open.
4. **A chosen palette.** One family of hues plus one accent, muted. Shadows have a color (cool blue, deep green), they are not just darker.
5. **Light from a real source, and darkness allowed.** A candle, a fire, a window: each lights what is near it and falls off. Large areas can sit in shadow (the campfire frame is 90% dark). No glow on everything.
6. **Detail only where the eye goes.** The focal spot is drawn carefully; the rest is big simple shapes, silhouettes or empty space.
7. **Composition with intent.** Framing by trunks, curtains or foreground silhouettes; an unusual scale (tiny world, giant creature); the focus off center; quiet space around it.
8. **Imperfection.** Lines wobble a little, perspective is drawn by hand, painted letters are weathered.

## What made the bus stop slop

The model's stock "cozy lofi anime" template: a lamp-lit interior on one side and a wide wet view on the other, a glowing vending machine, power lines, lit farmhouse windows, misty mountains under a purple-orange dusk gradient, a wet road full of mirror reflections and glints. A stock red panda in the default cute style, evenly crisp black outlines, evenly fine fake texture on every surface, bloom on every light. The four candidates were nearly the same picture: the prompt never moved the model off its default. The pick model scored them 9 and 10 for art: it rewards polish, it does not see originality.

## Measured (the style metrics in out/style_refs/metrics.json, 2026-10-25)

All images brought to the same size (0.1 MP) first. Medians:

| | his references | rejected bus stop | our earlier key art |
|---|---|---|---|
| detail concentration (Gini over a 6x6 grid; high = detail in a few places) | 0.28 | 0.23 | 0.16 |
| thin dark lines, % of the frame | 1.1 | 4.1 | 5.9 |
| color of those lines (chroma; 0 = black or gray) | 25 | 15 | 15 |
| tiny bright spots (glints, wet sparkle, bokeh), % | 0.25 | 0.56 | 1.09 |
| fine fake texture inside flat areas | 0.61 | 1.66 | 2.78 |
| chroma p90 (the most saturated tenth) | 36 | 47 | 40 |

Read together: the references keep their detail in a few places, draw fewer and colored lines, have about half the glints, keep flat areas flat (their texture is broad brush grain, not fine noise everywhere) and stay less saturated. Our generated art spreads detail, black lines, glints and micro-texture evenly over the frame. These numbers can become a screen in the pick stage once a look is set.

## How to write a key-art prompt in a hand-made style

gpt-image follows long, concrete prompts. Write every block; vague words ("beautiful", "cozy", "detailed", "high quality") pull it back to its default.

1. **Style block first:** the medium and how it is applied (gouache with dry-brush strokes and paper grain; ink lines in a named color that taper and break; flat fills with one light and one dark tone), where it is careful (the characters) and where it is loose (the background), and the palette as named colors with the accent and the shadow color.
2. **The scene as a moment:** where, when, the weather, and what the characters are doing, specific and a little funny.
3. **The cast, word for word** from the cast sheet, the same in every video (recurring cast, Truman 2026-10-25).
4. **Light:** the one main source, what it lights and from which side, how far it reaches before it falls off, the secondary sources, the shadow color, and how much of the frame is dark.
5. **Composition:** camera height and direction, where the focal group sits (off center), what frames the picture, where the quiet space is.
6. **Pipeline needs:** 16:9, locked camera, no people, no text, no painted rain, steam, smoke or hanging drops, clear glass, open space around lights and windows.
7. **Avoid list:** no glossy or plastic surfaces, sparkles, bokeh, lens flare, bloom halos, glowing particles, god rays, glinting wet reflections, sunset gradient skies, teal-and-orange grading, HDR detail on every surface, airbrushed gradients, machine-clean outlines, shiny anime eyes, blush stickers. And the positive version: leave large areas simple, detail only where the eye goes.

## His decisions on the new direction (2026-10-25)

- References 1, 2, 4 and 5.
- Original made-up creatures, not real animals.
- They may be awake doing something quiet (reading, a handheld game, roasting something over a fire), with breathing and blinks drawn in code. Nothing generated: the 2026-10-18 rule against generated video of a painted character stands.
- A recurring cast for the channel: the same characters in future videos.
- The scale changes per video: a tiny world, a normal room, a giant creature.
- **Approved styles** (after the test rounds he liked them all and asked to keep these styles): style A, inked and painted, and style C, loose brushwork, saved word for word as the looks `ink-gouache` and `brushwork-night` in config/aesthetics.json, with the bare-window treatment (strip the room to what the story needs). Approved images: `assets/reference/styles/`.
- **The model:** gpt-image-2 for these looks (the looks' `keyart_model`), about $0.29 an image.
- **The cast** (config/cast.json): his Pacific Northwest picks from the round 4 lineups: the polyphemus mothling (it carries the cast's one lantern), the pygmy short-horned lizard (sagebrush and moss growing on it), the graceful decorator crab (a garden on its back), the northwestern garter snake (a fern sprout and a knitted scarf) and the banded alder borer (a hiking pack, his look pending). The salamander (his addition: a classic Pacific Northwest animal) is the western red-backed salamander holding a salal leaf like an umbrella. The stone toad and the moss newt are out ("too similar").
- **The first video's four:** the mothling, the short-horned lizard, the garter snake and the red-backed salamander, at the tiny campfire in the rain (config/cast.json `first_video`).
- **One lantern in the whole cast** (not everyone holds a lantern: other items, or nothing, look better): the mothling's, because a moth that brings its own light is the joke. Every other creature has a different touch or holds nothing.
- **Pacific Northwest creatures:** every cast member is based on a PNW animal, with its real colors and markings on a rounder, softer storybook body.
- **A silly, unrealistic touch on each,** ideally one the code can animate: the lantern, a scarf blowing, plants growing on them. Never completely realistic.
- **The story makes sense.** A roasted blackberry didn't. A scene's activity is one people really do (warming up at a fire, waiting for a pot of soup, reading), never an odd stand-in picked for scale.
- **First video:** the tiny campfire in style A.

## Process for a new look

1. A test batch: a few styles from his picks, the same scene and cast in each, so only the style changes. Look at every image yourself against the rules above before he sees it.
2. He picks; the style block, palette and cast descriptions are frozen in the look (config/aesthetics.json) and reused word for word. Characters are designed on a plain-paper lineup first (one image, all candidates side by side), then pasted into scenes word for word from config/cast.json.
3. Only then the autopilot. A new look always stops at the key-art sheet for his OK (L135).

## In the pipeline (tools/new_video.py)

- A look with `keyart_model` generates with it (`ink-gouache` and `brushwork-night`: gpt-image-2).
- A brief with `cast` (ids in config/cast.json) gets the cast's descriptions word for word, and the boilerplate's one-pet sentence becomes "no other creatures besides the characters described".
- A brief's `composition` follows the light; a look's `avoid` list ends the prompt.
- A look's `brief_rules` go to the plan model with the approved cast, so it writes `cast`, `composition` and a story that makes sense.

## Iteration log

- **Round 1 (2026-10-25):** styles A (inked and painted, refs 2 and 4), B (clear-line flat color, ref 1), C (loose brushwork, ref 5); a window seat in the rain and a tiny campfire under a burdock leaf; a draft cast (a river-stone creature with a clover sprout, a mothling). Prompts: `out/style_explore/round1/prompts.json`. Sheets: `out/style_explore/round1/sheet_*.jpg`.
  - **gpt-image-2.5-sunburst (the default) keeps its own house style.** All 12 images looked like one artist: polished, evenly detailed, fine noise texture on every surface, saturated fire, whatever the style words said ("flat fills", "loose brushwork", "one-hue palette" changed almost nothing).
  - **gpt-image-2 follows the medium.** The same prompt gave wobbly brown ink lines, mottled paint on paper, muted color and simpler rooms (`round1/crop_models_1to1.jpg`). It costs about 4 times as much (7,370 output tokens an image, about $0.29, against about $0.07).
  - **The content pulls harder than the style words.** "Cozy attic window seat with patchwork, string lights, candle" produced the stock cottagecore clutter (shelves, plants, framed pictures, rugs) in every style. Strip a scene to what the story needs and say what is not there.
  - **Every mention becomes a thing.** "Cool blue moonlight" drew a moon in all 14 images. Painted rain streaks came back once despite the pipeline line. Say "no moon", "the air is clear, no rain streaks drawn".
  - **What worked:** real darkness and a single fire with a falloff, the creatures reading as our own characters, the campfire under a leaf as a concept.
- **Round 2 (2026-10-25), gpt-image-2 only:** B and C on the campfire scene, and the window scene stripped bare (plank walls, nothing on them, one cushion, the candle as the only light inside, a named palette). `out/style_explore/round2/sheet_round2.jpg`. Now the three styles differ: B went to a one-hue green with clearer outlines and simpler shapes, C darker and bluer with forms made by light, the bare window much closer to reference 2's restraint. He approved A, C and the bare window.
- **Round 3 (2026-10-25): a cast lineup** in style A on plain paper (`out/style_explore/round3/sheet_cast.jpg`): the six creatures came out as a real hand-painted character sheet. The model read "a tail tip that glows like a paper lantern" as a lantern hanging from the tail and "scarf snake" as a snake in a knitted scarf; he liked both. A lineup on plain paper is the cheapest way to judge designs: one image, every candidate side by side.
- **Round 4 (2026-10-25): PNW versions** of each role with a silly touch, and the insect options (`out/style_explore/round4/`). He picked moth 3, lizard 3, crab 2, snake 4, insect 2. The model put a lantern on whatever the prompt let it ("carrying a tiny lantern", "holding a lantern on a twig"): three of his five picks held one.
- **Round 5 (2026-10-25):** the picked cast with one lantern (the mothling's), three touches for the alder borer (an alder-leaf umbrella, a knitted beanie, a hiking pack), and six PNW salamanders, each with a different touch (`out/style_explore/round5/`). The prompt says which one creature holds a lantern and that the rest hold nothing unless described. He found two drawing errors: the leaf umbrella cut off the beetle's antennae and the pack strap clipped through its arm (details like these can't ship, L138). He picked the western red-backed salamander, holding a salal leaf like the ensatina did (more recognizable, and it lives under leaves anyway).
- **Round 6 (2026-10-25):** the first video's four (mothling, short-horned lizard, garter snake, red-backed salamander with its leaf) and the alder borer with the pack, every held or worn thing described as it sits on the body (`out/style_explore/round6/`). Version 2 checked at 1:1: the hand around the twig, the lantern on its string, the scarf around the neck, the fingers around the leaf stem, six legs and whole antennae on the beetle. Saved as `assets/reference/styles/cast_lineup_round6.jpg`. The beetle's far strap is still unclear (the detail check flagged it once of two asks): look again before the beetle's first scene.
- **The detail check** (new_video.py pick, L138), tested: it flagged the round 5 pack beetle (strap through the arm) and passed round 6's mothling, snake and salamander. Without the vote it was unsteady (the same crops: a clipping strap one time, nothing the next), and it raised false alarms until told that things running off a crop's edge, a storybook creature's two arms and two legs, and small style differences are not errors.
- **The first scene, the Burdock Shelter (2026-10-25):** `scenes/leaf-campfire-rain`, look `ink-gouache`, the four friends at the tiny campfire under a burdock leaf in the rain, waiting on a pot of soup; the salamander arriving under its salal leaf. Four candidates on gpt-image-2 ($1.17), `out/leaf-campfire-rain/keyart_sheet.jpg`; the pick (with the detail check, $0.17) chose #4 and marked #1 and #3 down for the snake's scarf showing one end. At 1:1 #4 is clean. Measured against his references: thin dark lines 1.4% (refs 1.1, bus stop 4.1), glints 0.10% (refs 0.25), saturation p90 21 (refs 36); still busier fine texture than the references (1.5 against 0.6: moss stippled over the whole ground), so the next prompt for this look can ask for the ground as big simple shapes with texture only near the fire.
- **Revisions of #4 (2026-10-25, L139), `tools/keyart_revise.py`:** the lizard lifted in code (value, contrast, color inside its SAM outline: nothing redrawn); the salamander moved out into the rain, its leaf high, looking away (one edit, painted out and in together, worked); the mothling and its lantern moved away from the fire. The move took four tries: with the old spot inside the mask the edit model kept the mothling there and hung the lantern on the fire's side (r1, r2); painted out first (r3a) and then in with a mask over the new spot only, it worked once the lantern came first in the prompt (r4b; r3b left the lantern out). A variant at the roof's right edge (R) cut the lantern's light with the mask's straight edge. Result: `assets/keyart/leaf-campfire-rain/round1/hero_gpt-image-2_20261025-145312_4_varL.png`. **He rejected it** (L140): its lantern light was cut by the mask's edge too (I missed it at 1:1), the mothling sat in a corner, the lizard still blended, the salamander's snout looked like a lizard's.
- **Round 2 of the scene (2026-10-25):** a new image instead of more edits, staged as he described: the moth, snake and lizard around the fire, the salamander out in the rain holding its leaf and the lantern, one in each hand, looking for something; the lantern a scene prop (no longer in the mothling's design); the salamander's description with a blunt, rounded snout and smooth skin; the lizard lighter than the moss. He picked #3; its lizard was dodged and burned in code from +15.4 to +20.7 L over the ground (`hero_gpt-image-2_20261025-154404_3_lizard.png`). Composition changes are a new image, never edits that move characters.
