from __future__ import annotations
import re
from typing import Annotated
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class QuestRef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    quest_id: UUID
    quest: Annotated[str, Field(min_length=1, max_length=300,
                                validation_alias=AliasChoices("quest", "quest_text"))]


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True,
                              str_strip_whitespace=True)
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: str
    speech_style: str
    visual: list[str] = Field(
        validation_alias=AliasChoices("visual", "appearance_keywords"))
    image_url: Annotated[str, Field(min_length=1)]


class FeedGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest: QuestRef
    character: CharacterRef


class FeedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str  # visual + action (캐릭터 포즈)
    scene: str      # 배경 장면


class GeneratedFeed(BaseModel):
    character_id: UUID
    quest_id: UUID
    image_url: str
    caption: Annotated[str, Field(max_length=140)]

    @field_validator("caption")
    @classmethod
    def _must_contain_korean(cls, v: str) -> str:
        if not re.search(r"[가-힣]", v):
            raise ValueError("caption must contain Korean")
        return v
