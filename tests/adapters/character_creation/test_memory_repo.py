from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from adapters.character_creation.memory_repo import InMemoryRepo
from agents.character_creation.schemas import CharacterEntity


def _entity(user_id: str = "u1", name: str = "보리") -> CharacterEntity:
    return CharacterEntity(
        character_id=uuid4(),
        user_id=user_id,
        name=name,
        persona="용감한 강아지",
        personality="용감함",
        speech_style="씩씩한 말투",
        background="동네 골목대장",
        image_url="https://example.com/x.png",
        source_image_url=None,
        created_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_count_active_starts_at_zero() -> None:
    repo = InMemoryRepo()
    assert await repo.count_active("u1") == 0


@pytest.mark.asyncio
async def test_save_then_count_active() -> None:
    repo = InMemoryRepo()
    await repo.save(_entity(user_id="u1"))
    await repo.save(_entity(user_id="u1", name="감자"))
    await repo.save(_entity(user_id="u2"))
    assert await repo.count_active("u1") == 2
    assert await repo.count_active("u2") == 1


@pytest.mark.asyncio
async def test_today_regen_count_starts_at_zero() -> None:
    repo = InMemoryRepo()
    assert await repo.today_regen_count("u1") == 0


@pytest.mark.asyncio
async def test_increment_counter_returns_new_value() -> None:
    repo = InMemoryRepo()
    assert await repo.increment("u1") == 1
    assert await repo.increment("u1") == 2
    assert await repo.today_regen_count("u1") == 2
    assert await repo.today_regen_count("u2") == 0


@pytest.mark.asyncio
async def test_list_returns_saved_entities_for_user() -> None:
    repo = InMemoryRepo()
    a = _entity(user_id="u1", name="보리")
    b = _entity(user_id="u1", name="감자")
    c = _entity(user_id="u2", name="콩이")
    await repo.save(a)
    await repo.save(b)
    await repo.save(c)
    assert [e.name for e in repo.list_characters("u1")] == ["보리", "감자"]
    assert [e.name for e in repo.list_characters("u2")] == ["콩이"]
