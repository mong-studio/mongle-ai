from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.quest_generation import pipeline as quest_pipeline
from agents.quest_generation.pipeline import Ports as QuestPorts
from agents.quest_generation.schemas import (
    QuestDistributionResult,
)
from api.deps import get_quest_ports
from api.envelope import Envelope, done
from api.quest_generation.schemas import QuestGenerationRequest
from api.security import require_api_key

router = APIRouter(prefix="/v1/quest", dependencies=[Depends(require_api_key)])


async def _generate(
    body: QuestGenerationRequest,
    ports: QuestPorts,
) -> Envelope[QuestDistributionResult]:
    result = await quest_pipeline.run(body.to_agent_input(), ports=ports)
    return done(result)


@router.post("/generate", response_model=Envelope[QuestDistributionResult])
async def generate(
    body: QuestGenerationRequest,
    ports: QuestPorts = Depends(get_quest_ports),
) -> Envelope[QuestDistributionResult]:
    return await _generate(body, ports)
