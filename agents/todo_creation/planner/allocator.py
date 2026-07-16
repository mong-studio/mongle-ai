"""routine plan_kind 전개기 (설계서 §3.4, Phase 1).

"주 N회" 또는 "월수금" 같은 cadence 를 horizon 내 실제 날짜로 전개해
TaskCandidate(캘린더 이벤트) 리스트로 만든다. 결정적·LLM 무관.
마감일 이후는 만들지 않는다(Phase 0 deadline clamp 규칙과 정합).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Sequence

from agents.todo_creation.schemas import TaskCandidate

_WEEKDAY_CHARS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# "주 N회"처럼 요일이 명시되지 않은 경우의 기본 분산(평일 우선, 간격 균등).
_SPREAD: dict[int, tuple[int, ...]] = {
    1: (0,),
    2: (1, 3),
    3: (0, 2, 4),
    4: (0, 1, 3, 5),
    5: (0, 1, 2, 3, 4),
    6: (0, 1, 2, 3, 4, 5),
    7: (0, 1, 2, 3, 4, 5, 6),
}


def _parse_weekdays(cadence: str) -> set[int]:
    """cadence 에서 요일 집합을 뽑는다. 명시 요일 우선, 없으면 '주 N회' 의 N 으로 분산."""
    explicit = {_WEEKDAY_CHARS[c] for c in cadence if c in _WEEKDAY_CHARS}
    if explicit:
        return explicit
    match = re.search(r"\d+", cadence)
    count = int(match.group()) if match else 1
    count = max(1, min(7, count))
    return set(_SPREAD[count])


_DAILY_WORDS = ("매일", "날마다", "데일리", "매일매일")

_FREQ_RE = re.compile(r"(\d+)\s*(?:회|번)")


def _weekday_run(text: str) -> str | None:
    """연속된 요일 글자 런 중 길이>=2인 최장 런을 돌려준다.

    "월수금"은 잡고, 단일 요일이 다른 글자에 섞인 '금요일'·'일주일'·'토요일'은
    런 길이 1이라 걸러진다(날짜/기간 표현과의 오탐 방지).
    """
    best = ""
    run = ""
    for ch in text:
        if ch in _WEEKDAY_CHARS:
            run += ch
        else:
            if len(run) >= 2 and len(run) > len(best):
                best = run
            run = ""
    if len(run) >= 2 and len(run) > len(best):
        best = run
    return best or None


def recover_cadence(text: str) -> str | None:
    """원문에서 cadence 를 결정적으로 복구한다. 못 찾으면 None(→ follow_up 되묻기).

    우선순위: 매일 > 명시 요일(월수금) > 숫자 빈도(주 N회).
    모델이 빈도를 'weekly' 로 뭉개거나 슬롯에서 누락하는 결함의 안전망.
    단일 요일 글자('금요일'·'일주일')는 날짜/기간이라 요일 cadence 로 보지 않는다.
    """
    if not text:
        return None
    if any(word in text for word in _DAILY_WORDS):
        return "매일"
    weekdays = _weekday_run(text)
    if weekdays:
        return weekdays
    match = _FREQ_RE.search(text)
    if match:
        count = max(1, min(7, int(match.group(1))))
        return f"주 {count}회"
    return None


_DAILY_TIME_RE = re.compile(r"(?:하루|매일|날마다)\s*(?:에)?\s*(\d+)\s*(시간|분)")


def parse_daily_time(text: str) -> str | None:
    """'하루/매일 N시간·분' 을 결정적으로 파싱해 '하루 N시간'/'하루 N분' 으로 정규화.

    사용자가 명시한 하루 가용 시간(available_time/daily_hours)을 모델 대신 코드가 뽑는다.
    """
    if not text:
        return None
    match = _DAILY_TIME_RE.search(text)
    if not match:
        return None
    return f"하루 {match.group(1)}{match.group(2)}"


_HANGUL_MONTHS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6}
_HORIZON_RE = re.compile(r"(\d+)\s*(개월|달|주)")


def parse_horizon_days(text: str) -> int | None:
    """'두 달'·'8주'·'3개월' 같은 기간을 일수로 파싱한다(routine horizon). 없으면 None."""
    if not text:
        return None
    for word, months in _HANGUL_MONTHS.items():
        if f"{word} 달" in text or f"{word}달" in text:
            return min(months * 30, 366)
    match = _HORIZON_RE.search(text)
    if not match:
        return None
    days = int(match.group(1)) * (7 if match.group(2) == "주" else 30)
    return min(max(1, days), 366)


_TAG_RE = re.compile(r"태그[를은는]?\s*['\"]?([가-힣A-Za-z0-9]{1,12}?)['\"]?\s*으?로")


def parse_tag_override(text: str) -> str | None:
    """'태그를 운동으로' 같은 태그 변경 요청에서 태그값을 파싱한다. 없으면 None."""
    if not text:
        return None
    match = _TAG_RE.search(text)
    return match.group(1) if match else None


def cadence_is_specific(cadence: str) -> bool:
    """cadence 에 빈도(주 N회)·명시 요일·'매일' 이 있으면 구체적이다.

    '매주'처럼 횟수도 요일도 없는 표현은 모호하므로 False(주 몇 회인지 되물어야 함).
    """
    text = (cadence or "").replace(" ", "")
    if not text:
        return False
    if any(word in text for word in _DAILY_WORDS):
        return True
    if any(ch in _WEEKDAY_CHARS for ch in text):
        return True
    return bool(re.search(r"\d", text))


def expand_routine(
    activity: str,
    cadence: str,
    *,
    today: date,
    horizon_days: int = 28,
    deadline: date | None = None,
    routine_items: Sequence[str] | None = None,
) -> list[TaskCandidate]:
    """cadence 를 horizon 내 날짜로 전개한다(마감 이후 제외)."""
    weekdays = _parse_weekdays(cadence)
    title = activity.strip()[:20] or "루틴"
    titles_by_weekday = _titles_by_weekday(routine_items, weekdays)
    events: list[TaskCandidate] = []
    for offset in range(max(0, horizon_days)):
        day = today + timedelta(days=offset)
        if deadline is not None and day > deadline:
            break
        if day.weekday() in weekdays:
            events.append(
                TaskCandidate(
                    title=titles_by_weekday.get(day.weekday(), title),
                    due_date=day,
                    tags=["루틴"],
                )
            )
    return events


def _titles_by_weekday(
    routine_items: Sequence[str] | None, weekdays: set[int]
) -> dict[int, str]:
    """구조화된 회차별 항목을 선택 요일 순서에 맞춰 배치한다."""
    items = [
        str(item).strip()[:20]
        for item in (routine_items or [])
        if str(item).strip()
    ]
    if not items:
        return {}
    return {
        weekday: items[index % len(items)]
        for index, weekday in enumerate(sorted(weekdays))
    }
