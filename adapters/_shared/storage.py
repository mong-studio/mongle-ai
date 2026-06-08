"""STORAGE 환경변수 토글로 S3Port 구현체를 만드는 팩토리.

- STORAGE=s3    → boto3 client + S3Storage (presigned URL 반환)
- STORAGE=local → LocalStorage (메모리 stub, 개발/테스트용)

AWS 자격증명(AWS_ACCESS_KEY_ID/SECRET)은 boto3 의 기본 자격증명 체인이
환경변수에서 자동으로 읽으므로 여기서 직접 다루지 않는다. region 만 명시한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.s3_storage import S3Storage

if TYPE_CHECKING:
    from agents.character_creation.protocols import S3Port

_PRESIGN_EXPIRES = 3600


def build_storage() -> S3Port:
    """STORAGE 환경변수에 따라 S3Storage 또는 LocalStorage 를 반환한다."""
    backend = os.getenv("STORAGE", "local").strip().lower()
    if backend == "local":
        return LocalStorage(root=Path("."))
    if backend == "s3":
        return _build_s3_storage()
    raise ValueError(f"알 수 없는 STORAGE 값: {backend!r} (s3 또는 local 이어야 함)")


def _build_s3_storage() -> S3Storage:
    bucket = os.getenv("AWS_S3_BUCKET")
    if not bucket:
        raise ValueError("STORAGE=s3 인데 AWS_S3_BUCKET 환경변수가 없습니다")
    region = os.getenv("AWS_REGION")
    prefix = os.getenv("AWS_S3_PREFIX", "")

    import boto3

    # presigned URL 이 글로벌 엔드포인트(s3.amazonaws.com)로 생성되면 S3 가 리전
    # 엔드포인트로 307 리다이렉트 → Host 가 바뀌어 SigV4 서명(SignedHeaders=host)이
    # 깨지고 403 이 난다. 리전 엔드포인트를 명시해 presigned host 를 리전형으로 고정한다.
    endpoint_url = f"https://s3.{region}.amazonaws.com" if region else None
    client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
    return S3Storage(
        client=client,
        bucket=bucket,
        prefix=prefix,
        presign_expires=_PRESIGN_EXPIRES,
    )
