"""Mi:dm-mini-Instruct 어댑터 — todo_creation.LLMPort.split_tasks.

OpenAI 호환 endpoint(vLLM 등)에서 Mi:dm 모델을 호출한다. Mi:dm 은
json_schema strict 모드를 지원하지 않으므로 시스템 프롬프트 JSON 지시 +
수동 파싱 + 1회 재시도로 구조화 출력을 강제한다 (AI_RULES §3).

multi-turn 메서드(judge_sufficiency 등)는 multi-turn 파이프라인이
UI에 연결될 때 구현한다. 현재는 NotImplementedError.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from adapters._shared.openai_compat import build_async_client
from adapters.todo_creation._prompts import TASK_SPLITTER_SYSTEM, task_splitter_user
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn

log = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_SCHEMA_REINFORCE = (
    "이전 응답이 유효한 JSON 이 아니었거나 형식을 어겼다. "
    '다음 형식만 출력하라: {"tasks": [{"title": "...", "due_date": "YYYY-MM-DD", "time_hint": null}]}\n'
    "코드 펜스(```), 설명, 주석 없이 JSON 객체만 출력하라."
)


def _strip_fence(raw: str) -> str:
    m = _CODE_FENCE_RE.search(raw)
    return m.group(1).strip() if m else raw.strip()


def _parse_tasks(raw: str) -> list[TaskCandidate]:
    stripped = _strip_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err
    if not isinstance(parsed, dict) or "tasks" not in parsed:
        raise LLMOutputError(f"missing 'tasks' key: {stripped[:200]}")
    tasks_raw = parsed["tasks"]
    if not isinstance(tasks_raw, list):
        raise LLMOutputError("'tasks' is not a list")
    out: list[TaskCandidate] = []
    for item in tasks_raw:
        try:
            out.append(
                TaskCandidate(
                    title=item["title"],
                    due_date=date.fromisoformat(item["due_date"]),
                    time_hint=item.get("time_hint"),
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid task item {item!r}: {err}") from err
    return out


@dataclass
class MidmLLM:
    """Implements todo_creation LLMPort backed by Mi:dm-mini-Instruct."""

    model: str
    base_url: str
    api_key: str = "EMPTY"
    temperature: float = 0.7

    async def split_tasks(self, *, prompt: str, today: date) -> list[TaskCandidate]:
        client = build_async_client(base_url=self.base_url, api_key=self.api_key)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": TASK_SPLITTER_SYSTEM},
            {"role": "user", "content": task_splitter_user(prompt, today)},
        ]
        last_err: LLMOutputError | None = None
        for attempt in range(2):  # AI_RULES §3: todo LLM 최대 2회 시도
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
            except Exception as err:
                raise LLMFailedError(f"midm call failed: {err}") from err
            raw = response.choices[0].message.content or "" if response.choices else ""
            try:
                return _parse_tasks(raw)
            except LLMOutputError as err:
                last_err = err
                log.warning("midm split_tasks parse fail (attempt %d): %s", attempt + 1, err)
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": _SCHEMA_REINFORCE},
                ]
        assert last_err is not None
        raise last_err

    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date
    ) -> tuple[bool, list[str], ParsedGoal]:
        raise NotImplementedError("multi-turn not yet wired for MidmLLM")

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str:
        raise NotImplementedError("multi-turn not yet wired for MidmLLM")

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        raise NotImplementedError("multi-turn not yet wired for MidmLLM")

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        raise NotImplementedError("multi-turn not yet wired for MidmLLM")
