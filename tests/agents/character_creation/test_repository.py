from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from agents.character_creation.repository import InMemoryCharacterRepository
from agents.character_creation.schemas import CharacterEntity


def _entity(user_id: str = "u1") -> CharacterEntity:
    return CharacterEntity(
        character_id=uuid4(),
        user_id=user_id,
        name="몽글이",
        persona="p",
        personality="x",
        speech_style="y",
        background="z",
        image_url="https://s3/c.png",
        source_image_url=None,
        created_at=datetime(2026, 5, 22),
    )


async def test_active_count_starts_at_zero() -> None:
    repo = InMemoryCharacterRepository()
    assert await repo.count_active("u1") == 0


async def test_save_increments_active_count() -> None:
    repo = InMemoryCharacterRepository()
    await repo.save(_entity("u1"))
    await repo.save(_entity("u1"))
    await repo.save(_entity("u2"))
    assert await repo.count_active("u1") == 2
    assert await repo.count_active("u2") == 1


async def test_today_regen_count_is_caller_managed() -> None:
    repo = InMemoryCharacterRepository()
    assert await repo.today_regen_count("u1") == 0
    repo.set_regen_count("u1", 2)
    assert await repo.today_regen_count("u1") == 2
