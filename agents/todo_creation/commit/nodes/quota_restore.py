from __future__ import annotations

from typing import Any

from agents.todo_creation.commit.state import CommitGraphState


async def quota_restore_node(
    state: CommitGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    inp = state["input"]
    await ports.quest_counter.decr(user_id=inp.user_id, day_kst=inp.today)
    return {}
