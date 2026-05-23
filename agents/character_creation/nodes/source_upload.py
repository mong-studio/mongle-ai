from __future__ import annotations

from typing import Any

from agents.character_creation.nodes.image_upload import key_for, put_once
from agents.character_creation.state import CharacterGraphState


async def source_upload_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    image = state["input"].source_image
    assert image is not None
    key = key_for(state["input"].user_id, image.content_type, prefix="sources")
    url = await put_once(
        ports.s3, key=key, body=image.data, content_type=image.content_type
    )
    return {"source_url": url, "source_key": key}
