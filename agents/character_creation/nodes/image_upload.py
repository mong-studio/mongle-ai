from __future__ import annotations

from uuid import uuid4

from agents.character_creation.protocols import S3Port

_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}


def key_for(user_id: str, content_type: str, *, prefix: str) -> str:
    ext = _EXT_BY_MIME.get(content_type, "bin")
    return f"{prefix}/{user_id}/{uuid4()}.{ext}"


async def put_once(
    s3: S3Port, *, key: str, body: bytes, content_type: str
) -> str:
    return await s3.put_object(key=key, body=body, content_type=content_type)
