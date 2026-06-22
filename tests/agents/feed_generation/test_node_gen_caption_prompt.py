import pytest
from agents.feed_generation.nodes.gen_caption_prompt import gen_caption_prompt_node
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import make_state

pytestmark = pytest.mark.asyncio


async def test_builds_caption_prompt_with_persona_quest_and_image():
    state = make_state(feed_prompt=FeedPrompt(character="분홍, cleaning a room", scene="cozy bedroom"))
    cmd = await gen_caption_prompt_node(state, {})
    p = cmd.update["caption_prompt"]
    assert "몽글이" in p and "방 청소하기" in p
    # 예전 정보량 복원 — 캐릭터 모습(동작)과 배경이 모두 캡션 프롬프트에 포함
    assert "cleaning a room" in p
    assert "cozy bedroom" in p
    assert cmd.goto == "llm_caption"
