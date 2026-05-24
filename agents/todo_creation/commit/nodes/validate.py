from __future__ import annotations

from typing import Any

from agents.todo_creation.commit.state import CommitGraphState


async def validate_node(
    state: CommitGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    """C1/C2/C5 are enforced by Pydantic on CommitInput.
    C3: re-route items by due_date vs today.
    C4 (user_id match) is the caller/router layer's responsibility.
    """
    inp = state["input"]
    today = inp.today

    re_todos = []
    re_events = []
    for item in [*inp.todos, *inp.calendar_events]:
        if item.due_date == today:
            re_todos.append(item)
        else:
            re_events.append(item)
    return {"re_routed_todos": re_todos, "re_routed_events": re_events}
