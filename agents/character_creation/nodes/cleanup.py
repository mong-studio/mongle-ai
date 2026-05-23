from __future__ import annotations

from typing import Any

from agents.character_creation.state import CharacterGraphState


async def cleanup_source_image_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    source_key = state.get("source_key")
    if source_key:
        await ports.s3.delete_object(key=source_key)
    error = state.get("error")
    assert error is not None
    raise error
