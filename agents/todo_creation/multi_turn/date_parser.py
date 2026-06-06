from __future__ import annotations

import re
from datetime import date, timedelta

_WEEKDAYS = {
    "월요일": 0,
    "화요일": 1,
    "수요일": 2,
    "목요일": 3,
    "금요일": 4,
    "토요일": 5,
    "일요일": 6,
}


def parse_explicit_deadline(text: str, *, today: date) -> date | None:
    """한국어 날짜 표현 중 플래너 deadline 으로 쓸 수 있는 표현만 해석한다."""

    normalized = re.sub(r"\s+", "", text)
    relative = _parse_relative_day(normalized, today=today)
    if relative is not None:
        return relative
    weekday = _parse_weekday(normalized, today=today)
    if weekday is not None:
        return weekday
    return None


def has_explicit_deadline(text: str, *, today: date) -> bool:
    return parse_explicit_deadline(text, today=today) is not None


def _parse_relative_day(text: str, *, today: date) -> date | None:
    for word, days in (("오늘", 0), ("내일", 1), ("모레", 2), ("글피", 3)):
        if word in text:
            return today + timedelta(days=days)

    match = re.search(r"(\d+)일(뒤|후)", text)
    if match:
        return today + timedelta(days=int(match.group(1)))

    match = re.search(r"(\d+)주(뒤|후)", text)
    if match:
        return today + timedelta(weeks=int(match.group(1)))

    match = re.search(r"(\d+)개월(뒤|후)", text)
    if match:
        return today + timedelta(days=30 * int(match.group(1)))

    return None


def _parse_weekday(text: str, *, today: date) -> date | None:
    for weekday_name, weekday_index in _WEEKDAYS.items():
        if weekday_name not in text:
            continue
        if f"다다음주{weekday_name}" in text or f"다담주{weekday_name}" in text:
            return _week_start(today) + timedelta(days=14 + weekday_index)
        if f"다음주{weekday_name}" in text:
            return _week_start(today) + timedelta(days=7 + weekday_index)
        if f"이번주{weekday_name}" in text:
            candidate = _week_start(today) + timedelta(days=weekday_index)
            return candidate if candidate >= today else candidate + timedelta(days=7)
        if f"다음{weekday_name}" in text:
            return _next_weekday(today, weekday_index)
        return _next_weekday(today, weekday_index)
    return None


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _next_weekday(today: date, weekday_index: int) -> date:
    days = (weekday_index - today.weekday()) % 7
    if days == 0:
        days = 7
    return today + timedelta(days=days)
