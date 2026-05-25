from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agents.todo_creation.commit.pipeline import run as commit_run
from agents.todo_creation.multi_turn.state import MultiTurnGraphState
from agents.todo_creation.schemas import CommitInput, TaskCandidate, TurnResult


def _idempotency_key(session_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"multi:{session_id}")


async def commit_invoke_node(state: MultiTurnGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    now = config["configurable"]["now"]
    input_ = state["input"]
    plan = state["current_plan"]
    today = input_.today

    candidates = [
        TaskCandidate(title=t.title, due_date=d.date, time_hint=t.time_hint, tags=t.tags)
        for d in plan.days for t in d.tasks
    ]
    todos = [c for c in candidates if c.due_date == today]
    events = [c for c in candidates if c.due_date != today]

    commit_input = CommitInput(
        user_id=input_.user_id,
        idempotency_key=_idempotency_key(input_.session_id),
        today=today,
        todos=todos,
        calendar_events=events,
    )
    result = await commit_run(commit_input, ports=ports.commit_ports, now=now)

    await ports.session_store.delete(session_id=input_.session_id)
    return {"result": TurnResult(kind="committed", commit_result=result)}
