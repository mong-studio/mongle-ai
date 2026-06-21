from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.reply_generation import pipeline as reply_pipeline
from agents.reply_generation.protocols import Ports as ReplyPorts
from agents.reply_generation.schemas import GeneratedReply, ReplyGenerationInput
from api.deps import get_reply_ports
from api.envelope import Envelope, done
from api.security import require_api_key

router = APIRouter(prefix="/v1/reply", dependencies=[Depends(require_api_key)])


@router.post("/generate", response_model=Envelope[GeneratedReply])
async def generate(
    body: ReplyGenerationInput,
    ports: ReplyPorts = Depends(get_reply_ports),
) -> Envelope[GeneratedReply]:
    result = await reply_pipeline.run(body, ports=ports)
    return done(result)
