from agents.feed_generation.graph import build_graph
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed

_graph = build_graph()


async def run(feed_input: FeedGenerationInput, *, ports: Ports) -> GeneratedFeed:
    initial_state = {
        "input": feed_input,
        "image_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_ctx": None,
        "raw_caption": None,
        "result": None,
    }
    config = {"configurable": {"ports": ports}}

    final_state = initial_state
    async for event in _graph.astream(initial_state, config=config, stream_mode="values"):
        final_state = event

    return final_state["result"]
