from __future__ import annotations

from agents.character_creation.state import CharacterGraphState


def decide(state: CharacterGraphState) -> list[str]:
    """Fan out after validate.

    image-and-text path: llm_persona + source_upload 병렬 실행 후
                         source_upload → vlm_analyzer.
    text-only path:      llm_persona + vlm_analyzer 직접 — vlm_analyzer 가
                         source_image 부재를 감지하면 즉시 {"vlm_result": None}
                         을 반환해 image_generator fan-in 을 만족시킨다.
    """
    if state["input"].source_image is not None:
        return ["llm_persona", "source_upload"]
    return ["llm_persona", "vlm_analyzer"]
