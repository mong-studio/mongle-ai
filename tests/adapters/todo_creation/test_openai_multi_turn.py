from __future__ import annotations

import os
from datetime import date

import pytest

from adapters.todo_creation.openai_multi_turn import OpenAIMultiTurnLLM
from agents.todo_creation.schemas import (
    ChatMessage, Day, ParsedGoal, TaggedPlan, Task,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_OPENAI") != "1",
    reason="RUN_REAL_OPENAI=1 required",
)


@pytest.mark.asyncio
async def test_judge_planner_real_call():
    llm = OpenAIMultiTurnLLM()
    j = await llm.judge_planner(
        history=[ChatMessage(role="user", content="3일 후 정보처리기사 시험")],
        previous_goal=None,
        today=date(2026, 5, 25),
    )
    assert j.parsed_goal.goal_type is not None or j.missing_aspects


@pytest.mark.asyncio
async def test_edit_agent_step_real_call():
    llm = OpenAIMultiTurnLLM()
    plan = TaggedPlan(
        summary_text="3일 학습 플랜",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부", tags=["학습"])])],
    )
    d = await llm.edit_agent_step(
        history=[ChatMessage(role="user", content="이대로 확정")],
        current_plan=plan,
    )
    assert d.tool_name in {"confirm", "regenerate_plan"}
