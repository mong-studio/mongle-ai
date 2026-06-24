from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.todo_creation.planner.nodes.follow_up import follow_up_node


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
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="800점",
    ) as mock_interrupt:
        out = await follow_up_node(_state(), _config(llm))
    assert out["follow_up_question"] == "목표 점수는, 몽글?"
    assert out["history"][-2:] == [
        {"role": "assistant", "content": "목표 점수는, 몽글?"},
        {"role": "user", "content": "800점"},
    ]
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["목표 점수"],
        history=[{"role": "user", "content": "내일 시험"}],
    )
    mock_interrupt.assert_called_once_with("목표 점수는, 몽글?")


@pytest.mark.asyncio
async def test_history_preserves_prior_turns() -> None:
    prior = [
        {"role": "user", "content": "내일 시험"},
        {"role": "assistant", "content": "어떤 시험?"},
        {"role": "user", "content": "영어 말하기 시험"},
    ]
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="목표 점수?")
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="800점",
    ):
        out = await follow_up_node(_state(history=prior), _config(llm))
    # 기존 3 + assistant question + user answer = 5
    assert len(out["history"]) == 5
    assert out["history"][:3] == prior


@pytest.mark.asyncio
async def test_routine_missing_cadence_passes_korean_hint() -> None:
    # routine 의 미충족 슬롯 key(cadence)는 사람용 한국어 힌트로 변환돼 전달된다.
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="주 몇 번 하실래요?")
    state = {
        "history": [{"role": "user", "content": "매주 운동하고 싶어"}],
        "missing_aspects": ["cadence"],
        "parsed_goal": {"plan_kind": "routine"},
    }
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="주 3회",
    ):
        await follow_up_node(state, _config(llm))
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["주 몇 회 또는 어떤 요일인지"],
        history=[{"role": "user", "content": "매주 운동하고 싶어"}],
    )
