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
    json_schema = job_input.get("json_schema")  # 후보2: 있으면 JSON 구조 강제

    text = get_pipeline().generate(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        json_schema=json_schema,
    )
    return {"text": text}


# __main__ 가드 필수: vLLM 은 CUDA 가 (RunPod fitness check 등으로) 이미 초기화된
# 환경에서 워커를 'spawn' 으로 띄운다. spawn 은 이 모듈을 자식 프로세스에서 다시
# import 하는데, 가드가 없으면 자식이 runpod.serverless.start() 를 재실행해
# 또 다른 서버리스 워커로 부팅 → vLLM 엔진코어가 못 떠 부모가 영원히 대기(hang).
# (증상: 모델 로딩 중 "Starting Serverless Worker" 가 두 번 찍히고 정지, completed=0)
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
