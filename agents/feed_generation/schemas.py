from __future__ import annotations
import re
from typing import Annotated, Any
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# 캡션 허용: 한글·숫자·공백·문장부호·해시태그(#)·이모지. 그 외(한자·가나·라틴·베트남어 등)는 외국어.
_CAPTION_FOREIGN = re.compile(
    r"[^가-힣ㄱ-ㅎㅏ-ㅣ0-9\s.,!?~…·\-'\"“”‘’()\[\]%#@\U0001F000-\U0001FAFF☀-➿️‍]"
)


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
    appearance_payload: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("appearance_payload", "appearance"),
    )
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
    def _must_be_korean(cls, v: str) -> str:
        # 기존엔 '한글 포함'만 검사해 한국어+중국어 혼합 캡션이 통과했다(예: "광谱的灯光下…").
        # 한글이 있어야 하고, 허용 외 외국어 문자가 하나도 없어야 한다.
        if not re.search(r"[가-힣]", v):
            raise ValueError("caption must contain Korean")
        if _CAPTION_FOREIGN.search(v):
            raise ValueError("caption must be Korean only (foreign script not allowed)")
        return v
