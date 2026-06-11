from __future__ import annotations

from typing import Any

from agents.todo_creation.planner.date_parser import (
    has_explicit_deadline,
    parse_explicit_deadline,
)
from agents.todo_creation.planner.state import PlannerGraphState
from agents.todo_creation.state import ParsedGoal, Turn

_AMBIGUOUS_DEADLINE_WORDS = ("곧", "조만간", "언젠가", "나중에", "머지않아")
_DEADLINE_SENSITIVE_WORDS = ("시험", "마감", "발표", "면접", "여행", "결혼식", "행사")


def collect_user_text(state: PlannerGraphState) -> str:
    """현재 턴과 이전 user turn 을 하나의 문자열로 합친다."""

    return " ".join(
        [
            str(state.get("message", "")),
            *[
                str(turn.get("content", ""))
                for turn in state.get("history", [])
                if turn.get("role") == "user"
            ],
        ]
    )


def latest_user_goal(history: list[Turn], fallback: str) -> str:
    """반복 질문 fallback 에서 가장 최근 user 목표를 우선 사용한다."""

    for turn in history:
        if turn.get("role") == "user" and str(turn.get("content", "")).strip():
            return str(turn.get("content", "")).strip()
    return fallback


def build_recovery_goal(state: PlannerGraphState) -> ParsedGoal:
    """LLM 이 out_of_scope 로 오판해도 기존 목표 정보를 유지한다."""

    previous: ParsedGoal = state.get("parsed_goal") or {}
    goal_text = previous.get("goal_text") or latest_user_goal(
        state.get("history", []), state.get("message", "")
    )
    parsed_goal: ParsedGoal = previous.copy()
    parsed_goal["intent"] = "plan"
    parsed_goal["goal_text"] = goal_text or "목표"
    parsed_goal["deadline"] = previous.get("deadline")
    parsed_goal["daily_capacity_minutes"] = previous.get("daily_capacity_minutes")
    parsed_goal["user_profile_memory"] = state.get("user_profile_memory") or {}
    merge_deadline_from_state(state, parsed_goal)
    return parsed_goal


def merge_deadline_from_state(
    state: PlannerGraphState, parsed_goal: ParsedGoal
) -> None:
    """사용자 입력에 명시 날짜가 있으면 parsed_goal.deadline 을 보정한다."""

    today = state.get("today")
    if today is None:
        return
    deadline = parse_explicit_deadline(collect_user_text(state), today=today)
    if deadline is not None:
        parsed_goal["deadline"] = deadline


def delegates_planning(message: str) -> bool:
    """사용자가 플래너에게 세부 구성을 맡기는지 판별한다."""

    compact = "".join(str(message).split())
    delegate_words = ("추천해줘", "알아서", "정해줘", "짜줘", "계획해줘", "네가해줘")
    return any(word in compact for word in delegate_words)


def should_accept_out_of_scope(state: PlannerGraphState) -> bool:
    """아주 짧고 명백히 무관한 첫 입력만 out_of_scope 로 수용한다."""

    history = state.get("history", [])
    message = str(state.get("message", "")).strip()
    user_turns = [
        str(turn.get("content", "")).strip()
        for turn in history
        if turn.get("role") == "user" and str(turn.get("content", "")).strip()
    ]
    if len(user_turns) >= 2:
        return False
    if len(message) >= 18:
        return False
    return True


def needs_deadline_follow_up(
    state: PlannerGraphState, parsed_goal: ParsedGoal | None
) -> bool:
    """날짜가 애매한 중요한 목표는 계획 대신 deadline 질문으로 되돌린다."""

    text = collect_user_text(state)
    has_ambiguous_deadline = any(word in text for word in _AMBIGUOUS_DEADLINE_WORDS)
    has_deadline_sensitive_goal = any(word in text for word in _DEADLINE_SENSITIVE_WORDS)
    if has_ambiguous_deadline and has_deadline_sensitive_goal:
        return not _has_explicit_deadline(text, state=state)
    return bool(
        has_deadline_sensitive_goal
        and parsed_goal
        and not parsed_goal.get("deadline")
        and not _has_explicit_deadline(text, state=state)
    )


def _has_explicit_deadline(text: str, *, state: PlannerGraphState) -> bool:
    """절대 날짜/상대 날짜가 있으면 계획 생성으로 진행한다."""

    today = state.get("today")
    if today is not None and has_explicit_deadline(text, today=today):
        return True
    explicit_words = ("이번달", "다음달")
    if any(word in text.replace(" ", "") for word in explicit_words):
        return True
    date_markers = ("일 뒤", "주 뒤", "개월 뒤", "월", "-")
    return any(char.isdigit() for char in text) and any(marker in text for marker in date_markers)
