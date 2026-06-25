"""plan_generator 노드 SFT 템플릿: 런타임 동기화 + 빌드 정합성.

학습 == 서빙이 목적이므로 system·user 가 런타임과 바이트 동일한지(sync),
assistant 타깃이 서빙 plan_generator 계약을 지키는지 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from sft_pipeline.build.lib import plan_generator_template as tpl

_CASE = {
    "exam_type": "토익",
    "time_left_days": "7",
    "daily_hours_value": "3",
    "start_level": "기초",
    "goal": "700점",
    "special_notes": "직장 병행",
    "source_url": "https://example.test/case",
}
_TODAY = date(2026, 6, 21)


def test_mirror_matches_runtime():
    """미러한 system 상수·user 빌더가 서빙(_prompts)과 바이트 동일해야 한다."""
    from adapters.todo_creation._prompts import (
        PLAN_GENERATOR_SYSTEM as runtime_system,
        plan_generator_user as runtime_user,
    )

    assert tpl.PLAN_GENERATOR_SYSTEM == runtime_system

    parsed_goal = tpl.build_parsed_goal(_CASE, _TODAY)
    assert tpl.plan_generator_user(
        parsed_goal=parsed_goal, today=_TODAY
    ) == runtime_user(parsed_goal=parsed_goal, today=_TODAY)


def test_record_shape():
    rec = tpl.build_record(_CASE, _TODAY)
    roles = [m["role"] for m in rec["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert rec["messages"][0]["content"] == tpl.PLAN_GENERATOR_SYSTEM
    assert rec["messages"][1]["content"].startswith("today=2026-06-21\n플랜 입력(JSON): ")
    # 학습 소비측(dataset.load_messages)이 요구: 마지막 assistant 비어있지 않음.
    assert rec["messages"][-1]["content"].strip()
    assert rec["meta"]["node"] == "plan_generator"


def test_assistant_obeys_serving_contract():
    obj = json.loads(tpl.build_record(_CASE, _TODAY)["messages"][2]["content"])
    days = obj["days"]
    horizon = _TODAY + timedelta(days=29)  # 서빙: 오늘부터 30일 이내

    assert obj["summary_text"]
    assert "rationale" not in obj  # 서빙 스키마에 rationale 없음
    assert set(obj["personalization_patch"]) == {
        "preferences",
        "constraints",
        "planning_style",
    }
    # 출력 키 순서: summary_text → days → personalization_patch
    assert list(obj) == ["summary_text", "days", "personalization_patch"]
    assert 1 <= len(days) <= 30

    seen_dates = set()
    total_tasks = 0
    for day in days:
        d = date.fromisoformat(day["date"])
        assert _TODAY <= d <= horizon  # 최대 30일·과거 금지
        assert d not in seen_dates  # 날짜 중복 없음
        seen_dates.add(d)
        assert 1 <= len(day["tasks"]) <= 3
        total_tasks += len(day["tasks"])
        for task in day["tasks"]:
            assert date.fromisoformat(task["due_date"]) == d  # due_date==day.date
            assert 1 <= len(task["title"]) <= 20
            assert set(task) == {"title", "due_date"}  # 서빙: difficulty/tags 미출력
    assert total_tasks <= 15


def test_deadline_and_capacity_derived():
    pg = tpl.build_parsed_goal(_CASE, _TODAY)
    assert pg["intent"] == "plan"
    assert pg["goal_tag"] == "토익"
    assert pg["deadline"] == (_TODAY + timedelta(days=7)).isoformat()
    assert pg["daily_capacity_minutes"] == 180


def test_missing_fields_no_crash():
    """빈/누락 필드여도 유효 레코드를 만든다(deadline=None, 기본 7일)."""
    rec = tpl.build_record({"exam_type": "", "time_left_days": ""}, _TODAY)
    obj = json.loads(rec["messages"][2]["content"])
    assert obj["days"]  # 최소 1일 이상
    pg_user = rec["messages"][1]["content"]
    assert "'deadline': None" in pg_user
