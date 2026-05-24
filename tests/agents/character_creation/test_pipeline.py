from __future__ import annotations

import pytest

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
    LLMFailedError,
    ValidationFailedError,
)
from agents.character_creation.pipeline import Ports, run
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from tests.agents.character_creation.fakes import (
    FakeImageGenerator,
    FakeLLM,
    FakeRepository,
    FakeS3,
    FakeVLM,
)


def _ports(
    *,
    repo: FakeRepository | None = None,
    llm: FakeLLM | None = None,
    vlm: FakeVLM | None = None,
    s3: FakeS3 | None = None,
    img: FakeImageGenerator | None = None,
) -> Ports:
    return Ports(
        llm=llm or FakeLLM(),
        vlm=vlm or FakeVLM(),
        s3=s3 or FakeS3(),
        image_generator=img or FakeImageGenerator(),
        repository=repo or FakeRepository(),
    )


def _input(with_image: bool = False, *, bad_mime: bool = False) -> CharacterCreationInput:
    if with_image:
        src = SourceImage(
            filename="a.png",
            content_type="application/pdf" if bad_mime else "image/png",
            data=b"\x89PNG",
        )
    else:
        src = None
    return CharacterCreationInput(
        user_id="u1",
        name="몽글이",
        persona="다정한 곰",
        source_image=src,
    )


async def test_text_only_pipeline_returns_entity_without_source_url() -> None:
    ports = _ports()
    entity = await run(_input(), ports=ports)
    assert entity.source_image_url is None
    assert entity.image_url.startswith("https://fake-s3.local/characters/u1/")
    assert ports.vlm.calls == 0  # type: ignore[attr-defined]


async def test_image_plus_text_pipeline_uploads_source_and_invokes_vlm() -> None:
    ports = _ports()
    entity = await run(_input(with_image=True), ports=ports)
    assert entity.source_image_url is not None
    assert entity.source_image_url.startswith("https://fake-s3.local/sources/u1/")
    assert ports.vlm.calls == 1  # type: ignore[attr-defined]
    assert ports.image_generator.last_inputs["vlm_result"] is not None  # type: ignore[attr-defined]


async def test_vlm_failure_degrades_but_completes() -> None:
    ports = _ports(vlm=FakeVLM(fail_times=3))
    entity = await run(_input(with_image=True), ports=ports)
    assert entity is not None
    assert ports.image_generator.last_inputs["vlm_result"] is None  # type: ignore[attr-defined]


async def test_validation_failure_does_not_call_external_services() -> None:
    ports = _ports()
    with pytest.raises(ValidationFailedError):
        await run(_input(with_image=True, bad_mime=True), ports=ports)
    assert ports.llm.calls == 0  # type: ignore[attr-defined]
    assert ports.image_generator.calls == 0  # type: ignore[attr-defined]


async def test_llm_failure_propagates_after_retries() -> None:
    ports = _ports(llm=FakeLLM(fail_times=3))
    with pytest.raises(LLMFailedError):
        await run(_input(), ports=ports)


async def test_image_generator_failure_cleans_up_source_upload() -> None:
    s3 = FakeS3()
    repo = FakeRepository()
    ports = _ports(s3=s3, repo=repo, img=FakeImageGenerator(fail_times=2))
    with pytest.raises(ImageGenerationFailedError):
        await run(_input(with_image=True), ports=ports)
    assert len(s3.deleted_keys) >= 1
    assert any(k.startswith("sources/u1/") for k in s3.deleted_keys)
