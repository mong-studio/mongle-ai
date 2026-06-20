from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sft_pipeline.io_utils import write_jsonl

VALID_DISTRACTOR_KINDS = frozenset({"out_of_scope", "chit_chat"})


def _kind(rec: dict) -> str:
    """포맷에 상관없이 distractor kind 반환"""
    if "meta" in rec:
        return rec["meta"].get("kind", "")
    return rec.get("distractor_type", "")


def validate_assistant_json(rec: dict) -> str | None:
    if "meta" not in rec:
        return None

    last = next(
        (m for m in reversed(rec["messages"]) if m["role"] == "assistant"), None
    )
    if last is None:
        return "[Distractor Error] assistant 메시지 없음"

    try:
        d = json.loads(last["content"])
    except json.JSONDecodeError as e:
        return f"[Distractor Error] JSON 파싱 실패: {e}"

    kind = d.get("kind")
    if kind not in VALID_DISTRACTOR_KINDS:
        return f"[Distractor Error] kind={kind!r} - {set(VALID_DISTRACTOR_KINDS)} 중 하나여야 함"
    if not d.get("message"):
        return "[Distractor Error] message 필드 없음"
    return None


def to_sample(rec: dict) -> dict:
    """distractor 레코드를 SFT {messages, meta} 포맷으로 변환"""
    meta = dict(rec["meta"])
    meta.setdefault("provenance", "distractor")
    meta.setdefault("distractor_type", meta.get("kind", "out_of_scope"))
    meta.setdefault("is_distractor", True)
    return {"messages": rec["messages"], "meta": meta}


def stratified_sample(records: list[dict], *, fraction: float) -> list[dict]:
    """kind 비율을 보존하며 결정론적으로 fraction만큼 선정"""
    if fraction >= 1.0:
        return list(records)

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[_kind(r)].append(r)

    out: list[dict] = []
    for dtype in sorted(groups):
        grp = sorted(
            groups[dtype],
            key=lambda r: str(r.get("meta", {}).get("scenario") or r.get("id", "")),
        )
        k = max(1, round(fraction * len(grp)))
        out.extend(grp[:k])
    return out


def load_distractors(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="distractor jsonl -> SFT messages 포맷 서브 샘플"
    )
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument(
        "--fraction",
        type=float,
        default=0.30,
        help="유형 비율 보존 subsample 비율(default 0.30), 1.0시 바로 전체 사용",
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
