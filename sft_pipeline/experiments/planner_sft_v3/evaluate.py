"""holdout 승격 평가 — 3단 루브릭으로 측정, 스펙 §7 임계값 미달 시 exit 1.

GPU 라이브 실행(모델 생성 + judge 채점):
  uv run python -m sft_pipeline.experiments.planner_sft_v3.evaluate \
    --adapter outputs/planner-sft-v3-run1/adapter \
    --holdout sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl \
    --out outputs/planner-sft-v3-run1/eval_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    EXAM_LEAK_TERMS,
    check_structure,
    has_english_leak,
)

BASE_MODEL = "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct"

THRESHOLDS = {
    "parse_rate": ("min", 0.85),
    "structure_violation_rate": ("max", 0.20),
    "deadline_rate": ("min", 0.75),
    "exam_leak": ("max", 0),
    "english_leak": ("max", 0),
    "semantic_avg": ("min", 3.5),
}


def score_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """모델 출력 리스트 → 게이트 지표. 순수 함수(모델·네트워크 무관)."""
    total = len(outputs)
    parsed_count = 0
    violation_count = 0
    deadline_ok = 0
    exam_leak = 0
    english_leak = 0
    semantic_scores: list[float] = []

    for out in outputs:
        goal = out["parsed_goal"]
        today = date.fromisoformat(out["today"])
        try:
            plan = contract.parse_plan_output(out["raw_text"])
        except ValueError:
            continue
        parsed_count += 1

        issues = check_structure(plan, goal, today)
        if issues:
            violation_count += 1
        full_text = json.dumps(plan, ensure_ascii=False)
        if goal.get("plan_kind") != "exam" and any(t in full_text for t in EXAM_LEAK_TERMS):
            exam_leak += 1
        if has_english_leak(full_text):
            english_leak += 1
        if not any(i.startswith("S2") for i in issues):
            deadline_ok += 1
        if out.get("judge_scores"):
            semantic_scores.append(out["judge_scores"]["average"])

    return {
        "total": total,
        "parse_rate": parsed_count / total if total else 0.0,
        "structure_violation_rate": violation_count / parsed_count if parsed_count else 1.0,
        "deadline_rate": deadline_ok / parsed_count if parsed_count else 0.0,
        "exam_leak": exam_leak,
        "english_leak": english_leak,
        "semantic_avg": round(sum(semantic_scores) / len(semantic_scores), 2)
        if semantic_scores else 0.0,
    }


def passes_gate(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    failures = []
    for key, (mode, limit) in THRESHOLDS.items():
        value = metrics[key]
        ok = value >= limit if mode == "min" else value <= limit
        if not ok:
            failures.append(f"{key}={value} (기준 {mode} {limit})")
    return not failures, failures


# ── GPU 라이브 경로 (단위 테스트 밖 — V2 evaluate.py 의 _load/_generate 미러) ──

def _load(adapter: str, base_model: str):
    import torch
    from peft import PeftModel
    from torch import nn
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model, torch_dtype=torch.bfloat16, device_map="auto", trust_remote_code=True
    )
    # EXAONE × tf5.x: peft 가 임베딩을 못 찾음 → 수동 노출 (train_plain.py 와 동일 우회)
    try:
        _emb = model.get_input_embeddings()
    except (NotImplementedError, AttributeError):
        _emb = None
    if _emb is None:
        embedding = next(m for m in model.modules() if isinstance(m, nn.Embedding))
        model.get_input_embeddings = lambda: embedding
    if adapter and adapter != "base":
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def _generate(model, tokenizer, system: str, user: str, max_new_tokens: int) -> str:
    import torch

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ids = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    )
    if hasattr(ids, "input_ids"):
        ids = ids["input_ids"]
    ids = ids.to(model.device)
    with torch.no_grad():
        output = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
    return tokenizer.decode(output[0][ids.shape[-1]:], skip_special_tokens=True).strip()


def _judge_scores_live(plan_text: str, parsed_goal: dict) -> dict | None:
    from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
        SEMANTIC_JUDGE_SYSTEM, parse_judge_reply, semantic_judge_user,
    )
    from sft_pipeline.experiments.planner_sft_v3.distill_dataset import _openai_fns

    try:
        plan = contract.parse_plan_output(plan_text)
    except ValueError:
        return None
    _, judge = _openai_fns()
    try:
        return parse_judge_reply(judge(SEMANTIC_JUDGE_SYSTEM, semantic_judge_user(plan, parsed_goal)))
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="planner SFT v3 holdout 승격 평가")
    parser.add_argument("--adapter", required=True, help="어댑터 경로 또는 'base'")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    args = parser.parse_args()

    holdout = [json.loads(line) for line in args.holdout.read_text(encoding="utf-8").splitlines() if line.strip()]
    model, tokenizer = _load(args.adapter, args.base_model)

    outputs = []
    for item in holdout:
        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        raw = _generate(model, tokenizer, contract.SYSTEM_PROMPT, user, args.max_new_tokens)
        try:
            contract.parse_plan_output(raw)
        except ValueError:
            # 운영과 동일한 재시도 1회 (스펙 §7)
            raw = _generate(model, tokenizer, contract.SYSTEM_PROMPT, user, args.max_new_tokens)
        outputs.append({
            "input_id": item["input_id"],
            "parsed_goal": item["parsed_goal"],
            "today": item["today"],
            "raw_text": raw,
            "judge_scores": _judge_scores_live(raw, item["parsed_goal"]),
        })

    metrics = score_outputs(outputs)
    passed, failures = passes_gate(metrics)
    report = {"adapter": args.adapter, "metrics": metrics, "passed": passed, "failures": failures,
              "outputs": outputs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sft-v3] passed={passed} metrics={metrics}")
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
