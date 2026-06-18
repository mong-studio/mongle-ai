from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from agents.character_creation.debug import log_end, log_start, log_step
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
from agents.character_creation.nodes.translate_appearance import (
    translate_appearance_node,
)
from agents.character_creation.nodes.validate import validate_node
from agents.character_creation.protocols import (
    CharacterRepositoryPort,
    ImageGeneratorPort,
    LLMPort,
    S3Port,
    TranslatorPort,
)
from agents.character_creation.schemas import CharacterCreationInput, CharacterEntity
from agents.character_creation.state import CharacterGraphState


@dataclass
class Ports:
    llm: LLMPort
    s3: S3Port
    image_generator: ImageGeneratorPort
    repository: CharacterRepositoryPort
    translator: TranslatorPort


async def _sync_node(state: CharacterGraphState, config: dict[str, Any]) -> dict:
    return {}


def build_graph():
    g = StateGraph(CharacterGraphState)

    g.add_node(
        "validate",
        validate_node,
        destinations=("llm_persona", "source_upload"),
    )
    g.add_node(
        "llm_persona",
        llm_persona_node,
        retry=RetryPolicy(max_attempts=3, retry_on=LLMFailedError),
    )
    # 번역 실패는 노드 내부에서 흡수(원본 한국어 유지)하므로 retry 불필요.
    g.add_node("translate_appearance", translate_appearance_node)
    g.add_node(
        "source_upload",
        source_upload_node,
        retry=RetryPolicy(max_attempts=4, retry_on=S3UploadFailedError),
    )
    g.add_node("sync", _sync_node)
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

    g.add_edge(START, "validate")
    g.add_edge("source_upload", "sync")
    g.add_edge("llm_persona", "translate_appearance")
    g.add_edge("translate_appearance", "sync")
    g.add_edge("sync", "image_generator")
    g.add_edge("cleanup_source_image", END)

    return g.compile()


_GRAPH = build_graph()


async def run(
    input: CharacterCreationInput,
    *,
    ports: Ports,
    now: datetime | None = None,
) -> CharacterEntity:
    initial: CharacterGraphState = {"input": input}
    config = {"configurable": {"ports": ports, "now": now}}

    log_start(input)

    final: Any = None
    step = 0
    async for mode, chunk in _GRAPH.astream(
        initial, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "updates":
            for node_name, update in chunk.items():
                step += 1
                log_step(step, node_name, update)
        elif mode == "values":
            final = chunk

    log_end(final)

    assert final is not None
    entity = final["entity"]
    assert entity is not None
    return entity
