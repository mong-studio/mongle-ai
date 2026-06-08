from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.commit.state import CommitGraphState


async def save_dispatcher_node(
    state: CommitGraphState, config: RunnableConfig
) -> dict[str, Any]:
    ports = get_ports(config)
    repo = ports.repository
    inp = state.get("input")
    if inp is None:
        raise KeyError("CommitGraphState.input is required")

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
        todos=state.get("re_routed_todos") or [],
        events=state.get("re_routed_events") or [],
    )
    return {
        "idempotent_hit": False,
        "todo_ids": todo_ids,
        "event_ids": event_ids,
    }
