"""TranslatorPort 구현체 — RunPod Qwen base(LoRA 없음)로 KR→EN 외형 번역.

이미지 워커(SDXL/CLIP)는 영어만 이해하므로 한국어 appearance 를 영어 visual
태그로 바꾼다. base 어댑터(no-LoRA)는 planner 엔드포인트에서 서빙된다.
"""
from __future__ import annotations

from adapters._shared.runpod_client import RunPodJobError, run_and_poll
from adapters.character_creation._prompts import load as load_prompt
from agents.character_creation.exceptions import LLMFailedError

_SYSTEM_PROMPT = load_prompt("translate_appearance_v1")
_TEMPERATURE = 0.2
_MAX_TOKENS = 120


class RunPodTranslator:
    def __init__(self, *, endpoint_url: str, api_key: str) -> None:
        self._endpoint_url = endpoint_url
        self._api_key = api_key

    async def translate_appearance(self, korean: str) -> str:
        payload = {
            "input": {
                "adapter": "base",
                "temperature": _TEMPERATURE,
                "max_tokens": _MAX_TOKENS,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": korean},
                ],
            }
        }
        try:
            output = await run_and_poll(
                endpoint_url=self._endpoint_url,
                api_key=self._api_key,
                payload=payload,
                label="translate_appearance",
            )
        except RunPodJobError as err:
            raise LLMFailedError(f"appearance 번역 실패: {err}") from err
        return str(output.get("text") or "").strip()
