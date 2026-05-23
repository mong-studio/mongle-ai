from __future__ import annotations

import pytest

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.nodes.cleanup import cleanup_source_image_node
from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeS3


def _state(*, source_key: str | None, error: Exception) -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
        source_key=source_key,
        error=error,
    )


def _config(s3: FakeS3) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.s3 = s3
    return {"configurable": {"ports": p}}


async def test_cleanup_deletes_source_key_then_raises() -> None:
    s3 = FakeS3()
    err = ImageGenerationFailedError("boom")
    with pytest.raises(ImageGenerationFailedError):
        await cleanup_source_image_node(
            _state(source_key="sources/u1/abc.png", error=err),
            _config(s3),
        )
    assert s3.deleted_keys == ["sources/u1/abc.png"]


async def test_cleanup_without_source_key_still_raises() -> None:
    s3 = FakeS3()
    err = ImageGenerationFailedError("boom")
    with pytest.raises(ImageGenerationFailedError):
        await cleanup_source_image_node(
            _state(source_key=None, error=err),
            _config(s3),
        )
    assert s3.deleted_keys == []
