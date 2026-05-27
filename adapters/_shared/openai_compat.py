"""OpenAI 호환 (vLLM/TGI/Ollama/실제 OpenAI) 비동기 클라이언트 빌더.

(base_url, api_key) 별로 AsyncOpenAI 싱글톤을 캐시한다.
import 비용을 ui extras 가 없는 환경에서 피하기 위해 lazy import.
"""

from __future__ import annotations

from typing import Any

_CLIENT_CACHE: dict[tuple[str | None, str | None], Any] = {}


def build_async_client(*, base_url: str | None, api_key: str | None) -> Any:
    key = (base_url, api_key)
    cached = _CLIENT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from openai import AsyncOpenAI
    except ImportError as err:
        raise RuntimeError(
            "openai SDK not installed (install with `pip install mongle-village[ui]`)"
        ) from err
    kwargs: dict[str, Any] = {}
    if base_url is not None:
        kwargs["base_url"] = base_url
    if api_key is not None:
        kwargs["api_key"] = api_key
    client = AsyncOpenAI(**kwargs)
    _CLIENT_CACHE[key] = client
    return client


def reset_cache() -> None:
    """테스트 격리용."""
    _CLIENT_CACHE.clear()
