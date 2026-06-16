"""RunPod Serverless 기반 QwenLLM — quest_generation 용.

QwenLLM 을 상속하고 _complete_raw 만 RunPod /run → /status 폴링으로 대체한다.
generate_quest 메서드는 그대로 동작한다.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from adapters.quest_generation.qwen_llm import QwenLLM
from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL
from agents.quest_generation.exceptions import LLMFailedError

_HTTP_TIMEOUT = 30.0
_MAX_CONSECUTIVE_POLL_ERRORS = 3
_TERMINAL_STATUSES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})


class RunPodQwenLLM(QwenLLM):
    """quest_generation QwenLLM 의 RunPod Serverless 버전."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        adapter: str,
        model: str = DEFAULT_QWEN_MODEL,
        temperature: float = 0.1,
        max_tokens: int = 300,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._endpoint_url = endpoint_url.rstrip("/")
        self._adapter = adapter
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def _complete_raw(self, *, messages: list[dict[str, str]]) -> str:
        payload = {
            "input": {
                "adapter": self._adapter,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                run_resp = await client.post(
                    f"{self._endpoint_url}/run", json=payload, headers=headers
                )
                run_resp.raise_for_status()
                job_id = run_resp.json()["id"]
            except httpx.HTTPError as err:
                raise LLMFailedError(
                    f"RunPod job submit failed [quest]: {err}"
                ) from err

            deadline = time.monotonic() + self._poll_timeout
            poll_errors = 0
            while True:
                try:
                    status_resp = await client.get(
                        f"{self._endpoint_url}/status/{job_id}",
                        headers=headers,
                        timeout=_HTTP_TIMEOUT,
                    )
                    status_resp.raise_for_status()
                except httpx.HTTPError:
                    poll_errors += 1
                    if poll_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                        raise LLMFailedError(
                            "RunPod poll failed repeatedly [quest]"
                        )
                    await asyncio.sleep(self._poll_interval)
                    continue

                poll_errors = 0
                data = status_resp.json()
                status = data.get("status")

                if status == "COMPLETED":
                    text = (data.get("output") or {}).get("text")
                    if text is None:
                        raise LLMFailedError(
                            "RunPod COMPLETED 응답에 output.text 가 없습니다 [quest]"
                        )
                    return str(text)

                if status in _TERMINAL_STATUSES:
                    detail = str(data.get("error") or "")[:200]
                    raise LLMFailedError(
                        f"RunPod job {status} [quest]: {detail}"
                    )

                if time.monotonic() >= deadline:
                    raise LLMFailedError(
                        f"RunPod job timed out [quest] ({self._poll_timeout}s)"
                    )
                await asyncio.sleep(self._poll_interval)
