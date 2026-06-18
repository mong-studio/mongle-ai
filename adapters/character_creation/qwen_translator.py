"""TranslatorPort 구현체 — 로컬 Qwen(OpenAI 호환 서버) 직접 호출 KR→EN 외형 번역.

로컬 개발(LLM_PROVIDER=qwen)용. 운영(runpod)은 RunPodTranslator 를 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from adapters.character_creation._prompts import load as load_prompt
from agents.character_creation.exceptions import LLMFailedError

_SYSTEM_PROMPT = load_prompt("translate_appearance_v1")


@dataclass
class QwenTranslator:
    model: str
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    temperature: float = 0.2
    max_tokens: int = 120
    timeout_seconds: float = 30.0

    async def translate_appearance(self, korean: str) -> str:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": korean},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as err:
            raise LLMFailedError(f"appearance 번역 실패: {err}") from err
        return str(content or "").strip()
