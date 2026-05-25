from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END
from langgraph.types import Command

from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    LLMPersonaResult,
    VLMResult,
)
from agents.character_creation.state import CharacterGraphState

_Target = Literal["__end__", "cleanup_source_image"]


def build(
    *,
    input: CharacterCreationInput,
    llm_result: LLMPersonaResult,
    vlm_result: VLMResult | None,
    generated_image_url: str,
    source_image_url: str | None,
    now: datetime,
) -> CharacterEntity:
    return CharacterEntity(
        character_id=uuid4(),
        user_id=input.user_id,
        name=input.name,
        persona=input.persona,
        personality=llm_result.personality,
        speech_style=llm_result.speech_style,
        background=llm_result.background,
        image_url=generated_image_url,
        source_image_url=source_image_url,
        appearance_description=vlm_result.appearance_description if vlm_result else None,
        created_at=now,
    )


async def builder_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> Command[_Target]:
    now = config["configurable"].get("now") or datetime.now(tz=UTC)
    try:
        llm_result = state.get("llm_result")
        generated_url = state.get("generated_url")
        assert llm_result is not None
        assert generated_url is not None
        entity = build(
            input=state["input"],
            llm_result=llm_result,
            vlm_result=state.get("vlm_result"),
            generated_image_url=generated_url,
            source_image_url=state.get("source_url"),
            now=now,
        )
    except Exception as err:
        return Command(update={"error": err}, goto="cleanup_source_image")
    return Command(update={"entity": entity}, goto=END)
