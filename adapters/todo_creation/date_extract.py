"""Tavily 검색 텍스트에서 '시험일' 후보를 추출한다 (D12, 결정적·LLM 무관).

시험 일정 페이지엔 원서접수·시험일·합격발표가 섞여 있어, 날짜 위치에서 가장 가까운
키워드로 역할(시험/접수/발표)을 분류해 시험일만 남긴다. 필기/실기 연결도 최근접
키워드로 추정하되 완벽할 필요는 없다(사용자 확인 단계가 완충). today 이전은 버린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

ExamPart = Literal["필기", "실기"] | None

_WINDOW = 40  # 날짜에서 이 거리 안의 키워드만 라벨링에 사용

_P_ISO = re.compile(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})")
_P_FULL = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_P_MD = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")

_REG_WORDS = ("접수", "원서", "수험표")
_RESULT_WORDS = ("발표", "합격자")
_EXAM_WORDS = ("시험", "필기", "실기")
_WRITTEN_WORDS = ("필기", "1차", "필답")
_PRACTICAL_WORDS = ("실기", "2차", "실무")


@dataclass(frozen=True)
class ExamDateCandidate:
    date: date
    part: ExamPart
    raw: str


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _nearest(text: str, words: tuple[str, ...], pos: int) -> int | None:
    """pos 에서 words 중 가장 가까운 출현까지의 거리(없으면 None)."""
    best: int | None = None
    for w in words:
        idx = text.find(w)
        while idx != -1:
            dist = abs(idx - pos)
            if best is None or dist < best:
                best = dist
            idx = text.find(w, idx + 1)
    return best


def _category(text: str, pos: int) -> str:
    cats = {
        "registration": _nearest(text, _REG_WORDS, pos),
        "result": _nearest(text, _RESULT_WORDS, pos),
        "exam": _nearest(text, _EXAM_WORDS, pos),
    }
    best_cat, best_dist = "unknown", None
    for cat, dist in cats.items():
        if dist is not None and dist <= _WINDOW and (best_dist is None or dist < best_dist):
            best_cat, best_dist = cat, dist
    return best_cat


def _part(text: str, pos: int) -> ExamPart:
    w = _nearest(text, _WRITTEN_WORDS, pos)
    p = _nearest(text, _PRACTICAL_WORDS, pos)
    if w is None and p is None:
        return None
    if p is None or (w is not None and w <= p):
        return "필기"
    return "실기"


def extract_exam_dates(text: str, *, today: date) -> list[ExamDateCandidate]:
    found: list[ExamDateCandidate] = []
    seen: set[tuple[date, ExamPart]] = set()

    def _add(d: date | None, start: int, end: int) -> None:
        if d is None or d < today:
            return
        if _category(text, start) in ("registration", "result"):
            return
        part = _part(text, start)
        key = (d, part)
        if key in seen:
            return
        seen.add(key)
        raw = text[max(0, start - _WINDOW) : end + _WINDOW].strip()
        found.append(ExamDateCandidate(date=d, part=part, raw=raw))

    for m in _P_ISO.finditer(text):
        y, mo, da = (int(g) for g in m.groups())
        _add(_safe_date(y, mo, da), m.start(), m.end())
    for m in _P_FULL.finditer(text):
        y, mo, da = (int(g) for g in m.groups())
        _add(_safe_date(y, mo, da), m.start(), m.end())
    for m in _P_MD.finditer(text):
        mo, da = (int(g) for g in m.groups())
        _add(_safe_date(today.year, mo, da), m.start(), m.end())

    found.sort(key=lambda c: c.date)
    return found
