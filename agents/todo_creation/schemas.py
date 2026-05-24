from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SingleTurnInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=1, max_length=200)]
    today: date


class TaskCandidate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    due_date: date
    time_hint: str | None = None
    tags: Annotated[list[str], Field(default_factory=list)]


class GenerateResult(BaseModel):
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]


class CommitInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    idempotency_key: UUID
    today: date
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]

    @model_validator(mode="after")
    def _check_size(self) -> CommitInput:
        total = len(self.todos) + len(self.calendar_events)
        if total == 0:
            raise ValueError("empty payload")
        if total > 50:
            raise ValueError("too many items (max 50)")
        return self


class CommitResult(BaseModel):
    todo_ids: list[UUID]
    event_ids: list[UUID]
    quest_distribution_triggered: bool
