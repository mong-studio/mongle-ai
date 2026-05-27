from typing import Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["img2img"]


def _build_image_prompt(character: CharacterRef, quest: QuestRef) -> str:
    keywords = ", ".join(character.appearance_keywords)
    return (
        f"{keywords}, performing task: {quest.quest_text}, "
        "anime style, detailed illustration, vibrant colors"
    )


async def assemble_image_prompt_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build_image_prompt(state["input"].character, state["input"].quest)
    return Command(update={"image_prompt": prompt}, goto="img2img")
