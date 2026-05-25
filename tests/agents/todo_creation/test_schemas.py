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


# ---- Unified single/multi I/O ----

from pydantic import TypeAdapter

from agents.todo_creation.schemas import (
    FollowUpResult,
    GenerateInput,
    MultiGenerateInput,
    SingleGenerateInput,
    TurnResult,
)


def test_single_input_max_200() -> None:
    assert (
        SingleGenerateInput(user_id="u1", prompt="a" * 200, today=date(2026, 5, 25)).mode
        == "single"
    )


def test_single_input_over_200_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        SingleGenerateInput(user_id="u1", prompt="a" * 201, today=date(2026, 5, 25))


def test_multi_input_max_600() -> None:
    inp = MultiGenerateInput(user_id="u1", message="가" * 600, today=date(2026, 5, 25))
    assert inp.mode == "multi"
    assert inp.thread_id is None


def test_multi_input_over_600_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        MultiGenerateInput(user_id="u1", message="가" * 601, today=date(2026, 5, 25))


def test_generate_input_discriminator_single() -> None:
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode": "single", "user_id": "u1", "prompt": "x", "today": "2026-05-25"}
    )
    assert isinstance(parsed, SingleGenerateInput)


def test_generate_input_discriminator_multi() -> None:
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode": "multi", "user_id": "u1", "message": "안녕", "today": "2026-05-25"}
    )
    assert isinstance(parsed, MultiGenerateInput)


def test_turn_result_discriminator() -> None:
    a = TypeAdapter(TurnResult)
    c = a.validate_python(
        {"kind": "candidates", "thread_id": "t1", "todos": [], "calendar_events": []}
    )
    f = a.validate_python(
        {"kind": "follow_up", "thread_id": "t1", "question": "?", "missing_aspects": []}
    )
    assert isinstance(c, GenerateResult)
    assert isinstance(f, FollowUpResult)


