from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from agents.todo_creation.schemas import (
    FollowUpResult,
    GenerateResult,
    MultiGenerateInput,
    SingleTurnInput,
    TurnResult,
)
from agents.todo_creation.commit import pipeline as commit_pipeline
from agents.todo_creation.multi_turn import pipeline as multi_pipeline
from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts
from agents.todo_creation.schemas import CommitResult
from agents.todo_creation.single_turn import pipeline as single_pipeline
from agents.todo_creation.single_turn.pipeline import GeneratePorts
from api.config import AppConfig
from api.deps import build_commit_ports, get_config, get_todo_generate_ports, get_todo_multiturn_ports
from api.envelope import Envelope, done
from api.security import require_api_key
from api.todo_creation.schemas import CommitRequest

router = APIRouter(prefix="/v1/todo", dependencies=[Depends(require_api_key)])


@router.post("/generate", response_model=Envelope[GenerateResult])
async def generate(
    body: SingleTurnInput,
    ports: GeneratePorts = Depends(get_todo_generate_ports),
) -> Envelope[GenerateResult]:
    result = await single_pipeline.run(body, ports=ports, now=datetime.now())
    return done(result)


@router.post("/chat", response_model=Envelope[GenerateResult | FollowUpResult])
async def chat(
    body: MultiGenerateInput,
    ports: MultiTurnPorts = Depends(get_todo_multiturn_ports),
) -> Envelope[TurnResult]:
    result = await multi_pipeline.run(body, ports=ports, now=datetime.now())
    return done(result)


@router.post("/commit", response_model=Envelope[CommitResult])
async def commit(
    body: CommitRequest,
    cfg: AppConfig = Depends(get_config),
) -> Envelope[CommitResult]:
    ports = build_commit_ports(cfg, remaining_daily_quota=body.remaining_daily_quota)
    result = await commit_pipeline.run(body.input, ports=ports, now=datetime.now())
    return done(result)
