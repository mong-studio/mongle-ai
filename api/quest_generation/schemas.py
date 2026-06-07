from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.quest_generation.schemas import (
    Character,
    QuestGenerationInput,
    TodoRef,
)


class QuestCharacterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    persona: str | None = None
    personality: str | None = None
    speech_style: str | None = None
    appearance_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_profile(self) -> "QuestCharacterRequest":
        if not (self.persona or self.personality):
            raise ValueError("persona 또는 personality 중 하나는 필요합니다")
        return self

    def to_agent_character(self) -> Character:
        return Character(
            character_id=self.character_id,
            name=self.name,
            personality=self.personality or self.persona or "",
            speech_style=self.speech_style or "기본 말투",
            appearance_keywords=self.appearance_keywords,
        )


class QuestGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todos: list[TodoRef]
    characters: list[QuestCharacterRequest]
    remaining_daily_quota: Annotated[int, Field(ge=0)]
    shuffle_seed: int | None = None

    def to_agent_input(self) -> QuestGenerationInput:
        return QuestGenerationInput(
            todos=self.todos,
            characters=[c.to_agent_character() for c in self.characters],
            remaining_daily_quota=self.remaining_daily_quota,
            shuffle_seed=self.shuffle_seed,
        )
