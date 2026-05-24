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


async def test_save_appends_per_user() -> None:
    repo = InMemoryCharacterRepository()
    await repo.save(_entity("u1"))
    await repo.save(_entity("u1"))
    await repo.save(_entity("u2"))
    assert len(repo._by_user["u1"]) == 2
    assert len(repo._by_user["u2"]) == 1


async def test_increment_returns_running_total() -> None:
    repo = InMemoryCharacterRepository()
    assert await repo.increment("u1") == 1
    assert await repo.increment("u1") == 2
    assert await repo.increment("u2") == 1
