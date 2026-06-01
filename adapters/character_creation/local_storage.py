from __future__ import annotations

import base64
from pathlib import Path

from agents.character_creation.exceptions import S3UploadFailedError


class LocalStorage:
    """Implements S3Port using in-memory storage.

    파일을 디스크에 저장하지 않고 메모리에만 보관한다.
    image_url은 data URI로 반환하므로 st.image()에서 바로 렌더링 가능.
    """

    def __init__(self, *, root: Path, prefix: str = "") -> None:
        self._store: dict[str, tuple[bytes, str]] = {}  # key → (body, content_type)

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str:
        self._store[key] = (body, content_type)
        b64 = base64.b64encode(body).decode()
        return f"data:{content_type};base64,{b64}"

    async def delete_object(self, *, key: str) -> None:
        self._store.pop(key, None)
