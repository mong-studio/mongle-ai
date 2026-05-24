from __future__ import annotations

from typing import Any

from agents.todo_creation.commit.state import CommitGraphState


async def save_dispatcher_node(
    state: CommitGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    repo = ports.repository
    inp = state["input"]

    existing = await repo.find_by_idempotency_key(
        user_id=inp.user_id, key=inp.idempotency_key
    )
    if existing is not None:
        return {
            "idempotent_hit": True,
            "todo_ids": existing.todo_ids,
            "event_ids": existing.event_ids,
        }

    todo_ids, event_ids = await repo.save(
        user_id=inp.user_id,
        idempotency_key=inp.idempotency_key,
        todos=state["re_routed_todos"] or [],
        events=state["re_routed_events"] or [],
    )
    return {
        "idempotent_hit": False,
        "todo_ids": todo_ids,
        "event_ids": event_ids,
    }
