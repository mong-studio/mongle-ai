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
from agents.character_creation.router import decide
from agents.character_creation.state import CharacterGraphState

# ---------------------------------------------------------------------------
# Compensation routing helpers
# ---------------------------------------------------------------------------

def _ok_or_cleanup(next_ok: str):
    """Return a conditional-edges router: go to next_ok on success, else cleanup."""
    def _route(state: CharacterGraphState) -> str:
        return "cleanup_source_image" if state.error is not None else next_ok
    return _route


def _ok_or_cleanup_end(state: CharacterGraphState) -> str:
    return "cleanup_source_image" if state.error is not None else END


# ---------------------------------------------------------------------------
# No-op node for the text-only path so image_generator always has two resolved
# predecessors regardless of which branch was taken.
# ---------------------------------------------------------------------------

async def _vlm_skip_node(state: CharacterGraphState, config: object) -> dict:
    """Placeholder that satisfies the vlm_analyzer → image_generator fan-in
    when no source image is provided. Returns an empty update."""
    return {}


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
    g.add_node("vlm_skip", _vlm_skip_node)
    g.add_node("image_generator", image_generator_node)
    g.add_node("generated_upload", generated_upload_node)
    g.add_node("builder", builder_node)
    g.add_node("cleanup_source_image", cleanup_source_image_node)

    # ---- edges ----
    g.add_edge(START, "validate")

    # validate fans out based on whether a source image was provided
    g.add_conditional_edges("validate", decide)

    # image-and-text path: source_upload → vlm_analyzer → image_generator
    g.add_edge("source_upload", "vlm_analyzer")
    g.add_edge("vlm_analyzer", "image_generator")

    # text-only path: vlm_skip → image_generator (dummy to satisfy fan-in)
    g.add_edge("vlm_skip", "image_generator")

    # llm_persona always feeds into image_generator (fan-in with vlm branch)
    g.add_edge("llm_persona", "image_generator")

    # downstream pipeline with compensation routing on error
    g.add_conditional_edges("image_generator", _ok_or_cleanup("generated_upload"))
    g.add_conditional_edges("generated_upload", _ok_or_cleanup("builder"))
    g.add_conditional_edges("builder", _ok_or_cleanup_end)
    g.add_edge("cleanup_source_image", END)

    return g.compile()
