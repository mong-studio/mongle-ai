from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TodoRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    todo_id: UUID


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: Annotated[str, Field(min_length=1)]
    speech_style: Annotated[str, Field(min_length=1)]
    appearance_keywords: list[str] = Field(default_factory=list)


class QuestGenerationInput(BaseModel):
    todos: list[TodoRef]
    characters: list[Character]
    remaining_daily_quota: Annotated[int, Field(ge=0)]
    shuffle_seed: int | None = None


class GeneratedQuest(BaseModel):
    character_id: UUID
    todo_id: UUID
    quest_text: Annotated[str, Field(min_length=1, max_length=80)]


class SkippedItem(BaseModel):
    todo_id: UUID
    reason: Literal["llm_failure"]


class QuestDistributionResult(BaseModel):
    generated: list[GeneratedQuest]
    skipped: list[SkippedItem]
