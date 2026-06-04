from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from agents.character_creation.schemas import PersonalityKeyword


class CharacterCreationRequest(BaseModel):
    user_id: str
    name: Annotated[str, Field(min_length=1, max_length=50)]
    persona: Annotated[str, Field(min_length=1)]
    personality_keywords: Annotated[
        list[PersonalityKeyword], Field(default_factory=list, max_length=3)
    ]
    source_image_key: str | None = None
    source_image_url: str | None = None
    source_image_content_type: str | None = None
