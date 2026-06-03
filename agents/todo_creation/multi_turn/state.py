from __future__ import annotations

from datetime import date, datetime
from typing import TypedDict

from agents.todo_creation.schemas import MultiGenerateInput, TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn


class MultiTurnGraphState(TypedDict, total=False):
    # required (pipeline populates)
    message: str
    today: date
    now: datetime
    user_id: str

    # conversation
    history: list[Turn]
    sufficiency: bool | None
    missing_aspects: list[str]
    parsed_goal: ParsedGoal | None
    follow_up_question: str | None

    # plan (P1: plan_generator 구현 시 채워짐)
    plan: list[PlanDay] | None
    summary_text: str | None

    # output
    todos: list[TaskCandidate] | None
    calendar_events: list[TaskCandidate] | None
