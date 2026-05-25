from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from agents.todo_creation.schemas import (
    ChatMessage,
    MultiTurnInput,
    ParsedGoal,
    PlanDraft,
    PlannerJudgment,
    TaggedPlan,
    TurnResult,
)


class MultiTurnGraphState(TypedDict, total=False):
    input: MultiTurnInput
    now: datetime

    phase: Literal["gathering", "reviewing"]
    history: list[ChatMessage]
    parsed_goal: ParsedGoal | None
    current_plan: TaggedPlan | None

    judgment: PlannerJudgment | None
    follow_up_question: str | None

    edit_instructions: str | None
    confirmed: bool | None

    plan_draft: PlanDraft | None

    result: TurnResult | None
    error: Exception | None
