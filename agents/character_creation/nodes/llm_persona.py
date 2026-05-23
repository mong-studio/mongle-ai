from __future__ import annotations

from typing import Any

from agents.character_creation.state import CharacterGraphState


async def llm_persona_node(state: CharacterGraphState, config: dict[str, Any]) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    result = await ports.llm.generate_persona(
        persona=state["input"].persona,
        keywords=state["input"].personality_keywords,
    )
    return {"llm_result": result}
