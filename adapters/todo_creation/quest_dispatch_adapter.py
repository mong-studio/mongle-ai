from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Protocol
from uuid import UUID

from agents.quest_generation.schemas import GeneratedQuest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TodoRow:
    todo_id: UUID


@dataclass(frozen=True)
class CharacterRow:
    character_id: UUID
    name: str
    personality: str
    speech_style: str
    appearance_description: str | None


class TodoQueryPort(Protocol):
    async def list_today_pending(
        self, *, user_id: str, today: date
    ) -> list[TodoRow]: ...


class CharacterQueryPort(Protocol):
    async def list_active(
        self, *, user_id: str
    ) -> list[CharacterRow]: ...


class QuestPersistencePort(Protocol):
    async def insert_many(
        self, *, quests: list[GeneratedQuest]
    ) -> None: ...
