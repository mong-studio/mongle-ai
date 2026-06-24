"""multi 모드 planner 노드.

LLMPort.judge_sufficiency 결과로 `Command(goto='plan_generator' | 'follow_up')`
분기. parsed_goal/sufficiency/missing_aspects 를 state 업데이트.

재시도 정책은 graph 등록 시점(`add_node(..., retry=RetryPolicy(3, LLMFailedError))`).
JSON 파싱 실패 등 LLMOutputError 는 그대로 raise.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.planner.goal_rules import (
    build_recovery_goal,
    delegates_planning,
    merge_deadline_from_state,
    needs_deadline_follow_up,
    should_accept_out_of_scope,
)
from agents.todo_creation.planner.schedule_lookup import resolve_exam_deadline
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.state import ParsedGoal, Turn


async def planner_node(
    state: PlannerGraphState, config: RunnableConfig
) -> Command[str]:
    llm = get_ports(config).llm
    existing_goal = state.get("parsed_goal")
    # routine 은 결정적 전개(expand_routine)라 revision_request 텍스트를 못 읽는다.
    # revision 시 judge 를 재실행해 cadence 슬롯을 갱신·재전개하도록 단락을 건너뛴다.
    is_routine = bool(existing_goal and existing_goal.get("plan_kind") == "routine")
    if state.get("revision_request") and state.get("plan") and not is_routine:
        previous_plan = state.get("plan") or []
        revision_goal: ParsedGoal = cast(
            ParsedGoal,
            existing_goal.copy() if existing_goal is not None else {},
        )
        revision_goal["revision_request"] = state.get("revision_request")
        revision_goal["previous_plan"] = previous_plan
        revision_goal["user_profile_memory"] = state.get("user_profile_memory") or {}
        return _plan_command(
            parsed_goal=revision_goal,
            sufficient=True,
            missing=[],
        )

    if _follow_up_count(state.get("history", [])) >= 2:
        return _plan_command(
            parsed_goal=build_recovery_goal(state), sufficient=True, missing=[]
        )

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
        and not should_accept_out_of_scope(state)
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
        cast(ParsedGoal, parsed.copy()) if parsed is not None else None
    )
    if resolved_goal is not None:
        # exam·시험일 미상·공식 도메인 아는 시험만, 실패·불확실 시 아래 follow_up 폴백.
        today_val = state.get("today")
        if today_val is not None:
            await resolve_exam_deadline(
                resolved_goal,
                today=today_val,
                # 옵셔널 포트: 미설정/미니 스텁이면 None → 기존 되묻기 거동.
                lookup=getattr(get_ports(config), "exam_schedule_lookup", None),
            )
        # routine 은 요일 단어가 cadence(주기)라 deadline 으로 오인하면 안 된다
        # (예: "매주 월요일" 의 '월요일' 을 마감일로 파싱해 horizon 을 clamp 하는 버그 방지).
        if resolved_goal.get("plan_kind") != "routine":
            merge_deadline_from_state(state, resolved_goal)
            if resolved_goal.get("deadline") and "deadline" in (missing or []):
                missing = [item for item in missing if item != "deadline"]
                if not missing:
                    sufficient = True
        resolved_goal["user_profile_memory"] = state.get("user_profile_memory") or {}

    if delegates_planning(state.get("message", "")) and resolved_goal:
        sufficient = True
        missing = []

    if sufficient and needs_deadline_follow_up(state, resolved_goal):
        return Command(
            goto="follow_up",
            update={
                "sufficiency": False,
                "missing_aspects": ["deadline"],
                "parsed_goal": resolved_goal,
            },
        )

    return Command(
        goto="plan_generator" if sufficient else "follow_up",
        update={
            "sufficiency": bool(sufficient),
            "missing_aspects": list(missing or []),
            "parsed_goal": resolved_goal,
        },
    )


def _follow_up_count(history: list[Turn]) -> int:
    """assistant 질문 수를 기준으로 꼬리질문 반복 횟수를 계산한다."""

    return sum(
        1
        for turn in history
        if turn.get("role") == "assistant"
        and (
            turn.get("type") == "follow_up"
            or (
                turn.get("type") is None
                and str(turn.get("content") or "").endswith("?")
            )
        )
    )


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
