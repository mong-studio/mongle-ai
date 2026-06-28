"""Model loaders used by the production single-image pipeline."""

from __future__ import annotations

import gc
import os


CHAR_LORA_SOURCE = os.environ.get("CHAR_LORA_SOURCE", "Hadimeeee/mongle-character-lora")
LCM_LORA_SOURCE = os.environ.get("LCM_LORA_SOURCE", "latent-consistency/lcm-lora-sdxl")
BASE_MODEL = os.environ.get("SDXL_BASE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")


def load_text2img_pipeline(lora_scale: float = 0.75):
    import torch
    from diffusers import LCMScheduler, StableDiffusionXLPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for image-character generation")

    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.load_lora_weights(LCM_LORA_SOURCE, adapter_name="lcm")
    pipe.load_lora_weights(CHAR_LORA_SOURCE, adapter_name="pixel_art")
    pipe.set_adapters(["lcm", "pixel_art"], adapter_weights=[1.0, lora_scale])
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.to("cuda")
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    return pipe


def unload_pipeline(pipe) -> None:
    import torch

    try:
        pipe.to("cpu")
    except Exception:
        pass
    del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
