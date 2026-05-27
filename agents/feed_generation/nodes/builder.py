from typing import Literal

from langgraph.constants import END
from langgraph.types import Command

from agents.feed_generation.schemas import GeneratedFeed
from agents.feed_generation.state import FeedGraphState

_Target = Literal["__end__"]


async def builder_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    result = GeneratedFeed(
        character_id=state["input"].character.character_id,
        quest_id=state["input"].quest.quest_id,
        image_url=state["image_url"],
        caption=state["raw_caption"],
    )
    return Command(update={"result": result}, goto=END)
