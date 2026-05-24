from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from uuid import UUID

from agents.todo_creation.schemas import CommitInput, TaskCandidate


class CommitGraphState(TypedDict, total=False):
    # required
    input: CommitInput
    now: datetime
    # produced
    re_routed_todos: list[TaskCandidate] | None
    re_routed_events: list[TaskCandidate] | None
    idempotent_hit: bool | None
    todo_ids: list[UUID] | None
    event_ids: list[UUID] | None
    quest_triggered: bool | None
    error: Exception | None
