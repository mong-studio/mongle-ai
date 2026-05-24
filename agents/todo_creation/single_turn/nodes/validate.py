from __future__ import annotations

from typing import Any

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.schemas import SingleTurnInput
from agents.todo_creation.single_turn.state import GenerateGraphState


def check(input: SingleTurnInput) -> None:
    if len(input.prompt) > 200:
        raise ValidationError(code="A1", message="prompt exceeds 200 chars")
    if not input.prompt.strip():
        raise ValidationError(code="A2", message="prompt is empty or whitespace")
    if not input.user_id:
        raise ValidationError(code="A3", message="user_id is required")


async def validate_node(
    state: GenerateGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    check(state["input"])
    return {}
