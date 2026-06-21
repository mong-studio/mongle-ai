"""mixed sft_dataset.jsonl → train/valid stratified 분할.

설계 근거:
- **stratified**: provenance(daily-latte/exam-synth/distractor/exam-crawl) 별로
  비율을 보존해 train·valid 모두 골고루 섞이게 한다. 단순 head/tail 분할은 한쪽에
  특정 출처가 쏠릴 수 있어 부적합.
- **결정론적 셔플**: seed 고정으로 재현 가능.
- **exact dedup + 교차 분리**: 내용(messages) SHA256 으로 중복 제거 후, 각 고유 샘플을
  한 split 에만 배정 → train/valid 누수 없음(sft-coherence #10).
- 구조(messages/meta)는 그대로 통과시키고, 직렬화는 학습 직전 한 번만 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def _content_key(sample: dict) -> str:
    payload = json.dumps(sample["messages"], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedup(samples: list[dict]) -> list[dict]:
    """messages 내용 기준 exact 중복 제거(첫 등장 유지). 입력 비변경."""
    seen: set[str] = set()
    out: list[dict] = []
    for sample in samples:
        key = _content_key(sample)
        if key in seen:
            continue
        seen.add(key)
        out.append(sample)
    return out


def _provenance(sample: dict) -> str:
    return (sample.get("meta") or {}).get("provenance", "?")


def stratified_split(
    samples: list[dict], *, ratio: float = 0.9, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """provenance stratified + 결정론적 셔플로 train/valid 분할.

    각 출처별로 셔플 후 ratio 지점에서 잘라 train/valid 에 비례 배분한다.
    출처 표본이 1건뿐이면 전부 train 으로 보낸다(valid 손실 방지).
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for sample in dedup(samples):
        buckets[_provenance(sample)].append(sample)

    rng = random.Random(seed)
    train: list[dict] = []
    valid: list[dict] = []
    for prov in sorted(buckets):
        items = list(buckets[prov])  # 복사 — 원본 비변경
        rng.shuffle(items)
        cut = len(items) if len(items) <= 1 else max(1, int(len(items) * ratio))
        train.extend(items[:cut])
        valid.extend(items[cut:])

    rng.shuffle(train)
    rng.shuffle(valid)
    return train, valid


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(samples: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(s, ensure_ascii=False) for s in samples)
    path.write_text(body + "\n" if body else "", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="mixed jsonl → stratified train/valid 분할")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out-train", dest="out_train", required=True, type=Path)
    parser.add_argument("--out-valid", dest="out_valid", required=True, type=Path)
    parser.add_argument("--ratio", type=float, default=0.9, help="train 비율(기본 0.9)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    samples = _read_jsonl(args.in_path)
    train, valid = stratified_split(samples, ratio=args.ratio, seed=args.seed)
    _write_jsonl(train, args.out_train)
    _write_jsonl(valid, args.out_valid)

    kept = len(train) + len(valid)
    print(f"[split] train={len(train)} valid={len(valid)} (입력 {len(samples)}, 중복제거 후 {kept})")
    print(f"[split] train by prov: {dict(Counter(_provenance(s) for s in train))}")
    print(f"[split] valid by prov: {dict(Counter(_provenance(s) for s in valid))}")


if __name__ == "__main__":
    main()
