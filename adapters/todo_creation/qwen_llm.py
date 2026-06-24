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
    PLAN_CRITIC_SYSTEM,
    PLAN_GENERATOR_SYSTEM,
    PLANNER_JUDGE_SYSTEM,
    TASK_SPLITTER_SYSTEM,
    follow_up_user,
    goal_tag_user,
    plan_critic_user,
    plan_generator_user,
    planner_judge_user,
    task_splitter_user,
)
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.planner.allocator import cadence_is_specific
from agents.todo_creation.planner.slot_schemas import SLOT_SCHEMAS, missing_required
from agents.todo_creation.schemas import SplitResult, TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay, Turn
from agents.todo_creation.todo.when_resolver import resolve_when

# 스키마 뱅크로 충족을 코드 결정하는 일상 종류(exam 은 기존 모델·deadline 휴리스틱 유지).
_SCHEMA_DRIVEN_KINDS = frozenset({"routine", "vague_goal", "lifestyle"})

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
        # 1회 복구 시도 — 재실패하면 원래 JSONDecodeError 를 그대로 전파
        return json.loads(_WEDGED_QUOTE.sub("", stripped))


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
        if isinstance(cand, dict):
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
# 재시도는 high-temp 로 샘플링 다양성을 줘 결정론적 실패를 탈출한다(critic 재생성과 동일 레버).
_RETRY_TEMPERATURE = 0.7


async def _complete_json_with_retry(
    llm: "QwenLLM",
    *,
    messages: list[dict[str, str]],
    label: str,
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
                    difficulty=int(item.get("difficulty") or 1),
                )
                for item in day.get("tasks", [])
            ]
        except (KeyError, ValueError, TypeError) as err:
            raise LLMOutputError(f"invalid plan day {day!r}: {err}") from err
        days.append({"date": day_date, "tasks": tasks})
    return days


# 한국어-only 제목 패턴: 한글 음절 + 숫자 + 공백 + 한국어 흔한 구두점만 허용.
# 한자('备')·라틴('prech') 등 외국 문자를 토큰 단계에서 차단 → 모델이 한글 표현으로 우회.
# (repair 는 사용자 입력을 복사하는 TODO 에만 통함. 플래너 제목은 생성물이라 복원 원본이 없음.)
_KOREAN_TITLE_PATTERN = r"^[가-힣0-9 ()·,.~/%\-]+$"
_ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def plan_guided_schema() -> dict[str, Any]:
    """generate_plan 의 vLLM guided_json(outlines) 스키마.

    구조를 강제(JSON 유효성 덤)하고 task.title 을 한국어-only 로 제약한다.
    summary_text/rationale 는 날짜·괄호가 정상 등장하므로 제약하지 않는다(과제약 방지).
    """
    task = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "pattern": _KOREAN_TITLE_PATTERN},
            "due_date": {"type": "string", "pattern": _ISO_DATE_PATTERN},
            "difficulty": {"type": "integer"},
        },
        "required": ["title", "due_date", "difficulty"],
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
            "rationale": {"type": "string"},
            "personalization_patch": {"type": "object"},
            "days": {"type": "array", "items": day},
        },
        "required": ["summary_text", "days"],
    }


_VERDICT_CATEGORIES = frozenset(
    {"load", "order", "progression", "coherence", "rationale"}
)


def _normalize_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    """critic verdict 를 안전한 형태로 정규화한다.

    결손·오타 필드를 기본값으로 채우고, major 이슈가 하나라도 있으면 모델의 ok 값과
    무관하게 ok 를 False 로 강등한다(방어적).
    """
    raw_issues = raw.get("issues")
    issues: list[dict[str, Any]] = []
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            day = item.get("day")
            issues.append(
                {
                    "day": day if isinstance(day, str) else None,
                    "category": category
                    if category in _VERDICT_CATEGORIES
                    else "coherence",
                    "severity": "major" if item.get("severity") == "major" else "minor",
                    "detail": str(item.get("detail") or ""),
                    "suggested_fix": str(item.get("suggested_fix") or ""),
                }
            )
    has_major = any(issue["severity"] == "major" for issue in issues)
    # ok 진리값 정규화: 문자열 "false" 같은 퇴화 출력을 truthy 로 오인하지 않는다.
    raw_ok = raw.get("ok", True)
    model_ok = raw_ok is True or str(raw_ok).strip().lower() == "true"
    return {"ok": model_ok and not has_major, "issues": issues}


@dataclass
class QwenLLM:
    """Qwen2.5-Instruct 로 todo_creation LLMPort 를 구현한다."""

    base_url: str
    model: str = DEFAULT_QWEN_MODEL
    api_key: str = "EMPTY"
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout_seconds: float = 90.0
    # worker 가 SamplingParams 로 전달받는다(미설정 시 near-greedy 퇴화 방지).
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
            # top_p 만 표준 OpenAI 필드라 범용 HTTP 경로에 보낸다. top_k/repetition_penalty
            # 는 비표준이라 순수 OpenAI 서버에서 400 → RunPod(vLLM) 경로에서만 전송한다.
            "top_p": self.top_p,
        }
        if guided_json is not None:
            # vLLM OpenAI 서버 확장 필드. 외국 문자 차단엔 pattern 지원이 확실한 outlines 백엔드.
            payload["guided_json"] = guided_json
            payload["guided_decoding_backend"] = "outlines"
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
            :20
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
            goal.pop("plan_kind", None)
            plan_kind = None

        # 일상 종류(routine/vague_goal/lifestyle)는 스키마 뱅크로 충족을 코드 결정한다.
        # exam·미분류는 모델의 is_sufficient/missing_aspects 를 그대로 신뢰(기존 거동 보존).
        if intent == "plan" and plan_kind in _SCHEMA_DRIVEN_KINDS:
            filled = {k for k, v in slots.items() if v not in (None, "", [], {})}
            # routine: cadence 가 채워졌어도 '매주'처럼 빈도(주 N회/요일)가 없으면
            # 모호하므로 미충족으로 보고 cadence 를 되묻는다.
            if (
                plan_kind == "routine"
                and "cadence" in filled
                and not cadence_is_specific(str(slots.get("cadence") or ""))
            ):
                filled.discard("cadence")
            schema_missing = missing_required(plan_kind, filled)
            return (not schema_missing), schema_missing, goal

        return bool(parsed.get("is_sufficient")), [str(x) for x in missing], goal

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
            self, messages=messages, label="follow_up"
        )
        question = str(parsed.get("question") or "").strip()
        if not question:
            raise LLMOutputError("empty follow-up question")
        return question[:300]

    async def generate_plan(
        self,
        *,
        parsed_goal: ParsedGoal,
        today: date,
        temperature: float | None = None,
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
            temperature=temperature,
            # 외국 문자 차단: task.title 을 한국어-only 로 강제(outlines guided_json).
            guided_json=plan_guided_schema(),
        )
        summary = str(parsed.get("summary_text") or "").strip()
        if "personalization_patch" in parsed:
            parsed_goal["personalization_patch"] = (
                parsed.get("personalization_patch") or {}
            )
        # rationale(객관 근거)를 parsed_goal 에 실어 critic 이 검증하게 한다(plan_critic_user
        # 가 parsed_goal 을 통째 직렬화하므로 시그니처 변경 없이 흐른다).
        rationale = str(parsed.get("rationale") or "").strip()
        if rationale:
            parsed_goal["rationale"] = rationale[:200]
        return summary, _parse_plan_days(parsed.get("days"))

    async def critique_plan(
        self,
        *,
        parsed_goal: ParsedGoal,
        plan: list[PlanDay],
        today: date,
        overloaded_days: list[str] | None = None,
    ) -> dict[str, Any]:
        """생성된 계획의 soft 품질(논리·부하·순서·페이싱)을 비평한다.

        하드 제약(마감 등)은 코드가 이미 처리했으므로 보지 않는다. verdict 가 끝까지
        파싱되지 않으면 ok=True 로 통과시킨다(fail-open — 이미 하드 제약을 통과한
        계획의 배달을 critic 파싱 실패로 막지 않는다).
        """
        messages = [
            {"role": "system", "content": PLAN_CRITIC_SYSTEM},
            {
                "role": "user",
                "content": plan_critic_user(
                    parsed_goal=_as_jsonable(parsed_goal),
                    plan_json=_as_jsonable(plan),
                    today=today,
                    overloaded_days=overloaded_days or [],
                ),
            },
        ]
        try:
            parsed = await _complete_json_with_retry(
                self, messages=messages, label="critique"
            )
        except LLMOutputError:
            return {"ok": True, "issues": []}
        return _normalize_verdict(parsed)

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
        return goal_tag[:20]

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        goal_tag = str(
            parsed_goal.get("goal_tag") or parsed_goal.get("goal_text") or "목표"
        )
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
