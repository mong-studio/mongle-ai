from typing import Literal

from langgraph.types import Command

from agents.feed_generation.schemas import CharacterRef, FeedPrompt, QuestRef
from agents.feed_generation.state import FeedGraphState

_Target = Literal["llm_caption"]


def _build(character: CharacterRef, quest: QuestRef, feed_prompt: FeedPrompt) -> str:
    # 캡션이 이미지 내용과 어긋나지 않도록 캐릭터 모습(외형+동작)과 배경을 모두 전달(C6).
    return (
        f"당신은 '{character.name}'이라는 캐릭터입니다.\n"
        f"성격: {character.personality}\n"
        f"말투: {character.speech_style}\n\n"
        f"방금 완료한 퀘스트: {quest.quest}\n"
        f"이미지 속 모습: {feed_prompt.character}\n"
        f"이미지 배경: {feed_prompt.scene}\n\n"
        "위 퀘스트를 완료하고 느낀 소감을 캐릭터의 말투로 한국어 SNS 캡션으로 써주세요.\n"
        "규칙: 반드시 한국어로만 작성, 140자 이하, 캡션 텍스트만 출력"
    )


async def gen_caption_prompt_node(state: FeedGraphState, config: dict) -> Command[_Target]:
    prompt = _build(
        state["input"].character,
        state["input"].quest,
        state["feed_prompt"],
    )
    return Command(update={"caption_prompt": prompt}, goto="llm_caption")
