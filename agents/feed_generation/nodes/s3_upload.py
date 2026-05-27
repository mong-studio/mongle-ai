from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import S3UploadError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.state import FeedGraphState

_Target = Literal["assemble_caption_ctx"]


async def s3_upload_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    character_id = state["input"].character.character_id
    quest_id = state["input"].quest.quest_id
    key = f"feeds/{character_id}/{quest_id}.png"
    try:
        image_url = await ports.s3.upload(key, state["raw_image"])
    except S3UploadError:
        raise
    except Exception as exc:
        raise S3UploadError(str(exc)) from exc
    return Command(update={"image_url": image_url}, goto="assemble_caption_ctx")
