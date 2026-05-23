from __future__ import annotations

import pytest

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.nodes.source_upload import source_upload_node
from agents.character_creation.schemas import CharacterCreationInput, SourceImage
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeS3


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


def _config(s3: FakeS3) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.s3 = s3
    return {"configurable": {"ports": p}}


async def test_source_upload_returns_url_and_key() -> None:
    s3 = FakeS3()
    out = await source_upload_node(_state(), _config(s3))
    assert out["source_url"].startswith("https://fake-s3.local/sources/u1/")
    assert out["source_key"].startswith("sources/u1/")
    assert s3.calls == 1


async def test_source_upload_raises_for_retry_policy() -> None:
    s3 = FakeS3(fail_times=1)
    with pytest.raises(S3UploadFailedError):
        await source_upload_node(_state(), _config(s3))
    assert s3.calls == 1
