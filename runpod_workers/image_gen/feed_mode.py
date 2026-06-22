"""피드 이미지 생성 모드 — img2img 캐릭터 + 배경 생성 + 합성 + 블렌딩.

Hadimee `mongle-bg-lora/feed_pipeline/pipeline.py` 5단계를 워커 feed 모드로 이식한다.
한 SDXL 에 character+bg+lcm LoRA 를 named adapter 로 올리고 from_pipe 로 i2i·inpaint
파이프를 공유한다(SDXL 1벌). torch/diffusers/rembg/PIL 은 함수 내부에서 지연 import
한다 — 순수함수(composite/_appearance_to_str) 테스트가 GPU 의존성 없이 동작하도록.

STEP 1 img2img(str=0.75): 기준 이미지 → 픽셀아트 캐릭터(포즈 변환)
STEP 2 rembg: 픽셀아트 캐릭터 누끼
STEP 3 text2img: 퀘스트 배경 장면 생성(랜덤 시드)
STEP 4 캐릭터를 배경 위에 합성(그림자 + rim 마스크)
STEP 5 inpaint 블렌딩(경계 봉합, str=0.35)
"""
from __future__ import annotations

import gc
import io
import os

import numpy as np

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

_LCM_LORA = "latent-consistency/lcm-lora-sdxl"
_LCM_LORA_REVISION = "a18548dd4956b174ec5b0d78d340c8dae0a129cd"
_BASE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
_BASE_MODEL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"

NEGATIVE = (
    "realistic, 3d render, photograph, blurry, dark, gloomy, "
    "watercolor, sketch, painterly, smooth illustration, "
    "modern city, urban, scary, violence, text, watermark, "
    "multiple characters, tiling, repeated, "
    "human, person, girl, boy, man, woman, "
    "human face, realistic face, humanoid, skin, flesh"
)

NEGATIVE_BG = (
    NEGATIVE + ", character, animal, figure, creature, stuffed toy, "
    "npc, villager, sprite, sitting figure, standing figure, "
    "person sitting, person standing, foreground character"
)

BG_STYLE = (
    "32-bit pixel art style, side view, 2D scene, "
    "pastel colors high brightness warm cheerful palette, "
    "soft warm cozy lighting, "
    "detailed pixel art background illustration, "
    "empty scene with no characters"
)


def _appearance_to_str(appearance: dict) -> str:
    if not appearance:
        return ""
    parts = []
    for key in ("body_color", "animal_type", "body_shape", "eye_style"):
        val = appearance.get(key, "")
        if val:
            parts.append(val)
    accessories = appearance.get("accessories", [])
    if isinstance(accessories, list) and accessories:
        parts.append(", ".join(accessories))
    user_desc = appearance.get("user_description", "")
    if user_desc:
        parts.append(user_desc)
    return ", ".join(parts)


def generate_character(pipe_i2i, nobg_pil, quest_action: str,
                       appearance: dict = None,
                       char_scale: float = 1.0, bg_scale: float = 0.3,
                       strength: float = 0.75, steps: int = 8, seed: int = 42):
    """STEP 1: img2img -> 픽셀아트 캐릭터 (흰 배경)"""
    import torch
    from PIL import Image

    SIZE = (1024, 1024)
    img = nobg_pil.convert("RGBA").resize(SIZE, Image.LANCZOS)
    bg = Image.new("RGB", SIZE, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])

    pipe_i2i.set_adapters(
        ["character", "bg", "lcm"],
        adapter_weights=[char_scale, bg_scale, 1.0],
    )

    appearance_str = _appearance_to_str(appearance)
    char_desc = f"{appearance_str}, " if appearance_str else ""

    prompt = (
        f"monglestyle, {quest_action}, "
        f"{char_desc}"
        f"cute chibi stuffed animal plush toy character in action, full body pose, non-human animal, "
        f"pure white background, 32-bit pixel art, soft pixel shading"
    )

    print(f"  [STEP 1] 캐릭터 생성  strength={strength}")
    return pipe_i2i(
        prompt=prompt,
        image=bg,
        strength=strength,
        negative_prompt=NEGATIVE,
        num_inference_steps=steps,
        guidance_scale=1.5,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]


def remove_bg(char_rgb_pil):
    """STEP 2: rembg 누끼 -> RGBA"""
    from PIL import Image
    from rembg import remove as rembg_remove

    print("  [STEP 2] rembg 누끼...")
    buf = io.BytesIO()
    char_rgb_pil.save(buf, format="PNG")
    result = Image.open(io.BytesIO(rembg_remove(buf.getvalue()))).convert("RGBA")
    print("  누끼 완료")
    return result


def generate_background(pipe_t2i, quest_scene: str,
                        bg_scale: float = 1.0,
                        steps: int = 8, seed: int = None):
    """STEP 3: text2img -> 퀘스트 배경 장면 (seed=None이면 완전 랜덤)"""
    import torch

    pipe_t2i.set_adapters(
        ["character", "bg", "lcm"],
        adapter_weights=[0.1, bg_scale, 1.0],
    )

    prompt = (
        f"monglestyle, {quest_scene} scene environment, {BG_STYLE}, "
        f"wide open background, no foreground character"
    )

    gen = torch.Generator("cuda")
    if seed is not None:
        gen.manual_seed(seed)

    print(f"  [STEP 3] 배경 생성  scene={quest_scene[:50]}")
    return pipe_t2i(
        prompt=prompt,
        negative_prompt=NEGATIVE_BG,
        num_inference_steps=steps,
        guidance_scale=1.5,
        height=1024,
        width=1024,
        generator=gen,
    ).images[0]


def composite(bg_pil, char_nobg_pil, ground_ratio: float = 0.85,
              min_char_ratio: float = 0.30, max_char_ratio: float = 0.48):
    """STEP 4: 임시 합성 + 마스크 반환"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    bw, bh = bg_pil.size

    char_orig = char_nobg_pil.convert("RGBA")
    alpha_orig = np.array(char_orig.split()[3])
    rows_o = np.any(alpha_orig > 10, axis=1)
    cols_o = np.any(alpha_orig > 10, axis=0)
    rmin_o, rmax_o = np.where(rows_o)[0][[0, -1]]
    cmin_o, cmax_o = np.where(cols_o)[0][[0, -1]]
    content_h = rmax_o - rmin_o
    content_w = cmax_o - cmin_o

    min_h = int(bh * min_char_ratio)
    max_h = int(bh * max_char_ratio)
    if content_h > max_h:
        scale = max_h / content_h
    elif content_h < min_h:
        scale = min_h / content_h
    else:
        scale = 1.0

    new_w = int(char_orig.size[0] * scale)
    new_h = int(char_orig.size[1] * scale)
    char = char_orig.resize((new_w, new_h), Image.LANCZOS)

    alpha = np.array(char.split()[3])
    rows = np.any(alpha > 10, axis=1)
    cols = np.any(alpha > 10, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    char_h = rmax - rmin
    char_w = cmax - cmin

    target_bottom = int(bh * ground_ratio)
    dy = target_bottom - rmax
    dx = (bw - (cmin + cmax)) // 2

    foot_cx = bw // 2
    foot_cy = target_bottom + int(char_h * 0.04)
    sw, sh = int(char_w * 0.45), int(char_h * 0.06)
    shadow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [foot_cx - sw, foot_cy - sh, foot_cx + sw, foot_cy + sh],
        fill=(0, 0, 0, 60),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))

    char_shifted = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    char_shifted.paste(char, (dx, dy))

    result = bg_pil.copy().convert("RGBA")
    result = Image.alpha_composite(result, shadow)
    result = Image.alpha_composite(result, char_shifted)

    shifted_alpha = np.array(char_shifted.split()[3])
    mask_base = Image.fromarray(np.where(shifted_alpha > 10, np.uint8(255), np.uint8(0)))
    mask_dilated = mask_base.filter(ImageFilter.MaxFilter(size=33))
    mask_eroded = mask_base.filter(ImageFilter.MinFilter(size=21))
    rim_mask = ImageChops.subtract(mask_dilated, mask_eroded)
    rim_mask = rim_mask.filter(ImageFilter.GaussianBlur(radius=6))
    mask_rgb = rim_mask.convert("RGB")

    return result.convert("RGB"), mask_rgb


def inpaint_blend(pipe_inpaint, composite_rgb, mask_rgb, quest_action: str,
                  char_scale: float = 0.8, bg_scale: float = 0.8,
                  strength: float = 0.35, steps: int = 8, seed: int = 42):
    """STEP 5: 캐릭터 경계 인페인팅 블렌딩"""
    import torch

    pipe_inpaint.set_adapters(
        ["character", "bg", "lcm"],
        adapter_weights=[char_scale, bg_scale, 1.0],
    )

    prompt = (
        f"monglestyle, {quest_action}, "
        f"cute chibi stuffed animal plush toy character in action, "
        f"32-bit pixel art, {BG_STYLE}"
    )

    print(f"  [STEP 5] 인페인팅 블렌딩  strength={strength}")
    return pipe_inpaint(
        prompt=prompt,
        image=composite_rgb,
        mask_image=mask_rgb,
        strength=strength,
        negative_prompt=NEGATIVE,
        num_inference_steps=steps,
        guidance_scale=1.5,
        height=1024,
        width=1024,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]


def img2img_blend(pipe_i2i, composite_rgb, quest_action: str,
                  char_scale: float = 0.8, bg_scale: float = 0.8,
                  strength: float = 0.40, steps: int = 8, seed: int = 42):
    """STEP 5 대안: 전체 이미지 img2img 블렌딩"""
    import torch

    pipe_i2i.set_adapters(
        ["character", "bg", "lcm"],
        adapter_weights=[char_scale, bg_scale, 1.0],
    )

    prompt = (
        f"monglestyle, {quest_action}, "
        f"cute chibi stuffed animal plush toy character in action, "
        f"32-bit pixel art, {BG_STYLE}"
    )

    print(f"  [STEP 5] 전체 img2img 블렌딩  strength={strength}")
    return pipe_i2i(
        prompt=prompt,
        image=composite_rgb,
        strength=strength,
        negative_prompt=NEGATIVE,
        num_inference_steps=steps,
        guidance_scale=1.5,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]


def _composite_bytes(bg_bytes: bytes, sprite_bytes: bytes):
    """테스트/유틸용 bytes 래퍼 — composite 를 PNG bytes in/out 으로 노출."""
    from PIL import Image

    bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
    sprite = Image.open(io.BytesIO(sprite_bytes)).convert("RGBA")
    rgb, mask = composite(bg, sprite)
    rb, mb = io.BytesIO(), io.BytesIO()
    rgb.save(rb, "PNG")
    mask.save(mb, "PNG")
    return rb.getvalue(), mb.getvalue()


class FeedMode:
    """SDXL + char/bg/lcm LoRA + i2i/inpaint(from_pipe). run.py 기본값 bake.

    blend mode 토글: _BLEND_MODE = "inpaint" (기본) | "img2img".
    """

    _BLEND_MODE = "inpaint"
    _STRENGTH = 0.75
    _INPAINT_STR = 0.35
    _STEPS = 8
    _CHAR_SCALE = 1.0
    _CHAR_SEED = 42

    def __init__(self, *, lora_character_source: str, lora_bg_source: str) -> None:
        import torch
        from diffusers import (LCMScheduler, StableDiffusionXLImg2ImgPipeline,
                               StableDiffusionXLInpaintPipeline,
                               StableDiffusionXLPipeline)

        print("SDXL(feed) 로드 중...")
        t2i = StableDiffusionXLPipeline.from_pretrained(
            _BASE_MODEL,
            revision=_BASE_MODEL_REVISION,
            torch_dtype=torch.float16,
            use_safetensors=True,
            variant="fp16",
        ).to("cuda")
        t2i.load_lora_weights(lora_character_source, adapter_name="character")
        t2i.load_lora_weights(lora_bg_source, adapter_name="bg")
        t2i.load_lora_weights(_LCM_LORA, adapter_name="lcm", revision=_LCM_LORA_REVISION)
        t2i.scheduler = LCMScheduler.from_config(t2i.scheduler.config)
        t2i.enable_attention_slicing()

        self._t2i = t2i
        self._i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(t2i)
        self._inpaint = StableDiffusionXLInpaintPipeline.from_pipe(t2i)
        print("feed 로드 완료!")

    def generate(self, *, source_image_bytes: bytes | None = None,
                 prompt: str | None = None, scene_prompt: str | None = None) -> bytes:
        from PIL import Image

        if source_image_bytes is None:
            raise ValueError("[ERROR] feed 모드는 source_image_bytes(캐릭터 기준 이미지)가 필요합니다")
        if not (prompt and prompt.strip()):
            raise ValueError("[ERROR] feed 모드는 prompt(캐릭터 포즈)가 필요합니다")

        scene = (scene_prompt or prompt).strip()
        char_src = Image.open(io.BytesIO(source_image_bytes)).convert("RGBA")

        char = generate_character(
            self._i2i, char_src, prompt,
            char_scale=self._CHAR_SCALE, bg_scale=0.3,
            strength=self._STRENGTH, steps=self._STEPS, seed=self._CHAR_SEED,
        )
        char_nobg = remove_bg(char)
        bg = generate_background(self._t2i, scene, steps=self._STEPS, seed=None)
        comp_rgb, mask_rgb = composite(bg, char_nobg)

        if self._BLEND_MODE == "img2img":
            final = img2img_blend(self._i2i, comp_rgb, prompt, steps=self._STEPS)
        else:
            final = inpaint_blend(
                self._inpaint, comp_rgb, mask_rgb, prompt,
                strength=self._INPAINT_STR, steps=self._STEPS,
            )

        gc.collect()
        buf = io.BytesIO()
        final.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
