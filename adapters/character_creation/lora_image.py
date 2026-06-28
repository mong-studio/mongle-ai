from __future__ import annotations

import io

import cv2
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
from PIL import Image
from rembg import remove

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.schemas import ImageGenerationResult, LLMPersonaResult

# 런타임 SSOT. 사람이 읽는 카탈로그: adapters/character_creation/prompts/image_gen_v1.md (변경 시 동기화).
# 로컬 개발용 provider. 운영 RunPod 구현은 runpod_workers/image_gen/에 분리되어 있다.
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
_STRENGTH = 0.6
_STEPS = 30
_GUIDANCE = 7.5
_BG_MIN_RATIO = 0.40


class LoRAImageGenerator:
    """ImageGeneratorPort 구현체 — LoRA + ControlNet + rembg 파이프라인."""

    def __init__(self, *, lora_dir: str) -> None:
        device = (
            "mps" if torch.backends.mps.is_available()
            else "cuda" if torch.cuda.is_available()
            else "cpu"
        )
        # MPS는 float16 불안정 → bfloat16, CPU는 float32
        if device == "mps":
            dtype = torch.bfloat16
        elif device == "cuda":
            dtype = torch.float16
        else:
            dtype = torch.float32

        controlnet = ControlNetModel.from_pretrained(
            "diffusers/controlnet-canny-sdxl-1.0",
            torch_dtype=dtype,
            use_safetensors=True,
        )
        pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            controlnet=controlnet,
            torch_dtype=dtype,
            use_safetensors=True,
        )
        pipe.load_lora_weights(lora_dir)
        pipe.to(device)
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

    def _to_bytes(self, image: Image.Image) -> bytes:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        fallback_persona: str | None,
        source_image_bytes: bytes | None = None,
    ) -> ImageGenerationResult:
        try:
            if source_image_bytes is not None:
                # 사진 있을 때 — img2img + ControlNet
                original = Image.open(io.BytesIO(source_image_bytes)).convert("RGB").resize(_SIZE)
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

            return ImageGenerationResult(image_bytes=self._to_bytes(result))

        except ImageGenerationFailedError:
            raise
        except Exception as err:
            raise ImageGenerationFailedError(f"LoRA image generation failed: {err}") from err
