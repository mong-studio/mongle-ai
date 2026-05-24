from __future__ import annotations

from typing import Any

from agents.todo_creation.schemas import GenerateResult
from agents.todo_creation.single_turn.state import GenerateGraphState


async def date_router_node(
    state: GenerateGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    today = state["input"].today
    todos = []
    events = []
    for task in state["split_tasks"] or []:
        if task.due_date == today:
            todos.append(task)
        else:
            events.append(task)
    return {"result": GenerateResult(todos=todos, calendar_events=events)}
