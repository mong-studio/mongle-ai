"""base vs v3 LoRA A/B 노트북 생성기.

생성 후 GPU pod 에서 실행·출력 임베드(승격 관문, 스펙 §7):
  uv run python -m sft_pipeline.experiments.planner_sft_v3.build_ab_notebook
  jupyter nbconvert --to notebook --execute --inplace \
    sft_pipeline/experiments/planner_sft_v3/ab_test.ipynb
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_OUT = Path("sft_pipeline/experiments/planner_sft_v3/ab_test.ipynb")


def _code(source: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": source.splitlines(keepends=True)}


def _md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


_CELLS = [
    _md("# Planner SFT v3 — base vs LoRA A/B\n같은 holdout 30건을 두 모델로 생성·채점한다. "
        "**출력이 박힌 이 노트북의 커밋이 승격 관문이다** (스펙 §7)."),
    _code("""import sys, json
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))  # 저장소 루트에서 실행

from sft_pipeline.experiments.planner_sft_v3 import contract
from sft_pipeline.experiments.planner_sft_v3.evaluate import (
    BASE_MODEL, _generate, _judge_scores_live, _load, passes_gate, score_outputs,
)

ADAPTER = "outputs/planner-sft-v3-run1/adapter"  # 평가 대상 어댑터
HOLDOUT = Path("sft_pipeline/experiments/planner_sft_v3/data/holdout.jsonl")
holdout = [json.loads(l) for l in HOLDOUT.read_text(encoding="utf-8").splitlines() if l.strip()]
print(f"holdout {len(holdout)}건")"""),
    _code("""def run(adapter_name):
    model, tok = _load(adapter_name, BASE_MODEL)
    outs = []
    for item in holdout:
        user = contract.build_user(item["parsed_goal"], date.fromisoformat(item["today"]))
        raw = _generate(model, tok, contract.SYSTEM_PROMPT, user, 1200)
        outs.append({"input_id": item["input_id"], "parsed_goal": item["parsed_goal"],
                     "today": item["today"], "raw_text": raw,
                     "judge_scores": _judge_scores_live(raw, item["parsed_goal"])})
    del model
    import torch; torch.cuda.empty_cache()
    return outs

base_outputs = run("base")
lora_outputs = run(ADAPTER)"""),
    _code("""base_metrics = score_outputs(base_outputs)
lora_metrics = score_outputs(lora_outputs)
print("base:", json.dumps(base_metrics, ensure_ascii=False, indent=2))
print("lora:", json.dumps(lora_metrics, ensure_ascii=False, indent=2))"""),
    _code("""lora_passed, failures = passes_gate(lora_metrics)
semantic_win = lora_metrics["semantic_avg"] >= base_metrics["semantic_avg"]
promote = lora_passed and semantic_win
print(f"게이트 통과: {lora_passed} (미달: {failures})")
print(f"의미 평균 LoRA {lora_metrics['semantic_avg']} vs base {base_metrics['semantic_avg']}"
      f" -> {'우위' if semantic_win else '열세'}")
print(f"\\n최종 판정: {'승격 자격' if promote else '기각 — 수치와 함께 기록'}")"""),
    _code("""# 케이스별 나란히 비교 (처음 5건)
for b, l in list(zip(base_outputs, lora_outputs))[:5]:
    print("=" * 60)
    print("목표:", b["parsed_goal"]["goal_text"])
    print("[base]", b["raw_text"][:300])
    print("[lora]", l["raw_text"][:300])"""),
]


def build_notebook(out: Path = _DEFAULT_OUT) -> None:
    nb = {"cells": _CELLS, "metadata": {"language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sft-v3] wrote {out}")


if __name__ == "__main__":
    build_notebook()
