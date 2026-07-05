"""서빙 계약 스냅샷이 런타임 원본과 동기화돼 있는지 검사한다 (train==serve)."""
from datetime import date

import pytest

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from adapters.todo_creation.qwen_llm import plan_guided_schema
from sft_pipeline.experiments.planner_sft_v3 import contract

GOAL = {
    "intent": "plan",
    "plan_kind": "lifestyle",
    "slots": {"goal": "운동과 독서 병행", "success_criteria": "한 달 유지"},
    "goal_text": "운동과 독서 병행",
    "goal_tag": "운동독서",
    "deadline": "2026-08-04",
    "daily_capacity_minutes": 60,
    "personalization_patch": {"preferences": [], "constraints": ["평일 1시간"]},
    "assumptions": [],
}


def test_system_prompt_matches_runtime():
    assert contract.SYSTEM_PROMPT == PLAN_GENERATOR_SYSTEM


def test_user_builder_matches_runtime():
    today = date(2026, 7, 5)
    assert contract.build_user(GOAL, today) == plan_generator_user(
        parsed_goal=GOAL, today=today
    )


def test_guided_schema_matches_runtime():
    assert contract.GUIDED_SCHEMA == plan_guided_schema()


def test_parse_plan_output_roundtrip():
    text = '{"summary_text":"요약","days":[{"date":"2026-07-06","tasks":[{"title":"스트레칭","due_date":"2026-07-06"}]}]}'
    parsed = contract.parse_plan_output(text)
    assert parsed["summary_text"] == "요약"
    assert parsed["days"][0]["tasks"][0]["title"] == "스트레칭"


def test_parse_plan_output_rejects_garbage():
    with pytest.raises(ValueError):
        contract.parse_plan_output("계획을 세워드릴게요!")
    with pytest.raises(ValueError):
        contract.parse_plan_output('{"summary_text":"요약만 있고 days 없음"}')
