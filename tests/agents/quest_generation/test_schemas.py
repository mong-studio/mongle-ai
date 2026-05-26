from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.quest_generation.schemas import (
    Character,
    GeneratedQuest,
    QuestDistributionResult,
    QuestGenerationInput,
    SkippedItem,
    TodoRef,
)


def test_todo_ref_holds_only_id():
    ref = TodoRef(todo_id=uuid4())
    assert set(ref.model_fields.keys()) == {"todo_id"}


def test_character_required_fields():
    c = Character(
        character_id=uuid4(),
        name="버섯이",
        personality="호기심 많고 조용함",
        speech_style="존댓말",
        appearance_keywords=["빨간 모자", "둥근 몸"],
    )
    assert c.name == "버섯이"


def test_quest_generation_input_quota_nonneg():
    with pytest.raises(ValidationError):
        QuestGenerationInput(
            todos=[],
            characters=[],
            remaining_daily_quota=-1,
        )


def test_quest_generation_input_seed_optional():
    inp = QuestGenerationInput(
        todos=[],
        characters=[],
        remaining_daily_quota=0,
    )
    assert inp.shuffle_seed is None


def test_generated_quest_text_max_80():
    with pytest.raises(ValidationError):
        GeneratedQuest(
            character_id=uuid4(),
            todo_id=uuid4(),
            quest_text="가" * 81,
        )


def test_generated_quest_text_min_1():
    with pytest.raises(ValidationError):
        GeneratedQuest(
            character_id=uuid4(),
            todo_id=uuid4(),
            quest_text="",
        )


def test_skipped_item_reason_literal():
    item = SkippedItem(todo_id=uuid4(), reason="llm_failure")
    assert item.reason == "llm_failure"

    with pytest.raises(ValidationError):
        SkippedItem(todo_id=uuid4(), reason="other")  # type: ignore[arg-type]


def test_result_default_empty_lists():
    r = QuestDistributionResult(generated=[], skipped=[])
    assert r.generated == []
    assert r.skipped == []
