"""시간표현(when) → 절대날짜 결정적 변환 (뉴로-심볼릭의 '심볼릭' 절반).

LLM 은 task 별 시간표현 구문(`when`)만 추출하고, 날짜 계산은 이 모듈이 한다.
TIMEX normalization 의 축소판: 상대표현을 기준일(today=DCT)에 앵커링해 절대날짜로 변환.
모델의 날짜 산수 오류(예: '내일'을 +3일로 계산)를 구조적으로 제거하는 것이 목적이다.

지원하지 않는 표현은 today 로 안전하게 폴백한다(없는 날짜를 지어내지 않음).
과거로 계산된 날짜는 today 로 클램프한다(기존 task_splitter._correct 와 동일 규칙).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# 월=0 ... 일=6 (date.weekday() 규약)
_WEEKDAY = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

_N_DAYS = re.compile(r"(\d+)\s*일\s*(?:뒤|후|내|째)")
_N_WEEKS = re.compile(r"(\d+)\s*주\s*(?:뒤|후)")
_MD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

# 순우리말 날짜수 ("사흘 뒤" = +3). ponytail: "하루종일"처럼 날짜 아닌 용례는 못 거른다.
_NATIVE_DAYS = {
    "하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5,
    "엿새": 6, "이레": 7, "여드레": 8, "아흐레": 9, "열흘": 10,
}


def _this_sunday(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())


def _next_weekday(today: date, target: int, *, this_week: bool) -> date:
    """target 요일의 다음 발생일. this_week=True 면 이번 주 범위 내 해당 요일."""
    if this_week:
        return today + timedelta(days=target - today.weekday())
    delta = (target - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _raw_resolve(phrase: str, today: date) -> date:
    p = phrase.replace(" ", "")

    if any(k in p for k in ("오늘", "당일", "이따", "금일")):
        return today
    if "모레" in p:  # 내일모레 포함
        return today + timedelta(days=2)
    if "글피" in p:
        return today + timedelta(days=3)
    if "내일" in p or "명일" in p or "익일" in p or p == "낼":
        return today + timedelta(days=1)
    if "어제" in p:
        return today  # 과거 클램프

    for word, n in _NATIVE_DAYS.items():  # 사흘 뒤, 이틀 뒤 …
        if word in p:
            return today + timedelta(days=n)

    # 요일 — bare 이번주/다음주 분기보다 먼저 본다('이번 주 금요일' 같은 수식 우선)
    for ko, idx in _WEEKDAY.items():
        if f"{ko}요일" in p:
            if "다음주" in p or "담주" in p:
                next_monday = today + timedelta(days=7 - today.weekday())
                return next_monday + timedelta(days=idx)
            this_week = "이번" in p or "금주" in p
            return _next_weekday(today, idx, this_week=this_week)

    if "다음주" in p or "담주" in p:
        return today + timedelta(days=7)  # 다음 주 = 오늘 기준 일주일 뒤
    if any(k in p for k in ("이번주", "금주", "주말", "이번달", "이달", "말일")):
        return _this_sunday(today)

    m = _N_DAYS.search(p)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = _N_WEEKS.search(p)
    if m:
        return today + timedelta(days=7 * int(m.group(1)))
    m = _ISO.search(p)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _MD.search(p)
    if m:
        return date(today.year, int(m.group(1)), int(m.group(2)))

    return today  # 미지원 표현 폴백


def resolve_when(phrase: str | None, today: date) -> date:
    """when 구문(또는 None) + 기준일 → 절대날짜. 과거는 today 로 클램프."""
    if not phrase or not phrase.strip():
        return today
    resolved = _raw_resolve(phrase, today)
    return resolved if resolved >= today else today
