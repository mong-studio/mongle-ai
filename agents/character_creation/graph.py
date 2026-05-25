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
from agents.character_creation.state import CharacterGraphState

# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_graph():
    g = StateGraph(CharacterGraphState)

    # ---- nodes ----
    # validate fans out via Command(goto=[...]) — image-and-text path goes to
    # [llm_persona, source_upload]; text-only goes to [llm_persona, vlm_analyzer]
    # (vlm short-circuits to None when there is no source image).
    g.add_node(
        "validate",
        validate_node,
        destinations=("llm_persona", "source_upload", "vlm_analyzer"),
    )
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
    # image_generator/generated_upload/builder return Command for either the
    # success path or cleanup_source_image (compensation on error).
    g.add_node(
        "image_generator",
        image_generator_node,
        destinations=("generated_upload", "cleanup_source_image"),
    )
    g.add_node(
        "generated_upload",
        generated_upload_node,
        destinations=("builder", "cleanup_source_image"),
    )
    g.add_node(
        "builder",
        builder_node,
        destinations=("cleanup_source_image", END),
    )
    g.add_node("cleanup_source_image", cleanup_source_image_node)

    # ---- edges ----
    g.add_edge(START, "validate")

    # source_upload → vlm_analyzer → image_generator (image-and-text path).
    g.add_edge("source_upload", "vlm_analyzer")
    g.add_edge("vlm_analyzer", "image_generator")

    # llm_persona always feeds into image_generator (fan-in with vlm branch).
    g.add_edge("llm_persona", "image_generator")

    g.add_edge("cleanup_source_image", END)

    return g.compile()
