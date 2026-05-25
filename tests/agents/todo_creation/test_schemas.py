from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from agents.todo_creation.schemas import (
    CommitInput,
    CommitResult,
    GenerateResult,
    SingleTurnInput,
    TaskCandidate,
)


# ---- SingleTurnInput ----

def test_single_turn_input_accepts_200_char_prompt() -> None:
    SingleTurnInput(user_id="u1", prompt="가" * 200, today=date(2026, 5, 24))


def test_single_turn_input_rejects_201_char_prompt() -> None:
    with pytest.raises(PydanticValidationError):
        SingleTurnInput(user_id="u1", prompt="가" * 201, today=date(2026, 5, 24))


def test_single_turn_input_rejects_empty_prompt() -> None:
    with pytest.raises(PydanticValidationError):
        SingleTurnInput(user_id="u1", prompt="", today=date(2026, 5, 24))


def test_single_turn_input_rejects_empty_user_id() -> None:
    with pytest.raises(PydanticValidationError):
        SingleTurnInput(user_id="", prompt="할 일", today=date(2026, 5, 24))


# ---- TaskCandidate ----

def test_task_candidate_defaults() -> None:
    t = TaskCandidate(title="코테", due_date=date(2026, 5, 24))
    assert t.time_hint is None
    assert t.tags == []


def test_task_candidate_rejects_empty_title() -> None:
    with pytest.raises(PydanticValidationError):
        TaskCandidate(title="", due_date=date(2026, 5, 24))


def test_task_candidate_rejects_title_over_80_chars() -> None:
    with pytest.raises(PydanticValidationError):
        TaskCandidate(title="x" * 81, due_date=date(2026, 5, 24))


# ---- GenerateResult ----

def test_generate_result_allows_empty_lists() -> None:
    GenerateResult(todos=[], calendar_events=[])


# ---- CommitInput ----

def _ok_task(d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title="할 일", due_date=d)


def test_commit_input_accepts_normal_payload() -> None:
    CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=[_ok_task()],
        calendar_events=[],
    )


def test_commit_input_rejects_total_over_50() -> None:
    too_many = [_ok_task() for _ in range(51)]
    with pytest.raises(PydanticValidationError):
        CommitInput(
            user_id="u1",
            idempotency_key=uuid4(),
            today=date(2026, 5, 24),
            todos=too_many,
            calendar_events=[],
        )


def test_commit_input_rejects_empty_payload() -> None:
    with pytest.raises(PydanticValidationError):
        CommitInput(
            user_id="u1",
            idempotency_key=uuid4(),
            today=date(2026, 5, 24),
            todos=[],
            calendar_events=[],
        )


def test_commit_input_accepts_exactly_50() -> None:
    items = [_ok_task() for _ in range(50)]
    CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=items,
        calendar_events=[],
    )


# ---- CommitResult ----

def test_commit_result_smoke() -> None:
    r = CommitResult(
        todo_ids=[uuid4()],
        event_ids=[],
        quest_distribution_triggered=False,
    )
    assert r.quest_distribution_triggered is False


# === multi_turn schemas ===
from datetime import datetime

from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, Day, MultiTurnInput, ParsedGoal, PlanDraft,
    PlannerJudgment, SessionState, TaggedPlan, Task, TurnResult,
)


def test_multi_turn_input_max_length_600():
    inp = MultiTurnInput(user_id="u1", session_id="s1", message="가" * 600, today=date(2026, 5, 25))
    assert len(inp.message) == 600


def test_multi_turn_input_over_600_rejected():
    with pytest.raises(PydanticValidationError):
        MultiTurnInput(user_id="u1", session_id="s1", message="가" * 601, today=date(2026, 5, 25))


def test_chat_message_roles():
    assert ChatMessage(role="user", content="hi").role == "user"
    with pytest.raises(PydanticValidationError):
        ChatMessage(role="system", content="x")


def test_parsed_goal_all_optional():
    g = ParsedGoal()
    assert g.goal_type is None and g.extras == {}


def test_planner_judgment_round_trip():
    j = PlannerJudgment(is_sufficient=False, missing_aspects=["하루 시간"], parsed_goal=ParsedGoal(goal_type="정처기"))
    assert j.missing_aspects == ["하루 시간"]


def test_plan_draft_no_length_at_schema():
    draft = PlanDraft(summary_text="가" * 2000, days=[])
    assert len(draft.summary_text) == 2000


def test_tagged_plan_has_tags():
    plan = TaggedPlan(
        summary_text="요약",
        days=[Day(date=date(2026, 5, 25), tasks=[Task(title="공부", tags=["학습"])])],
    )
    assert plan.days[0].tasks[0].tags == ["학습"]


def test_agent_decision_tool_names():
    assert AgentDecision(tool_name="confirm", tool_args={}).tool_name == "confirm"
    d = AgentDecision(tool_name="regenerate_plan", tool_args={"instructions": "더 짧게"})
    assert d.tool_args["instructions"] == "더 짧게"
    with pytest.raises(PydanticValidationError):
        AgentDecision(tool_name="invalid", tool_args={})


def test_turn_result_kinds():
    assert TurnResult(kind="question", question="?").kind == "question"
    assert TurnResult(kind="plan", plan=TaggedPlan(summary_text="x", days=[])).plan is not None
    assert TurnResult(kind="committed").kind == "committed"


def test_session_state_phase_literals():
    now = datetime(2026, 5, 25, 12, 0)
    s = SessionState(session_id="s1", user_id="u1", phase="gathering", history=[], parsed_goal=None, current_plan=None, created_at=now, updated_at=now)
    assert s.phase == "gathering"
    with pytest.raises(PydanticValidationError):
        SessionState(session_id="s1", user_id="u1", phase="invalid", history=[], parsed_goal=None, current_plan=None, created_at=now, updated_at=now)
