from __future__ import annotations

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.nodes.generated_upload import generated_upload_node
from agents.character_creation.schemas import CharacterCreationInput
from agents.character_creation.state import CharacterGraphState
from tests.agents.character_creation.fakes import FakeS3


def _state() -> CharacterGraphState:
    return CharacterGraphState(
        input=CharacterCreationInput(user_id="u1", name="몽글이", persona="다정한 곰"),
        is_regeneration=False,
        image_bytes=b"GENERATED_PNG_BYTES",
    )


def _config(s3: FakeS3) -> dict:
    class _Ports:
        pass
    p = _Ports()
    p.s3 = s3
    return {"configurable": {"ports": p}}


async def test_generated_upload_returns_url() -> None:
    s3 = FakeS3()
    out = await generated_upload_node(_state(), _config(s3))
    assert out.update["generated_url"].startswith("https://fake-s3.local/characters/u1/")
    assert out.goto == "builder"
    assert s3.calls == 1


async def test_generated_upload_retries_then_succeeds_within_attempts() -> None:
    s3 = FakeS3(fail_times=3)
    out = await generated_upload_node(_state(), _config(s3))
    assert out.update["generated_url"].startswith("https://fake-s3.local/characters/u1/")
    assert out.goto == "builder"
    assert s3.calls == 4


async def test_generated_upload_records_error_after_attempts_exhausted() -> None:
    s3 = FakeS3(fail_times=99)
    out = await generated_upload_node(_state(), _config(s3))
    assert isinstance(out.update["error"], S3UploadFailedError)
    assert "generated_url" not in out.update
    assert out.goto == "cleanup_source_image"
    assert s3.calls == 4
