from __future__ import annotations

from typing import Any

from agents.character_creation.state import CharacterGraphState


async def cleanup_source_image_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    if state.source_key:
        await ports.s3.delete_object(key=state.source_key)
    assert state.error is not None
    raise state.error
