from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agents.todo_creation.commit import pipeline as commit_pipeline
from agents.todo_creation.planner import pipeline as multi_pipeline
from agents.todo_creation.planner.pipeline import PlannerPorts
from agents.todo_creation.schemas import (
    CommitResult,
    PlannerInput,
    TodoResult,
    TodoInput,
    PlannerResult,
)
from agents.todo_creation.todo import pipeline as single_pipeline
from agents.todo_creation.todo.pipeline import GeneratePorts
from api.config import AppConfig
from api.deps import (
    build_commit_ports,
    get_config,
    get_todo_generate_ports,
    get_todo_planner_ports,
)
from api.envelope import Envelope, ErrorBody, done
from api.security import require_api_key
from api.todo_creation.jobs import JobState, TodoJobStore
from api.todo_creation.schemas import CommitInput, TodoJobRef

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/todo", dependencies=[Depends(require_api_key)])


def get_job_store(request: Request) -> TodoJobStore:
    """앱 전역 인메모리 잡 스토어. lifespan 이 우회된 테스트에선 지연 생성."""
    store = getattr(request.app.state, "todo_jobs", None)
    if store is None:
        store = TodoJobStore()
        request.app.state.todo_jobs = store
    return store


def _poll(store: TodoJobStore, job_id: str, kind: str) -> Envelope:
    """잡 상태를 폴링한다. done→result, error→error envelope, 진행 중→pending."""
    job = store.get(job_id)
    if job is None or job.kind != kind:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="잡을 찾을 수 없습니다"
        )
    if job.state is JobState.DONE:
        return done(job.result)
    if job.state is JobState.ERROR:
        return Envelope(
            status="error",
            error=ErrorBody(
                code=job.error_code or "todo_job_failed",
                message=job.error_message or "",
            ),
        )
    return Envelope(status="pending", result=None)


async def _run_generate(
    *, store: TodoJobStore, job_id: str, body: TodoInput, ports: GeneratePorts
) -> None:
    try:
        result = await single_pipeline.run(body, ports=ports, now=datetime.now())
        store.mark_done(job_id, result)
    except Exception as err:  # noqa: BLE001 - 잡 실패는 폴링으로 전달한다
        log.exception("todo generate job failed: job_id=%s", job_id)
        store.mark_error(job_id, code="todo_generate_failed", message=str(err))


async def _run_chat(
    *, store: TodoJobStore, job_id: str, body: PlannerInput, ports: PlannerPorts
) -> None:
    try:
        result = await multi_pipeline.run(body, ports=ports, now=datetime.now())
        store.mark_done(job_id, result)
    except Exception as err:  # noqa: BLE001 - 잡 실패는 폴링으로 전달한다
        log.exception("todo chat job failed: job_id=%s", job_id)
        store.mark_error(job_id, code="todo_chat_failed", message=str(err))


# todo 생성 (submit) — planner LLM 이 Pod 100s 프록시를 넘기므로 비동기 잡으로 분리.
@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[TodoJobRef],
)
async def generate(
    body: TodoInput,
    ports: GeneratePorts = Depends(get_todo_generate_ports),
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[TodoJobRef]:
    job_id = store.create("generate")
    task = asyncio.create_task(
        _run_generate(store=store, job_id=job_id, body=body, ports=ports)
    )
    store.track_task(task)
    return Envelope(status="pending", result=TodoJobRef(job_id=job_id))


# todo 생성 (poll)
@router.get("/generate/{job_id}", response_model=Envelope[TodoResult])
async def get_generate_job(
    job_id: str,
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[TodoResult]:
    return _poll(store, job_id, "generate")


# planner (submit)
@router.post(
    "/chat",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[TodoJobRef],
)
async def chat(
    body: PlannerInput,
    ports: PlannerPorts = Depends(get_todo_planner_ports),
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[TodoJobRef]:
    job_id = store.create("chat")
    task = asyncio.create_task(
        _run_chat(store=store, job_id=job_id, body=body, ports=ports)
    )
    store.track_task(task)
    return Envelope(status="pending", result=TodoJobRef(job_id=job_id))


# planner (poll)
@router.get("/chat/{job_id}", response_model=Envelope[PlannerResult])
async def get_chat_job(
    job_id: str,
    store: TodoJobStore = Depends(get_job_store),
) -> Envelope[PlannerResult]:
    return _poll(store, job_id, "chat")


# 계획 확정 — 동기 유지(짧은 경로). quest 분배는 서버측에서 graceful degrade 처리.
@router.post("/commit", response_model=Envelope[CommitResult])
async def commit(
    body: CommitInput,
    cfg: AppConfig = Depends(get_config),
) -> Envelope[CommitResult]:
    ports = build_commit_ports(cfg, remaining_daily_quota=body.remaining_daily_quota)
    result = await commit_pipeline.run(body.input, ports=ports, now=datetime.now())
    return done(result)
