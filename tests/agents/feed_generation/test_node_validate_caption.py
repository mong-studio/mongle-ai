import pytest
from agents.feed_generation.exceptions import CaptionValidationError
from agents.feed_generation.nodes.validate_caption import validate_caption_node, check_caption
from tests.agents.feed_generation.fakes import make_state


async def test_validate_caption_valid_routes_to_builder():
    state = make_state(raw_caption="오늘 방 청소 완료! 기분 좋다 ✨")
    cmd = await validate_caption_node(state, {})
    assert cmd.goto == "builder"


async def test_validate_caption_rejects_over_140_chars():
    with pytest.raises(CaptionValidationError) as exc_info:
        check_caption("가" * 141)
    assert exc_info.value.code == "caption_too_long"


async def test_validate_caption_accepts_exactly_140_chars():
    check_caption("가" * 140)  # should not raise


async def test_validate_caption_rejects_no_korean():
    with pytest.raises(CaptionValidationError) as exc_info:
        check_caption("Cleaned my room! Great day!")
    assert exc_info.value.code == "no_korean"


async def test_validate_caption_accepts_mixed_korean_and_emoji():
    check_caption("청소 완료! ✨🎉")  # should not raise
