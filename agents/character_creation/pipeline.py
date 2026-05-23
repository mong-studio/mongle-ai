from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agents.character_creation.graph import build_graph
from agents.character_creation.protocols import (
    CharacterRepositoryPort,
    ImageGeneratorPort,
    LLMPort,
    RegenerationCounterPort,
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
    counter: RegenerationCounterPort
    repository: CharacterRepositoryPort


_GRAPH = build_graph()


async def run(
    input: CharacterCreationInput,
    *,
    ports: Ports,
    is_regeneration: bool,
    now: datetime | None = None,
) -> CharacterEntity:
    initial = CharacterGraphState(input=input, is_regeneration=is_regeneration)
    final = await _GRAPH.ainvoke(
        initial, config={"configurable": {"ports": ports, "now": now}}
    )
    entity = final["entity"] if isinstance(final, dict) else final.entity
    assert entity is not None
    return entity
