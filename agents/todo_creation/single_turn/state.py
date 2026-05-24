from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from agents.todo_creation.schemas import GenerateResult, SingleTurnInput, TaskCandidate


class GenerateGraphState(TypedDict, total=False):
    # required
    input: SingleTurnInput
    now: datetime
    # produced
    split_tasks: list[TaskCandidate] | None
    result: GenerateResult | None
    error: Exception | None
