from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.multi_turn.nodes.planner import planner_node


def _state() -> dict:
    return {
        "history": [{"role": "user", "content": "내일 토익 시험"}],
        "message": "내일 토익 시험",
        "today": date(2026, 5, 25),
    }


def _config(llm: AsyncMock) -> dict:
    return {"configurable": {"ports": type("P", (), {"llm": llm})()}}


@pytest.mark.asyncio
async def test_sufficient_goes_to_plan_generator() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(return_value=(True, [], {"goal_text": "토익 800"}))
    cmd = await planner_node(_state(), _config(llm))
    assert isinstance(cmd, Command)
    assert cmd.goto == "plan_generator"
    assert cmd.update["sufficiency"] is True
    assert cmd.update["parsed_goal"] == {"goal_text": "토익 800"}
    assert cmd.update["missing_aspects"] == []


@pytest.mark.asyncio
async def test_insufficient_goes_to_follow_up() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(return_value=(False, ["목표 점수"], {}))
    cmd = await planner_node(_state(), _config(llm))
    assert cmd.goto == "follow_up"
    assert cmd.update["sufficiency"] is False
    assert cmd.update["missing_aspects"] == ["목표 점수"]
    assert cmd.update["parsed_goal"] is None


@pytest.mark.asyncio
async def test_llm_output_error_propagates() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(side_effect=LLMOutputError("schema violation"))
    with pytest.raises(LLMOutputError):
        await planner_node(_state(), _config(llm))


@pytest.mark.asyncio
async def test_called_with_history_and_message() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(return_value=(True, [], {"goal_text": "g"}))
    state = _state()
    await planner_node(state, _config(llm))
    llm.judge_sufficiency.assert_awaited_once_with(
        history=state["history"],
        message=state["message"],
        today=state["today"],
    )
