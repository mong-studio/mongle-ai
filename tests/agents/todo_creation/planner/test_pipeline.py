from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.planner.pipeline import PlannerPorts, get_debug_state, run
from agents.todo_creation.schemas import (
    FollowUpResult,
    CandidatesResult,
    PlannerInput,
    OutOfScopeResult,
    SplitResult,
    TaskCandidate,
)
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


@dataclass
class _FakeLLM:
    sufficiency_responses: list[tuple[bool, list[str], ParsedGoal | None]] = field(
        default_factory=list
    )
    follow_up_responses: list[str] = field(default_factory=list)
    plan_responses: list[tuple[str, list[PlanDay]]] = field(default_factory=list)
    seen_history: list[list[Turn]] = field(default_factory=list)
    seen_parsed_goals: list[ParsedGoal] = field(default_factory=list)
    goal_tag_response: str = "계획"

    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date, user_profile_memory=None
    ) -> tuple[bool, list[str], ParsedGoal]:
        self.seen_history.append(history)
        return self.sufficiency_responses.pop(0)

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str:
        return self.follow_up_responses.pop(0)

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        self.seen_parsed_goals.append(parsed_goal)
        if self.plan_responses:
            return self.plan_responses.pop(0)
        return "", []

    async def generate_goal_tag(
        self, *, parsed_goal: ParsedGoal, history: list[Turn]
    ) -> str:
        return str(parsed_goal.get("goal_tag") or self.goal_tag_response)

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        return plan

    async def split_tasks(self, *, prompt: str, today: date):
        return SplitResult(intent="plan", tasks=[])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 5, 27)
_NOW = datetime(2026, 5, 27, 9, 0)


def _input(message: str = "프로젝트 완성하기", thread_id: str | None = None) -> PlannerInput:
    return PlannerInput(
        user_id="u1",
        message=message,
        today=_TODAY,
        thread_id=thread_id,
    )


def _ports(llm: _FakeLLM) -> PlannerPorts:
    return PlannerPorts(llm=llm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_insufficient_on_first_call_returns_follow_up() -> None:
    llm = _FakeLLM(
        sufficiency_responses=[(False, ["deadline"], None)],
        follow_up_responses=["언제까지 완료하실 건가요?"],
    )
    result = await run(_input(), ports=_ports(llm), now=_NOW)

    assert isinstance(result, FollowUpResult)
    assert result.question == "언제까지 완료하실 건가요?"
    assert result.missing_aspects == ["deadline"]
    assert result.thread_id  # non-empty


async def test_resume_after_follow_up_returns_candidates_result() -> None:
    goal: ParsedGoal = {"goal_text": "프로젝트 완성하기"}
    llm = _FakeLLM(
        sufficiency_responses=[
            (False, ["deadline"], None),  # first turn: not sufficient
            (True, [], goal),             # second turn: sufficient after answer
        ],
        # LangGraph re-executes the node from the top on resume, so
        # generate_follow_up_question is called once to produce the interrupt
        # value, then once more when the node re-runs before interrupt() returns.
        follow_up_responses=["언제까지 완료하실 건가요?", "언제까지 완료하실 건가요?"],
    )

    first = await run(_input(), ports=_ports(llm), now=_NOW)
    assert isinstance(first, FollowUpResult)

    second = await run(
        _input(message="이번 주 금요일까지요", thread_id=first.thread_id),
        ports=_ports(llm),
        now=_NOW,
    )
    assert isinstance(second, CandidatesResult)
    assert second.thread_id == first.thread_id


async def test_sufficient_immediately_returns_candidates_result() -> None:
    goal: ParsedGoal = {"goal_text": "코테 준비", "goal_tag": "코테"}
    llm = _FakeLLM(
        sufficiency_responses=[(True, [], goal)],
    )
    result = await run(_input(message="이번 주까지 코테 준비"), ports=_ports(llm), now=_NOW)

    assert isinstance(result, CandidatesResult)
    assert result.thread_id
    assert llm.seen_history[0] == [{"role": "user", "content": "이번 주까지 코테 준비"}]


async def test_out_of_scope_returns_guidance() -> None:
    llm = _FakeLLM(
        sufficiency_responses=[
            (False, [], {"intent": "out_of_scope", "goal_text": ""})
        ],
    )

    result = await run(_input(message="오늘 날씨가 뭐야?"), ports=_ports(llm), now=_NOW)

    assert isinstance(result, OutOfScopeResult)
    assert "이장님" in result.message


async def test_revision_after_generated_plan_uses_previous_plan() -> None:
    first_task = TaskCandidate(title="개념 복습", due_date=_TODAY)
    second_task = TaskCandidate(title="실전 문제", due_date=_TODAY)
    goal: ParsedGoal = {"goal_text": "코테 준비", "goal_tag": "코테"}
    llm = _FakeLLM(
        sufficiency_responses=[(True, [], goal)],
        plan_responses=[
            ("첫 플랜", [{"date": _TODAY, "tasks": [first_task]}]),
            ("수정 플랜", [{"date": _TODAY, "tasks": [second_task]}]),
        ],
    )

    first = await run(_input(message="3일 뒤 코테 준비"), ports=_ports(llm), now=_NOW)
    assert isinstance(first, CandidatesResult)

    second = await run(
        _input(message="실전 문제를 더 많이 넣어줘", thread_id=first.thread_id),
        ports=_ports(llm),
        now=_NOW,
    )

    assert isinstance(second, CandidatesResult)
    assert second.todos[0].title == second_task.title
    assert second.todos[0].tags == ["코테"]
    assert llm.seen_parsed_goals[-1]["revision_request"] == "실전 문제를 더 많이 넣어줘"
    assert llm.seen_parsed_goals[-1]["previous_plan"]


async def test_acceptance_after_generated_plan_returns_previous_candidates_without_llm() -> None:
    task = TaskCandidate(title="개념 복습", due_date=_TODAY)
    goal: ParsedGoal = {"goal_text": "코테 준비", "goal_tag": "코테"}
    llm = _FakeLLM(
        sufficiency_responses=[(True, [], goal)],
        plan_responses=[("첫 플랜", [{"date": _TODAY, "tasks": [task]}])],
    )

    first = await run(_input(message="3일 뒤 코테 준비"), ports=_ports(llm), now=_NOW)
    assert isinstance(first, CandidatesResult)

    second = await run(
        _input(message="그렇게 할게", thread_id=first.thread_id),
        ports=_ports(llm),
        now=_NOW,
    )

    assert isinstance(second, CandidatesResult)
    assert second.todos == first.todos
    assert second.summary_text == first.summary_text
    assert len(llm.seen_parsed_goals) == 1
    assert llm.seen_parsed_goals[0]["goal_tag"] == "코테"


async def test_debug_state_exposes_thread_memory_summary() -> None:
    task = TaskCandidate(title="개념 복습", due_date=_TODAY)
    goal: ParsedGoal = {"goal_text": "코테 준비", "goal_tag": "코테"}
    llm = _FakeLLM(
        sufficiency_responses=[(True, [], goal)],
        plan_responses=[("요약", [{"date": _TODAY, "tasks": [task]}])],
    )
    ports = _ports(llm)

    result = await run(_input(message="3일 뒤 코테 준비"), ports=ports, now=_NOW)
    assert isinstance(result, CandidatesResult)
    state = get_debug_state(thread_id=result.thread_id, ports=ports)

    assert state["history_turns"] >= 1
    assert state["parsed_goal"]["goal_tag"] == "코테"
    assert state["has_previous_plan"] is True
    assert state["todo_count"] == 1


async def test_validation_error_propagates() -> None:
    llm = _FakeLLM()
    bad = PlannerInput.model_construct(
        user_id="u1", message="hello", today=_TODAY, thread_id=None
    )
    with pytest.raises(ValidationError):
        await run(bad, ports=_ports(llm), now=_NOW)
