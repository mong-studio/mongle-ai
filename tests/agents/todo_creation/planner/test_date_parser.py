from __future__ import annotations

from datetime import date

from agents.todo_creation.planner.date_parser import parse_explicit_deadline


def test_parses_next_week_weekday_without_space() -> None:
    today = date(2026, 5, 25)

    result = parse_explicit_deadline("시험은 다음주 토요일이야", today=today)

    assert result == date(2026, 6, 6)


def test_parses_this_week_weekday_with_space() -> None:
    today = date(2026, 5, 25)

    result = parse_explicit_deadline("이번 주 금요일까지 끝내야 해", today=today)

    assert result == date(2026, 5, 29)


def test_parses_next_weekday_phrase() -> None:
    today = date(2026, 5, 25)

    result = parse_explicit_deadline("다음 월요일에 시작하고 싶어", today=today)

    assert result == date(2026, 6, 1)


def test_parses_relative_days_without_space() -> None:
    today = date(2026, 5, 25)

    result = parse_explicit_deadline("5일뒤 발표야", today=today)

    assert result == date(2026, 5, 30)


def test_parses_korean_month_day() -> None:
    result = parse_explicit_deadline(
        "철인 삼종 경기는 8월 8일이야", today=date(2026, 6, 24)
    )

    assert result == date(2026, 8, 8)


def test_parses_korean_full_date() -> None:
    result = parse_explicit_deadline(
        "2027년 8월 8일 경기", today=date(2026, 6, 24)
    )

    assert result == date(2027, 8, 8)


def test_month_day_rolls_to_next_year_when_already_past() -> None:
    result = parse_explicit_deadline(
        "1월 10일 경기", today=date(2026, 6, 24)
    )

    assert result == date(2027, 1, 10)
