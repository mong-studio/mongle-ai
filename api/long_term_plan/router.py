"""장기 계획(long-term plan) API.

큰 목표 하나를 받아 일자별 plan 으로 분해한다. 내부적으로는 기존 todo planner
파이프라인(planner LoRA)을 그대로 재사용하며, 응답에 일자별 `plan` 을 노출한다.

planner LLM 은 RunPod Pod 100s 프록시를 넘기므로 todo /chat 과 동일하게
submit(202)+poll(GET) 비동기 잡으로 운영한다. 잡 스토어는 todo 와 공유한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from agents.todo_creation.planner import pipeline as planner_pipeline
from agents.todo_creation.planner.pipeline import PlannerPorts
from agents.todo_creation.schemas import PlannerInput, PlannerResult
from api.deps import get_todo_planner_ports
from api.envelope import Envelope, ErrorBody, done
from api.long_term_plan.schemas import LongTermPlanRequest
from api.security import require_api_key
from api.todo_creation.jobs import JobState, TodoJobStore
from api.todo_creation.router import get_job_store
from api.todo_creation.schemas import TodoJobRef

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/plan", dependencies=[Depends(require_api_key)])

_KIND = "plan"


async def _run(
    *, store: TodoJobStore, job_id: str, body: PlannerInput, ports: PlannerPorts
) -> None:
    try:
        result = await planner_pipeline.run(body, ports=ports, now=datetime.now())
        store.mark_done(job_id, result)
    except Exception as err:  # noqa: BLE001 - 잡 실패는 폴링으로 전달한다
        log.exception("long-term plan job failed: job_id=%s", job_id)
        store.mark_error(job_id, code="long_term_plan_failed", message=str(err))


# 장기 계획 생성 (submit)
@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[TodoJobRef],
)
async def generate(
    body: LongTermPlanRequest,
    ports: PlannerPorts = Depends(get_todo_planner_ports),
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[TodoJobRef]:
    job_id = store.create(_KIND)
    task = asyncio.create_task(
        _run(store=store, job_id=job_id, body=body.to_planner_input(), ports=ports)
    )
    store.track_task(task)
    return Envelope(status="pending", result=TodoJobRef(job_id=job_id))


# 장기 계획 생성 (poll)
@router.get("/generate/{job_id}", response_model=Envelope[PlannerResult])
async def get_job(
    job_id: str,
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[PlannerResult]:
    job = store.get(job_id)
    if job is None or job.kind != _KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="잡을 찾을 수 없습니다"
        )
    if job.state is JobState.DONE:
        return done(job.result)
    if job.state is JobState.ERROR:
        return Envelope(
            status="error",
            error=ErrorBody(
                code=job.error_code or "long_term_plan_failed",
                message=job.error_message or "",
            ),
        )
    return Envelope(status="pending", result=None)
