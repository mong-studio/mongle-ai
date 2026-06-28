from __future__ import annotations

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.nodes.image_generator import image_generator_node
from agents.character_creation.schemas import (
    CharacterCreationInput,
    LLMPersonaResult,
)
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeImageGenerator, FakeRepository


def _state() -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        llm_result=LLMPersonaResult(personality="p", speech_style="s", background="b", appearance="a"),
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
    assert out.update["image_bytes"] == b"GENERATED_PNG_BYTES"
    assert out.update["appearance_payload"]["character_type"] == "bear"
    assert isinstance(out.update["image_generator_seconds"], float)
    assert out.goto == "generated_upload"
    assert img.calls == 1


async def test_image_generator_retries_then_succeeds_within_attempts() -> None:
    img = FakeImageGenerator(fail_times=1)
    out = await image_generator_node(_state(), _config(img, FakeRepository()))
    assert out.update["image_bytes"] == b"GENERATED_PNG_BYTES"
    assert isinstance(out.update["image_generator_seconds"], float)
    assert out.goto == "generated_upload"
    assert img.calls == 2


async def test_image_generator_records_error_after_attempts_exhausted() -> None:
    img = FakeImageGenerator(fail_times=99)
    out = await image_generator_node(_state(), _config(img, FakeRepository()))
    assert isinstance(out.update["error"], ImageGenerationFailedError)
    assert "image_bytes" not in out.update
    assert out.goto == "cleanup_source_image"
    assert img.calls == 2


async def test_image_generator_passes_fallback_persona() -> None:
    img = FakeImageGenerator()
    await image_generator_node(_state(), _config(img, FakeRepository()))
    assert img.last_inputs["fallback_persona"] == "다정한 곰"


async def test_image_generator_increments_counter() -> None:
    repo = FakeRepository()
    await image_generator_node(_state(), _config(FakeImageGenerator(), repo))
    assert repo.increments == 1
