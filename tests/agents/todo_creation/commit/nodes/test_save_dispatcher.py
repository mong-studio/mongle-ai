from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.nodes.save_dispatcher import save_dispatcher_node
from agents.todo_creation.exceptions import SaveFailedError
from agents.todo_creation.schemas import CommitInput, TaskCandidate


def _t(title: str = "할 일", d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title=title, due_date=d)


def _state(
    repo: MemoryTodoRepository,
    *,
    todos: list[TaskCandidate] | None = None,
    events: list[TaskCandidate] | None = None,
    key=None,
) -> tuple[dict, dict]:
    todos = todos if todos is not None else [_t()]
    events = events if events is not None else []
    inp = CommitInput(
        user_id="u1",
        idempotency_key=key or uuid4(),
        today=date(2026, 5, 24),
        todos=todos,
        calendar_events=events,
    )

    class _P:
        pass

    p = _P()
    p.repository = repo
    state = {
        "input": inp,
        "now": None,
        "re_routed_todos": todos,
        "re_routed_events": events,
    }
    config = {"configurable": {"ports": p, "now": None}}
    return state, config


async def test_save_dispatcher_miss_calls_save_and_returns_ids() -> None:
    repo = MemoryTodoRepository()
    state, config = _state(repo)
    diff = await save_dispatcher_node(state, config)
    assert diff["idempotent_hit"] is False
    assert len(diff["todo_ids"]) == 1
    assert diff["event_ids"] == []


async def test_save_dispatcher_hit_returns_existing_and_skips_save() -> None:
    repo = MemoryTodoRepository()
    key = uuid4()
    state1, config1 = _state(repo, key=key)
    diff1 = await save_dispatcher_node(state1, config1)
    seeded_todo_ids = diff1["todo_ids"]

    state2, config2 = _state(repo, key=key)
    diff2 = await save_dispatcher_node(state2, config2)
    assert diff2["idempotent_hit"] is True
    assert diff2["todo_ids"] == seeded_todo_ids


async def test_save_dispatcher_propagates_save_failed() -> None:
    repo = MemoryTodoRepository(fail_next=True)
    state, config = _state(repo)
    with pytest.raises(SaveFailedError):
        await save_dispatcher_node(state, config)
