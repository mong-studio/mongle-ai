from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import OutOfScopeResult, out_of_scope_message_for
from agents.todo_creation.todo.state import GenerateGraphState


async def out_of_scope_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    """단일턴: 플랜과 무관한 입력에 짧게 반응하고 계획 대화로 유도한다."""

    message = str(state.get("prompt") or "")
    return {
        "result": OutOfScopeResult(
            thread_id="",
            message=await _generate_reply(message=message, config=config),
        ),
    }


async def _generate_reply(*, message: str, config: RunnableConfig) -> str:
    llm = get_ports(config).llm
    generator = getattr(llm, "generate_out_of_scope_reply", None)
    if generator is None:
        return out_of_scope_message_for(message)
    try:
        return await generator(message=message, history=[])
    except (LLMFailedError, LLMOutputError, TimeoutError):
        return out_of_scope_message_for(message)
