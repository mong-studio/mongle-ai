import re
from typing import Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import CaptionValidationError
from agents.feed_generation.state import FeedGraphState

_KOREAN_RE = re.compile(r"[가-힣]")
_Target = Literal["builder"]


def check_caption(caption: str) -> None:
    if len(caption) > 140:
        raise CaptionValidationError(
            code="caption_too_long",
            message=f"캡션이 {len(caption)}자입니다. 최대 140자.",
        )
    if not _KOREAN_RE.search(caption):
        raise CaptionValidationError(
            code="no_korean",
            message="캡션에 한국어가 없습니다.",
        )


async def validate_caption_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    check_caption(state["raw_caption"])
    return Command(goto="builder")
