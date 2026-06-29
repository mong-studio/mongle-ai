"""SDXL 2단계 피드 생성.

1단계: 배경 LoRA 로 '퀘스트 장면 배경'(캐릭터 없음)을 text2img 로 생성.
2단계: 그 배경을 init 이미지로 삼아 캐릭터 LoRA 로 img2img → 장면 '안에' 캐릭터를
       그려 넣는다(PIL 합성 아님, 전부 모델 생성).

단일 패스로는 배경 LoRA 와 캐릭터 LoRA 가 경쟁해 '리치한 배경 + 또렷한 캐릭터'를
동시에 못 얻는다. 2단계로 배경(1단계)과 캐릭터(2단계)를 분리해 둘 다 확보한다.
"""

from __future__ import annotations

import gc
import os

from pipelines.shared.character_profile import normalize_profile


os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

CHARACTER_LORA = "Hadimeeee/mongle-character-lora"
BG_LORA = "Hadimeeee/mongle-bg-lora"

# img2img 재생성 강도(0~1). 높을수록 캐릭터가 강하게 들어오지만 배경이 더 덮인다.
# 0.5~0.7 이 배경 보존 ↔ 캐릭터 표현 균형점. 재빌드 없이 튜닝하도록 env 로 노출.
IMG2IMG_STRENGTH = float(os.environ.get("FEED_IMG2IMG_STRENGTH", "0.62"))

# 1단계 배경: 어떤 캐릭터/생물도 그려지면 안 된다(빈 장면).
BG_NEGATIVE = (
    "realistic, 3d render, photograph, blurry, dark, gloomy, watercolor, sketch, "
    "painterly, smooth illustration, modern city, urban, scary, violence, text, "
    "watermark, tiling, repeated, human, person, girl, boy, man, woman, humanoid, "
    "human body, human face, skin, hair, clothes, dress, shirt, close-up, cropped, "
    "zoomed in, macro, character, animal, creature, mascot, plush toy, doll, figure"
)

# 2단계 캐릭터: 사람/다중 캐릭터/프레임 꽉 채움은 막되, 'character' 자체는 허용한다.
CHAR_NEGATIVE = (
    "realistic, 3d render, photograph, blurry, dark, gloomy, watercolor, sketch, "
    "painterly, smooth illustration, scary, violence, text, watermark, "
    "multiple characters, tiling, repeated, human, person, girl, boy, man, woman, "
    "humanoid, human body, human face, skin, hair, clothes, dress, shirt, "
    "close-up, cropped, oversized character, character filling frame"
)


def _identity(profile) -> str:
    colors = " and ".join(profile["main_colors"][:2])
    return " ".join(part for part in (colors, profile["character_type"]) if part)


def _to_appearance_str(profile) -> str:
    identity = _identity(profile)
    parts = [f"a pixel art stuffed {identity} character"]
    for key in ("body", "silhouette", "face", "ears_arms", "outfit"):
        if profile[key]:
            parts.append(profile[key])
    parts.extend(profile["secondary_colors"][:3])
    parts.extend(profile["accessories"][:3])
    parts.extend(profile["must_preserve"][:5])
    return ", ".join(parts)


def build_bg_prompt(quest_en: str) -> tuple[str, str]:
    """1단계: 캐릭터 없는 '퀘스트 장면 배경'. quest_en 은 설정·소품 묘사다."""
    prompt = (
        f"monglestyle, cozy pastel pixel art scene of {quest_en}, "
        f"no character, empty open foreground, 32-bit pixel art, pastel colors, wide shot"
    )
    prompt_2 = (
        "monglestyle, detailed cozy pixel art environment, soft pastel lighting, "
        "empty foreground, no character"
    )
    return prompt, prompt_2


def build_char_prompt(profile, quest_en: str) -> tuple[str, str]:
    """2단계: 위 배경 위에서 캐릭터가 퀘스트를 하는 모습."""
    identity = _identity(profile)
    prompt = (
        f"monglestyle, a cute {identity} character {quest_en}, "
        f"full body, the character in the scene, 32-bit pixel art, pastel colors"
    )
    prompt_2 = f"monglestyle, {quest_en}, {_to_appearance_str(profile)}"
    return prompt, prompt_2


class FeedPipeline:
    """1단계 text2img + 2단계 img2img — 같은 모델 컴포넌트를 공유한다."""

    def __init__(self, txt2img, img2img) -> None:
        self.txt2img = txt2img
        self.img2img = img2img


def load_pipeline() -> FeedPipeline:
    import torch
    from diffusers import (
        DPMSolverMultistepScheduler,
        StableDiffusionXLImg2ImgPipeline,
        StableDiffusionXLPipeline,
    )

    txt2img = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
        use_safetensors=True,
    ).to("cuda")
    txt2img.load_lora_weights(CHARACTER_LORA, adapter_name="character")
    txt2img.load_lora_weights(BG_LORA, adapter_name="bg")
    txt2img.scheduler = DPMSolverMultistepScheduler.from_config(
        txt2img.scheduler.config, use_karras_sigmas=True
    )
    txt2img.enable_attention_slicing()
    txt2img.enable_vae_slicing()
    txt2img.enable_vae_tiling()  # 1024² VAE decode 피크 OOM 방지(타일 디코드)

    # img2img 는 같은 unet/vae/text_encoder 를 공유 → 추가 VRAM 없음.
    img2img = StableDiffusionXLImg2ImgPipeline.from_pipe(txt2img)
    return FeedPipeline(txt2img, img2img)


def generate(appearance, quest_en: str, pipe: FeedPipeline, seed: int = 42):
    import torch

    profile = normalize_profile(appearance)
    gen = torch.Generator("cuda").manual_seed(seed)

    # 1단계 — 퀘스트 배경(캐릭터 LoRA 끔)
    bg_prompt, bg_prompt_2 = build_bg_prompt(quest_en)
    pipe.txt2img.set_adapters(["character", "bg"], adapter_weights=[0.0, 1.1])
    background = pipe.txt2img(
        prompt=bg_prompt,
        prompt_2=bg_prompt_2,
        negative_prompt=BG_NEGATIVE,
        num_inference_steps=25,
        guidance_scale=8.5,
        height=1024,
        width=1024,
        generator=gen,
    ).images[0]

    # 2단계 — 그 배경 위에 캐릭터를 img2img 로 그려 넣음(캐릭터 LoRA 우위)
    char_prompt, char_prompt_2 = build_char_prompt(profile, quest_en)
    pipe.img2img.set_adapters(["character", "bg"], adapter_weights=[1.0, 0.4])
    return pipe.img2img(
        image=background,
        prompt=char_prompt,
        prompt_2=char_prompt_2,
        negative_prompt=CHAR_NEGATIVE,
        strength=IMG2IMG_STRENGTH,
        num_inference_steps=30,
        guidance_scale=7.5,
        generator=gen,
    ).images[0]


def unload_pipeline(pipe: FeedPipeline) -> None:
    import torch

    pipe.img2img = None
    pipe.txt2img = None
    gc.collect()
    torch.cuda.empty_cache()
