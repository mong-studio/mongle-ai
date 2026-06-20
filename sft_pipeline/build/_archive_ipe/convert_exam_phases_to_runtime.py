"""정보처리기사 phases 기반 exam SFT를 런타임 PlanOutput 스키마로 변환한다.

입력 assistant 출력:
  {"kind":"plan","title":...,"phases":[{"tasks":[...]}],"calendar_events":[...],"summary_text":...}

출력 assistant 출력:
  {"summary_text":...,"todos":[...],"calendar_events":[...]}

기존 validate_dataset.py 와 mix_dataset.py 에 바로 연결하기 위한 어댑터다.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from sft_pipeline.build.lib.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.build.lib.prompts import runtime_system_prompt
from sft_pipeline.io_utils import write_jsonl


DEFAULT_IN = Path("sft_pipeline/data/generated/exam_information_processing_engineer_all_sft.jsonl")
DEFAULT_OUT = Path("sft_pipeline/data/generated/exam_information_processing_engineer_runtime_sft.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _clean_tags(tags: Any, *, extra: list[str]) -> list[str]:
    out: list[str] = []
    for tag in list(tags or []) + extra:
        text = str(tag).strip()
        if text and text not in out:
            out.append(text)
    return out[:8]


def _runtime_task(task: dict[str, Any], *, phase: str | None = None) -> dict[str, Any]:
    extras = [phase] if phase else []
    priority = task.get("priority")
    if priority:
        extras.append(f"priority:{priority}")
    return {
        "title": str(task.get("title", "")).strip()[:20],
        "due_date": str(task.get("due_date", "")).strip(),
        "tags": _clean_tags(task.get("tags"), extra=extras),
    }


def _event_task(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(event.get("title", "")).strip()[:20],
        "due_date": str(event.get("due_date", "")).strip(),
        "tags": _clean_tags(event.get("tags"), extra=[]),
    }


def _convert_plan(plan: dict[str, Any], *, today: date) -> dict[str, Any]:
    todos: list[dict[str, Any]] = []
    calendar_events: list[dict[str, Any]] = []

    for phase in plan.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        phase_name = str(phase.get("phase", "")).strip() or None
        for task in phase.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            converted = _runtime_task(task, phase=phase_name)
            due = date.fromisoformat(converted["due_date"])
            if due == today:
                todos.append(converted)
            else:
                calendar_events.append(converted)

    for event in plan.get("calendar_events") or []:
        if not isinstance(event, dict):
            continue
        converted = _event_task(event)
        due = date.fromisoformat(converted["due_date"])
        if due == today:
            todos.append(converted)
        else:
            calendar_events.append(converted)

    return {
        "summary_text": plan.get("summary_text"),
        "todos": todos,
        "calendar_events": calendar_events,
    }


def _replace_system_prompt(messages: list[dict[str, Any]], *, today: str) -> list[dict[str, Any]]:
    out = deepcopy(messages)
    prompt = runtime_system_prompt(
        today,
        extra_quality="시험 계획에서는 정확한 시험명·과목명·합격 기준·취약 범위 반영",
    )
    if out and out[0].get("role") == "system":
        out[0]["content"] = prompt
    else:
        out.insert(0, {"role": "system", "content": prompt})
    return out


def convert_sample(sample: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(sample)
    meta = out.setdefault("meta", {})
    today = date.fromisoformat(str(meta["today"]))
    old_plan = json.loads(out["messages"][-1]["content"])
    runtime_plan = _convert_plan(old_plan, today=today)

    # 변환 결과를 기존 런타임 미러 스키마로 즉시 확인한다.
    parsed = parse_plan(json.dumps(runtime_plan, ensure_ascii=False))
    errors = check_plan_consistency(
        parsed,
        today=today,
        horizon_days=int(meta["time_left_days"]) if meta.get("time_left_days") else None,
    )
    if errors:
        sample_id = meta.get("id", "?")
        raise ValueError(f"{sample_id}: converted plan consistency errors: {errors}")

    out["messages"] = _replace_system_prompt(out["messages"], today=str(meta["today"]))
    out["messages"][-1]["content"] = json.dumps(runtime_plan, ensure_ascii=False)
    meta["output_schema"] = "runtime-plan-v1"
    meta["converted_from_schema"] = "exam-phases-v1"
    return out


def convert_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [convert_sample(sample) for sample in samples]


def main() -> None:
    parser = argparse.ArgumentParser(description="정보처리기사 phases SFT → 런타임 PlanOutput SFT 변환")
    parser.add_argument("--in", dest="in_path", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    samples = convert_samples(_load_jsonl(args.in_path))
    write_jsonl(samples, args.out_path)
    by_part = Counter((s.get("meta") or {}).get("exam_part", "?") for s in samples)
    by_result = Counter((s.get("meta") or {}).get("result", "?") for s in samples)
    print(f"converted {len(samples)} samples -> {args.out_path}")
    for part, count in by_part.items():
        print(f"  part {part}: {count}")
    for result, count in by_result.items():
        print(f"  result {result}: {count}")


if __name__ == "__main__":
    main()
