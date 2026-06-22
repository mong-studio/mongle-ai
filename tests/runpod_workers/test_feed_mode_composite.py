import io
import sys

from PIL import Image

sys.path.insert(0, "runpod_workers/image_gen")


def _png(mode, color, size=(64, 64)):
    b = io.BytesIO()
    Image.new(mode, size, color).save(b, "PNG")
    return b.getvalue()


def test_composite_returns_rgb_and_mask_same_size():
    from feed_mode import _composite_bytes

    rgb, mask = _composite_bytes(_png("RGB", (0, 0, 255)), _png("RGBA", (255, 0, 0, 200)))
    r = Image.open(io.BytesIO(rgb))
    m = Image.open(io.BytesIO(mask))
    assert r.mode == "RGB" and r.size == (64, 64)
    assert m.size == (64, 64)


def test_appearance_to_str_joins_fields():
    from feed_mode import _appearance_to_str

    s = _appearance_to_str({"body_color": "pink", "accessories": ["hat"]})
    assert "pink" in s and "hat" in s


def test_appearance_to_str_empty():
    from feed_mode import _appearance_to_str

    assert _appearance_to_str({}) == ""
    assert _appearance_to_str(None) == ""
