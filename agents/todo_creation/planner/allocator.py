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


_DAILY_WORDS = ("매일", "날마다", "데일리", "매일매일")

_FREQ_RE = re.compile(r"(\d+)\s*(?:회|번)")


def recover_cadence(text: str) -> str | None:
    """모델이 빈도를 'weekly' 같은 영어 period 로 뭉개 떨어뜨릴 때 원문에서 복구한다.

    예: "매주 3회 물 마실거야" → "주 3회", "일주일에 2번" → "주 2회".
    슬롯에 "3회" 가 들어있었는데 모델이 카운트를 잃어버리는 결함의 결정적 안전망.
    요일("월수금") 추출은 '일주일'·'요일'·'평일' 등이 요일 글자를 품어 오탐이 많으므로
    숫자 빈도(N회/번)만 신뢰한다 — 못 찾으면 None 으로 follow_up 되묻기에 맡긴다.
    """
    if not text:
        return None
    match = _FREQ_RE.search(text)
    if match:
        count = max(1, min(7, int(match.group(1))))
        return f"주 {count}회"
    return None


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
            events.append(TaskCandidate(title=title, due_date=day, tags=["루틴"]))
    return events
