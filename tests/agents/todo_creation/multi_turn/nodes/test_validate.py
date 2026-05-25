from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.nodes.validate import HANGUL_RATIO_MIN, validate_node


@pytest.mark.asyncio
async def test_validate_passes_normal_korean(base_input):
    assert await validate_node({"input": base_input}, {}) == {}


@pytest.mark.asyncio
async def test_m2_whitespace_only(base_input):
    state = {"input": base_input.model_copy(update={"message": "   "})}
    with pytest.raises(ValidationError) as ei:
        await validate_node(state, {})
    assert ei.value.code == "M2"


@pytest.mark.asyncio
async def test_m3_hangul_ratio_too_low(base_input):
    state = {"input": base_input.model_copy(update={"message": "abcdefghij"})}
    with pytest.raises(ValidationError) as ei:
        await validate_node(state, {})
    assert ei.value.code == "M3"


@pytest.mark.asyncio
async def test_m3_passes_mixed_korean_above_threshold(base_input):
    state = {"input": base_input.model_copy(update={"message": "한국어 a"})}
    assert await validate_node(state, {}) == {}


def test_hangul_ratio_constant():
    assert HANGUL_RATIO_MIN == 0.3
