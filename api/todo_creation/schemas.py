from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from agents.todo_creation.schemas import CommitPayload


class CommitInput(BaseModel):
    input: CommitPayload
    remaining_daily_quota: Annotated[int, Field(ge=0)]


class TodoJobRef(BaseModel):
    """submit(202) 응답의 result — 폴링에 쓸 job_id."""

    job_id: str
