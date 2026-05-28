from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from agents.todo_creation.exceptions import ValidationError
from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts, run
from agents.todo_creation.schemas import FollowUpResult, GenerateResult, MultiGenerateInput
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

    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date
    ) -> tuple[bool, list[str], ParsedGoal]:
        return self.sufficiency_responses.pop(0)

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str:
        return self.follow_up_responses.pop(0)

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        return "", []

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        return plan

    async def split_tasks(self, *, prompt: str, today: date):
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 5, 27)
_NOW = datetime(2026, 5, 27, 9, 0)


def _input(message: str = "프로젝트 완성하기", thread_id: str | None = None) -> MultiGenerateInput:
    return MultiGenerateInput(
        user_id="u1",
        message=message,
        today=_TODAY,
        thread_id=thread_id,
    )


def _ports(llm: _FakeLLM) -> MultiTurnPorts:
    return MultiTurnPorts(llm=llm)


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


async def test_resume_after_follow_up_returns_generate_result() -> None:
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
    assert isinstance(second, GenerateResult)
    assert second.thread_id == first.thread_id


async def test_sufficient_immediately_returns_generate_result() -> None:
    goal: ParsedGoal = {"goal_text": "코테 준비"}
    llm = _FakeLLM(
        sufficiency_responses=[(True, [], goal)],
    )
    result = await run(_input(message="이번 주까지 코테 준비"), ports=_ports(llm), now=_NOW)

    assert isinstance(result, GenerateResult)
    assert result.thread_id


async def test_validation_error_propagates() -> None:
    llm = _FakeLLM()
    bad = MultiGenerateInput.model_construct(
        user_id="u1", message="hello", today=_TODAY, thread_id=None
    )
    with pytest.raises(ValidationError):
        await run(bad, ports=_ports(llm), now=_NOW)
