from __future__ import annotations

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.s3_storage import S3Storage


class FeedS3Adapter:
    """S3Storage/LocalStorage의 put_object 인터페이스를 feed S3Port(upload)로 변환."""

    def __init__(self, storage: S3Storage | LocalStorage) -> None:
        self._storage = storage

    async def upload(self, key: str, data: bytes) -> str:
        return await self._storage.put_object(
            key=key, body=data, content_type="image/png"
        )
