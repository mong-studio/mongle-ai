from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn


class PlannerGraphState(TypedDict, total=False):
    # required (pipeline populates)
    message: str
    today: date
    now: datetime
    user_id: str

    # conversation
    history: list[Turn]
    memory_summary: dict | None
    recent_turns: list[Turn]
    user_profile_memory: dict | None
    personalization_patch: dict | None
    revision_request: str | None
    sufficiency: bool | None
    missing_aspects: list[str]
    parsed_goal: ParsedGoal | None
    follow_up_question: str | None
    out_of_scope_message: str | None

    # plan (P1: plan_generator 구현 시 채워짐)
    plan: list[PlanDay] | None
    summary_text: str | None

    # critic 루프 (LLM-Modulo): 재생성 횟수 바운드 + 라우팅 플래그
    critique_retries: int
    needs_revision: bool

    # output
    todos: list[TaskCandidate] | None
    calendar_events: list[TaskCandidate] | None
