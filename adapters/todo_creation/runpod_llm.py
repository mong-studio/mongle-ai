"""RunPod Serverless 기반 QwenLLM — todo_creation 용.

QwenLLM 을 상속하고 complete_raw 만 RunPod Serverless 호출로 대체한다.
전송(/run→/status 폴링)은 adapters._shared.runpod_client 가 담당한다.
split_tasks · judge_sufficiency 등 모든 비즈니스 메서드는 그대로 동작한다.
"""
from __future__ import annotations

from adapters._shared.runpod_client import RunPodJobError, run_and_poll
from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL, QwenLLM
from agents.todo_creation.exceptions import LLMFailedError


class RunPodQwenLLM(QwenLLM):
    """QwenLLM 의 RunPod Serverless 버전 — complete_raw 만 오버라이드."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        adapter: str,
        model: str = DEFAULT_QWEN_MODEL,
        temperature: float = 0.1,
        max_tokens: int = 2400,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            base_url="",
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._endpoint_url = endpoint_url
        self._adapter = adapter
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def complete_raw(
        self, *, messages: list[dict[str, str]], label: str = "qwen"
    ) -> str:
        payload = {
            "input": {
                "adapter": self._adapter,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
        }
        try:
            output = await run_and_poll(
                endpoint_url=self._endpoint_url,
                api_key=self.api_key,
                payload=payload,
                label=label,
                poll_interval=self._poll_interval,
                poll_timeout=self._poll_timeout,
            )
        except RunPodJobError as err:
            raise LLMFailedError(str(err)) from err

        text = output.get("text")
        if text is None:
            raise LLMFailedError(
                f"RunPod COMPLETED 응답에 output.text 가 없습니다 [{label}]"
            )
        return str(text)
