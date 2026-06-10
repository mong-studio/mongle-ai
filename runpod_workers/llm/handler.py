"""RunPod Serverless 핸들러 — Qwen2.5 + LoRA LLM 추론.

입력:  {"input": {"messages": [...], "temperature": 0.1, "max_tokens": 800}}
출력:  {"text": "<생성된 텍스트>"}
실패:  예외 전파 → RunPod 이 job 을 FAILED 로 마킹
"""
from __future__ import annotations

import runpod

from pipeline import get_pipeline


def handler(job: dict) -> dict:
    job_input = job.get("input") or {}
    messages = job_input.get("messages")
    if not messages or not isinstance(messages, list):
        raise ValueError("'messages' 필드가 필요합니다 (list of chat messages)")

    temperature = float(job_input.get("temperature", 0.1))
    max_tokens = int(job_input.get("max_tokens", 800))

    text = get_pipeline().generate(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return {"text": text}


runpod.serverless.start({"handler": handler})
