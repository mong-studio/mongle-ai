"""SFT JSONL 품질 검사. 스키마·빈값·input 복붙(output==input) 휴리스틱.

참고: 이 검증기는 '데이터셋 위생'(스키마/빈값/프롬프트 복붙)만 본다.
원문(블로그) 표절 방지는 상류 단계의 책임이다 - actual_plan_summary 는
사람이 재서술한 요약이어야 하며(원문 복붙 금지), 이는 수집 검수 체크리스트
(reports/preprocessing_report_template.md)와 README 가이드로 강제한다.
build_output 은 의도적으로 actual_plan_summary 를 템플릿에 포함하므로,
output 이 요약을 포함하는지 검사하지 않는다(정상 동작을 오탐하게 됨).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = {"instruction", "input", "output", "meta"}
REQUIRED_META = {"source_url", "exam_type", "result"}
MIN_OUTPUT_LEN = 20


def _validate_one(sample: dict, idx: int) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_KEYS - set(sample)
    if missing:
        errors.append(f"line {idx}: missing keys {sorted(missing)}")
        return errors

    for key in ("instruction", "input", "output"):
        if not str(sample[key]).strip():
            errors.append(f"line {idx}: empty {key}")

    meta = sample.get("meta") or {}
    meta_missing = REQUIRED_META - set(meta)
    if meta_missing:
        errors.append(f"line {idx}: meta missing {sorted(meta_missing)}")

    output = str(sample.get("output", ""))
    if len(output.strip()) < MIN_OUTPUT_LEN:
        errors.append(f"line {idx}: output too short (<{MIN_OUTPUT_LEN})")
    if output.strip() and output.strip() == str(sample.get("input", "")).strip():
        errors.append(f"line {idx}: raw_copy (output == input)")
    return errors


def validate_samples(path: Path) -> dict:
    errors: list[str] = []
    ok = 0
    with open(path, encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid json ({exc})")
                continue
            line_errors = _validate_one(sample, idx)
            if line_errors:
                errors.extend(line_errors)
            else:
                ok += 1
    return {"ok": ok, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="SFT JSONL 품질 검사")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    args = parser.parse_args()
    report = validate_samples(args.in_path)
    print(f"ok={report['ok']} errors={len(report['errors'])}")
    for err in report["errors"]:
        print(f"  - {err}")
    sys.exit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
