"""구조화 케이스 스키마. 누락값 정책: 미기재→빈값/None, 추정 금지, 모호→review_flags."""
from __future__ import annotations

from dataclasses import dataclass, field

from sft_pipeline.structure.exam_types import canonicalize_exam_type
from sft_pipeline.structure.normalize import parse_daily_hours, parse_time_left

RAW_COLUMNS = [
    "source_url",
    "exam_type",
    "time_left",
    "daily_hours",
    "start_level",
    "goal",
    "special_notes",
    "actual_plan_summary",
    "result",
    "evidence_spans",
]

VALID_RESULTS = {"합격", "불합격"}


@dataclass(frozen=True)
class StructuredCase:
    source_url: str
    exam_type: str
    time_left: str
    time_left_days: int | None
    daily_hours: str
    daily_hours_value: float | None
    daily_hours_min: float | None
    daily_hours_max: float | None
    start_level: str
    goal: str
    special_notes: str
    actual_plan_summary: str
    result: str
    evidence_spans: str
    review_flags: list[str] = field(default_factory=list)


def structure_row(row: dict) -> StructuredCase:
    flags: list[str] = []

    exam = canonicalize_exam_type(row.get("exam_type", ""))
    if exam is None:
        flags.append("exam_type_unmapped")
        exam = ""

    tl = parse_time_left(row.get("time_left", ""))
    if tl.days is None:
        flags.append("time_left_missing")

    dh = parse_daily_hours(row.get("daily_hours", ""))
    if dh.hours is None:
        flags.append("daily_hours_missing")

    result = (row.get("result", "") or "").strip()
    if result not in VALID_RESULTS:
        flags.append("result_unknown")
        result = "미상"

    if not (row.get("actual_plan_summary", "") or "").strip():
        flags.append("plan_summary_missing")

    return StructuredCase(
        source_url=(row.get("source_url", "") or "").strip(),
        exam_type=exam,
        time_left=tl.raw,
        time_left_days=tl.days,
        daily_hours=dh.raw,
        daily_hours_value=dh.hours,
        daily_hours_min=dh.hours_min,
        daily_hours_max=dh.hours_max,
        start_level=(row.get("start_level", "") or "").strip(),
        goal=(row.get("goal", "") or "").strip(),
        special_notes=(row.get("special_notes", "") or "").strip(),
        actual_plan_summary=(row.get("actual_plan_summary", "") or "").strip(),
        result=result,
        evidence_spans=(row.get("evidence_spans", "") or "").strip(),
        review_flags=flags,
    )
