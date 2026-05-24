from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from agents.todo_creation.schemas import (
    AgentDecision,
    ChatMessage,
    CommitResult,
    ParsedGoal,
    PlanDraft,
    PlannerJudgment,
    SessionState,
    TaggedPlan,
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


class MultiTurnLLMPort(Protocol):
    async def judge_planner(
        self, *, history: list[ChatMessage], previous_goal: ParsedGoal | None, today: date
    ) -> PlannerJudgment: ...

    async def generate_follow_up(
        self, *, missing_aspects: list[str], history: list[ChatMessage]
    ) -> str: ...

    async def generate_plan(
        self,
        *,
        parsed_goal: ParsedGoal,
        today: date,
        edit_instructions: str | None,
    ) -> PlanDraft: ...

    async def tag_plan(
        self, *, plan_draft: PlanDraft, parsed_goal: ParsedGoal
    ) -> TaggedPlan: ...

    async def edit_agent_step(
        self, *, history: list[ChatMessage], current_plan: TaggedPlan
    ) -> AgentDecision: ...


class SessionStorePort(Protocol):
    async def load(self, *, session_id: str) -> SessionState | None: ...

    async def save(self, *, state: SessionState) -> None: ...

    async def delete(self, *, session_id: str) -> None: ...
