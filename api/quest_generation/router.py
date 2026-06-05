from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.quest_generation import pipeline as quest_pipeline
from agents.quest_generation.pipeline import Ports as QuestPorts
from agents.quest_generation.schemas import (
    QuestDistributionResult,
    QuestGenerationInput,
)
from api.deps import get_quest_ports
from api.envelope import Envelope, done
from api.security import require_api_key

router = APIRouter(prefix="/v1/quest", dependencies=[Depends(require_api_key)])


@router.post("/generate", response_model=Envelope[QuestDistributionResult])
async def generate(
    body: QuestGenerationInput,
    ports: QuestPorts = Depends(get_quest_ports),
) -> Envelope[QuestDistributionResult]:
    result = await quest_pipeline.run(body, ports=ports)
    return done(result)
