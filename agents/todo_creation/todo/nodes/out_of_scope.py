from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.schemas import OUT_OF_SCOPE_MESSAGE, OutOfScopeResult
from agents.todo_creation.todo.state import GenerateGraphState


async def out_of_scope_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """단일턴: 플랜과 무관한 입력에 고정 안내문(OutOfScopeResult)을 반환한다."""

    return {
        "result": OutOfScopeResult(thread_id="", message=OUT_OF_SCOPE_MESSAGE),
    }
