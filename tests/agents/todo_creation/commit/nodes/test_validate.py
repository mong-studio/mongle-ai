from __future__ import annotations

from datetime import date
from uuid import uuid4

from agents.todo_creation.commit.nodes.validate import validate_node
from agents.todo_creation.schemas import CommitInput, TaskCandidate


def _t(title: str, d: date) -> TaskCandidate:
    return TaskCandidate(title=title, due_date=d)


def _input(
    todos: list[TaskCandidate] | None = None,
    events: list[TaskCandidate] | None = None,
    today: date = date(2026, 5, 24),
) -> CommitInput:
    return CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=today,
        todos=todos if todos is not None else [_t("a", today)],
        calendar_events=events if events is not None else [],
    )


def _state(inp: CommitInput) -> dict:
    return {"input": inp, "now": None}


async def test_happy_path_no_rerouting_needed() -> None:
    inp = _input(
        todos=[_t("오늘 일", date(2026, 5, 24))],
        events=[_t("내일 일", date(2026, 5, 25))],
    )
    diff = await validate_node(_state(inp), {"configurable": {}})
    assert len(diff["re_routed_todos"]) == 1
    assert diff["re_routed_todos"][0].title == "오늘 일"
    assert len(diff["re_routed_events"]) == 1
    assert diff["re_routed_events"][0].title == "내일 일"


async def test_c3_auto_reroute_when_today_item_in_events() -> None:
    inp = _input(
        todos=[_t("내일 일", date(2026, 5, 25))],
        events=[_t("오늘 일", date(2026, 5, 24))],
    )
    diff = await validate_node(_state(inp), {"configurable": {}})
    assert len(diff["re_routed_todos"]) == 1
    assert diff["re_routed_todos"][0].title == "오늘 일"
    assert len(diff["re_routed_events"]) == 1
    assert diff["re_routed_events"][0].title == "내일 일"


async def test_c3_auto_reroute_when_future_item_in_todos() -> None:
    inp = _input(
        todos=[_t("내일 일", date(2026, 5, 25))],
        events=[_t("모레 일", date(2026, 5, 26))],
    )
    diff = await validate_node(_state(inp), {"configurable": {}})
    assert diff["re_routed_todos"] == []
    assert len(diff["re_routed_events"]) == 2
