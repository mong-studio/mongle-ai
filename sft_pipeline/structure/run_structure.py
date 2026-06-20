"""raw_cases.csv → structured.csv (검증·정규화). #로 시작하는 행은 주석."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sft_pipeline.structure.fields import StructuredCase, structure_row

STRUCTURED_COLUMNS = [
    "source_url",
    "exam_type",
    "time_left",
    "time_left_days",
    "daily_hours",
    "daily_hours_value",
    "daily_hours_min",
    "daily_hours_max",
    "start_level",
    "goal",
    "special_notes",
    "actual_plan_summary",
    "result",
    "evidence_spans",
    "review_flags",
]


def read_raw_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            row
            for row in reader
            if row.get("source_url") and not row["source_url"].lstrip().startswith("#")
        ]


def _to_record(case: StructuredCase) -> dict:
    return {
        "source_url": case.source_url,
        "exam_type": case.exam_type,
        "time_left": case.time_left,
        "time_left_days": "" if case.time_left_days is None else case.time_left_days,
        "daily_hours": case.daily_hours,
        "daily_hours_value": "" if case.daily_hours_value is None else case.daily_hours_value,
        "daily_hours_min": "" if case.daily_hours_min is None else case.daily_hours_min,
        "daily_hours_max": "" if case.daily_hours_max is None else case.daily_hours_max,
        "start_level": case.start_level,
        "goal": case.goal,
        "special_notes": case.special_notes,
        "actual_plan_summary": case.actual_plan_summary,
        "result": case.result,
        "evidence_spans": case.evidence_spans,
        "review_flags": ";".join(case.review_flags),
    }


def write_structured(rows: list[dict], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = [_to_record(structure_row(r)) for r in rows]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STRUCTURED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="raw_cases.csv → structured.csv")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    rows = read_raw_cases(args.in_path)
    n = write_structured(rows, args.out_path)
    print(f"structured {n} cases -> {args.out_path}")


if __name__ == "__main__":
    main()
