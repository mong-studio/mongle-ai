from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from agents.todo_creation.schemas import (
    CommitInput,
    CommitResult,
    GenerateResult,
    TodoInput,
    TaskCandidate,
)


# ---- TodoInput ----

def test_todo_input_accepts_200_char_prompt() -> None:
    """싱글턴 입력이 최대 길이 200자 프롬프트를 정상 수용하는지 확인한다."""
    TodoInput(user_id="u1", prompt="가" * 200, today=date(2026, 5, 24))


def test_todo_input_rejects_201_char_prompt() -> None:
    """싱글턴 입력이 201자 초과 프롬프트를 스키마 단계에서 거부하는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        TodoInput(user_id="u1", prompt="가" * 201, today=date(2026, 5, 24))


def test_todo_input_rejects_empty_prompt() -> None:
    """싱글턴 입력에서 빈 프롬프트를 허용하지 않는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        TodoInput(user_id="u1", prompt="", today=date(2026, 5, 24))


def test_todo_input_rejects_empty_user_id() -> None:
    """싱글턴 입력에서 빈 user_id를 허용하지 않는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        TodoInput(user_id="", prompt="할 일", today=date(2026, 5, 24))


# ---- TaskCandidate ----

def test_task_candidate_defaults() -> None:
    """TaskCandidate 생성 시 tags 기본값이 빈 리스트인지 확인한다."""
    t = TaskCandidate(title="코테", due_date=date(2026, 5, 24))
    assert t.tags == []


def test_task_candidate_rejects_empty_title() -> None:
    """TaskCandidate가 빈 title을 거부하는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        TaskCandidate(title="", due_date=date(2026, 5, 24))


def test_task_candidate_rejects_title_over_20_chars() -> None:
    """TaskCandidate가 20자를 넘는 title을 거부하는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        TaskCandidate(title="x" * 21, due_date=date(2026, 5, 24))


# ---- GenerateResult ----

def test_generate_result_allows_empty_lists() -> None:
    """후보가 없는 상태에서도 GenerateResult 인스턴스를 만들 수 있는지 확인한다."""
    GenerateResult(todos=[], calendar_events=[])


# ---- CommitInput ----

def _ok_task(d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title="할 일", due_date=d)


def test_commit_input_accepts_normal_payload() -> None:
    """커밋 입력이 일반적인 todo payload를 정상 수용하는지 확인한다."""
    CommitInput(
        user_id="u1",
        idempotency_key=uuid4(),
        today=date(2026, 5, 24),
        todos=[_ok_task()],
        calendar_events=[],
    )


def test_commit_input_rejects_total_over_50() -> None:
    """커밋 입력이 총 50개를 넘는 항목을 거부하는지 확인한다."""
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
    """커밋 입력이 todo와 calendar_events가 모두 비어 있으면 거부되는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        CommitInput(
            user_id="u1",
            idempotency_key=uuid4(),
            today=date(2026, 5, 24),
            todos=[],
            calendar_events=[],
        )


def test_commit_input_accepts_exactly_50() -> None:
    """커밋 입력이 최대 허용치인 50개는 수용하는지 확인한다."""
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
    """CommitResult가 기본 필드 조합만으로도 안정적으로 생성되는지 확인한다."""
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
    """통합 generate 스키마의 single 모드가 200자 프롬프트를 유지하는지 확인한다."""
    assert (
        SingleGenerateInput(user_id="u1", prompt="a" * 200, today=date(2026, 5, 25)).mode
        == "single"
    )


def test_single_input_over_200_rejected() -> None:
    """통합 generate 스키마의 single 모드가 200자 초과 입력을 거부하는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        SingleGenerateInput(user_id="u1", prompt="a" * 201, today=date(2026, 5, 25))


def test_multi_input_max_600() -> None:
    """멀티턴 입력이 최대 길이 600자 메시지를 수용하는지 확인한다."""
    inp = MultiGenerateInput(user_id="u1", message="가" * 600, today=date(2026, 5, 25))
    assert inp.mode == "multi"
    assert inp.thread_id is None


def test_multi_input_blank_thread_id_becomes_none() -> None:
    """공백뿐인 thread_id가 None으로 정리되는지 확인한다."""
    inp = MultiGenerateInput(
        user_id="u1",
        message="운동 계획",
        today=date(2026, 5, 25),
        thread_id="   ",
    )
    assert inp.thread_id is None


def test_multi_input_over_600_rejected() -> None:
    """멀티턴 입력이 600자 초과 메시지를 거부하는지 확인한다."""
    with pytest.raises(PydanticValidationError):
        MultiGenerateInput(user_id="u1", message="가" * 601, today=date(2026, 5, 25))


def test_generate_input_discriminator_single() -> None:
    """통합 GenerateInput discriminator가 single payload를 올바른 모델로 파싱하는지 확인한다."""
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode": "single", "user_id": "u1", "prompt": "x", "today": "2026-05-25"}
    )
    assert isinstance(parsed, SingleGenerateInput)


def test_generate_input_discriminator_multi() -> None:
    """통합 GenerateInput discriminator가 multi payload를 올바른 모델로 파싱하는지 확인한다."""
    parsed = TypeAdapter(GenerateInput).validate_python(
        {"mode": "multi", "user_id": "u1", "message": "안녕", "today": "2026-05-25"}
    )
    assert isinstance(parsed, MultiGenerateInput)


def test_turn_result_discriminator() -> None:
    """TurnResult union이 candidates/follow_up 결과를 올바른 모델로 구분하는지 확인한다."""
    a = TypeAdapter(TurnResult)
    c = a.validate_python(
        {"kind": "candidates", "thread_id": "t1", "todos": [], "calendar_events": []}
    )
    f = a.validate_python(
        {"kind": "follow_up", "thread_id": "t1", "question": "?", "missing_aspects": []}
    )
    assert isinstance(c, GenerateResult)
    assert isinstance(f, FollowUpResult)


def test_single_turn_result_discriminates_out_of_scope() -> None:
    from pydantic import TypeAdapter
    from agents.todo_creation.schemas import SingleTurnResult, OutOfScopeResult

    adapter = TypeAdapter(SingleTurnResult)
    parsed = adapter.validate_python(
        {"kind": "out_of_scope", "thread_id": "", "message": "안내"}
    )
    assert isinstance(parsed, OutOfScopeResult)


def test_split_result_holds_intent_and_tasks() -> None:
    from agents.todo_creation.schemas import SplitResult, TaskCandidate
    from datetime import date

    r = SplitResult(intent="plan", tasks=[TaskCandidate(title="x", due_date=date(2026, 6, 13))])
    assert r.intent == "plan"
    assert len(r.tasks) == 1


def test_out_of_scope_message_constant_nonempty() -> None:
    from agents.todo_creation.schemas import OUT_OF_SCOPE_MESSAGE

    assert isinstance(OUT_OF_SCOPE_MESSAGE, str) and len(OUT_OF_SCOPE_MESSAGE) > 0


def test_single_turn_result_discriminates_candidates() -> None:
    from datetime import date
    from pydantic import TypeAdapter
    from agents.todo_creation.schemas import SingleTurnResult, GenerateResult

    adapter = TypeAdapter(SingleTurnResult)
    parsed = adapter.validate_python(
        {
            "kind": "candidates",
            "todos": [{"title": "x", "due_date": "2026-06-13", "tags": []}],
            "calendar_events": [],
        }
    )
    assert isinstance(parsed, GenerateResult)
