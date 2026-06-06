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

from sft_pipeline.io_utils import write_jsonl

# 외부 공개판에 허용되는 출처(provenance) 화이트리스트(fail-closed).
# 라이선스가 명시적으로 공개 가능한 출처만 통과시킨다. 누락/오타/미지정 출처는
# 저작권 안전을 위해 기본 제외한다.
_PUBLIC_ALLOWED = {"daily-latte"}
RELEASES = ("public", "internal")


def mix(samples: list[dict], *, release: str) -> list[dict]:
    if release not in RELEASES:
        raise ValueError(f"release must be one of {RELEASES}, got {release!r}")
    if release == "internal":
        return list(samples)
    return [s for s in samples if (s.get("meta") or {}).get("provenance") in _PUBLIC_ALLOWED]


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


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
    print(f"[mix][{args.release}] wrote {len(mixed)} samples -> {args.out_path}")
    for prov, n in by_prov.most_common():
        print(f"[mix]   {prov}: {n}")


if __name__ == "__main__":
    main()
