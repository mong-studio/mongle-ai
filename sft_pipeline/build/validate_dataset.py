"""SFT JSONL 품질 검사. messages 스키마·빈값·역할 순서·직전 user 복붙 휴리스틱.

참고: 이 검증기는 '데이터셋 위생'(스키마/빈값/프롬프트 복붙)만 본다.
원문(블로그) 표절 방지는 상류 단계의 책임이다 - actual_plan_summary 는
사람이 재서술한 요약이어야 하며(원문 복붙 금지), 이는 수집 검수 체크리스트
(reports/preprocessing_report_template.md)와 README 가이드로 강제한다.

스키마는 단일턴(시험준비)과 멀티턴(일상)을 모두 담는 messages 형식으로 통일한다.
meta.provenance 로 출처를 구분하며, exam-crawl 출처에만 exam_type/result 를 강제한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = {"messages", "meta"}
EXAM_REQUIRED_META = {"source_url", "exam_type", "result"}
VALID_ROLES = {"system", "user", "assistant"}
MIN_OUTPUT_LEN = 20


def _validate_messages(messages, idx: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(messages, list) or len(messages) < 2:
        return [f"line {idx}: messages must be a list of >=2 turns"]

    for j, m in enumerate(messages):
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            errors.append(f"line {idx}: message {j} missing role/content")
            continue
        if m["role"] not in VALID_ROLES:
            errors.append(f"line {idx}: message {j} invalid role {m['role']!r}")
        if not str(m["content"]).strip():
            errors.append(f"line {idx}: message {j} empty content")
    if errors:
        return errors

    roles = [m["role"] for m in messages]
    if "user" not in roles:
        errors.append(f"line {idx}: no user turn")
    if roles[-1] != "assistant":
        errors.append(f"line {idx}: last turn must be assistant")
        return errors

    last = str(messages[-1]["content"]).strip()
    if len(last) < MIN_OUTPUT_LEN:
        errors.append(f"line {idx}: last assistant too short (<{MIN_OUTPUT_LEN})")
    prev_user = next(
        (str(m["content"]).strip() for m in reversed(messages[:-1]) if m["role"] == "user"),
        "",
    )
    if last and last == prev_user:
        errors.append(f"line {idx}: raw_copy (assistant == preceding user)")
    return errors


def _validate_meta(meta: dict, idx: int) -> list[str]:
    errors: list[str] = []
    if "provenance" not in meta:
        errors.append(f"line {idx}: meta missing ['provenance']")
    if meta.get("provenance") == "exam-crawl":
        missing = EXAM_REQUIRED_META - set(meta)
        if missing:
            errors.append(f"line {idx}: meta missing {sorted(missing)}")
    return errors


def _validate_one(sample: dict, idx: int) -> list[str]:
    missing = REQUIRED_KEYS - set(sample)
    if missing:
        return [f"line {idx}: missing keys {sorted(missing)}"]
    errors = _validate_messages(sample.get("messages"), idx)
    errors += _validate_meta(sample.get("meta") or {}, idx)
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
