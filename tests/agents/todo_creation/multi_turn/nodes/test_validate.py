from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.nodes.validate import multi_validate_node


def _state(message: str, history: list | None = None) -> dict:
    return {
        "mode": "multi",
        "user_id": "u1",
        "message": message,
        "today": date(2026, 5, 25),
        "now": datetime(2026, 5, 25, tzinfo=timezone.utc),
        "history": history if history is not None else [],
    }


@pytest.mark.asyncio
async def test_600_ok() -> None:
    out = await multi_validate_node(_state("가" * 600), {})
    assert out["history"][-1] == {"role": "user", "content": "가" * 600}


@pytest.mark.asyncio
async def test_601_rejected() -> None:
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("가" * 601), {})


@pytest.mark.asyncio
async def test_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        await multi_validate_node(_state(""), {})


@pytest.mark.asyncio
async def test_whitespace_rejected() -> None:
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("   "), {})


@pytest.mark.asyncio
async def test_korean_ratio_threshold_ok() -> None:
    # 한글 5 / 영문 5 = 0.5 — 통과
    out = await multi_validate_node(_state("안녕하세요hello"), {})
    assert "history" in out


@pytest.mark.asyncio
async def test_no_korean_rejected() -> None:
    with pytest.raises(ValidationError):
        await multi_validate_node(_state("hello world only english"), {})


@pytest.mark.asyncio
async def test_history_appended_to_prior() -> None:
    prior = [
        {"role": "user", "content": "첫번째"},
        {"role": "assistant", "content": "추가 질문"},
    ]
    out = await multi_validate_node(_state("두번째 메시지", history=prior), {})
    assert len(out["history"]) == 3
    assert out["history"][-1] == {"role": "user", "content": "두번째 메시지"}


@pytest.mark.asyncio
async def test_whitespace_and_digits_excluded_from_ratio() -> None:
    # 공백/숫자 제외하고 한글 5 / 영문 5 = 0.5 — 통과
    out = await multi_validate_node(_state("안녕하세요 hello 123"), {})
    assert "history" in out
