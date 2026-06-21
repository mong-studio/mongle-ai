"""Qwen2.5-Instruct adapter for feed_generation caption generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL
from agents.feed_generation.exceptions import CaptionGenerationError


@dataclass
class QwenLLM:
    model: str = DEFAULT_QWEN_MODEL
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    temperature: float = 0.75  # 캡션 창작 다양성
    max_tokens: int = 300
    timeout_seconds: float = 30.0

    async def generate(self, prompt: str) -> str:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
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
            content = data["choices"][0]["message"]["content"]
            if not content:
                raise CaptionGenerationError("Qwen 응답에 content가 없습니다")
            return str(content).strip()
        except CaptionGenerationError:
            raise
        except Exception as exc:
            raise CaptionGenerationError(str(exc)) from exc
