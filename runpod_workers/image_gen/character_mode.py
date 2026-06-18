"""캐릭터 픽셀아트 생성 모드 (SDXL + character LoRA, 두 경로).

adapter="character" 요청을 처리한다. mongle-character-lora 모델 카드의 두 경로를 쓴다:
  - 사진 있을 때: 표준 img2img + ControlNet(canny) — 30 step, guidance 7.5, CN 0.75
  - 사진 없을 때: LCM text2img(외형 묘사 prompt) — 8 step, guidance 1.5 (+ lcm-lora-sdxl)
공통: 트리거 `monglestyle`, character LoRA scale 0.9.
사람이 읽는 프롬프트 카탈로그: adapters/character_creation/prompts/image_gen_v1.md
"""
from __future__ import annotations

import io

import cv2
import numpy as np
import torch
from diffusers import (
    ControlNetModel,
    LCMScheduler,
    StableDiffusionXLControlNetImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from PIL import Image
from rembg import remove

# mongle-character-lora 트리거(monglestyle)로 시작하는 고정 스타일 가드.
# 캐릭터 묘사는 ControlNet(사진 윤곽)이 담당하므로 프롬프트는 스타일만 고정한다.
_PROMPT = (
    "monglestyle, single stuffed animal toy mascot character, full body, "
    "centered, front view, cute chibi proportions, 32-bit pixel art sprite, "
    "soft pixel shading, clean silhouette, thick dark outlines, flat coloring, "
    "sharp pixel edges, no anti-aliasing, no gradients, pure white background"
)
_NEGATIVE_PROMPT = (
    "realistic, 3d render, blurry, smooth, photograph, gradient, shadow, "
    "anti-aliasing, soft edges, painterly, watercolor, sketch, detailed texture"
)

_SIZE = (512, 512)
_CANNY_LOW = 80
_CANNY_HIGH = 180
_CONTROLNET_SCALE = 0.75  # 모델 카드 권장(0.45~0.85, 일반 인형 0.75)
_STRENGTH = 0.75
_STEPS = 30  # 모델 카드 표준 img2img 경로(LCM 미사용)
_GUIDANCE = 7.5
_LORA_SCALE = 0.9  # 모델 카드 character LoRA scale(두 경로 공통)
_BG_MIN_RATIO = 0.40
_N_COLORS = 32  # 출력 팔레트 양자화(MEDIANCUT, dither 없음)

# 모델 카드 LCM fast path — 사진 없는 text2img 경로 가속(bg_mode 와 동일 LCM-LoRA).
_LCM_LORA = "latent-consistency/lcm-lora-sdxl"
_LCM_STEPS = 8  # 모델 카드 LCM 경로
_LCM_GUIDANCE = 1.5  # 모델 카드 LCM 경로
_LCM_SCALE = 1.0  # LCM-LoRA 가중치(bg_mode 와 동일)

_CONTROLNET_MODEL = "diffusers/controlnet-canny-sdxl-1.0"
_BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"


class CharacterMode:
    """SDXL + ControlNet(canny) + character LoRA + rembg 파이프라인 (CUDA 전용)."""

    def __init__(self, *, lora_source: str) -> None:
        dtype = torch.float16
        controlnet = ControlNetModel.from_pretrained(
            _CONTROLNET_MODEL, torch_dtype=dtype, use_safetensors=True, variant="fp16"
        )
        pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
            _BASE_MODEL,
            controlnet=controlnet,
            torch_dtype=dtype,
            use_safetensors=True,
            variant="fp16",
        )
        # character(스타일) + lcm 두 LoRA 를 named adapter 로 올린다. img2img 는
        # character 만, text2img 는 character+lcm 을 generate 마다 set_adapters 로 켠다.
        pipe.load_lora_weights(lora_source, adapter_name="character")
        pipe.load_lora_weights(_LCM_LORA, adapter_name="lcm")
        pipe.to("cuda")
        pipe.enable_attention_slicing()
        self._pipe = pipe
        # 사진 없는 text-only 경로 — base/unet/LoRA 를 공유(from_pipe, VRAM 재사용)하되
        # LCM 스케줄러로 8-step text2img. unet 을 공유하므로 generate 마다 set_adapters
        # 로 활성 어댑터를 전환한다(워커는 단일 요청 직렬 처리라 안전).
        self._txt2img = StableDiffusionXLPipeline.from_pipe(pipe)
        self._txt2img.scheduler = LCMScheduler.from_config(
            self._txt2img.scheduler.config
        )

    def _remove_background(self, image: Image.Image) -> Image.Image:
        removed = remove(image.convert("RGBA"))
        white_bg = Image.new("RGBA", removed.size, (255, 255, 255, 255))
        white_bg.paste(removed, mask=removed.split()[3])
        return white_bg.convert("RGB")

    def _bg_ok(self, image: Image.Image) -> bool:
        arr = np.array(image.convert("RGB"))
        mask = (arr[:, :, 0] >= 245) & (arr[:, :, 1] >= 245) & (arr[:, :, 2] >= 245)
        return float(mask.sum()) / mask.size >= _BG_MIN_RATIO

    def _canny(self, image: Image.Image) -> Image.Image:
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, _CANNY_LOW, _CANNY_HIGH)
        return Image.fromarray(np.stack([edges] * 3, axis=-1))

    def _quantize(self, image: Image.Image) -> Image.Image:
        """제한된 팔레트로 양자화해 진짜 도트 느낌을 만든다 (MEDIANCUT, dither 없음)."""
        quantized = image.quantize(
            colors=_N_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
        return quantized.convert("RGB")

    def _to_bytes(self, image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def generate(
        self, *, source_image_bytes: bytes | None = None, prompt: str | None = None
    ) -> bytes:
        """사진이 있으면 표준 img2img(ControlNet), 없으면 LCM text2img(외형 묘사 prompt)."""
        if source_image_bytes is not None:
            # 사진 있을 때 — 모델 카드 표준 30-step img2img + ControlNet (LCM 미사용,
            # character LoRA 만 활성, 사진 윤곽이 형태를 결정하므로 prompt 미사용)
            self._pipe.set_adapters(["character"], adapter_weights=[_LORA_SCALE])
            original = (
                Image.open(io.BytesIO(source_image_bytes)).convert("RGB").resize(_SIZE)
            )
            bg_removed = self._remove_background(original)
            src = bg_removed if self._bg_ok(bg_removed) else original
            canny_img = self._canny(src)
            result = self._pipe(
                prompt=_PROMPT,
                negative_prompt=_NEGATIVE_PROMPT,
                image=src,
                control_image=canny_img,
                num_inference_steps=_STEPS,
                guidance_scale=_GUIDANCE,
                controlnet_conditioning_scale=_CONTROLNET_SCALE,
                strength=_STRENGTH,
            ).images[0]
        else:
            # 사진 없을 때 — 모델 카드 LCM 8-step text2img (character+lcm 활성),
            # 고정 스타일 가드에 외형 묘사를 덧붙인다.
            self._txt2img.set_adapters(
                ["character", "lcm"], adapter_weights=[_LORA_SCALE, _LCM_SCALE]
            )
            full_prompt = (
                f"{_PROMPT}, {prompt.strip()}" if prompt and prompt.strip() else _PROMPT
            )
            result = self._txt2img(
                prompt=full_prompt,
                negative_prompt=_NEGATIVE_PROMPT,
                num_inference_steps=_LCM_STEPS,
                guidance_scale=_LCM_GUIDANCE,
                width=_SIZE[0],
                height=_SIZE[1],
            ).images[0]

        return self._to_bytes(self._quantize(result))
