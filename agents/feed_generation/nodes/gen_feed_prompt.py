from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.exceptions import PromptGenerationError
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import CharacterRef, FeedPrompt, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["feed_image"]

_SYSTEM = (
    "You convert a Korean quest into two English lines for a pixel-art image.\n"
    "Output EXACTLY two lines, nothing else:\n"
    "action: <6-12 word verb-starting phrase, the character performing the quest>\n"
    "scene: <short background scene description, no characters>\n\n"
    "Example —\n"
    "Quest: 방 청소하기\n"
    "action: tidying up a messy bedroom with a broom\n"
    "scene: cozy sunlit bedroom interior\n\n"
    "Quest: {quest}"
)


def _extract(text: str, marker: str) -> str:
    """줄 어디서든 marker(예: 'action:') 뒤 텍스트를 뽑는다(번호·마크다운 허용)."""
    for line in text.splitlines():
        idx = line.lower().find(marker)
        if idx != -1:
            return line[idx + len(marker):].strip().strip("*").strip('"').strip()
    return ""


def _parse(text: str) -> tuple[str, str]:
    action = _extract(text, "action:")
    scene = _extract(text, "scene:")
    # 한쪽만 있으면 다른 쪽으로 채운다(reference run.py 동작).
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
        # LLM 호출 자체 실패(네트워크 등) — 재시도 대상
        raise PromptGenerationError(str(exc)) from exc

    action, scene = _parse(raw)
    # 캡션 파인튜닝 모델이 action/scene 형식을 안 지킬 수 있다. 하드페일하지 않고
    # 원문 quest 로 폴백한다(피드는 생성되고 포즈/장면 품질만 저하).
    if not action:
        action = scene = quest.quest

    feed_prompt = FeedPrompt(
        character=_character_prompt(state["input"].character, action),
        scene=scene,
    )
    return Command(update={"feed_prompt": feed_prompt}, goto="feed_image")
