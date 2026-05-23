from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)

Route = Literal["text_only", "image_and_text"]


class CharacterGraphState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    input: CharacterCreationInput
    is_regeneration: bool

    route: Route | None = None

    llm_result: LLMPersonaResult | None = None
    vlm_result: VLMResult | None = None

    source_url: str | None = None
    source_key: str | None = None

    image_bytes: bytes | None = None
    generated_url: str | None = None

    entity: CharacterEntity | None = None

    error: Exception | None = None
