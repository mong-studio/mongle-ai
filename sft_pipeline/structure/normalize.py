"""기간·하루 공부시간 표현 정규화. 추정 금지: 모호하면 None."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "normalization.yaml"


@lru_cache(maxsize=1)
def _rules() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class TimeLeft:
    days: int | None
    raw: str


@dataclass(frozen=True)
class DailyHours:
    hours: float | None
    hours_min: float | None
    hours_max: float | None
    raw: str


def _is_missing(text: str) -> bool:
    return text.strip() in _rules()["missing_tokens"]


def parse_time_left(raw: str | None) -> TimeLeft:
    text = (raw or "").strip()
    if _is_missing(text):
        return TimeLeft(None, text)

    d_minus = re.search(r"[Dd]\s*-\s*(\d+)", text)
    if d_minus:
        return TimeLeft(int(d_minus.group(1)), text)

    for keyword, days in _rules()["time_left_keywords"].items():
        if keyword in text:
            return TimeLeft(int(days), text)

    units = "|".join(sorted(map(re.escape, _rules()["period_units"]), key=len, reverse=True))
    num_unit = re.search(rf"(\d+)\s*({units})", text)
    if num_unit:
        n = int(num_unit.group(1))
        mult = _rules()["period_units"][num_unit.group(2)]
        return TimeLeft(n * mult, text)

    return TimeLeft(None, text)


def parse_daily_hours(raw: str | None) -> DailyHours:
    text = (raw or "").strip()
    if _is_missing(text):
        return DailyHours(None, None, None, text)

    rng = re.search(r"(\d+(?:\.\d+)?)\s*[~\-]\s*(\d+(?:\.\d+)?)", text)
    if rng:
        lo, hi = float(rng.group(1)), float(rng.group(2))
        return DailyHours((lo + hi) / 2, lo, hi, text)

    minutes = re.search(r"(\d+)\s*분", text)
    if minutes:
        return DailyHours(round(int(minutes.group(1)) / 60, 2), None, None, text)

    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:시간|h|H)", text)
    if hours:
        return DailyHours(float(hours.group(1)), None, None, text)

    return DailyHours(None, None, None, text)
