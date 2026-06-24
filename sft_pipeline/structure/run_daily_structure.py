"""raw_daily.csv → structured_daily.csv (검증·정규화). #로 시작하는 행은 주석."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sft_pipeline.structure.daily_fields import StructuredDailyCase, structure_daily_row

STRUCTURED_DAILY_COLUMNS = [
    "source_url",
    "source_type",
    "plan_kind",
    "goal_text",
    "activity",
    "domains",
    "cadence",
    "cadence_specific",
    "time_of_day",
    "horizon_days",
    "trigger",
    "real_breakdown",
    "review_flags",
]


def read_raw_daily(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            row
            for row in reader
            if row.get("source_url") and not row["source_url"].lstrip().startswith("#")
        ]


def _to_record(case: StructuredDailyCase) -> dict:
    return {
        "source_url": case.source_url,
        "source_type": case.source_type,
        "plan_kind": case.plan_kind,
        "goal_text": case.goal_text,
        "activity": case.activity,
        "domains": ";".join(case.domains),
        "cadence": case.cadence,
        "cadence_specific": str(case.cadence_specific),
        "time_of_day": case.time_of_day,
        "horizon_days": "" if case.horizon_days is None else case.horizon_days,
        "trigger": case.trigger,
        "real_breakdown": case.real_breakdown,
        "review_flags": ";".join(case.review_flags),
    }


def write_structured_daily(rows: list[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = [_to_record(structure_daily_row(r)) for r in rows]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_DAILY_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="raw_daily.csv → structured_daily.csv")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    rows = read_raw_daily(args.in_path)
    n = write_structured_daily(rows, args.out_path)
    print(f"structured {n} daily cases -> {args.out_path}")


if __name__ == "__main__":
    main()
