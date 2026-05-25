from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.planner_judge import (
    planner_judge_node, route_after_judge,
)
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, PlannerJudgment


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_judge_returns_insufficient(base_input, fake_mt_llm):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"),
    )]
    state = {"input": base_input, "history": [ChatMessage(role="user", content=base_input.message)], "parsed_goal": None}
    out = await planner_judge_node(state, _config(fake_mt_llm))
    assert out["judgment"].is_sufficient is False
    assert out["parsed_goal"].goal_type == "정처기"
    assert fake_mt_llm.calls["judge_planner"] == 1


@pytest.mark.asyncio
async def test_judge_returns_sufficient(base_input, fake_mt_llm):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=True, missing_aspects=[],
        parsed_goal=ParsedGoal(goal_type="정처기", daily_capacity="3h"),
    )]
    state = {"input": base_input, "history": [], "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await planner_judge_node(state, _config(fake_mt_llm))
    assert out["judgment"].is_sufficient is True
    assert out["parsed_goal"].daily_capacity == "3h"


@pytest.mark.asyncio
async def test_judge_raises_on_llm_failure(base_input, fake_mt_llm):
    fake_mt_llm.fail_times_judge = 1
    state = {"input": base_input, "history": [], "parsed_goal": None}
    with pytest.raises(LLMFailedError):
        await planner_judge_node(state, _config(fake_mt_llm))


def test_route_after_judge():
    yes = PlannerJudgment(is_sufficient=True, missing_aspects=[], parsed_goal=ParsedGoal())
    no = PlannerJudgment(is_sufficient=False, missing_aspects=["x"], parsed_goal=ParsedGoal())
    assert route_after_judge({"judgment": yes}) == "plan_generator"
    assert route_after_judge({"judgment": no}) == "follow_up"
