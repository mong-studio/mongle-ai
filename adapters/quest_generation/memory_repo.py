from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from adapters.todo_creation.quest_dispatch_adapter import CharacterRow, TodoRow
from agents.quest_generation.schemas import GeneratedQuest


@dataclass
class MemoryTodoQueryRepo:
    """In-memory TodoQueryPort. Use `seed(user_id, today, rows)` from test fixtures or app dev mode."""

    _by_user_day: dict[tuple[str, date], list[TodoRow]] = field(default_factory=dict)

    def seed(self, user_id: str, day: date, rows: list[TodoRow]) -> None:
        self._by_user_day[(user_id, day)] = list(rows)

    async def list_today_pending(
        self, *, user_id: str, today: date
    ) -> list[TodoRow]:
        return list(self._by_user_day.get((user_id, today), []))


@dataclass
class MemoryCharacterQueryRepo:
    """In-memory CharacterQueryPort."""

    _by_user: dict[str, list[CharacterRow]] = field(default_factory=dict)

    def seed(self, user_id: str, rows: list[CharacterRow]) -> None:
        self._by_user[user_id] = list(rows)

    async def list_active(self, *, user_id: str) -> list[CharacterRow]:
        return list(self._by_user.get(user_id, []))


@dataclass
class MemoryQuestPersistenceRepo:
    """In-memory QuestPersistencePort. `inserted` accumulates all calls."""

    inserted: list[GeneratedQuest] = field(default_factory=list)

    async def insert_many(self, *, quests: list[GeneratedQuest]) -> None:
        self.inserted.extend(quests)
