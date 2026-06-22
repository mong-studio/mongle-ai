from uuid import uuid4
import pytest
from pydantic import ValidationError
from agents.feed_generation.schemas import CharacterRef, QuestRef, GeneratedFeed


def _char(**kw):
    data = dict(character_id=uuid4(), name="몽글이", personality="밝음",
                speech_style="반말", visual=["분홍"], image_url="https://x/y.png")
    data.update(kw)
    return data


def test_visual_alias_accepts_old_key():
    c = CharacterRef(**{k: v for k, v in _char().items() if k != "visual"},
                     appearance_keywords=["분홍"])
    assert c.visual == ["분홍"]


def test_quest_alias_accepts_old_key():
    q = QuestRef(quest_id=uuid4(), quest_text="방 청소하기")
    assert q.quest == "방 청소하기"


def test_blank_image_url_rejected():
    with pytest.raises(ValidationError):
        CharacterRef(**_char(image_url="   "))


def test_caption_requires_korean():
    with pytest.raises(ValidationError):
        GeneratedFeed(character_id=uuid4(), quest_id=uuid4(),
                      image_url="https://x", caption="all english here")


def test_caption_over_140_rejected():
    with pytest.raises(ValidationError):
        GeneratedFeed(character_id=uuid4(), quest_id=uuid4(),
                      image_url="https://x", caption="가" * 141)
