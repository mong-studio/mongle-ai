"""SDXL feed generation from a canonical character profile and scene text."""

from __future__ import annotations

import gc
import os

from pipelines.shared.character_profile import normalize_profile


os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

CHARACTER_LORA = "Hadimeeee/mongle-character-lora"
BG_LORA = "Hadimeeee/mongle-bg-lora"

NEGATIVE = (
    "realistic, 3d render, photograph, blurry, dark, gloomy, watercolor, sketch, "
    "painterly, smooth illustration, modern city, urban, scary, violence, text, "
    "watermark, multiple characters, tiling, repeated, human, person, girl, boy, "
    "man, woman, humanoid, human body, human face, skin, hair, clothes, dress, "
    "shirt, close-up, cropped, zoomed in, macro, oversized character, character filling frame"
)


def _to_appearance_str(appearance) -> str:
    profile = normalize_profile(appearance)
    colors = " and ".join(profile["main_colors"][:2])
    identity = " ".join(part for part in (colors, profile["character_type"]) if part)
    parts = [f"a pixel art stuffed {identity} character"]
    for key in ("body", "silhouette", "face", "ears_arms", "outfit"):
        if profile[key]:
            parts.append(profile[key])
    parts.extend(profile["secondary_colors"][:3])
    parts.extend(profile["accessories"][:3])
    parts.extend(profile["must_preserve"][:5])
    return ", ".join(parts)


def build_prompt(appearance, quest_en: str) -> tuple[str, str]:
    profile = normalize_profile(appearance)
    colors = " and ".join(profile["main_colors"][:2])
    identity = " ".join(part for part in (colors, profile["character_type"]) if part)
    prompt = (
        f"monglestyle, full body shot, small {identity} character in a wide scene, "
        f"{quest_en}, 32-bit pixel art, pastel colors"
    )
    prompt_2 = f"monglestyle, {_to_appearance_str(profile)}"
    return prompt, prompt_2


def load_pipeline():
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
        use_safetensors=True,
    ).to("cuda")
    pipe.load_lora_weights(CHARACTER_LORA, adapter_name="character")
    pipe.load_lora_weights(BG_LORA, adapter_name="bg")
    pipe.set_adapters(["character", "bg"], adapter_weights=[0.9, 1.1])
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True
    )
    pipe.enable_attention_slicing()
    return pipe


def generate(appearance, quest_en: str, pipe, seed: int = 42):
    import torch

    prompt, prompt_2 = build_prompt(appearance, quest_en)
    return pipe(
        prompt=prompt,
        prompt_2=prompt_2,
        negative_prompt=NEGATIVE,
        num_inference_steps=25,
        guidance_scale=8.5,
        height=1024,
        width=1024,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]


def unload_pipeline(pipe) -> None:
    import torch

    del pipe
    gc.collect()
    torch.cuda.empty_cache()
