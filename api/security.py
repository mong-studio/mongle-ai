from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """X-API-Key 헤더를 환경변수 MONGLE_API_KEY와 상수시간 비교한다.

    - 서버에 키가 설정되지 않았으면 500 (구성 오류).
    - 헤더 누락/불일치는 401.
    """
    expected = os.environ.get("MONGLE_API_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MONGLE_API_KEY 가 서버에 설정되지 않았습니다",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 API 키",
        )
