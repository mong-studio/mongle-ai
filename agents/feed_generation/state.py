from __future__ import annotations
from typing import TypedDict
from agents.feed_generation.schemas import FeedGenerationInput, FeedPrompt, GeneratedFeed


class FeedGraphState(TypedDict):
    input: FeedGenerationInput
    feed_prompt: FeedPrompt | None   # gen_feed_prompt 산출(character/scene)
    raw_image: bytes | None          # 워커 feed 모드 완성 PNG
    image_url: str | None
    caption_prompt: str | None       # gen_caption_prompt 산출
    raw_caption: str | None
    result: GeneratedFeed | None
