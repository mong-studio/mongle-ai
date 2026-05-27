from uuid import uuid4

import pytest
from pydantic import ValidationError

from agents.feed_generation.schemas import (
    QuestRef,
    CharacterRef,
    FeedGenerationInput,
    GeneratedFeed,
)


def test_quest_ref_rejects_empty_text():
    with pytest.raises(ValidationError):
        QuestRef(quest_id=uuid4(), quest_text="")


def test_character_ref_requires_image_url():
    with pytest.raises(ValidationError):
        CharacterRef(
            character_id=uuid4(),
            name="몽글이",
            personality="밝음",
            speech_style="반말",
            appearance_keywords=["분홍 머리"],
        )


def test_feed_generation_input_rejects_extra_fields():
    with pytest.raises(ValidationError):
        FeedGenerationInput(
            quest={"quest_id": str(uuid4()), "quest_text": "청소"},
            character={
                "character_id": str(uuid4()),
                "name": "몽글이",
                "personality": "밝음",
                "speech_style": "반말",
                "appearance_keywords": [],
                "image_url": "https://s3.example.com/c.png",
            },
            extra_field="bad",
        )


def test_generated_feed_rejects_caption_over_140():
    with pytest.raises(ValidationError):
        GeneratedFeed(
            character_id=uuid4(),
            quest_id=uuid4(),
            image_url="https://s3.example.com/f.png",
            caption="가" * 141,
        )


def test_generated_feed_accepts_caption_at_140():
    feed = GeneratedFeed(
        character_id=uuid4(),
        quest_id=uuid4(),
        image_url="https://s3.example.com/f.png",
        caption="가" * 140,
    )
    assert len(feed.caption) == 140
