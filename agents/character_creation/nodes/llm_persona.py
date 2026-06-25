from __future__ import annotations

import time
from typing import Any

from agents.character_creation.state import CharacterGraphState


async def llm_persona_node(state: CharacterGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    start = time.perf_counter()
    result = await ports.llm.generate_persona(
        name=state["input"].name,
        persona=state["input"].persona,
        keywords=state["input"].personality_keywords,
    )
    elapsed = round(time.perf_counter() - start, 3)
    return {"llm_result": result, "llm_persona_seconds": elapsed}
