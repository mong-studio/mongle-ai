"""multi 모드 planner 노드.

LLMPort.judge_sufficiency 결과로 `Command(goto='plan_generator' | 'follow_up')`
분기. parsed_goal/sufficiency/missing_aspects 를 state 업데이트.

재시도 정책은 graph 등록 시점(`add_node(..., retry=RetryPolicy(3, LLMFailedError))`).
JSON 파싱 실패 등 LLMOutputError 는 그대로 raise.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.allocator import (
    cadence_is_specific,
    recover_cadence,
)
from agents.todo_creation.planner.goal_rules import (
    build_recovery_goal,
    delegates_planning,
    has_explicit_exam_context,
    is_competition_event_context,
    merge_deadline_from_state,
    needs_deadline_follow_up,
    is_supported_exam_context,
    normalize_competition_event_goal,
    normalize_supported_exam_goal,
    required_competition_event_missing,
    required_supported_exam_missing,
    should_accept_out_of_scope,
)
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.planner.slot_schemas import missing_required, slot_hints
from agents.todo_creation.state import ParsedGoal, Turn

async def planner_node(
    state: PlannerGraphState, config: RunnableConfig
) -> Command[str]:
    ports = get_ports(config)
    llm = ports.llm
    existing_goal = state.get("parsed_goal")
    is_revision = bool(state.get("revision_request") and state.get("plan"))
    classification = None
    if not _is_routine_candidate(state, existing_goal=existing_goal):
        classification = await _classify_request(
            getattr(ports, "classifier", None),
            history=state.get("history", []),
            message=state.get("message", ""),
            has_existing_goal=existing_goal is not None,
        )
    if (
        classification
        and classification["intent"] == "conversation"
        and existing_goal is None
        and not is_revision
    ):
        return _out_of_scope_command()

    sufficient, missing, parsed = await _judge_sufficiency(
        llm,
        history=state.get("history", []),
        message=state.get("message", ""),
        today=state.get("today"),
        user_profile_memory=state.get("user_profile_memory"),
    )
    if (
        parsed
        and parsed.get("intent") == "out_of_scope"
        and (
            is_revision
            or (classification and classification["intent"] != "conversation")
            or not should_accept_out_of_scope(state)
        )
    ):
        parsed = build_recovery_goal(state)
        sufficient = True
        missing = []

    if parsed and parsed.get("intent") == "out_of_scope":
        return Command(
            goto="out_of_scope",
            update={
                "sufficiency": False,
                "missing_aspects": [],
                "parsed_goal": parsed.copy(),
            },
        )

    resolved_goal: ParsedGoal | None = (
        _merge_goal_context(existing_goal, cast(ParsedGoal, parsed.copy()))
        if parsed is not None
        else (
            normalize_competition_event_goal(state, None)
            if is_competition_event_context(state, None)
            else (
                normalize_supported_exam_goal(state, None)
                if is_supported_exam_context(state, None)
                else None
            )
        )
    )
    if resolved_goal is not None:
        _apply_classification(resolved_goal, classification)
        if is_competition_event_context(state, resolved_goal):
            resolved_goal = normalize_competition_event_goal(state, resolved_goal)
        elif is_supported_exam_context(state, resolved_goal):
            resolved_goal = normalize_supported_exam_goal(state, resolved_goal)
        elif (
            resolved_goal.get("plan_kind") == "exam"
            and not has_explicit_exam_context(state, resolved_goal)
        ):
            resolved_goal["plan_kind"] = "project"
            slots = resolved_goal.get("slots")
            if isinstance(slots, dict):
                resolved_goal["slots"] = {
                    key: value
                    for key, value in slots.items()
                    if key
                    not in {
                        "exam_name",
                        "exam_part",
                        "exam_date",
                        "daily_hours",
                        "current_level",
                        "background",
                        "weak_subjects",
                    }
                }
        # routine 은 요일 단어가 cadence(주기)라 deadline 으로 오인하면 안 된다
        # (예: "매주 월요일" 의 '월요일' 을 마감일로 파싱해 horizon 을 clamp 하는 버그 방지).
        if resolved_goal.get("plan_kind") != "routine":
            merge_deadline_from_state(state, resolved_goal)
            if resolved_goal.get("deadline") and "deadline" in (missing or []):
                missing = [item for item in missing if item != "deadline"]
                if not missing:
                    sufficient = True
        resolved_goal["user_profile_memory"] = state.get("user_profile_memory") or {}
        plan_kind = resolved_goal.get("plan_kind") or "project"
        if plan_kind not in ("exam", "event", "routine", "vague_goal", "lifestyle", "project"):
            plan_kind = "project"
        resolved_goal["plan_kind"] = plan_kind
        # 모델이 "매주 3회" 의 빈도를 "weekly" 로 뭉개 떨어뜨리면 expand_routine 이
        # 주 1회로 펴버린다. 슬롯이 모호하면 원문에서 cadence 를 결정적으로 복구한다.
        if plan_kind == "routine":
            slots = resolved_goal.get("slots") or {}
            recovered = _recover_explicit_cadence(str(state.get("message") or ""))
            if recovered or not cadence_is_specific(str(slots.get("cadence") or "")):
                recovered = recovered or recover_cadence(str(state.get("message") or ""))
                if recovered:
                    resolved_goal["slots"] = {**slots, "cadence": recovered}
        if is_revision:
            resolved_goal["revision_request"] = state.get("revision_request")
            resolved_goal["previous_plan"] = state.get("plan") or []

    if delegates_planning(state.get("message", "")) and resolved_goal:
        sufficient = True
        missing = []

    if resolved_goal is not None:
        if is_competition_event_context(state, resolved_goal):
            missing = required_competition_event_missing(state, resolved_goal)
            sufficient = not missing
        elif is_supported_exam_context(state, resolved_goal):
            missing = required_supported_exam_missing(state, resolved_goal)
            sufficient = not missing
        else:
            slots = resolved_goal.get("slots") or {}
            filled = {
                key
                for key, value in slots.items()
                if value not in (None, "", [], {})
            }
            plan_kind = str(resolved_goal.get("plan_kind") or "project")
            if plan_kind == "project":
                if str(resolved_goal.get("goal_text") or "").strip():
                    filled.add("goal")
                if resolved_goal.get("deadline"):
                    filled.add("horizon")
                if resolved_goal.get("daily_capacity_minutes"):
                    filled.add("available_time")
            # routine: cadence 가 채워졌어도 '매주'처럼 빈도가 없으면 모호 → 되묻는다
            # (judge_sufficiency 의 동일 가드가 이 재계산으로 덮이지 않도록 보장).
            if (
                plan_kind == "routine"
                and "cadence" in filled
                and not cadence_is_specific(str(slots.get("cadence") or ""))
            ):
                filled.discard("cadence")
            schema_missing = missing_required(plan_kind, filled)
            # 모델이 다른 유형의 슬롯을 섞어도 현재 plan_kind 스키마만 따른다.
            missing = schema_missing
            sufficient = not missing

    follow_up_count = int(state.get("follow_up_count") or 0)
    deadline_needed = bool(
        sufficient and needs_deadline_follow_up(state, resolved_goal) and not is_revision
    )
    if deadline_needed:
        if follow_up_count < 2:
            return Command(
                goto="follow_up",
                update={
                    "sufficiency": False,
                    "missing_aspects": ["deadline"],
                    "parsed_goal": resolved_goal,
                },
            )
        sufficient = False
        missing = list(dict.fromkeys(["deadline", *(missing or [])]))

    if resolved_goal is not None and (is_revision or (not sufficient and follow_up_count >= 2)):
        _apply_missing_assumptions(
            resolved_goal,
            missing=list(missing or []),
            today=state.get("today"),
        )
        sufficient = True

    return Command(
        goto="plan_generator" if sufficient else "follow_up",
        update={
            "sufficiency": bool(sufficient),
            "missing_aspects": list(missing or []),
            "parsed_goal": resolved_goal,
        },
    )


def _merge_goal_context(
    existing: ParsedGoal | None, current: ParsedGoal
) -> ParsedGoal:
    """이전 턴에서 확보한 목표/슬롯을 현재 판정 결과에 누적한다."""

    if not existing:
        return current
    merged: ParsedGoal = existing.copy()
    merged.update({key: value for key, value in current.items() if value is not None})
    previous_slots = existing.get("slots")
    current_slots = current.get("slots")
    merged["slots"] = {
        **(previous_slots if isinstance(previous_slots, dict) else {}),
        **(current_slots if isinstance(current_slots, dict) else {}),
    }
    return merged


async def _classify_request(
    classifier: Any,
    *,
    history: list[Turn],
    message: str,
    has_existing_goal: bool,
) -> dict[str, Any] | None:
    if classifier is None:
        return None
    classify = getattr(classifier, "classify_request", None)
    if classify is None:
        return None
    return await classify(
        history=history,
        message=message,
        has_existing_goal=has_existing_goal,
    )


def _apply_classification(
    goal: ParsedGoal, classification: dict[str, Any] | None
) -> None:
    if not classification:
        return
    confidence = float(classification.get("confidence") or 0.0)
    plan_kind = classification.get("plan_kind")
    if classification.get("intent") == "continuation" and (
        confidence < 0.65 or plan_kind is None
    ):
        plan_kind = goal.get("plan_kind") or "project"
    if confidence < 0.65 or plan_kind not in {
        "exam",
        "event",
        "routine",
        "lifestyle",
        "project",
    }:
        if classification.get("intent") != "continuation":
            plan_kind = "project"
    goal["plan_kind"] = cast(Any, plan_kind)
    goal["classification_confidence"] = confidence
    goal["classification_evidence"] = list(classification.get("evidence") or [])
    goal["unknown_entity"] = classification.get("unknown_entity")


def _apply_missing_assumptions(
    goal: ParsedGoal, *, missing: list[str], today: Any
) -> None:
    assumptions = list(goal.get("assumptions") or [])
    if not goal.get("deadline") and today is not None:
        assumptions.append("목표 날짜가 정해지지 않아 첫 30일 실행안으로 구성했어요")
    plan_kind = str(goal.get("plan_kind") or "project")
    for item in missing:
        assumptions.append(_assumption_sentence(plan_kind, item))
    goal["assumptions"] = list(dict.fromkeys(assumptions))


def _assumption_sentence(plan_kind: str, missing_key: str) -> str:
    """내부 슬롯명을 사용자에게 보일 한국어 가정 문장으로 바꾼다."""

    custom = {
        "deadline": "목표 날짜가 정해지지 않아 첫 30일 실행안으로 구성했어요",
        "exam_date": "시험일이 확인되지 않아 가까운 준비 일정 기준으로 잡았어요",
        "event_date": "행사일이 확인되지 않아 가까운 준비 일정 기준으로 잡았어요",
        "horizon": "기간이 확인되지 않아 첫 30일 실행안으로 구성했어요",
        "available_time": "가용 시간이 확인되지 않아 하루 30분 안팎으로 잡았어요",
        "daily_hours": "하루 가능 시간이 확인되지 않아 하루 30분 안팎으로 잡았어요",
        "current_level": "현재 수준이 확인되지 않아 입문 수준으로 잡았어요",
        "background": "경험 배경이 확인되지 않아 처음 해보는 사람도 따라갈 수 있게 잡았어요",
        "weekly_cadence": "주간 빈도가 확인되지 않아 주 2회 기준으로 잡았어요",
    }
    if missing_key in custom:
        return custom[missing_key]
    label = slot_hints(plan_kind, [missing_key])[0]
    if label == missing_key:
        label = "필요한 세부 조건"
    return f"{label}이 확인되지 않아 일반적인 수준으로 잡았어요"


async def _judge_sufficiency(
    llm: Any,
    *,
    history: list[Turn],
    message: str,
    today: Any,
    user_profile_memory: dict[str, Any] | None,
) -> tuple[bool, list[str], ParsedGoal]:
    params = inspect.signature(llm.judge_sufficiency).parameters
    kwargs: dict[str, Any] = {
        "history": history,
        "message": message,
        "today": today,
    }
    if "user_profile_memory" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    ):
        kwargs["user_profile_memory"] = user_profile_memory
    return await llm.judge_sufficiency(**kwargs)


def _is_routine_candidate(
    state: PlannerGraphState, *, existing_goal: ParsedGoal | None
) -> bool:
    """명확한 반복 주기는 classifier를 생략하고 judge 한 번으로 처리한다."""
    if existing_goal and existing_goal.get("plan_kind") == "routine":
        return True
    message = str(state.get("message") or "")
    return bool(_recover_explicit_cadence(message))


def _recover_explicit_cadence(text: str) -> str | None:
    recovered = recover_cadence(text)
    if recovered:
        return recovered
    compact = re.sub(r"[\s,·/&]+", "", text)
    if compact in {"매일", "날마다"}:
        return "매일"
    if re.fullmatch(r"[월화수목금토일]{1,7}", compact):
        return "".join(dict.fromkeys(compact))
    return None


def _plan_command(
    *, parsed_goal: ParsedGoal, sufficient: bool, missing: list[str]
) -> Command[str]:
    return Command(
        goto="plan_generator" if sufficient else "follow_up",
        update={
            "sufficiency": bool(sufficient),
            "missing_aspects": list(missing),
            "parsed_goal": parsed_goal,
        },
    )


def _out_of_scope_command() -> Command[str]:
    return Command(
        goto="out_of_scope",
        update={
            "sufficiency": False,
            "missing_aspects": [],
            "parsed_goal": {"intent": "out_of_scope"},
        },
    )
