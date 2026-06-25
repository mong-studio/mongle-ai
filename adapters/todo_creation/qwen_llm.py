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
from typing import Any, cast

import httpx

from adapters.todo_creation._domain_wiki import load_wiki
from adapters.todo_creation._prompts import (
    FOLLOW_UP_SYSTEM,
    GOAL_TAG_SYSTEM,
    OUT_OF_SCOPE_REPLY_SYSTEM,
    PLAN_GENERATOR_SYSTEM,
    PLAN_VALIDATOR_SYSTEM,
    PLANNER_JUDGE_SYSTEM,
    REQUEST_CLASSIFIER_SYSTEM,
    TASK_SPLITTER_SYSTEM,
    follow_up_user,
    goal_tag_user,
    out_of_scope_reply_user,
    plan_generator_user,
    plan_validator_user,
    planner_judge_user,
    request_classifier_user,
    task_splitter_user,
)
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.planner.allocator import cadence_is_specific
from agents.todo_creation.planner.slot_schemas import SLOT_SCHEMAS, missing_required
from agents.todo_creation.schemas import MAX_TAG_LENGTH, SplitResult, TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn
from agents.todo_creation.todo.when_resolver import resolve_when

# 스키마 뱅크로 충족을 코드 결정하는 일상 종류.
_SCHEMA_DRIVEN_KINDS = frozenset(
    {"event", "routine", "vague_goal", "lifestyle", "project"}
)

log = logging.getLogger(__name__)

DEFAULT_QWEN_MODEL = "Qwen/Qwen2.5-7B-Instruct"

_JSON_REINFORCE = (
    "직전 응답은 파싱할 수 없다. 설명 없이 요청한 스키마의 JSON 객체 하나만 다시 출력하라. "
    "코드 펜스, 주석, 마크다운, 추가 문장을 절대 포함하지 마라."
)




# ponytail: base 모델이 가끔 구조 토큰 사이에 잉여 따옴표(]"} 처럼)를 뱉어 JSON 이 깨진다.
# 진짜 해결은 워커 측 guided/json decoding 이지만 그건 RunPod 워커 코드 소관(이 repo 밖).
# 닫는 괄호와 닫는 괄호/쉼표 사이에 낀 따옴표는 항상 무효 JSON 이라 안전하게 제거한다.
_WEDGED_QUOTE = re.compile(r'(?<=[}\]])"(?=\s*[}\],])')


def _loads_tolerant(stripped: str) -> Any:
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Qwen이 문자열 안의 줄바꿈을 이스케이프하지 않거나 구조 토큰 사이에
        # 잉여 따옴표를 넣는 경우만 제한적으로 복구한다.
        repaired = _WEDGED_QUOTE.sub("", stripped)
        try:
            return json.loads(repaired, strict=False)
        except json.JSONDecodeError:
            return json.loads(_trim_truncated_top_level_object(repaired), strict=False)


def _trim_truncated_top_level_object(raw: str) -> str:
    """뒤쪽 필드가 잘린 객체에서 완성된 top-level 필드만 보존한다.

    예: {"summary_text":"...", "days":[...], "personalization_patch":{"plann
    처럼 optional 뒤쪽 필드가 끊기면 마지막 top-level 쉼표 앞까지만 남기고
    객체를 닫는다. 중첩 객체/배열 내부 쉼표는 건드리지 않는다.
    """

    stripped = raw.strip()
    if not stripped.startswith("{"):
        raise json.JSONDecodeError("not an object", raw, 0)
    depth = 0
    in_string = False
    escaped = False
    last_top_level_comma = -1
    for index, char in enumerate(stripped):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 1:
            last_top_level_comma = index
    if last_top_level_comma == -1:
        raise json.JSONDecodeError("no complete top-level field", raw, 0)
    return stripped[:last_top_level_comma].rstrip() + "}"


def strip_json_fence(raw: str) -> str:
    """응답에서 첫 JSON 객체만 추출. 앞뒤 코드펜스·산문·꼬리 펜스를 허용한다."""
    start = raw.find("{")
    if start == -1:
        return raw.strip()
    try:
        _, end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError:
        return raw[start:].strip()
    return raw[start:end]


def _first_object_with_key(raw: str, key: str) -> dict[str, Any] | None:
    """raw 안의 모든 { 후보를 훑어 `key` 를 가진 첫 디코딩 가능 객체를 반환.

    base 모델이 깨진 JSON 뒤에 '정정' 객체를 다시 뱉거나(rambling) 산문을 섞을 때,
    스키마 마커(key)를 가진 진짜 객체를 건져낸다.
    """
    dec = json.JSONDecoder()
    idx = raw.find("{")
    while idx != -1:
        try:
            obj, _ = dec.raw_decode(raw, idx)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and key in obj:
            return obj
        idx = raw.find("{", idx + 1)
    return None


def _parse_split_object(raw: str) -> dict[str, Any]:
    """분해기 응답에서 split 객체(dict)를 최대한 견고하게 복구한다.

    1) 첫 객체 정상/잉여따옴표 → strip_json_fence + _loads_tolerant
    2) rambling·롤누수·산문 혼입 → tasks 키를 가진 객체를 스캔으로 건짐
    """
    stripped = strip_json_fence(raw)
    try:
        cand = _loads_tolerant(stripped)
        if isinstance(cand, dict) and "tasks" in cand:
            return cand
    except json.JSONDecodeError:
        pass
    salvaged = _first_object_with_key(raw, "tasks")
    if isinstance(salvaged, dict):
        return salvaged
    raise LLMOutputError(f"non-JSON response: {stripped[:200]}")




def build_task_splitter_messages(*, prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TASK_SPLITTER_SYSTEM},
        {"role": "user", "content": task_splitter_user(prompt)},
    ]


def parse_task_response(raw: str, today: date) -> SplitResult:
    """뉴로-심볼릭 응답 파싱: 모델의 when 구문을 resolve_when 으로 절대날짜화."""
    parsed = _parse_split_object(raw)

    intent = parsed.get("intent")
    if intent not in ("plan", "out_of_scope"):
        intent = "plan"
    if intent == "out_of_scope":
        return SplitResult(intent="out_of_scope", tasks=[])

    if "tasks" not in parsed:
        raise LLMOutputError(f"missing 'tasks' key: {raw[:200]}")
    tasks_raw = parsed["tasks"]
    if not isinstance(tasks_raw, list):
        raise LLMOutputError("'tasks' is not a list")

    out: list[TaskCandidate] = []
    for item in tasks_raw:
        try:
            out.append(
                TaskCandidate(
                    title=item["title"],
                    due_date=resolve_when(item.get("when"), today),
                    tags=item.get("tags") or [],
                )
            )
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid task item {item!r}: {err}") from err
    return SplitResult(intent="plan", tasks=out)




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
        parsed = _loads_tolerant(stripped)
    except json.JSONDecodeError as err:
        raise LLMOutputError(f"non-JSON response: {stripped[:200]}") from err
    if not isinstance(parsed, dict):
        raise LLMOutputError(f"JSON response is not an object: {stripped[:200]}")
    return parsed


# near-greedy(temp 0.1)는 파싱 실패 시 재시도해도 같은 망가진 JSON 을 반복한다.
# 재시도는 high-temp 로 샘플링 다양성을 줘 결정론적 실패를 탈출한다.
_RETRY_TEMPERATURE = 0.7

# 한국어-only 제목 패턴: 한글 음절 + 숫자 + 공백 + 한국어 흔한 구두점만 허용.
# 외국 문자를 토큰 단계에서 차단 → 모델이 한글 표현으로 우회.
# 대문자(IT, SQL, GitHub 등 통용 약어)는 허용, 소문자 단독 라틴어만 차단.
_KOREAN_TITLE_PATTERN = r"^[가-힣A-Z0-9 ()·,.~/%\-]+$"
_ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# 채팅 문장용 한국어-only 패턴: 제목 패턴에 문장 부호(!?…줄바꿈)만 추가.
# 중국어·일본어 한자/가나는 화이트리스트에 없어 토큰 단계에서 차단된다.
_KOREAN_SENTENCE_PATTERN = r"^[가-힣A-Z0-9 ()·,.!?~/%\-…\n]+$"


def _korean_text_schema(field: str) -> dict[str, Any]:
    """follow_up/out_of_scope 처럼 자유 문장 1개 필드를 한국어-only 로 제약."""
    return {
        "type": "object",
        "properties": {field: {"type": "string", "pattern": _KOREAN_SENTENCE_PATTERN}},
        "required": [field],
    }


def plan_guided_schema() -> dict[str, Any]:
    """generate_plan 의 vLLM guided_json 스키마 — task.title 을 한국어-only 로 제약."""
    task = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "pattern": _KOREAN_TITLE_PATTERN},
            "due_date": {"type": "string", "pattern": _ISO_DATE_PATTERN},
        },
        "required": ["title", "due_date"],
    }
    day = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "pattern": _ISO_DATE_PATTERN},
            "tasks": {"type": "array", "items": task},
        },
        "required": ["date", "tasks"],
    }
    return {
        "type": "object",
        "properties": {
            "summary_text": {"type": "string"},
            "days": {"type": "array", "items": day},
            "personalization_patch": {"type": "object"},
        },
        "required": ["summary_text", "days"],
    }


async def _complete_json_with_retry(
    llm: "QwenLLM",
    *,
    messages: list[dict[str, str]],
    label: str,
    required_keys: tuple[str, ...] = (),
    temperature: float | None = None,
    guided_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last_err: LLMOutputError | None = None
    current = messages
    retry_temp = (
        _RETRY_TEMPERATURE
        if temperature is None
        else max(temperature, _RETRY_TEMPERATURE)
    )
    for attempt in range(2):
        raw = await llm.complete_raw(
            messages=current,
            label=label,
            temperature=temperature if attempt == 0 else retry_temp,
            guided_json=guided_json,
        )
        try:
            parsed = _parse_json_object(raw)
            missing = [key for key in required_keys if key not in parsed]
            if missing:
                raise LLMOutputError("missing required JSON keys: " + ", ".join(missing))
            return parsed
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
    max_tokens: int = 2400
    timeout_seconds: float = 90.0
    top_p: float = 0.8
    top_k: int = 20
    repetition_penalty: float = 1.05

    async def complete_raw(
        self,
        *,
        messages: list[dict[str, str]],
        label: str = "qwen",
        temperature: float | None = None,
        guided_json: dict[str, Any] | None = None,
    ) -> str:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        if guided_json is not None:
            # backend 선택은 서버의 structured-output 설정(auto)에 맡긴다.
            payload["guided_json"] = guided_json
        else:
            payload["response_format"] = {"type": "json_object"}
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
        """뉴로-심볼릭 분해기: 모델은 task별 when 구문만 추출하고
        절대날짜는 resolve_when 이 결정적으로 계산한다."""
        messages = build_task_splitter_messages(prompt=prompt)
        last_err: LLMOutputError | None = None

        for attempt in range(2):
            raw = await self.complete_raw(messages=messages, label="split_tasks")
            try:
                return parse_task_response(raw, today)
            except LLMOutputError as err:
                last_err = err
                log.warning(
                    "qwen split_tasks parse fail (attempt %d): %s", attempt + 1, err
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": _JSON_REINFORCE},
                ]

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
        goal_obj = parsed.get("parsed_goal") or {}
        if not isinstance(goal_obj, dict):
            raise LLMOutputError("'parsed_goal' is not an object")
        goal = cast(ParsedGoal, goal_obj)

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
        goal["goal_tag"] = str(goal.get("goal_tag") or goal.get("goal_text") or "목표")[
            :MAX_TAG_LENGTH
        ]
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
            plan_kind = "project" if intent == "plan" else None
            if plan_kind is not None:
                goal["plan_kind"] = plan_kind
            else:
                goal.pop("plan_kind", None)

        # 일반 계획 종류는 스키마 뱅크로 충족을 코드 결정한다.
        # exam 은 시험마다 필수 정보가 달라 모델 판단과 planner_node 의 도메인 보정을 함께 쓴다.
        if intent == "plan" and plan_kind in _SCHEMA_DRIVEN_KINDS:
            filled = {k for k, v in slots.items() if v not in (None, "", [], {})}
            if plan_kind == "project":
                if str(goal.get("goal_text") or "").strip():
                    filled.add("goal")
                if goal.get("deadline"):
                    filled.add("horizon")
                if goal.get("daily_capacity_minutes"):
                    filled.add("available_time")
            # routine: cadence 가 채워졌어도 '매주'처럼 빈도(주 N회/요일)가 없으면
            # 모호하므로 미충족으로 보고 cadence 를 되묻는다.
            if (
                plan_kind == "routine"
                and "cadence" in filled
                and not cadence_is_specific(str(slots.get("cadence") or ""))
            ):
                filled.discard("cadence")
            schema_missing = missing_required(plan_kind, filled)
            if plan_kind == "project":
                schema_missing = list(
                    dict.fromkeys(
                        [
                            *[
                                str(item)
                                for item in missing
                                if str(item) not in filled
                            ],
                            *schema_missing,
                        ]
                    )
                )
            return (not schema_missing), schema_missing, goal

        return bool(parsed.get("is_sufficient")), [str(x) for x in missing], goal

    async def classify_request(
        self,
        *,
        history: list[Turn],
        message: str,
        has_existing_goal: bool,
    ) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": REQUEST_CLASSIFIER_SYSTEM},
            {
                "role": "user",
                "content": request_classifier_user(
                    history=_as_jsonable(history),
                    message=message,
                    has_existing_goal=has_existing_goal,
                ),
            },
        ]
        parsed = await _complete_json_with_retry(
            self, messages=messages, label="classify_request"
        )
        intent = str(parsed.get("intent") or "planning")
        if intent not in {"planning", "conversation", "continuation"}:
            intent = "planning"
        plan_kind = parsed.get("plan_kind")
        if plan_kind not in SLOT_SCHEMAS:
            plan_kind = "project" if intent != "conversation" else None
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = parsed.get("evidence") or []
        return {
            "intent": intent,
            "plan_kind": plan_kind,
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence": [str(item) for item in evidence if str(item).strip()][:5],
            "unknown_entity": (
                str(parsed.get("unknown_entity")).strip()
                if parsed.get("unknown_entity")
                else None
            ),
        }

    async def generate_follow_up_question(
        self,
        *,
        missing_aspects: list[str],
        history: list[Turn],
    ) -> str:
        messages = [
            {"role": "system", "content": FOLLOW_UP_SYSTEM},
            {
                "role": "user",
                "content": follow_up_user(
                    missing_aspects=missing_aspects,
                    history=_as_jsonable(history),
                ),
            },
        ]
        parsed = await _complete_json_with_retry(
            self,
            messages=messages,
            label="follow_up",
            guided_json=_korean_text_schema("question"),
        )
        question = str(parsed.get("question") or "").strip()
        if not question:
            raise LLMOutputError("empty follow-up question")
        return question[:300]

    async def generate_out_of_scope_reply(
        self,
        *,
        message: str,
        history: list[Turn],
    ) -> str:
        messages = [
            {"role": "system", "content": OUT_OF_SCOPE_REPLY_SYSTEM},
            {
                "role": "user",
                "content": out_of_scope_reply_user(
                    message=message,
                    history=_as_jsonable(history),
                ),
            },
        ]
        parsed = await _complete_json_with_retry(
            self,
            messages=messages,
            label="out_of_scope_reply",
            guided_json=_korean_text_schema("reply"),
        )
        reply = str(parsed.get("reply") or "").strip()
        if not reply:
            raise LLMOutputError("empty out-of-scope reply")
        return reply[:180]

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        system = PLAN_GENERATOR_SYSTEM
        goal_tag = str(parsed_goal.get("goal_tag") or "")
        wiki = load_wiki(goal_tag) if goal_tag else None
        if wiki:
            system = (
                system + f"\n\n[도메인 지식 — {goal_tag}]\n"
                "아래는 이 목표에 특화된 학습 전략 위키다. "
                "플랜 생성 시 태스크 이름과 순서를 이 위키에 맞춰 만들어라.\n\n" + wiki
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
        parsed = await _complete_json_with_retry(
            self,
            messages=messages,
            label="plan",
            required_keys=("days",),
            # 외국 문자 차단: task.title 을 한국어-only 로 강제(guided_json).
            guided_json=plan_guided_schema(),
        )
        summary = str(parsed.get("summary_text") or "").strip()
        if "personalization_patch" in parsed:
            parsed_goal["personalization_patch"] = parsed.get("personalization_patch") or {}
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
        parsed = await _complete_json_with_retry(
            self, messages=messages, label="goal_tag"
        )
        goal_tag = str(parsed.get("goal_tag") or "").strip()
        if not goal_tag:
            raise LLMOutputError("empty goal_tag")
        return goal_tag[:MAX_TAG_LENGTH]

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        goal_tag = str(
            parsed_goal.get("goal_tag") or parsed_goal.get("goal_text") or "목표"
        )
        goal_tag = goal_tag.strip()[:MAX_TAG_LENGTH] or "목표"
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

    async def validate_plan(
        self,
        *,
        plan: list[PlanDay],
        summary_text: str,
        parsed_goal: ParsedGoal,
        today: date,
    ) -> tuple[bool, list[str]]:
        messages = [
            {"role": "system", "content": PLAN_VALIDATOR_SYSTEM},
            {
                "role": "user",
                "content": plan_validator_user(
                    parsed_goal=_as_jsonable(parsed_goal),
                    summary_text=summary_text,
                    days=_as_jsonable(plan),
                    today=today,
                ),
            },
        ]
        parsed = await _complete_json_with_retry(
            self, messages=messages, label="validate_plan"
        )
        issues = parsed.get("issues") or []
        if not isinstance(issues, list):
            raise LLMOutputError("'issues' is not a list")
        return bool(parsed.get("valid")), [str(item) for item in issues]
