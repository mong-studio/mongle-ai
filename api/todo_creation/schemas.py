from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from agents.todo_creation.schemas import CommitPayload


class CommitInput(BaseModel):
    input: CommitPayload
    remaining_daily_quota: Annotated[int, Field(ge=0)]
