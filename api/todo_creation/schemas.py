from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from agents.todo_creation.schemas import CommitInput


class CommitRequest(BaseModel):
    input: CommitInput
    remaining_daily_quota: Annotated[int, Field(ge=0)]
