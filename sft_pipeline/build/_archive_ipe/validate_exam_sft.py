"""정보처리기사 exam SFT JSONL 전용 검증기.

기존 validate_dataset.py 는 런타임 GenerateResult 형태
(`summary_text`/`todos`/`calendar_events`)를 검사한다. 정보처리기사 1차
크롤 데이터는 시험 계획 보고서용 `kind/title/phases/calendar_events` 형태라
별도 검증기로 형식과 공식 기준 반영 여부를 확인한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.validate_dataset import (
    _validate_language,
    _validate_messages,
)


REQUIRED_KEYS = {"messages", "meta"}
REQUIRED_META = {
    "id",
    "today",
    "provenance",
    "source_url",
    "source_batch",
    "exam_type",
    "exam_part",
    "result",
    "time_left_days",
    "study_process_summary",
    "review_summary",
}
VALID_EXAM_PARTS = {"written", "practical"}
VALID_PRIORITIES = {"high", "medium", "low"}
WRITTEN_REQUIRED_TERMS = (
    "소프트웨어설계",
    "소프트웨어개발",
    "데이터베이스구축",
    "프로그래밍언어활용",
    "정보시스템구축관리",
    "과목당 40점 이상",
    "평균 60점 이상",
)
PRACTICAL_REQUIRED_TERMS = (
    "정보처리실무",
    "60점 이상",
)


def _parse_date(value: Any, *, field: str, idx: int, errors: list[str]) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"line {idx}: invalid {field} date {value!r}")
        return None


def _validate_meta(meta: dict[str, Any], idx: int) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_META - set(meta)
    if missing:
        errors.append(f"line {idx}: meta missing {sorted(missing)}")
    if meta.get("provenance") != "exam-crawl":
        errors.append(f"line {idx}: meta.provenance must be 'exam-crawl'")
    if meta.get("exam_part") not in VALID_EXAM_PARTS:
        errors.append(f"line {idx}: invalid exam_part {meta.get('exam_part')!r}")
    if not str(meta.get("source_url", "")).startswith(("http://", "https://")):
        errors.append(f"line {idx}: source_url must be http(s)")
    if "time_left_days" in meta:
        days = meta.get("time_left_days")
        if not isinstance(days, int) or days <= 0:
            errors.append(f"line {idx}: time_left_days must be a positive integer")
    return errors


def _validate_task(task: Any, idx: int, phase_no: int, task_no: int) -> list[str]:
    errors: list[str] = []
    where = f"line {idx}: phase {phase_no} task {task_no}"
    if not isinstance(task, dict):
        return [f"{where} must be an object"]
    for key in ("title", "due_date", "priority", "tags"):
        if key not in task:
            errors.append(f"{where} missing {key!r}")
    if task.get("priority") not in VALID_PRIORITIES:
        errors.append(f"{where} invalid priority {task.get('priority')!r}")
    if not isinstance(task.get("tags"), list):
        errors.append(f"{where} tags must be a list")
    if not str(task.get("title", "")).strip():
        errors.append(f"{where} empty title")
    return errors


def _validate_plan_shape(plan: Any, meta: dict[str, Any], idx: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return [f"line {idx}: assistant JSON must be an object"]
    for key in ("kind", "title", "deadline", "phases", "calendar_events", "summary_text"):
        if key not in plan:
            errors.append(f"line {idx}: assistant JSON missing {key!r}")
    if errors:
        return errors
    if plan.get("kind") != "plan":
        errors.append(f"line {idx}: assistant kind must be 'plan'")
    if not str(plan.get("title", "")).strip():
        errors.append(f"line {idx}: empty title")
    if not str(plan.get("summary_text", "")).strip():
        errors.append(f"line {idx}: empty summary_text")

    today = _parse_date(meta.get("today"), field="meta.today", idx=idx, errors=errors)
    deadline = _parse_date(plan.get("deadline"), field="deadline", idx=idx, errors=errors)
    horizon_days = meta.get("time_left_days")
    max_due = today + timedelta(days=horizon_days) if today and isinstance(horizon_days, int) else None
    if today and deadline:
        if deadline < today:
            errors.append(f"line {idx}: deadline before meta.today")
        if max_due and deadline > max_due:
            errors.append(f"line {idx}: deadline beyond time_left_days horizon")

    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append(f"line {idx}: phases must be a non-empty list")
        return errors
    for phase_no, phase in enumerate(phases, start=1):
        if not isinstance(phase, dict):
            errors.append(f"line {idx}: phase {phase_no} must be an object")
            continue
        for key in ("phase", "due_date", "tasks"):
            if key not in phase:
                errors.append(f"line {idx}: phase {phase_no} missing {key!r}")
        phase_due = _parse_date(phase.get("due_date"), field=f"phase {phase_no} due_date", idx=idx, errors=errors)
        if today and phase_due and phase_due < today:
            errors.append(f"line {idx}: phase {phase_no} due_date before meta.today")
        if max_due and phase_due and phase_due > max_due:
            errors.append(f"line {idx}: phase {phase_no} due_date beyond horizon")
        tasks = phase.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"line {idx}: phase {phase_no} tasks must be a non-empty list")
            continue
        for task_no, task in enumerate(tasks, start=1):
            errors += _validate_task(task, idx, phase_no, task_no)
            if isinstance(task, dict) and "due_date" in task:
                task_due = _parse_date(task.get("due_date"), field=f"phase {phase_no} task {task_no} due_date", idx=idx, errors=errors)
                if today and task_due and task_due < today:
                    errors.append(f"line {idx}: phase {phase_no} task {task_no} due_date before meta.today")
                if max_due and task_due and task_due > max_due:
                    errors.append(f"line {idx}: phase {phase_no} task {task_no} due_date beyond horizon")

    calendar_events = plan.get("calendar_events")
    if not isinstance(calendar_events, list):
        errors.append(f"line {idx}: calendar_events must be a list")
    else:
        for event_no, event in enumerate(calendar_events, start=1):
            if not isinstance(event, dict):
                errors.append(f"line {idx}: calendar event {event_no} must be an object")
                continue
            for key in ("title", "due_date", "tags"):
                if key not in event:
                    errors.append(f"line {idx}: calendar event {event_no} missing {key!r}")
            if "due_date" in event:
                _parse_date(event.get("due_date"), field=f"calendar event {event_no} due_date", idx=idx, errors=errors)
            if not isinstance(event.get("tags"), list):
                errors.append(f"line {idx}: calendar event {event_no} tags must be a list")
    return errors


def _validate_official_terms(plan_text: str, meta: dict[str, Any], idx: int) -> list[str]:
    errors: list[str] = []
    terms = WRITTEN_REQUIRED_TERMS if meta.get("exam_part") == "written" else PRACTICAL_REQUIRED_TERMS
    missing = [term for term in terms if term not in plan_text]
    if missing:
        errors.append(f"line {idx}: assistant missing official terms {missing}")
    return errors


def _validate_one(sample: dict[str, Any], idx: int) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_KEYS - set(sample)
    if missing:
        return [f"line {idx}: missing keys {sorted(missing)}"]

    messages = sample.get("messages")
    meta = sample.get("meta") or {}
    errors += _validate_messages(messages, idx)
    if isinstance(messages, list):
        errors += _validate_language(messages, idx)
    if not isinstance(meta, dict):
        errors.append(f"line {idx}: meta must be an object")
        return errors
    errors += _validate_meta(meta, idx)
    if errors:
        return errors

    assistant_text = str(messages[-1]["content"])
    try:
        plan = json.loads(assistant_text)
    except json.JSONDecodeError as exc:
        return [f"line {idx}: assistant content is not JSON ({exc})"]
    errors += _validate_plan_shape(plan, meta, idx)
    errors += _validate_official_terms(assistant_text, meta, idx)
    return errors


def validate_samples(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    ok = 0
    by_part: Counter[str] = Counter()
    by_result: Counter[str] = Counter()
    by_batch: Counter[str] = Counter()
    seen_ids: set[str] = set()

    with path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid json ({exc})")
                continue
            meta = sample.get("meta") if isinstance(sample, dict) else {}
            line_errors: list[str] = []
            if isinstance(meta, dict):
                sample_id = meta.get("id")
                if sample_id in seen_ids:
                    line_errors.append(f"line {idx}: duplicate meta.id {sample_id!r}")
                elif sample_id:
                    seen_ids.add(str(sample_id))
                by_part[str(meta.get("exam_part", "?"))] += 1
                by_result[str(meta.get("result", "?"))] += 1
                by_batch[str(meta.get("source_batch", "?"))] += 1
            line_errors += _validate_one(sample, idx) if isinstance(sample, dict) else [f"line {idx}: sample must be an object"]
            if line_errors:
                errors.extend(line_errors)
            else:
                ok += 1

    return {
        "ok": ok,
        "errors": errors,
        "by_part": dict(by_part),
        "by_result": dict(by_result),
        "by_batch": dict(by_batch),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 exam SFT JSONL 전용 검증")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="검증 요약을 JSON으로 출력")
    args = parser.parse_args()

    report = validate_samples(args.in_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[validate-exam] ok={report['ok']} errors={len(report['errors'])}")
        print(f"[validate-exam] by_part={report['by_part']}")
        print(f"[validate-exam] by_result={report['by_result']}")
        for err in report["errors"]:
            print(f"[validate-exam]   - {err}")
    sys.exit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
