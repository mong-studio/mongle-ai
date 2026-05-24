from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.character_creation.debug import log_end, log_start, log_step
from agents.character_creation.graph import build_graph
from agents.character_creation.protocols import (
    CharacterRepositoryPort,
    ImageGeneratorPort,
    LLMPort,
    S3Port,
    VLMPort,
)
from agents.character_creation.schemas import CharacterCreationInput, CharacterEntity
from agents.character_creation.state import CharacterGraphState


@dataclass
class Ports:
    llm: LLMPort
    vlm: VLMPort
    s3: S3Port
    image_generator: ImageGeneratorPort
    repository: CharacterRepositoryPort


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
