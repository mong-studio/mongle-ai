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
    absolute = _parse_absolute_date(normalized, today=today)
    if absolute is not None:
        return absolute
    relative = _parse_relative_day(normalized, today=today)
    if relative is not None:
        return relative
    weekday = _parse_weekday(normalized, today=today)
    if weekday is not None:
        return weekday
    return None


def _parse_absolute_date(text: str, *, today: date) -> date | None:
    iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso_match:
        return _safe_date(
            int(iso_match.group(1)),
            int(iso_match.group(2)),
            int(iso_match.group(3)),
        )

    full_match = re.search(r"(\d{4})년(\d{1,2})월(\d{1,2})일", text)
    if full_match:
        return _safe_date(
            int(full_match.group(1)),
            int(full_match.group(2)),
            int(full_match.group(3)),
        )

    month_day_match = re.search(r"(\d{1,2})월(\d{1,2})일", text)
    if not month_day_match:
        return None
    month = int(month_day_match.group(1))
    day = int(month_day_match.group(2))
    candidate = _safe_date(today.year, month, day)
    if candidate is not None and candidate < today:
        candidate = _safe_date(today.year + 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
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

    # 상대 월 마감: "이번 달 말/이번 달" → 이달 말일, "다음 달/담달" → 다음달 말일
    if "이번달말" in text or "이달말" in text:
        return _end_of_month(today)
    if "다음달" in text or "담달" in text:
        return _end_of_month(_end_of_month(today) + timedelta(days=1))
    if "이번달" in text:
        return _end_of_month(today)

    return None


def _end_of_month(value: date) -> date:
    first_of_next = (value.replace(day=1) + timedelta(days=32)).replace(day=1)
    return first_of_next - timedelta(days=1)


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
