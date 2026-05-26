from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node


def _state(history: list | None = None) -> dict:
    return {
        "history": history
        if history is not None
        else [{"role": "user", "content": "내일 시험"}],
        "missing_aspects": ["목표 점수"],
    }


def _config(llm: AsyncMock) -> dict:
    return {"configurable": {"ports": type("P", (), {"llm": llm})()}}


@pytest.mark.asyncio
async def test_calls_llm_and_interrupts_with_question() -> None:
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="목표 점수는?")
    with patch(
        "agents.todo_creation.multi_turn.nodes.follow_up.interrupt",
        return_value="800점",
    ) as mock_interrupt:
        out = await follow_up_node(_state(), _config(llm))
    assert out["follow_up_question"] == "목표 점수는?"
    assert out["history"][-2:] == [
        {"role": "assistant", "content": "목표 점수는?"},
        {"role": "user", "content": "800점"},
    ]
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["목표 점수"],
        history=[{"role": "user", "content": "내일 시험"}],
    )
    mock_interrupt.assert_called_once_with("목표 점수는?")


@pytest.mark.asyncio
async def test_history_preserves_prior_turns() -> None:
    prior = [
        {"role": "user", "content": "내일 시험"},
        {"role": "assistant", "content": "어떤 시험?"},
        {"role": "user", "content": "토익"},
    ]
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="목표 점수?")
    with patch(
        "agents.todo_creation.multi_turn.nodes.follow_up.interrupt",
        return_value="800점",
    ):
        out = await follow_up_node(_state(history=prior), _config(llm))
    # 기존 3 + assistant question + user answer = 5
    assert len(out["history"]) == 5
    assert out["history"][:3] == prior
