"""캐릭터 픽셀아트 생성 모드 (SDXL + character LoRA, 두 경로).

adapter="character" 요청을 처리한다. mongle-character-lora 모델 카드 표준 경로(30 step,
guidance 7.5, LoRA scale 0.9)를 쓴다:
  - 사진 있을 때: img2img + ControlNet(canny) — 사진 윤곽이 형태를 결정(prompt 미사용)
  - 사진 없을 때: text2img(외형 묘사 prompt) — 고정 스타일 가드에 appearance 를 덧붙임
공통: 트리거 `monglestyle`.
사람이 읽는 프롬프트 카탈로그: adapters/character_creation/prompts/image_gen_v1.md
"""
from __future__ import annotations

import io

import cv2
import numpy as np
import torch
from diffusers import (
    ControlNetModel,
    StableDiffusionXLControlNetImg2ImgPipeline,
    StableDiffusionXLPipeline,
)
from PIL import Image
from rembg import remove

# mongle-character-lora 트리거(monglestyle)로 시작하는 고정 스타일 가드.
# 사진 있을 때는 ControlNet(윤곽), 없을 때는 prompt(외형 묘사)가 캐릭터를 결정한다.
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
_STEPS = 30  # 모델 카드 표준(LCM 미사용 — 외형 프롬프트 충실도 우선)
_GUIDANCE = 7.5
_LORA_SCALE = 0.9  # 모델 카드 character LoRA cross-attention scale
_BG_MIN_RATIO = 0.40
_N_COLORS = 32  # 출력 팔레트 양자화(MEDIANCUT, dither 없음)

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
        pipe.load_lora_weights(lora_source)
        pipe.to("cuda")
        pipe.enable_attention_slicing()
        self._pipe = pipe
        # 사진 없는 text-only 경로용 text2img — 동일 base/unet/LoRA 를 공유(VRAM 재사용).
        self._txt2img = StableDiffusionXLPipeline.from_pipe(pipe)

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
        """사진이 있으면 img2img(ControlNet), 없으면 prompt(외형 묘사) 기반 text2img."""
        lora_kwargs = {"cross_attention_kwargs": {"scale": _LORA_SCALE}}
        if source_image_bytes is not None:
            # 사진 있을 때 — img2img + ControlNet (prompt 미사용, 사진 윤곽이 형태를 결정)
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
                **lora_kwargs,
            ).images[0]
        else:
            # 사진 없을 때 — 고정 스타일 가드에 외형 묘사를 덧붙여 text2img (30 step)
            full_prompt = (
                f"{_PROMPT}, {prompt.strip()}" if prompt and prompt.strip() else _PROMPT
            )
            result = self._txt2img(
                prompt=full_prompt,
                negative_prompt=_NEGATIVE_PROMPT,
                num_inference_steps=_STEPS,
                guidance_scale=_GUIDANCE,
                width=_SIZE[0],
                height=_SIZE[1],
                **lora_kwargs,
            ).images[0]

        return self._to_bytes(self._quantize(result))
