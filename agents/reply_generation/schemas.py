from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=50)]
    personality: str
    speech_style: str


class ReplyGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: CharacterRef
    post_caption: Annotated[str, Field(min_length=1, max_length=150)]
    user_comment: Annotated[str, Field(min_length=1, max_length=50)]


class GeneratedReply(BaseModel):
    character_id: UUID
    reply_text: Annotated[str, Field(min_length=1, max_length=50)]
