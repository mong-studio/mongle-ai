from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from agents.todo_creation.schemas import (
    CommitResult,
    TaskCandidate,
)


class LLMPort(Protocol):
    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]: ...


class TodoRepositoryPort(Protocol):
    async def find_by_idempotency_key(
        self, *, user_id: str, key: UUID
    ) -> CommitResult | None: ...

    async def save(
        self,
        *,
        user_id: str,
        idempotency_key: UUID,
        todos: list[TaskCandidate],
        events: list[TaskCandidate],
    ) -> tuple[list[UUID], list[UUID]]: ...


class QuestCounterPort(Protocol):
    async def incr_if_under_limit(
        self, *, user_id: str, day_kst: date, limit: int
    ) -> bool: ...


class QuestDispatchPort(Protocol):
    async def dispatch(self, *, user_id: str) -> None: ...
