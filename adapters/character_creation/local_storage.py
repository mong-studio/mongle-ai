from __future__ import annotations

from pathlib import Path

from agents.character_creation.exceptions import S3UploadFailedError


class LocalStorage:
    """Implements S3Port by writing bytes to a local directory.

    Returns the absolute file path so ``st.image(path)`` can render it directly.
    """

    def __init__(self, *, root: Path, prefix: str = "") -> None:
        self._root = Path(root)
        self._prefix = prefix.strip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        rel = f"{self._prefix}/{key}" if self._prefix else key
        return self._root / rel

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str:
        path = self._full_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        except OSError as err:
            raise S3UploadFailedError(f"Local write failed: {err}") from err
        return str(path)

    async def delete_object(self, *, key: str) -> None:
        path = self._full_path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as err:
            raise S3UploadFailedError(f"Local delete failed: {err}") from err
