from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agents.quest_generation import pipeline as quest_pipeline
from agents.quest_generation.pipeline import Ports as QuestPorts
from agents.quest_generation.schemas import QuestDistributionResult
from api.deps import get_quest_ports
from api.envelope import Envelope, ErrorBody, done
from api.quest_generation.schemas import QuestGenerationRequest, QuestJobRef
from api.security import require_api_key
from api.todo_creation.jobs import JobState, TodoJobStore

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/quest", dependencies=[Depends(require_api_key)])

_JOB_KIND = "quest_generate"


def get_job_store(request: Request) -> TodoJobStore:
    """앱 전역 인메모리 잡 스토어. lifespan 이 우회된 테스트에선 지연 생성."""
    store = getattr(request.app.state, "quest_jobs", None)
    if store is None:
        store = TodoJobStore()
        request.app.state.quest_jobs = store
    return store


def _poll(store: TodoJobStore, job_id: str) -> Envelope:
    """잡 상태를 폴링한다. done→result, error→error envelope, 진행 중→pending."""
    job = store.get(job_id)
    if job is None or job.kind != _JOB_KIND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="잡을 찾을 수 없습니다"
        )
    if job.state is JobState.DONE:
        return done(job.result)
    if job.state is JobState.ERROR:
        return Envelope(
            status="error",
            error=ErrorBody(
                code=job.error_code or "quest_job_failed",
                message=job.error_message or "",
            ),
        )
    return Envelope(status="pending", result=None)


async def _run_generate(
    *,
    store: TodoJobStore,
    job_id: str,
    body: QuestGenerationRequest,
    ports: QuestPorts,
) -> None:
    try:
        result = await quest_pipeline.run(body.to_agent_input(), ports=ports)
        store.mark_done(job_id, result)
    except Exception as err:  # noqa: BLE001 - 잡 실패는 폴링으로 전달한다
        log.exception("quest generate job failed: job_id=%s", job_id)
        store.mark_error(job_id, code="quest_generate_failed", message=str(err))


# 퀘스트 분배 (submit) — Pod 100s 프록시를 넘기므로 비동기 잡으로 분리.
@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[QuestJobRef],
)
async def generate(
    body: QuestGenerationRequest,
    ports: QuestPorts = Depends(get_quest_ports),
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[QuestJobRef]:
    job_id = store.create(_JOB_KIND)
    task = asyncio.create_task(
        _run_generate(store=store, job_id=job_id, body=body, ports=ports)
    )
    store.track_task(task)
    return Envelope(status="pending", result=QuestJobRef(job_id=job_id))


# 퀘스트 분배 (poll)
@router.get("/generate/{job_id}", response_model=Envelope[QuestDistributionResult])
async def get_generate_job(
    job_id: str,
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[QuestDistributionResult]:
    return _poll(store, job_id)
