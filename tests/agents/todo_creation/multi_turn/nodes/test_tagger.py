from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.tagger import tagger_node
from agents.todo_creation.schemas import Day, ParsedGoal, PlanDraft, TaggedPlan, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


@pytest.mark.asyncio
async def test_tagger_returns_tagged_plan(base_input, fake_mt_llm):
    fake_mt_llm.tag_responses = [TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부", tags=["학습", "정처기"])])],
    )]
    state = {
        "input": base_input,
        "plan_draft": PlanDraft(summary_text="요약", days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])]),
        "parsed_goal": ParsedGoal(goal_type="정처기"),
    }
    out = await tagger_node(state, _config(fake_mt_llm))
    assert out["current_plan"].days[0].tasks[0].tags == ["학습", "정처기"]
