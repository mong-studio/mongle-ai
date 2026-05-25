from __future__ import annotations


class LLMFailedError(Exception):
    """Raised when LLM call (or its structured-output parse) fails."""
