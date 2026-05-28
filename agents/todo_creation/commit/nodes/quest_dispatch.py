from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END
from langgraph.types import Command

from agents.todo_creation.commit.state import CommitGraphState

logger = logging.getLogger(__name__)


async def quest_dispatch_node(
    state: CommitGraphState, config: dict[str, Any]
) -> Command:
    """Call QuestDispatchPort. On failure, routes to quota_restore to decrement
    the counter that quest_gate already incremented."""
    ports = config["configurable"]["ports"]
    user_id = state["input"].user_id
    try:
        await ports.quest_dispatch.dispatch(user_id=user_id)
    except Exception as err:
        logger.exception(
            "quest_dispatch failed for user=%s, restoring quota slot: %s", user_id, err
        )
        return Command(goto="quota_restore", update={"quest_triggered": False})
    return Command(goto=END, update={"quest_triggered": True})
