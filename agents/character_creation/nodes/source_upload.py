from __future__ import annotations

import time
from typing import Any

from agents.character_creation.nodes._upload_utils import key_for, put_once
from agents.character_creation.state import CharacterGraphState


async def source_upload_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    image = state["input"].source_image
    assert image is not None
    key = key_for(state["input"].user_id, image.content_type, prefix="sources")
    start = time.perf_counter()
    url = await put_once(
        ports.s3, key=key, body=image.data, content_type=image.content_type
    )
    return {
        "source_url": url,
        "source_key": key,
        "source_upload_seconds": round(time.perf_counter() - start, 3),
    }
