from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    PersonalityKeyword,
    VLMResult,
)


def test_personality_keyword_enum_has_12_values() -> None:
    assert len(PersonalityKeyword) == 12
    assert PersonalityKeyword("다정한") is PersonalityKeyword.AFFECTIONATE


def test_input_requires_persona_and_name(sample_user_id: str) -> None:
    with pytest.raises(ValidationError):
        CharacterCreationInput(user_id=sample_user_id)  # type: ignore[call-arg]


def test_input_rejects_more_than_three_keywords(sample_user_id: str) -> None:
    with pytest.raises(ValidationError):
        CharacterCreationInput(
            user_id=sample_user_id,
            name="몽글이",
            persona="설명",
            personality_keywords=[
                PersonalityKeyword.AFFECTIONATE,
                PersonalityKeyword.CALM,
                PersonalityKeyword.BRAVE,
                PersonalityKeyword.CHEERFUL,
            ],
        )


def test_llm_persona_result_all_fields_required() -> None:
    with pytest.raises(ValidationError):
        LLMPersonaResult(personality="x", speech_style="y")  # type: ignore[call-arg]


def test_vlm_result_holds_appearance_description() -> None:
    result = VLMResult(appearance_description="둥근 갈색 곰, 빨간 리본")
    assert "곰" in result.appearance_description


def test_character_entity_serializes_round_trip(sample_user_id: str) -> None:
    entity = CharacterEntity(
        character_id=uuid4(),
        user_id=sample_user_id,
        name="몽글이",
        persona="...",
        personality="다정함",
        speech_style="존댓말",
        background="숲에서 옴",
        image_url="https://s3/characters/x.png",
        source_image_url=None,
        created_at=datetime(2026, 5, 22, 12, 0, 0),
    )
    dumped = entity.model_dump()
    assert dumped["source_image_url"] is None
    assert dumped["name"] == "몽글이"
