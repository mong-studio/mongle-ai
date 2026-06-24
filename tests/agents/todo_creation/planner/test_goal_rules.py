from __future__ import annotations

from datetime import date

from agents.todo_creation.planner.goal_rules import needs_deadline_follow_up

_TODAY = date(2026, 6, 23)


def _state(message: str) -> dict:
    return {"message": message, "today": _TODAY, "history": []}


def test_competition_without_date_needs_deadline_follow_up() -> None:
    """'철인 삼종 경기'처럼 날짜 없는 이벤트 목표는 horizon 을 지어내지 말고 날짜를 되묻는다."""
    goal = {"goal_text": "철인 삼종 경기 출전", "deadline": None}
    assert needs_deadline_follow_up(_state("철인 삼종 경기에 나가고 싶어"), goal) is True


def test_competition_with_explicit_date_generates_plan() -> None:
    """경기 날짜를 명시하면 되묻지 않고 plan 생성으로 진행한다."""
    goal = {"goal_text": "철인 삼종 경기 출전", "deadline": date(2026, 8, 8)}
    assert needs_deadline_follow_up(_state("8월 8일에 경기가 있어"), goal) is False


def test_plain_goal_without_event_word_does_not_force_follow_up() -> None:
    """이벤트 단어가 없는 일반 목표는 deadline 없이도 되묻지 않는다(기존 거동 보존)."""
    goal = {"goal_text": "영어 공부", "deadline": None}
    assert needs_deadline_follow_up(_state("영어 공부 좀 시작하고 싶어"), goal) is False
