from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1)]


class ParsedGoal(BaseModel):
    goal_type: str | None = None
    deadline: date | None = None
    daily_capacity: str | None = None
    target_level: str | None = None
    extras: Annotated[dict[str, str], Field(default_factory=dict)]


class PlannerJudgment(BaseModel):
    is_sufficient: bool
    missing_aspects: Annotated[list[str], Field(default_factory=list)]
    parsed_goal: ParsedGoal


class Task(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=80)]
    detail: str | None = None
    time_hint: str | None = None
    tags: Annotated[list[str], Field(default_factory=list)]


class Day(BaseModel):
    date: date
    tasks: Annotated[list[Task], Field(default_factory=list)]


class PlanDraft(BaseModel):
    summary_text: Annotated[str, Field(min_length=1)]
    days: Annotated[list[Day], Field(default_factory=list)]


class TaggedPlan(BaseModel):
    summary_text: Annotated[str, Field(min_length=1)]
    days: Annotated[list[Day], Field(default_factory=list)]


class MultiTurnInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    session_id: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1, max_length=600)]
    today: date


class AgentDecision(BaseModel):
    tool_name: Literal["regenerate_plan", "confirm"]
    tool_args: Annotated[dict[str, str], Field(default_factory=dict)]


class TurnResult(BaseModel):
    kind: Literal["question", "plan", "committed"]
    question: str | None = None
    plan: TaggedPlan | None = None
    commit_result: CommitResult | None = None


class SessionState(BaseModel):
    session_id: Annotated[str, Field(min_length=1)]
    user_id: Annotated[str, Field(min_length=1)]
    phase: Literal["gathering", "reviewing"]
    history: Annotated[list[ChatMessage], Field(default_factory=list)]
    parsed_goal: ParsedGoal | None = None
    current_plan: TaggedPlan | None = None
    created_at: datetime
    updated_at: datetime
