from __future__ import annotations

from datetime import datetime
from typing import NotRequired, TypedDict
from uuid import UUID

from agents.todo_creation.schemas import CommitInput, TaskCandidate


class CommitGraphState(TypedDict):
    input: CommitInput
    now: datetime
    re_routed_todos: NotRequired[list[TaskCandidate] | None]
    re_routed_events: NotRequired[list[TaskCandidate] | None]
    idempotent_hit: NotRequired[bool | None]
    todo_ids: NotRequired[list[UUID] | None]
    event_ids: NotRequired[list[UUID] | None]
    quest_triggered: NotRequired[bool | None]
    error: NotRequired[Exception | None]
