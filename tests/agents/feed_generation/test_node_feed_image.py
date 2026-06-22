import pytest
from agents.feed_generation.nodes.feed_image import feed_image_node
from agents.feed_generation.exceptions import ImageGenerationError
from agents.feed_generation.schemas import FeedPrompt
from tests.agents.feed_generation.fakes import (
    make_state, make_ports, FakeImageGenerator, FailingImageGenerator)

pytestmark = pytest.mark.asyncio


async def test_calls_generate_feed_with_prompts_and_ref():
    gen = FakeImageGenerator()
    state = make_state(feed_prompt=FeedPrompt(character="분홍, cleaning", scene="bedroom"))
    cmd = await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=gen)}})
    ref, char, scene = gen.feed_calls[0]
    assert ref == state["input"].character.image_url
    assert char == "분홍, cleaning" and scene == "bedroom"
    assert cmd.update["raw_image"] == gen.image_bytes
    assert cmd.goto == "s3_upload"


async def test_generator_failure_propagates():
    state = make_state(feed_prompt=FeedPrompt(character="x", scene="y"))
    with pytest.raises(ImageGenerationError):
        await feed_image_node(state, {"configurable": {"ports": make_ports(image_generator=FailingImageGenerator())}})
