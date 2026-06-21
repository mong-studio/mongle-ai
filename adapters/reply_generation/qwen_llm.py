"""Qwen2.5-Instruct adapter for reply_generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL
from agents.reply_generation.exceptions import ReplyLLMError


@dataclass
class QwenLLM:
    model: str = DEFAULT_QWEN_MODEL
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    temperature: float = 0.85  # 답글 창작 다양성
    max_tokens: int = 120
    timeout_seconds: float = 30.0

    async def generate(self, prompt: str) -> str:
        content = await self._complete_raw(
            messages=[{"role": "user", "content": prompt}]
        )
        if not content:
            raise ReplyLLMError("Qwen 응답에 content가 없습니다")
        return str(content).strip()

    async def _complete_raw(self, *, messages: list[dict[str, str]]) -> str:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception as exc:
            raise ReplyLLMError(str(exc)) from exc
