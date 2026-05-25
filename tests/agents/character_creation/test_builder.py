from __future__ import annotations

from datetime import datetime

from agents.character_creation.nodes.builder import build, builder_node
from agents.character_creation.schemas import (
    CharacterCreationInput,
    LLMPersonaResult,
    VLMResult,
)
from agents.character_creation.state import CharacterGraphState


def _input(**kw) -> CharacterCreationInput:
    return CharacterCreationInput(
        user_id="u1",
        name="몽글이",
        persona="다정한 곰",
        **kw,
    )


def _llm() -> LLMPersonaResult:
    return LLMPersonaResult(
        personality="다정한 성격",
        speech_style="존댓말",
        background="숲에서 옴",
    )


def test_builds_entity_with_all_required_fields() -> None:
    fixed_now = datetime(2026, 5, 22, 9, 0, 0)
    entity = build(
        input=_input(),
        llm_result=_llm(),
        vlm_result=VLMResult(appearance_description="둥근 곰"),
        generated_image_url="https://s3/characters/u1/x.png",
        source_image_url="https://s3/sources/u1/y.png",
        now=fixed_now,
    )
    assert entity.user_id == "u1"
    assert entity.name == "몽글이"
    assert entity.persona == "다정한 곰"
    assert entity.personality == "다정한 성격"
    assert entity.speech_style == "존댓말"
    assert entity.background == "숲에서 옴"
    assert entity.image_url.endswith("x.png")
    assert entity.source_image_url is not None
    assert entity.appearance_description == "둥근 곰"
    assert entity.created_at == fixed_now
    assert entity.character_id is not None


def test_source_url_is_none_for_text_only() -> None:
    entity = build(
        input=_input(),
        llm_result=_llm(),
        vlm_result=None,
        generated_image_url="https://s3/c.png",
        source_image_url=None,
        now=datetime(2026, 5, 22),
    )
    assert entity.source_image_url is None
    assert entity.appearance_description is None


async def test_builder_node_assembles_entity() -> None:
    state = CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
        llm_result=LLMPersonaResult(personality="p", speech_style="s", background="b"),
        generated_url="https://fake-s3.local/characters/u1/x.png",
    )
    out = await builder_node(state, {"configurable": {"ports": object(), "now": None}})
    entity = out.update["entity"]
    assert entity.name == "몽글이"
    assert entity.image_url.endswith("x.png")
    assert entity.source_image_url is None
    assert out.goto == "__end__"


async def test_builder_node_records_error_when_state_invalid() -> None:
    state = CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
    )
    out = await builder_node(state, {"configurable": {"ports": object(), "now": None}})
    assert isinstance(out.update["error"], Exception)
    assert out.goto == "cleanup_source_image"
