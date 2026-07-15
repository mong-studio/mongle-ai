"""서빙 계약 스냅샷 — 런타임 심볼의 읽기 전용 re-export + 출력 파서.

train==serve 원칙: 데이터 생성·평가·A/B 는 전부 이 모듈만 사용한다.
런타임 계약이 바뀌면 tests/test_contract.py 의 sync 테스트가 깨져 즉시 드러난다.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from adapters.todo_creation.qwen_llm import plan_guided_schema

SYSTEM_PROMPT: str = PLAN_GENERATOR_SYSTEM
GUIDED_SCHEMA: dict[str, Any] = plan_guided_schema()


def build_user(parsed_goal: dict[str, Any], today: date) -> str:
    return plan_generator_user(parsed_goal=parsed_goal, today=today)


def parse_plan_output(text: str) -> dict[str, Any]:
    """모델/teacher 출력 텍스트를 계약 형태로 파싱한다. 실패 시 ValueError."""
    s_idx, e_idx = text.find("{"), text.rfind("}")
    if s_idx != -1 and e_idx > s_idx:
        text = text[s_idx:e_idx + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON 객체가 아님")
    if not str(parsed.get("summary_text") or "").strip():
        raise ValueError("summary_text 누락")
    days = parsed.get("days")
    if not isinstance(days, list) or not days:
        raise ValueError("days 누락 또는 빈 배열")
    for day in days:
        if not isinstance(day, dict) or not day.get("date") or not day.get("tasks"):
            raise ValueError(f"day 형식 위반: {day!r}")
    return parsed
