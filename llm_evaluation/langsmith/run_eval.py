"""라이브 RunPod planner 를 데이터셋으로 평가하고 LangSmith 실험으로 올린다.

전제:
  - .env 에 LANGSMITH_TRACING/LANGSMITH_API_KEY + RunPod(RUNPOD_*) 키가 있어야 함.
실행:
  uv run python -m llm_evaluation.langsmith.run_eval
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

from langsmith import Client
from langsmith.evaluation import aevaluate

from agents._shared.observability import init_langsmith
from agents.todo_creation.planner.pipeline import run
from agents.todo_creation.schemas import PlannerInput
from api.config import AppConfig
from api.deps import build_todo_planner_ports
from llm_evaluation.langsmith.dataset import ensure_dataset
from llm_evaluation.langsmith.evaluators import (
    HEURISTIC_EVALUATORS,
    make_judge_evaluators,
    make_plan_quality_evaluator,
)

_DATASET = "mongle-planner-eval"

_CFG = AppConfig.from_env()
_PORTS = build_todo_planner_ports(_CFG)


async def _target(inputs: dict) -> dict:
    """멀티턴 turns 를 같은 thread_id 로 재생하고 마지막 결과를 반환."""
    today = date.fromisoformat(inputs["today"])
    now = datetime.combine(today, datetime.min.time())
    thread_id: str | None = None
    result = None
    for msg in inputs["turns"]:
        pi = PlannerInput(
            user_id=inputs["user_id"],
            message=msg,
            today=today,
            thread_id=thread_id,
            user_profile_memory=inputs.get("user_profile_memory"),
        )
        result = await run(pi, ports=_PORTS, now=now)
        thread_id = result.thread_id
    return {"kind": result.kind, "result": result.model_dump(mode="json")}


async def main() -> None:
    if not init_langsmith():
        raise SystemExit("LANGSMITH_TRACING/LANGSMITH_API_KEY 가 .env 에 필요합니다.")
    client = Client()
    ensure_dataset(client, _DATASET)
    judge = _PORTS.classifier or _PORTS.llm
    evaluators = [
        *HEURISTIC_EVALUATORS,
        *make_judge_evaluators(judge),
        make_plan_quality_evaluator(judge),
    ]
    results = await aevaluate(
        _target,
        data=_DATASET,
        evaluators=evaluators,
        experiment_prefix="planner",
        max_concurrency=2,  # ponytail: RunPod 동시성 보수적. 처리량 필요하면 올릴 것.
    )
    print(f"실험 완료: {results}")


if __name__ == "__main__":
    asyncio.run(main())
