"""빌드 시 공개 모델 프리다운로드 — 콜드스타트 단축.

character_mode.py / bg_mode.py 와 동일한 방식으로 로드해 HF 캐시 레이아웃을 일치시킨다.
스타일 LoRA(private repo)는 런타임에 LORA_CHARACTER_REPO / LORA_BG_REPO + HF_TOKEN 으로 받는다.
공개 LCM-LoRA 는 빌드 시 받아 bg 모드 콜드스타트를 단축한다.

모델 가중치는 commit SHA(revision)로 고정해 빌드 재현성을 보장한다.
HF 429 rate limit 에는 지수 백오프로 재시도한다(llm/bake.py 와 동일 패턴).
"""
from __future__ import annotations

import time

import torch
from diffusers import (
    ControlNetModel,
    StableDiffusionXLControlNetImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from huggingface_hub import snapshot_download
from huggingface_hub.errors import HfHubHTTPError
from PIL import Image
from rembg import remove

# 모델 ID + commit SHA — bake 와 런타임 로더(character_mode.py, bg_mode.py)가 동일 값을 써야
# 런타임 캐시 히트가 보장된다. SHA 갱신 시 양쪽을 같은 PR 에서 함께 변경한다.
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_BASE_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"

CONTROLNET = "diffusers/controlnet-canny-sdxl-1.0"
CONTROLNET_REVISION = "eb115a19a10d14909256db740ed109532ab1483c"

LCM_LORA = "latent-consistency/lcm-lora-sdxl"
LCM_LORA_REVISION = "a18548dd4956b174ec5b0d78d340c8dae0a129cd"


def _with_backoff(fn, *, attempts: int = 5, base_delay: int = 15):
    """429 에 지수 백오프 재시도. 다른 오류는 즉시 재raise."""
    for attempt in range(attempts):
        try:
            return fn()
        except HfHubHTTPError as err:
            status = getattr(err.response, "status_code", None)
            if status == 429 and attempt < attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"HF 429 rate limit — {delay}s 후 재시도 ({attempt + 1}/{attempts})")
                time.sleep(delay)
                continue
            raise


# character 모드: SDXL + ControlNet(canny) img2img
controlnet = _with_backoff(lambda: ControlNetModel.from_pretrained(
    CONTROLNET,
    revision=CONTROLNET_REVISION,
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
))
_with_backoff(lambda: StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
    SDXL_BASE,
    revision=SDXL_BASE_REVISION,
    controlnet=controlnet,
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
))

# bg 모드: SDXL text2img 베이스(위와 동일 SDXL 캐시 재사용) + LCM-LoRA
_with_backoff(lambda: StableDiffusionXLPipeline.from_pretrained(
    SDXL_BASE,
    revision=SDXL_BASE_REVISION,
    torch_dtype=torch.float16,
    use_safetensors=True,
    variant="fp16",
))
_with_backoff(lambda: snapshot_download(LCM_LORA, revision=LCM_LORA_REVISION))

# rembg u2net 모델도 미리 받는다
remove(Image.new("RGB", (8, 8), (255, 255, 255)))
