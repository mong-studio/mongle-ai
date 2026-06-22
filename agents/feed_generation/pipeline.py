from langgraph.graph import END, START, StateGraph
from langgraph.pregel import RetryPolicy

from agents.feed_generation.exceptions import (
    CaptionGenerationError,
    FeedGenerationError,
    ImageGenerationError,
    PromptGenerationError,
    S3UploadError,
)
from agents.feed_generation.nodes import (
    builder,
    feed_image,
    gen_caption_prompt,
    gen_feed_prompt,
    llm_caption,
    s3_upload,
)
from agents.feed_generation.protocols import Ports
from agents.feed_generation.schemas import FeedGenerationInput, GeneratedFeed
from agents.feed_generation.state import FeedGraphState


def build_graph():
    graph = StateGraph(FeedGraphState)

    graph.add_node(
        "gen_feed_prompt",
        gen_feed_prompt.gen_feed_prompt_node,
        retry=RetryPolicy(max_attempts=3, retry_on=PromptGenerationError),
    )
    graph.add_node(
        "feed_image",
        feed_image.feed_image_node,
        retry=RetryPolicy(max_attempts=3, retry_on=ImageGenerationError),
    )
    graph.add_node(
        "s3_upload",
        s3_upload.s3_upload_node,
        retry=RetryPolicy(max_attempts=3, retry_on=S3UploadError),
    )
    graph.add_node("gen_caption_prompt", gen_caption_prompt.gen_caption_prompt_node)
    graph.add_node(
        "llm_caption",
        llm_caption.llm_caption_node,
        retry=RetryPolicy(max_attempts=3, retry_on=CaptionGenerationError),
    )
    graph.add_node("builder", builder.builder_node)

    graph.add_edge(START, "gen_feed_prompt")
    graph.add_edge("gen_feed_prompt", "feed_image")
    graph.add_edge("feed_image", "s3_upload")
    graph.add_edge("s3_upload", "gen_caption_prompt")
    graph.add_edge("gen_caption_prompt", "llm_caption")
    graph.add_edge("llm_caption", "builder")
    graph.add_edge("builder", END)

    return graph.compile()


_graph = build_graph()


async def run(feed_input: FeedGenerationInput, *, ports: Ports) -> GeneratedFeed:
    initial_state = {
        "input": feed_input,
        "feed_prompt": None,
        "raw_image": None,
        "image_url": None,
        "caption_prompt": None,
        "raw_caption": None,
        "result": None,
    }
    config = {"configurable": {"ports": ports}}
    final_state = await _graph.ainvoke(initial_state, config=config)
    result = final_state.get("result")
    if result is None:
        raise FeedGenerationError("Pipeline completed without producing a result")
    return result
