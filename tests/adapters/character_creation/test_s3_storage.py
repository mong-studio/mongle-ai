from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from adapters.character_creation.s3_storage import S3Storage
from agents.character_creation.exceptions import S3UploadFailedError


def _make_client(presigned_url: str = "https://signed.example.com/x") -> MagicMock:
    client = MagicMock()
    client.put_object.return_value = {}
    client.generate_presigned_url.return_value = presigned_url
    return client


@pytest.mark.asyncio
async def test_put_object_uploads_with_prefix() -> None:
    client = _make_client()
    storage = S3Storage(
        client=client, bucket="my-bucket", prefix="mongle-village", presign_expires=3600
    )
    url = await storage.put_object(
        key="characters/u1/abc.png", body=b"\x89PNG", content_type="image/png"
    )

    client.put_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="mongle-village/characters/u1/abc.png",
        Body=b"\x89PNG",
        ContentType="image/png",
    )
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "my-bucket", "Key": "mongle-village/characters/u1/abc.png"},
        ExpiresIn=3600,
    )
    assert url == "https://signed.example.com/x"


@pytest.mark.asyncio
async def test_put_object_without_prefix() -> None:
    client = _make_client()
    storage = S3Storage(client=client, bucket="b", prefix="", presign_expires=600)
    await storage.put_object(key="sources/u1/x.png", body=b"data", content_type="image/png")
    client.put_object.assert_called_once_with(
        Bucket="b", Key="sources/u1/x.png", Body=b"data", ContentType="image/png"
    )


@pytest.mark.asyncio
async def test_put_object_wraps_client_error() -> None:
    client = MagicMock()
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "PutObject"
    )
    storage = S3Storage(client=client, bucket="b", prefix="p", presign_expires=10)

    with pytest.raises(S3UploadFailedError):
        await storage.put_object(key="x", body=b"", content_type="image/png")


@pytest.mark.asyncio
async def test_delete_object_uses_prefixed_key() -> None:
    client = MagicMock()
    storage = S3Storage(
        client=client, bucket="my-bucket", prefix="mongle-village", presign_expires=3600
    )
    await storage.delete_object(key="sources/u1/abc.png")
    client.delete_object.assert_called_once_with(
        Bucket="my-bucket", Key="mongle-village/sources/u1/abc.png"
    )


@pytest.mark.asyncio
async def test_delete_object_wraps_client_error() -> None:
    client = MagicMock()
    client.delete_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "DeleteObject"
    )
    storage = S3Storage(client=client, bucket="b", prefix="p", presign_expires=10)
    with pytest.raises(S3UploadFailedError):
        await storage.delete_object(key="sources/u/x.png")
