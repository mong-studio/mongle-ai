from typing import Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import InputValidationError
from agents.feed_generation.state import FeedGraphState

_Target = Literal["assemble_image_prompt"]


async def validate_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    if not state["input"].character.image_url.strip():
        raise InputValidationError(
            code="empty_image_url",
            message="character.image_url must not be blank",
        )
    return Command(goto="assemble_image_prompt")
