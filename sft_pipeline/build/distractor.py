"""distractor(네거티브) 샘플을 SFT {messages, meta} 포맷으로 변환·서브샘플.

distractor 는 '플랜을 만들면 안 되는' 경계 사례다 — 잡담/감사, 과약속 거절,
모호한 의도 되묻기, 프롬프트 인젝션 방어, 범위 밖·위험 요청 거절 등.
assistant 출력이 플랜 JSON 이 아니라 평문 대화이므로 meta.provenance='distractor'
로 표시해 validate 2층(플랜 정합성)을 건너뛰게 한다(1층 위생만 적용).

이런 네거티브를 일정 비율 섞으면, 모든 입력에 플랜 JSON 을 토해내는 과생성을
막고 '언제 플랜을 만들고 언제 대화/거절할지'의 경계를 학습시킬 수 있다.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sft_pipeline.io_utils import write_jsonl

PROVENANCE = "distractor"


def to_sample(rec: dict) -> dict:
    """distractor 원본 레코드를 SFT {messages, meta} 포맷으로 변환한다."""
    return {
        "messages": rec["messages"],
        "meta": {
            "provenance": PROVENANCE,
            "turn_type": "single",
            "source_id": str(rec.get("id", "")),
            "label": rec.get("label", ""),
            "distractor_type": rec.get("distractor_type", ""),
            "is_distractor": True,
            "source": rec.get("source", ""),
        },
    }


def stratified_sample(records: list[dict], *, fraction: float) -> list[dict]:
    """distractor_type 비율을 보존하며 결정론적으로 fraction 만큼 고른다.

    각 유형 그룹을 id 로 정렬한 뒤 앞에서 round(fraction*n)개(최소 1개)를 취한다.
    난수를 쓰지 않아 같은 입력이면 항상 같은 결과(재현성).
    """
    if fraction >= 1.0:
        return list(records)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r.get("distractor_type", "")].append(r)
    out: list[dict] = []
    for dtype in sorted(groups):
        grp = sorted(groups[dtype], key=lambda r: str(r.get("id", "")))
        k = max(1, round(fraction * len(grp)))
        out.extend(grp[:k])
    return out


def load_distractors(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="distractor jsonl → SFT messages 포맷 서브샘플")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument(
        "--fraction",
        type=float,
        default=0.30,
        help="유형 비율 보존 서브샘플 비율(기본 0.30). 1.0 이면 전체 사용.",
    )
    args = parser.parse_args()

    recs = load_distractors(args.in_path)
    sampled = stratified_sample(recs, fraction=args.fraction)
    samples = [to_sample(r) for r in sampled]
    write_jsonl(samples, args.out_path)
    print(
        f"[distractor] {len(samples)}/{len(recs)} samples "
        f"(fraction={args.fraction}) -> {args.out_path}"
    )


if __name__ == "__main__":
    main()
