from __future__ import annotations

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from agents.character_creation.exceptions import S3UploadFailedError


class S3Storage:
    """Implements S3Port using boto3. Returns a presigned GET URL after upload."""

    def __init__(
        self,
        *,
        client: Any,
        bucket: str,
        prefix: str,
        presign_expires: int = 3600,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._expires = presign_expires

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    async def put_object(self, *, key: str, body: bytes, content_type: str) -> str:
        full_key = self._full_key(key)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=full_key,
                Body=body,
                ContentType=content_type,
            )
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": full_key},
                ExpiresIn=self._expires,
            )
        except (BotoCoreError, ClientError) as err:
            raise S3UploadFailedError(f"S3 put_object failed: {err}") from err

    async def delete_object(self, *, key: str) -> None:
        full_key = self._full_key(key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=full_key)
        except (BotoCoreError, ClientError) as err:
            raise S3UploadFailedError(f"S3 delete_object failed: {err}") from err
