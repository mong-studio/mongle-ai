from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts, run_turn
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, Day, ParsedGoal, PlanDraft, PlannerJudgment,
    SessionState, TaggedPlan, Task,
)


@dataclass
class _Dispatch:
    calls: int = 0
    async def dispatch(self, *, user_id: str) -> None:
        self.calls += 1


def _make_ports(fake_mt_llm, session_store, *, fail_repo=False) -> MultiTurnPorts:
    return MultiTurnPorts(
        llm=fake_mt_llm,
        session_store=session_store,
        commit_ports=CommitPorts(
            repository=MemoryTodoRepository(fail_next=fail_repo),
            quest_counter=MemoryQuestCounter(),
            quest_dispatch=_Dispatch(),
        ),
    )


def _plan_draft(today: date) -> PlanDraft:
    return PlanDraft(summary_text="요약", days=[Day(date=today, tasks=[Task(title="공부")])])


def _tagged_plan(today: date) -> TaggedPlan:
    return TaggedPlan(summary_text="요약", days=[Day(date=today, tasks=[Task(title="공부", tags=["학습"])])])


def _reviewing_state(input_, today, now):
    return SessionState(
        session_id=input_.session_id, user_id=input_.user_id, phase="reviewing",
        history=[ChatMessage(role="user", content="이전")],
        parsed_goal=ParsedGoal(goal_type="정처기"),
        current_plan=_tagged_plan(today),
        created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_turn1_insufficient_returns_question(base_input, now, today, fake_mt_llm, session_store):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"),
    )]
    fake_mt_llm.follow_up_responses = ["하루 학습 시간은?"]

    result = await run_turn(base_input, ports=_make_ports(fake_mt_llm, session_store), now=now)
    assert result.kind == "question"
    assert result.question == "하루 학습 시간은?"
    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "gathering"


@pytest.mark.asyncio
async def test_turn1_sufficient_returns_plan(base_input, now, today, fake_mt_llm, session_store):
    fake_mt_llm.judge_responses = [PlannerJudgment(
        is_sufficient=True, missing_aspects=[],
        parsed_goal=ParsedGoal(goal_type="정처기", daily_capacity="3h"),
    )]
    fake_mt_llm.plan_responses = [_plan_draft(today)]
    fake_mt_llm.tag_responses = [_tagged_plan(today)]

    result = await run_turn(base_input, ports=_make_ports(fake_mt_llm, session_store), now=now)
    assert result.kind == "plan"
    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "reviewing"


@pytest.mark.asyncio
async def test_turn3a_confirm_commits_and_clears_session(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]

    result = await run_turn(
        base_input.model_copy(update={"message": "확정해줘"}),
        ports=_make_ports(fake_mt_llm, session_store),
        now=now,
    )
    assert result.kind == "committed"
    assert await session_store.load(session_id=base_input.session_id) is None


@pytest.mark.asyncio
async def test_turn3b_regenerate_returns_new_plan(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(
        tool_name="regenerate_plan", tool_args={"instructions": "더 가볍게"},
    )]
    fake_mt_llm.plan_responses = [_plan_draft(today)]
    fake_mt_llm.tag_responses = [_tagged_plan(today)]

    result = await run_turn(
        base_input.model_copy(update={"message": "더 가볍게 해줘"}),
        ports=_make_ports(fake_mt_llm, session_store),
        now=now,
    )
    assert result.kind == "plan"
    assert fake_mt_llm.last_plan_edit_instructions == ["더 가볍게"]


@pytest.mark.asyncio
async def test_commit_failure_preserves_session(base_input, now, today, fake_mt_llm, session_store):
    await session_store.save(state=_reviewing_state(base_input, today, now))
    fake_mt_llm.agent_decisions = [AgentDecision(tool_name="confirm", tool_args={})]

    with pytest.raises(Exception):
        await run_turn(
            base_input.model_copy(update={"message": "확정"}),
            ports=_make_ports(fake_mt_llm, session_store, fail_repo=True),
            now=now,
        )
    assert await session_store.load(session_id=base_input.session_id) is not None
