from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from agents.todo_creation.commit.graph import build_commit_graph
from agents.todo_creation.exceptions import SaveFailedError
from agents.todo_creation.schemas import CommitInput, TaskCandidate


class _SuccessDispatch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, user_id: str) -> None:
        self.calls.append(user_id)


class _FailingDispatch:
    async def dispatch(self, *, user_id: str) -> None:
        raise RuntimeError("dispatch broken")


class _Ports:
    def __init__(self, repo, counter, dispatch) -> None:
        self.repository = repo
        self.quest_counter = counter
        self.quest_dispatch = dispatch


def _today() -> date:
    return date(2026, 5, 24)


def _input(
    *,
    today_count: int = 1,
    future_count: int = 0,
    key=None,
) -> CommitInput:
    return CommitInput(
        user_id="u1",
        idempotency_key=key or uuid4(),
        today=_today(),
        todos=[
            TaskCandidate(title=f"오늘{i}", due_date=_today())
            for i in range(today_count)
        ],
        calendar_events=[
            TaskCandidate(title=f"내일{i}", due_date=date(2026, 5, 25))
            for i in range(future_count)
        ],
    )


def _state(inp: CommitInput) -> dict:
    return {"input": inp, "now": None}


async def test_commit_graph_happy_today_triggers_quest() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    dispatch = _SuccessDispatch()
    final = await graph.ainvoke(
        _state(_input(today_count=2)),
        config={
            "configurable": {
                "ports": _Ports(repo, counter, dispatch),
                "now": None,
            }
        },
    )
    assert final["quest_triggered"] is True
    assert len(final["todo_ids"]) == 2
    assert counter.peek(user_id="u1", day_kst=_today()) == 1
    assert dispatch.calls == ["u1"]


async def test_commit_graph_at_quota_skips_trigger() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    for _ in range(5):
        await counter.incr_if_under_limit(
            user_id="u1", day_kst=_today(), limit=5
        )
    dispatch = _SuccessDispatch()
    final = await graph.ainvoke(
        _state(_input(today_count=1)),
        config={
            "configurable": {
                "ports": _Ports(repo, counter, dispatch),
                "now": None,
            }
        },
    )
    assert final.get("quest_triggered") in (False, None)
    assert dispatch.calls == []
    assert counter.peek(user_id="u1", day_kst=_today()) == 5


async def test_commit_graph_future_only_skips_trigger() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    dispatch = _SuccessDispatch()
    final = await graph.ainvoke(
        _state(_input(today_count=0, future_count=2)),
        config={
            "configurable": {
                "ports": _Ports(repo, counter, dispatch),
                "now": None,
            }
        },
    )
    assert final.get("quest_triggered") in (False, None)
    assert len(final["event_ids"]) == 2
    assert dispatch.calls == []


async def test_commit_graph_idempotent_second_call_skips_save_and_trigger() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    dispatch = _SuccessDispatch()
    key = uuid4()
    ports = _Ports(repo, counter, dispatch)

    final1 = await graph.ainvoke(
        _state(_input(today_count=1, key=key)),
        config={"configurable": {"ports": ports, "now": None}},
    )
    final2 = await graph.ainvoke(
        _state(_input(today_count=1, key=key)),
        config={"configurable": {"ports": ports, "now": None}},
    )
    assert final1["todo_ids"] == final2["todo_ids"]
    assert final2["idempotent_hit"] is True
    assert dispatch.calls == ["u1"]
    assert counter.peek(user_id="u1", day_kst=_today()) == 1


async def test_commit_graph_c3_auto_reroute() -> None:
    """User puts today item into calendar_events; backend re-routes."""
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    dispatch = _SuccessDispatch()
    inp = CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=_today(),
        todos=[TaskCandidate(title="내일 일", due_date=date(2026, 5, 25))],
        calendar_events=[TaskCandidate(title="오늘 일", due_date=_today())],
    )
    final = await graph.ainvoke(
        _state(inp),
        config={
            "configurable": {
                "ports": _Ports(repo, counter, dispatch),
                "now": None,
            }
        },
    )
    assert len(final["todo_ids"]) == 1
    assert len(final["event_ids"]) == 1
    assert final["quest_triggered"] is True


async def test_commit_graph_save_failure_raises_and_does_not_dispatch() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository(fail_next=True)
    counter = MemoryQuestCounter()
    dispatch = _SuccessDispatch()
    with pytest.raises(SaveFailedError):
        await graph.ainvoke(
            _state(_input(today_count=1)),
            config={
                "configurable": {
                    "ports": _Ports(repo, counter, dispatch),
                    "now": None,
                }
            },
        )
    assert dispatch.calls == []
    assert counter.peek(user_id="u1", day_kst=_today()) == 0


async def test_commit_graph_dispatch_failure_does_not_break_commit() -> None:
    graph = build_commit_graph()
    repo = MemoryTodoRepository()
    counter = MemoryQuestCounter()
    dispatch = _FailingDispatch()
    final = await graph.ainvoke(
        _state(_input(today_count=1)),
        config={
            "configurable": {
                "ports": _Ports(repo, counter, dispatch),
                "now": None,
            }
        },
    )
    assert len(final["todo_ids"]) == 1
    assert final["quest_triggered"] is False
    assert counter.peek(user_id="u1", day_kst=_today()) == 0
