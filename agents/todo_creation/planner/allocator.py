"""routine plan_kind 전개기 (설계서 §3.4, Phase 1).

"주 N회" 또는 "월수금" 같은 cadence 를 horizon 내 실제 날짜로 전개해
TaskCandidate(캘린더 이벤트) 리스트로 만든다. 결정적·LLM 무관.
마감일 이후는 만들지 않는다(Phase 0 deadline clamp 규칙과 정합).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

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


def expand_routine(
    activity: str,
    cadence: str,
    *,
    today: date,
    horizon_days: int = 28,
    deadline: date | None = None,
) -> list[TaskCandidate]:
    """cadence 를 horizon 내 날짜로 전개한다(마감 이후 제외)."""
    weekdays = _parse_weekdays(cadence)
    title = activity.strip()[:20] or "루틴"
    events: list[TaskCandidate] = []
    for offset in range(max(0, horizon_days)):
        day = today + timedelta(days=offset)
        if deadline is not None and day > deadline:
            break
        if day.weekday() in weekdays:
            events.append(TaskCandidate(title=title, due_date=day, tags=["routine"]))
    return events
