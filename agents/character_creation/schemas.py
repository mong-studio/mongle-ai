from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
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
    appearance: str
    # 영어 이미지 태그는 필수. 비면 스키마 검증 실패 → qwen 어댑터가 재시도해 채운다.
    # (워커의 Qwen2-VL 재번역을 없애려면 이 값이 항상 채워져야 한다.)
    appearance_en: Annotated[str, Field(min_length=1)]


class ImageGenerationResult(BaseModel):
    image_bytes: bytes
    appearance_payload: dict[str, Any] | None = None


class CharacterEntity(BaseModel):
    character_id: UUID
    user_id: str
    name: str
    persona: str
    personality: str
    speech_style: str
    background: str
    appearance: str
    appearance_payload: dict[str, Any] | None = None
    image_url: str
    source_image_url: str | None
    created_at: datetime
    # 단계별 소요시간(초). 키: "llm_persona", "image_generator". 계측 실패 시 비어 있음.
    timings: dict[str, float] = Field(default_factory=dict)
