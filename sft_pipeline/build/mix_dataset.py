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
#   - daily-latte: MS-LaTTE(MIT) 유래 일상 플랜
#   - distractor : 우리가 직접 만든 네거티브(경계) 데이터 → 저작권 이슈 없음
_PUBLIC_ALLOWED = {"daily-latte", "distractor"}
RELEASES = ("public", "internal")


def mix(samples: list[dict], *, release: str) -> list[dict]:
    if release not in RELEASES:
        raise ValueError(f"release must be one of {RELEASES}, got {release!r}")
    if release == "internal":
        return list(samples)
    return [s for s in samples if (s.get("meta") or {}).get("provenance") in _PUBLIC_ALLOWED]


def interleave(base: list[dict], extra: list[dict]) -> list[dict]:
    """extra 항목을 base 사이에 고르게 끼워 넣는다(둘 다 원래 순서 보존, 결정론적).

    distractor 를 플랜 샘플 전체에 균등 분산시켜, 트레이너가 셔플하지 않더라도
    네거티브가 끝에 몰리지 않게 한다. base/extra 중 하나가 비면 나머지를 그대로 반환.
    부동소수 없이 정수 비교(ei*nb <= bi*ne)로 진행률을 맞춰 균등 분산한다.
    """
    if not extra:
        return list(base)
    if not base:
        return list(extra)
    out: list[dict] = []
    bi = ei = 0
    nb, ne = len(base), len(extra)
    for _ in range(nb + ne):
        if ei < ne and (bi >= nb or ei * nb <= bi * ne):
            out.append(extra[ei])
            ei += 1
        else:
            out.append(base[bi])
            bi += 1
    return out


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="exam/daily messages → sft_dataset.jsonl (release 믹스)")
    parser.add_argument("--exam", type=Path, default=None, help="시험 jsonl(exam-crawl)")
    parser.add_argument("--daily", type=Path, default=None, help="일상 jsonl(daily-latte)")
    parser.add_argument(
        "--distractor",
        type=Path,
        default=None,
        help="distractor jsonl(네거티브). 플랜 샘플 사이에 균등 인터리브된다.",
    )
    parser.add_argument("--release", choices=RELEASES, default="internal")
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    args = parser.parse_args()

    # 플랜 샘플(exam/daily)과 distractor 를 따로 모은다 — 인터리브를 위해 분리.
    plan_samples: list[dict] = []
    for src in (args.exam, args.daily):
        if src is not None:
            plan_samples.extend(load_jsonl(src))
    distractor_samples = load_jsonl(args.distractor) if args.distractor else []

    # release 정책은 두 그룹 각각에 적용(공개판은 화이트리스트 밖 출처 제외).
    plans = mix(plan_samples, release=args.release)
    distractors = mix(distractor_samples, release=args.release)
    # distractor 를 플랜 전체에 균등 분산(끝에 몰리지 않게).
    mixed = interleave(plans, distractors)

    write_jsonl(mixed, args.out_path)
    by_prov = Counter((s.get("meta") or {}).get("provenance", "?") for s in mixed)
    print(f"[mix][{args.release}] wrote {len(mixed)} samples -> {args.out_path}")
    for prov, n in by_prov.most_common():
        print(f"[mix]   {prov}: {n}")


if __name__ == "__main__":
    main()
