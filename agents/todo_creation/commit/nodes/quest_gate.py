from __future__ import annotations

from typing import Any

from langgraph.graph import END

from agents.todo_creation.commit.state import CommitGraphState

QUEST_DAILY_LIMIT = 5


async def quest_gate(
    state: CommitGraphState, config: dict[str, Any]
) -> str:
    """Conditional-edge router function.

    Returns "quest_dispatch" when all conditions hold:
      - At least one re_routed_todo has due_date == today (saved as today's TODO)
      - This commit is not an idempotent hit (so we don't double-trigger)
      - The per-user-per-day counter has room (atomic increment).
    Otherwise returns END.

    NB: incrementing the counter is a side effect that happens here. We do it
    only when we have actually decided to dispatch — otherwise the limit is
    not "consumed".
    """
    inp = state["input"]
    today = inp.today

    has_today_todo = any(
        t.due_date == today for t in (state.get("re_routed_todos") or [])
    )
    if not has_today_todo:
        return END
    if state.get("idempotent_hit") is True:
        return END

    ports = config["configurable"]["ports"]
    counter = ports.quest_counter
    acquired = await counter.incr_if_under_limit(
        user_id=inp.user_id, day_kst=today, limit=QUEST_DAILY_LIMIT
    )
    if not acquired:
        return END
    return "quest_dispatch"
