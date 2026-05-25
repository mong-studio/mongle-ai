from __future__ import annotations

from typing import TypedDict

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)


class _RequiredState(TypedDict):
    input: CharacterCreationInput


class CharacterGraphState(_RequiredState, total=False):
    llm_result: LLMPersonaResult | None
    vlm_result: VLMResult | None

    source_url: str | None
    source_key: str | None

    image_bytes: bytes | None
    generated_url: str | None

    entity: CharacterEntity | None

    error: Exception | None
