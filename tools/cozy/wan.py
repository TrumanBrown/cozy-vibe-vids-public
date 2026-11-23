"""The Wan 2.2 image-to-video model (TASKS.md T12), moved verbatim from pet_clips.py, which is retired for pets:
tools/fire_clips.py makes the fire clips with it.

  MODEL           the checkpoint (pinned in cozy/models.py)
  load_pipe()     the pipeline on a 12 GB GPU: fp8 weight storage, the VAE on the CPU and tiled
  VaeShuttle      moves the VAE to the GPU only around its own encode and decode

Importing this sets the Hugging Face cache to cache/hf and the CUDA allocator setting, as pet_clips and fire_clips do;
torch and diffusers load with load_pipe(), not at import.
"""
import os

from cozy.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from cozy.models import revision  # noqa: E402


MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"


def load_pipe():
    import torch
    from diffusers import WanImageToVideoPipeline
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16, revision=revision(MODEL))
    # fp8 weight storage (bf16 compute) keeps the 5B transformer at ~5 GB; the VAE stays on the CPU while the
    # transformer denoises and visits the GPU only to encode the first frame and decode (tiled). On Windows a
    # GPU that runs out of memory silently spills into shared RAM and gets ~5x slower, so keep headroom.
    pipe.transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.bfloat16)
    pipe.transformer.to("cuda")
    pipe.vae.enable_tiling()
    return pipe


class VaeShuttle:
    """Moves the VAE to the GPU only around its own calls (encode the first frame, decode the latents)."""
    def __init__(self, pipe):
        import torch
        self.vae, self.torch = pipe.vae, torch
        for name in ("encode", "decode"):
            fn = getattr(self.vae, name)

            def wrap(*a, _fn=fn, **k):
                self.vae.to("cuda")
                try:
                    out = _fn(*[x.to("cuda") if hasattr(x, "to") else x for x in a], **k)
                finally:
                    self.vae.to("cpu")
                    self.torch.cuda.empty_cache()
                return out
            setattr(self.vae, name, wrap)
