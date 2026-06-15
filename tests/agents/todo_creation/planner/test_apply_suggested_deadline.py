from __future__ import annotations

from datetime import date

from agents.todo_creation.planner.goal_rules import apply_suggested_deadline


def _state(answer: str, suggested: date | None) -> dict:
    return {
        "suggested_deadline": suggested,
        "history": [
            {"role": "assistant", "content": "정처기 필기 2026-07-05로 짤까요?"},
            {"role": "user", "content": answer},
        ],
    }


def test_affirmation_promotes_suggested_to_deadline() -> None:
    goal: dict = {}
    apply_suggested_deadline(_state("응", date(2026, 7, 5)), goal)
    assert goal["deadline"] == date(2026, 7, 5)


def test_phrase_affirmation_promotes() -> None:
    goal: dict = {}
    apply_suggested_deadline(_state("이대로 해줘", date(2026, 7, 5)), goal)
    assert goal["deadline"] == date(2026, 7, 5)


def test_false_affirm_substring_does_not_promote() -> None:
    # "모르겠네" 의 "네" 가 긍정으로 오인식되면 안 된다.
    goal: dict = {}
    apply_suggested_deadline(_state("잘 모르겠네", date(2026, 7, 5)), goal)
    assert "deadline" not in goal


def test_negative_answer_does_not_promote() -> None:
    goal: dict = {}
    apply_suggested_deadline(_state("아니 다른 날짜로", date(2026, 7, 5)), goal)
    assert "deadline" not in goal


def test_existing_deadline_is_preserved() -> None:
    goal: dict = {"deadline": date(2026, 1, 1)}
    apply_suggested_deadline(_state("응", date(2026, 7, 5)), goal)
    assert goal["deadline"] == date(2026, 1, 1)


def test_no_suggestion_is_noop() -> None:
    goal: dict = {}
    apply_suggested_deadline(_state("응", None), goal)
    assert "deadline" not in goal
