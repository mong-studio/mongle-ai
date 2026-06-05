"""
    todo_creation.LLMPort 용 Qwen2.5-Instruct 어댑터.
    vLLM 같은 OpenAI 호환 chat completions 엔드포인트를 대상으로 하되,
    OpenAI 서비스 사용을 전제하지 않도록 일반 HTTP 클라이언트로 호출한다.
    TODO 에이전트는 상태를 갖지 않으며, 매 호출마다 현재 프롬프트와 날짜
    컨텍스트만 보내고 모델의 JSON 문자열 응답을 파싱한다.
"""

"""
    LLMFailedError:
    LLM 호출 자체가 실패한 경우
    예: 서버 꺼짐, timeout, HTTP 500

    LLMOutputError:
    LLM 호출은 성공했지만 응답 형식이 이상한 경우
    예: JSON 아님, tasks 키 없음, due_date 형식 이상함
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from adapters.todo_creation._prompts import TASK_SPLITTER_SYSTEM, task_splitter_user
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn

log = logging.getLogger(__name__)

DEFAULT_QWEN_MODEL = "Qwen/Qwen2.5-7B-Instruct"

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_SCHEMA_REINFORCE = (
    "직전 응답은 파싱할 수 없다. 설명 없이 JSON 객체 하나만 다시 출력하라.\n"
    '스키마: {"tasks": [{"title": "20자 이하 명사구", '
    '"due_date": "YYYY-MM-DD", "tags": ["20자 이하 태그"]}]}\n'
    "코드 펜스, 주석, 마크다운, 추가 문장을 절대 포함하지 마라."
)


def build_task_splitter_messages(
    *, prompt: str, today: date
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TASK_SPLITTER_SYSTEM},
        {"role": "user", "content": task_splitter_user(prompt, today)},
    ]


def strip_json_fence(raw: str) -> str:
    match = _CODE_FENCE_RE.search(raw)
    return match.group(1).strip() if match else raw.strip()


def parse_task_response(raw: str) -> list[TaskCandidate]:
    stripped = strip_json_fence(raw)
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
                    tags=item.get("tags") or [],
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid task item {item!r}: {err}") from err
    return out


def reinforce_messages(
    messages: list[dict[str, str]], *, raw_response: str
) -> list[dict[str, str]]:
    return [
        *messages,
        {"role": "assistant", "content": raw_response},
        {"role": "user", "content": _SCHEMA_REINFORCE},
    ]


@dataclass
class QwenLLM:
    """Qwen2.5-Instruct 로 todo_creation LLMPort 를 구현한다."""

    base_url: str
    model: str = DEFAULT_QWEN_MODEL
    api_key: str = "EMPTY"
    temperature: float = 0.1
    max_tokens: int = 800
    timeout_seconds: float = 30.0

    async def complete_raw(self, *, messages: list[dict[str, str]]) -> str:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as err:
            raise LLMFailedError(f"qwen call failed: {err}") from err

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError, ValueError) as err:
            raise LLMOutputError(
                f"invalid qwen response envelope: {response.text[:200]}"
            ) from err

    async def split_tasks(self, *, prompt: str, today: date) -> list[TaskCandidate]:
        messages = build_task_splitter_messages(prompt=prompt, today=today)
        last_err: LLMOutputError | None = None

        for attempt in range(2):
            raw = await self.complete_raw(messages=messages)
            try:
                return parse_task_response(raw)
            except LLMOutputError as err:
                last_err = err
                log.warning(
                    "qwen split_tasks parse fail (attempt %d): %s",
                    attempt + 1,
                    err,
                )
                messages = reinforce_messages(messages, raw_response=raw)

        assert last_err is not None
        raise last_err

    async def judge_sufficiency(
        self, *, history: list[Turn], message: str, today: date
    ) -> tuple[bool, list[str], ParsedGoal]:
        raise NotImplementedError("QwenLLM 멀티턴 연동은 아직 구현되지 않았다")

    async def generate_follow_up_question(
        self, *, missing_aspects: list[str], history: list[Turn]
    ) -> str:
        raise NotImplementedError("QwenLLM 멀티턴 연동은 아직 구현되지 않았다")

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        raise NotImplementedError("QwenLLM 멀티턴 연동은 아직 구현되지 않았다")

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        raise NotImplementedError("QwenLLM 멀티턴 연동은 아직 구현되지 않았다")
