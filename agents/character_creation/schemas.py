from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PersonalityKeyword(str, Enum):
    ADVENTUROUS = "모험적인"
    CALM = "차분한"
    CURIOUS = "호기심많은"
    AFFECTIONATE = "다정한"
    PLAYFUL = "장난스러운"
    DILIGENT = "부지런한"
    STRONG = "강력한"
    DREAMY = "몽환적인"
    ANGRY = "분노가 많은"
    BRAVE = "용감한"
    GENTLE = "온화한"
    CHEERFUL = "명랑한"


class SourceImage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    filename: str
    content_type: str
    data: bytes


class CharacterCreationInput(BaseModel):
    user_id: str
    name: Annotated[str, Field(min_length=1, max_length=50)]
    persona: Annotated[str, Field(min_length=1)]
    personality_keywords: Annotated[
        list[PersonalityKeyword],
        Field(default_factory=list, max_length=3),
    ]
    source_image: SourceImage | None = None


class LLMPersonaResult(BaseModel):
    personality: str
    speech_style: str
    background: str


class VLMResult(BaseModel):
    appearance_description: str


class CharacterEntity(BaseModel):
    character_id: UUID
    user_id: str
    name: str
    persona: str
    personality: str
    speech_style: str
    background: str
    image_url: str
    source_image_url: str | None
    appearance_description: str | None = None
    created_at: datetime
