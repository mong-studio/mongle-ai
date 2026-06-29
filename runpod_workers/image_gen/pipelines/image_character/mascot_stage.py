"""
Stage A: real photo -> mascot LoRA + ControlNet(Canny) -> mascot concept image.

Self-contained copy of the Stage-A half of mascot_pixel_deploy/pipeline.py.
Stage B (sprite LoRA img2img) is intentionally not included here -- this
pipeline replaces it with character_gen.py (text_character's character LoRA,
txt2img from the appearance card only, no mascot pixels). If
mascot_pixel_deploy/pipeline.py's Stage A logic changes, this copy must be
updated by hand to match.
"""

from __future__ import annotations

import os

import cv2
import numpy as np
import torch
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# 마스코트 LoRA 가중치 파일은 복제하지 않고 mascot_pixel_deploy/models를 그대로 가리킴
# (안전텐서 177MB를 코드와 별개로 중복 보관할 이유가 없음).
MASCOT_LORA = os.environ.get(
    "MASCOT_LORA_SOURCE",
    os.path.join(REPO_ROOT, "models", "mascot_lora"),
)

BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
CONTROLNET_MODEL_ID = "diffusers/controlnet-canny-sdxl-1.0"
MASCOT_CONTROLNET_SCALE = 0.7
MASCOT_DENOISE_STRENGTH = 0.4
MASCOT_LORA_SCALE = 1.0
MASCOT_DETAIL_EDGE_SIGMA = 0.9  # 내부(디테일) 엣지 민감도. 높을수록 약한 경계도 더 잡음 (기존 0.33)
RESOLUTION = 512

MASCOT_PROMPT = (
    "monglemascot, cute soft object mascot concept, front-facing, centered, "
    "cute kawaii face with simple round eyes and a small smile, "
    "bold black outline on eyes nose and mouth, high contrast facial features "
    "clearly defined against the fur/body color"
)
NEGATIVE_PROMPT = (
    "smooth illustration, resized illustration, image filter, blurry pixel art, "
    "soft gradients, anti-aliasing, airbrush shading, painterly texture, "
    "realistic fabric, detailed fur, noisy texture, photo-realistic, 3d render, "
    "random interior lines, crack patterns, fur texture lines, complex background, "
    "decorative background, shadowed background, new markings, extra patterns"
)


def remove_background(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """반환: (흰 배경에 합성한 RGB, 알파 채널 보존한 RGBA)"""
    from rembg import remove as rembg_remove

    rgba = rembg_remove(image.convert("RGBA"))
    white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
    white_bg.paste(rgba, mask=rgba.split()[3])
    return white_bg, rgba


def _auto_canny(gray: np.ndarray, sigma: float = 0.33) -> np.ndarray:
    median = float(np.median(gray))
    low = int(max(0, (1.0 - sigma) * median))
    high = int(min(255, (1.0 + sigma) * median))
    return cv2.Canny(gray, low, high, L2gradient=True)


def make_canny_image_no_clahe(rgb_image: Image.Image, alpha_image: Image.Image | None) -> Image.Image:
    """마스코트 단계 엣지맵: 실루엣(알파마스크) + 디테일(auto-Canny, CLAHE 없음).

    CLAHE를 마스코트 단계에 적용하면 얼굴 없는 사물(베개 등)에서 몸통 천
    질감 잡음을 더 잡아버려 ControlNet 조건이 빡빡해지고 얼굴이 새로 안
    생기는 회귀가 있었음 (mascot_pixel_pipeline 9차 테스트).
    """
    rgb = np.array(rgb_image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)

    if alpha_image is not None:
        mask = (np.array(alpha_image.convert("L")) > 10).astype(np.uint8) * 255
        silhouette_edges = cv2.Canny(mask, 50, 150)
        silhouette_edges = cv2.dilate(silhouette_edges, np.ones((3, 3), np.uint8), iterations=2)
        detail_edges = cv2.bitwise_and(_auto_canny(denoised, sigma=MASCOT_DETAIL_EDGE_SIGMA), mask)
        edges = cv2.bitwise_or(silhouette_edges, detail_edges)
    else:
        edges = _auto_canny(denoised, sigma=MASCOT_DETAIL_EDGE_SIGMA)

    return Image.fromarray(np.stack([edges] * 3, axis=-1))


def load_mascot_pipeline(lora_scale: float = MASCOT_LORA_SCALE):
    from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    print(f"  ControlNet 로드 중... ({CONTROLNET_MODEL_ID})")
    controlnet = ControlNetModel.from_pretrained(CONTROLNET_MODEL_ID, torch_dtype=dtype)
    print(f"  SDXL + ControlNet + mascot LoRA 로드 중... ({MASCOT_LORA})")
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        BASE_MODEL,
        controlnet=controlnet,
        torch_dtype=dtype,
        use_safetensors=True,
    )
    pipe.load_lora_weights(MASCOT_LORA, adapter_name="mascot")
    if hasattr(pipe, "set_adapters"):
        pipe.set_adapters(["mascot"], adapter_weights=[lora_scale])
    pipe.to(device)
    if device == "cuda":
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
        pipe.enable_vae_tiling()  # VAE decode 피크 OOM 방지(타일 디코드)
    return pipe


def unload_mascot_pipeline(pipe) -> None:
    try:
        pipe.to("cpu")
    except Exception:
        pass
    del pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def generate_mascot(
    photo_path: str,
    seed: int = 42,
    pipe=None,
    denoise_strength: float | None = None,
) -> Image.Image:
    """실사 사진 경로 -> 마스코트 컨셉 이미지.

    pipe를 넘기면 그 파이프라인을 재사용하고(배치용, 모델 재로드 없음),
    안 넘기면 새로 로드했다가 끝나고 바로 해제한다. denoise_strength를
    안 넘기면 모듈 기본값(MASCOT_DENOISE_STRENGTH)을 쓴다.
    """
    strength = MASCOT_DENOISE_STRENGTH if denoise_strength is None else denoise_strength
    owned_pipe = pipe is None
    if pipe is None:
        pipe = load_mascot_pipeline()

    try:
        original = Image.open(photo_path).convert("RGB").resize((RESOLUTION, RESOLUTION))
        photo_rgb, photo_rgba = remove_background(original)
        photo_rgb = photo_rgb.resize((RESOLUTION, RESOLUTION))
        photo_rgba = photo_rgba.resize((RESOLUTION, RESOLUTION))
        mascot_canny = make_canny_image_no_clahe(photo_rgb, photo_rgba)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        generator = torch.Generator(device=device).manual_seed(seed)
        mascot = pipe(
            prompt=MASCOT_PROMPT,
            negative_prompt=NEGATIVE_PROMPT,
            image=photo_rgb,
            control_image=mascot_canny,
            num_inference_steps=20,
            guidance_scale=7.5,
            strength=strength,
            controlnet_conditioning_scale=MASCOT_CONTROLNET_SCALE,
            generator=generator,
        ).images[0]
    finally:
        if owned_pipe:
            unload_mascot_pipeline(pipe)

    return mascot
