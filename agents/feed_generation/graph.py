from langgraph.graph import END, START, StateGraph
from langgraph.pregel import RetryPolicy

from agents.feed_generation.exceptions import (
    CaptionGenerationError,
    ImageGenerationError,
    S3UploadError,
)
from agents.feed_generation.nodes import (
    assemble_caption_ctx,
    assemble_image_prompt,
    builder,
    img2img,
    llm_caption,
    s3_upload,
    validate,
    validate_caption,
)
from agents.feed_generation.state import FeedGraphState


def build_graph():
    graph = StateGraph(FeedGraphState)

    graph.add_node("validate", validate.validate_node)
    graph.add_node("assemble_image_prompt", assemble_image_prompt.assemble_image_prompt_node)
    graph.add_node(
        "img2img",
        img2img.img2img_node,
        retry=RetryPolicy(max_attempts=3, retry_on=ImageGenerationError),
    )
    graph.add_node(
        "s3_upload",
        s3_upload.s3_upload_node,
        retry=RetryPolicy(max_attempts=3, retry_on=S3UploadError),
    )
    graph.add_node("assemble_caption_ctx", assemble_caption_ctx.assemble_caption_ctx_node)
    graph.add_node(
        "llm_caption",
        llm_caption.llm_caption_node,
        retry=RetryPolicy(max_attempts=3, retry_on=CaptionGenerationError),
    )
    graph.add_node("validate_caption", validate_caption.validate_caption_node)
    graph.add_node("builder", builder.builder_node)

    graph.add_edge(START, "validate")
    graph.add_edge("validate", "assemble_image_prompt")
    graph.add_edge("assemble_image_prompt", "img2img")
    graph.add_edge("img2img", "s3_upload")
    graph.add_edge("s3_upload", "assemble_caption_ctx")
    graph.add_edge("assemble_caption_ctx", "llm_caption")
    graph.add_edge("llm_caption", "validate_caption")
    graph.add_edge("validate_caption", "builder")
    graph.add_edge("builder", END)

    return graph.compile()
