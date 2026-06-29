from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.appearance import payload_from_visual
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["s3_upload"]


async def feed_image_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    feed_prompt = state["feed_prompt"]
    character = state["input"].character
    # v2 이전 캐릭터는 appearance_payload 가 없다 → visual 에서 결정적으로 합성(피드 가능).
    appearance_payload = character.appearance_payload or payload_from_visual(character.visual)
    try:
        raw_image = await ports.image_generator.generate_feed(
            character.image_url,
            feed_prompt.character,
            feed_prompt.scene,
            appearance_payload,
        )
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(str(exc)) from exc
    return Command(update={"raw_image": raw_image}, goto="s3_upload")
