from __future__ import annotations

from typing import Any, TypedDict

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
)


class _RequiredState(TypedDict):
    input: CharacterCreationInput


class CharacterGraphState(_RequiredState, total=False):
    llm_result: LLMPersonaResult | None

    source_url: str | None
    source_key: str | None

    image_bytes: bytes | None
    appearance_payload: dict[str, Any] | None
    generated_url: str | None

    entity: CharacterEntity | None

    # 단계별 소요시간(초). 각 노드가 자기 것만 기록 → builder 가 entity.timings 로 합친다.
    llm_persona_seconds: float | None
    image_generator_seconds: float | None
    source_upload_seconds: float | None
    generated_upload_seconds: float | None

    error: Exception | None
