"""RunPod Serverless 핸들러 — 멀티-어댑터 이미지 생성.

입력:  {"input": {"adapter": "character|bg",
                  "source_image_b64": "<base64|null>",   # character 모드
                  "prompt": "<씬 묘사 텍스트>"}}            # bg 모드
출력:  {"image_b64": "<base64 PNG>"}
실패:  예외 전파 → RunPod 이 job 을 FAILED 로 마킹 (호출측 어댑터가 처리)
"""
from __future__ import annotations

import base64

import runpod

from pipeline import get_pipeline


def handler(job: dict) -> dict:
    job_input = job.get("input") or {}

    adapter = job_input.get("adapter")
    if not adapter or not isinstance(adapter, str):
        raise ValueError("[ERROR] 'adapter' 필드가 필요합니다 (character|bg)")

    source_b64 = job_input.get("source_image_b64")
    source_bytes = base64.b64decode(source_b64, validate=True) if source_b64 else None
    prompt = job_input.get("prompt")

    png_bytes = get_pipeline().generate(
        adapter=adapter,
        source_image_bytes=source_bytes,
        prompt=prompt,
    )
    return {"image_b64": base64.b64encode(png_bytes).decode()}


runpod.serverless.start({"handler": handler})
