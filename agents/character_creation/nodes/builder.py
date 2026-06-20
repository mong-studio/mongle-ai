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
)
from agents.character_creation.state import CharacterGraphState

_Target = Literal["__end__", "cleanup_source_image"]


def build(
    *,
    input: CharacterCreationInput,
    llm_result: LLMPersonaResult,
    generated_image_url: str,
    source_image_url: str | None,
    now: datetime,
    timings: dict[str, float] | None = None,
) -> CharacterEntity:
    return CharacterEntity(
        character_id=uuid4(),
        user_id=input.user_id,
        name=input.name,
        persona=input.persona,
        personality=llm_result.personality,
        speech_style=llm_result.speech_style,
        background=llm_result.background,
        appearance=llm_result.appearance_en or llm_result.appearance,
        image_url=generated_image_url,
        source_image_url=source_image_url,
        created_at=now,
        timings=timings or {},
    )


def _collect_timings(state: CharacterGraphState) -> dict[str, float]:
    """각 노드가 state 에 남긴 단계별 소요시간을 entity.timings 형태로 모은다."""
    timings: dict[str, float] = {}
    keys = (
        ("source_upload", "source_upload_seconds"),
        ("llm_persona", "llm_persona_seconds"),
        ("image_generator", "image_generator_seconds"),
        ("generated_upload", "generated_upload_seconds"),
    )
    for label, state_key in keys:
        if (v := state.get(state_key)) is not None:
            timings[label] = v
    return timings


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
            generated_image_url=generated_url,
            source_image_url=state.get("source_url"),
            now=now,
            timings=_collect_timings(state),
        )
    except Exception as err:
        return Command(update={"error": err}, goto="cleanup_source_image")
    return Command(update={"entity": entity}, goto=END)
