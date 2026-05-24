from __future__ import annotations

import pytest

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
    LLMFailedError,
)
from agents.character_creation.graph import build_graph
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import (
    FakeImageGenerator,
    FakeLLM,
    FakeRepository,
    FakeS3,
    FakeVLM,
)


class _Ports:
    def __init__(self, **kw) -> None:
        self.llm = kw.get("llm") or FakeLLM()
        self.vlm = kw.get("vlm") or FakeVLM()
        self.s3 = kw.get("s3") or FakeS3()
        self.image_generator = kw.get("image_generator") or FakeImageGenerator()
        self.repository = kw.get("repository") or FakeRepository()


def _state(*, with_image: bool = False) -> CharacterGraphState:
    src = (
        SourceImage(filename="a.png", content_type="image/png", data=b"\x89PNG")
        if with_image
        else None
    )
    return CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1", name="몽글이", persona="다정한 곰", source_image=src
        ),
    )


def _final_entity(final):
    return final["entity"] if isinstance(final, dict) else final.entity


def _final_source_image_url(final):
    e = _final_entity(final)
    return e.source_image_url


async def test_graph_text_only_path_produces_entity() -> None:
    graph = build_graph()
    ports = _Ports()
    final = await graph.ainvoke(
        _state(),
        config={"configurable": {"ports": ports, "now": None}},
    )
    assert _final_entity(final) is not None
    assert ports.vlm.calls == 0


async def test_graph_image_path_invokes_vlm_and_source_upload() -> None:
    graph = build_graph()
    ports = _Ports()
    final = await graph.ainvoke(
        _state(with_image=True),
        config={"configurable": {"ports": ports, "now": None}},
    )
    assert _final_source_image_url(final) is not None
    assert ports.vlm.calls == 1


async def test_graph_llm_retry_policy_eventually_raises() -> None:
    graph = build_graph()
    ports = _Ports(llm=FakeLLM(fail_times=99))
    with pytest.raises(LLMFailedError):
        await graph.ainvoke(
            _state(), config={"configurable": {"ports": ports, "now": None}}
        )


async def test_graph_llm_retry_policy_succeeds_within_attempts() -> None:
    graph = build_graph()
    ports = _Ports(llm=FakeLLM(fail_times=2))
    final = await graph.ainvoke(
        _state(), config={"configurable": {"ports": ports, "now": None}}
    )
    assert _final_entity(final) is not None
    assert ports.llm.calls == 3


async def test_graph_image_generator_failure_triggers_source_cleanup() -> None:
    graph = build_graph()
    s3 = FakeS3()
    ports = _Ports(
        s3=s3,
        image_generator=FakeImageGenerator(fail_times=99),
    )
    with pytest.raises(ImageGenerationFailedError):
        await graph.ainvoke(
            _state(with_image=True),
            config={"configurable": {"ports": ports, "now": None}},
        )
    assert any(k.startswith("sources/u1/") for k in s3.deleted_keys)
