from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Command

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState

ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png"}
MAX_BYTES = 5 * 1024 * 1024

_ValidateTarget = Literal["llm_persona", "source_upload", "vlm_analyzer"]


def check(input: CharacterCreationInput) -> None:
    if input.source_image is None:
        return
    if input.source_image.content_type not in ALLOWED_MIME:
        raise ValidationFailedError(
            code="C3",
            message=f"허용되지 않는 형식: {input.source_image.content_type}",
        )
    if len(input.source_image.data) > MAX_BYTES:
        raise ValidationFailedError(
            code="C4",
            message="이미지가 5MB를 초과합니다.",
        )


async def validate_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> Command[_ValidateTarget]:
    check(state["input"])
    targets: list[_ValidateTarget] = (
        ["llm_persona", "source_upload"]
        if state["input"].source_image is not None
        else ["llm_persona", "vlm_analyzer"]
    )
    return Command(goto=targets)
