from __future__ import annotations

from typing import Literal, TypedDict

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)

Route = Literal["text_only", "image_and_text"]


class _RequiredState(TypedDict):
    input: CharacterCreationInput


class CharacterGraphState(_RequiredState, total=False):
    route: Route | None

    llm_result: LLMPersonaResult | None
    vlm_result: VLMResult | None

    source_url: str | None
    source_key: str | None

    image_bytes: bytes | None
    generated_url: str | None

    entity: CharacterEntity | None

    error: Exception | None
