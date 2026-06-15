from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.schemas import TodoInput
from agents.todo_creation.todo.state import GenerateGraphState


def check(input: TodoInput) -> None:
    if len(input.message) > 200:
        raise ValidationError(code="A1", message="message exceeds 200 chars")
    if not input.message.strip():
        raise ValidationError(code="A2", message="message is empty or whitespace")
    if not input.user_id:
        raise ValidationError(code="A3", message="user_id is required")


async def validate_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    check(state["input"])
    return {}
