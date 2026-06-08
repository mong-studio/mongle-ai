"""structured.csv → sft_dataset.jsonl. --use-llm/--split/--today 옵션 지원."""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from sft_pipeline.build.rephrase import make_client, rephrase
from sft_pipeline.build.templates import build_input, build_instruction, build_plan
from sft_pipeline.io_utils import write_jsonl


def _to_float(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value):
    if value in ("", None):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def build_samples(
    structured_path: Path,
    *,
    today: date | None = None,
    use_llm: bool = False,
    client=None,
    model: str = "gpt-4o-mini",
) -> list[dict]:
    today = today or date.today()
    with open(structured_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    samples: list[dict] = []
    for i, case in enumerate(rows):
        plan = build_plan(case, today)
        # JSON 구조는 보존하고 전략 내러티브(summary_text)만 LLM 재서술 대상이다.
        summary, by = rephrase(
            plan.summary_text or "", use_llm=use_llm, client=client, model=model
        )
        if by == "llm":
            plan = plan.model_copy(update={"summary_text": summary.strip()[:1500]})
        user_content = f"{build_instruction(case, i)}\n\n{build_input(case, today)}"
        samples.append(
            {
                "messages": [
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": plan.model_dump_json()},
                ],
                "meta": {
                    "provenance": "exam-crawl",
                    "task_type": "plan",
                    "source_url": case.get("source_url", ""),
                    "exam_type": case.get("exam_type", ""),
                    "result": case.get("result", ""),
                    "time_left_days": _to_int(case.get("time_left_days", "")),
                    "daily_hours": _to_float(case.get("daily_hours_value", "")),
                    "today": today.isoformat(),
                    "evidence_spans": case.get("evidence_spans", ""),
                    "synthesized_by": by,
                },
            }
        )
    return samples


def _split(samples: list[dict], ratio: float = 0.8) -> tuple[list[dict], list[dict]]:
    cut = max(1, int(len(samples) * ratio))
    return samples[:cut], samples[cut:]


def main() -> None:
    parser = argparse.ArgumentParser(description="structured.csv → sft_dataset.jsonl")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--split", action="store_true", help="train/valid 분리 출력(8:2)")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="due_date 산술 기준일(YYYY-MM-DD). 미지정 시 오늘. 재현 빌드 시 고정 권장.",
    )
    args = parser.parse_args()

    client = make_client() if args.use_llm else None
    if args.use_llm and client is None:
        print("[build] warning: --use-llm 지정됐지만 OPENAI_API_KEY 가 없어 템플릿으로 대체합니다.", file=sys.stderr)
    samples = build_samples(args.in_path, today=args.today, use_llm=args.use_llm, client=client)

    if args.split:
        train, valid = _split(samples)
        if not valid:
            print("[build] warning: 샘플이 너무 적어 valid 세트가 비었습니다.", file=sys.stderr)
        write_jsonl(train, args.out_path.with_name(args.out_path.stem + "_train.jsonl"))
        write_jsonl(valid, args.out_path.with_name(args.out_path.stem + "_valid.jsonl"))
        print(f"[build] wrote {len(train)} train / {len(valid)} valid")
    else:
        write_jsonl(samples, args.out_path)
        print(f"[build] wrote {len(samples)} samples -> {args.out_path}")


if __name__ == "__main__":
    main()
