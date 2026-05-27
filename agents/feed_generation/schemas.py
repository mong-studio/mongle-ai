from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuestRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest_id: UUID
    quest_text: Annotated[str, Field(min_length=1, max_length=300)]


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: str
    speech_style: str
    appearance_keywords: list[str]
    image_url: str


class FeedGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest: QuestRef
    character: CharacterRef


class GeneratedFeed(BaseModel):
    character_id: UUID
    quest_id: UUID
    image_url: str
    caption: Annotated[str, Field(max_length=140)]
