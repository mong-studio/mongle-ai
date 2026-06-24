"""일상 cadence·time_of_day·horizon 정규화. 추정 금지: 모호하면 None/빈값."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sft_pipeline.structure.normalize import parse_time_left

_WEEKDAY_CHARS = set("월화수목금토일")
_DAILY_WORDS = ("매일", "날마다", "데일리")
_TIME_WORDS = ("아침", "오전", "점심", "오후", "저녁", "밤")


@dataclass(frozen=True)
class Cadence:
    specific: bool
    raw: str


def parse_cadence(raw: str | None) -> Cadence:
    text = (raw or "").replace(" ", "")
    if not text:
        return Cadence(False, raw or "")
    if any(w in text for w in _DAILY_WORDS):
        return Cadence(True, raw or "")
    if any(ch in _WEEKDAY_CHARS for ch in text):
        return Cadence(True, raw or "")
    return Cadence(bool(re.search(r"\d", text)), raw or "")


def parse_horizon_days(raw: str | None) -> int | None:
    return parse_time_left(raw).days


def parse_time_of_day(raw: str | None) -> str:
    text = raw or ""
    for word in _TIME_WORDS:
        if word in text:
            return word
    return ""
