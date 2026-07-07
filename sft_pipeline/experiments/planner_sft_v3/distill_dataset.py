"""GPT-4o teacher 증류 러너 — 3단 게이트 필터 + input_id 단위 재개 캐시.

라이브 실행(비용 발생): OPENAI_API_KEY 필요.
  uv run python -m sft_pipeline.experiments.planner_sft_v3.distill_dataset \
    --out sft_pipeline/experiments/planner_sft_v3/data/planner_sft_v3_gold.jsonl \
    --holdout-out sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    SEMANTIC_JUDGE_SYSTEM,
    check_structure,
    parse_judge_reply,
    semantic_judge_user,
    verdict,
)
from sft_pipeline.experiments.planner_sft_v3.goal_corpus import build_inputs
from sft_pipeline.io_utils import write_jsonl

CompleteFn = Callable[[str, str], str]

_FIX_SUFFIX = "\n\n[재생성 요청] 직전 계획은 분배·순서·완결성 점수가 낮았다. 목표에 더 밀착한 내용으로 다시 작성하라."


def _evaluate_candidate(text: str, item: dict) -> tuple[str, list[str], dict | None, str | None]:
    """(state, structure_issues, plan, syntax_error)"""
    try:
        plan = contract.parse_plan_output(text)
    except ValueError as exc:
        return "DROP", [], None, f"구문: {exc}"
    issues = check_structure(plan, item["parsed_goal"], date.fromisoformat(item["today"]))
    if issues:
        return "DROP", issues, plan, None
    return "PENDING_JUDGE", [], plan, None


def run_distill(
    inputs: list[dict],
    complete: CompleteFn,
    judge: CompleteFn,
    cache_dir: Path,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    accepted: list[dict] = []
    drop_reasons: Counter[str] = Counter()
    fix_retried = 0

    for item in inputs:
        cache_file = cache_dir / f"{item['input_id']}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("record"):
                accepted.append(cached["record"])
            else:
                drop_reasons[cached["reason"]] += 1
            continue

        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        record, reason = None, None
        prompt_user = user
        for attempt in range(2):  # 최초 1회 + FIX 재생성 1회
            text = complete(contract.SYSTEM_PROMPT, prompt_user)
            state, issues, plan, syntax_error = _evaluate_candidate(text, item)
            if state == "DROP":
                reason = syntax_error or issues[0]
                break
            judge_reply = judge(SEMANTIC_JUDGE_SYSTEM, semantic_judge_user(plan, item["parsed_goal"]))
            try:
                scores = parse_judge_reply(judge_reply)
            except ValueError as exc:
                reason = f"judge: {exc}"
                break
            decision = verdict(True, issues, scores["average"])
            if decision == "ACCEPT":
                record = {
                    "messages": [
                        {"role": "system", "content": contract.SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": text},
                    ],
                    "meta": {
                        "provenance": "planner-sft-v3-distill",
                        "dataset_version": "v3",
                        "domain": item["domain"],
                        "input_id": item["input_id"],
                        "today": item["today"],
                        "judge_scores": scores,
                    },
                }
                break
            if decision == "FIX" and attempt == 0:
                fix_retried += 1
                prompt_user = user + _FIX_SUFFIX
                continue
            reason = f"의미 평균 {scores['average']} ({decision})"
            break

        cache_file.write_text(
            json.dumps({"record": record, "reason": reason}, ensure_ascii=False),
            encoding="utf-8",
        )
        if record:
            accepted.append(record)
        else:
            drop_reasons[reason or "unknown"] += 1

    return {
        "accepted": accepted,
        "report": {
            "total": len(inputs),
            "accepted": len(accepted),
            "fix_retried": fix_retried,
            "dropped": sum(drop_reasons.values()),
            "drop_reasons": dict(drop_reasons),
        },
    }


def _openai_fns() -> tuple[CompleteFn, CompleteFn]:
    from openai import OpenAI  # crawl/daily_extractor.py 와 동일 의존성

    client = OpenAI()

    def _call(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        return response.choices[0].message.content or ""

    return _call, _call


def main() -> None:
    parser = argparse.ArgumentParser(description="planner SFT v3 teacher 증류")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--holdout-out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path,
                        default=Path("outputs/planner-sft-v3-distill-cache"))
    parser.add_argument("--limit", type=int, default=0, help="스모크용 입력 제한(0=전체)")
    args = parser.parse_args()

    train_inputs, holdout_inputs = build_inputs()
    if args.limit:
        train_inputs = train_inputs[: args.limit]
    complete, judge = _openai_fns()
    result = run_distill(train_inputs, complete, judge, args.cache_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(result["accepted"], args.out)
    write_jsonl(holdout_inputs, args.holdout_out)
    report_path = args.out.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(result["report"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[sft-v3] accepted {result['report']['accepted']}/{result['report']['total']}"
          f" -> {args.out} (드롭 사유: {report_path})")


if __name__ == "__main__":
    main()
