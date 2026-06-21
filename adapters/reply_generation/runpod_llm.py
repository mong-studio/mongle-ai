"""RunPod Serverless 기반 QwenLLM — reply_generation 용.

QwenLLM 을 상속하고 _complete_raw 만 RunPod Serverless 호출로 대체한다.
generate 메서드는 그대로 동작한다.
"""
from __future__ import annotations

from adapters._shared.runpod_client import RunPodJobError, run_and_poll
from adapters.reply_generation.qwen_llm import QwenLLM
from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL
from agents.reply_generation.exceptions import ReplyLLMError


class RunPodQwenLLM(QwenLLM):
    """reply_generation QwenLLM 의 RunPod Serverless 버전."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        adapter: str,
        model: str = DEFAULT_QWEN_MODEL,
        temperature: float = 0.85,
        max_tokens: int = 120,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._endpoint_url = endpoint_url
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
        try:
            output = await run_and_poll(
                endpoint_url=self._endpoint_url,
                api_key=self.api_key,
                payload=payload,
                label="reply",
                poll_interval=self._poll_interval,
                poll_timeout=self._poll_timeout,
            )
        except RunPodJobError as err:
            raise ReplyLLMError(str(err)) from err

        text = output.get("text")
        if text is None:
            raise ReplyLLMError(
                "RunPod COMPLETED 응답에 output.text 가 없습니다 [reply]"
            )
        return str(text)
