"""정보처리기사 배치별 SFT JSONL을 내부 학습용 합본으로 결합한다."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from sft_pipeline.io_utils import write_jsonl


DEFAULT_INPUTS = (
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_sft.jsonl"),
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_written_expansion_sft.jsonl"),
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_practical_sft.jsonl"),
    Path("sft_pipeline/data/generated/exam_information_processing_engineer_retry_expansion_sft.jsonl"),
)
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_all_sft.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _exam_type(meta: dict[str, Any]) -> str:
    part = meta.get("exam_part")
    if part == "written":
        return "정보처리기사 필기"
    if part == "practical":
        return "정보처리기사 실기"
    return "정보처리기사"


def _normalize(sample: dict[str, Any], *, source_batch: str, fallback_id: str) -> dict[str, Any]:
    out = deepcopy(sample)
    meta = out.setdefault("meta", {})
    meta.setdefault("id", fallback_id)
    meta.setdefault("provenance", "exam-crawl")
    meta.setdefault("source", "exam-crawl-structured")
    meta.setdefault("exam_type", _exam_type(meta))
    meta["source_batch"] = source_batch
    return out


def combine(paths: list[Path]) -> tuple[list[dict[str, Any]], Counter[str], list[str]]:
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    skipped: list[str] = []
    by_batch: Counter[str] = Counter()

    for path in paths:
        batch = path.stem
        for idx, sample in enumerate(_load_jsonl(path), start=1):
            fallback_id = f"{batch}-{idx}"
            normalized = _normalize(sample, source_batch=batch, fallback_id=fallback_id)
            sample_id = str(normalized.get("meta", {}).get("id") or fallback_id)
            if sample_id in seen:
                skipped.append(sample_id)
                continue
            seen.add(sample_id)
            samples.append(normalized)
            by_batch[batch] += 1

    return samples, by_batch, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 SFT JSONL 배치 합본 생성")
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    samples, by_batch, skipped = combine(args.inputs)
    write_jsonl(samples, args.out)

    by_part = Counter((s.get("meta") or {}).get("exam_part", "?") for s in samples)
    by_result = Counter((s.get("meta") or {}).get("result", "?") for s in samples)
    print(f"combined {len(samples)} samples -> {args.out}")
    for batch, count in by_batch.items():
        print(f"  batch {batch}: {count}")
    for part, count in by_part.items():
        print(f"  part {part}: {count}")
    for result, count in by_result.items():
        print(f"  result {result}: {count}")
    if skipped:
        print(f"  skipped duplicate ids: {len(skipped)}")


if __name__ == "__main__":
    main()
