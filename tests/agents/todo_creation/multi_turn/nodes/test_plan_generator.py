from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from agents.todo_creation.multi_turn.nodes.plan_generator import plan_generator_node
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

_TODAY = date(2026, 5, 27)
_FUTURE = date(2026, 5, 30)


@dataclass
class _FakeLLM:
    plan_response: tuple[str, list[PlanDay]] = field(
        default_factory=lambda: ("", [])
    )
    tag_response: list[PlanDay] | None = None

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        return self.plan_response

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        return self.tag_response if self.tag_response is not None else plan

    async def judge_sufficiency(self, **_): ...
    async def generate_follow_up_question(self, **_): ...
    async def split_tasks(self, **_): ...


@dataclass
class _Ports:
    llm: _FakeLLM


def _config(llm: _FakeLLM) -> dict:
    return {"configurable": {"ports": _Ports(llm=llm)}}


def _state(parsed_goal: ParsedGoal | None = None) -> dict:
    return {"today": _TODAY, "parsed_goal": parsed_goal}


async def test_splits_today_tasks_into_todos() -> None:
    task = TaskCandidate(title="코테", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("오늘 코테 준비", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == [task]
    assert result["calendar_events"] == []
    assert result["summary_text"] == "오늘 코테 준비"


async def test_splits_future_tasks_into_calendar_events() -> None:
    task = TaskCandidate(title="발표", due_date=_FUTURE)
    plan: list[PlanDay] = [{"date": _FUTURE, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("발표 준비", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == []
    assert result["calendar_events"] == [task]


async def test_mixed_plan_splits_correctly() -> None:
    today_task = TaskCandidate(title="코테", due_date=_TODAY)
    future_task = TaskCandidate(title="발표", due_date=_FUTURE)
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [today_task]},
        {"date": _FUTURE, "tasks": [future_task]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == [today_task]
    assert result["calendar_events"] == [future_task]


async def test_empty_plan_returns_empty_lists() -> None:
    llm = _FakeLLM(plan_response=("", []))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == []
    assert result["calendar_events"] == []
    assert result["plan"] == []
