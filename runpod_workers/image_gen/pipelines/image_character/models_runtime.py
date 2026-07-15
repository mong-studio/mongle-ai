"""Model loaders used by the production single-image pipeline."""

from __future__ import annotations

import gc
import os

from model_refs import LCM_LORA, SDXL_BASE

CHAR_LORA_SOURCE = os.environ.get("CHAR_LORA_SOURCE", "Hadimeeee/mongle-character-lora")
LCM_LORA_SOURCE = LCM_LORA.repo_id
BASE_MODEL = SDXL_BASE.repo_id


def load_text2img_pipeline(lora_scale: float = 0.75):
    import torch
    from diffusers import LCMScheduler, StableDiffusionXLPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for image-character generation")

    pipe = StableDiffusionXLPipeline.from_pretrained(
        BASE_MODEL,
        revision=SDXL_BASE.revision,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.load_lora_weights(LCM_LORA_SOURCE, adapter_name="lcm", revision=LCM_LORA.revision)
    pipe.load_lora_weights(CHAR_LORA_SOURCE, adapter_name="pixel_art")
    pipe.set_adapters(["lcm", "pixel_art"], adapter_weights=[1.0, lora_scale])
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.to("cuda")
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()  # VAE decode 피크 OOM 방지(타일 디코드)
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
