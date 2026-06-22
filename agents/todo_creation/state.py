"""Unified state for single/multi `generate_graph`.

single 경로는 `prompt` / `split_tasks` 만 사용하고,
multi 경로는 `message` / `history` / `parsed_goal` / `plan` / `summary_text` 등을 사용한다.
양 경로는 `todos` / `calendar_events` 키로 fan-in 한 뒤 `date_router` → END.

`turn_count` 는 두지 않는다 (MAX_TURN 미적용; `len(history)/2` 로 도출 가능).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, TypedDict

from agents.todo_creation.schemas import TaskCandidate


class Turn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ParsedGoal(TypedDict, total=False):
    intent: Literal["plan", "out_of_scope"]
    plan_kind: Literal["exam", "routine", "vague_goal", "lifestyle"]
    slots: dict[str, Any]
    goal_text: str
    goal_tag: str
    deadline: date | None
    daily_capacity_minutes: int | None
    revision_request: str | None
    previous_plan: list[PlanDay]
    user_profile_memory: dict[str, Any]
    personalization_patch: dict[str, Any]


class PlanDay(TypedDict):
    date: date
    tasks: list[TaskCandidate]


class GenerateState(TypedDict, total=False):
    # required (entry 가 채움)
    mode: Literal["single", "multi"]
    user_id: str
    today: date
    now: datetime

    # single path
    prompt: str
    split_tasks: list[TaskCandidate]

    # multi path
    message: str
    history: list[Turn]
    memory_summary: dict[str, Any] | None
    recent_turns: list[Turn]
    revision_request: str | None
    parsed_goal: ParsedGoal | None
    sufficiency: bool | None
    missing_aspects: list[str]
    follow_up_question: str | None
    plan: list[PlanDay] | None
    summary_text: str | None

    # both — date_router 결과
    todos: list[TaskCandidate]
    calendar_events: list[TaskCandidate]

    # error
    error: Exception | None
