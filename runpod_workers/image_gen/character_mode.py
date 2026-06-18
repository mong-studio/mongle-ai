"""캐릭터 픽셀아트 생성 모드 (SDXL + character LoRA, 두 경로).

adapter="character" 요청을 처리한다. mongle-character-lora 모델 카드 표준 경로
(30 step, guidance 7.5, LoRA scale 0.9)와 카드 예시 프롬프트 구조를 따른다.
프롬프트 패턴(카드 Quick Start): `monglestyle, {외형 subject}, {스타일 키워드}`
  - 사진 있을 때: img2img + ControlNet(canny) — 사진 윤곽이 형태, prompt 가 색·디테일
  - 사진 없을 때: text2img — prompt(외형 subject)가 캐릭터를 결정
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

_TRIGGER = "monglestyle"  # mongle-character-lora 트리거(카드: 항상 맨 앞)
# 모델 카드 Quick Start 예시의 스타일 꼬리 — subject(외형) 뒤에 붙는다(verbatim).
_STYLE_SUFFIX = (
    "single stuffed animal toy mascot character, full body, centered, "
    "front view, cute chibi proportions, 32-bit pixel art sprite, "
    "soft pixel shading, clean silhouette, pure white background"
)
# 외형 묘사가 없을 때 쓸 중립 subject.
_FALLBACK_SUBJECT = "cute stuffed animal mascot"
_NEGATIVE_PROMPT = (
    "realistic, 3d render, blurry, smooth, photograph, gradient, shadow, "
    "anti-aliasing, soft edges, painterly, watercolor, sketch, detailed texture"
)

_SIZE = (512, 512)
_CANNY_LOW = 80
_CANNY_HIGH = 180
_CONTROLNET_SCALE = 0.75  # 모델 카드 권장(0.45~0.85, 일반 인형 0.75)
_STRENGTH = 0.75
_STEPS = 30  # 모델 카드 표준(외형 프롬프트 충실도 우선)
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

    def _prompt_for(self, appearance: str | None) -> str:
        """카드 패턴으로 프롬프트 구성: 트리거 → subject(외형) → 스타일 키워드."""
        subject = appearance.strip() if appearance and appearance.strip() else _FALLBACK_SUBJECT
        return f"{_TRIGGER}, {subject}, {_STYLE_SUFFIX}"

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
        """사진이 있으면 img2img(ControlNet), 없으면 text2img. 둘 다 카드 프롬프트 패턴."""
        full_prompt = self._prompt_for(prompt)
        if source_image_bytes is not None:
            # 사진 있을 때 — img2img + ControlNet (사진 윤곽이 형태, prompt 가 색·디테일)
            original = (
                Image.open(io.BytesIO(source_image_bytes)).convert("RGB").resize(_SIZE)
            )
            bg_removed = self._remove_background(original)
            src = bg_removed if self._bg_ok(bg_removed) else original
            canny_img = self._canny(src)
            result = self._pipe(
                prompt=full_prompt,
                negative_prompt=_NEGATIVE_PROMPT,
                image=src,
                control_image=canny_img,
                num_inference_steps=_STEPS,
                guidance_scale=_GUIDANCE,
                controlnet_conditioning_scale=_CONTROLNET_SCALE,
                strength=_STRENGTH,
                cross_attention_kwargs={"scale": _LORA_SCALE},
            ).images[0]
        else:
            # 사진 없을 때 — text2img (prompt 의 외형 subject 가 캐릭터를 결정)
            result = self._txt2img(
                prompt=full_prompt,
                negative_prompt=_NEGATIVE_PROMPT,
                num_inference_steps=_STEPS,
                guidance_scale=_GUIDANCE,
                width=_SIZE[0],
                height=_SIZE[1],
                cross_attention_kwargs={"scale": _LORA_SCALE},
            ).images[0]

        return self._to_bytes(self._quantize(result))
