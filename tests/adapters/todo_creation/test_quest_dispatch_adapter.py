from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from adapters.quest_generation.fake_llm import FakeLLM
from adapters.quest_generation.memory_repo import (
    MemoryCharacterQueryRepo,
    MemoryQuestPersistenceRepo,
    MemoryTodoQueryRepo,
)
from adapters.todo_creation.quest_dispatch_adapter import (
    CharacterRow,
    QuestDispatchAdapter,
    TodoRow,
)


def _today() -> date:
    return date(2026, 5, 25)


def _char(name: str = "A") -> CharacterRow:
    return CharacterRow(
        character_id=uuid4(),
        name=name,
        personality="p",
        speech_style="s",
        appearance_description=None,
    )


async def test_dispatch_inserts_generated_quests():
    todo_repo = MemoryTodoQueryRepo()
    char_repo = MemoryCharacterQueryRepo()
    quest_repo = MemoryQuestPersistenceRepo()
    llm = FakeLLM()

    today = _today()
    t1, t2 = TodoRow(todo_id=uuid4()), TodoRow(todo_id=uuid4())
    todo_repo.seed("u1", today, [t1, t2])
    char_repo.seed("u1", [_char("A"), _char("B")])

    adapter = QuestDispatchAdapter(
        todo_repo=todo_repo,
        character_repo=char_repo,
        quest_repo=quest_repo,
        llm=llm,
        today_fn=lambda: today,
    )

    await adapter.dispatch(user_id="u1")

    assert len(quest_repo.inserted) == 2
    assert {q.todo_id for q in quest_repo.inserted} == {t1.todo_id, t2.todo_id}
    assert len(llm.calls) == 2


async def test_dispatch_no_todos_is_silent_noop():
    todo_repo = MemoryTodoQueryRepo()
    char_repo = MemoryCharacterQueryRepo()
    quest_repo = MemoryQuestPersistenceRepo()
    llm = FakeLLM()
    char_repo.seed("u1", [_char()])

    adapter = QuestDispatchAdapter(
        todo_repo=todo_repo,
        character_repo=char_repo,
        quest_repo=quest_repo,
        llm=llm,
        today_fn=_today,
    )
    await adapter.dispatch(user_id="u1")
    assert quest_repo.inserted == []
    assert llm.calls == []


async def test_dispatch_no_characters_is_silent_noop():
    todo_repo = MemoryTodoQueryRepo()
    char_repo = MemoryCharacterQueryRepo()
    quest_repo = MemoryQuestPersistenceRepo()
    llm = FakeLLM()
    todo_repo.seed("u1", _today(), [TodoRow(todo_id=uuid4())])

    adapter = QuestDispatchAdapter(
        todo_repo=todo_repo,
        character_repo=char_repo,
        quest_repo=quest_repo,
        llm=llm,
        today_fn=_today,
    )
    await adapter.dispatch(user_id="u1")
    assert quest_repo.inserted == []
    assert llm.calls == []


async def test_dispatch_partial_failure_logs_warning_and_persists_successes(caplog):
    todo_repo = MemoryTodoQueryRepo()
    char_repo = MemoryCharacterQueryRepo()
    quest_repo = MemoryQuestPersistenceRepo()
    llm = FakeLLM(fail_times=3)  # exhaust retries on first todo

    today = _today()
    todo_repo.seed("u1", today, [TodoRow(todo_id=uuid4()), TodoRow(todo_id=uuid4())])
    char_repo.seed("u1", [_char()])

    adapter = QuestDispatchAdapter(
        todo_repo=todo_repo,
        character_repo=char_repo,
        quest_repo=quest_repo,
        llm=llm,
        today_fn=lambda: today,
    )
    with caplog.at_level(logging.WARNING, logger="adapters.todo_creation.quest_dispatch_adapter"):
        await adapter.dispatch(user_id="u1")

    assert len(quest_repo.inserted) == 1
    assert any("partial" in rec.message for rec in caplog.records)
