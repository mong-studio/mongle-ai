"""캐릭터 픽셀아트 생성 모드 (SDXL + ControlNet canny img2img + LoRA).

adapter="character" 요청을 처리한다. 사진(또는 기본 실루엣)을 받아 mongle 캐릭터
스프라이트로 변환한다. LoRA 는 `Hadimeeee/mongle-character-lora` 기준:
  - 트리거: monglestyle
  - 30 step, guidance 7.5, ControlNet conditioning 0.75, LoRA scale 0.9
사람이 읽는 프롬프트 카탈로그: adapters/character_creation/prompts/image_gen_v1.md
"""
from __future__ import annotations

import io

import cv2
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
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
_STEPS = 30  # 모델 카드 표준(LCM 미사용 경로)
_GUIDANCE = 7.5
_LORA_SCALE = 0.9  # 모델 카드 cross-attention scale
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

    def _make_default_source(self) -> Image.Image:
        """사진 없을 때 쓸 기본 실루엣 — 흰 배경에 회색 원."""
        img = Image.new("RGB", _SIZE, (255, 255, 255))
        arr = np.array(img)
        cx, cy, r = _SIZE[0] // 2, _SIZE[1] // 2, _SIZE[0] // 3
        cv2.circle(arr, (cx, cy), r, (180, 180, 180), -1)
        return Image.fromarray(arr)

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
        """character 모드는 사진(또는 기본 실루엣) 기반 — prompt 인자는 사용하지 않는다."""
        lora_kwargs = {"cross_attention_kwargs": {"scale": _LORA_SCALE}}
        if source_image_bytes is not None:
            # 사진 있을 때 — img2img + ControlNet
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
            # 사진 없을 때 — 동그란 실루엣을 기본 소스로 사용
            src = self._make_default_source()
            canny_img = self._canny(src)
            result = self._pipe(
                prompt=_PROMPT,
                negative_prompt=_NEGATIVE_PROMPT,
                image=src,
                control_image=canny_img,
                num_inference_steps=_STEPS,
                guidance_scale=_GUIDANCE,
                controlnet_conditioning_scale=0.4,
                strength=0.99,
                **lora_kwargs,
            ).images[0]

        return self._to_bytes(self._quantize(result))
