"""RunPod Serverless 기반 QwenLLM — todo_creation 용.

QwenLLM 을 상속하고 complete_raw 만 RunPod Serverless 호출로 대체한다.
전송(/run→/status 폴링)은 adapters._shared.runpod_client 가 담당한다.
split_tasks · judge_sufficiency 등 모든 비즈니스 메서드는 그대로 동작한다.
"""
from __future__ import annotations

from langsmith import traceable

from adapters._shared.runpod_client import RunPodJobError, run_and_poll
from adapters.todo_creation.qwen_llm import DEFAULT_QWEN_MODEL, QwenLLM
from agents.todo_creation.exceptions import LLMFailedError

_LABEL_MAX_TOKENS = {
    "classify_request": 256,
    "judge_sufficiency": 700,
    "follow_up": 256,
    "goal_tag": 96,
    "out_of_scope_reply": 256,
    "split_tasks": 384,
    "validate_plan": 384,
    "plan": 1400,
}

_LABEL_POLL_TIMEOUT = {
    "classify_request": 45.0,
    "judge_sufficiency": 75.0,
    "follow_up": 45.0,
    "goal_tag": 30.0,
    "out_of_scope_reply": 45.0,
    "split_tasks": 60.0,
    "validate_plan": 45.0,
    "plan": 150.0,
}


def _drop_self(inputs: dict) -> dict:
    return {k: v for k, v in inputs.items() if k != "self"}


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

    @traceable(run_type="llm", name="runpod_llm", process_inputs=_drop_self)
    async def complete_raw(
        self,
        *,
        messages: list[dict[str, str]],
        label: str = "qwen",
        temperature: float | None = None,
        guided_json: dict | None = None,
    ) -> str:
        request_max_tokens = min(
            self.max_tokens, _LABEL_MAX_TOKENS.get(label, self.max_tokens)
        )
        request_poll_timeout = min(
            self._poll_timeout, _LABEL_POLL_TIMEOUT.get(label, self._poll_timeout)
        )
        job_input: dict = {
            "adapter": self._adapter,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": request_max_tokens,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "json_mode": True,
        }
        if guided_json is not None:
            # 워커가 vLLM GuidedDecodingParams 로 변환(외국 문자 차단). 미전달 시 기존 거동.
            job_input["guided_json"] = guided_json
        payload = {"input": job_input}
        try:
            output = await run_and_poll(
                endpoint_url=self._endpoint_url,
                api_key=self.api_key,
                payload=payload,
                label=label,
                poll_interval=self._poll_interval,
                poll_timeout=request_poll_timeout,
            )
        except RunPodJobError as err:
            raise LLMFailedError(str(err)) from err

        text = output.get("text")
        if text is None:
            raise LLMFailedError(
                f"RunPod COMPLETED 응답에 output.text 가 없습니다 [{label}]"
            )
        return str(text)
