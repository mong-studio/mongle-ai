from __future__ import annotations

from typing import Any

from agents.character_creation import validation
from agents.character_creation.state import CharacterGraphState


async def validate_node(state: CharacterGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    await validation.check(
        state.input, repo=ports.repository, is_regeneration=state.is_regeneration
    )
    route = "image_and_text" if state.input.source_image is not None else "text_only"
    return {"route": route}
