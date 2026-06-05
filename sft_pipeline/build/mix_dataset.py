"""시험(exam-crawl) + 일상(daily-latte) messages 샘플을 release 정책에 맞게 믹스.

- release=public : 저작권 위험이 있는 exam-crawl 을 provenance 기준으로 제외(일상만 공개).
- release=internal: 전체 포함(내부 학습용).
저작권 정책: 시험-크롤은 라이선스 없는 블로그 기반이라 외부 배포 불가.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# 외부 공개판에서 제외할 출처(provenance).
_EXCLUDE_FROM_PUBLIC = {"exam-crawl"}
RELEASES = ("public", "internal")


def mix(samples: list[dict], *, release: str) -> list[dict]:
    if release not in RELEASES:
        raise ValueError(f"release must be one of {RELEASES}, got {release!r}")
    if release == "internal":
        return list(samples)
    return [s for s in samples if (s.get("meta") or {}).get("provenance") not in _EXCLUDE_FROM_PUBLIC]


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(samples: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="exam/daily messages → sft_dataset.jsonl (release 믹스)")
    parser.add_argument("--exam", type=Path, default=None, help="시험 jsonl(exam-crawl)")
    parser.add_argument("--daily", type=Path, default=None, help="일상 jsonl(daily-latte)")
    parser.add_argument("--release", choices=RELEASES, default="internal")
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()

    samples: list[dict] = []
    for src in (args.exam, args.daily):
        if src is not None:
            samples.extend(load_jsonl(src))

    mixed = mix(samples, release=args.release)
    write_jsonl(mixed, args.out_path)
    by_prov = Counter((s.get("meta") or {}).get("provenance", "?") for s in mixed)
    print(f"[{args.release}] wrote {len(mixed)} samples -> {args.out_path}")
    for prov, n in by_prov.most_common():
        print(f"  {prov}: {n}")


if __name__ == "__main__":
    main()
