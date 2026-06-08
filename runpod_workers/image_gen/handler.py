"""RunPod Serverless 핸들러 — 캐릭터 픽셀아트 이미지 생성.

입력:  {"input": {"source_image_b64": "<base64|null>"}}
출력:  {"image_b64": "<base64 PNG>"}
실패:  예외 전파 → RunPod 이 job 을 FAILED 로 마킹 (호출측 어댑터가 처리)
"""
from __future__ import annotations

import base64

import runpod

from pipeline import get_pipeline


def handler(job: dict) -> dict:
    job_input = job.get("input") or {}
    source_b64 = job_input.get("source_image_b64")
    source_bytes = base64.b64decode(source_b64, validate=True) if source_b64 else None

    png_bytes = get_pipeline().generate(source_image_bytes=source_bytes)
    return {"image_b64": base64.b64encode(png_bytes).decode()}


runpod.serverless.start({"handler": handler})
