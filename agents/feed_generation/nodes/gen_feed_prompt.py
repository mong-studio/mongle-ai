from typing import Any, Literal
from langgraph.types import Command
from agents.feed_generation.exceptions import PromptGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedPrompt, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["feed_image"]

_SYSTEM = (
    "You convert a Korean quest into two English lines for a pixel-art image.\n"
    "Output EXACTLY two lines:\n"
    "action: <6-12 word verb-starting phrase, the character performing the quest>\n"
    "scene: <short background scene description, no characters>\n"
    "Quest: {quest}"
)


def _parse(text: str) -> tuple[str, str]:
    action = scene = ""
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("action:"):
            action = line.split(":", 1)[1].strip()
        elif low.startswith("scene:"):
            scene = line.split(":", 1)[1].strip()
    action = action or scene
    scene = scene or action
    return action, scene


def _character_prompt(character: CharacterRef, action: str) -> str:
    visual = ", ".join(k for k in character.visual if k.strip())
    return f"{visual}, {action}" if visual else action


async def gen_feed_prompt_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    ports: Ports = config["configurable"]["ports"]
    quest: QuestRef = state["input"].quest
    try:
        raw = await ports.llm.generate(_SYSTEM.format(quest=quest.quest))
    except Exception as exc:
        raise PromptGenerationError(str(exc)) from exc
    action, scene = _parse(raw)
    if not action:
        raise PromptGenerationError("LLM이 action/scene을 반환하지 않음")
    feed_prompt = FeedPrompt(
        character=_character_prompt(state["input"].character, action),
        scene=scene,
    )
    return Command(update={"feed_prompt": feed_prompt}, goto="feed_image")
