from __future__ import annotations


class FakeLLM:
    """Small local fallback for feed integration tests."""

    async def generate(self, prompt: str) -> str:
        return "오늘도 작은 일을 해냈어요."
