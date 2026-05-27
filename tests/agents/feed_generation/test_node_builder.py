from langgraph.constants import END
from agents.feed_generation.nodes.builder import builder_node
from agents.feed_generation.schemas import GeneratedFeed
from tests.agents.feed_generation.fakes import make_state


async def test_builder_node_constructs_generated_feed():
    state = make_state(
        image_url="https://s3.example.com/feeds/out.png",
        raw_caption="오늘 청소 완료 ✨",
    )
    cmd = await builder_node(state, {})

    assert cmd.goto == END
    feed: GeneratedFeed = cmd.update["result"]
    assert feed.character_id == state["input"].character.character_id
    assert feed.quest_id == state["input"].quest.quest_id
    assert feed.image_url == "https://s3.example.com/feeds/out.png"
    assert feed.caption == "오늘 청소 완료 ✨"


async def test_builder_node_result_is_generated_feed_instance():
    state = make_state(
        image_url="https://s3.example.com/feeds/out.png",
        raw_caption="청소 최고 ✨",
    )
    cmd = await builder_node(state, {})
    assert isinstance(cmd.update["result"], GeneratedFeed)
