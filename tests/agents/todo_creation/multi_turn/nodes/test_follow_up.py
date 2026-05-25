from __future__ import annotations

import pytest

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.multi_turn.nodes.follow_up import follow_up_node
from agents.todo_creation.schemas import ChatMessage, ParsedGoal, PlannerJudgment


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_follow_up_returns_question(base_input, fake_mt_llm):
    fake_mt_llm.follow_up_responses = ["하루에 몇 시간 정도 가능하실까요?"]
    state = {
        "input": base_input,
        "history": [ChatMessage(role="user", content=base_input.message)],
        "judgment": PlannerJudgment(is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal()),
    }
    out = await follow_up_node(state, _config(fake_mt_llm))
    assert out["follow_up_question"] == "하루에 몇 시간 정도 가능하실까요?"


@pytest.mark.asyncio
async def test_follow_up_raises_on_llm_failure(base_input, fake_mt_llm):
    fake_mt_llm.fail_times_follow_up = 1
    state = {
        "input": base_input, "history": [],
        "judgment": PlannerJudgment(is_sufficient=False, missing_aspects=["x"], parsed_goal=ParsedGoal()),
    }
    with pytest.raises(LLMFailedError):
        await follow_up_node(state, _config(fake_mt_llm))
