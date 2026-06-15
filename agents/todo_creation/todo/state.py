from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from agents.todo_creation.schemas import CandidatesResult, OutOfScopeResult, TodoInput, TaskCandidate


class GenerateGraphState(TypedDict, total=False):
    # required
    input: TodoInput
    now: datetime
    # produced
    intent: Literal["plan", "out_of_scope"] | None
    split_tasks: list[TaskCandidate] | None
    result: CandidatesResult | OutOfScopeResult | None
    error: Exception | None
