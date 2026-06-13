from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from agents.todo_creation.schemas import (
    FollowUpResult,
    MultiGenerateInput,
    SingleTurnResult,
    TodoInput,
    TurnResult,
)
from agents.todo_creation.commit import pipeline as commit_pipeline
from agents.todo_creation.planner import pipeline as multi_pipeline
from agents.todo_creation.planner.pipeline import PlannerPorts
from agents.todo_creation.schemas import CommitResult
from agents.todo_creation.todo import pipeline as single_pipeline
from agents.todo_creation.todo.pipeline import GeneratePorts
from api.config import AppConfig
from api.deps import build_commit_ports, get_config, get_todo_generate_ports, get_todo_planner_ports
from api.envelope import Envelope, done
from api.security import require_api_key
from api.todo_creation.schemas import CommitRequest

router = APIRouter(prefix="/v1/todo", dependencies=[Depends(require_api_key)])


async def _generate(
    body: TodoInput,
    ports: GeneratePorts,
) -> Envelope[SingleTurnResult]:
    result = await single_pipeline.run(body, ports=ports, now=datetime.now())
    return done(result)


async def _chat(
    body: MultiGenerateInput,
    ports: PlannerPorts,
) -> Envelope[TurnResult]:
    result = await multi_pipeline.run(body, ports=ports, now=datetime.now())
    return done(result)


async def _commit(
    body: CommitRequest,
    cfg: AppConfig,
) -> Envelope[CommitResult]:
    ports = build_commit_ports(cfg, remaining_daily_quota=body.remaining_daily_quota)
    result = await commit_pipeline.run(body.input, ports=ports, now=datetime.now())
    return done(result)


@router.post("/generate", response_model=Envelope[SingleTurnResult])
async def generate(
    body: TodoInput,
    ports: GeneratePorts = Depends(get_todo_generate_ports),
) -> Envelope[SingleTurnResult]:
    return await _generate(body, ports)


@router.post("/chat", response_model=Envelope[TurnResult])
async def chat(
    body: MultiGenerateInput,
    ports: PlannerPorts = Depends(get_todo_planner_ports),
) -> Envelope[TurnResult]:
    return await _chat(body, ports)


@router.post("/commit", response_model=Envelope[CommitResult])
async def commit(
    body: CommitRequest,
    cfg: AppConfig = Depends(get_config),
) -> Envelope[CommitResult]:
    return await _commit(body, cfg)
