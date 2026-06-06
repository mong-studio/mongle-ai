"""SFT 타깃 출력 스키마 + 정합성 검증.

런타임 `agents/todo_creation/schemas.py` 의 GenerateResult/TaskCandidate 를 미러링한다(직접 import 는 학습 파이프라인↔런타임 결합을 만들므로 미러 + 동기화 테스트로 보호: tests/test_plan_schemas.py::test_mirror_matches_runtime_schema).

정합성 규칙(분기는 docs/features/todo/CLAUDE.md C5/date_router 와 동일):
- 날짜: today <= due_date <= today + horizon_days
- 분기: due_date == today → todos, 미래 → calendar_events
- 분량: 1 <= 항목 수 <= 50
- 품질: 'N단원/N일차' 식 단조 분해 제목이 과반이면 reject
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError


class PlanTask(BaseModel):
    """런타임 TaskCandidate 미러."""

    title: Annotated[str, Field(min_length=1, max_length=20)]
    due_date: date
    tags: Annotated[list[str], Field(default_factory=list)]


class PlanOutput(BaseModel):
    """런타임 GenerateResult 미러(kind/thread_id 등 서버 발급 필드는 제외)."""

    summary_text: Annotated[str | None, Field(max_length=1500)] = None
    todos: list[PlanTask]
    calendar_events: list[PlanTask]


def _extract_json(content: str) -> str:
    """```json 코드펜스·앞뒤 잡설을 제거하고 JSON 객체만 남긴다."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text


def parse_plan(content: str) -> PlanOutput:
    """assistant 출력 문자열 → PlanOutput. 실패 시 ValueError."""
    try:
        data = json.loads(_extract_json(content), strict=False)
        return PlanOutput.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"[파싱] 플랜 출력 파싱 실패: {exc}") from exc


# 'N단원 풀기'처럼 숫자+분할단위로 시작하는 기계적 분해 제목 패턴
_MONOTONIC_RE = re.compile(r"^\s*\d+\s*(단원|일차|장|챕터|파트|과)\b")

MAX_ITEMS = 50  # 런타임 CommitInput 제약과 동일


def _task_errors(
    bucket: str,
    task: PlanTask,
    *,
    today: date,
    horizon: date | None,
    horizon_days: int | None,
) -> Iterator[str]:
    """항목 1개의 날짜 범위·C5 분기 위반 메시지를 yield 한다."""
    if task.due_date < today:
        yield f"[날짜] {bucket} '{task.title}': due_date가 오늘 이전"
    elif horizon is not None and task.due_date > horizon:
        yield f"[날짜] {bucket} '{task.title}': due_date가 horizon(D-{horizon_days}) 초과"
    if bucket == "todos" and task.due_date != today:
        yield f"[분기] todos '{task.title}': due_date가 오늘이어야 함 (C5)"
    if bucket == "calendar_events" and task.due_date == today:
        yield f"[분기] calendar_events '{task.title}': 오늘 마감은 todos에 속함 (C5)"


def check_plan_consistency(
    plan: PlanOutput,
    *,
    today: date,
    horizon_days: int | None,
) -> list[str]:
    """정합성 위반 메시지 목록을 돌려준다(빈 리스트 = 통과)."""
    items = [("todos", t) for t in plan.todos] + [
        ("calendar_events", t) for t in plan.calendar_events
    ]
    if not items:
        return ["[분량] 빈 플랜 (todos/calendar_events 없음)"]

    horizon = today + timedelta(days=horizon_days) if horizon_days is not None else None

    size_errors = (
        [f"[분량] 항목 과다 ({len(items)} > {MAX_ITEMS})"] if len(items) > MAX_ITEMS else []
    )
    date_errors = [
        error
        for bucket, task in items
        for error in _task_errors(
            bucket, task, today=today, horizon=horizon, horizon_days=horizon_days
        )
    ]
    monotonic = sum(1 for _, t in items if _MONOTONIC_RE.match(t.title))
    quality_errors = (
        [f"[품질] 단조 분해 제목 과반 ({monotonic}/{len(items)}, 'N단원/N일차' 식)"]
        if monotonic * 2 > len(items)
        else []
    )
    return size_errors + date_errors + quality_errors
