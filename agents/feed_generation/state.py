from __future__ import annotations

from typing import TypedDict

from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed


class FeedGraphState(TypedDict):
    input: FeedGenerationInput
    image_prompt: str | None
    raw_image: bytes | None
    image_url: str | None
    caption_ctx: str | None
    raw_caption: str | None
    result: GeneratedFeed | None
