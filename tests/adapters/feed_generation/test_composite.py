from __future__ import annotations

import io

from PIL import Image

from adapters.feed_generation.composite import composite_sprite_on_background


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _background(size: int = 256, color=(200, 120, 60)) -> bytes:
    return _png(Image.new("RGBA", (size, size), (*color, 255)))


def _sprite(w: int = 80, h: int = 120, color=(20, 80, 200)) -> bytes:
    # 가운데에 단색 사각형이 있는 투명 스프라이트.
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for yy in range(h):
        for xx in range(w):
            img.putpixel((xx, yy), (*color, 255))
    return _png(img)


def test_result_is_valid_png_and_matches_background_size() -> None:
    out = composite_sprite_on_background(_background(256), _sprite(), with_shadow=False)
    result = Image.open(io.BytesIO(out))
    assert result.size == (256, 256)
    assert result.format == "PNG"


def test_sprite_is_placed_centered_bottom() -> None:
    bg_color = (200, 120, 60)
    sprite_color = (20, 80, 200)
    out = composite_sprite_on_background(
        _background(256, bg_color),
        _sprite(80, 120, sprite_color),
        sprite_height_ratio=0.45,
        bottom_margin_ratio=0.08,
        with_shadow=False,
    )
    result = Image.open(io.BytesIO(out)).convert("RGB")

    # 스프라이트 높이 = 256*0.45 ≈ 115, 하단 여백 = 256*0.08 ≈ 20.
    # 캐릭터가 놓인 영역(중앙·하단)은 스프라이트 색이어야 한다.
    cx = 256 // 2
    sprite_y = 256 - int(256 * 0.45) - int(256 * 0.08) + 5  # 스프라이트 상단 살짝 아래
    assert result.getpixel((cx, sprite_y)) == sprite_color

    # 좌상단(스프라이트가 없는 곳)은 배경색 그대로여야 한다.
    assert result.getpixel((5, 5)) == bg_color


def test_with_shadow_does_not_crash_and_keeps_size() -> None:
    out = composite_sprite_on_background(_background(256), _sprite(), with_shadow=True)
    result = Image.open(io.BytesIO(out))
    assert result.size == (256, 256)
