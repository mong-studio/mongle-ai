from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.exceptions import EditAgentError
from agents.todo_creation.multi_turn.nodes.edit_agent import (
    edit_agent_node, route_after_edit_agent,
)
from agents.todo_creation.schemas import AgentDecision, ChatMessage, Day, TaggedPlan, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


def _plan() -> TaggedPlan:
    return TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])],
    )


@pytest.mark.asyncio
async def test_edit_agent_confirm_tool(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]
    state = {
        "input": base_input,
        "history": [ChatMessage(role="user", content=base_input.message)],
        "current_plan": _plan(),
    }
    out = await edit_agent_node(state, _config(fake_mt_llm))
    assert out["confirmed"] is True


@pytest.mark.asyncio
async def test_edit_agent_regenerate_tool(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(
        tool_name="regenerate_plan", tool_args={"instructions": "마지막 날 가볍게"},
    )]
    state = {"input": base_input, "history": [], "current_plan": _plan()}
    out = await edit_agent_node(state, _config(fake_mt_llm))
    assert out["edit_instructions"] == "마지막 날 가볍게"


@pytest.mark.asyncio
async def test_edit_agent_regenerate_without_instructions_raises(base_input, fake_mt_llm):
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="regenerate_plan", tool_args={})]
    state = {"input": base_input, "history": [], "current_plan": _plan()}
    with pytest.raises(EditAgentError) as ei:
        await edit_agent_node(state, _config(fake_mt_llm))
    assert ei.value.code == "M9"


def test_route_after_edit_agent_confirm():
    assert route_after_edit_agent({"confirmed": True}) == "commit_invoke"


def test_route_after_edit_agent_regenerate():
    assert route_after_edit_agent({"edit_instructions": "x"}) == "plan_generator"
