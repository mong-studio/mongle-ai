from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.schemas import SingleTurnInput
from agents.todo_creation.single_turn.nodes.validate import (
    check,
    validate_node,
)


def _input(prompt: str = "오늘 코테", user_id: str = "u1") -> SingleTurnInput:
    return SingleTurnInput(user_id=user_id, prompt=prompt, today=date(2026, 5, 24))


def test_check_passes_for_normal_input() -> None:
    check(_input())  # no exception


def test_check_rejects_201_chars() -> None:
    long = "가" * 201
    # SingleTurnInput pydantic blocks construction first; build via model_construct
    inp = SingleTurnInput.model_construct(
        user_id="u1", prompt=long, today=date(2026, 5, 24)
    )
    with pytest.raises(ValidationError) as ei:
        check(inp)
    assert ei.value.code == "A1"


def test_check_rejects_whitespace_only_prompt() -> None:
    inp = SingleTurnInput.model_construct(
        user_id="u1", prompt="   ", today=date(2026, 5, 24)
    )
    with pytest.raises(ValidationError) as ei:
        check(inp)
    assert ei.value.code == "A2"


def test_check_rejects_empty_user_id() -> None:
    inp = SingleTurnInput.model_construct(
        user_id="", prompt="hi", today=date(2026, 5, 24)
    )
    with pytest.raises(ValidationError) as ei:
        check(inp)
    assert ei.value.code == "A3"


async def test_validate_node_returns_empty_diff_on_success() -> None:
    state = {"input": _input(), "now": None}
    diff = await validate_node(state, {"configurable": {}})
    assert diff == {}


async def test_validate_node_raises_on_invalid() -> None:
    bad = SingleTurnInput.model_construct(
        user_id="u1", prompt="", today=date(2026, 5, 24)
    )
    state = {"input": bad, "now": None}
    with pytest.raises(ValidationError):
        await validate_node(state, {"configurable": {}})
