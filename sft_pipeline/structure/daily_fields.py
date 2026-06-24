"""일상 구조화 케이스 스키마. 미기재→빈값/None, 추정 금지, 모호→review_flags."""
from __future__ import annotations

from dataclasses import dataclass, field

from sft_pipeline.structure.daily_normalize import (
    parse_cadence,
    parse_horizon_days,
    parse_time_of_day,
)
from sft_pipeline.structure.daily_taxonomy import (
    canonicalize_domain,
    canonicalize_plan_kind,
)

RAW_DAILY_COLUMNS = [
    "source_url",
    "source_type",
    "plan_kind",
    "goal_text",
    "activity",
    "domains",
    "cadence",
    "time_of_day",
    "horizon",
    "trigger",
    "real_breakdown",
]


@dataclass(frozen=True)
class StructuredDailyCase:
    source_url: str
    source_type: str
    plan_kind: str
    goal_text: str
    activity: str
    domains: list[str]
    cadence: str
    cadence_specific: bool
    time_of_day: str
    horizon_days: int | None
    trigger: str
    real_breakdown: str
    review_flags: list[str] = field(default_factory=list)


def _clean(row: dict, key: str) -> str:
    return (row.get(key, "") or "").strip()


def _domains(raw: str, flags: list[str]) -> list[str]:
    out: list[str] = []
    for token in (t.strip() for t in raw.split(";") if t.strip()):
        canonical = canonicalize_domain(token)
        if canonical is None:
            flags.append("domain_unmapped")
        elif canonical not in out:
            out.append(canonical)
    return out


def structure_daily_row(row: dict) -> StructuredDailyCase:
    flags: list[str] = []

    plan_kind = canonicalize_plan_kind(_clean(row, "plan_kind"))
    if plan_kind is None:
        flags.append("plan_kind_unmapped")
        plan_kind = ""

    cadence_raw = _clean(row, "cadence")
    cadence = parse_cadence(cadence_raw)
    # exam/lifestyle 은 cadence 가 핵심 슬롯이 아니므로 vague 플래그를 강제하지 않는다.
    if plan_kind in ("routine", "vague_goal") and cadence_raw and not cadence.specific:
        flags.append("cadence_vague")

    real_breakdown = _clean(row, "real_breakdown")
    if not real_breakdown:
        flags.append("real_breakdown_missing")

    return StructuredDailyCase(
        source_url=_clean(row, "source_url"),
        source_type=_clean(row, "source_type"),
        plan_kind=plan_kind,
        goal_text=_clean(row, "goal_text"),
        activity=_clean(row, "activity"),
        domains=_domains(_clean(row, "domains"), flags),
        cadence=cadence_raw,
        cadence_specific=cadence.specific,
        time_of_day=parse_time_of_day(_clean(row, "time_of_day")),
        horizon_days=parse_horizon_days(_clean(row, "horizon")),
        trigger=_clean(row, "trigger"),
        real_breakdown=real_breakdown,
        review_flags=flags,
    )
