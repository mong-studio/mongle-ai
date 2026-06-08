"""구 meta 스키마 jsonl 을 task_type 스키마로 1회성 마이그레이션한다.

이미 생성·정제된 클린셋(messages)은 그대로 두고 meta 만 새 스키마로 바꾼다:
- `task_type` 추가: provenance='distractor' 면 'chat', 그 외는 'plan'
- `turn_type` 제거 (전 샘플 'single' 상수, 소비처 없음 — task_type 이 역할 흡수)
- `is_distractor` 제거 (provenance='distractor' 와 완전 중복)
- `rephrased_by` → `synthesized_by` 이름 통일 (exam-crawl 만 쓰던 다른 이름)

새 스키마 입력에 다시 돌려도 변화가 없다(멱등). messages 는 절대 손대지 않는다
— 학습 토큰 시퀀스 불변이 마이그레이션의 전제다.

실행:
    python -m sft_pipeline.build.migrate_meta \
        --in sft_pipeline/data/generated/daily_v2_clean.jsonl \
        --out sft_pipeline/data/generated/daily_v2_clean.jsonl
    (--in 과 --out 이 같으면 전체를 읽은 뒤 한 번에 덮어쓴다)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sft_pipeline.io_utils import write_jsonl

# 구 스키마에서 제거할 키들
_DROP_KEYS = {"turn_type", "is_distractor"}


def migrate_meta(meta: dict) -> dict:
    """meta 한 개를 새 스키마로 변환한 새 딕셔너리를 돌려준다(입력 불변)."""
    out = {k: v for k, v in meta.items() if k not in _DROP_KEYS}
    if "rephrased_by" in out:
        out["synthesized_by"] = out.pop("rephrased_by")
    if "task_type" not in out:
        provenance = out.get("provenance")
        out["task_type"] = "chat" if provenance == "distractor" else "plan"
    return out


def migrate_sample(sample: dict) -> dict:
    """샘플 한 개의 meta 만 변환한다. messages 는 그대로 통과."""
    return {**sample, "meta": migrate_meta(sample.get("meta") or {})}


def migrate_file(in_path: Path, out_path: Path) -> int:
    """jsonl 전체를 변환해 쓴다. 변환한 샘플 수를 돌려준다.

    전량을 먼저 메모리에 읽고 나서 쓰므로 --in 과 --out 이 같아도 안전하다.
    """
    samples = []
    with open(in_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            samples.append(migrate_sample(json.loads(line)))
    write_jsonl(samples, out_path)
    return len(samples)


def main() -> None:
    parser = argparse.ArgumentParser(description="구 meta 스키마 → task_type 스키마 마이그레이션")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()
    n = migrate_file(args.in_path, args.out_path)
    print(f"[migrate_meta] {n} samples: {args.in_path} -> {args.out_path}")


if __name__ == "__main__":
    main()
