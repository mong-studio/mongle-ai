from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.feed_generation import pipeline as feed_pipeline
from agents.feed_generation.pipeline import Ports as FeedPorts
from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed
from api.deps import get_feed_ports
from api.envelope import Envelope, done
from api.security import require_api_key

router = APIRouter(prefix="/v1/feed", dependencies=[Depends(require_api_key)])


@router.post("/generate", response_model=Envelope[GeneratedFeed])
async def generate(
    body: FeedGenerationInput,
    ports: FeedPorts = Depends(get_feed_ports),
) -> Envelope[GeneratedFeed]:
    result = await feed_pipeline.run(body, ports=ports)
    return done(result)
