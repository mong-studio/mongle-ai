from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# langchain 1.2.x removed module-level debug/verbose/llm_cache attributes,
# but langchain_core 0.3.x still tries to read them via _HAS_LANGCHAIN guard.
# Patch them in before any LangGraph/LangChain code runs.
# ---------------------------------------------------------------------------
try:
    import langchain as _lc  # noqa: F401

    for _attr, _default in (("debug", False), ("verbose", False), ("llm_cache", None)):
        if not hasattr(_lc, _attr):
            setattr(_lc, _attr, _default)
except ImportError:
    pass


@pytest.fixture
def sample_user_id() -> str:
    return "user-0001"


@pytest.fixture
def sample_persona_text() -> str:
    return "낮잠을 좋아하지만 사용자에게 다정한 곰돌이."


@pytest.fixture
def sample_keywords() -> list[str]:
    return ["다정한", "온화한"]


@pytest.fixture
def sample_image_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    )
