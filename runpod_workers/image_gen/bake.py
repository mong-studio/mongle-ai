"""빌드 시 공개 모델 프리다운로드 — 콜드스타트 단축.

pipeline.py 와 동일한 방식으로 로드해 HF 캐시 레이아웃을 일치시킨다.
LoRA(private repo)는 런타임에 LORA_REPO_ID + HF_TOKEN 으로 받는다.
"""
from __future__ import annotations

import torch
from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
from PIL import Image
from rembg import remove

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

# rembg u2net 모델도 미리 받는다
remove(Image.new("RGB", (8, 8), (255, 255, 255)))
