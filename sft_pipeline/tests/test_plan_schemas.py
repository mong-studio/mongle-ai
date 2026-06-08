"""SFT 타깃 플랜 스키마(parse_plan)와 정합성 검증(check_plan_consistency) 테스트.

스키마는 런타임 agents/todo_creation/schemas.py 의 GenerateResult/TaskCandidate 를
미러링한다. 정합성 규칙:
- 날짜: today <= due_date <= today + horizon_days
- 분기(C5/date_router): due_date == today ↔ todos, 미래 → calendar_events
- 분량: 1 <= 항목 수 <= 50
- 품질: 'N단원/N일차' 식 단조 분해가 과반이면 reject
"""

from datetime import date

import pytest

from sft_pipeline.build.plan_schemas import (
    PlanOutput,
    PlanTask,
    _loads_lenient,
    _normalize_plan_dict,
    check_plan_consistency,
    parse_plan,
    rebucket_by_date,
)

TODAY = date(2026, 6, 6)


def _plan_json(todos=None, events=None, summary="D-7 기출 위주 플랜이에요!"):
    import json

    return json.dumps(
        {
            "summary_text": summary,
            "todos": todos
            if todos is not None
            else [
                {
                    "title": "기출 1개년 풀기",
                    "due_date": "2026-06-06",
                    "tags": ["공부"],
                },
            ],
            "calendar_events": events
            if events is not None
            else [
                {"title": "오답 정리", "due_date": "2026-06-08", "tags": ["공부"]},
            ],
        },
        ensure_ascii=False,
    )


# === parse_plan ===


def test_parse_plan_valid_json():
    plan = parse_plan(_plan_json())
    assert isinstance(plan, PlanOutput)
    assert plan.todos[0].title == "기출 1개년 풀기"
    assert plan.calendar_events[0].due_date == date(2026, 6, 8)


def test_parse_plan_strips_code_fence():
    fenced = "```json\n" + _plan_json() + "\n```"
    plan = parse_plan(fenced)
    assert plan.todos[0].title == "기출 1개년 풀기"


def test_parse_plan_rejects_long_title():
    bad = _plan_json(todos=[{"title": "스" * 31, "due_date": "2026-06-06", "tags": []}])
    with pytest.raises(ValueError):
        parse_plan(bad)


def test_parse_plan_rejects_bad_date():
    bad = _plan_json(todos=[{"title": "기출", "due_date": "내일", "tags": []}])
    with pytest.raises(ValueError):
        parse_plan(bad)


def test_parse_plan_rejects_non_json():
    with pytest.raises(ValueError):
        parse_plan("주말 아침에 하는 걸 추천해요.")


# === check_plan_consistency ===


def test_consistency_ok():
    plan = parse_plan(_plan_json())
    assert check_plan_consistency(plan, today=TODAY, horizon_days=7) == []


def test_consistency_empty_plan():
    plan = parse_plan(_plan_json(todos=[], events=[]))
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("빈 플랜" in e for e in errors)


def test_consistency_too_many_items():
    events = [
        {"title": f"항목 {i}", "due_date": "2026-06-08", "tags": []} for i in range(51)
    ]
    plan = parse_plan(_plan_json(todos=[], events=events))
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("항목 과다" in e for e in errors)


def test_consistency_date_before_today():
    plan = parse_plan(
        _plan_json(events=[{"title": "복습", "due_date": "2026-06-01", "tags": []}])
    )
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("오늘 이전" in e for e in errors)


def test_consistency_date_beyond_horizon():
    plan = parse_plan(
        _plan_json(events=[{"title": "복습", "due_date": "2026-07-01", "tags": []}])
    )
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("horizon" in e and "초과" in e for e in errors)


def test_consistency_no_horizon_allows_far_future():
    plan = parse_plan(
        _plan_json(events=[{"title": "복습", "due_date": "2026-07-01", "tags": []}])
    )
    assert check_plan_consistency(plan, today=TODAY, horizon_days=None) == []


def test_consistency_todo_must_be_today():
    """C5: 오늘이 아닌 task 가 todos 에 있으면 분기 위반."""
    plan = parse_plan(
        _plan_json(todos=[{"title": "기출", "due_date": "2026-06-08", "tags": []}])
    )
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("todos" in e and "오늘" in e for e in errors)


def test_consistency_event_must_be_future():
    """오늘 task 가 calendar_events 에 있으면 분기 위반."""
    plan = parse_plan(
        _plan_json(events=[{"title": "기출", "due_date": "2026-06-06", "tags": []}])
    )
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("calendar_events" in e for e in errors)


def test_consistency_monotonic_decomposition_rejected():
    """'1단원 풀기, 2단원 풀기...' 식 기계적 분해가 과반이면 품질 reject."""
    events = [
        {"title": f"{i}단원 풀기", "due_date": "2026-06-08", "tags": []}
        for i in range(1, 5)
    ] + [{"title": "오답 정리", "due_date": "2026-06-09", "tags": []}]
    plan = parse_plan(_plan_json(todos=[], events=events))
    errors = check_plan_consistency(plan, today=TODAY, horizon_days=7)
    assert any("단조 분해" in e for e in errors)


def test_consistency_minority_numbered_titles_ok():
    """숫자 포함 제목을 단조 분해로 오판하지 않는지 확인(거짓 양성 가드).

    품질 규칙은 _MONOTONIC_RE 매칭 제목이 '과반'일 때만 reject 한다.
    실전 플랜에도 '기출 1회차 풀기' 같은 숫자 포함 제목은 자연스럽게 나오며,
    이런 제목은 정규식에 매칭되지 않아야 한다:
    - 제목이 숫자로 시작하지 않음 ('기출'로 시작)
    - '회차'는 분할 단위 목록(단원|일차|장|챕터|파트|과)에 없음

    즉 누군가 정규식을 일상적인 숫자 포함 제목까지 잡을 만큼 넓히거나,
    검사를 '하나라도 있으면 reject'로 강화하면 이 테스트가 깨진다.
    과반 reject 쪽 경계는 test_consistency_monotonic_decomposition_rejected 가 커버.
    """
    events = [
        {"title": "기출 1회차 풀기", "due_date": "2026-06-08", "tags": []},
        {"title": "오답 정리", "due_date": "2026-06-09", "tags": []},
        {"title": "요약노트 복습", "due_date": "2026-06-10", "tags": []},
    ]
    plan = parse_plan(_plan_json(todos=[], events=events))
    assert check_plan_consistency(plan, today=TODAY, horizon_days=7) == []


# === 런타임 스키마 동기화 가드 ===


def test_mirror_matches_runtime_schema():
    """미러 스키마가 런타임 TaskCandidate 제약(title<=20)과 어긋나면 실패."""
    from agents.todo_creation.schemas import TaskCandidate

    from sft_pipeline.build.plan_schemas import PlanTask

    runtime_meta = TaskCandidate.model_fields["title"].metadata
    mirror_meta = PlanTask.model_fields["title"].metadata
    runtime_len = [m.max_length for m in runtime_meta if hasattr(m, "max_length")]
    mirror_len = [m.max_length for m in mirror_meta if hasattr(m, "max_length")]
    assert runtime_len == mirror_len == [30]


# === LLM 출력 관용 정규화(합성 파서용) ===


def test_normalize_fills_missing_lists_and_tags():
    n = _normalize_plan_dict(
        {"summary_text": "x", "todos": [{"title": "a", "due_date": "2026-06-06"}]}
    )
    assert n["calendar_events"] == []  # 누락 키 → []
    assert n["todos"][0]["tags"] == []  # tags 기본값


def test_normalize_maps_date_alias_to_due_date():
    n = _normalize_plan_dict(
        {"todos": [], "calendar_events": [{"title": "a", "date": "2026-06-08"}]}
    )
    ev = n["calendar_events"][0]
    assert ev["due_date"] == "2026-06-08"
    assert "date" not in ev


def test_loads_lenient_takes_first_object_on_extra_data():
    text = '{"a": 1}\n{"b": 2}\n뒤에 붙은 설명'
    assert _loads_lenient(text) == {"a": 1}


def test_loads_lenient_strips_code_fence():
    assert _loads_lenient('```json\n{"a": 1}\n```') == {"a": 1}


def test_normalize_then_validate_recovers_missing_calendar_events():
    raw = '{"summary_text":"x","todos":[{"title":"오늘 할 일","due_date":"2026-06-06"}]} 추가설명'
    plan = PlanOutput.model_validate(_normalize_plan_dict(_loads_lenient(raw)))
    assert plan.calendar_events == []
    assert plan.todos[0].tags == []


def test_rebucket_moves_tasks_by_date():
    """런타임 date_router 와 동일: due_date==today → todos, 미래 → calendar_events."""
    plan = PlanOutput(
        summary_text="x",
        # LLM 이 분류를 틀려 미래 항목을 todos 에, 오늘 항목을 events 에 넣은 상태
        todos=[
            PlanTask(title="오늘 개념", due_date=TODAY),
            PlanTask(title="내일 기출", due_date=date(2026, 6, 7)),
        ],
        calendar_events=[PlanTask(title="오늘 정리", due_date=TODAY)],
    )
    fixed = rebucket_by_date(plan, today=TODAY)
    assert {t.title for t in fixed.todos} == {"오늘 개념", "오늘 정리"}
    assert {e.title for e in fixed.calendar_events} == {"내일 기출"}
    assert all(t.due_date == TODAY for t in fixed.todos)
    assert all(e.due_date != TODAY for e in fixed.calendar_events)
    # 재분류 후 C5 분기 위반이 사라진다
    assert check_plan_consistency(fixed, today=TODAY, horizon_days=7) == []


def test_rebucket_preserves_summary_and_is_pure():
    """summary 보존, 입력 plan 불변(새 객체 반환)."""
    plan = PlanOutput(
        summary_text="요약 보존",
        todos=[PlanTask(title="내일 일", due_date=date(2026, 6, 7))],
        calendar_events=[],
    )
    fixed = rebucket_by_date(plan, today=TODAY)
    assert fixed.summary_text == "요약 보존"
    assert plan.todos[0].title == "내일 일"  # 원본 불변
    assert fixed.todos == [] and len(fixed.calendar_events) == 1


def test_dump_plan_for_training_excludes_tags():
    """학습용 직렬화는 tags 를 제외하고(Tagger 노드 책임), 파서는 누락을 []로 흡수한다."""
    from sft_pipeline.build.plan_schemas import PlanTask, dump_plan_for_training

    plan = PlanOutput(
        summary_text="요약",
        todos=[PlanTask(title="할 일", due_date=date(2026, 6, 8), tags=["공부"])],
        calendar_events=[],
    )
    dumped = dump_plan_for_training(plan)
    assert '"tags"' not in dumped
    assert parse_plan(dumped).todos[0].tags == []
