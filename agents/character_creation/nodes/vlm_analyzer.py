from __future__ import annotations

from typing import Any

from agents.character_creation.exceptions import VLMFailedError
from agents.character_creation.state import CharacterGraphState

MAX_ATTEMPTS = 3


async def vlm_analyzer_node(state: CharacterGraphState, config: dict[str, Any]) -> dict[str, Any]:
    if state["input"].source_image is None:
        return {"vlm_result": None}
    ports = config["configurable"]["ports"]
    for _ in range(MAX_ATTEMPTS):
        try:
            result = await ports.vlm.extract_appearance(state["input"].source_image)
            return {"vlm_result": result}
        except VLMFailedError:
            continue
    return {"vlm_result": None}
