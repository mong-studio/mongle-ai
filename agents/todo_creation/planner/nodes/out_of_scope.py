from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.schemas import PLANNER_OUT_OF_SCOPE_MESSAGE


async def out_of_scope_node(
    state: dict[str, Any], config: RunnableConfig
) -> dict[str, Any]:
    """플랜과 관련 없는 입력에는 고정 안내문만 반환한다."""

    return {
        "out_of_scope_message": PLANNER_OUT_OF_SCOPE_MESSAGE,
        "todos": [],
        "calendar_events": [],
    }
