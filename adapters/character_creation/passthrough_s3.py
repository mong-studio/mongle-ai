from __future__ import annotations

from dataclasses import dataclass

from agents.character_creation.protocols import S3Port

_SOURCE_PREFIX = "sources"


@dataclass
class PassthroughSourceS3:
    """S3Port 구현. 소스 이미지는 웹이 이미 S3 에 업로드했으므로(spec §6),
    'sources/' prefix 키는 재업로드하지 않고 알려진 source_url 을 그대로 반환한다.
    그 외 키(생성 이미지 'characters/')는 inner 실제 S3 어댑터에 위임한다.
    """

    inner: S3Port
    source_url: str

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str:
        if key.split("/", 1)[0] == _SOURCE_PREFIX:
            return self.source_url
        return await self.inner.put_object(key=key, body=body, content_type=content_type)

    async def delete_object(self, *, key: str) -> None:
        if key.split("/", 1)[0] == _SOURCE_PREFIX:
            return None
        await self.inner.delete_object(key=key)
