from typing import Any, Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, FeedPrompt, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["feed_image"]


def _character_prompt(character: CharacterRef, quest: QuestRef) -> str:
    visual = ", ".join(k for k in character.visual if k.strip())
    return f"{visual}, {quest.quest}" if visual else quest.quest


async def gen_feed_prompt_node(state: FeedGraphState, config: dict[str, Any]) -> Command[_Target]:
    # quest 를 캐릭터 포즈·배경 장면에 직접 사용(reference run.py 의 --quest-en pass-through).
    # 영문 action/scene 분리는 별도 VLM 몫이라 생략 — 워커 프롬프트 템플릿(monglestyle
    # LoRA + BG_STYLE)이 스타일·배경을 잡는다. LLM 호출이 없어 실패 지점도 없다.
    quest = state["input"].quest
    feed_prompt = FeedPrompt(
        character=_character_prompt(state["input"].character, quest),
        scene=quest.quest,
    )
    return Command(update={"feed_prompt": feed_prompt}, goto="feed_image")
