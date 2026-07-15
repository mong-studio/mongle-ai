from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    """LANGSMITH_TRACING 플래그가 켜져 있고 API 키가 있으면 True."""
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower() in _TRUTHY
    has_key = bool(os.environ.get("LANGSMITH_API_KEY", "").strip())
    return flag and has_key


def init_langsmith() -> bool:
    """LangSmith 트레이싱을 켠다. 멱등, 키/플래그 없으면 no-op.

    langsmith SDK 와 langchain 은 LANGSMITH_* 환경변수를 직접 읽으므로
    여기서는 기본 endpoint/project 만 채워주고 활성 여부를 반환한다.
    """
    if not langsmith_enabled():
        return False
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    os.environ.setdefault("LANGSMITH_PROJECT", "mongle-planner")
    return True
