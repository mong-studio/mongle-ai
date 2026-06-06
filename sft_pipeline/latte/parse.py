"""MS-LaTTE.json → 결정론적 시드(latte_parsed.csv).

여러 어노테이터(위치 3~4명, 시간 5명)의 판정을 다수결로 집계해
태스크당 대표 (위치, 시간대) 시드를 만든다. LLM 합성/한국어화는 하류 단계.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

PARSED_COLUMNS = [
    "id",
    "task_title",
    "list_title",
    "loc_known",
    "broad_location",
    "public_location",
    "time_known",
    "top_times",
]

# 2명 이상 동의한 시간 슬롯만 신뢰. 없으면 최빈 1개로 폴백.
_TIME_AGREE_MIN = 2


def _mode(values) -> str:
    """비어있지 않은 값 중 최빈값. 동률은 (-count, value)로 결정론적 선택."""
    counts = Counter(v for v in values if v)
    if not counts:
        return ""
    return min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _majority_yes(judgements: list[dict]) -> bool:
    yes = sum(1 for j in judgements if str(j.get("Known", "")).strip().lower() == "yes")
    return yes * 2 > len(judgements)


def aggregate_location(judgements: list[dict]) -> dict:
    broad = _mode(j.get("Locations", "") for j in judgements)
    public = ""
    if broad == "public":
        public = _mode(j.get("PublicLocations", "") for j in judgements)
    return {"known": _majority_yes(judgements), "broad": broad, "public": public}


def aggregate_time(judgements: list[dict]) -> dict:
    counts: Counter = Counter()
    for j in judgements:
        for label in str(j.get("Times", "")).split(","):
            label = label.strip()
            if label:
                counts[label] += 1

    agreed = [lbl for lbl, n in counts.items() if n >= _TIME_AGREE_MIN]
    if agreed:
        top = sorted(agreed, key=lambda lbl: (-counts[lbl], lbl))
    elif counts:
        top = [min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]]
    else:
        top = []
    return {"known": _majority_yes(judgements), "top_times": top}


def parse_record(rec: dict) -> dict:
    loc = aggregate_location(rec.get("LocJudgements", []))
    time = aggregate_time(rec.get("TimeJudgements", []))
    return {
        "id": rec.get("ID", ""),
        "task_title": rec.get("TaskTitle", ""),
        "list_title": rec.get("ListTitle", ""),
        "loc_known": loc["known"],
        "broad_location": loc["broad"],
        "public_location": loc["public"],
        "time_known": time["known"],
        "top_times": time["top_times"],
    }


def parse_records(data: list[dict]) -> list[dict]:
    return [parse_record(rec) for rec in data]


def load_and_parse(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return parse_records(data)


def write_csv(seeds: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PARSED_COLUMNS)
        writer.writeheader()
        for seed in seeds:
            row = dict(seed)
            row["top_times"] = ";".join(seed["top_times"])
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="MS-LaTTE.json → latte_parsed.csv")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    seeds = load_and_parse(args.in_path)
    write_csv(seeds, args.out_path)
    print(f"[parse] {len(seeds)} tasks -> {args.out_path}")


if __name__ == "__main__":
    main()
