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


from agents.quest_generation import pipeline as quest_pipeline
from agents.quest_generation.protocols import LLMPort
from agents.quest_generation.schemas import (
    Character,
    QuestGenerationInput,
    TodoRef,
)


class QuestDispatchAdapter:
    """Implements `QuestDispatchPort` (from agents/todo_creation/protocols.py).

    Bridges the commit pipeline's fire-and-forget `dispatch(user_id)` call to
    the quest_generation agent: fetches today's pending TODOs and the user's
    active characters, runs the agent, then persists generated quests.

    Known limitations (see docs/superpowers/specs/2026-05-25-quest-generation-design.md §11):
      - quota slot leak (1 dispatch increments by 1 in quest_gate regardless of N quests)
      - skipped items are only logged; no back-off queue
      - HUD/notification events are not emitted here
    """

    def __init__(
        self,
        *,
        todo_repo: TodoQueryPort,
        character_repo: CharacterQueryPort,
        quest_repo: QuestPersistencePort,
        llm: LLMPort,
        today_fn: Callable[[], date],
    ) -> None:
        self._todo_repo = todo_repo
        self._character_repo = character_repo
        self._quest_repo = quest_repo
        self._llm = llm
        self._today_fn = today_fn

    async def dispatch(self, *, user_id: str) -> None:
        today = self._today_fn()
        todo_rows = await self._todo_repo.list_today_pending(user_id=user_id, today=today)
        char_rows = await self._character_repo.list_active(user_id=user_id)

        if not todo_rows or not char_rows:
            return

        agent_input = QuestGenerationInput(
            todos=[TodoRef(todo_id=r.todo_id) for r in todo_rows],
            characters=[
                Character(
                    character_id=r.character_id,
                    name=r.name,
                    personality=r.personality,
                    speech_style=r.speech_style,
                    appearance_keywords=[r.appearance_description]
                    if r.appearance_description
                    else [],
                )
                for r in char_rows
            ],
            remaining_daily_quota=len(todo_rows),
        )

        result = await quest_pipeline.run(
            agent_input, ports=quest_pipeline.Ports(llm=self._llm)
        )

        if result.generated:
            await self._quest_repo.insert_many(quests=result.generated)

        if result.skipped:
            logger.warning(
                "quest_dispatch partial: user=%s generated=%d skipped=%d",
                user_id,
                len(result.generated),
                len(result.skipped),
            )
