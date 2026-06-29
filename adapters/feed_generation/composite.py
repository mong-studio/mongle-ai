"""피드 합성: 퀘스트 배경 PNG 위에 원본 캐릭터 스프라이트(투명 PNG)를 얹는다.

피드 캐릭터를 AI 로 다시 그리면 원본과 달라지므로, **원본 스프라이트를 그대로** 배경에
합성해 캐릭터 동일성을 보장한다. PIL 만 쓰는 순수 함수라 GPU·외부 호출 없이 단위 테스트 가능.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter


def _add_foot_shadow(
    canvas: Image.Image, x: int, y: int, w: int, h: int
) -> Image.Image:
    """캐릭터 발밑에 연한 타원 그림자를 깔아 '붕 뜬' 느낌을 줄인다."""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    sw = int(w * 0.7)
    sh = max(4, int(h * 0.12))
    sx = x + (w - sw) // 2
    sy = y + h - sh // 2
    draw.ellipse([sx, sy, sx + sw, sy + sh], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, sh // 3)))
    return Image.alpha_composite(canvas, shadow)


def composite_sprite_on_background(
    background_png: bytes,
    sprite_png: bytes,
    *,
    sprite_height_ratio: float = 0.45,
    bottom_margin_ratio: float = 0.08,
    with_shadow: bool = True,
) -> bytes:
    """배경 위 중앙 하단에 캐릭터 스프라이트를 합성한 PNG bytes 를 반환한다.

    Args:
        background_png: 퀘스트 장면 배경 PNG (워커 생성).
        sprite_png: 원본 캐릭터 스프라이트(투명 배경 PNG).
        sprite_height_ratio: 스프라이트 높이 / 배경 높이 (기본 0.45).
        bottom_margin_ratio: 하단 여백 / 배경 높이 (기본 0.08).
        with_shadow: 발밑 그림자 추가 여부.
    """
    bg = Image.open(io.BytesIO(background_png)).convert("RGBA")
    sprite = Image.open(io.BytesIO(sprite_png)).convert("RGBA")

    # 스프라이트를 배경 높이 기준 비율로 리사이즈(가로세로 비 유지).
    target_h = max(1, int(bg.height * sprite_height_ratio))
    scale = target_h / sprite.height
    target_w = max(1, int(sprite.width * scale))
    sprite = sprite.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 가로 중앙, 하단에서 bottom_margin_ratio 만큼 띄운 위치.
    x = (bg.width - target_w) // 2
    y = max(0, bg.height - target_h - int(bg.height * bottom_margin_ratio))

    canvas = bg.copy()
    if with_shadow:
        canvas = _add_foot_shadow(canvas, x, y, target_w, target_h)
    canvas.alpha_composite(sprite, (x, y))

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
