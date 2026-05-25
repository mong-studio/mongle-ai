from __future__ import annotations

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.nodes.image_generator import image_generator_node
from agents.character_creation.schemas import (
    CharacterCreationInput,
    LLMPersonaResult,
    VLMResult,
)
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeImageGenerator, FakeRepository


def _state(*, with_vlm: bool = False) -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
        llm_result=LLMPersonaResult(personality="p", speech_style="s", background="b"),
        vlm_result=VLMResult(appearance_description="둥근 갈색 곰") if with_vlm else None,
    )


def _config(img: FakeImageGenerator, repo: FakeRepository) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.image_generator = img
    p.repository = repo
    return {"configurable": {"ports": p}}


async def test_image_generator_returns_bytes_on_success() -> None:
    img = FakeImageGenerator()
    out = await image_generator_node(_state(), _config(img, FakeRepository()))
    assert out.update == {"image_bytes": b"GENERATED_PNG_BYTES"}
    assert out.goto == "generated_upload"
    assert img.calls == 1


async def test_image_generator_retries_then_succeeds_within_attempts() -> None:
    img = FakeImageGenerator(fail_times=1)
    out = await image_generator_node(_state(), _config(img, FakeRepository()))
    assert out.update == {"image_bytes": b"GENERATED_PNG_BYTES"}
    assert out.goto == "generated_upload"
    assert img.calls == 2


async def test_image_generator_records_error_after_attempts_exhausted() -> None:
    img = FakeImageGenerator(fail_times=99)
    out = await image_generator_node(_state(), _config(img, FakeRepository()))
    assert isinstance(out.update["error"], ImageGenerationFailedError)
    assert "image_bytes" not in out.update
    assert out.goto == "cleanup_source_image"
    assert img.calls == 2


async def test_image_generator_passes_vlm_result_when_present() -> None:
    img = FakeImageGenerator()
    await image_generator_node(_state(with_vlm=True), _config(img, FakeRepository()))
    assert img.last_inputs["vlm_result"] is not None
    assert img.last_inputs["fallback_persona"] is None


async def test_image_generator_sets_fallback_persona_when_no_vlm() -> None:
    img = FakeImageGenerator()
    await image_generator_node(_state(with_vlm=False), _config(img, FakeRepository()))
    assert img.last_inputs["vlm_result"] is None
    assert img.last_inputs["fallback_persona"] == "다정한 곰"


async def test_image_generator_increments_counter() -> None:
    repo = FakeRepository()
    await image_generator_node(_state(), _config(FakeImageGenerator(), repo))
    assert repo.increments == 1
