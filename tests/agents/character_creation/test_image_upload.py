from __future__ import annotations

import pytest

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.nodes.image_upload import key_for, put_once
from tests.agents.character_creation.fakes import FakeS3


def test_key_for_appends_correct_extension() -> None:
    key = key_for("u1", "image/png", prefix="sources")
    assert key.startswith("sources/u1/")
    assert key.endswith(".png")


def test_key_for_jpeg_maps_to_jpg() -> None:
    assert key_for("u1", "image/jpeg", prefix="sources").endswith(".jpg")


async def test_put_once_returns_url() -> None:
    s3 = FakeS3()
    url = await put_once(s3, key="sources/u1/abc.png", body=b"x", content_type="image/png")
    assert url.startswith("https://fake-s3.local/")


async def test_put_once_raises_on_failure_without_retry() -> None:
    s3 = FakeS3(fail_times=1)
    with pytest.raises(S3UploadFailedError):
        await put_once(s3, key="sources/u1/abc.png", body=b"x", content_type="image/png")
    assert s3.calls == 1
