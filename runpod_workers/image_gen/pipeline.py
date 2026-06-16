"""캐릭터 픽셀아트 이미지 생성 파이프라인 (RunPod Serverless 워커용).

adapters/character_creation/lora_image.py 의 디퓨전 로직 사본 — 변경 시 동기화.
차이점: 동기 실행, CUDA 전용, LoRA 를 로컬 폴더 대신 HF repo 에서 로드.
사람이 읽는 프롬프트 카탈로그: adapters/character_creation/prompts/image_gen_v1.md
"""
from __future__ import annotations

import io
import os

import cv2
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
from PIL import Image
from rembg import remove

_PROMPT = (
    "16x16 pixel art sprite, NES style, cute stuffed animal character, "
    "strictly pixelated, chunky visible pixels, limited flat color palette, "
    "sharp pixel boundaries, no anti-aliasing, no gradients, no shading, "
    "indie RPG game sprite style, warm saturated color palette, "
    "chibi proportions, thick dark outlines, flat 2-tone coloring, "
    "white background, full body, front-facing, "
    "bold black outlines, clean pixel edges"
)
_NEGATIVE_PROMPT = (
    "realistic, 3d render, blurry, smooth, photograph, gradient, shadow, "
    "anti-aliasing, soft edges, painterly, watercolor, sketch, detailed texture"
)

_SIZE = (512, 512)
_CANNY_LOW = 80
_CANNY_HIGH = 180
_CONTROLNET_SCALE = 0.8
_STRENGTH = 0.75
_STEPS = 50
_GUIDANCE = 7.5
_BG_MIN_RATIO = 0.40
_N_COLORS = 32  # 모델 카드 기준 출력 팔레트 양자화(MEDIANCUT, dither 없음)

_CONTROLNET_MODEL = "diffusers/controlnet-canny-sdxl-1.0"
_BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"


class PixelArtPipeline:
    """SDXL + ControlNet(canny) + LoRA + rembg 파이프라인 (CUDA 전용)."""

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

    def generate(self, *, source_image_bytes: bytes | None = None) -> bytes:
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
            ).images[0]

        return self._to_bytes(self._quantize(result))


_pipeline: PixelArtPipeline | None = None


def get_pipeline() -> PixelArtPipeline:
    """워커 프로세스에서 파이프라인을 한 번만 로드(지연)."""
    global _pipeline
    if _pipeline is None:
        lora_source = os.environ.get("LORA_REPO_ID", "").strip()
        if not lora_source:
            raise RuntimeError("LORA_REPO_ID 환경변수가 필요합니다 (HF repo ID)")
        _pipeline = PixelArtPipeline(lora_source=lora_source)
    return _pipeline
