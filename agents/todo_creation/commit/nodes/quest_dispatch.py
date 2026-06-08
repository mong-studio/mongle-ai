from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.commit.state import CommitGraphState

logger = logging.getLogger(__name__)


async def quest_dispatch_node(
    state: CommitGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """Call QuestDispatchPort. Failure is silently absorbed (silent skip).

    TODO: emit to a back-off queue on failure so dispatch can be retried later
    without blocking the commit response. Out of scope for the current spec.

    Known limitation: the daily quest counter was already incremented in
    quest_gate BEFORE this node runs, so a silent dispatch failure consumes a
    quota slot without delivering a quest. Over a day this can starve a user.
    A real backend should either (a) decrement the counter on failure, or
    (b) move the increment after a successful dispatch and accept the
    micro-race. Tracked for follow-up alongside the back-off queue.
    """
    ports = get_ports(config)
    user_id = state["input"].user_id
    try:
        await ports.quest_dispatch.dispatch(user_id=user_id)
    except Exception as err:
        logger.exception(
            "quest_dispatch failed for user=%s (silent skip): %s", user_id, err
        )
        return {"quest_triggered": False}
    return {"quest_triggered": True}
