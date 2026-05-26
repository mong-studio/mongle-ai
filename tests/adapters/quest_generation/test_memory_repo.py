from __future__ import annotations

from datetime import date
from uuid import uuid4

from adapters.quest_generation.memory_repo import (
    MemoryCharacterQueryRepo,
    MemoryQuestPersistenceRepo,
    MemoryTodoQueryRepo,
)
from adapters.todo_creation.quest_dispatch_adapter import CharacterRow, TodoRow
from agents.quest_generation.schemas import GeneratedQuest


async def test_memory_todo_returns_inserted_rows_for_user_date():
    repo = MemoryTodoQueryRepo()
    today = date(2026, 5, 25)
    row_a = TodoRow(todo_id=uuid4())
    row_b = TodoRow(todo_id=uuid4())
    repo.seed("u1", today, [row_a, row_b])
    repo.seed("u1", date(2026, 5, 26), [TodoRow(todo_id=uuid4())])
    repo.seed("u2", today, [TodoRow(todo_id=uuid4())])

    got = await repo.list_today_pending(user_id="u1", today=today)
    assert got == [row_a, row_b]


async def test_memory_todo_empty_default():
    repo = MemoryTodoQueryRepo()
    got = await repo.list_today_pending(user_id="u1", today=date(2026, 5, 25))
    assert got == []


async def test_memory_character_returns_active_for_user():
    repo = MemoryCharacterQueryRepo()
    char_a = CharacterRow(
        character_id=uuid4(),
        name="A",
        personality="p",
        speech_style="s",
        appearance_description=None,
    )
    repo.seed("u1", [char_a])
    got = await repo.list_active(user_id="u1")
    assert got == [char_a]

    other = await repo.list_active(user_id="u2")
    assert other == []


async def test_memory_quest_persistence_records_inserts():
    repo = MemoryQuestPersistenceRepo()
    q = GeneratedQuest(character_id=uuid4(), todo_id=uuid4(), quest_text="hello")
    await repo.insert_many(quests=[q])
    assert repo.inserted == [q]

    await repo.insert_many(quests=[])
    assert repo.inserted == [q]  # empty list is no-op
