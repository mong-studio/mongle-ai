from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["s3_upload"]


async def feed_image_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    feed_prompt = state["feed_prompt"]
    try:
        raw_image = await ports.image_generator.generate_feed(
            state["input"].character.image_url,
            feed_prompt.character,
            feed_prompt.scene,
        )
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(str(exc)) from exc
    return Command(update={"raw_image": raw_image}, goto="s3_upload")
