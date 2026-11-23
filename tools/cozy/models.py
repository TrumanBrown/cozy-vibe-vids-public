"""Every local model the tools load, pinned to the revision in use (TASKS.md T8).

An upstream push can't change a plate, its masks, a fire clip or a music match: the same key art gives the same
result on any machine. The revisions are the ones in cache/hf on the desktop on 2026-10-26, so nothing downloads
again. Moving a model forward is a deliberate change: edit it here, run what it makes, and record the goldens again.
"""

REVISIONS = {
    "depth-anything/Depth-Anything-V2-Small-hf": "5426e4f0f36572d16453bbda7a8389317b1bef99",   # plate_prep depth
    "caidas/swin2SR-classical-sr-x4-64": "c69ef3e2d2ac5777ff4a9f2f5afcd86d20604b7e",           # plate_prep upscale
    "facebook/sam2.1-hiera-large": "665f8e2ad61cf5f53d65644ff27c8ee525124610",                  # analyze_plate, pet_clips
    "Wan-AI/Wan2.2-TI2V-5B-Diffusers": "b8fff7315c768468a5333511427288870b2e9635",             # fire clips
    "laion/larger_clap_music": "a0b4534a14f58e20944452dff00a22a06ce629d1",                      # music_like
    "stabilityai/stable-diffusion-xl-base-1.0": "462165984030d82259a11f4367a4eed129e94a7b",     # enhance, gen_textures
    "madebyollin/sdxl-vae-fp16-fix": "207b116dae70ace3637169f1ddd2434b91b3a8cd",
    "diffusers/controlnet-depth-sdxl-1.0": "17bb97973f29801224cd66f192c5ffacf82648b4",
    "diffusers/controlnet-canny-sdxl-1.0": "eb115a19a10d14909256db740ed109532ab1483c",
}


def revision(repo):
    """The pinned revision of a model repo. A model that isn't pinned yet raises: add it here first."""
    try:
        return REVISIONS[repo]
    except KeyError:
        raise KeyError(f"{repo} has no pinned revision: add it to tools/cozy/models.py (TASKS.md T8)") from None
