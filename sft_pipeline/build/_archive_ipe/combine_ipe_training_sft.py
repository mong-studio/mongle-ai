"""정보처리기사 runtime plan + follow_up SFT를 내부 학습 후보로 결합한다."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sft_pipeline.io_utils import write_jsonl


DEFAULT_INPUTS = (
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_runtime_sft.jsonl"),
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_followup_sft.jsonl"),
)
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_training_sft.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def combine(paths: list[Path]) -> tuple[list[dict[str, Any]], Counter[str], list[str]]:
    samples: list[dict[str, Any]] = []
    by_provenance: Counter[str] = Counter()
    seen: set[str] = set()
    duplicates: list[str] = []

    for path in paths:
        for sample in _load_jsonl(path):
            meta = sample.get("meta") or {}
            sample_id = str(meta.get("id", ""))
            if sample_id and sample_id in seen:
                duplicates.append(sample_id)
                continue
            if sample_id:
                seen.add(sample_id)
            samples.append(sample)
            by_provenance[str(meta.get("provenance", "?"))] += 1
    return samples, by_provenance, duplicates


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 runtime plan + follow_up SFT 결합")
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    samples, by_provenance, duplicates = combine(args.inputs)
    write_jsonl(samples, args.out_path)
    print(f"combined {len(samples)} samples -> {args.out_path}")
    for provenance, count in by_provenance.items():
        print(f"  provenance {provenance}: {count}")
    if duplicates:
        print(f"  skipped duplicate ids: {len(duplicates)}")


if __name__ == "__main__":
    main()
