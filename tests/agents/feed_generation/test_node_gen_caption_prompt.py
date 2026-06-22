import pytest
from agents.feed_generation.nodes.gen_caption_prompt import gen_caption_prompt_node
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import make_state

pytestmark = pytest.mark.asyncio


async def test_builds_caption_prompt_with_persona_and_quest():
    state = make_state(feed_prompt=FeedPrompt(character="x", scene="bedroom"))
    cmd = await gen_caption_prompt_node(state, {})
    p = cmd.update["caption_prompt"]
    assert "몽글이" in p and "방 청소하기" in p
    assert cmd.goto == "llm_caption"
