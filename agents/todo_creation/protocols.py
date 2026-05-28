from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from agents.todo_creation.schemas import (
    CommitResult,
    TaskCandidate,
)
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn


class LLMPort(Protocol):
    # single
    async def split_tasks(
        self, *, prompt: str, today: date
    ) -> list[TaskCandidate]: ...

    # multi
    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date
    ) -> tuple[bool, list[str], ParsedGoal]: ...

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str: ...

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]: ...

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]: ...


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

    async def decr(self, *, user_id: str, day_kst: date) -> None: ...


class QuestDispatchPort(Protocol):
    async def dispatch(self, *, user_id: str) -> None: ...
