"""SDXL feed generation from a canonical character profile and scene text."""

from __future__ import annotations

import gc
import os

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

CHARACTER_LORA = "Hadimeeee/mongle-character-lora"
BG_LORA = "Hadimeeee/mongle-bg-lora"

# 캐릭터는 나중에 원본 스프라이트로 합성하므로, 배경에는 어떤 캐릭터도 그려지면 안 된다.
NEGATIVE = (
    "realistic, 3d render, photograph, blurry, dark, gloomy, watercolor, sketch, "
    "painterly, smooth illustration, modern city, urban, scary, violence, text, "
    "watermark, tiling, repeated, human, person, girl, boy, man, woman, humanoid, "
    "human body, human face, skin, hair, clothes, dress, shirt, close-up, cropped, "
    "zoomed in, macro, character, animal, creature, mascot, plush toy, doll, figure"
)


def build_prompt(quest_en: str) -> tuple[str, str]:
    """캐릭터 없는 '퀘스트 장면 배경' 프롬프트. quest_en 은 설정·소품 묘사다."""
    prompt = (
        f"monglestyle, cozy pastel sky island village background scene, {quest_en}, "
        f"no character, empty open foreground, 32-bit pixel art, pastel colors, wide shot"
    )
    prompt_2 = (
        "monglestyle, detailed cozy pixel art environment, soft pastel lighting, "
        "empty foreground, no character"
    )
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
    # 캐릭터는 합성으로 들어가므로 배경 생성에는 캐릭터 LoRA 를 끄고 배경 LoRA 만 쓴다.
    pipe.set_adapters(["character", "bg"], adapter_weights=[0.0, 1.1])
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True
    )
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()  # 1024² VAE decode 피크 OOM 방지(타일 디코드)
    return pipe


def generate(quest_en: str, pipe, seed: int = 42):
    import torch

    prompt, prompt_2 = build_prompt(quest_en)
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
