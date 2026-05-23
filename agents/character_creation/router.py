from __future__ import annotations

from agents.character_creation.state import CharacterGraphState


def decide(state: CharacterGraphState) -> list[str]:
    """Fan out after validate.

    image-and-text path: llm_persona + source_upload 병렬 실행.
    text-only path:      llm_persona + vlm_skip — image_generator 의 fan-in
                         (llm_persona, vlm_analyzer/vlm_skip) 두 입력이 항상
                         해소되도록 더미 노드를 통과시킨다.
    """
    if state.input.source_image is not None:
        return ["llm_persona", "source_upload"]
    return ["llm_persona", "vlm_skip"]
