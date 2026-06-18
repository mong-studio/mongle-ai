from __future__ import annotations

from datetime import date

import pytest

from agents.todo_creation.todo.when_resolver import resolve_when

# 기준일: 2026-06-18 (목요일). 이번주 일요일 = 2026-06-21, 다음주 월요일 = 2026-06-22.
TODAY = date(2026, 6, 18)


@pytest.mark.parametrize(
    "phrase, expected",
    [
        (None, TODAY),
        ("", TODAY),
        ("오늘", TODAY),
        ("내일", date(2026, 6, 19)),
        ("명일", date(2026, 6, 19)),  # 내일(문어체)
        ("익일", date(2026, 6, 19)),
        ("모레", date(2026, 6, 20)),
        ("내일모레", date(2026, 6, 20)),
        ("글피", date(2026, 6, 21)),
        ("이틀 뒤", date(2026, 6, 20)),  # 순우리말
        ("사흘 뒤", date(2026, 6, 21)),
        ("닷새 뒤", date(2026, 6, 23)),
        ("어제", TODAY),  # 과거 클램프
        ("이번주", date(2026, 6, 21)),
        ("이번 주", date(2026, 6, 21)),
        ("주말", date(2026, 6, 21)),
        ("3일 뒤", date(2026, 6, 21)),
        ("5일 후", date(2026, 6, 23)),
        ("2주 뒤", date(2026, 7, 2)),
        ("금요일", date(2026, 6, 19)),  # 목요일 기준 다음 금요일
        ("이번 주 금요일", date(2026, 6, 19)),
        ("다음주", date(2026, 6, 25)),  # 오늘(목) 기준 일주일 뒤
        ("다음주 화요일", date(2026, 6, 23)),  # 다음 주 월(6/22)+화
        ("6월 21일", date(2026, 6, 21)),
        ("2026-07-01", date(2026, 7, 1)),
        ("언젠가", TODAY),  # 미지원 → 폴백
    ],
)
def test_resolve_when(phrase, expected) -> None:
    assert resolve_when(phrase, TODAY) == expected


def test_past_iso_clamped_to_today() -> None:
    assert resolve_when("2020-01-01", TODAY) == TODAY


def test_monday_today_weekday_returns_today_for_this_week() -> None:
    # today 가 월요일일 때 '이번 주 월요일' 은 today
    monday = date(2026, 6, 22)
    assert resolve_when("이번 주 월요일", monday) == monday
