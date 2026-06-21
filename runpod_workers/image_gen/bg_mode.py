"""배경 장면 생성 모드 (SDXL text2img + bg LoRA + LCM-LoRA).

adapter="bg" 요청을 처리한다. 텍스트 프롬프트(씬 묘사)를 받아 픽셀아트 배경
장면을 생성한다(피드 배경용). LoRA 는 `Hadimeeee/mongle-bg-lora` 기준:
  - 베이스: SDXL 1.0, 스케줄러: LCM, 8 step, guidance 1.5
  - bg 스타일 LoRA + LCM-LoRA 를 함께 올려 set_adapters 로 결합한다.
"""
from __future__ import annotations

import io

import torch
from diffusers import LCMScheduler, StableDiffusionXLPipeline
from PIL import Image

_BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_BASE_MODEL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"
# LCM 8-step 가속용 공개 LoRA — bg 스타일 LoRA 와 함께 결합한다.
_LCM_LORA = "latent-consistency/lcm-lora-sdxl"
_LCM_LORA_REVISION = "a18548dd4956b174ec5b0d78d340c8dae0a129cd"

_NEGATIVE_PROMPT = (
    "character, person, creature, mascot, text, watermark, signature, "
    "realistic, 3d render, blurry, photograph"
)

_SIZE = (1024, 1024)  # SDXL 네이티브 해상도
_STEPS = 8  # LCM 최적
_GUIDANCE = 1.5  # LCM 모드 권장
_BG_SCALE = 1.0  # 모델 카드 기본(--bg-scale)


class BgMode:
    """SDXL text2img + bg LoRA + LCM-LoRA 파이프라인 (CUDA 전용)."""

    def __init__(self, *, lora_source: str) -> None:
        dtype = torch.float16
        pipe = StableDiffusionXLPipeline.from_pretrained(
            _BASE_MODEL,
            revision=_BASE_MODEL_REVISION,
            torch_dtype=dtype,
            use_safetensors=True,
            variant="fp16",
        )
        # bg 스타일 LoRA 와 LCM-LoRA 를 named adapter 로 동시 등록 후 결합.
        pipe.load_lora_weights(lora_source, adapter_name="bg")
        pipe.load_lora_weights(_LCM_LORA, adapter_name="lcm", revision=_LCM_LORA_REVISION)
        pipe.set_adapters(["bg", "lcm"], adapter_weights=[_BG_SCALE, 1.0])
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.to("cuda")
        pipe.enable_attention_slicing()
        self._pipe = pipe

    def _to_bytes(self, image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def generate(
        self, *, source_image_bytes: bytes | None = None, prompt: str | None = None
    ) -> bytes:
        """bg 모드는 텍스트 프롬프트 기반 — source_image_bytes 인자는 사용하지 않는다."""
        if not prompt or not prompt.strip():
            raise ValueError("[ERROR] bg 모드는 'prompt' 가 필요합니다 (씬 묘사 텍스트)")
        result = self._pipe(
            prompt=prompt,
            negative_prompt=_NEGATIVE_PROMPT,
            num_inference_steps=_STEPS,
            guidance_scale=_GUIDANCE,
            width=_SIZE[0],
            height=_SIZE[1],
        ).images[0]
        return self._to_bytes(result)
