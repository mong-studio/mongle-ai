from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.multi_turn.nodes.commit_invoke import commit_invoke_node
from agents.todo_creation.multi_turn.session_store import InMemorySessionStore
from agents.todo_creation.schemas import Day, SessionState, TaggedPlan, Task


@dataclass
class _Dispatch:
    calls: int = 0
    async def dispatch(self, *, user_id: str) -> None:
        self.calls += 1


@dataclass
class _MtPorts:
    session_store: InMemorySessionStore
    commit_ports: CommitPorts


def _config(mt_ports, now):
    return {"configurable": {"ports": mt_ports, "now": now}}


def _plan(today: date) -> TaggedPlan:
    return TaggedPlan(
        summary_text="요약",
        days=[
            Day(date=today, tasks=[Task(title="오늘 할일", tags=["todo"])]),
            Day(date=date(2026, 5, 27), tasks=[Task(title="내일 일정", tags=["event"])]),
        ],
    )


@pytest.mark.asyncio
async def test_commit_invoke_runs_commit_and_deletes_session(base_input, today, now, session_store):
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=None, current_plan=_plan(today),
        created_at=now, updated_at=now,
    ))
    commit_ports = CommitPorts(
        repository=MemoryTodoRepository(),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    mt_ports = _MtPorts(session_store=session_store, commit_ports=commit_ports)

    state = {"input": base_input, "current_plan": _plan(today), "now": now}
    out = await commit_invoke_node(state, _config(mt_ports, now))

    assert out["result"].kind == "committed"
    assert await session_store.load(session_id=base_input.session_id) is None


@pytest.mark.asyncio
async def test_commit_invoke_keeps_session_on_failure(base_input, today, now, session_store):
    await session_store.save(state=SessionState(
        session_id=base_input.session_id, user_id=base_input.user_id, phase="reviewing",
        history=[], parsed_goal=None, current_plan=_plan(today),
        created_at=now, updated_at=now,
    ))
    commit_ports = CommitPorts(
        repository=MemoryTodoRepository(fail_next=True),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=_Dispatch(),
    )
    mt_ports = _MtPorts(session_store=session_store, commit_ports=commit_ports)

    state = {"input": base_input, "current_plan": _plan(today), "now": now}
    with pytest.raises(Exception):
        await commit_invoke_node(state, _config(mt_ports, now))

    assert await session_store.load(session_id=base_input.session_id) is not None
