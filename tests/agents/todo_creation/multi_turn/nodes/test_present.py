from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from agents.todo_creation.multi_turn.nodes.present import present_node
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import (
    ChatMessage, CommitResult, Day, ParsedGoal, TaggedPlan, Task, TurnResult,
)


@dataclass
class _Ports:
    session_store: InMemorySessionStore


def _config(ports, now):
    return {"configurable": {"ports": ports, "now": now}}


@pytest.mark.asyncio
async def test_present_question_saves_session_gathering(base_input, now, session_store):
    state = {
        "input": base_input, "now": now, "phase": "gathering",
        "history": [ChatMessage(role="user", content=base_input.message)],
        "parsed_goal": ParsedGoal(goal_type="정처기"),
        "current_plan": None,
        "follow_up_question": "하루 시간은?",
    }
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "question"
    assert out["result"].question == "하루 시간은?"

    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "gathering"
    assert saved.history[-1].role == "assistant"


@pytest.mark.asyncio
async def test_present_plan_saves_session_reviewing(base_input, now, session_store, today):
    plan = TaggedPlan(
        summary_text="요약",
        days=[Day(date=today, tasks=[Task(title="공부", tags=["학습"])])],
    )
    state = {
        "input": base_input, "now": now, "phase": "gathering",
        "history": [ChatMessage(role="user", content=base_input.message)],
        "parsed_goal": ParsedGoal(),
        "current_plan": plan,
    }
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "plan"

    saved = await session_store.load(session_id=base_input.session_id)
    assert saved.phase == "reviewing"
    assert saved.current_plan is not None


@pytest.mark.asyncio
async def test_present_committed_passthrough(base_input, now, session_store):
    committed = TurnResult(
        kind="committed",
        commit_result=CommitResult(todo_ids=[], event_ids=[], quest_distribution_triggered=False),
    )
    state = {"input": base_input, "now": now, "result": committed}
    out = await present_node(state, _config(_Ports(session_store), now))
    assert out["result"].kind == "committed"
    # commit_invoke 가 이미 session 삭제했으므로 present 는 save 하지 않음
    assert await session_store.load(session_id=base_input.session_id) is None
