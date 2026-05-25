from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.character_creation.exceptions import (
    LLMFailedError,
    S3UploadFailedError,
)
from agents.character_creation.nodes.builder import builder_node
from agents.character_creation.nodes.cleanup import cleanup_source_image_node
from agents.character_creation.nodes.generated_upload import generated_upload_node
from agents.character_creation.nodes.image_generator import image_generator_node
from agents.character_creation.nodes.llm_persona import llm_persona_node
from agents.character_creation.nodes.source_upload import source_upload_node
from agents.character_creation.nodes.validate import validate_node
from agents.character_creation.nodes.vlm_analyzer import vlm_analyzer_node
from agents.character_creation.router import decide, ok_or_cleanup
from agents.character_creation.state import CharacterGraphState

# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph():
    g = StateGraph(CharacterGraphState)

    # ---- nodes ----
    g.add_node("validate", validate_node)
    g.add_node(
        "llm_persona",
        llm_persona_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
    )
    g.add_node(
        "source_upload",
        source_upload_node,
        retry=RetryPolicy(max_attempts=4, retry_on=S3UploadFailedError),
    )
    g.add_node("vlm_analyzer", vlm_analyzer_node)
    g.add_node("image_generator", image_generator_node)
    g.add_node("generated_upload", generated_upload_node)
    g.add_node("builder", builder_node)
    g.add_node("cleanup_source_image", cleanup_source_image_node)

    # ---- edges ----
    g.add_edge(START, "validate")

    # validate fans out based on whether a source image was provided.
    # image-and-text: source_upload → vlm_analyzer; text-only: vlm_analyzer 직행.
    g.add_conditional_edges(
        "validate",
        decide,
        ["llm_persona", "source_upload", "vlm_analyzer"],
    )

    # source_upload → vlm_analyzer → image_generator (image-and-text path).
    g.add_edge("source_upload", "vlm_analyzer")
    g.add_edge("vlm_analyzer", "image_generator")

    # llm_persona always feeds into image_generator (fan-in with vlm branch)
    g.add_edge("llm_persona", "image_generator")

    # downstream pipeline with compensation routing on error
    g.add_conditional_edges(
        "image_generator",
        ok_or_cleanup("generated_upload"),
        ["generated_upload", "cleanup_source_image"],
    )
    g.add_conditional_edges(
        "generated_upload",
        ok_or_cleanup("builder"),
        ["builder", "cleanup_source_image"],
    )
    g.add_conditional_edges(
        "builder",
        ok_or_cleanup(END),
        ["cleanup_source_image", END],
    )
    g.add_edge("cleanup_source_image", END)

    return g.compile()
