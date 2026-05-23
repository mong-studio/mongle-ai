from __future__ import annotations

from typing import Any

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.state import CharacterGraphState

MAX_ATTEMPTS = 2


async def image_generator_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    ports = config["configurable"]["ports"]
    assert state.llm_result is not None

    await ports.counter.increment(state.input.user_id)
    last_err: ImageGenerationFailedError | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            image_bytes = await ports.image_generator.generate(
                user_id=state.input.user_id,
                llm_result=state.llm_result,
                vlm_result=state.vlm_result,
                fallback_persona=state.input.persona if state.vlm_result is None else None,
            )
            return {"image_bytes": image_bytes}
        except ImageGenerationFailedError as err:
            last_err = err
            continue
    assert last_err is not None
    return {"error": last_err}
