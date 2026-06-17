"""빌드 시 공개 모델 프리다운로드 — 콜드스타트 단축.

character_mode.py / bg_mode.py 와 동일한 방식으로 로드해 HF 캐시 레이아웃을 일치시킨다.
스타일 LoRA(private repo)는 런타임에 LORA_CHARACTER_REPO / LORA_BG_REPO + HF_TOKEN 으로 받는다.
공개 LCM-LoRA 는 빌드 시 받아 bg 모드 콜드스타트를 단축한다.
"""
from __future__ import annotations

import torch
from diffusers import (
    ControlNetModel,
    StableDiffusionXLControlNetImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from huggingface_hub import snapshot_download
from PIL import Image
from rembg import remove

# character 모드: SDXL + ControlNet(canny) img2img
controlnet = ControlNetModel.from_pretrained(
    "diffusers/controlnet-canny-sdxl-1.0",
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
)
StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    controlnet=controlnet,
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
)

# bg 모드: SDXL text2img 베이스(위와 동일 SDXL 캐시 재사용) + LCM-LoRA
StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
)
snapshot_download("latent-consistency/lcm-lora-sdxl")

# rembg u2net 모델도 미리 받는다
remove(Image.new("RGB", (8, 8), (255, 255, 255)))
