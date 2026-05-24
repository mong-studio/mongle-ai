from __future__ import annotations

import logging
from typing import Any

from agents.todo_creation.commit.state import CommitGraphState

logger = logging.getLogger(__name__)


async def quest_dispatch_node(
    state: CommitGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    """Call QuestDispatchPort. Failure is silently absorbed (silent skip).

    TODO: emit to a back-off queue on failure so dispatch can be retried later
    without blocking the commit response. Out of scope for the current spec.
    """
    ports = config["configurable"]["ports"]
    user_id = state["input"].user_id
    try:
        await ports.quest_dispatch.dispatch(user_id=user_id)
    except Exception as err:
        logger.exception(
            "quest_dispatch failed for user=%s (silent skip): %s", user_id, err
        )
        return {"quest_triggered": False}
    return {"quest_triggered": True}
