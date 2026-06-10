from __future__ import annotations

import hmac
import hashlib
import logging
import os

from fastapi import Header, HTTPException, Request, status

from api.config import AppConfig

logger = logging.getLogger(__name__)


def _normalize_api_key(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip("\"'")


def _fingerprint(value: str) -> str:
    if not value:
        return "EMPTY"
    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"len={len(value)} sha={digest}"


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    """X-API-Key 헤더를 앱 설정의 API 키와 상수시간 비교한다.

    - 우선순위: app.state.config.api_key -> 환경변수 MONGLE_API_KEY
    - 서버에 키가 설정되지 않았으면 500 (구성 오류).
    - 헤더 누락/불일치는 401.
    """
    cfg = getattr(request.app.state, "config", None)
    expected = _normalize_api_key(cfg.api_key) if isinstance(cfg, AppConfig) else ""
    if not expected:
        expected = _normalize_api_key(os.environ.get("MONGLE_API_KEY"))
    provided = _normalize_api_key(x_api_key)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MONGLE_API_KEY 가 서버에 설정되지 않았습니다",
        )
    if not provided or not hmac.compare_digest(provided, expected):
        if os.environ.get("MONGLE_DEBUG_TODO", "").strip() == "1":
            logger.warning(
                "API key mismatch: provided=%s expected=%s path=%s",
                _fingerprint(provided),
                _fingerprint(expected),
                request.url.path,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 API 키",
        )
