"""기생성 jsonl 의 assistant 플랜 JSON 에서 tags 키를 제거한다(1회성, 멱등).

태그는 별도 Tagger 노드 책임(todo CLAUDE.md §4.9)이라 플랜 SFT 학습 대상에서
제외한다(2026-06-08 결정). meta.task_type == 'plan' 샘플의 assistant content 만
다시 직렬화하고, chat 샘플(distractor)·user 턴·meta 는 손대지 않는다.
직렬화 포맷은 빌더와 동일(dump_plan_for_training — compact·ensure_ascii=False)이라
신규 합성분과 바이트 단위로 정합한다.

실행:
    python -m sft_pipeline.build.strip_tags \
        --in sft_pipeline/data/generated/daily_v2_clean.jsonl \
        --out sft_pipeline/data/generated/daily_v2_clean.jsonl
    (--in 과 --out 이 같으면 전체를 읽은 뒤 한 번에 덮어쓴다)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sft_pipeline.build.plan_schemas import dump_plan_for_training, parse_plan
from sft_pipeline.io_utils import write_jsonl


def strip_tags_record(rec: dict) -> dict:
    """플랜 샘플의 assistant 플랜에서 tags 를 뺀 새 레코드를 돌려준다(입력 불변)."""
    if rec.get("meta", {}).get("task_type") != "plan":
        return rec
    messages = list(rec["messages"])
    plan = parse_plan(messages[-1]["content"])
    messages[-1] = {**messages[-1], "content": dump_plan_for_training(plan)}
    return {**rec, "messages": messages}


def main() -> None:
    parser = argparse.ArgumentParser(description="assistant 플랜 JSON 에서 tags 제거(멱등)")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    with open(args.in_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    out = [strip_tags_record(r) for r in records]
    changed = sum(1 for a, b in zip(records, out) if a != b)
    write_jsonl(out, args.out_path)
    print(f"[strip_tags] {len(out)} records ({changed} changed) -> {args.out_path}")


if __name__ == "__main__":
    main()
