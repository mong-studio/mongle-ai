from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from langgraph.graph import END

from agents.todo_creation.planner.nodes.critic import (
    _detect_overload,
    critic_node,
    route_after_critic,
)
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

_TODAY = date(2026, 5, 27)
_MAJOR = {"ok": False, "issues": [{"severity": "major", "category": "load",
          "detail": "하루 과부하", "suggested_fix": "이틀로 쪼개기", "day": _TODAY.isoformat()}]}
_CLEAN = {"ok": True, "issues": []}


@dataclass
class _FakeLLM:
    verdict: dict = field(default_factory=lambda: dict(_CLEAN))
    critique_calls: int = 0
    last_overloaded: list | None = None

    async def critique_plan(
        self, *, parsed_goal, plan, today, overloaded_days=None
    ) -> dict:
        self.critique_calls += 1
        self.last_overloaded = overloaded_days
        return self.verdict


@dataclass
class _Ports:
    llm: _FakeLLM


def _config(llm: _FakeLLM) -> dict:
    return {"configurable": {"ports": _Ports(llm=llm)}}


def _plan(*difficulties: int) -> list[PlanDay]:
    tasks = [
        TaskCandidate(title=f"t{i}", due_date=_TODAY, difficulty=d)
        for i, d in enumerate(difficulties)
    ]
    return [{"date": _TODAY, "tasks": tasks}]


def _state(
    plan: list[PlanDay],
    *,
    parsed_goal: ParsedGoal | None = None,
    retries: int = 0,
) -> dict:
    return {
        "today": _TODAY,
        "plan": plan,
        "parsed_goal": parsed_goal or {"goal_tag": "목표"},
        "critique_retries": retries,
    }


def test_detect_overload_flags_only_days_over_cap() -> None:
    over = _plan(3, 3)  # Σ6 > 5
    ok = _plan(2, 2)  # Σ4 <= 5
    assert _detect_overload(over) == [_TODAY.isoformat()]
    assert _detect_overload(ok) == []


async def test_major_issue_triggers_revision_and_increments_retry() -> None:
    llm = _FakeLLM(verdict=dict(_MAJOR))
    out = await critic_node(_state(_plan(1)), _config(llm))
    assert out["needs_revision"] is True
    assert out["critique_retries"] == 1
    pg = out["parsed_goal"]
    assert pg["previous_plan"] == _plan(1)
    assert pg["revision_request"]  # non-empty backprompt text


async def test_clean_verdict_ends_without_revision() -> None:
    llm = _FakeLLM(verdict=dict(_CLEAN))
    out = await critic_node(_state(_plan(1)), _config(llm))
    assert out["needs_revision"] is False
    assert "parsed_goal" not in out  # 수정 채널 안 건드림
    assert llm.critique_calls == 1


async def test_retry_budget_exhausted_does_not_revise() -> None:
    llm = _FakeLLM(verdict=dict(_MAJOR))
    out = await critic_node(_state(_plan(1), retries=1), _config(llm))
    assert out["needs_revision"] is False  # retries<1 아님 → 재생성 안 함


async def test_routine_plan_skips_critic() -> None:
    llm = _FakeLLM(verdict=dict(_MAJOR))
    state = _state(_plan(3, 3), parsed_goal={"plan_kind": "routine"})
    out = await critic_node(state, _config(llm))
    assert out["needs_revision"] is False
    assert llm.critique_calls == 0  # routine 은 코드 전개라 비평 미경유


async def test_empty_plan_skips_critic() -> None:
    llm = _FakeLLM(verdict=dict(_MAJOR))
    out = await critic_node(_state([]), _config(llm))
    assert out["needs_revision"] is False
    assert llm.critique_calls == 0


async def test_overloaded_days_passed_to_critic() -> None:
    llm = _FakeLLM(verdict=dict(_CLEAN))
    await critic_node(_state(_plan(3, 3)), _config(llm))
    assert llm.last_overloaded == [_TODAY.isoformat()]


def _exam_leak_plan() -> list[PlanDay]:
    """비-시험 목표에 시험 task 가 섞인 plan (LoRA 과적합 누수 재현)."""
    return [
        {
            "date": _TODAY,
            "tasks": [
                TaskCandidate(title="수영 훈련", due_date=_TODAY, difficulty=2),
                TaskCandidate(title="정처기 신청", due_date=_TODAY, difficulty=1),
            ],
        }
    ]


async def test_exam_contamination_forces_revision_even_if_llm_says_ok() -> None:
    """LLM critic 이 통과시켜도 비-시험 목표에 시험 task 가 섞이면 코드가 재생성을 강제한다."""
    llm = _FakeLLM(verdict=dict(_CLEAN))
    state = _state(_exam_leak_plan(), parsed_goal={"goal_tag": "철인삼종", "plan_kind": "lifestyle"})
    out = await critic_node(state, _config(llm))
    assert out["needs_revision"] is True
    assert "정처기 신청" in out["parsed_goal"]["revision_request"]


async def test_exam_goal_allows_exam_tasks() -> None:
    """plan_kind=exam 이면 시험 task 는 정당하므로 누수로 보지 않는다."""
    llm = _FakeLLM(verdict=dict(_CLEAN))
    state = _state(_exam_leak_plan(), parsed_goal={"goal_tag": "정처기", "plan_kind": "exam"})
    out = await critic_node(state, _config(llm))
    assert out["needs_revision"] is False


def test_route_sends_to_generator_only_when_revision_needed() -> None:
    assert route_after_critic({"needs_revision": True}) == "plan_generator"
    assert route_after_critic({"needs_revision": False}) == END
    assert route_after_critic({}) == END
