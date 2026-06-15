from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TodoInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    prompt: Annotated[str, Field(min_length=1, max_length=200)]
    today: date


class TaskCandidate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=20)]
    due_date: date
    tags: Annotated[list[str], Field(default_factory=list)]


class CandidatesResult(BaseModel):
    """후보 확정/검토 단계 응답 (single + multi 공통).

    `thread_id` 는 single 의 1-shot 호출에서도 발급된 값을 echo 한다.
    기존 todo date_router 호출 시 default `""` 로 호환.
    `summary_text` 는 multi 의 plan_generator 결과(C3 ≤ 1500자)만 채움.
    """

    kind: Literal["candidates"] = "candidates"
    thread_id: str = ""
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]
    summary_text: str | None = None
    profile_memory_patch: dict[str, Any] | None = None


class CommitPayload(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    idempotency_key: UUID
    today: date
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]

    @model_validator(mode="after")
    def _check_size(self) -> CommitPayload:
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


# === Multi-turn generate I/O ===


class PlannerInput(BaseModel):
    user_id: Annotated[str, Field(min_length=1)]
    message: Annotated[str, Field(min_length=1, max_length=600)]
    today: date
    thread_id: str | None = None
    user_profile_memory: dict[str, Any] | None = None

    @field_validator("thread_id", mode="before")
    @classmethod
    def _normalize_thread_id(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value


class FollowUpResult(BaseModel):
    """multi 의 추가 질문 응답 (interrupt 발생 시)."""

    kind: Literal["follow_up"] = "follow_up"
    thread_id: str
    question: Annotated[str, Field(max_length=300)]
    missing_aspects: list[str]


class OutOfScopeResult(BaseModel):
    """multi 플래너 범위를 벗어난 입력에 대한 안내 응답."""

    kind: Literal["out_of_scope"] = "out_of_scope"
    thread_id: str
    message: str


PlannerResult = Annotated[
    CandidatesResult | FollowUpResult | OutOfScopeResult,
    Field(discriminator="kind"),
]


# === Single-turn types ===

OUT_OF_SCOPE_MESSAGE = (
    "나는 목표를 TODO랑 일정으로 차근차근 나눠주는 이장님이야. "
    "준비할 일이나 이루고 싶은 목표를 말해주면 같이 계획을 짜볼게."
)


class SplitResult(BaseModel):
    """단일턴 split_tasks 의 출력: 범위 판단(intent) + 후보 목록."""

    model_config = ConfigDict(frozen=True)
    intent: Literal["plan", "out_of_scope"]
    tasks: list[TaskCandidate]


TodoResult = Annotated[
    CandidatesResult | OutOfScopeResult,
    Field(discriminator="kind"),
]
