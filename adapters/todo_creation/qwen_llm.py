"""
    todo_creation.LLMPort 용 Qwen2.5-Instruct 어댑터.
    vLLM 같은 OpenAI 호환 chat completions 엔드포인트를 대상으로 하되,
    OpenAI 서비스 사용을 전제하지 않도록 일반 HTTP 클라이언트로 호출한다.
    TODO 에이전트는 상태를 갖지 않으며, 매 호출마다 현재 프롬프트와 날짜
    컨텍스트만 보내고 모델의 JSON 문자열 응답을 파싱한다.

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

from adapters.todo_creation._domain_wiki import load_wiki
from adapters.todo_creation._prompts import (
    FOLLOW_UP_SYSTEM,
    GOAL_TAG_SYSTEM,
    PLAN_GENERATOR_SYSTEM,
    PLANNER_JUDGE_SYSTEM,
    follow_up_user,
    goal_tag_user,
    plan_generator_user,
    planner_judge_user,
    TASK_SPLITTER_SYSTEM,
    task_splitter_user,
)
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.planner.slot_schemas import SLOT_SCHEMAS, missing_required
from agents.todo_creation.schemas import SplitResult, TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn

# 스키마 뱅크로 충족을 코드 결정하는 일상 종류(exam 은 기존 모델·deadline 휴리스틱 유지).
_SCHEMA_DRIVEN_KINDS = frozenset({"routine", "vague_goal", "lifestyle"})

log = logging.getLogger(__name__)

DEFAULT_QWEN_MODEL = "Qwen/Qwen2.5-7B-Instruct"

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_SCHEMA_REINFORCE = (
    "직전 응답은 파싱할 수 없다. 설명 없이 JSON 객체 하나만 다시 출력하라.\n"
    '스키마: {"intent": "plan"|"out_of_scope", "tasks": [{"title": "20자 이하 명사구", '
    '"due_date": "YYYY-MM-DD", "tags": ["20자 이하 태그"]}]}\n'
    "out_of_scope 이면 tasks 는 [] 로 둔다.\n"
    "코드 펜스, 주석, 마크다운, 추가 문장을 절대 포함하지 마라."
)
_JSON_REINFORCE = (
    "직전 응답은 파싱할 수 없다. 설명 없이 요청한 스키마의 JSON 객체 하나만 다시 출력하라. "
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


def parse_task_response(raw: str) -> SplitResult:
    stripped = strip_json_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err

    if not isinstance(parsed, dict):
        raise LLMOutputError(f"not a JSON object: {stripped[:200]}")

    intent = parsed.get("intent")
    if intent not in ("plan", "out_of_scope"):
        intent = "plan"
    if intent == "out_of_scope":
        return SplitResult(intent="out_of_scope", tasks=[])

    if "tasks" not in parsed:
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
    return SplitResult(intent="plan", tasks=out)


def reinforce_messages(
    messages: list[dict[str, str]], *, raw_response: str
) -> list[dict[str, str]]:
    return [
        *messages,
        {"role": "assistant", "content": raw_response},
        {"role": "user", "content": _SCHEMA_REINFORCE},
    ]


def _json_default(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"{type(value)!r} is not JSON serializable")


def _as_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _parse_json_object(raw: str) -> dict[str, Any]:
    stripped = strip_json_fence(raw)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err
    if not isinstance(parsed, dict):
        raise LLMOutputError(f"JSON response is not an object: {stripped[:200]}")
    return parsed


async def _complete_json_with_retry(
    llm: "QwenLLM", *, messages: list[dict[str, str]], label: str
) -> dict[str, Any]:
    last_err: LLMOutputError | None = None
    current = messages
    for attempt in range(2):
        raw = await llm.complete_raw(messages=current, label=label)
        try:
            return _parse_json_object(raw)
        except LLMOutputError as err:
            last_err = err
            log.warning("qwen %s parse fail (attempt %d): %s", label, attempt + 1, err)
            current = [
                *current,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _JSON_REINFORCE},
            ]
    assert last_err is not None
    raise last_err


def _parse_plan_days(raw_days: Any) -> list[PlanDay]:
    if not isinstance(raw_days, list):
        raise LLMOutputError("'days' is not a list")

    days: list[PlanDay] = []
    for day in raw_days:
        if not isinstance(day, dict):
            raise LLMOutputError(f"invalid day item: {day!r}")
        try:
            day_date = date.fromisoformat(str(day["date"]))
            tasks = [
                TaskCandidate(
                    title=item["title"],
                    due_date=date.fromisoformat(str(item["due_date"])),
                    tags=item.get("tags") or [],
                )
                for item in day.get("tasks", [])
            ]
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid plan day {day!r}: {err}") from err
        days.append({"date": day_date, "tasks": tasks})
    return days


@dataclass
class QwenLLM:
    """Qwen2.5-Instruct 로 todo_creation LLMPort 를 구현한다."""

    base_url: str
    model: str = DEFAULT_QWEN_MODEL
    api_key: str = "EMPTY"
    temperature: float = 0.1
    max_tokens: int = 800
    timeout_seconds: float = 90.0

    async def complete_raw(
        self, *, messages: list[dict[str, str]], label: str = "qwen"
    ) -> str:
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
        except httpx.HTTPStatusError as err:
            body = err.response.text[:200] if err.response is not None else ""
            status = err.response.status_code if err.response is not None else "unknown"
            raise LLMFailedError(
                f"qwen call failed at {label}: status={status}, body={body}"
            ) from err
        except httpx.TimeoutException as err:
            raise LLMFailedError(
                f"qwen call timed out at {label} "
                f"(timeout_seconds={self.timeout_seconds}): {err}"
            ) from err
        except httpx.HTTPError as err:
            raise LLMFailedError(f"qwen call failed at {label}: {err}") from err

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError, ValueError) as err:
            raise LLMOutputError(
                f"invalid qwen response envelope: {response.text[:200]}"
            ) from err

    async def split_tasks(self, *, prompt: str, today: date) -> SplitResult:
        messages = build_task_splitter_messages(prompt=prompt, today=today)
        last_err: LLMOutputError | None = None

        for attempt in range(2):
            raw = await self.complete_raw(messages=messages, label="split_tasks")
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
        self,
        *,
        history: list[Turn],
        message: str,
        today: date,
        user_profile_memory: dict[str, Any] | None = None,
    ) -> tuple[bool, list[str], ParsedGoal]:
        messages = [
            {"role": "system", "content": PLANNER_JUDGE_SYSTEM},
            {
                "role": "user",
                "content": planner_judge_user(
                    history=_as_jsonable(history),
                    message=message,
                    today=today,
                    user_profile_memory=user_profile_memory,
                ),
            },
        ]
        parsed = await _complete_json_with_retry(
            self, messages=messages, label="judge_sufficiency"
        )
        goal = parsed.get("parsed_goal") or {}
        if not isinstance(goal, dict):
            raise LLMOutputError("'parsed_goal' is not an object")

        deadline = goal.get("deadline")
        if deadline:
            try:
                goal["deadline"] = date.fromisoformat(str(deadline))
            except ValueError as err:
                raise LLMOutputError(f"invalid deadline: {deadline!r}") from err
        else:
            goal["deadline"] = None

        intent = parsed.get("intent") or goal.get("intent") or "plan"
        goal["intent"] = intent
        goal["goal_tag"] = str(goal.get("goal_tag") or goal.get("goal_text") or "목표")[:20]
        missing = parsed.get("missing_aspects") or []
        if not isinstance(missing, list):
            raise LLMOutputError("'missing_aspects' is not a list")

        plan_kind = goal.get("plan_kind")
        raw_slots = goal.get("slots")
        slots = raw_slots if isinstance(raw_slots, dict) else {}
        goal["slots"] = slots
        if isinstance(plan_kind, str) and plan_kind in SLOT_SCHEMAS:
            goal["plan_kind"] = plan_kind
        else:
            goal.pop("plan_kind", None)
            plan_kind = None

        # 일상 종류(routine/vague_goal/lifestyle)는 스키마 뱅크로 충족을 코드 결정한다.
        # exam·미분류는 모델의 is_sufficient/missing_aspects 를 그대로 신뢰(기존 거동 보존).
        if intent == "plan" and plan_kind in _SCHEMA_DRIVEN_KINDS:
            filled = {k for k, v in slots.items() if v not in (None, "", [], {})}
            schema_missing = missing_required(plan_kind, filled)
            return (not schema_missing), schema_missing, goal

        return bool(parsed.get("is_sufficient")), [str(x) for x in missing], goal

    async def generate_follow_up_question(
        self,
        *,
        missing_aspects: list[str],
        history: list[Turn],
        enrichment_context: dict | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": FOLLOW_UP_SYSTEM},
            {
                "role": "user",
                "content": follow_up_user(
                    missing_aspects=missing_aspects,
                    history=_as_jsonable(history),
                    enrichment_context=enrichment_context,
                ),
            },
        ]
        parsed = await _complete_json_with_retry(self, messages=messages, label="follow_up")
        question = str(parsed.get("question") or "").strip()
        if not question:
            raise LLMOutputError("empty follow-up question")
        return question[:300]

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        system = PLAN_GENERATOR_SYSTEM
        goal_tag = str(parsed_goal.get("goal_tag") or "")
        wiki = load_wiki(goal_tag) if goal_tag else None
        if wiki:
            system = (
                system
                + f"\n\n[도메인 지식 — {goal_tag}]\n"
                "아래는 이 목표에 특화된 학습 전략 위키다. "
                "플랜 생성 시 태스크 이름과 순서를 이 위키에 맞춰 만들어라.\n\n"
                + wiki
            )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": plan_generator_user(
                    parsed_goal=_as_jsonable(parsed_goal), today=today
                ),
            },
        ]
        parsed = await _complete_json_with_retry(self, messages=messages, label="plan")
        summary = str(parsed.get("summary_text") or "").strip()
        if "profile_memory_patch" in parsed:
            parsed_goal["profile_memory_patch"] = parsed.get("profile_memory_patch") or {}
        return summary, _parse_plan_days(parsed.get("days"))

    async def generate_goal_tag(
        self, *, parsed_goal: ParsedGoal, history: list[Turn]
    ) -> str:
        messages = [
            {"role": "system", "content": GOAL_TAG_SYSTEM},
            {
                "role": "user",
                "content": goal_tag_user(
                    parsed_goal=_as_jsonable(parsed_goal),
                    history=_as_jsonable(history),
                ),
            },
        ]
        parsed = await _complete_json_with_retry(self, messages=messages, label="goal_tag")
        goal_tag = str(parsed.get("goal_tag") or "").strip()
        if not goal_tag:
            raise LLMOutputError("empty goal_tag")
        return goal_tag[:20]

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        goal_tag = str(parsed_goal.get("goal_tag") or parsed_goal.get("goal_text") or "목표")
        goal_tag = goal_tag.strip()[:20] or "목표"
        return [
            {
                **day,
                "tasks": [
                    task.model_copy(update={"tags": [goal_tag]})
                    for task in day.get("tasks", [])
                ],
            }
            for day in plan
        ]
