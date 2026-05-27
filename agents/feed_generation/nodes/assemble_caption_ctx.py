from typing import Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["llm_caption"]


def _build_caption_prompt(character: CharacterRef, quest: QuestRef, image_prompt: str) -> str:
    return (
        f"당신은 '{character.name}'이라는 캐릭터입니다.\n"
        f"성격: {character.personality}\n"
        f"말투: {character.speech_style}\n\n"
        f"방금 완료한 퀘스트: {quest.quest_text}\n"
        f"이미지 분위기: {image_prompt}\n\n"
        "위 퀘스트를 완료하고 느낀 소감을 캐릭터의 말투로 한국어 SNS 캡션으로 써주세요.\n"
        "규칙: 반드시 한국어로만 작성, 140자 이하, 캡션 텍스트만 출력"
    )


async def assemble_caption_ctx_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build_caption_prompt(
        state["input"].character,
        state["input"].quest,
        state["image_prompt"],
    )
    return Command(update={"caption_ctx": prompt}, goto="llm_caption")
