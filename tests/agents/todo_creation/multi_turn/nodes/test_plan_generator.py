from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.plan_generator import (
    C3_LIMIT, plan_generator_node, truncate_at_sentence,
)
from agents.todo_creation.schemas import Day, ParsedGoal, PlanDraft, Task


class _Ports:
    def __init__(self, llm):
        self.llm = llm


def _config(fake_mt_llm):
    return {"configurable": {"ports": _Ports(llm=fake_mt_llm)}}


def _draft(summary: str) -> PlanDraft:
    return PlanDraft(summary_text=summary, days=[Day(date=date(2026, 5, 26), tasks=[Task(title="공부")])])


@pytest.mark.asyncio
async def test_plan_generator_happy_path(base_input, fake_mt_llm):
    fake_mt_llm.plan_responses = [_draft("짧은 요약.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert out["plan_draft"].summary_text == "짧은 요약."
    assert fake_mt_llm.last_plan_edit_instructions == [None]


@pytest.mark.asyncio
async def test_plan_generator_uses_edit_instructions(base_input, fake_mt_llm):
    fake_mt_llm.plan_responses = [_draft("수정된 요약.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기"), "edit_instructions": "마지막 날을 가볍게"}
    await plan_generator_node(state, _config(fake_mt_llm))
    assert fake_mt_llm.last_plan_edit_instructions == ["마지막 날을 가볍게"]


@pytest.mark.asyncio
async def test_plan_generator_c3_regenerates_once(base_input, fake_mt_llm):
    long_summary = "가" * (C3_LIMIT + 100)
    fake_mt_llm.plan_responses = [_draft(long_summary), _draft("이번엔 짧음.")]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert out["plan_draft"].summary_text == "이번엔 짧음."
    assert fake_mt_llm.calls["generate_plan"] == 2


@pytest.mark.asyncio
async def test_plan_generator_c3_truncates_after_retry(base_input, fake_mt_llm):
    too_long = "첫 문장입니다. 두 번째 문장입니다. " + ("가" * (C3_LIMIT + 100))
    fake_mt_llm.plan_responses = [_draft(too_long), _draft(too_long)]
    state = {"input": base_input, "parsed_goal": ParsedGoal(goal_type="정처기")}
    out = await plan_generator_node(state, _config(fake_mt_llm))
    assert len(out["plan_draft"].summary_text) <= C3_LIMIT
    assert out["plan_draft"].summary_text.endswith(".")


def test_truncate_at_sentence_uses_last_period():
    text = "첫 문장. 두 번째 문장. 세 번째 문장입니다."
    out = truncate_at_sentence(text, limit=20)
    assert out.endswith(".") and len(out) <= 20


def test_truncate_at_sentence_hard_cut_when_no_period():
    text = "마침표가 전혀 없는 매우 긴 문장입니다 마침표 없음"
    out = truncate_at_sentence(text, limit=10)
    assert len(out) == 10
