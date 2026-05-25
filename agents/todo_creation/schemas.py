from __future__ import annotations

from datetime import date
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
    """후보 확정/검토 단계 응답 (single + multi 공통).

    `thread_id` 는 single 의 1-shot 호출에서도 발급된 값을 echo 한다.
    기존 single_turn date_router 호출 시 default `""` 로 호환.
    `summary_text` 는 multi 의 plan_generator 결과(C3 ≤ 1500자)만 채움.
    """

    kind: Literal["candidates"] = "candidates"
    thread_id: str = ""
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]
    summary_text: str | None = None


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


# === Unified single/multi generate I/O ===


class SingleGenerateInput(BaseModel):
    mode: Literal["single"] = "single"
    user_id: Annotated[str, Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=1, max_length=200)]
    today: date


class MultiGenerateInput(BaseModel):
    mode: Literal["multi"] = "multi"
    user_id: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1, max_length=600)]
    today: date
    thread_id: str | None = None  # 첫 호출은 None, 서버가 발급


GenerateInput = Annotated[
    SingleGenerateInput | MultiGenerateInput,
    Field(discriminator="mode"),
]


class FollowUpResult(BaseModel):
    """multi 의 추가 질문 응답 (interrupt 발생 시)."""

    kind: Literal["follow_up"] = "follow_up"
    thread_id: str
    question: Annotated[str, Field(max_length=300)]
    missing_aspects: list[str]


TurnResult = Annotated[
    GenerateResult | FollowUpResult,
    Field(discriminator="kind"),
]


