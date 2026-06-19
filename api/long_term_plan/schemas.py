from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.todo_creation.schemas import PlannerInput


class LongTermPlanRequest(BaseModel):
    """장기 계획 생성 요청. 큰 목표 하나(goal)를 받아 일자별 plan 으로 분해한다.

    멀티턴: 마감일 등 정보가 부족하면 follow_up 으로 되묻는다. 응답의 thread_id 를
    다음 요청에 넣어 같은 대화를 이어간다(기존 planner /v1/todo/chat 과 동일 규약).
    """

    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[str, Field(min_length=1)]
    goal: Annotated[str, Field(min_length=1, max_length=600)]
    today: date
    thread_id: str | None = None
    user_profile_memory: dict[str, Any] | None = None

    @field_validator("thread_id", mode="before")
    @classmethod
    def _normalize_thread_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def to_planner_input(self) -> PlannerInput:
        return PlannerInput(
            user_id=self.user_id,
            message=self.goal,
            today=self.today,
            thread_id=self.thread_id,
            user_profile_memory=self.user_profile_memory,
        )
