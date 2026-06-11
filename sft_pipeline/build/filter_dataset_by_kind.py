"""SFT JSONL을 assistant 출력 kind 기준으로 필터링한다."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sft_pipeline.io_utils import write_jsonl
from sft_pipeline.train.postcheck import assistant_kind


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def filter_by_kind(samples: list[dict], kinds: set[str]) -> list[dict]:
    return [
        sample
        for sample in samples
        if assistant_kind(str(sample["messages"][-1]["content"])) in kinds
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="assistant kind 기준 JSONL 필터")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--kind", action="append", required=True, help="남길 kind. 여러 번 지정 가능")
    args = parser.parse_args()

    samples = load_jsonl(args.in_path)
    filtered = filter_by_kind(samples, set(args.kind))
    write_jsonl(filtered, args.out_path)
    counts = Counter(assistant_kind(str(sample["messages"][-1]["content"])) for sample in filtered)
    print(f"[filter-kind] wrote {len(filtered)} / {len(samples)} -> {args.out_path}")
    print(f"[filter-kind] by kind: {dict(counts)}")


if __name__ == "__main__":
    main()
