from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.planner.conversation_style import render_chief_voice
from agents.todo_creation.schemas import out_of_scope_message_for


async def out_of_scope_node(
    state: dict[str, Any], config: RunnableConfig
) -> dict[str, Any]:
    """플랜과 관련 없는 입력에는 짧게 반응하고 계획 대화로 유도한다."""

    message = str(state.get("message") or "")
    reply = await _generate_reply(message=message, state=state, config=config)
    return {
        "out_of_scope_message": render_chief_voice(reply),
        "todos": [],
        "calendar_events": [],
    }


async def _generate_reply(
    *, message: str, state: dict[str, Any], config: RunnableConfig
) -> str:
    ports = get_ports(config)
    llm = getattr(ports, "classifier", None) or ports.llm
    generator = getattr(llm, "generate_out_of_scope_reply", None)
    if generator is None:
        return out_of_scope_message_for(message)
    try:
        reply = await generator(message=message, history=state.get("history", []))
        return reply
    except (LLMFailedError, LLMOutputError, TimeoutError):
        return out_of_scope_message_for(message)
