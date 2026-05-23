from __future__ import annotations

from agents.character_creation.nodes.vlm_analyzer import vlm_analyzer_node
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeVLM


def _state() -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1",
            name="몽글이",
            persona="다정한 곰",
            source_image=SourceImage(filename="a.png", content_type="image/png", data=b"\x89PNG"),
        ),
        is_regeneration=False,
    )


def _config(vlm: FakeVLM) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.vlm = vlm
    return {"configurable": {"ports": p}}


async def test_vlm_analyzer_returns_result_on_success() -> None:
    vlm = FakeVLM()
    out = await vlm_analyzer_node(_state(), _config(vlm))
    assert out["vlm_result"] is not None
    assert vlm.calls == 1


async def test_vlm_analyzer_returns_none_after_three_failures() -> None:
    vlm = FakeVLM(fail_times=3)
    out = await vlm_analyzer_node(_state(), _config(vlm))
    assert out["vlm_result"] is None
    assert vlm.calls == 3


async def test_vlm_analyzer_succeeds_on_second_attempt() -> None:
    vlm = FakeVLM(fail_times=1)
    out = await vlm_analyzer_node(_state(), _config(vlm))
    assert out["vlm_result"] is not None
    assert vlm.calls == 2


async def test_vlm_analyzer_returns_none_without_calling_vlm_when_no_source_image() -> None:
    vlm = FakeVLM()
    state = CharacterGraphState(
        input=CharacterCreationInput(
            user_id="u1", name="몽글이", persona="다정한 곰", source_image=None
        ),
        is_regeneration=False,
    )
    out = await vlm_analyzer_node(state, _config(vlm))
    assert out == {"vlm_result": None}
    assert vlm.calls == 0
