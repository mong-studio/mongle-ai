from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import CaptionGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["validate_caption"]


async def llm_caption_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    try:
        raw_caption = await ports.llm.generate(state["caption_ctx"])
    except CaptionGenerationError:
        raise
    except Exception as exc:
        raise CaptionGenerationError(str(exc)) from exc
    return Command(update={"raw_caption": raw_caption}, goto="validate_caption")
