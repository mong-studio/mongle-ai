"""SFT 파인튜닝된 Qwen 플래너(LoRA) 어댑터.

vLLM 등 OpenAI 호환 엔드포인트로 서빙된 `qwen7b-planner-lora` 를 대상으로,
`generate_plan` 만 SFT 학습 분포와 동일한 호출(단일 user 턴, system 없음,
기준일 앵커 포함)로 바꾼다. 모델 출력은 런타임 `GenerateResult` 를 미러링한
구조화 플랜 JSON(`{"summary_text", "todos", "calendar_events"}`)이므로,
due_date 기준으로 묶어 파이프라인이 기대하는 `PlanDay` 목록으로 변환한다
(오늘/미래 분기는 기존 date_router/plan_generator_node 가 다시 수행).

되묻기 판정(judge_sufficiency)·follow-up·goal_tag 등 나머지 역할은 SFT 학습
대상이 아니므로 QwenLLM 의 프롬프트 경로를 그대로 상속해 같은 엔드포인트의
베이스 능력으로 처리한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from adapters.todo_creation.qwen_llm import QwenLLM, strip_json_fence
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

log = logging.getLogger(__name__)

DEFAULT_SFT_MODEL = "qwen7b-planner-lora"

_PLAN_REINFORCE = (
    "직전 응답은 파싱할 수 없다. 설명 없이 JSON 객체 하나만 다시 출력하라.\n"
    '스키마: {"summary_text": "플랜 요약", '
    '"todos": [{"title": "20자 이하", "due_date": "YYYY-MM-DD"}], '
    '"calendar_events": [{"title": "20자 이하", "due_date": "YYYY-MM-DD"}]}\n'
    "코드 펜스, 주석, 마크다운, 추가 문장을 절대 포함하지 마라."
)


def build_sft_plan_message(*, parsed_goal: ParsedGoal, today: date) -> str:
    """parsed_goal 을 SFT 학습 user 턴 형식(조건 나열 + 기준일 앵커)으로 만든다."""
    goal_text = str(parsed_goal.get("goal_text") or "").strip() or "할 일"

    conditions: list[str] = []
    deadline = parsed_goal.get("deadline")
    if isinstance(deadline, date):
        conditions.append(f"마감일: {deadline.isoformat()} (D-{(deadline - today).days})")
    capacity = parsed_goal.get("daily_capacity_minutes")
    if capacity:
        conditions.append(f"하루 가용: {capacity}분")
    revision = str(parsed_goal.get("revision_request") or "").strip()
    if revision:
        conditions.append(f"수정 요청: {revision}")

    condition_text = f" 조건: {' / '.join(conditions)}." if conditions else ""
    return f"'{goal_text}' 계획을 세워줘.{condition_text} (기준일: {today.isoformat()})"


def _parse_tasks(items: Any, *, bucket: str) -> list[TaskCandidate]:
    if not isinstance(items, list):
        raise LLMOutputError(f"'{bucket}' is not a list")
    out: list[TaskCandidate] = []
    for item in items:
        try:
            out.append(
                TaskCandidate(
                    title=item["title"],
                    due_date=date.fromisoformat(str(item["due_date"])),
                    tags=item.get("tags") or [],
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid {bucket} item {item!r}: {err}") from err
    return out


def parse_sft_plan(raw: str) -> tuple[str, list[PlanDay]]:
    """SFT 출력(GenerateResult 미러 JSON) → (summary_text, PlanDay 목록)."""
    stripped = strip_json_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err
    if not isinstance(parsed, dict):
        raise LLMOutputError(f"JSON response is not an object: {stripped[:200]}")

    tasks = [
        *_parse_tasks(parsed.get("todos") or [], bucket="todos"),
        *_parse_tasks(parsed.get("calendar_events") or [], bucket="calendar_events"),
    ]
    if not tasks:
        raise LLMOutputError("empty plan (no todos/calendar_events)")

    by_date: dict[date, list[TaskCandidate]] = {}
    for task in tasks:
        by_date = {**by_date, task.due_date: [*by_date.get(task.due_date, []), task]}

    days: list[PlanDay] = [
        {"date": day, "tasks": by_date[day]} for day in sorted(by_date)
    ]
    summary = str(parsed.get("summary_text") or "").strip()
    return summary, days


@dataclass
class SftQwenLLM(QwenLLM):
    """generate_plan 만 SFT 학습 포맷으로 호출하는 todo_creation LLMPort 구현."""

    model: str = DEFAULT_SFT_MODEL

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        # 학습과 동일: system 없이 단일 user 턴(train/inference skew 방지).
        messages = [
            {"role": "user", "content": build_sft_plan_message(parsed_goal=parsed_goal, today=today)}
        ]

        last_err: LLMOutputError | None = None
        current = messages
        for attempt in range(2):
            raw = await self.complete_raw(messages=current, label="sft_plan")
            try:
                return parse_sft_plan(raw)
            except LLMOutputError as err:
                last_err = err
                log.warning("sft plan parse fail (attempt %d): %s", attempt + 1, err)
                current = [
                    *current,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": _PLAN_REINFORCE},
                ]
        assert last_err is not None
        raise last_err
