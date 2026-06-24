"""structured_daily.csv → 일상 planner 노드 SFT jsonl (§4.6 Stage ②).

케이스당 judge·(goal_tag·generator·critic) 레코드. 내용은 결정론(GPT-4o 는 상류 추출만).
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from sft_pipeline.build.lib.daily_nodes_template import build_records
from sft_pipeline.io_utils import write_jsonl


def build_samples(structured_path: Path, today: date | None = None) -> list[dict]:
    today = today or date.today()
    try:
        with open(structured_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError as err:
        raise SystemExit(f"[입력] structured_daily.csv 읽기 실패: {structured_path} ({err})")
    samples: list[dict] = []
    for case in rows:
        samples.extend(build_records(case, today))
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="structured_daily.csv → 일상 노드 SFT jsonl")
    parser.add_argument("structured_path", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    samples = build_samples(args.structured_path, today=args.today)
    if not samples:
        raise SystemExit("[입력] 생성된 샘플이 0개입니다.")
    write_jsonl(samples, args.out_path)


if __name__ == "__main__":
    main()
