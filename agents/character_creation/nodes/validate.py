from __future__ import annotations

from typing import Any

from agents.character_creation.exceptions import ValidationFailedError
from agents.character_creation.protocols import CharacterRepositoryPort
from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState

ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png"}
MAX_BYTES = 5 * 1024 * 1024
MAX_ACTIVE_CHARACTERS = 10
MAX_DAILY_REGEN = 3


async def check(
    input: CharacterCreationInput,
    *,
    repo: CharacterRepositoryPort,
    is_regeneration: bool,
) -> None:
    if await repo.count_active(input.user_id) >= MAX_ACTIVE_CHARACTERS:
        raise ValidationFailedError(
            code="C1",
            message=f"보유 캐릭터가 {MAX_ACTIVE_CHARACTERS}개를 초과했습니다.",
        )

    if is_regeneration:
        used = await repo.today_regen_count(input.user_id)
        if used >= MAX_DAILY_REGEN:
            raise ValidationFailedError(
                code="C2",
                message=f"오늘 재생성 횟수가 {MAX_DAILY_REGEN}회를 초과했습니다.",
            )

    if input.source_image is not None:
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


async def validate_node(state: CharacterGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    await check(
        state["input"], repo=ports.repository, is_regeneration=state["is_regeneration"]
    )
    route = "image_and_text" if state["input"].source_image is not None else "text_only"
    return {"route": route}
