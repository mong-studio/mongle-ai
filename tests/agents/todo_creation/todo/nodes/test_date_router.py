from __future__ import annotations

from datetime import date

from agents.todo_creation.schemas import SingleTurnInput, TaskCandidate
from agents.todo_creation.single_turn.nodes.date_router import date_router_node


def _state(split: list[TaskCandidate]) -> dict:
    return {
        "input": SingleTurnInput(
            user_id="u1", prompt="x", today=date(2026, 5, 24)
        ),
        "now": None,
        "split_tasks": split,
    }


async def test_all_today_goes_to_todos() -> None:
    tasks = [
        TaskCandidate(title="a", due_date=date(2026, 5, 24)),
        TaskCandidate(title="b", due_date=date(2026, 5, 24)),
    ]
    diff = await date_router_node(_state(tasks), {"configurable": {}})
    assert len(diff["result"].todos) == 2
    assert diff["result"].calendar_events == []


async def test_all_future_goes_to_events() -> None:
    tasks = [TaskCandidate(title="a", due_date=date(2026, 5, 27))]
    diff = await date_router_node(_state(tasks), {"configurable": {}})
    assert diff["result"].todos == []
    assert len(diff["result"].calendar_events) == 1


async def test_mixed_routes_correctly() -> None:
    tasks = [
        TaskCandidate(title="today", due_date=date(2026, 5, 24)),
        TaskCandidate(title="future", due_date=date(2026, 5, 27)),
    ]
    diff = await date_router_node(_state(tasks), {"configurable": {}})
    assert len(diff["result"].todos) == 1
    assert diff["result"].todos[0].title == "today"
    assert len(diff["result"].calendar_events) == 1
    assert diff["result"].calendar_events[0].title == "future"


async def test_empty_split_yields_empty_result() -> None:
    diff = await date_router_node(_state([]), {"configurable": {}})
    assert diff["result"].todos == []
    assert diff["result"].calendar_events == []
